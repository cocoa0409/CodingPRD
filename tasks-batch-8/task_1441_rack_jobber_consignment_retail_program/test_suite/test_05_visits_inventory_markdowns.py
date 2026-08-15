"""Route service visits (day-of discipline, count submission, confirm/dispute
cycles, fiscal caps), the consignment inventory ledger, the scan-driven
reorder cascade, and markdown/vendor-return authorizations."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    apply_markdown,
    approve_markdown,
    assert_balance_ledger_invariant,
    assert_inventory_balance,
    confirm_visit,
    create_service_visit_payload,
    get_agreement,
    get_balance,
    get_markdown,
    get_visit,
    list_balances,
    make_retailer_manager_headers,
    make_route_driver_headers,
    new_active_agreement,
    new_markdown,
    new_program,
    new_route,
    new_service_visit,
    new_store,
    post_matched_sale,
    post_scan,
    run_restock_visit,
    set_clock,
    setup_shop,
    setup_stocked_shop,
    submit_visit_counts,
    check_in_visit,
    validate_error,
    validate_paginated,
    validate_success,
    visit_count_line,
)

ADMIN = TEST_USERS["jobber_admin_headers"]


class TestVisitDayOfDiscipline:
    def test_checkin_day_before_rejected(self, api):
        """PRD section 3.5: "Check-in — `SCHEDULED` to `CHECKED_IN` — is
        performed by the assigned `RouteDriver`, requires the logical clock
        date to equal `scheduled_date` exactly (a visit attempted on any other
        day is rejected with `ERR_VISIT_WINDOW_CLOSED`), and requires the
        agreement to still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)."

        Design: Corner/validations/visit_checkin_wrong_day_rejected
        """
        ctx = setup_shop(with_product=False, with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-02")
        res = api.check_in_service_visit(
            visit["id"], make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_VISIT_WINDOW_CLOSED)
        assert get_visit(visit["id"])["status"] == "SCHEDULED"

    def test_visit_swept_to_missed(self, api):
        """PRD section 2.6: "A scheduled service visit whose `scheduled_date`
        has passed without a check-in becomes `MISSED`."

        Design: Corner/state_machines/visit_auto_missed_on_clock_sweep
        """
        ctx = setup_shop(with_product=False, with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        set_clock("2026-08-03T00:00:00Z")
        assert get_visit(visit["id"])["status"] == "MISSED"


class TestVisitOwnership:
    def test_driver_not_assigned_forbidden(self, api):
        """PRD section 2.8: "Ownership identity: a `RetailerManager` must match
        the acting agreement's store, failing with
        `ERR_STORE_MANAGER_MISMATCH` (HTTP 403); a `RouteDriver` must match the
        visit route's assigned driver, failing with `ERR_DRIVER_NOT_ASSIGNED`
        (HTTP 403)."

        Design: Corner/validations/driver_not_assigned_forbidden
        """
        ctx = setup_shop(with_product=False, with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        res = api.check_in_service_visit(
            visit["id"], make_route_driver_headers("drv-2"))
        validate_error(res, ApiErrorId.ERR_DRIVER_NOT_ASSIGNED)
        assert get_visit(visit["id"])["status"] == "SCHEDULED"

    def test_store_manager_mismatch_forbidden(self, api):
        """PRD section 2.8: "Ownership identity: a `RetailerManager` must match
        the acting agreement's store, failing with
        `ERR_STORE_MANAGER_MISMATCH` (HTTP 403); a `RouteDriver` must match the
        visit route's assigned driver, failing with `ERR_DRIVER_NOT_ASSIGNED`
        (HTTP 403)."
        PRD section 2.1: "When `X-User-Role` is `RetailerManager`, `X-User-ID`
        is the `id` of the acting `Store`".

        Design: Corner/validations/store_manager_mismatch_forbidden
        """
        ctx = setup_shop(with_route=True)
        store_b = new_store(name="Own B", store_code="OB1")
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        check_in_visit(visit["id"])
        submit_visit_counts(
            visit["id"],
            [visit_count_line(ctx["product"]["id"], 0, 5)])
        res = api.confirm_service_visit(
            visit["id"], make_retailer_manager_headers(store_b["id"]))
        validate_error(res, ApiErrorId.ERR_STORE_MANAGER_MISMATCH)


class TestVisitConfirmFromState:
    def test_confirm_before_counts_rejected(self, api):
        """PRD section 3.5: "Confirmation by the store's `RetailerManager` —
        `COUNTS_SUBMITTED` to `CONFIRMED`, a terminal state — requires the
        manager identity match and an `ACTIVE` agreement."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/visit_confirm_before_counts_rejected
        """
        ctx = setup_shop(with_product=False, with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        check_in_visit(visit["id"])
        res = api.confirm_service_visit(
            visit["id"], make_retailer_manager_headers(ctx["store"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_visit(visit["id"])["status"] == "CHECKED_IN"


class TestVisitSchedulingGates:
    def test_route_program_mismatch_rejected(self, api):
        """PRD section 3.5: "Scheduling one takes `route_id`,
        `store_agreement_id`, and `scheduled_date`; the agreement must be
        `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) and must belong to the
        route's program (`ERR_ROUTE_PROGRAM_MISMATCH` otherwise)."

        Design: Corner/validations/route_program_mismatch_rejected
        """
        set_clock()
        program_a = new_program(name="RouteA")
        program_b = new_program(name="RouteB")
        store = new_store(name="RMStore", store_code="RM1")
        agreement_b = new_active_agreement(program_b["id"], store["id"])
        route_a = new_route(program_a["id"])
        res = api.create_service_visit(
            create_service_visit_payload(route_a["id"], agreement_b["id"]),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_ROUTE_PROGRAM_MISMATCH)


class TestRestockValueCap:
    def test_cap_equality_allowed(self, api):
        """PRD section 3.5: "Submission is gated by the agreement's fiscal cap:
        the sum, across lines, of each line's `restock_units` multiplied by its
        product's `jobber_cost_cents` may not exceed `restock_value_cap_cents`,
        and a submission that breaks the cap is rejected with
        `ERR_RESTOCK_VALUE_CAP_EXCEEDED`."

        Design: Corner/calculations/restock_value_cap_equality_allowed
        """
        ctx = setup_shop(agreement_overrides={"restock_value_cap_cents": 500},
                         with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        check_in_visit(visit["id"])
        submitted = submit_visit_counts(
            visit["id"],
            [visit_count_line(ctx["product"]["id"], 0, 5)])
        assert submitted["status"] == "COUNTS_SUBMITTED", (
            "5 * 100 == 500 == cap: only strict excess rejects")
        assert submitted["applied_restock_value_cents"] == 500

    def test_cap_exceeded_rejected(self, api):
        """PRD section 3.5: "Submission is gated by the agreement's fiscal cap:
        the sum, across lines, of each line's `restock_units` multiplied by its
        product's `jobber_cost_cents` may not exceed `restock_value_cap_cents`,
        and a submission that breaks the cap is rejected with
        `ERR_RESTOCK_VALUE_CAP_EXCEEDED`."

        Design: Corner/validations/restock_value_cap_exceeded_rejected
        """
        ctx = setup_shop(agreement_overrides={"restock_value_cap_cents": 500},
                         with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        check_in_visit(visit["id"])
        res = api.submit_visit_counts(
            visit["id"],
            {"lines": [visit_count_line(ctx["product"]["id"], 0, 6)]},
            make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_RESTOCK_VALUE_CAP_EXCEEDED)
        assert get_visit(visit["id"])["status"] == "CHECKED_IN"


class TestSubmitCountsPrecedence:
    def _scheduled_visit_with_tight_cap(self, api):
        ctx = setup_shop(agreement_overrides={"restock_value_cap_cents": 500},
                         with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        return ctx, visit

    def test_state_gate_outranks_fiscal_cap(self, api):
        """PRD section 2.8: "Every request is evaluated against a fixed
        precedence ladder, and the first failing check wins — a failure higher
        on the ladder masks every check below it."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)." — and "Fiscal caps close the ladder:
        the restock value cap (`ERR_RESTOCK_VALUE_CAP_EXCEEDED`, HTTP 409),
        the markdown credit cap (`ERR_MARKDOWN_CAP_EXCEEDED`, HTTP 409), and
        the minimum payout (`ERR_PAYOUT_BELOW_MINIMUM`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/submit_counts_state_beats_fiscal
        """
        ctx, visit = self._scheduled_visit_with_tight_cap(api)
        # Visit still SCHEDULED (never checked in) AND restock value 600 > 500.
        res = api.submit_visit_counts(
            visit["id"],
            {"lines": [visit_count_line(ctx["product"]["id"], 0, 6)]},
            make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_visit(visit["id"])
        assert after["status"] == "SCHEDULED"
        assert after["total_restock_units"] == 0, "no totals were frozen"

    def test_fiscal_cap_fires_once_state_is_valid(self, api):
        """PRD section 3.5: "Submission is gated by the agreement's fiscal cap:
        the sum, across lines, of each line's `restock_units` multiplied by its
        product's `jobber_cost_cents` may not exceed `restock_value_cap_cents`,
        and a submission that breaks the cap is rejected with
        `ERR_RESTOCK_VALUE_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_counts_state_beats_fiscal
        """
        ctx, visit = self._scheduled_visit_with_tight_cap(api)
        check_in_visit(visit["id"])
        res = api.submit_visit_counts(
            visit["id"],
            {"lines": [visit_count_line(ctx["product"]["id"], 0, 6)]},
            make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_RESTOCK_VALUE_CAP_EXCEEDED)
        assert get_visit(visit["id"])["status"] == "CHECKED_IN"


class TestVisitDisputeRecountCycle:
    def _submitted_visit(self, api):
        ctx = setup_shop(with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        check_in_visit(visit["id"])
        submitted = submit_visit_counts(
            visit["id"],
            [visit_count_line(ctx["product"]["id"], 0, 40)])
        return ctx, visit["id"], submitted

    def test_recount_clears_frozen_lines(self, api):
        """PRD section 3.5: "A disputed visit returns to the driver through
        recount — `DISPUTED` back to `CHECKED_IN` — which clears
        `submitted_lines` and every computed total so the driver may count and
        submit afresh."

        Design: Difficulty/non_linear_state_machine/visit_counts_dispute_recount_cycle
        """
        ctx, visit_id, submitted = self._submitted_visit(api)
        assert submitted["status"] == "COUNTS_SUBMITTED"
        assert submitted["total_restock_units"] == 40
        disputed = validate_success(api.dispute_service_visit(
            visit_id, {"reason": "count mismatch at shelf"},
            make_retailer_manager_headers(ctx["store"]["id"])), 200)
        assert disputed["status"] == "DISPUTED"
        recount = validate_success(
            api.recount_service_visit(visit_id,
                                      make_route_driver_headers("drv-1")), 200)
        assert recount["status"] == "CHECKED_IN"
        assert not recount["submitted_lines"], "recount clears submitted_lines"
        assert recount["total_restock_units"] == 0
        assert recount["total_counted_units"] == 0
        resubmitted = submit_visit_counts(
            visit_id, [visit_count_line(ctx["product"]["id"], 0, 40)])
        assert resubmitted["status"] == "COUNTS_SUBMITTED"
        assert resubmitted["total_restock_units"] == 40, (
            "the second submit re-froze the lines")
        confirmed = confirm_visit(visit_id, ctx["store"]["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["version"] == submitted["version"] + 4, (
            "each transition increments the visit version by exactly one")

    def test_restock_posts_exactly_once_after_cycle(self, api):
        """PRD section 3.5: "Confirmation rewrites the inventory ledger: for
        each line, the balance for that agreement and product is created if
        absent, and its `on_hand_units` is set to `counted_units` plus
        `restock_units` — the physical count resets the book — while
        `lifetime_delivered_units` grows by the line's `restock_units` and the
        stock posture of §3.6 is recomputed."

        Design: Difficulty/non_linear_state_machine/visit_counts_dispute_recount_cycle
        """
        ctx, visit_id, _ = self._submitted_visit(api)
        validate_success(api.dispute_service_visit(
            visit_id, {"reason": "count mismatch at shelf"},
            make_retailer_manager_headers(ctx["store"]["id"])), 200)
        validate_success(api.recount_service_visit(
            visit_id, make_route_driver_headers("drv-1")), 200)
        submit_visit_counts(
            visit_id, [visit_count_line(ctx["product"]["id"], 0, 40)])
        confirm_visit(visit_id, ctx["store"]["id"])
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance is not None
        assert_inventory_balance(balance)
        assert balance["on_hand_units"] == 40
        assert balance["lifetime_delivered_units"] == 40, (
            "restock posted exactly once, on the confirm")


class TestVisitConfirmAgreementGate:
    def _counts_submitted_visit(self, api):
        ctx = setup_shop(with_route=True)
        visit = new_service_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                                  scheduled_date="2026-08-01")
        check_in_visit(visit["id"])
        submit_visit_counts(
            visit["id"],
            [visit_count_line(ctx["product"]["id"], 0, 10)])
        return ctx, visit["id"]

    def test_confirm_blocked_when_agreement_suspended(self, api):
        """PRD section 3.5: "Confirmation by the store's `RetailerManager` —
        `COUNTS_SUBMITTED` to `CONFIRMED`, a terminal state — requires the
        manager identity match and an `ACTIVE` agreement."

        Design: Difficulty/cross_entity_state_dependency/visit_confirm_requires_agreement_active
        """
        ctx, visit_id = self._counts_submitted_visit(api)
        validate_success(api.suspend_agreement(
            ctx["agreement"]["id"], {"reason": "shrink investigation"}, ADMIN),
            200)
        res = api.confirm_service_visit(
            visit_id, make_retailer_manager_headers(ctx["store"]["id"]))
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        assert get_visit(visit_id)["status"] == "COUNTS_SUBMITTED"
        assert list_balances(ctx["agreement"]["id"],
                             ctx["product"]["id"]) == [], (
            "no InventoryBalance is created while the confirm is blocked")

    def test_confirm_succeeds_after_resume(self, api):
        """PRD section 3.1: "Resumption by a `JobberAdmin` returns a
        `SUSPENDED` agreement to `ACTIVE`."
        PRD section 3.5: "Confirmation by the store's `RetailerManager` —
        `COUNTS_SUBMITTED` to `CONFIRMED`, a terminal state — requires the
        manager identity match and an `ACTIVE` agreement."

        Design: Difficulty/cross_entity_state_dependency/visit_confirm_requires_agreement_active
        """
        ctx, visit_id = self._counts_submitted_visit(api)
        validate_success(api.suspend_agreement(
            ctx["agreement"]["id"], {"reason": "shrink investigation"}, ADMIN),
            200)
        validate_success(api.resume_agreement(ctx["agreement"]["id"], ADMIN),
                         200)
        confirmed = confirm_visit(visit_id, ctx["store"]["id"])
        assert confirmed["status"] == "CONFIRMED"
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 10
        assert balance["lifetime_delivered_units"] == 10


class TestBalanceCreationAndReconciliation:
    def test_balance_auto_created_on_first_confirm(self, api):
        """PRD section 3.6: "The InventoryBalance for the scan's agreement and
        product is created on first use — the first confirmed restock or the
        first matched scan for the pair".
        PRD section 3.6: "Each balance's `reorder_point_units` equals its
        product's `units_per_facing`, and its derived `stock_posture` reads
        `DEPLETED` when on-hand is zero or below, `LOW` when on-hand is
        positive but no greater than the reorder point, and `NORMAL` above it."

        Design: Corner/entities/inventory_balance_auto_created_on_confirm
        """
        ctx = setup_shop(with_route=True,
                         product_overrides={"units_per_facing": 12})
        assert list_balances(ctx["agreement"]["id"]) == []
        run_restock_visit(ctx["route"]["id"], ctx["agreement"]["id"],
                          ctx["store"]["id"], ctx["product"]["id"], 40)
        balances, meta = validate_paginated(api.list_inventory_balances(
            ADMIN, params={"store_agreement_id": ctx["agreement"]["id"],
                           "product_id": ctx["product"]["id"]}))
        assert meta["total_count"] == 1
        balance = balances[0]
        assert_inventory_balance(balance)
        assert balance["on_hand_units"] == 40
        assert balance["lifetime_delivered_units"] == 40
        assert balance["reorder_point_units"] == 12
        assert balance["stock_posture"] == "NORMAL"

    def test_counters_reconcile_after_mixed_scans(self, api):
        """PRD section 3.6: "The balance obeys one invariant: on hand equals
        delivered minus scanned plus customer returns minus shrink minus vendor
        returns, and it may legitimately go negative when unscanned shelf stock
        sells through."
        PRD section 3.6: "A `SALE` decrements on-hand by its `quantity` and
        adds to `lifetime_scanned_units`; a `RETURN` increments on-hand and
        adds to `lifetime_customer_return_units`; a `VOID` reverses its
        target's units and counters."

        Design: Corner/cross_cutting_complexity/derived_field_reconciliation_after_mixed_scans
        """
        ctx = setup_stocked_shop(restock_units=40)
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 15, "2026-08-01T10:00:00Z",
                          client_event_id="rc-s")
        post_scan(ctx["agreement"]["id"], ctx["product"]["id"],
                  ctx["store"]["id"], event_type="RETURN", quantity=3,
                  scanned_at="2026-08-01T11:00:00Z", client_event_id="rc-r")
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 28, "40 - 15 + 3"
        assert balance["lifetime_delivered_units"] == 40
        assert balance["lifetime_scanned_units"] == 15
        assert balance["lifetime_customer_return_units"] == 3
        assert balance["lifetime_shrink_units"] == 0
        assert balance["lifetime_rma_units"] == 0
        assert balance["stock_posture"] == "NORMAL"
        assert_balance_ledger_invariant(balance)


class TestReorderCascade:
    def _cascade_scenario(self, api):
        ctx = setup_shop(with_route=True,
                         product_overrides={"units_per_facing": 12})
        ctx["confirmed_visit"] = run_restock_visit(
            ctx["route"]["id"], ctx["agreement"]["id"],
            ctx["store"]["id"], ctx["product"]["id"], 20)
        future_visit = new_service_visit(
            ctx["route"]["id"], ctx["agreement"]["id"],
            scheduled_date="2026-08-03")
        return ctx, future_visit

    def test_scan_below_reorder_point_updates_balance(self, api):
        """PRD section 3.6: "its derived `stock_posture` reads `DEPLETED` when
        on-hand is zero or below, `LOW` when on-hand is positive but no greater
        than the reorder point, and `NORMAL` above it."

        Design: Difficulty/transitive_cascade/scan_match_reorder_cascade
        """
        ctx, _ = self._cascade_scenario(api)
        scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            16, "2026-08-01T11:00:00Z", client_event_id="s-drop")
        assert scan["status"] == "MATCHED"
        assert scan["unit_price_cents"] == 200
        assert scan["line_value_cents"] == 3200
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 4
        assert balance["stock_posture"] == "LOW", "0 < 4 <= reorder point 12"

    def test_reorder_cascade_flags_earliest_scheduled_visit(self, api):
        """PRD section 3.6: "When a matched scan leaves a balance's
        `on_hand_units` at or below `reorder_point_units`, the system selects
        the agreement's `SCHEDULED` service visit with the earliest
        `scheduled_date` on or after the clock date, breaking ties toward the
        earliest visit `created_at`, and sets that visit's `auto_restock_flag`
        to true with `suggested_restock_units` equal to twice the reorder point
        minus the current on-hand, floored at zero — enough to restock to two
        full reorder points."

        Design: Difficulty/transitive_cascade/scan_match_reorder_cascade
        """
        ctx, future_visit = self._cascade_scenario(api)
        post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            16, "2026-08-01T11:00:00Z", client_event_id="s-drop")
        flagged = get_visit(future_visit["id"])
        assert flagged["auto_restock_flag"] is True
        assert flagged["suggested_restock_units"] == 20, (
            "max(0, 2 * 12 - 4)")
        confirmed = get_visit(ctx["confirmed_visit"]["id"])
        assert confirmed["auto_restock_flag"] is False, (
            "the selector never mutates a non-SCHEDULED visit")


class TestVisitFkFiltering:
    def test_list_visits_filtered_by_agreement(self, api):
        """PRD section 3.5: "Visit listings may be filtered by `route_id`,
        `store_agreement_id`, or `status`."

        Design: Corner/endpoints/list_filter_by_fk_scoped
        """
        set_clock()
        program = new_program(name="FilterFK")
        store_a = new_store(name="FK A", store_code="FA1")
        store_b = new_store(name="FK B", store_code="FB1")
        agr_a = new_active_agreement(program["id"], store_a["id"])
        agr_b = new_active_agreement(program["id"], store_b["id"])
        route = new_route(program["id"])
        visit_a = new_service_visit(route["id"], agr_a["id"], "2026-08-01")
        visit_b = new_service_visit(route["id"], agr_b["id"], "2026-08-01")
        data, meta = validate_paginated(api.list_service_visits(
            ADMIN, params={"store_agreement_id": agr_a["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == visit_a["id"]
        assert visit_b["id"] not in [row["id"] for row in data]


class TestMarkdownAuthorizations:
    def test_markdown_credit_cap_exceeded_rejected(self, api):
        """PRD section 3.8: "The credit is capped per period: it may not exceed
        the agreement's `markdown_cap_pct_of_gross` multiplied by the gross
        scanned sales of the settlement period containing the clock's current
        date, rounded half-up, and an application breaking the cap is rejected
        with `ERR_MARKDOWN_CAP_EXCEEDED`."

        Design: Corner/validations/markdown_cap_exceeded_rejected
        """
        ctx = setup_shop(agreement_overrides={
            "markdown_liability": "SHARED", "markdown_jobber_share_pct": 0.5,
            "markdown_cap_pct_of_gross": 0.08})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 5, "2026-08-01T09:00:00Z",
                          client_event_id="md-1")
        markdown = new_markdown(ctx["agreement"]["id"], ctx["product"]["id"],
                                auth_type="MARKDOWN", units=2,
                                markdown_price_cents=100)
        approve_markdown(markdown["id"], ctx["store"]["id"])
        res = api.apply_markdown_authorization(markdown["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_MARKDOWN_CAP_EXCEEDED)
        # raw credit round((200 - 100) * 2 * 0.5) == 100 > round(0.08 * 1000) == 80
        assert get_markdown(markdown["id"])["status"] == "APPROVED"

    def test_rma_apply_insufficient_stock_rejected(self, api):
        """PRD section 3.8: "For `RETURN_TO_VENDOR`, the balance must
        physically cover the pull: `on_hand_units` below `units` is rejected
        with `ERR_RANGE_INVALID`; otherwise on-hand falls by `units`,
        `lifetime_rma_units` grows by `units`, and `credit_cents` is 0."

        Design: Corner/validations/rma_apply_insufficient_stock_rejected
        """
        ctx = setup_shop()
        markdown = new_markdown(ctx["agreement"]["id"], ctx["product"]["id"],
                                auth_type="RETURN_TO_VENDOR", units=10)
        approve_markdown(markdown["id"], ctx["store"]["id"])
        res = api.apply_markdown_authorization(markdown["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_RANGE_INVALID)
        assert get_markdown(markdown["id"])["status"] == "APPROVED"

    def test_approved_markdown_expires_on_sweep(self, api):
        """PRD section 3.8: "Approval starts a fourteen-day fuse — an approved
        authorization still unapplied when the clock date passes fourteen days
        after the `approved_at` date is swept to `EXPIRED`, also terminal."

        Design: Corner/state_machines/markdown_auto_expire_on_clock_sweep
        """
        ctx = setup_shop()
        markdown = new_markdown(ctx["agreement"]["id"], ctx["product"]["id"],
                                auth_type="MARKDOWN", units=1,
                                markdown_price_cents=180)
        approve_markdown(markdown["id"], ctx["store"]["id"])
        set_clock("2026-08-16T00:00:00Z")
        after = get_markdown(markdown["id"])
        assert after["status"] == "EXPIRED", (
            "approved 2026-08-01 + 14 days < 2026-08-16")

    def test_restock_then_rma_units_conserved(self, api):
        """PRD section 3.6: "The balance obeys one invariant: on hand equals
        delivered minus scanned plus customer returns minus shrink minus vendor
        returns, and it may legitimately go negative when unscanned shelf stock
        sells through."
        PRD section 3.8: "For `RETURN_TO_VENDOR`, the balance must physically
        cover the pull: `on_hand_units` below `units` is rejected with
        `ERR_RANGE_INVALID`; otherwise on-hand falls by `units`,
        `lifetime_rma_units` grows by `units`, and `credit_cents` is 0."

        Design: Difficulty/compensating_invariant/restock_then_rma_units_conserved
        """
        ctx = setup_stocked_shop(restock_units=40)
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 40
        assert balance["lifetime_delivered_units"] == 40
        markdown = new_markdown(ctx["agreement"]["id"], ctx["product"]["id"],
                                auth_type="RETURN_TO_VENDOR", units=40)
        approve_markdown(markdown["id"], ctx["store"]["id"])
        applied = apply_markdown(markdown["id"])
        assert applied["status"] == "APPLIED"
        assert applied["credit_cents"] == 0, "RMA moves units, not money"
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 0, (
            "the compensating pull restores the pre-pair on-hand")
        assert balance["lifetime_rma_units"] == 40
        assert balance["lifetime_scanned_units"] == 0
        assert balance["lifetime_shrink_units"] == 0
        assert balance["lifetime_customer_return_units"] == 0
        assert_balance_ledger_invariant(balance)

    def test_rma_pair_leaves_no_residual_charge(self, api):
        """PRD section 3.8: "For `RETURN_TO_VENDOR`, the balance must
        physically cover the pull: `on_hand_units` below `units` is rejected
        with `ERR_RANGE_INVALID`; otherwise on-hand falls by `units`,
        `lifetime_rma_units` grows by `units`, and `credit_cents` is 0."

        Design: Difficulty/compensating_invariant/restock_then_rma_units_conserved
        """
        ctx = setup_stocked_shop(restock_units=40)
        markdown = new_markdown(ctx["agreement"]["id"], ctx["product"]["id"],
                                auth_type="RETURN_TO_VENDOR", units=40)
        approve_markdown(markdown["id"], ctx["store"]["id"])
        apply_markdown(markdown["id"])
        agreement = get_agreement(ctx["agreement"]["id"])
        assert agreement["cumulative_delivered_units"] == 40
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 0
        assert_balance_ledger_invariant(balance)

