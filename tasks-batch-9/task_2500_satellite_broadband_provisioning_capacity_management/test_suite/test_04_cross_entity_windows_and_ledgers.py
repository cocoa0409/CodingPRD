"""Cross-entity state dependencies, window arithmetic and ledger conservation.

Three families of behaviour live in this module:

* a write on one entity refused because a *different* entity sits in the wrong
  state (activation against a terminal that is not `INSTALLED`, installation
  against a failing sky survey, in-motion roaming against a licence that
  forbids in-motion operation);
* the two different interval rules the platform uses — half-open and buffer
  free for impairment events on a beam, closed plus a 24-hour cooldown for
  roaming windows on a subscription;
* two conserved quantities — integer cell slots and money in cents — checked
  across an action and its compensating action.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_cell_ledger_invariants,
    assert_subscriber_ledger_invariants,
    create_outage_event_payload,
    create_roaming_authorization_payload,
    create_subscriber,
    create_subscription_payload,
    credit_decision_payload,
    deliver_terminal,
    get_cell_version,
    install_terminal,
    make_compliance_officer_headers,
    make_provisioning_agent_headers,
    make_subscriber_headers,
    obstruction_scan_payload,
    open_outage_event,
    request_roaming,
    request_roaming_info,
    reset_clock_to_epoch,
    resolve_outage_event,
    roaming_decision_payload,
    scan_terminal,
    set_clock,
    setup_active_subscription,
    setup_approved_roaming_window,
    setup_reserved_order,
    setup_topology,
    setup_waitlisted_order,
    ship_terminal,
    suspend_subscription,
    terminate_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─────────────────────────────────────────────────────────────────────────────
# Subscription depends on Terminal: activation needs an INSTALLED unit
# ─────────────────────────────────────────────────────────────────────────────


class TestActivationDependsOnTerminalState:
    """The order side of an activation can be perfectly legal and the write still
    refused, because the bound terminal has not reached `INSTALLED`."""

    @pytest.mark.parametrize(
        "deliver_first,expected_terminal_state",
        [
            (True, "DELIVERED"),
            (False, "SHIPPED"),
        ],
        ids=["terminal_delivered", "terminal_still_shipped"],
    )
    def test_activation_refused_while_terminal_has_not_reached_installed(
        self, api, agent_headers, deliver_first, expected_terminal_state
    ):
        """A RESERVED, unexpired order cannot be activated onto a terminal that is
        merely delivered (or still in transit).

        PRD §3.5: "The named terminal's `terminal_state` must be `INSTALLED`, or the attempt is refused with `ERR_TERMINAL_NOT_INSTALLED`."
        PRD §3.4: "Confirming delivery moves the unit `SHIPPED → DELIVERED` and increases the terminal's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/activation_rejected_when_the_bound_terminal_is_only_delivered
        """
        env = setup_reserved_order(install_terminal_too=False)
        terminal_id = env["terminal"]["id"]
        if deliver_first:
            deliver_terminal(terminal_id)

        cell_version = get_cell_version(env["cell"]["id"])
        response = api.create_subscription(
            create_subscription_payload(
                service_order_id=env["order"]["id"],
                terminal_id=terminal_id,
                expected_service_cell_version=cell_version,
            ),
            agent_headers,
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_NOT_INSTALLED, expected_status=409)

        terminal = validate_success(api.get_terminal(terminal_id, agent_headers))
        assert terminal["terminal_state"] == expected_terminal_state, (
            "a refused activation must not move the terminal's logistics state, expected "
            f"{expected_terminal_state}, got {terminal['terminal_state']}"
        )
        assert not terminal.get("last_scan_verdict"), (
            "no sky survey was recorded, so last_scan_verdict must stay empty, got "
            f"{terminal.get('last_scan_verdict')!r}"
        )

        order = validate_success(api.get_service_order(env["order"]["id"], agent_headers))
        assert order["order_state"] == "RESERVED", (
            f"the order keeps its reservation after the refusal, got {order['order_state']}"
        )

    def test_refused_activation_leaves_the_cell_and_beam_ledgers_untouched(
        self, api, agent_headers, netops_headers
    ):
        """The hold is still a hold: nothing becomes a commitment and no megabits
        are sold when the activation is refused for the terminal's state.

        PRD §3.5: "The named terminal's `terminal_state` must be `INSTALLED`, or the attempt is refused with `ERR_TERMINAL_NOT_INSTALLED`."
        PRD §3.5: "On the cell, `reserved_slot_count` drops by 1 while `committed_terminal_count` rises by 1 — the hold becomes a commitment — after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."
        PRD §2.8: "Only subscriptions whose `service_state` is `PENDING_ACTIVATION` or `ACTIVE` contribute to that sold total."

        Design: Difficulty/cross_entity_state_dependency/activation_rejected_when_the_bound_terminal_is_only_delivered
        """
        env = setup_reserved_order(install_terminal_too=False)
        deliver_terminal(env["terminal"]["id"])

        cell_version = get_cell_version(env["cell"]["id"])
        response = api.create_subscription(
            create_subscription_payload(
                service_order_id=env["order"]["id"],
                terminal_id=env["terminal"]["id"],
                expected_service_cell_version=cell_version,
            ),
            agent_headers,
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_NOT_INSTALLED, expected_status=409)

        cell = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        assert cell["committed_terminal_count"] == 0, (
            f"no commitment may be booked by a refused activation, got "
            f"{cell['committed_terminal_count']}"
        )
        assert cell["reserved_slot_count"] == 1, (
            f"the reservation must survive the refusal, got {cell['reserved_slot_count']}"
        )
        assert_cell_ledger_invariants(cell)

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert float(beam["weighted_sold_mbps"]) == pytest.approx(0, abs=0.001), (
            f"no subscription exists, so no megabits are sold, got {beam['weighted_sold_mbps']}"
        )

    def test_activation_admitted_once_the_same_terminal_is_installed(self, api, agent_headers):
        """Surveying and installing the very same terminal removes the only
        obstacle, and the identical activation then succeeds.

        PRD §3.5: "The named terminal's `terminal_state` must be `INSTALLED`, or the attempt is refused with `ERR_TERMINAL_NOT_INSTALLED`."
        PRD §3.5: "On success a subscription record is created and lands in four independent state dimensions at once: `service_state` `PENDING_ACTIVATION`, `authorization_state` `UNAUTHORIZED`, `priority_state` `PRIORITY` and `disclosure_ack_state` `PENDING_ACK`."

        Design: Difficulty/cross_entity_state_dependency/activation_rejected_when_the_bound_terminal_is_only_delivered
        """
        env = setup_reserved_order(install_terminal_too=False)
        terminal_id = env["terminal"]["id"]
        deliver_terminal(terminal_id)

        refused = api.create_subscription(
            create_subscription_payload(
                service_order_id=env["order"]["id"],
                terminal_id=terminal_id,
                expected_service_cell_version=get_cell_version(env["cell"]["id"]),
            ),
            agent_headers,
        )
        validate_error(refused, ApiErrorId.ERR_TERMINAL_NOT_INSTALLED, expected_status=409)

        scan_terminal(terminal_id, env["subscriber"]["id"])
        installed = install_terminal(terminal_id, env["subscriber"]["id"])
        assert installed["terminal_state"] == "INSTALLED", (
            f"setup expected an installed terminal, got {installed['terminal_state']}"
        )

        accepted = api.create_subscription(
            create_subscription_payload(
                service_order_id=env["order"]["id"],
                terminal_id=terminal_id,
                expected_service_cell_version=get_cell_version(env["cell"]["id"]),
            ),
            agent_headers,
        )
        subscription = validate_success(accepted, expected_status=201)
        assert subscription["service_state"] == "PENDING_ACTIVATION", (
            f"a new subscription lands PENDING_ACTIVATION, got {subscription['service_state']}"
        )
        assert subscription["authorization_state"] == "UNAUTHORIZED", (
            f"a new subscription lands UNAUTHORIZED, got {subscription['authorization_state']}"
        )
        assert subscription["priority_state"] == "PRIORITY", (
            f"a new subscription lands PRIORITY, got {subscription['priority_state']}"
        )
        assert subscription["disclosure_ack_state"] == "PENDING_ACK", (
            f"a new subscription lands PENDING_ACK, got {subscription['disclosure_ack_state']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Terminal depends on ObstructionScan: the newest qualifying verdict gates install
# ─────────────────────────────────────────────────────────────────────────────


class TestInstallDependsOnObstructionScanVerdict:
    """Installation reads a different entity — the sky survey — and a `FAIL`
    verdict blocks the transition even from the legal from-state `DELIVERED`."""

    def _delivered_terminal(self):
        reset_clock_to_epoch()
        subscriber = create_subscriber(index=1)
        terminal = ship_terminal(subscriber["id"], index=1)
        deliver_terminal(terminal["id"])
        return subscriber, terminal

    def test_install_refused_when_the_qualifying_scan_verdict_is_fail(self, api, agent_headers):
        """17 blocked samples of 200 is 8.50 percent, above the 8.00 ceiling, so
        the verdict is `FAIL` and the install is refused.

        PRD §3.4: "The survey computes `obstruction_pct` as one hundred times the obstructed count divided by the total count, rounded half up to 2 decimal places, and derives a `scan_verdict` from three bands: `PASS` when `obstruction_pct` is at most 2.00, `MARGINAL` when it is strictly greater than 2.00 and at most 8.00, and `FAIL` when it is strictly greater than 8.00."
        PRD §3.4: "Recording a survey immediately refreshes the terminal's `last_scan_verdict` to the newly computed verdict, since a survey taken now is by construction newer than both the terminal's `created_at` and any `ownership_changed_at`."
        PRD §3.4: "If a qualifying survey exists but its verdict is `FAIL`, the install is refused with `ERR_OBSTRUCTION_VERDICT_FAIL`; a verdict of `PASS` or of `MARGINAL` both admit."

        Design: Difficulty/cross_entity_state_dependency/install_rejected_when_newest_qualifying_obstruction_scan_verdict_is_fail
        """
        subscriber, terminal = self._delivered_terminal()
        subscriber_headers = make_subscriber_headers(subscriber["id"])

        scan = validate_success(
            api.create_obstruction_scan(
                terminal["id"], obstruction_scan_payload(17, 200), subscriber_headers
            ),
            expected_status=201,
        )
        assert float(scan["obstruction_pct"]) == pytest.approx(8.50, abs=0.001), (
            f"17 of 200 samples is 8.50 percent, got {scan['obstruction_pct']}"
        )
        assert scan["scan_verdict"] == "FAIL", (
            f"8.50 percent is strictly above 8.00, so the verdict is FAIL, got "
            f"{scan['scan_verdict']}"
        )

        response = api.install_terminal(terminal["id"], subscriber_headers)
        validate_error(response, ApiErrorId.ERR_OBSTRUCTION_VERDICT_FAIL, expected_status=422)

        after = validate_success(api.get_terminal(terminal["id"], agent_headers))
        assert after["last_scan_verdict"] == "FAIL", (
            f"the terminal carries the newly computed verdict, got {after['last_scan_verdict']}"
        )
        assert after["terminal_state"] == "DELIVERED", (
            f"a refused install leaves the unit in DELIVERED, got {after['terminal_state']}"
        )
        assert not after.get("installed_at"), (
            f"installed_at is stamped only on success, got {after.get('installed_at')!r}"
        )

    @pytest.mark.parametrize(
        "obstructed,total,expected_verdict",
        [
            (4, 200, "PASS"),
            (16, 200, "MARGINAL"),
        ],
        ids=["pass_at_2_00_percent", "marginal_at_8_00_percent"],
    )
    def test_install_admitted_on_pass_and_on_marginal(
        self, api, obstructed, total, expected_verdict
    ):
        """Both admitting bands are checked at their upper boundary: 2.00 percent
        is still `PASS` and 8.00 percent is still `MARGINAL`, and either installs.

        PRD §3.4: "The survey computes `obstruction_pct` as one hundred times the obstructed count divided by the total count, rounded half up to 2 decimal places, and derives a `scan_verdict` from three bands: `PASS` when `obstruction_pct` is at most 2.00, `MARGINAL` when it is strictly greater than 2.00 and at most 8.00, and `FAIL` when it is strictly greater than 8.00."
        PRD §3.4: "If a qualifying survey exists but its verdict is `FAIL`, the install is refused with `ERR_OBSTRUCTION_VERDICT_FAIL`; a verdict of `PASS` or of `MARGINAL` both admit."
        PRD §3.4: "On success, `installed_at` is stamped with the logical clock's current instant."

        Design: Difficulty/cross_entity_state_dependency/install_rejected_when_newest_qualifying_obstruction_scan_verdict_is_fail
        """
        subscriber, terminal = self._delivered_terminal()
        subscriber_headers = make_subscriber_headers(subscriber["id"])

        scan = validate_success(
            api.create_obstruction_scan(
                terminal["id"], obstruction_scan_payload(obstructed, total), subscriber_headers
            ),
            expected_status=201,
        )
        assert scan["scan_verdict"] == expected_verdict, (
            f"{obstructed} of {total} samples should band as {expected_verdict}, got "
            f"{scan['scan_verdict']}"
        )

        installed = validate_success(api.install_terminal(terminal["id"], subscriber_headers))
        assert installed["terminal_state"] == "INSTALLED", (
            f"a {expected_verdict} verdict admits the install, got {installed['terminal_state']}"
        )
        assert installed["installed_at"], "installed_at must be stamped on a successful install"

    @pytest.mark.parametrize(
        "first,second,expect_install_refused",
        [
            ((1, 200), (17, 200), True),
            ((17, 200), (1, 200), False),
        ],
        ids=["pass_then_fail_blocks", "fail_then_pass_admits"],
    )
    def test_the_newest_recorded_survey_is_the_one_that_gates_the_install(
        self, api, agent_headers, first, second, expect_install_refused
    ):
        """Two surveys on the same unit: the verdict the install reads is the one
        the most recent recording wrote, in either direction.

        PRD §3.4: "Recording a survey immediately refreshes the terminal's `last_scan_verdict` to the newly computed verdict, since a survey taken now is by construction newer than both the terminal's `created_at` and any `ownership_changed_at`."
        PRD §3.4: "If a qualifying survey exists but its verdict is `FAIL`, the install is refused with `ERR_OBSTRUCTION_VERDICT_FAIL`; a verdict of `PASS` or of `MARGINAL` both admit."

        Design: Difficulty/cross_entity_state_dependency/install_rejected_when_newest_qualifying_obstruction_scan_verdict_is_fail
        """
        subscriber, terminal = self._delivered_terminal()
        subscriber_headers = make_subscriber_headers(subscriber["id"])

        for obstructed, total in (first, second):
            validate_success(
                api.create_obstruction_scan(
                    terminal["id"], obstruction_scan_payload(obstructed, total), subscriber_headers
                ),
                expected_status=201,
            )

        expected_verdict = "FAIL" if expect_install_refused else "PASS"
        current = validate_success(api.get_terminal(terminal["id"], agent_headers))
        assert current["last_scan_verdict"] == expected_verdict, (
            f"the last recorded survey should leave last_scan_verdict {expected_verdict}, got "
            f"{current['last_scan_verdict']}"
        )

        response = api.install_terminal(terminal["id"], subscriber_headers)
        if expect_install_refused:
            validate_error(response, ApiErrorId.ERR_OBSTRUCTION_VERDICT_FAIL, expected_status=422)
            after = validate_success(api.get_terminal(terminal["id"], agent_headers))
            assert after["terminal_state"] == "DELIVERED", (
                f"a FAIL verdict blocks the install, got {after['terminal_state']}"
            )
        else:
            installed = validate_success(response)
            assert installed["terminal_state"] == "INSTALLED", (
                f"a PASS verdict admits the install, got {installed['terminal_state']}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# RoamingAuthorization depends on SpectrumLicense: in-motion permission
# ─────────────────────────────────────────────────────────────────────────────


class TestInMotionApprovalDependsOnGoverningLicense:
    """The plan may allow in-motion operation and the request may therefore be
    raised, yet the approval still fails on the governing licence's own flag."""

    def test_in_motion_approval_refused_when_the_governing_license_forbids_it(
        self, api, agent_headers, compliance_headers
    ):
        """The licence for the target jurisdiction carries `in_motion_permitted`
        false, so the compliance decision is refused and nothing moves.

        PRD §3.7: "For `mode` `IN_MOTION`, approval additionally requires the selected licence's `in_motion_permitted` to be true and the subscription's plan `in_motion_allowed` to be true, refusing otherwise with `ERR_IN_MOTION_NOT_PERMITTED`."
        PRD §3.7: "A newly raised request is born in `auth_state` `REQUESTED` with `info_round_count` at 0, and with `governing_license_id`, `decision_note` and `revoked_reason` all empty."

        Design: Difficulty/cross_entity_state_dependency/in_motion_roaming_approval_rejected_when_the_governing_license_forbids_in_motion
        """
        env = setup_active_subscription(in_motion_permitted=False)
        request = request_roaming(
            env["subscription"]["id"],
            subscriber_id=env["subscriber"]["id"],
            mode="IN_MOTION",
            target_jurisdiction_code="US-CA",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-05T00:00:00Z",
        )
        assert request["auth_state"] == "REQUESTED", (
            f"the plan allows in-motion so the request itself is accepted, got "
            f"{request['auth_state']}"
        )

        response = api.decide_roaming_authorization(
            request["id"],
            roaming_decision_payload("APPROVE", decision_note="vessel documentation complete"),
            compliance_headers,
        )
        validate_error(response, ApiErrorId.ERR_IN_MOTION_NOT_PERMITTED, expected_status=422)

        after = validate_success(api.get_roaming_authorization(request["id"], compliance_headers))
        assert after["auth_state"] == "REQUESTED", (
            f"a refused decision leaves the review in REQUESTED, got {after['auth_state']}"
        )
        assert not after.get("governing_license_id"), (
            "governing_license_id is stamped only by a successful approval, got "
            f"{after.get('governing_license_id')!r}"
        )

        subscription = validate_success(
            api.get_subscription(env["subscription"]["id"], agent_headers)
        )
        assert subscription["authorization_state"] == "AUTHORIZED_FIXED", (
            "the subscription's authorisation dimension must not be lifted, got "
            f"{subscription['authorization_state']}"
        )

        license_record = validate_success(
            api.get_spectrum_license(env["license"]["id"], compliance_headers)
        )
        assert license_record["in_motion_permitted"] is False, (
            "setup expected a licence that forbids in-motion operation, got "
            f"{license_record['in_motion_permitted']!r}"
        )

    def test_in_motion_approval_lifts_the_subscription_when_the_license_permits_it(
        self, api, agent_headers, compliance_headers
    ):
        """The same request under a licence whose `in_motion_permitted` is true is
        approved, stamps the governing licence and lifts the authorisation.

        PRD §3.7: "For `mode` `IN_MOTION`, approval additionally requires the selected licence's `in_motion_permitted` to be true and the subscription's plan `in_motion_allowed` to be true, refusing otherwise with `ERR_IN_MOTION_NOT_PERMITTED`."
        PRD §3.7: "On success the subscription's authorisation dimension is lifted `AUTHORIZED_FIXED → AUTHORIZED_IN_MOTION`."
        PRD §3.7: "**Approval** moves the record `REQUESTED → APPROVED`, stores the supplied note in `decision_note`, and stamps `governing_license_id` with the licence selected by the ranking rule of §2.10 — candidates whose `jurisdiction_code` equals `target_jurisdiction_code` and which are both `ACTIVE` and `COORDINATED`, ranked by `expires_at` descending with `created_at` ascending as the tie-break."

        Design: Difficulty/cross_entity_state_dependency/in_motion_roaming_approval_rejected_when_the_governing_license_forbids_in_motion
        """
        env = setup_active_subscription(in_motion_permitted=True)
        request = request_roaming(
            env["subscription"]["id"],
            subscriber_id=env["subscriber"]["id"],
            mode="IN_MOTION",
            target_jurisdiction_code="US-CA",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-05T00:00:00Z",
        )

        decided = validate_success(
            api.decide_roaming_authorization(
                request["id"],
                roaming_decision_payload("APPROVE", decision_note="vessel documentation complete"),
                compliance_headers,
            )
        )
        assert decided["auth_state"] == "APPROVED", (
            f"a permitted in-motion request is approved, got {decided['auth_state']}"
        )
        assert decided["governing_license_id"] == env["license"]["id"], (
            "the only candidate licence for US-CA must be stamped as governing, got "
            f"{decided['governing_license_id']!r}"
        )

        subscription = validate_success(
            api.get_subscription(env["subscription"]["id"], agent_headers)
        )
        assert subscription["authorization_state"] == "AUTHORIZED_IN_MOTION", (
            "an approved IN_MOTION grant lifts AUTHORIZED_FIXED to AUTHORIZED_IN_MOTION, got "
            f"{subscription['authorization_state']}"
        )

    def test_roam_temporary_approval_is_unaffected_by_the_in_motion_flag(
        self, api, agent_headers, compliance_headers
    ):
        """The licence flag gates the `IN_MOTION` mode only: a temporary roaming
        window is approved under the very same licence that forbids in-motion.

        PRD §3.7: "For `mode` `IN_MOTION`, approval additionally requires the selected licence's `in_motion_permitted` to be true and the subscription's plan `in_motion_allowed` to be true, refusing otherwise with `ERR_IN_MOTION_NOT_PERMITTED`."
        PRD §3.7: "For `mode` `ROAM_TEMPORARY`, approval changes nothing beyond the authorisation record itself."
        PRD §3.7: "No cell counter moves, no beam is recomputed, and the subscription's dimensions are untouched."

        Design: Difficulty/cross_entity_state_dependency/in_motion_roaming_approval_rejected_when_the_governing_license_forbids_in_motion
        """
        env = setup_active_subscription(in_motion_permitted=False)
        request = request_roaming(
            env["subscription"]["id"],
            subscriber_id=env["subscriber"]["id"],
            mode="ROAM_TEMPORARY",
            target_jurisdiction_code="US-CA",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-05T00:00:00Z",
        )

        decided = validate_success(
            api.decide_roaming_authorization(
                request["id"],
                roaming_decision_payload("APPROVE", decision_note="itinerary verified"),
                compliance_headers,
            )
        )
        assert decided["auth_state"] == "APPROVED", (
            f"a ROAM_TEMPORARY window needs no in-motion permission, got {decided['auth_state']}"
        )
        assert decided["governing_license_id"] == env["license"]["id"], (
            f"the US-CA licence governs the window, got {decided['governing_license_id']!r}"
        )

        subscription = validate_success(
            api.get_subscription(env["subscription"]["id"], agent_headers)
        )
        assert subscription["authorization_state"] == "AUTHORIZED_FIXED", (
            "ROAM_TEMPORARY leaves the subscription's dimensions untouched, got "
            f"{subscription['authorization_state']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Impairment windows on a beam: half-open, no buffer
# ─────────────────────────────────────────────────────────────────────────────


class TestOutageWindowHalfOpenArithmetic:
    """A resolved event owns `[started_at, ended_at)`. The right endpoint is free
    for the next event; anything strictly inside is not."""

    def _beam_with_resolved_event(self):
        """Topology plus one RESOLVED EQUIPMENT_FAILURE window [08-05 00:00, 08-05 04:00)."""
        env = setup_topology()
        set_clock("2026-08-11T00:00:00Z")
        event = open_outage_event(
            env["beam"]["id"],
            cause="EQUIPMENT_FAILURE",
            severity="FULL_OUTAGE",
            started_at="2026-08-05T00:00:00Z",
        )
        env["event"] = resolve_outage_event(event["id"], "2026-08-05T04:00:00Z")
        return env

    def test_new_event_starting_exactly_at_the_prior_ended_at_is_accepted(
        self, api, netops_headers
    ):
        """Back-to-back impairments are legitimate because the prior interval
        excludes its right endpoint.

        PRD §3.8: "A resolved event covers the span from its `started_at` inclusive up to its `ended_at` exclusive; an open event covers everything from its `started_at` onward with no upper bound."
        PRD §3.8: "Because the upper bound is exclusive, a new event whose `started_at` is exactly another event's `ended_at` is accepted — back-to-back impairments are legitimate."
        PRD §3.8: "Resolution moves the event `OPEN → RESOLVED` and computes `outage_minutes` as the number of whole minutes between `started_at` and `ended_at`, discarding any partial minute."
        PRD §3.8: "The event is born in `event_state` `OPEN` with no `ended_at`, no `outage_minutes`, no `credit_eligible` determination yet, and `generated_credit_count` at 0."

        Design: Difficulty/resource_temporal_overlap/outage_window_half_open_adjacency_accepted_while_interior_start_collides
        """
        env = self._beam_with_resolved_event()
        assert env["event"]["outage_minutes"] == 240, (
            f"[00:00, 04:00) is 240 whole minutes, got {env['event']['outage_minutes']}"
        )

        adjacent = validate_success(
            api.create_outage_event(
                create_outage_event_payload(
                    beam_id=env["beam"]["id"],
                    cause="EQUIPMENT_FAILURE",
                    severity="FULL_OUTAGE",
                    started_at="2026-08-05T04:00:00Z",
                ),
                netops_headers,
            ),
            expected_status=201,
        )
        assert adjacent["event_state"] == "OPEN", (
            f"a freshly opened event is OPEN, got {adjacent['event_state']}"
        )
        assert adjacent["started_at"] == "2026-08-05T04:00:00.000Z", (
            f"started_at is echoed as an ISO 8601 UTC instant, got {adjacent['started_at']!r}"
        )
        assert not adjacent.get("ended_at"), (
            f"an open event has no ended_at, got {adjacent.get('ended_at')!r}"
        )
        assert adjacent.get("outage_minutes") is None, (
            f"an open event has no outage_minutes, got {adjacent.get('outage_minutes')!r}"
        )

        data, meta = validate_paginated(
            api.list_outage_events(netops_headers, params={"beam_id": env["beam"]["id"]})
        )
        assert meta["total_count"] == 2, (
            f"the beam should carry exactly two events, got {meta['total_count']}"
        )
        assert len(data) == 2, f"both events must be listed, got {len(data)}"

    @pytest.mark.parametrize(
        "started_at",
        ["2026-08-05T00:00:00Z", "2026-08-05T02:00:00Z", "2026-08-05T03:59:00Z"],
        ids=["left_endpoint_inclusive", "strict_interior", "just_before_right_endpoint"],
    )
    def test_new_event_starting_inside_the_prior_span_is_rejected(
        self, api, netops_headers, started_at
    ):
        """Every instant from the prior `started_at` up to but excluding its
        `ended_at` is occupied for that beam and cause.

        PRD §3.8: "A resolved event covers the span from its `started_at` inclusive up to its `ended_at` exclusive; an open event covers everything from its `started_at` onward with no upper bound."
        PRD §3.8: "A new event whose `started_at` falls inside any such span is refused with `ERR_OUTAGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_window_half_open_adjacency_accepted_while_interior_start_collides
        """
        env = self._beam_with_resolved_event()

        response = api.create_outage_event(
            create_outage_event_payload(
                beam_id=env["beam"]["id"],
                cause="EQUIPMENT_FAILURE",
                severity="FULL_OUTAGE",
                started_at=started_at,
            ),
            netops_headers,
        )
        validate_error(response, ApiErrorId.ERR_OUTAGE_WINDOW_OVERLAP, expected_status=409)

        _, meta = validate_paginated(
            api.list_outage_events(netops_headers, params={"beam_id": env["beam"]["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused filing must not persist an event, got {meta['total_count']}"
        )

    def test_an_open_event_occupies_everything_from_its_started_at_onward(
        self, api, netops_headers
    ):
        """With no `ended_at` there is no right endpoint to free, so a later
        instant on the same beam and cause still collides.

        PRD §3.8: "A resolved event covers the span from its `started_at` inclusive up to its `ended_at` exclusive; an open event covers everything from its `started_at` onward with no upper bound."
        PRD §3.8: "A new event whose `started_at` falls inside any such span is refused with `ERR_OUTAGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_window_half_open_adjacency_accepted_while_interior_start_collides
        """
        env = setup_topology()
        set_clock("2026-08-11T00:00:00Z")
        open_outage_event(
            env["beam"]["id"],
            cause="EQUIPMENT_FAILURE",
            severity="FULL_OUTAGE",
            started_at="2026-08-05T00:00:00Z",
        )

        response = api.create_outage_event(
            create_outage_event_payload(
                beam_id=env["beam"]["id"],
                cause="EQUIPMENT_FAILURE",
                severity="FULL_OUTAGE",
                started_at="2026-08-09T12:00:00Z",
            ),
            netops_headers,
        )
        validate_error(response, ApiErrorId.ERR_OUTAGE_WINDOW_OVERLAP, expected_status=409)

    def test_a_different_cause_never_collides_on_the_same_beam(self, api, netops_headers):
        """Occupancy is per beam *and* cause, so an interior instant under another
        cause is admitted while the same cause is refused.

        PRD §3.8: "A new event whose `started_at` falls inside any such span is refused with `ERR_OUTAGE_WINDOW_OVERLAP`."
        PRD §3.8: "Events with different causes on the same beam, or the same cause on different beams, never collide."

        Design: Difficulty/resource_temporal_overlap/outage_window_half_open_adjacency_accepted_while_interior_start_collides
        """
        env = self._beam_with_resolved_event()

        refused = api.create_outage_event(
            create_outage_event_payload(
                beam_id=env["beam"]["id"],
                cause="EQUIPMENT_FAILURE",
                severity="FULL_OUTAGE",
                started_at="2026-08-05T02:00:00Z",
            ),
            netops_headers,
        )
        validate_error(refused, ApiErrorId.ERR_OUTAGE_WINDOW_OVERLAP, expected_status=409)

        admitted = validate_success(
            api.create_outage_event(
                create_outage_event_payload(
                    beam_id=env["beam"]["id"],
                    cause="WEATHER_RAIN_FADE",
                    severity="FULL_OUTAGE",
                    started_at="2026-08-05T02:00:00Z",
                ),
                netops_headers,
            ),
            expected_status=201,
        )
        assert admitted["cause"] == "WEATHER_RAIN_FADE", (
            f"the admitted event keeps the requested cause, got {admitted['cause']}"
        )
        assert admitted["event_state"] == "OPEN", (
            f"the admitted event is OPEN, got {admitted['event_state']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Roaming windows on a subscription: closed interval plus a 24-hour cooldown
# ─────────────────────────────────────────────────────────────────────────────


class TestRoamingWindowClosedIntervalAndCooldown:
    """An approved window occupies `[effective_from, effective_until]` and then a
    24-hour cooldown whose far edge is exclusive."""

    def _subscription_with_approved_window(self):
        """A live service holding one APPROVED window [08-05 00:00, 08-10 00:00],
        whose 24-hour cooldown therefore ends at 2026-08-11T00:00:00Z."""
        return setup_approved_roaming_window(
            mode="ROAM_TEMPORARY",
            target_jurisdiction_code="US-CA",
            effective_from="2026-08-05T00:00:00Z",
            effective_until="2026-08-10T00:00:00Z",
        )

    @pytest.mark.parametrize(
        "effective_from,effective_until",
        [
            ("2026-08-08T00:00:00Z", "2026-08-12T00:00:00Z"),
            ("2026-08-10T00:00:00Z", "2026-08-15T00:00:00Z"),
            ("2026-08-10T23:00:00Z", "2026-08-15T00:00:00Z"),
            ("2026-08-10T23:59:00Z", "2026-08-15T00:00:00Z"),
        ],
        ids=[
            "overlaps_the_closed_interval",
            "touches_the_closed_interval_end",
            "inside_the_cooldown",
            "one_minute_before_the_cooldown_ends",
        ],
    )
    def test_window_inside_the_approved_interval_or_its_cooldown_is_refused(
        self, api, effective_from, effective_until
    ):
        """Both rejecting conditions are exercised: overlapping the approved closed
        interval at all, and starting strictly before the cooldown's far edge.

        PRD §3.7: "The requested window is compared against the closed window of every authorisation on that subscription whose `auth_state` is `APPROVED`, and two conditions each reject the request with `ERR_ROAMING_WINDOW_CONFLICT`: the requested closed interval from `effective_from` through `effective_until` overlapping an approved closed interval at all, or the requested `effective_from` falling strictly earlier than that approved window's `effective_until` plus a 24-hour cooldown."
        PRD §3.7: "An `effective_from` landing exactly at the end of the cooldown is accepted; the buffer is exclusive at its far edge."

        Design: Difficulty/resource_temporal_overlap/roaming_window_closed_interval_plus_cooldown_buffer_blocks_then_admits
        """
        env = self._subscription_with_approved_window()
        assert env["roaming"]["auth_state"] == "APPROVED", (
            f"setup expected an APPROVED window, got {env['roaming']['auth_state']}"
        )

        response = api.create_roaming_authorization(
            create_roaming_authorization_payload(
                subscription_id=env["subscription"]["id"],
                mode="ROAM_TEMPORARY",
                target_jurisdiction_code="US-CA",
                effective_from=effective_from,
                effective_until=effective_until,
            ),
            make_subscriber_headers(env["subscriber"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ROAMING_WINDOW_CONFLICT, expected_status=409)

    def test_window_starting_exactly_at_the_cooldown_edge_is_admitted(
        self, api, compliance_headers
    ):
        """`effective_until` 2026-08-10T00:00:00Z plus 24 hours is
        2026-08-11T00:00:00Z, and a request starting exactly there is accepted.

        PRD §3.7: "The requested window is compared against the closed window of every authorisation on that subscription whose `auth_state` is `APPROVED`, and two conditions each reject the request with `ERR_ROAMING_WINDOW_CONFLICT`: the requested closed interval from `effective_from` through `effective_until` overlapping an approved closed interval at all, or the requested `effective_from` falling strictly earlier than that approved window's `effective_until` plus a 24-hour cooldown."
        PRD §3.7: "An `effective_from` landing exactly at the end of the cooldown is accepted; the buffer is exclusive at its far edge."
        PRD §3.7: "A newly raised request is born in `auth_state` `REQUESTED` with `info_round_count` at 0, and with `governing_license_id`, `decision_note` and `revoked_reason` all empty."

        Design: Difficulty/resource_temporal_overlap/roaming_window_closed_interval_plus_cooldown_buffer_blocks_then_admits
        """
        env = self._subscription_with_approved_window()
        assert env["roaming"]["governing_license_id"] == env["license"]["id"], (
            "setup expected the US-CA licence stamped on the approved window, got "
            f"{env['roaming']['governing_license_id']!r}"
        )

        admitted = validate_success(
            api.create_roaming_authorization(
                create_roaming_authorization_payload(
                    subscription_id=env["subscription"]["id"],
                    mode="ROAM_TEMPORARY",
                    target_jurisdiction_code="US-CA",
                    effective_from="2026-08-11T00:00:00Z",
                    effective_until="2026-08-15T00:00:00Z",
                ),
                make_subscriber_headers(env["subscriber"]["id"]),
            ),
            expected_status=201,
        )
        assert admitted["auth_state"] == "REQUESTED", (
            f"a newly raised request is born REQUESTED, got {admitted['auth_state']}"
        )
        assert admitted["effective_from"] == "2026-08-11T00:00:00.000Z", (
            f"the accepted window keeps its requested start, got {admitted['effective_from']!r}"
        )
        assert admitted["info_round_count"] == 0, (
            f"a newly raised request has no information rounds, got {admitted['info_round_count']}"
        )
        assert not admitted.get("governing_license_id"), (
            "governing_license_id stays empty until approval, got "
            f"{admitted.get('governing_license_id')!r}"
        )

        _, meta = validate_paginated(
            api.list_roaming_authorizations(
                compliance_headers, params={"subscription_id": env["subscription"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"the subscription should carry the approved window plus the new one, got "
            f"{meta['total_count']}"
        )

    def test_resubmission_re_runs_the_same_overlap_and_cooldown_checks(
        self, api, compliance_headers
    ):
        """A corrected window offered from `NEEDS_INFO` faces exactly the checks the
        original request faced, and a start inside the cooldown is refused again.

        PRD §3.7: "The requester (the owning `Subscriber` or a `ProvisioningAgent`) closes the round by resubmitting a corrected window, supplying a fresh `effective_from` and `effective_until` that replace the stored pair; the resubmission moves the record `NEEDS_INFO → REQUESTED`, requires `effective_until` strictly later than `effective_from`, and re-runs exactly the same overlap and cooldown checks the original request faced, with the same `ERR_ROAMING_WINDOW_CONFLICT` on failure."
        PRD §3.7: "An `effective_from` landing exactly at the end of the cooldown is accepted; the buffer is exclusive at its far edge."

        Design: Difficulty/resource_temporal_overlap/roaming_window_closed_interval_plus_cooldown_buffer_blocks_then_admits
        """
        env = self._subscription_with_approved_window()
        subscriber_headers = make_subscriber_headers(env["subscriber"]["id"])

        second = request_roaming(
            env["subscription"]["id"],
            subscriber_id=env["subscriber"]["id"],
            mode="ROAM_TEMPORARY",
            target_jurisdiction_code="US-CA",
            effective_from="2026-08-20T00:00:00Z",
            effective_until="2026-08-25T00:00:00Z",
        )
        sent_back = request_roaming_info(second["id"])
        assert sent_back["auth_state"] == "NEEDS_INFO", (
            f"setup expected the review sent back for information, got {sent_back['auth_state']}"
        )

        refused = api.resubmit_roaming_authorization(
            second["id"],
            {"effective_from": "2026-08-10T23:00:00Z", "effective_until": "2026-08-15T00:00:00Z"},
            subscriber_headers,
        )
        validate_error(refused, ApiErrorId.ERR_ROAMING_WINDOW_CONFLICT, expected_status=409)

        still_open = validate_success(
            api.get_roaming_authorization(second["id"], compliance_headers)
        )
        assert still_open["auth_state"] == "NEEDS_INFO", (
            "a refused resubmission does not close the information round, got "
            f"{still_open['auth_state']}"
        )

        accepted = validate_success(
            api.resubmit_roaming_authorization(
                second["id"],
                {
                    "effective_from": "2026-08-11T00:00:00Z",
                    "effective_until": "2026-08-15T00:00:00Z",
                },
                subscriber_headers,
            )
        )
        assert accepted["auth_state"] == "REQUESTED", (
            f"an accepted resubmission moves NEEDS_INFO to REQUESTED, got {accepted['auth_state']}"
        )
        assert accepted["effective_from"] == "2026-08-11T00:00:00.000Z", (
            f"the resubmitted pair replaces the stored one, got {accepted['effective_from']!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Conserved quantity 1: integer cell slots
# ─────────────────────────────────────────────────────────────────────────────


class TestCellSlotLedgerConservation:
    """`committed_terminal_count + reserved_slot_count + free_slot_count` equals
    `max_active_terminals` at every observable point of the lifecycle."""

    @staticmethod
    def _assert_slot_sum(cell, expected_committed, expected_reserved, expected_free, moment):
        assert cell["committed_terminal_count"] == expected_committed, (
            f"{moment}: committed_terminal_count should be {expected_committed}, got "
            f"{cell['committed_terminal_count']}"
        )
        assert cell["reserved_slot_count"] == expected_reserved, (
            f"{moment}: reserved_slot_count should be {expected_reserved}, got "
            f"{cell['reserved_slot_count']}"
        )
        assert cell["free_slot_count"] == expected_free, (
            f"{moment}: free_slot_count should be {expected_free}, got {cell['free_slot_count']}"
        )
        total = (
            cell["committed_terminal_count"]
            + cell["reserved_slot_count"]
            + cell["free_slot_count"]
        )
        assert total == cell["max_active_terminals"], (
            f"{moment}: the three slot counters must sum to max_active_terminals "
            f"{cell['max_active_terminals']}, got {total}"
        )
        assert_cell_ledger_invariants(cell)

    def test_slot_ledger_is_conserved_from_reservation_through_activation_to_termination(
        self, api, agent_headers, netops_headers
    ):
        """One slot on the cell: it is a hold, then a commitment, then free again,
        and the sum never drifts.

        PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."
        PRD §3.5: "On the cell, `reserved_slot_count` drops by 1 while `committed_terminal_count` rises by 1 — the hold becomes a commitment — after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."
        PRD §3.9: "Hop one: the cell's `committed_terminal_count` drops by 1, after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."

        Design: Difficulty/compensating_invariant/cell_slot_ledger_conserved_across_activation_and_termination
        """
        env = setup_reserved_order()
        cell_id = env["cell"]["id"]

        before = validate_success(api.get_service_cell(cell_id, agent_headers))
        assert before["max_active_terminals"] == 1, (
            f"setup expected a single-slot cell, got {before['max_active_terminals']}"
        )
        self._assert_slot_sum(before, 0, 1, 0, "with the order reserved")

        subscription = validate_success(
            api.create_subscription(
                create_subscription_payload(
                    service_order_id=env["order"]["id"],
                    terminal_id=env["terminal"]["id"],
                    expected_service_cell_version=before["version"],
                ),
                agent_headers,
            ),
            expected_status=201,
        )

        between = validate_success(api.get_service_cell(cell_id, agent_headers))
        self._assert_slot_sum(between, 1, 0, 0, "after activation")

        terminated = validate_success(
            api.terminate_subscription(
                subscription["id"], {"termination_reason": "customer churn"}, agent_headers
            )
        )
        assert terminated["service_state"] == "TERMINATED", (
            f"the subscription must reach TERMINATED, got {terminated['service_state']}"
        )

        after = validate_success(api.get_service_cell(cell_id, agent_headers))
        self._assert_slot_sum(after, 0, 0, 1, "after termination")
        assert after["waitlist_depth"] == 0, (
            f"no order was ever waitlisted on this cell, got {after['waitlist_depth']}"
        )

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert float(beam["weighted_sold_mbps"]) == pytest.approx(0, abs=0.001), (
            "a TERMINATED subscription contributes nothing to the sold total, got "
            f"{beam['weighted_sold_mbps']}"
        )

    def test_termination_settles_the_order_terminal_and_account_alongside_the_slot(
        self, api, agent_headers, logistics_headers
    ):
        """The compensating action also closes out the records the activation moved:
        the consumed order, the bound terminal and the account.

        PRD §3.9: "A `ProvisioningAgent` supplies a `termination_reason`, and a subscription whose `service_state` is `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED` moves to the terminal state `TERMINATED`; its `terminated_at` is stamped with the logical clock's current instant and its `authorization_state` is forced to `DEAUTHORIZED`."
        PRD §3.9: "The bound terminal is pulled back: a terminal in `INSTALLED` moves `INSTALLED → RETURN_INITIATED`."
        PRD §3.9: "And the subscriber's `account_state` moves to `CLOSED` when that subscriber has no remaining subscription whose `service_state` is `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED`."
        PRD §3.5: "The consumed order moves `RESERVED → ACTIVATED`, which is terminal for it."

        Design: Difficulty/compensating_invariant/cell_slot_ledger_conserved_across_activation_and_termination
        """
        env = setup_reserved_order()
        subscription = validate_success(
            api.create_subscription(
                create_subscription_payload(
                    service_order_id=env["order"]["id"],
                    terminal_id=env["terminal"]["id"],
                    expected_service_cell_version=get_cell_version(env["cell"]["id"]),
                ),
                agent_headers,
            ),
            expected_status=201,
        )

        terminated = validate_success(
            api.terminate_subscription(
                subscription["id"], {"termination_reason": "customer churn"}, agent_headers
            )
        )
        assert terminated["authorization_state"] == "DEAUTHORIZED", (
            f"termination forces DEAUTHORIZED, got {terminated['authorization_state']}"
        )
        assert terminated["terminated_at"] == "2026-08-01T00:00:00.000Z", (
            "terminated_at is the logical clock's current instant, got "
            f"{terminated['terminated_at']!r}"
        )

        order = validate_success(api.get_service_order(env["order"]["id"], agent_headers))
        assert order["order_state"] == "ACTIVATED", (
            f"the consumed order stays ACTIVATED, got {order['order_state']}"
        )

        terminal = validate_success(api.get_terminal(env["terminal"]["id"], logistics_headers))
        assert terminal["terminal_state"] == "RETURN_INITIATED", (
            f"the bound terminal is pulled back, got {terminal['terminal_state']}"
        )

        subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert subscriber["account_state"] == "CLOSED", (
            f"no non-terminal subscription remains, got {subscriber['account_state']}"
        )

        cell = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        self._assert_slot_sum(cell, 0, 0, 1, "after termination")
        assert cell["availability_state"] == "AVAILABLE", (
            f"a cell with a free slot advertises AVAILABLE, got {cell['availability_state']}"
        )

    def test_the_slot_freed_by_termination_is_handed_to_the_waitlisted_order(
        self, api, agent_headers
    ):
        """Promotion redistributes the unit rather than creating one: committed
        falls to 0 and reserved rises to 1, so the sum is still exactly one slot.

        PRD §3.9: "Hop one: the cell's `committed_terminal_count` drops by 1, after which `free_slot_count` and `availability_state` are recomputed and the cell's `version` increases by 1."
        PRD §3.9: "Hop two, caused by hop one: the promotion routine runs on that cell, so the top-ranked waitlisted order — highest `waitlist_priority_score`, `created_at` ascending as tie-break — moves `WAITLISTED → RESERVED` with its `reservation_expires_at` set to the logical clock's current instant plus 72 hours and its `promoted_at` stamped."

        Design: Difficulty/compensating_invariant/cell_slot_ledger_conserved_across_activation_and_termination
        """
        env = setup_active_subscription()
        waiting = setup_waitlisted_order(env, subscriber_index=2)
        assert waiting["order"]["order_state"] == "WAITLISTED", (
            f"setup expected a waitlisted order, got {waiting['order']['order_state']}"
        )

        before = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        self._assert_slot_sum(before, 1, 0, 0, "with the service live")
        assert before["waitlist_depth"] == 1, (
            f"one order waits on this cell, got {before['waitlist_depth']}"
        )

        terminate_subscription(env["subscription"]["id"])

        after = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        self._assert_slot_sum(after, 0, 1, 0, "after termination promoted the waitlisted order")
        assert after["waitlist_depth"] == 0, (
            f"the promoted order left the waitlist, got {after['waitlist_depth']}"
        )

        promoted = validate_success(api.get_service_order(waiting["order"]["id"], agent_headers))
        assert promoted["order_state"] == "RESERVED", (
            f"the top-ranked waitlisted order is promoted to RESERVED, got "
            f"{promoted['order_state']}"
        )
        assert promoted["promoted_at"], "a promoted order carries promoted_at"

    def test_suspension_keeps_the_committed_slot_while_releasing_the_megabits(
        self, api, agent_headers, netops_headers
    ):
        """Suspension moves no slot at all: the sum is conserved with the unit still
        sitting in `committed_terminal_count`, even though the beam is released.

        PRD §3.9: "What does **not** move is the cell's `committed_terminal_count` — a suspended subscription keeps its slot, so suspending a customer frees megabits but does not free a seat, and no waitlist promotion runs."
        PRD §2.8: "`SUSPENDED` and `TERMINATED` subscriptions contribute nothing — which is the asymmetry worth internalising: **a suspended subscription keeps its cell slot but releases its beam megabits.**"

        Design: Difficulty/compensating_invariant/cell_slot_ledger_conserved_across_activation_and_termination
        """
        env = setup_active_subscription()

        before = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        self._assert_slot_sum(before, 1, 0, 0, "with the service live")

        suspend_subscription(env["subscription"]["id"], suspend_reason="non-payment")

        after = validate_success(api.get_service_cell(env["cell"]["id"], agent_headers))
        self._assert_slot_sum(after, 1, 0, 0, "after suspension")

        beam = validate_success(api.get_beam(env["beam"]["id"], netops_headers))
        assert float(beam["weighted_sold_mbps"]) == pytest.approx(0, abs=0.001), (
            "a suspended subscription leaves the sold set entirely, got "
            f"{beam['weighted_sold_mbps']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Conserved quantity 2: money in cents across the credit ledgers
# ─────────────────────────────────────────────────────────────────────────────


class TestCreditLedgerConservation:
    """`pending_credit_cents + credit_balance_cents` is raised by a resolution and
    returned to its pre-outage value by a rejection."""

    def _submitted_credit(self, api, agent_headers):
        """A live service impaired for 300 minutes, with the drafted credit submitted
        by the operator `ops-user-1`.

        The impairment runs [2026-08-10T21:30:00Z, 2026-08-11T02:30:00Z) on an
        EQUIPMENT_FAILURE / FULL_OUTAGE event against a 9900-cent plan.
        """
        env = setup_active_subscription()
        subscriber = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert subscriber["pending_credit_cents"] == 0, "the account starts with nothing pending"
        assert subscriber["credit_balance_cents"] == 0, "the account starts with no balance"

        set_clock("2026-08-11T03:00:00Z")
        event = open_outage_event(
            env["beam"]["id"],
            cause="EQUIPMENT_FAILURE",
            severity="FULL_OUTAGE",
            started_at="2026-08-10T21:30:00Z",
        )
        env["event"] = resolve_outage_event(event["id"], "2026-08-11T02:30:00Z")

        credits, meta = validate_paginated(
            api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
        )
        assert meta["total_count"] == 1, (
            f"one affected subscription means one drafted credit, got {meta['total_count']}"
        )
        env["credit"] = validate_success(
            api.submit_outage_credit(
                credits[0]["id"], make_provisioning_agent_headers("ops-user-1")
            )
        )
        return env

    def test_rejection_returns_the_pending_plus_balance_sum_to_its_pre_outage_value(
        self, api, agent_headers
    ):
        """69 cents enter the pending ledger at resolution and leave it at rejection
        without ever reaching the balance, so the sum is 0 again.

        PRD §3.8: "Each drafted credit's `provisional_credit_cents` is computed by the provisional rule below, and each affected subscriber's `pending_credit_cents` is increased by that amount."
        PRD §3.8: "Both branches stamp `decided_by_user_id` with the deciding operator's `X-User-ID` and store the supplied reason in `decision_reason`, and both branches decrease the subscriber's `pending_credit_cents` by the credit's `provisional_credit_cents` — the estimate always leaves the pending ledger."
        PRD §3.8: "A rejection moves the credit `SUBMITTED → REJECTED`, leaves `final_credit_cents` empty, and leaves `credit_balance_cents` untouched, so the provisional amount leaves the pending ledger without ever reaching the balance."

        Design: Difficulty/compensating_invariant/credit_ledger_conserved_when_a_submitted_outage_credit_is_rejected
        """
        env = self._submitted_credit(api, agent_headers)
        credit_id = env["credit"]["id"]

        raised = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert raised["pending_credit_cents"] == 69, (
            f"the provisional estimate sits in the pending ledger, got "
            f"{raised['pending_credit_cents']}"
        )
        assert raised["credit_balance_cents"] == 0, (
            f"nothing reaches the balance before approval, got {raised['credit_balance_cents']}"
        )
        assert raised["pending_credit_cents"] + raised["credit_balance_cents"] == 69, (
            "the resolution raises the conserved sum to 69 cents"
        )

        rejected = validate_success(
            api.decide_outage_credit(
                credit_id,
                credit_decision_payload(
                    decision="REJECT",
                    decision_reason="impairment attributable to customer obstruction",
                ),
                make_compliance_officer_headers("compliance-user-1"),
            )
        )
        assert rejected["credit_state"] == "REJECTED", (
            f"the credit must reach REJECTED, got {rejected['credit_state']}"
        )
        assert rejected["provisional_credit_cents"] == 69, (
            f"the provisional amount is not rewritten by the decision, got "
            f"{rejected['provisional_credit_cents']}"
        )
        assert rejected.get("final_credit_cents") is None, (
            f"a rejection leaves final_credit_cents empty, got "
            f"{rejected.get('final_credit_cents')!r}"
        )
        assert rejected["submitted_by_user_id"] == "ops-user-1", (
            f"the submitting operator is recorded, got {rejected['submitted_by_user_id']!r}"
        )
        assert rejected["decided_by_user_id"] == "compliance-user-1", (
            f"the deciding operator is recorded, got {rejected['decided_by_user_id']!r}"
        )

        settled = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert settled["pending_credit_cents"] == 0, (
            f"the estimate always leaves the pending ledger, got "
            f"{settled['pending_credit_cents']}"
        )
        assert settled["credit_balance_cents"] == 0, (
            f"a rejection leaves credit_balance_cents untouched, got "
            f"{settled['credit_balance_cents']}"
        )
        assert settled["pending_credit_cents"] + settled["credit_balance_cents"] == 0, (
            "the rejection must return the conserved sum to its pre-outage value of 0 cents"
        )
        assert_subscriber_ledger_invariants(settled)

        event = validate_success(api.get_outage_event(env["event"]["id"], agent_headers))
        assert event["generated_credit_count"] == 1, (
            f"the audit trail is not rewound by a rejection, got "
            f"{event['generated_credit_count']}"
        )

    def test_submission_alone_moves_no_money(self, api, agent_headers):
        """`DRAFT` and `SUBMITTED` both count as pending, so the sum is unchanged by
        the submission that precedes the decision.

        PRD §3.8: "On success the credit moves `DRAFT → SUBMITTED` and `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`."
        PRD §3.8: "The subscriber's `pending_credit_cents` does **not** change on submission, because `DRAFT` and `SUBMITTED` credits both count as pending."

        Design: Difficulty/compensating_invariant/credit_ledger_conserved_when_a_submitted_outage_credit_is_rejected
        """
        env = setup_active_subscription()
        set_clock("2026-08-11T03:00:00Z")
        event = open_outage_event(
            env["beam"]["id"],
            cause="EQUIPMENT_FAILURE",
            severity="FULL_OUTAGE",
            started_at="2026-08-10T21:30:00Z",
        )
        resolve_outage_event(event["id"], "2026-08-11T02:30:00Z")

        credits, _ = validate_paginated(
            api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
        )
        drafted = credits[0]
        assert drafted["credit_state"] == "DRAFT", (
            f"a resolution drafts the credit, got {drafted['credit_state']}"
        )

        before = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert before["pending_credit_cents"] == 69, (
            f"the drafted estimate is pending, got {before['pending_credit_cents']}"
        )

        submitted = validate_success(
            api.submit_outage_credit(drafted["id"], make_provisioning_agent_headers("ops-user-1"))
        )
        assert submitted["credit_state"] == "SUBMITTED", (
            f"the credit moves DRAFT to SUBMITTED, got {submitted['credit_state']}"
        )
        assert submitted["submitted_by_user_id"] == "ops-user-1", (
            f"the submitting operator is stamped, got {submitted['submitted_by_user_id']!r}"
        )

        after = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert after["pending_credit_cents"] == 69, (
            f"submission moves no money out of the pending ledger, got "
            f"{after['pending_credit_cents']}"
        )
        assert after["credit_balance_cents"] == 0, (
            f"submission moves no money into the balance, got {after['credit_balance_cents']}"
        )
        assert after["pending_credit_cents"] + after["credit_balance_cents"] == 69, (
            "the conserved sum is unchanged by submission"
        )

    def test_approval_moves_the_credit_out_of_pending_and_into_the_balance(
        self, api, agent_headers
    ):
        """The contrasting branch: the estimate still leaves the pending ledger, but
        the final amount lands in the balance instead of vanishing.

        PRD §3.8: "Both branches stamp `decided_by_user_id` with the deciding operator's `X-User-ID` and store the supplied reason in `decision_reason`, and both branches decrease the subscriber's `pending_credit_cents` by the credit's `provisional_credit_cents` — the estimate always leaves the pending ledger."
        PRD §3.8: "An approval moves the credit `SUBMITTED → APPROVED`, computes `final_credit_cents` by the final per-day rule, and increases the subscriber's `credit_balance_cents` by that final amount."
        PRD §3.8: "`credit_balance_cents` is the sum of `final_credit_cents` across that subscriber's credits in `credit_state` `APPROVED`."

        Design: Difficulty/compensating_invariant/credit_ledger_conserved_when_a_submitted_outage_credit_is_rejected
        """
        env = self._submitted_credit(api, agent_headers)

        approved = validate_success(
            api.decide_outage_credit(
                env["credit"]["id"],
                credit_decision_payload(
                    decision="APPROVE", decision_reason="impairment confirmed"
                ),
                make_compliance_officer_headers("compliance-user-1"),
            )
        )
        assert approved["credit_state"] == "APPROVED", (
            f"the credit must reach APPROVED, got {approved['credit_state']}"
        )
        assert isinstance(approved.get("final_credit_cents"), int), (
            "an approval computes final_credit_cents in whole cents, got "
            f"{approved.get('final_credit_cents')!r}"
        )

        settled = validate_success(api.get_subscriber(env["subscriber"]["id"], agent_headers))
        assert settled["pending_credit_cents"] == 0, (
            f"the estimate always leaves the pending ledger, got "
            f"{settled['pending_credit_cents']}"
        )
        assert settled["credit_balance_cents"] == approved["final_credit_cents"], (
            "credit_balance_cents is the sum of final_credit_cents across APPROVED credits, "
            f"expected {approved['final_credit_cents']}, got {settled['credit_balance_cents']}"
        )
        assert_subscriber_ledger_invariants(settled)
