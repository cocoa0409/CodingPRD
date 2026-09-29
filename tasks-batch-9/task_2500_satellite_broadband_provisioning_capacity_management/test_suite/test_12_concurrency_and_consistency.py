"""Optimistic concurrency on the two scarce ledgers, cascade discipline and the
immediate consistency model.

Every test builds its own precondition chain from PRD-declared endpoints, because
the server is restarted against an empty database before each one.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    acknowledge_disclosure,
    activate_subscription,
    add_active_subscription,
    assert_availability_projection,
    assert_beam,
    assert_beam_congestion_band,
    assert_cell_ledger_invariants,
    assert_service_cell,
    assert_subscription,
    authorize_subscription,
    cancel_order_payload,
    capacity_policy_payload,
    create_active_license,
    create_beam,
    create_order,
    create_plan,
    create_service_order_payload,
    create_subscriber,
    create_subscription_payload,
    get_beam,
    get_beam_version,
    get_cell,
    get_cell_version,
    get_order,
    get_subscriber,
    get_subscription,
    make_subscriber_headers,
    plan_change_payload,
    prepare_installed_terminal,
    set_clock,
    setup_active_subscription,
    setup_reserved_order,
    setup_topology,
    suspend_payload,
    usage_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
    write_capacity_policy,
)


# ═════════════════════ optimistic concurrency tokens ══════════════════════


class TestStaleServiceCellVersionAtActivation:
    """The activation token is a version check, not a capacity check."""

    def test_stale_cell_version_rejected_then_fresh_read_activates(
        self, api, agent_headers
    ):
        """A stale expected_service_cell_version is refused 412 even though a
        free slot exists, and the identical body with the re-read version wins.

        PRD §2.6: "Activating a subscription (`POST /satellite-broadband/subscriptions`) requires `expected_service_cell_version`, carrying the client's last observed `version` of the target `ServiceCell`."
        PRD §2.6: "If `expected_service_cell_version` does not equal the cell's current `version`, the activation is rejected with `ERR_STALE_SERVICE_CELL_VERSION` (HTTP 412) — even in cases where a fresh read would show free capacity and the very same request would then legitimately succeed."
        PRD §3.3: "The cell's `reserved_slot_count` increases by 1, its `free_slot_count` and `availability_state` are recomputed, and the cell's `version` increases by 1."
        PRD §3.5: "On the cell, `reserved_slot_count` drops by 1 while `committed_terminal_count` rises by 1 — the hold becomes a commitment — after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."

        Design: Corner/cross_cutting_layers/stale_service_cell_version_at_activation_rejected_then_a_fresh_read_succeeds
        """
        env = setup_topology(
            forward_capacity_mbps=1000,
            oversubscription_limit=4.0,
            max_active_terminals=2,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
        )
        cell_id = env["cell"]["id"]

        sub1 = create_subscriber(index=1, jurisdiction_code="US-CA")
        sub2 = create_subscriber(index=2, jurisdiction_code="US-CA")
        order1 = create_order(sub1["id"], cell_id, env["plan"]["id"])
        terminal1 = prepare_installed_terminal(sub1["id"], index=1)

        # The client's last observed cell version, taken before anybody else writes.
        cell_v1 = get_cell_version(cell_id)

        # A second order on the same cell advances the slot ledger while still
        # leaving one admitting slot (ceiling 2, two reservations, one of which is
        # the activating order's own and is therefore excluded at admission).
        order2 = create_order(sub2["id"], cell_id, env["plan"]["id"])

        stale = api.create_subscription(
            create_subscription_payload(
                service_order_id=order1["id"],
                terminal_id=terminal1["id"],
                expected_service_cell_version=cell_v1,
            ),
            agent_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_SERVICE_CELL_VERSION, 412)

        assert get_order(order1["id"])["order_state"] == "RESERVED", (
            "the refused activation must leave the consumed order RESERVED"
        )
        _rows, meta = validate_paginated(api.list_subscriptions(agent_headers))
        assert meta["total_count"] == 0, (
            f"a 412 must create no subscription, saw total_count={meta['total_count']}"
        )

        cell_v2 = validate_success(api.get_service_cell(cell_id, agent_headers))[
            "version"
        ]
        assert cell_v2 == cell_v1 + 1, (
            f"only the second order filing advanced the cell: expected "
            f"{cell_v1 + 1}, got {cell_v2}"
        )

        fresh = api.create_subscription(
            create_subscription_payload(
                service_order_id=order1["id"],
                terminal_id=terminal1["id"],
                expected_service_cell_version=cell_v2,
            ),
            agent_headers,
        )
        subscription = validate_success(fresh, 201)
        assert_subscription(subscription)
        assert subscription["service_state"] == "PENDING_ACTIVATION"
        assert subscription["service_cell_id"] == cell_id

        assert get_order(order1["id"])["order_state"] == "ACTIVATED"
        assert get_order(order2["id"])["order_state"] == "RESERVED"

        cell = get_cell(cell_id)
        assert_service_cell(cell)
        assert cell["committed_terminal_count"] == 1, (
            "the activated hold became a commitment"
        )
        assert cell["reserved_slot_count"] == 1, "the second order still holds a slot"
        assert cell["free_slot_count"] == 0
        assert cell["version"] == cell_v2 + 1, (
            f"the successful activation bumped the cell once: expected "
            f"{cell_v2 + 1}, got {cell['version']}"
        )


class TestStaleBeamVersionAtPlanChange:
    """The plan-change token guards the beam's sold-megabit ledger."""

    def test_stale_beam_version_rejected_then_re_read_change_applied(
        self, api, agent_headers, netops_headers
    ):
        """A plan change with a beam version another activation has moved past is
        refused 412, and the retry with the fresh token is applied in full.

        PRD §2.6: "Re-assigning a subscription's plan (`POST /satellite-broadband/subscriptions/{id}/plan-change`) requires `expected_beam_version`, carrying the client's last observed `version` of the `Beam` that serves the subscription's cell."
        PRD §2.6: "Another plan change, activation, termination or fair-use flip may have advanced the beam's `version` since the client computed its headroom. A mismatch is rejected with `ERR_STALE_BEAM_VERSION` (HTTP 412)."
        PRD §3.6: "On success the subscription's `service_plan_id` is replaced, its `effective_rate_mbps` is recomputed against the new plan, and its `priority_state` is re-evaluated against the new plan's `priority_data_gb` plus the beam's `deprioritization_grace_gb`."
        PRD §3.6: "The beam then recomputes `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state`, its `version` increases by 1, and every affected coverage cell recomputes `availability_state`."

        Design: Corner/cross_cutting_layers/stale_beam_version_at_plan_change_rejected_then_the_re_read_change_is_applied
        """
        env = setup_topology(
            forward_capacity_mbps=1000,
            oversubscription_limit=4.0,
            max_active_terminals=2,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
        )
        beam_id = env["beam"]["id"]
        cell_id = env["cell"]["id"]
        plan200_id = env["plan"]["id"]

        plan400 = create_plan(
            plan_code="PLAN-P1-400",
            committed_rate_mbps=400,
            priority_tier="PRIORITY_1",
            monthly_fee_cents=14900,
            priority_data_gb=200,
            deprioritized_rate_mbps=40,
            overage_rate_cents_per_gb=20,
        )

        sub1 = create_subscriber(index=1, jurisdiction_code="US-CA")
        sub2 = create_subscriber(index=2, jurisdiction_code="US-CA")

        order1 = create_order(sub1["id"], cell_id, plan200_id)
        terminal1 = prepare_installed_terminal(sub1["id"], index=1)
        sn1 = activate_subscription(
            order1["id"], terminal1["id"], service_cell_id=cell_id
        )
        acknowledge_disclosure(
            sn1["id"], sub1["id"], env["license"]["consumer_disclosure_version"]
        )
        authorize_subscription(sn1["id"], "FIXED")

        beam_v_stale = get_beam_version(beam_id)

        # A second activation on the same beam moves the sold-megabit ledger.
        order2 = create_order(sub2["id"], cell_id, plan200_id)
        terminal2 = prepare_installed_terminal(sub2["id"], index=2)
        activate_subscription(order2["id"], terminal2["id"], service_cell_id=cell_id)

        stale = api.change_plan(
            sn1["id"],
            plan_change_payload(
                new_service_plan_id=plan400["id"],
                expected_beam_version=beam_v_stale,
            ),
            agent_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_BEAM_VERSION, 412)

        assert get_subscription(sn1["id"])["service_plan_id"] == plan200_id, (
            "the refused plan change must leave the plan assignment alone"
        )
        beam_after_412 = get_beam(beam_id)
        assert beam_after_412["weighted_sold_mbps"] == pytest.approx(400, abs=0.001), (
            "two PRIORITY_1 subscriptions at 200 Mbps still sum to 400 after the 412"
        )

        beam_v_fresh = validate_success(api.get_beam(beam_id, netops_headers))["version"]
        assert beam_v_fresh == beam_v_stale + 1, (
            f"only the second activation advanced the beam: expected "
            f"{beam_v_stale + 1}, got {beam_v_fresh}"
        )

        fresh = api.change_plan(
            sn1["id"],
            plan_change_payload(
                new_service_plan_id=plan400["id"],
                expected_beam_version=beam_v_fresh,
            ),
            agent_headers,
        )
        changed = validate_success(fresh, 200)
        assert_subscription(changed)
        assert changed["service_plan_id"] == plan400["id"]
        assert changed["effective_rate_mbps"] == pytest.approx(400, abs=0.001), (
            "a PRIORITY subscription reports the new plan's committed rate"
        )
        assert changed["priority_state"] == "PRIORITY", (
            "no metered volume has been ingested, so nothing throttles"
        )

        beam = get_beam(beam_id)
        assert_beam(beam)
        assert beam["weighted_sold_mbps"] == pytest.approx(600, abs=0.001), (
            "400 Mbps upgraded plus the untouched 200 Mbps neighbour"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(0.6, abs=0.001)
        assert beam["capacity_state"] == "NORMAL"
        assert_beam_congestion_band(beam)
        assert beam["version"] == beam_v_fresh + 1, (
            f"the applied plan change bumped the beam once: expected "
            f"{beam_v_fresh + 1}, got {beam['version']}"
        )


class TestCapacityPolicyReplayedToken:
    """Replaying one beam version across two policy writes loses the second."""

    def test_second_policy_write_with_the_same_token_is_refused(
        self, api, netops_headers
    ):
        """The first policy write succeeds and bumps the beam; the second write
        replaying the same token is refused 412 and changes nothing.

        PRD §2.6: "Writing a beam's capacity policy (`POST /satellite-broadband/beams/{id}/capacity-policy`) likewise requires `expected_beam_version`."
        PRD §2.6: "A policy write supersedes the previous policy and has no state precondition to fail, so the version token is the only thing standing between a policy computed from an out-of-date congestion picture and the newer policy it would otherwise overwrite. A mismatch is rejected with `ERR_STALE_BEAM_VERSION` (HTTP 412)."
        PRD §3.2: "Writing the policy recomputes the beam's `oversubscription_ratio` and `capacity_state` against the new limit, re-evaluates every subscription on the beam against the new effective fair-use threshold, recomputes `availability_state` on every cell of the beam, and increases the beam's `version` by 1."

        Design: Corner/cross_cutting_layers/capacity_policy_written_twice_with_one_beam_version_is_rejected_the_second_time
        """
        set_clock(CLOCK_EPOCH)
        license_record = create_active_license()
        beam = create_beam(
            license_record["id"],
            forward_capacity_mbps=1000,
            oversubscription_limit=None,
        )
        beam_id = beam["id"]
        beam_v1 = beam["version"]
        assert beam["oversubscription_limit"] == pytest.approx(4.0, abs=0.001), (
            "an omitted oversubscription_limit defaults to 4.0"
        )

        first = api.write_capacity_policy(
            beam_id,
            capacity_policy_payload(
                expected_beam_version=beam_v1,
                oversubscription_limit=5.0,
                deprioritization_grace_gb=10,
            ),
            netops_headers,
        )
        written = validate_success(first, 200)
        assert written["oversubscription_limit"] == pytest.approx(5.0, abs=0.001)
        assert written["deprioritization_grace_gb"] == 10
        v_after_first = written["version"]
        assert v_after_first == beam_v1 + 1, (
            f"the accepted policy write bumps the beam once: expected "
            f"{beam_v1 + 1}, got {v_after_first}"
        )

        second = api.write_capacity_policy(
            beam_id,
            capacity_policy_payload(
                expected_beam_version=beam_v1,
                oversubscription_limit=6.0,
                deprioritization_grace_gb=20,
            ),
            netops_headers,
        )
        validate_error(second, ApiErrorId.ERR_STALE_BEAM_VERSION, 412)

        beam_now = get_beam(beam_id)
        assert beam_now["oversubscription_limit"] == pytest.approx(5.0, abs=0.001), (
            "the refused write must not blend into the stored policy"
        )
        assert beam_now["deprioritization_grace_gb"] == 10
        assert beam_now["version"] == v_after_first, (
            f"a refused token check performs no mutation: expected "
            f"{v_after_first}, got {beam_now['version']}"
        )


class TestBeamVersionCountsWritesOnly:
    """The beam's version is a write counter, not a request counter."""

    def test_writes_bump_the_beam_version_and_reads_never_do(
        self, api, agent_headers, netops_headers
    ):
        """Two policy writes and one activation each add exactly 1 to the beam's
        version, while the reads interleaved between them leave it untouched.

        PRD §2.5: "`updated_at` is refreshed to the logical-clock instant of the most recent mutation of that record, and `version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every mutation, including mutations a record suffers as the downstream hop of somebody else's cascade."
        PRD §2.8: "Recomputation of `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state` is triggered by subscription activation, network authorisation, suspension, resumption, termination, plan change, a fair-use deprioritisation flip, a fair-use restoration, a capacity-policy write, and the beam recompute step of a billing-cycle close. Every such recomputation increments the beam's `version`."
        PRD §3.5: "On the beam, `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state` are recomputed and the beam's `version` increases by 1."

        Design: Corner/cross_cutting_layers/beam_version_increments_on_every_write_and_never_on_a_read
        """
        env = setup_reserved_order(
            env=setup_topology(
                forward_capacity_mbps=1000,
                oversubscription_limit=4.0,
                max_active_terminals=1,
                committed_rate_mbps=200,
                priority_tier="PRIORITY_1",
            )
        )
        beam_id = env["beam"]["id"]
        cell_id = env["cell"]["id"]
        beam_v_created = env["beam"]["version"]

        v_read1 = validate_success(api.get_beam(beam_id, netops_headers))["version"]
        assert v_read1 == beam_v_created, (
            f"a read before any write agrees with the create response: expected "
            f"{beam_v_created}, got {v_read1}"
        )

        write1 = validate_success(
            api.write_capacity_policy(
                beam_id,
                capacity_policy_payload(
                    expected_beam_version=v_read1,
                    oversubscription_limit=5.0,
                    deprioritization_grace_gb=10,
                ),
                netops_headers,
            ),
            200,
        )
        v_write1 = write1["version"]

        write2 = validate_success(
            api.write_capacity_policy(
                beam_id,
                capacity_policy_payload(
                    expected_beam_version=v_write1,
                    oversubscription_limit=5.5,
                    deprioritization_grace_gb=20,
                ),
                netops_headers,
            ),
            200,
        )
        v_write2 = write2["version"]

        assert v_write1 == beam_v_created + 1, (
            f"first policy write: expected {beam_v_created + 1}, got {v_write1}"
        )
        assert v_write2 == beam_v_created + 2, (
            f"second policy write: expected {beam_v_created + 2}, got {v_write2}"
        )

        v_read2 = validate_success(api.get_beam(beam_id, agent_headers))["version"]
        assert v_read2 == v_write2, (
            f"reads never bump the counter: expected {v_write2}, got {v_read2}"
        )

        cell_v1 = validate_success(api.get_service_cell(cell_id, agent_headers))[
            "version"
        ]
        subscription = validate_success(
            api.create_subscription(
                create_subscription_payload(
                    service_order_id=env["order"]["id"],
                    terminal_id=env["terminal"]["id"],
                    expected_service_cell_version=cell_v1,
                ),
                agent_headers,
            ),
            201,
        )
        assert subscription["service_state"] == "PENDING_ACTIVATION"

        v_read3 = validate_success(api.get_beam(beam_id, netops_headers))["version"]
        assert v_read3 == beam_v_created + 3, (
            f"the activation's beam recompute is the third write: expected "
            f"{beam_v_created + 3}, got {v_read3}"
        )

        beam = get_beam(beam_id)
        assert beam["oversubscription_limit"] == pytest.approx(5.5, abs=0.001)
        assert beam["deprioritization_grace_gb"] == 20
        assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001)
        assert beam["oversubscription_ratio"] == pytest.approx(0.2, abs=0.001)


