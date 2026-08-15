"""Disputes: the inclusive 30-day filing window, error precedence, the
uphold cascade into re-audit, and the signed billing invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_allocation,
    add_records_request,
    approve_estimated,
    assert_billing_signed_sum_invariant,
    assign_auditor,
    complete_appointment,
    file_dispute,
    first_billing,
    get_success_data,
    issue_result,
    make_audit_manager_headers,
    receive_request,
    refresh_work_order,
    result_billings,
    schedule_appointment,
    set_clock,
    setup_dispute_under_review,
    setup_issued_standard_result,
    setup_noncompliant_work_order,
    start_review,
    submit_draft,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]
MGR2 = make_audit_manager_headers("mgr-2")


class TestDisputeWindow:
    def test_dispute_filed_at_exact_deadline_succeeds(self, api):
        """PRD: "The result must be `ISSUED`, and the filing window is thirty
        days: the logical clock must be at or before `issued_at` plus thirty
        days — filing exactly at the deadline succeeds, one second later draws
        `ERR_DISPUTE_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/dispute_window_thirty_days_exact
        """
        ctx = setup_issued_standard_result(policy_number="WC-1200",
                                           experience_mod_factor=1.00,
                                           issue_clock="2026-08-15T00:00:00Z")
        # issued_at 2026-08-15T00:00:00Z -> deadline 2026-09-14T00:00:00Z.

        dispute = file_dispute(ctx, clock="2026-09-14T00:00:00Z")
        assert dispute["status"] == "FILED", (
            "Filing at exactly issued_at + 30 days must succeed")
        assert dispute["audit_result_id"] == ctx["result"]["id"]

    def test_dispute_one_second_past_deadline_rejected(self, api):
        """PRD: "The result must be `ISSUED`, and the filing window is thirty
        days: the logical clock must be at or before `issued_at` plus thirty
        days — filing exactly at the deadline succeeds, one second later draws
        `ERR_DISPUTE_WINDOW_CLOSED`."
        PRD: "**Overruling** moves the dispute to `OVERRULED`, returns the
        result `DISPUTED → ISSUED`, and returns the work order to `BILLED` or
        `ESTIMATED_BILLED` according to the result's variant, with a version
        increment."

        Design: Difficulty/boundary_precision_check/dispute_window_thirty_days_exact
        """
        ctx = setup_issued_standard_result(policy_number="WC-1200",
                                           experience_mod_factor=1.00,
                                           issue_clock="2026-08-15T00:00:00Z")
        dispute = file_dispute(ctx, clock="2026-09-14T00:00:00Z")
        assert dispute["status"] == "FILED"
        start_review(ctx, reviewer="mgr-2")
        overruled = get_success_data(api.overrule_dispute(dispute["id"], MGR2))
        assert overruled["status"] == "OVERRULED"
        restored = validate_success(api.get_audit_result(ctx["result"]["id"],
                                                         MANAGER))
        assert restored["status"] == "ISSUED"

        set_clock("2026-09-14T00:00:01Z")
        late = api.file_dispute(ctx["result"]["id"], {"grounds": "OTHER"},
                                ctx["insured_headers"])
        validate_error(late, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)


class TestDisputeErrorPrecedence:
    def _setup_disputed_result(self, api, second_clock):
        """WC-1000 ISSUED at 2026-08-15, disputed 2026-09-01; clock moved to
        second_clock for the second filing attempt."""
        ctx = setup_issued_standard_result(policy_number="WC-1000",
                                           experience_mod_factor=1.00,
                                           issue_clock="2026-08-15T00:00:00Z")
        file_dispute(ctx, clock="2026-09-01T00:00:00Z")
        set_clock(second_clock)
        return ctx

    def test_state_violation_wins_over_closed_window(self, api):
        """PRD: "When several checks could reject the same request, the server
        evaluates them in a fixed order and returns the **first** matching
        failure:"
        PRD: "7. **State legality** — the target resource is in a from-state
        its state machine permits for the attempted transition, and terminal
        states reject everything; failure yields `ERR_INVALID_STATE_TRANSITION`
        (409)."
        PRD: "9. **Time windows** — appointment placement within the post-term
        window and dispute filing within its deadline; failures yield
        `ERR_APPOINTMENT_OUTSIDE_WINDOW` or `ERR_DISPUTE_WINDOW_CLOSED` (both
        409)."

        Design: Difficulty/priority_pair_validation_conflict/dispute_state_vs_temporal_priority
        """
        ctx = self._setup_disputed_result(api, "2026-09-20T00:00:00Z")
        # Window closed at 2026-09-14 AND the result is already DISPUTED.

        resp = api.file_dispute(ctx["result"]["id"], {"grounds": "OTHER"},
                                ctx["insured_headers"])
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert error["error_id"] != "ERR_DISPUTE_WINDOW_CLOSED", (
            "The state failure (priority 7) must be reported before the "
            "temporal failure (priority 9)")

    def test_second_dispute_rejected_on_state_alone(self, api):
        """PRD: "An insured who disagrees with an issued result files a
        dispute, choosing `grounds` of `CLASSIFICATION_ERROR`,
        `PAYROLL_ERROR`, `SUBCONTRACTOR_INCLUSION`, `CERT_REVIEW_ERROR`, or
        `OTHER`."
        PRD: "The result must be `ISSUED`, and the filing window is thirty
        days: the logical clock must be at or before `issued_at` plus thirty
        days — filing exactly at the deadline succeeds, one second later draws
        `ERR_DISPUTE_WINDOW_CLOSED`."
        PRD: "7. **State legality** — the target resource is in a from-state
        its state machine permits for the attempted transition, and terminal
        states reject everything; failure yields `ERR_INVALID_STATE_TRANSITION`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/dispute_state_vs_temporal_priority
        """
        ctx = self._setup_disputed_result(api, "2026-09-10T00:00:00Z")
        # Clock still inside the window (ends 2026-09-14); only the state
        # check can fail.

        resp = api.file_dispute(ctx["result"]["id"], {"grounds": "OTHER"},
                                ctx["insured_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestUpholdCascade:
    def test_uphold_supersedes_result_and_cancels_billing(self, api):
        """PRD: "**Upholding** moves the dispute to `UPHELD`, moves the result
        `DISPUTED → SUPERSEDED` (terminal), cancels every billing of that
        result still `ISSUED` or `PAST_DUE` as compensation, moves the work
        order to terminal `SUPERSEDED_BY_REAUDIT` with a version increment"

        Design: Difficulty/non_linear_state_machine/work_order_billed_disputed_superseded_reaudit_cycle
        """
        ctx = setup_dispute_under_review(policy_number="WC-600",
                                         reviewer="mgr-2")
        billing = ctx["billing"]
        assert billing["status"] == "ISSUED"

        upheld = get_success_data(api.uphold_dispute(ctx["dispute"]["id"],
                                                     MGR2))
        assert upheld["status"] == "UPHELD"

        result = validate_success(api.get_audit_result(ctx["result"]["id"],
                                                       MANAGER))
        assert result["status"] == "SUPERSEDED"
        bill_after = validate_success(
            api.get_billing_transaction(billing["id"], MANAGER))
        assert bill_after["status"] == "CANCELLED", (
            "Compensation: the superseded result's open billing is cancelled")
        wo = refresh_work_order(ctx)
        assert wo["status"] == "SUPERSEDED_BY_REAUDIT"

    def test_uphold_spawns_reaudit_work_order(self, api):
        """PRD: "and spawns the corrective audit: a brand-new work order with
        `audit_type` `REAUDIT`, status `SELECTED`, `reaudit_of_work_order_id`
        pointing at the superseded order, `selection_run_id` null (re-audits
        are born of disputes, not selection runs), the audit period copied
        from the policy, and `assigned_auditor_id` null."

        Design: Difficulty/non_linear_state_machine/work_order_billed_disputed_superseded_reaudit_cycle
        """
        ctx = setup_dispute_under_review(policy_number="WC-600",
                                         reviewer="mgr-2")
        get_success_data(api.uphold_dispute(ctx["dispute"]["id"], MGR2))

        reaudits, meta = validate_paginated(
            api.list_work_order_reaudits(ctx["work_order"]["id"], MANAGER))
        assert meta["total_count"] == 1, "Exactly one re-audit order spawns"
        reaudit = reaudits[0]
        assert reaudit["audit_type"] == "REAUDIT"
        assert reaudit["status"] == "SELECTED"
        assert reaudit["reaudit_of_work_order_id"] == ctx["work_order"]["id"]
        assert reaudit["selection_run_id"] is None
        assert reaudit["assigned_auditor_id"] is None


class TestEstimatedResultUpholdCascade:
    def _setup_estimated_dispute_under_review(self, api):
        """WC-900: estimated audit issued at 2026-08-17, disputed 2026-08-20,
        under review by mgr-1 (the approver was mgr-2)."""
        ctx = setup_noncompliant_work_order(policy_number="WC-900")
        approve_estimated(ctx, approver="mgr-2")
        file_dispute(ctx, grounds="CERT_REVIEW_ERROR",
                     clock="2026-08-20T00:00:00Z")
        start_review(ctx, reviewer="mgr-1")
        return ctx

    def test_estimated_result_uphold_cascades(self, api):
        """PRD: "**Upholding** moves the dispute to `UPHELD`, moves the result
        `DISPUTED → SUPERSEDED` (terminal), cancels every billing of that
        result still `ISSUED` or `PAST_DUE` as compensation, moves the work
        order to terminal `SUPERSEDED_BY_REAUDIT` with a version increment"

        Design: Difficulty/transitive_cascade/dispute_upheld_result_billing_workorder_reaudit_chain
        """
        ctx = self._setup_estimated_dispute_under_review(api)
        billing = ctx["billing"]

        upheld = get_success_data(api.uphold_dispute(
            ctx["dispute"]["id"], make_audit_manager_headers("mgr-1")))
        assert upheld["status"] == "UPHELD"

        result = validate_success(api.get_audit_result(ctx["result"]["id"],
                                                       MANAGER))
        assert result["status"] == "SUPERSEDED", "Hop 1: result superseded"
        bill_after = validate_success(
            api.get_billing_transaction(billing["id"], MANAGER))
        assert bill_after["status"] == "CANCELLED", (
            "Hop 2: the 500000-cent estimated billing is compensated")

    def test_estimated_uphold_spawns_reaudit_and_closes_graph(self, api):
        """PRD: "**Upholding** moves the dispute to `UPHELD`, moves the result
        `DISPUTED → SUPERSEDED` (terminal), cancels every billing of that
        result still `ISSUED` or `PAST_DUE` as compensation, moves the work
        order to terminal `SUPERSEDED_BY_REAUDIT` with a version increment,
        and spawns the corrective audit: a brand-new work order with
        `audit_type` `REAUDIT`, status `SELECTED`, `reaudit_of_work_order_id`
        pointing at the superseded order, `selection_run_id` null"

        Design: Difficulty/transitive_cascade/dispute_upheld_result_billing_workorder_reaudit_chain
        """
        ctx = self._setup_estimated_dispute_under_review(api)
        get_success_data(api.uphold_dispute(ctx["dispute"]["id"],
                                            make_audit_manager_headers("mgr-1")))

        wo = refresh_work_order(ctx)
        assert wo["status"] == "SUPERSEDED_BY_REAUDIT", "Hop 3: work order"

        reaudits, meta = validate_paginated(
            api.list_work_order_reaudits(ctx["work_order"]["id"], MANAGER))
        assert meta["total_count"] == 1
        assert reaudits[0]["audit_type"] == "REAUDIT"
        assert reaudits[0]["status"] == "SELECTED"

        remaining = [b for b in result_billings(ctx)
                     if b["status"] != "CANCELLED"]
        assert remaining == [], (
            "No non-CANCELLED billing remains for the superseded result")


class TestBillingInvariant:
    def _setup_reaudit_reissued(self, api):
        """WC-1800: original ISSUED (credit 554400), dispute upheld, and the
        spawned REAUDIT order driven through the physical path with identical
        payroll facts and re-issued."""
        ctx = setup_issued_standard_result(policy_number="WC-1800",
                                           issue_clock="2026-08-15T00:00:00Z")
        original_result = ctx["result"]
        original_billing = ctx["billing"]
        file_dispute(ctx, clock="2026-08-20T00:00:00Z")
        start_review(ctx, reviewer="mgr-2")
        get_success_data(api.uphold_dispute(ctx["dispute"]["id"], MGR2))

        reaudits, _ = validate_paginated(
            api.list_work_order_reaudits(ctx["work_order"]["id"], MANAGER))
        ctx["work_order"] = reaudits[0]
        ctx["requests"] = []
        ctx["result"] = None
        ctx["billing"] = None
        assign_auditor(ctx)
        add_records_request(ctx, "PAYROLL_SUMMARY")
        receive_request(ctx, ctx["requests"][0])
        appt = schedule_appointment(ctx, "2026-08-21T09:00:00Z",
                                    "2026-08-21T11:00:00Z")
        complete_appointment(ctx, appt)
        add_allocation(ctx, 95000, verify=True)
        submit_draft(ctx)
        issue_result(ctx, clock="2026-08-25T00:00:00Z")
        ctx["original_result"] = original_result
        ctx["original_billing"] = original_billing
        first_billing(ctx)
        return ctx

    def test_reaudit_reissue_reproduces_adjustment(self, api):
        """PRD: "The re-audit order then flows through the ordinary pipeline —
        assignment, records, appointment (re-audits take the physical path),
        allocations, draft, issuance — under all the same rules."
        PRD: "computes `adjustment_cents` as earned premium minus the policy's
        `estimated_annual_premium_cents` — a signed figure, positive when more
        premium is due"

        Design: Difficulty/compensating_invariant/billing_signed_sum_matches_latest_result_adjustment
        """
        ctx = self._setup_reaudit_reissued(api)

        original_billing = validate_success(
            api.get_billing_transaction(ctx["original_billing"]["id"], MANAGER))
        assert original_billing["status"] == "CANCELLED", (
            "The superseded result's billing was compensated at uphold")

        result2 = ctx["result"]
        assert result2["status"] == "ISSUED"
        assert result2["adjustment_cents"] == -554400, (
            "Identical payroll facts reproduce identical figures")

        billing2 = ctx["billing"]
        assert billing2["type"] == "RETURN_PREMIUM_CREDIT"
        assert billing2["amount_cents"] == 554400

    def test_billing_signed_sum_matches_latest_result_adjustment(self, api):
        """PRD: "One fiscal invariant survives all of this: across all of a
        policy's work orders, the signed sum of non-cancelled billing amounts
        — invoices counting positive, credits negative — always equals the
        `adjustment_cents` of the policy's latest issued, non-superseded
        result."

        Design: Difficulty/compensating_invariant/billing_signed_sum_matches_latest_result_adjustment
        """
        ctx = self._setup_reaudit_reissued(api)

        all_billings = result_billings(ctx, result=ctx["original_result"]) + \
            result_billings(ctx)
        assert_billing_signed_sum_invariant(all_billings, -554400)
