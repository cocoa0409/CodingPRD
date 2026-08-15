"""Awards, the append-only points ledger, derived balances, recognition tiers,
and the points-adjustment grant endpoint."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_employee_ledger_reconciles,
    assert_point_ledger_entry,
    create_catalog_item,
    create_points_adjustment_payload,
    create_redemption_order_payload,
    create_vendor,
    deliver_redemption_order,
    get_success_data,
    make_employee_headers,
    setup_employee_with_grant,
    setup_program_with_budget,
    submit_and_approve_nomination,
    validate_error,
    validate_paginated,
    validate_success,
)

VOPS = TEST_USERS["vendor_ops_headers"]


class TestFifoConsumption:
    def test_settlement_consumes_oldest_award_first(self, api, hr_admin_headers):
        """PRD §3.4: "When a redemption settles, the employee's `ACTIVE`
        awards are consumed in `granted_at` ascending order, ties broken by
        `created_at` ascending — UUID `id` values are never used for ordering —
        taking up to each award's `points_remaining` until the order's
        `points_total` is satisfied; an award drained to zero becomes
        `FULLY_REDEEMED`."

        Design: Corner/calculations/fifo_consumption_oldest_award_first
        """
        ctx = setup_program_with_budget(allocated_points=100000)
        program_id = ctx["program"]["id"]
        employee, manager = ctx["employee"], ctx["manager"]
        _, older_award = submit_and_approve_nomination(
            program_id, employee["id"], manager, 1000,
            type="MANAGER", reason_code="TEAMWORK", idempotency_key="calc-fifo-1",
        )
        # Advance the logical clock so the second award's granted_at is
        # strictly later (FIFO order is then determined by granted_at alone).
        get_success_data(api.set_clock("2026-08-01T01:00:00Z", hr_admin_headers))
        _, newer_award = submit_and_approve_nomination(
            program_id, employee["id"], manager, 2000,
            type="MANAGER", reason_code="INNOVATION", idempotency_key="calc-fifo-2",
        )

        vendor = create_vendor()
        item = create_catalog_item(
            vendor["id"], sku="BIG", name="Big", point_cost=1500,
            cash_value_cents=7500,
        )
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="calc-fifo-r1"),
            make_employee_headers(employee["id"]),
        ), 201)
        get_success_data(api.submit_redemption_order(order["id"], VOPS))
        get_success_data(api.mark_redemption_order_shipped(order["id"], VOPS))
        get_success_data(api.mark_redemption_order_delivered(order["id"], VOPS))

        older = validate_success(api.get_award(older_award, hr_admin_headers), 200)
        newer = validate_success(api.get_award(newer_award, hr_admin_headers), 200)
        assert older["points_remaining"] == 0
        assert older["status"] == "FULLY_REDEEMED"
        assert newer["points_remaining"] == 1500
        assert newer["status"] == "ACTIVE"


class TestAwardExpirySweep:
    def test_award_expiry_debits_points_and_releases_budget_commitment(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.4: "The expiry sweep of the clock advance walks the same
        order: each `ACTIVE` award whose `expires_at` is at or before the new
        clock time is expired, writing an `EXPIRY` ledger entry that debits
        `points_remaining` from `available_points` and adds it to
        `lifetime_expired_points`, releasing the same amount from the
        committed counter of the budget whose window contains the award's
        `granted_at` for the employee's department whenever that budget is not
        `CLOSED`, recomputing that budget's posture, and zeroing
        `points_remaining`."

        Design: Corner/state_machines/award_expiry_sweep_and_budget_release
        """
        ctx = setup_program_with_budget(
            allocated_points=10000,
            budget_overrides={"period_start_date": "2026-01-01",
                              "period_end_date": "2027-12-31"},
        )
        _, award_id = submit_and_approve_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 600,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="sm-aex-1",
        )
        # Granted at 2026-08-01T00:00:00Z; expires exactly twelve months later.
        get_success_data(api.set_clock("2027-08-01T00:00:01Z", hr_admin_headers))

        award = validate_success(api.get_award(award_id, hr_admin_headers), 200)
        assert award["status"] == "EXPIRED"
        assert award["points_remaining"] == 0

        employee = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert employee["available_points"] == 0
        assert employee["lifetime_expired_points"] == 600

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["committed_points"] == 0