# ════════════════════════════ cascade discipline ══════════════════════════


class TestSuspensionCascade:
    """Suspension frees megabits, re-opens cells and rolls up the account."""

    def test_suspension_cascades_beam_then_cells_then_the_account(
        self, api, agent_headers
    ):
        """Suspending one of two subscriptions flips the beam out of SATURATED,
        re-opens the cell, suspends the account, and keeps the committed slot.

        PRD §3.9: "Hop one: the governing beam's `weighted_sold_mbps` drops by this subscription's weighted contribution, because a suspended subscription leaves the sold set entirely; the beam's `oversubscription_ratio` and `capacity_state` are recomputed and its `version` increases by 1."
        PRD §3.9: "Hop two, caused by hop one: every coverage cell of that beam recomputes `availability_state`."
        PRD §3.9: "What does **not** move is the cell's `committed_terminal_count` — a suspended subscription keeps its slot, so suspending a customer frees megabits but does not free a seat, and no waitlist promotion runs."
        PRD §3.9: "Finally, the owning subscriber's `account_state` moves to `SUSPENDED` when every one of that subscriber's non-terminal subscriptions is `SUSPENDED`."
        PRD §2.8: "It is `NORMAL` when the ratio is less than or equal to three quarters of `oversubscription_limit`; `CONSTRAINED` when the ratio is strictly greater than three quarters of the limit but still less than or equal to the limit itself; and `SATURATED` when the ratio is strictly greater than the limit."
        PRD §3.3: "It is `CLOSED` if the governing beam's `beam_state` is `SUSPENDED`, or the beam's `capacity_state` is `SATURATED`, or the cell's `max_active_terminals` is 0 — those three override everything below."

        Design: Corner/cross_cutting_layers/suspending_one_subscription_cascades_beam_then_cells_then_the_subscriber_account
        """
        env = setup_active_subscription(
            env=setup_topology(
                forward_capacity_mbps=200,
                oversubscription_limit=4.0,
                max_active_terminals=2,
                committed_rate_mbps=200,
                priority_tier="PRIORITY_1",
            )
        )
        beam_id = env["beam"]["id"]
        cell_id = env["cell"]["id"]
        second = add_active_subscription(env, subscriber_index=2, terminal_index=2)

        # Two PRIORITY_1 subscriptions at 200 Mbps on a 200 Mbps beam sit at a
        # ratio of 2.0; tightening the limit to 1.5 pushes the beam SATURATED.
        beam_v_pre = get_beam_version(beam_id)
        beam_saturated = write_capacity_policy(
            beam_id,
            oversubscription_limit=1.5,
            deprioritization_grace_gb=0,
            expected_beam_version=beam_v_pre,
        )
        beam_v_saturated = beam_saturated["version"]

        assert beam_saturated["capacity_state"] == "SATURATED", (
            "a ratio of 2.0 is strictly greater than the 1.5 limit"
        )
        assert get_cell(cell_id)["availability_state"] == "CLOSED", (
            "a SATURATED governing beam closes the cell outright"
        )

        suspended = validate_success(
            api.suspend_subscription(
                second["subscription"]["id"],
                suspend_payload(suspend_reason="customer request"),
                agent_headers,
            ),
            200,
        )
        assert suspended["service_state"] == "SUSPENDED"

        # Hop one: the suspended subscription leaves the sold set.
        beam = get_beam(beam_id)
        assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
            "only the still-ACTIVE 200 Mbps subscription contributes"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(1.0, abs=0.001)
        assert beam["capacity_state"] == "NORMAL", (
            "1.0 is at or below three quarters of the 1.5 limit"
        )
        assert_beam_congestion_band(beam)
        assert beam["version"] == beam_v_saturated + 1, (
            f"the suspension's beam recompute bumps once: expected "
            f"{beam_v_saturated + 1}, got {beam['version']}"
        )

        # Hop two: the cell re-opens off the back of the beam's new band.
        cell = get_cell(cell_id)
        assert cell["availability_state"] == "WAITLIST_ONLY", (
            "no free slot but a waitlist depth below the cap"
        )
        assert cell["free_slot_count"] == 0
        assert cell["waitlist_depth"] == 0
        assert cell["committed_terminal_count"] == 2, (
            "a suspended subscription keeps its cell slot"
        )
        assert_cell_ledger_invariants(cell)

        # Hop three: the account rolls up.
        assert get_subscriber(second["subscriber"]["id"])["account_state"] == "SUSPENDED"

        assert get_subscription(env["subscription"]["id"])["service_state"] == "ACTIVE", (
            "the untouched neighbour keeps its service"
        )
        assert get_subscriber(env["subscriber"]["id"])["account_state"] == "ACTIVE"


