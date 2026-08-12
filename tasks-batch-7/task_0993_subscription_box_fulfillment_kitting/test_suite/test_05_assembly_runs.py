"""Assembly run lifecycle: creation defaults, period-slot uniqueness, lock
gates (plan state, credit boundary, component shortage), subscriber snapshot,
and the reserve/cancel conservation invariant.

Covers PRD §2.9 (validation order), §3.4 (assembly runs).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_revision,
    bom_line,
    churn_payload,
    create_active_plan_with_bom,
    create_assembly_run_payload,
    create_client,
    create_plan,
    create_revision,
    create_run,
    create_stocked_component,
    get_component,
    get_run,
    import_named_subscribers,
    list_run_events,
    list_run_shipments,
    lock_run,
    make_client_ops_headers,
    put_bom,
    set_clock,
    setup_kitted_scenario,
    subscriber_row,
    import_batch_payload,
    activate_plan,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestRunCreation:
    def test_newly_created_run_starts_draft(self):
        """PRD §3.4: "New runs stand in `DRAFT` with `planned_box_count`,
        `kitted_box_count`, and `estimate_cents` all at 0."

        Design: Corner/state_machines/newly_created_run_starts_draft
        """
        set_clock()
        client = create_client(name="SM8 Client", billing_email="sm8@acme.test")
        plan = create_plan(client["id"], "PL-SM8", name="SM8 Box",
                           shipping_weight_grams=500)
        run = validate_success(
            api_client.create_assembly_run(
                create_assembly_run_payload(plan["id"], "2026-05"), WAREHOUSE),
            expected_status=201)
        assert run["status"] == "DRAFT"
        assert run["planned_box_count"] == 0
        assert run["kitted_box_count"] == 0
        assert run["estimate_cents"] == 0
        assert isinstance(run["version"], int)


class TestRunPeriodSlot:
    def _setup_two_plans(self):
        set_clock()
        client = create_client(name="TO2 Client", billing_email="to2@acme.test")
        plan_a = create_plan(client["id"], "PL-TO2-A", name="TO2 Box A")
        plan_b = create_plan(client["id"], "PL-TO2-B", name="TO2 Box B")
        run_may = create_run(plan_a["id"], "2026-05")
        return client, plan_a, plan_b, run_may

    def test_run_period_slot_uniqueness_collision_and_neighbours(self):
        """PRD §3.4: "Only one run per plan and period may exist outside the
        `CANCELLED` state; a second non-cancelled run for the same pairing is
        rejected with `ERR_RUN_PERIOD_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/run_period_slot_uniqueness
        """
        _client, plan_a, plan_b, run_may = self._setup_two_plans()
        assert run_may["status"] == "DRAFT"

        dup = api_client.create_assembly_run(
            create_assembly_run_payload(plan_a["id"], "2026-05"), WAREHOUSE)
        validate_error(dup, ApiErrorId.ERR_RUN_PERIOD_CONFLICT)

        next_month = validate_success(
            api_client.create_assembly_run(
                create_assembly_run_payload(plan_a["id"], "2026-06"), WAREHOUSE),
            expected_status=201)
        assert next_month["status"] == "DRAFT", \
            "a different month is a different slot and must succeed"

        other_plan = validate_success(
            api_client.create_assembly_run(
                create_assembly_run_payload(plan_b["id"], "2026-05"), WAREHOUSE),
            expected_status=201)
        assert other_plan["status"] == "DRAFT", \
            "the slot is per BoxPlan, not global"

    def test_run_period_slot_freed_by_cancellation(self):
        """PRD §3.4: "Because the period-conflict rule counts only
        non-cancelled runs, a cancelled run frees its plan-and-period pairing
        for a future attempt."

        Design: Difficulty/resource_temporal_overlap/run_period_slot_uniqueness
        """
        _client, plan_a, _plan_b, run_may = self._setup_two_plans()
        cancelled = validate_success(api_client.cancel_assembly_run(run_may["id"],
                                                                    WAREHOUSE))
        assert cancelled["status"] == "CANCELLED"

        recreated = validate_success(
            api_client.create_assembly_run(
                create_assembly_run_payload(plan_a["id"], "2026-05"), WAREHOUSE),
            expected_status=201)
        assert recreated["status"] == "DRAFT"
        assert recreated["id"] != run_may["id"]


class TestRunLockPlanStateGate:
    def _setup_draft_plan_with_approved_bom(self, wallet: int = 50000):
        """Plan carries an APPROVED revision but is never activated."""
        set_clock()
        client = create_client(wallet_cents=wallet, name="CE1 Client",
                               billing_email="ce1@acme.test")
        component = create_stocked_component("CMP-CE1", 10)
        plan = create_plan(client["id"], "PL-CE1", price_per_box_cents=1000,
                           shipping_weight_grams=800, name="CE1 Box")
        revision = create_revision(plan["id"], client["id"])
        put_bom(revision["id"], client["id"], [bom_line(component["id"], 1)])
        approve_revision(revision["id"], client["id"])
        import_named_subscribers(plan["id"], client["id"], [("ce1a@x.test", 2)])
        run = create_run(plan["id"])
        return client, component, plan, run

    def test_run_lock_requires_plan_active_rejects_draft_plan(self):
        """PRD §3.4: "the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/run_lock_requires_plan_active
        """
        _client, component, _plan, run = \
            self._setup_draft_plan_with_approved_bom()
        resp = api_client.lock_assembly_run(run["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

        assert get_run(run["id"])["status"] == "DRAFT", \
            "rejected lock must leave the run DRAFT"
        assert list_run_events(run["id"]) == [], \
            "rejected lock must append no inventory events"
        assert get_component(component["id"])["reserved_units"] == 0

    def test_run_lock_succeeds_once_plan_activated(self):
        """PRD §3.4: "Locking a run — `DRAFT → LOCKED` — is the most heavily
        gated transition in the system, and its checks fire in the priority
        order of §2.9: the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/run_lock_requires_plan_active
        """
        client, _component, plan, run = self._setup_draft_plan_with_approved_bom()
        activate_plan(plan["id"], client["id"])

        locked = lock_run(run["id"])
        assert locked["status"] == "LOCKED", \
            "once the plan is ACTIVE the same lock must succeed"
        assert locked["planned_box_count"] == 1


class TestLockValidationPriority:
    def _setup_retired_plan(self, wallet: int):
        """Plan went ACTIVE then RETIRED; subscribers imported; run DRAFT."""
        set_clock()
        client = create_client(wallet_cents=wallet, name="PV1 Client",
                               billing_email="pv1@acme.test")
        component = create_stocked_component("CMP-PV1", 100)
        plan, _revision = create_active_plan_with_bom(
            client["id"], "PL-PV1", [(component["id"], 1)],
            price_per_box_cents=3000, shipping_weight_grams=1000)
        validate_success(api_client.retire_box_plan(
            plan["id"], make_client_ops_headers(client["id"])))
        import_named_subscribers(plan["id"], client["id"],
                                 [("pv1a@x.test", 2), ("pv1b@x.test", 2)])
        run = create_run(plan["id"])
        return client, plan, run

    def test_lock_plan_retired_and_zero_credit_state_wins(self):
        """PRD §2.9: "the server evaluates them in one fixed priority order,
        and the earliest failing tier determines the error the caller sees".
        PRD §3.4: "its checks fire in the priority order of §2.9: the plan must
        be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`) ... and only then do the money
        and capacity gates run."

        Design: Difficulty/priority_pair_validation_conflict/lock_plan_retired_and_zero_credit_state_wins
        """
        _client, _plan, run = self._setup_retired_plan(wallet=0)
        resp = api_client.lock_assembly_run(run["id"], WAREHOUSE)
        # Wallet 0 < would-be estimate 6000: the state tier (ERR_PLAN_NOT_ACTIVE)
        # must win over the fiscal tier (ERR_INSUFFICIENT_CREDIT).
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        assert get_run(run["id"])["status"] == "DRAFT"

    def test_lock_plan_retired_state_error_independent_of_credit(self):
        """PRD §3.4: "the plan must be `ACTIVE` (else
        `ERR_PLAN_NOT_ACTIVE`)" — the state gate is evaluated before, and
        independently of, the wallet gate ("and only then do the money and
        capacity gates run").

        Design: Difficulty/priority_pair_validation_conflict/lock_plan_retired_and_zero_credit_state_wins
        """
        _client, _plan, run = self._setup_retired_plan(wallet=100000)
        resp = api_client.lock_assembly_run(run["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        assert get_run(run["id"])["status"] == "DRAFT"


class TestLockCreditBoundary:
    def _setup_bd1(self, wallet: int):
        """2 ACTIVE subscribers at price 3000 -> estimate 6000 at lock."""
        set_clock()
        client = create_client(wallet_cents=wallet, name="BD1 Client",
                               billing_email="bd1@acme.test")
        component = create_stocked_component("CMP-BD1", 100)
        plan, _revision = create_active_plan_with_bom(
            client["id"], "PL-BD1", [(component["id"], 1)],
            price_per_box_cents=3000, shipping_weight_grams=1000)
        import_named_subscribers(plan["id"], client["id"],
                                 [("bd1a@x.test", 2), ("bd1b@x.test", 2)])
        run = create_run(plan["id"])
        return client, run

    def test_lock_credit_exactly_equal_estimate_passes(self):
        """PRD §3.4: "The credit gate requires the client's
        `credit_balance_cents` to be at least `estimate_cents` — equality
        passes — and rejects otherwise with `ERR_INSUFFICIENT_CREDIT`."
        PRD §3.4: "`estimate_cents` becomes `planned_box_count` multiplied by
        the plan's `price_per_box_cents`".

        Design: Difficulty/boundary_precision_check/lock_credit_exactly_equal_estimate_passes
        """
        client, run = self._setup_bd1(wallet=6000)
        locked = lock_run(run["id"])
        assert locked["status"] == "LOCKED"
        assert locked["planned_box_count"] == 2
        assert locked["estimate_cents"] == 6000, \
            f"estimate must freeze at 2 x 3000, got {locked['estimate_cents']}"

        balance = validate_success(api_client.get_client(client["id"], BILLING))
        assert balance["credit_balance_cents"] == 6000, (
            "the credit gate checks but does not debit at lock "
            f"(wallet {balance['credit_balance_cents']})"
        )

    def test_lock_credit_one_cent_below_estimate_rejected(self):
        """PRD §3.4: "The credit gate requires the client's
        `credit_balance_cents` to be at least `estimate_cents` — equality
        passes — and rejects otherwise with `ERR_INSUFFICIENT_CREDIT`."

        Design: Difficulty/boundary_precision_check/lock_credit_exactly_equal_estimate_passes
        """
        _client, run = self._setup_bd1(wallet=5999)
        resp = api_client.lock_assembly_run(run["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)
        assert get_run(run["id"])["status"] == "DRAFT"


class TestLockCapacityGates:
    def test_run_lock_component_shortage_rejected(self):
        """PRD §3.4: "The shortage gate requires, for every BOM line of the
        active revision, that the component's `available_units` be at least the
        line's `qty_per_box` multiplied by `planned_box_count`, rejecting with
        `ERR_COMPONENT_SHORTAGE` on any shortfall."

        Design: Corner/validations/run_lock_component_shortage_rejected
        """
        set_clock()
        client = create_client(wallet_cents=100000, name="V2 Client",
                               billing_email="v2@acme.test")
        component = create_stocked_component("CMP-V2", 1)
        plan, _revision = create_active_plan_with_bom(
            client["id"], "PL-V2", [(component["id"], 2)],
            price_per_box_cents=1000, shipping_weight_grams=800)
        import_named_subscribers(plan["id"], client["id"], [("v2@x.test", 2)])
        run = create_run(plan["id"])

        resp = api_client.lock_assembly_run(run["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_COMPONENT_SHORTAGE)

        assert get_run(run["id"])["status"] == "DRAFT"
        after = get_component(component["id"])
        assert after["reserved_units"] == 0, \
            "a rejected lock must not partially reserve stock"

    def test_run_lock_subscriber_snapshot_excludes_paused_and_churned(self):
        """PRD §3.4: "`planned_box_count` becomes the count of the plan's
        subscribers in `ACTIVE` status at the lock instant — `PAUSED` and
        `CHURNED` subscribers are excluded." PRD §3.4: "It creates one shipment
        per snapshotted subscriber".

        Design: Corner/calculations/run_lock_subscriber_snapshot_excludes_paused_and_churned
        """
        set_clock()
        client = create_client(wallet_cents=100000, name="CC2 Client",
                               billing_email="cc2@acme.test")
        headers = make_client_ops_headers(client["id"])
        component = create_stocked_component("CMP-CC2", 50)
        plan, _revision = create_active_plan_with_bom(
            client["id"], "PL-CC2", [(component["id"], 1)],
            price_per_box_cents=1000, shipping_weight_grams=800)
        s1 = import_named_subscribers(plan["id"], client["id"],
                                      [("cc2s1@x.test", 2)])[0]
        s2 = import_named_subscribers(plan["id"], client["id"],
                                      [("cc2s2@x.test", 2)])[0]
        s3 = import_named_subscribers(plan["id"], client["id"],
                                      [("cc2s3@x.test", 2)])[0]
        validate_success(api_client.pause_subscriber(s2["id"], headers))
        validate_success(api_client.churn_subscriber(s3["id"],
                                                     churn_payload("MOVED"), headers))
        run = create_run(plan["id"])

        locked = lock_run(run["id"])
        assert locked["status"] == "LOCKED"
        assert locked["planned_box_count"] == 1, (
            f"only the ACTIVE subscriber counts, got "
            f"{locked['planned_box_count']}"
        )
        shipments = list_run_shipments(run["id"])
        assert len(shipments) == 1, f"one shipment per snapshotted subscriber"
        assert shipments[0]["subscriber_id"] == s1["id"]
        assert shipments[0]["subscriber_id"] not in (s2["id"], s3["id"])


class TestReserveCancelConservation:
    def _setup_locked_ci1(self):
        """Component 100 on hand, BOM qty 2, 2 ACTIVE subscribers; run LOCKED
        (reserve 4)."""
        env = setup_kitted_scenario(
            "CI1", num_subscribers=2, qty_per_box=2, stock=100,
            price_per_box_cents=1000, shipping_weight_grams=800,
            wallet_cents=50000, run_state="LOCKED")
        return env

    def test_reserve_then_cancel_conserves_available_units(self):
        """PRD §2.6: "`available_units` is `on_hand_units` minus
        `reserved_units`". PRD §3.4: "a `LOCKED → CANCELLED` cancellation
        appends `RELEASE` events for the full remaining reservation of every
        BOM line (lowering each component's `reserved_units` accordingly),
        moves the run's `QUEUED` shipments to `CANCELLED`".

        Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_available_units
        """
        env = self._setup_locked_ci1()
        component_id = env["component"]["id"]
        mid = get_component(component_id)
        assert mid["available_units"] == 96 and mid["reserved_units"] == 4, (
            f"lock must reserve 4 of 100: available {mid['available_units']}, "
            f"reserved {mid['reserved_units']}"
        )

        cancelled = validate_success(
            api_client.cancel_assembly_run(env["run"]["id"], WAREHOUSE))
        assert cancelled["status"] == "CANCELLED"

        after = get_component(component_id)
        assert after["available_units"] == 100, \
            f"cancel must restore the pre-lock availability, got {after['available_units']}"
        assert after["reserved_units"] == 0
        assert after["on_hand_units"] == 100, \
            "nothing was committed, so on_hand must be untouched"

    def test_reserve_then_cancel_event_ledger_nets_to_zero(self):
        """PRD §3.4: "It appends one `RESERVE` inventory event per BOM line,
        with a positive `quantity_delta` equal to that line's required units".
        PRD §3.4: "a `LOCKED → CANCELLED` cancellation appends `RELEASE` events
        for the full remaining reservation of every BOM line".

        Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_available_units
        """
        env = self._setup_locked_ci1()
        run_id = env["run"]["id"]
        validate_success(api_client.cancel_assembly_run(run_id, WAREHOUSE))

        events = list_run_events(run_id)
        by_type = {}
        for event in events:
            by_type.setdefault(event["event_type"], []).append(event["quantity_delta"])
        assert by_type.get("RESERVE") == [4], \
            f"one RESERVE of +4 expected, got {by_type.get('RESERVE')}"
        assert by_type.get("RELEASE") == [-4], \
            f"one RELEASE of -4 expected, got {by_type.get('RELEASE')}"
        assert sum(e["quantity_delta"] for e in events) == 0, \
            "the run's event ledger must net to zero"

        cancelled_shipments = list_run_shipments(run_id, fulfill_status="CANCELLED")
        assert len(cancelled_shipments) == 2, \
            "both QUEUED shipments of the run must be CANCELLED"
        assert list_run_shipments(run_id, fulfill_status="QUEUED") == []