class TestAwardRevocation:
    def test_revoked_award_is_terminal(self, api, hr_admin_headers):
        """PRD §3.4: "Attempting to revoke an award that is not `ACTIVE` is
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/revoked_award_terminal_lockdown
        """
        ctx = setup_program_with_budget(allocated_points=10000)
        _, award_id = submit_and_approve_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 700,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="sm-tl-1",
        )
        get_success_data(api.revoke_award(award_id, hr_admin_headers, reason="first"))
        res = api.revoke_award(award_id, hr_admin_headers, reason="second")
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        entries, _ = validate_paginated(api.list_ledger_entries(
            ctx["employee"]["id"], hr_admin_headers,
            params={"entry_type": "CLAWBACK"},
        ))
        assert len(entries) == 1

    def test_approve_then_revoke_restores_budget_counters(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.4: "Revocation writes a `CLAWBACK` ledger entry debiting the
        award's full `points_remaining` from `available_points`, which may
        drive the balance negative when some of the grant was already spent;
        releases the same amount from the originating budget's
        `committed_points` when that budget is not `CLOSED`, recomputing
        posture; recomputes the employee's `lifetime_granted_points` and
        `recognition_tier`, possibly demoting the tier; zeroes
        `points_remaining`".

        Design: Difficulty/compensating_invariant/approve_then_revoke_budget_conservation
        """
        ctx = setup_program_with_budget(allocated_points=10000)
        program_id = ctx["program"]["id"]
        budget_id = ctx["budget"]["id"]
        _, award_id = submit_and_approve_nomination(
            program_id, ctx["employee"]["id"], ctx["manager"], 2500,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="ci2-n1",
        )
        mid = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert mid["reserved_points"] == 0
        assert mid["committed_points"] == 2500

        revoked = validate_success(api.revoke_award(
            award_id, hr_admin_headers, reason="granted in error"
        ), 200)
        assert revoked["status"] == "REVOKED"

        end = validate_success(api.get_budget(budget_id, finance_admin_headers), 200)
        assert end["reserved_points"] == 0
        assert end["committed_points"] == 0

        employee = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert employee["available_points"] == 0

    def test_revoke_claws_back_and_demotes_tier(self, api, hr_admin_headers):
        """PRD §3.4: "recomputes the employee's `lifetime_granted_points` and
        `recognition_tier`, possibly demoting the tier".
        PRD §3.4: "at least 20000 lifetime points earns `PLATINUM`, at least
        5000 earns `GOLD`, at least 1000 earns `SILVER`, and anything below
        that is `BRONZE`."

        Design: Difficulty/compensating_invariant/approve_then_revoke_budget_conservation
        """
        ctx = setup_program_with_budget(allocated_points=10000)
        _, award_id = submit_and_approve_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 2500,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="ci2b-n1",
        )
        promoted = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert promoted["recognition_tier"] == "SILVER"

        get_success_data(api.revoke_award(award_id, hr_admin_headers))
        demoted = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert demoted["recognition_tier"] == "BRONZE"
        assert demoted["lifetime_granted_points"] == 0
        assert demoted["available_points"] == 0

        entries, _ = validate_paginated(api.list_ledger_entries(
            ctx["employee"]["id"], hr_admin_headers,
            params={"entry_type": "CLAWBACK"},
        ))
        assert len(entries) == 1
        assert entries[0]["points"] == -2500


class TestTierBoundaries:
    def test_tier_boundary_exactly_1000_promotes_to_silver(
        self, api, hr_admin_headers
    ):
        """PRD §3.4: "at least 20000 lifetime points earns `PLATINUM`, at
        least 5000 earns `GOLD`, at least 1000 earns `SILVER`, and anything
        below that is `BRONZE`. The lower bounds are inclusive, so exactly
        1000 lifetime points is already `SILVER`."

        Design: Corner/calculations/tier_boundary_exactly_1000_silver
        """
        ctx = setup_program_with_budget(allocated_points=100000)
        program_id = ctx["program"]["id"]
        employee, manager = ctx["employee"], ctx["manager"]
        submit_and_approve_nomination(
            program_id, employee["id"], manager, 999,
            type="MANAGER", reason_code="TEAMWORK", idempotency_key="calc-tier-1",
        )
        below = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert below["recognition_tier"] == "BRONZE"

        submit_and_approve_nomination(
            program_id, employee["id"], manager, 1,
            type="MANAGER", reason_code="INNOVATION", idempotency_key="calc-tier-2",
        )
        at = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert at["lifetime_granted_points"] == 1000
        assert at["recognition_tier"] == "SILVER"


class TestPointsAdjustment:
    def test_points_adjustment_grants_award_and_charges_budget(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.4: "The adjustment creates an `Award` with `source`
        `ADJUSTMENT` and a null `nomination_id`, granted at the current
        instant and expiring twelve months later, writes a `GRANT_ADJUSTMENT`
        ledger entry, charges the budget selected exactly as a nomination
        would be — the employee's department budget whose window contains
        today, with `ERR_BUDGET_NOT_FOUND` and `ERR_BUDGET_EXHAUSTED` guarding
        as usual — by raising its `committed_points`, and recomputes the
        recipient's tier."

        Design: Corner/endpoints/points_adjustment_endpoint_grants_and_charges_budget
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000,
        )
        employee = ctx["employee"]
        award = validate_success(api.create_points_adjustment(
            employee["id"],
            create_points_adjustment_payload(ctx["program"]["id"], 250,
                                             reason="service catch-up"),
            hr_admin_headers,
        ), 201)
        assert award["source"] == "ADJUSTMENT"
        assert award["nomination_id"] is None

        refreshed = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert refreshed["available_points"] == 250
        assert refreshed["lifetime_granted_points"] == 250

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["committed_points"] == 250

        entries, _ = validate_paginated(api.list_ledger_entries(
            employee["id"], hr_admin_headers,
            params={"entry_type": "GRANT_ADJUSTMENT"},
        ))
        assert len(entries) == 1
        assert entries[0]["points"] == 250


class TestLedgerImmutability:
    def test_ledger_entry_carries_no_version_or_updated_at(
        self, api, hr_admin_headers
    ):
        """PRD §2.4: "The `PointLedgerEntry` is the sole exception: as an
        immutable journal record it carries only `id` and `created_at`;
        `updated_at` and `version` are absent, because a ledger entry is never
        modified after it is written."

        Design: Corner/entities/ledger_entry_immutable_no_version
        """
        ctx = setup_program_with_budget(allocated_points=10000)
        submit_and_approve_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], ctx["manager"], 100,
            type="MANAGER", reason_code="DELIVERY", idempotency_key="ent-imm-1",
        )
        entries, meta = validate_paginated(api.list_ledger_entries(
            ctx["employee"]["id"], hr_admin_headers
        ))
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_point_ledger_entry(entry)
        assert entry["entry_type"] == "GRANT_NOMINATION"
        assert entry["reference_type"] == "AWARD"


class TestLedgerReconciliation:
    def test_balances_reconcile_with_ledger_after_mixed_operations(
        self, api, hr_admin_headers
    ):
        """PRD §2.9: "Employee balances are derived from this journal, never
        stored as independent truths. `available_points` is the spendable sum
        of ledger movements and may go negative when a clawback reaches points
        already spent; `held_points` is the points escrowed by open redemption
        orders; `lifetime_granted_points` is the sum of grant entries minus
        clawback entries; `lifetime_redeemed_points` accumulates settled
        redemption points, including restocking-fee points".

        Design: Corner/cross_cutting_layers/ledger_reconciliation_after_mixed_ops
        """
        ctx = setup_employee_with_grant(3000)
        employee = ctx["employee"]
        vendor = create_vendor()
        item_a = create_catalog_item(vendor["id"], sku="A", name="A", point_cost=1000,
                                     cash_value_cents=5000)
        item_b = create_catalog_item(vendor["id"], sku="B", name="B", point_cost=400,
                                     cash_value_cents=2000)

        # Order A: delivered (settled).
        deliver_redemption_order(item_a["id"], employee, idempotency_key="xcut-rec-r1")
        # Order B: created then cancelled (hold then refund).
        order_b = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item_b["id"], idempotency_key="xcut-rec-r2"),
            make_employee_headers(employee["id"]),
        ), 201)
        get_success_data(api.cancel_redemption_order(
            order_b["id"], make_employee_headers(employee["id"])
        ))

        refreshed = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert refreshed["available_points"] == 2000
        assert refreshed["held_points"] == 0
        assert refreshed["lifetime_redeemed_points"] == 1000

        entries, _ = validate_paginated(api.list_ledger_entries(
            employee["id"], hr_admin_headers
        ))
        movements = [(e["entry_type"], e["points"]) for e in entries]
        assert ("GRANT_NOMINATION", 3000) in movements
        assert ("HOLD", -1000) in movements
        assert ("SETTLE_REDEEM", -1000) in movements
        assert ("HOLD", -400) in movements
        assert ("REFUND", 400) in movements
        assert_employee_ledger_reconciles(refreshed, entries)