# ═══════════════════ threshold reset across a cycle close ═════════════════


class TestFairUseResetAcrossCycleClose:
    """The cumulative fair-use threshold is armed, fired, reset and fired again."""

    def test_cycle_close_resets_the_counter_so_the_threshold_fires_again(
        self, api, netops_headers
    ):
        """A 100 GB reading throttles, the ops run restores PRIORITY and re-pins
        the cycle index, and only a reading carrying the new index throttles again.

        PRD §3.6: "Its `counted` flag is computed at ingest as true exactly when the supplied `billing_cycle_index` equals the subscription's current `cycle_billing_index`, and false otherwise."
        PRD §3.6: "A reading with `counted` false is still persisted and still readable, but it **never** advances `cycle_priority_gb_used`, and it is invisible both to the deprioritisation threshold and to the overage calculation."
        PRD §3.6: "If the subscription's `priority_state` is `PRIORITY` and its `cycle_priority_gb_used` is greater than or equal to the effective threshold, the fair-use dimension flips `PRIORITY → DEPRIORITIZED`."
        PRD §3.6: "On the flip, `deprioritized_at` is stamped with the logical clock's current instant and `effective_rate_mbps` is replaced by the plan's `deprioritized_rate_mbps` — this is the field a subscriber-facing portal reads to explain the slowdown, and it holds the plan's `committed_rate_mbps` whenever `priority_state` is `PRIORITY` and the plan's `deprioritized_rate_mbps` whenever it is `DEPRIORITIZED`."
        PRD §3.9: "**Fair-use reset.** Every subscription on the beam's cells whose `service_state` is `ACTIVE` has its `cycle_priority_gb_used` reset to 0, has its `deprioritized_at` cleared to empty, and has its `cycle_billing_index` set to the beam's newly incremented `billing_cycle_index`. Those among them whose `priority_state` was `DEPRIORITIZED` move `DEPRIORITIZED → PRIORITY`, which is the only way a throttled subscription is ever restored."

        Design: Corner/cross_cutting_layers/billing_cycle_close_resets_the_fair_use_counter_so_the_threshold_can_fire_again
        """
        env = setup_active_subscription(
            env=setup_topology(
                forward_capacity_mbps=1000,
                oversubscription_limit=4.0,
                max_active_terminals=1,
                committed_rate_mbps=200,
                priority_tier="PRIORITY_1",
                priority_data_gb=100,
            )
        )
        beam_id = env["beam"]["id"]
        sn1_id = env["subscription"]["id"]

        # Arm and fire: 100 GB against a 100 GB allowance and a 0 GB beam grace.
        validate_success(
            api.create_usage_record(
                sn1_id, usage_record_payload(gb_used=100, billing_cycle_index=0), netops_headers
            ),
            201,
        )
        fired = get_subscription(sn1_id)
        assert fired["priority_state"] == "DEPRIORITIZED", (
            "landing exactly on the effective threshold throttles"
        )
        assert fired["cycle_priority_gb_used"] == pytest.approx(100, abs=0.001)
        assert fired["effective_rate_mbps"] == pytest.approx(20, abs=0.001)

        throttled_beam = get_beam(beam_id)
        assert throttled_beam["weighted_sold_mbps"] == pytest.approx(50, abs=0.001), (
            "a DEPRIORITIZED subscription weighs 0.25 of its 200 Mbps"
        )
        assert throttled_beam["oversubscription_ratio"] == pytest.approx(0.05, abs=0.001)

        report = validate_success(api.close_billing_cycle(beam_id, netops_headers), 200)
        assert report["billing_cycle_index"] == 1
        assert report["restored_subscription_count"] == 1

        restored = get_subscription(sn1_id)
        assert restored["priority_state"] == "PRIORITY", (
            "the fair-use reset is the only path back from DEPRIORITIZED"
        )
        assert restored["cycle_priority_gb_used"] == pytest.approx(0, abs=0.001)
        assert not restored["deprioritized_at"], (
            f"deprioritized_at must be cleared to empty, got "
            f"{restored['deprioritized_at']!r}"
        )
        assert restored["cycle_billing_index"] == 1
        assert restored["effective_rate_mbps"] == pytest.approx(200, abs=0.001)

        reset_beam = get_beam(beam_id)
        assert reset_beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001), (
            "the restored subscription re-enters at its full tier weight"
        )
        assert reset_beam["oversubscription_ratio"] == pytest.approx(0.2, abs=0.001)

        stale_reading = validate_success(
            api.create_usage_record(
                sn1_id, usage_record_payload(gb_used=100, billing_cycle_index=0), netops_headers
            ),
            201,
        )
        assert stale_reading["counted"] is False, (
            "index 0 no longer matches the subscription's cycle_billing_index of 1"
        )
        after_stale = get_subscription(sn1_id)
        assert after_stale["priority_state"] == "PRIORITY", (
            "an uncounted reading cannot re-arm the threshold"
        )
        assert after_stale["cycle_priority_gb_used"] == pytest.approx(0, abs=0.001)

        current_reading = validate_success(
            api.create_usage_record(
                sn1_id, usage_record_payload(gb_used=100, billing_cycle_index=1), netops_headers
            ),
            201,
        )
        assert current_reading["counted"] is True
        refired = get_subscription(sn1_id)
        assert refired["priority_state"] == "DEPRIORITIZED", (
            "the reset threshold fires again at exactly 100 GB in the new cycle"
        )
        assert refired["effective_rate_mbps"] == pytest.approx(20, abs=0.001)


# ═════════════════════ derived slot ledger reconciliation ═════════════════


class TestCellSlotLedgerReconciliation:
    """The cell's derived counters reconcile as a transfer, not a re-count."""

    def test_counters_reconcile_after_reserve_waitlist_and_cancel(
        self, api, agent_headers
    ):
        """Reserve, waitlist, then cancel: the promotion moves one unit from
        waitlist_depth to reserved_slot_count and the ledger stays balanced.

        PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."
        PRD §3.3: "The cell's `reserved_slot_count` increases by 1, its `free_slot_count` and `availability_state` are recomputed, and the cell's `version` increases by 1."
        PRD §3.3: "Its `waitlist_priority_score` is computed as described below, the subscriber's `account_state` moves from `PROSPECT` to `WAITLISTED`, the cell's `waitlist_depth` increases by 1, `availability_state` is recomputed, and the cell's `version` increases by 1."
        PRD §3.3: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`, clears `reservation_expires_at` back to empty, drops the cell's `reserved_slot_count` by 1 to release the slot, and then runs the promotion routine on that cell, so a cancellation typically hands the slot straight to the top-ranked waitlisted order and moves that order's subscriber from `WAITLISTED` to `PROSPECT`."
        PRD §3.3: "Otherwise it is `AVAILABLE` when the free slot figure is at least 1. Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

        Design: Corner/cross_cutting_layers/cell_slot_counters_reconcile_after_reserve_waitlist_and_cancel
        """
        env = setup_topology(
            forward_capacity_mbps=1000,
            oversubscription_limit=4.0,
            max_active_terminals=1,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
        )
        cell_id = env["cell"]["id"]
        plan_id = env["plan"]["id"]

        sub1 = create_subscriber(index=1, jurisdiction_code="US-CA")
        sub2 = create_subscriber(index=2, jurisdiction_code="US-CA")

        order1 = validate_success(
            api.create_service_order(
                create_service_order_payload(
                    subscriber_id=sub1["id"],
                    service_cell_id=cell_id,
                    requested_plan_id=plan_id,
                ),
                agent_headers,
            ),
            201,
        )
        order2 = validate_success(
            api.create_service_order(
                create_service_order_payload(
                    subscriber_id=sub2["id"],
                    service_cell_id=cell_id,
                    requested_plan_id=plan_id,
                ),
                agent_headers,
            ),
            201,
        )
        assert order1["order_state"] == "RESERVED", "the single slot admits the first"
        assert order2["order_state"] == "WAITLISTED", "the second finds no free slot"

        checkpoint_1 = get_cell(cell_id)
        assert checkpoint_1["reserved_slot_count"] == 1
        assert checkpoint_1["waitlist_depth"] == 1
        assert checkpoint_1["committed_terminal_count"] == 0
        assert checkpoint_1["free_slot_count"] == 0
        assert checkpoint_1["availability_state"] == "WAITLIST_ONLY"
        assert_cell_ledger_invariants(checkpoint_1)

        projection = validate_success(
            api.get_cell_availability(cell_id, agent_headers), 200
        )
        assert_availability_projection(projection)
        assert projection["advertised_free_slot_count"] == 0, (
            "the availability read agrees with the persisted ledger"
        )

        first_cancel = validate_success(
            api.cancel_service_order(
                order1["id"], cancel_order_payload(cancel_reason="changed mind"), agent_headers
            ),
            200,
        )
        assert first_cancel["order_state"] == "CANCELLED"
        assert get_order(order2["id"])["order_state"] == "RESERVED", (
            "the released slot is handed to the top-ranked waitlisted order"
        )

        checkpoint_2 = get_cell(cell_id)
        assert checkpoint_2["reserved_slot_count"] == 1, (
            "the promotion transferred the hold rather than dropping it"
        )
        assert checkpoint_2["waitlist_depth"] == 0
        assert checkpoint_2["free_slot_count"] == 0
        assert checkpoint_2["availability_state"] == "WAITLIST_ONLY"
        assert_cell_ledger_invariants(checkpoint_2)
        assert get_subscriber(sub2["id"])["account_state"] == "PROSPECT", (
            "a promoted order's subscriber leaves WAITLISTED"
        )

        second_cancel = validate_success(
            api.cancel_service_order(
                order2["id"],
                cancel_order_payload(cancel_reason="changed mind too"),
                make_subscriber_headers(sub2["id"]),
            ),
            200,
        )
        assert second_cancel["order_state"] == "CANCELLED"

        checkpoint_3 = get_cell(cell_id)
        assert checkpoint_3["reserved_slot_count"] == 0
        assert checkpoint_3["waitlist_depth"] == 0
        assert checkpoint_3["committed_terminal_count"] == 0
        assert checkpoint_3["free_slot_count"] == 1
        assert checkpoint_3["availability_state"] == "AVAILABLE"
        assert_cell_ledger_invariants(checkpoint_3)

        for label, snapshot in (
            ("after the two creates", checkpoint_1),
            ("after the first cancel", checkpoint_2),
            ("after the second cancel", checkpoint_3),
        ):
            total = (
                snapshot["reserved_slot_count"]
                + snapshot["committed_terminal_count"]
                + snapshot["free_slot_count"]
            )
            assert total == snapshot["max_active_terminals"] == 1, (
                f"{label}: reserved + committed + free must reconcile to the "
                f"ceiling of 1, got {total}"
            )


# ══════════════════════════ immediate consistency ═════════════════════════


class TestActivationIsImmediatelyConsistent:
    """One write, zero waiting: no sweep and no re-read are needed."""

    def test_activation_side_effects_visible_in_response_and_immediate_reads(
        self, api, agent_headers, netops_headers
    ):
        """The activation response already carries every pinned derived field, and
        reads issued straight afterwards show the cell and beam fully recomputed.

        PRD §2.9: "Cascades are always fully applied before the response is written — the consistency model is immediate, and there is no deferred or eventual settlement anywhere in this platform."
        PRD §3.5: "On success a subscription record is created and lands in four independent state dimensions at once: `service_state` `PENDING_ACTIVATION`, `authorization_state` `UNAUTHORIZED`, `priority_state` `PRIORITY` and `disclosure_ack_state` `PENDING_ACK`."
        PRD §3.5: "The subscription's `disclosure_version_issued` takes the `consumer_disclosure_version` of the governing licence — the licence the beam radiates under, per §2.10 — and `disclosure_ack_deadline_at` is set to the activation instant plus 14 days."
        PRD §3.5: "Its `activated_at` is stamped with the logical clock's current instant, its `cycle_priority_gb_used` starts at 0, its `cycle_charge_cents` starts at 0, its `effective_rate_mbps` starts as the plan's `committed_rate_mbps`, and its `deauthorized_by_license_id`, `deprioritized_at`, `terminated_at` and `suspension_reason` all start empty."
        PRD §3.5: "The consumed order moves `RESERVED → ACTIVATED`, which is terminal for it. The subscriber's `account_state` moves to `ACTIVE`."
        PRD §3.5: "On the cell, `reserved_slot_count` drops by 1 while `committed_terminal_count` rises by 1 — the hold becomes a commitment — after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."
        PRD §3.5: "On the beam, `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state` are recomputed and the beam's `version` increases by 1."

        Design: Corner/consistency_model/activation_side_effects_are_visible_in_the_same_response_and_an_immediate_read
        """
        env = setup_reserved_order(
            env=setup_topology(
                forward_capacity_mbps=1000,
                oversubscription_limit=4.0,
                max_active_terminals=1,
                committed_rate_mbps=200,
                priority_tier="PRIORITY_1",
                clock=CLOCK_EPOCH,
            )
        )
        beam_id = env["beam"]["id"]
        cell_id = env["cell"]["id"]
        cell_v1 = get_cell_version(cell_id)

        subscription = validate_success(
            api.create_subscription(
                create_subscription_payload(
                    service_order_id=env["order"]["id"],
                    terminal_id=env["terminal"]["id"],
                    expected_service_cell_version=cell_v1,
                ),
                agent_headers,
            ),
            201,
        )
        assert_subscription(subscription)

        # Everything below is read off the activation response itself.
        assert subscription["service_state"] == "PENDING_ACTIVATION"
        assert subscription["authorization_state"] == "UNAUTHORIZED"
        assert subscription["priority_state"] == "PRIORITY"
        assert subscription["disclosure_ack_state"] == "PENDING_ACK"
        assert subscription["disclosure_version_issued"] == "CD-2026.1", (
            "the governing licence's disclosure version is pinned in this response"
        )
        assert subscription["disclosure_ack_deadline_at"] == "2026-08-15T00:00:00.000Z", (
            "the activation instant plus 14 days, with no later fill-in"
        )
        assert subscription["activated_at"] == "2026-08-01T00:00:00.000Z"
        assert subscription["cycle_billing_index"] == 0, (
            "copied from the beam's current billing_cycle_index"
        )
        assert subscription["cycle_priority_gb_used"] == pytest.approx(0, abs=0.001)
        assert subscription["cycle_charge_cents"] == 0
        assert subscription["effective_rate_mbps"] == pytest.approx(200, abs=0.001)

        # And immediately afterwards, with no clock advance and no sweep.
        cell = validate_success(api.get_service_cell(cell_id, agent_headers), 200)
        assert cell["free_slot_count"] == 0
        assert cell["committed_terminal_count"] == 1
        assert cell["reserved_slot_count"] == 0, "the hold became a commitment"
        assert cell["availability_state"] == "WAITLIST_ONLY"
        assert_cell_ledger_invariants(cell)

        beam = validate_success(api.get_beam(beam_id, netops_headers), 200)
        assert beam["weighted_sold_mbps"] == pytest.approx(200, abs=0.001)
        assert beam["oversubscription_ratio"] == pytest.approx(0.2, abs=0.001)
        assert beam["capacity_state"] == "NORMAL"
        assert_beam_congestion_band(beam)

        account = validate_success(
            api.get_subscriber(env["subscriber"]["id"], agent_headers), 200
        )
        assert account["account_state"] == "ACTIVE"
        assert get_order(env["order"]["id"])["order_state"] == "ACTIVATED"
