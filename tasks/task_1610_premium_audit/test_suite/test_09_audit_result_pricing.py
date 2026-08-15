"""Audit-result pricing: provisional vs final input sets, pinned rounding
order, the minimum-premium floor, and experience-mod revision derivation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_allocation,
    add_certificate,
    add_exposure,
    complete_appointment,
    confirm_appointment,
    first_billing,
    get_success_data,
    issue_result,
    list_policy_mod_revisions,
    receive_request,
    refresh_work_order,
    schedule_appointment,
    setup_issued_standard_result,
    setup_selected_work_order,
    set_clock,
    submit_draft,
    close_work_order,
    result_billings,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


def _setup_wc100_through_draft(api):
    """WC-100 PHYSICAL: 8810 (40c) + 5645 (1525c, high-hazard).

    AL-1: 8810 gross 40000, VERIFIED. AL-2: 5645 gross 60000 with documented
    overtime excess 3000 (auditable 57000), left DRAFT at draft time.
    SubCo 10000 on 5645 excluded by a verified full-period certificate;
    RiskyCo 5000 on 5645 included with no certificate.
    """
    ctx = setup_selected_work_order(
        policy_number="WC-100", estimated_annual_premium_cents=2000000,
        minimum_premium_cents=100000, experience_mod_factor=1.20,
        request_types=("PAYROLL_SUMMARY", "SUBCONTRACTOR_LIST"),
        receive_requests=True,
        extra_codes=[{"code": "5645", "description": "Carpentry",
                      "rate_per_100_cents": 1525, "high_hazard": True}])
    cc_b = ctx["ccs"]["5645"]
    appt = schedule_appointment(ctx)
    confirm_appointment(ctx, appt, by_insured=True)
    complete_appointment(ctx, appt)
    al1 = add_allocation(ctx, 40000)
    al2 = add_allocation(ctx, 60000, class_code_id=cc_b["id"],
                         overtime_excess_dollars=3000, overtime_documented=True)
    sub1 = add_exposure(ctx, subcontractor_name="SubCo", payments_dollars=10000,
                        governing_class_code_id=cc_b["id"])
    cert1 = add_certificate(ctx, sub1)
    get_success_data(api.verify_certificate(cert1["id"],
                                            ctx["auditor_headers"]))
    add_exposure(ctx, subcontractor_name="RiskyCo", payments_dollars=5000,
                 governing_class_code_id=cc_b["id"])
    get_success_data(api.verify_payroll_allocation(al1["id"],
                                                   ctx["auditor_headers"]))
    ctx["al1"] = al1
    ctx["al2"] = al2
    return ctx


class TestDualVariantPayrollInclusion:
    def test_provisional_variant_counts_draft_allocations(self, api):
        """PRD: "The **provisional** variant, used at draft time, draws its
        input set from `DRAFT` and `VERIFIED` allocations alike and treats
        `SUBMITTED` certificates as full-coverage exclusions."

        Design: Difficulty/dual_variant_calc/audit_result_provisional_vs_final_payroll_inclusion
        """
        ctx = _setup_wc100_through_draft(api)

        result = submit_draft(ctx)

        # 8810: round_half_up(40000*40/100) = 16000;
        # 5645: round_half_up((57000 DRAFT + 5000 sub)*1525/100) = 945500.
        assert result["manual_premium_cents"] == 961500
        assert result["earned_premium_cents"] == 1153800, (
            "round_half_up(961500 * 1.20) = 1153800")
        assert result["variant"] == "STANDARD"
        assert result["status"] == "PRELIMINARY"

    def test_final_variant_counts_verified_allocations_only(self, api):
        """PRD: "The **final** variant, used at issuance, restricts the input
        set to `VERIFIED` allocations only and counts `VERIFIED` certificates
        only — a certificate still `SUBMITTED` counts as no certificate."
        PRD: "Whenever the adjustment is non-zero, a **BillingTransaction** is
        created with its `type` set to `ADDITIONAL_PREMIUM_INVOICE` when the
        adjustment is positive and `RETURN_PREMIUM_CREDIT` when negative, with
        `amount_cents` equal to the absolute adjustment"

        Design: Difficulty/dual_variant_calc/audit_result_provisional_vs_final_payroll_inclusion
        """
        ctx = _setup_wc100_through_draft(api)
        provisional = submit_draft(ctx)
        assert provisional["manual_premium_cents"] == 961500

        # Replace the DRAFT allocation with a smaller VERIFIED one.
        get_success_data(api.reject_payroll_allocation(ctx["al2"]["id"],
                                                       ctx["auditor_headers"]))
        cc_b = ctx["ccs"]["5645"]
        al3 = add_allocation(ctx, 50000, class_code_id=cc_b["id"], verify=True)
        assert al3["status"] == "VERIFIED"

        result = issue_result(ctx, clock="2026-08-15T00:00:00Z")

        # 8810: 16000; 5645: round_half_up((50000 + 5000)*1525/100) = 838750.
        assert result["manual_premium_cents"] == 854750
        assert result["earned_premium_cents"] == 1025700, (
            "round_half_up(854750 * 1.20) = 1025700 >= minimum 100000")
        assert result["adjustment_cents"] == -974300, (
            "1025700 - 2000000 = -974300")
        assert result["earned_premium_cents"] != \
            provisional["earned_premium_cents"], (
                "Identical payroll facts priced under the two variants must "
                "differ")

        billing = first_billing(ctx)
        assert billing is not None
        assert billing["type"] == "RETURN_PREMIUM_CREDIT"
        assert billing["amount_cents"] == 974300
        assert billing["status"] == "ISSUED"


class TestManualPremiumRoundingOrder:
    def _setup_two_quarter_rate_codes(self, api):
        """WC-300: codes 9150 and 9151 both rated 25c per $100, each with a
        verified 150-dollar allocation on disjoint periods."""
        ctx = setup_selected_work_order(
            policy_number="WC-300", payroll_estimate_dollars=50000,
            minimum_premium_cents=100000, experience_mod_factor=1.00,
            class_code="9150", rate_per_100_cents=25,
            receive_requests=True,
            extra_codes=[{"code": "9151", "description": "Theatrical B",
                          "rate_per_100_cents": 25}])
        add_allocation(ctx, 150, class_code_id=ctx["ccs"]["9150"]["id"],
                       period_start="2026-01-01T00:00:00Z",
                       period_end="2026-03-31T00:00:00Z", verify=True)
        add_allocation(ctx, 150, class_code_id=ctx["ccs"]["9151"]["id"],
                       period_start="2026-04-01T00:00:00Z",
                       period_end="2026-06-30T00:00:00Z", verify=True)
        return ctx

    def test_manual_premium_rounds_per_class_code_then_sums(self, api):
        """PRD: "For each class code the premium is that code's base
        multiplied by its `rate_per_100_cents` and divided by one hundred,
        **rounded half up to integer cents per class code first**, and only
        then summed into `manual_premium_cents`."
        PRD: "The rounding order is pinned — summing the bases first and
        rounding once is forbidden, because the two orders disagree (two codes
        rated at 25 cents with bases of 150 dollars each yield 38 + 38 = 76
        cents under the pinned order, versus 75 cents if summed first)."

        Design: Difficulty/combinatorial_formula/manual_premium_per_code_rounding_order
        """
        ctx = self._setup_two_quarter_rate_codes(api)

        result = submit_draft(ctx)

        assert result["manual_premium_cents"] == 76, (
            "round_half_up(150*25/100) = 38 per class code, summed 38+38 = 76; "
            "the forbidden sum-first order would yield 75")

    def test_manual_premium_rounding_order_holds_at_issuance(self, api):
        """PRD: "For each class code the premium is that code's base
        multiplied by its `rate_per_100_cents` and divided by one hundred,
        **rounded half up to integer cents per class code first**, and only
        then summed into `manual_premium_cents`."
        PRD: "Both draft and issuance price the exposure the same way; only
        the input sets differ."

        Design: Difficulty/combinatorial_formula/manual_premium_per_code_rounding_order
        """
        ctx = self._setup_two_quarter_rate_codes(api)
        submit_draft(ctx)

        result = issue_result(ctx, clock="2026-08-15T00:00:00Z")

        assert result["manual_premium_cents"] == 76, (
            "Both allocations are VERIFIED, so the final variant prices the "
            "same pinned rounding order")
        # earned = max(round_half_up(76 * 1.00), 100000) = 100000 (floor).
        assert result["earned_premium_cents"] == 100000
        assert result["adjustment_cents"] == -500000


class TestEarnedPremiumFloor:
    def test_earned_premium_minimum_floor_branch(self, api):
        """PRD: "The **earned premium** for the `STANDARD` variant multiplies
        the manual premium by the policy's current `experience_mod_factor`,
        rounds half up to integer cents, and then applies the minimum-premium
        floor: the result is the greater of the modified premium and the
        policy's `minimum_premium_cents`."

        Design: Difficulty/combinatorial_formula/earned_premium_mod_floor_variant_branches
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-400", gross_payroll_dollars=100000,
            minimum_premium_cents=300000, experience_mod_factor=1.20)

        result = ctx["result"]
        assert result["manual_premium_cents"] == 40000, (
            "round_half_up(100000 * 40 / 100) = 40000")
        assert result["earned_premium_cents"] == 300000, (
            "max(round_half_up(40000 * 1.20) = 48000, minimum 300000): the "
            "floor branch dominates")
        assert result["adjustment_cents"] == -300000, (
            "300000 - 600000 = -300000")

    def test_zero_variance_creates_no_mod_revision(self, api):
        """PRD: "If the ratio's absolute value is below 0.05 (five percent),
        nothing happens."

        Design: Difficulty/combinatorial_formula/earned_premium_mod_floor_variant_branches
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-400", gross_payroll_dollars=100000,
            minimum_premium_cents=300000, experience_mod_factor=1.20)

        revisions = list_policy_mod_revisions(ctx)
        assert revisions == [], (
            "Audited payroll 100000 vs estimate 100000 gives variance 0.00, "
            "below the five-percent threshold; no ModRevision may be created")


class TestModRevisionEvaluationOrder:
    def test_issued_result_freezes_pre_revision_mod(self, api):
        """PRD: "The mod factor in force at computation time is captured on
        the result as `mod_factor_applied` and is never retroactively changed"
        PRD: "The evaluation order is pinned end to end: final payroll totals
        first, then manual premium, then earned premium with the
        *pre-revision* mod factor, then the billing adjustment, and only then
        the mod revision — the issued result always reflects the mod in force
        at issue time."

        Design: Difficulty/combinatorial_formula/mod_revision_evaluation_order_after_issue
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-500", gross_payroll_dollars=95000,
            experience_mod_factor=1.20)

        result = validate_success(api.get_audit_result(ctx["result"]["id"],
                                                       MANAGER))
        assert result["mod_factor_applied"] == 1.20, (
            "The issued result freezes the pre-revision mod factor")
        assert result["earned_premium_cents"] == 45600, (
            "max(round_half_up(38000 * 1.20), 10000) = 45600")

    def test_mod_revision_draft_computed_from_final_payroll(self, api):
        """PRD: "Otherwise a **ModRevision** is created in `DRAFT`, linked by
        `policy_id` and `source_work_order_id`, recording the policy's
        then-current mod as `prior_mod_factor` and the ratio as
        `payroll_variance_ratio`."
        PRD: "a variance of exactly −0.05 yields one step as well, from 1.20
        to 1.19"
        PRD: "A revision takes effect only when an `Underwriter` applies it"

        Design: Difficulty/combinatorial_formula/mod_revision_evaluation_order_after_issue
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-500", gross_payroll_dollars=95000,
            experience_mod_factor=1.20)

        revisions = list_policy_mod_revisions(ctx)
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision["prior_mod_factor"] == 1.20
        assert revision["revised_mod_factor"] == 1.19, (
            "variance (95000-100000)/100000 = -0.05; trunc(-0.05*20) = -1 "
            "step of 0.01")
        assert revision["status"] == "DRAFT"

        policy = validate_success(api.get_policy(ctx["policy"]["id"], MANAGER))
        assert policy["experience_mod_factor"] == 1.20, (
            "The revision must not touch the policy until applied")


class TestModRevisionConstants:
    def test_mod_revision_clamps_at_ceiling(self, api):
        """PRD: "The `revised_mod_factor` multiplies the ratio by twenty —
        one hundredth of mod movement per full five percent of variance —
        truncates toward zero, adds those hundredths to the prior mod, rounds
        half up to two decimals, and clamps the outcome to the inclusive band
        0.75 to 1.50."
        PRD: "a prior mod of 1.48 meeting a variance of +0.25 computes 1.53
        but clamps to 1.50."

        Design: Corner/calculations/mod_revision_clamp_ceiling
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-K3", gross_payroll_dollars=125000,
            experience_mod_factor=1.48)

        revisions = list_policy_mod_revisions(ctx)
        assert len(revisions) == 1
        assert revisions[0]["prior_mod_factor"] == 1.48
        assert revisions[0]["revised_mod_factor"] == 1.50, (
            "1.48 + 0.05 = 1.53 clamps to the 1.50 ceiling")

    def test_mod_revision_truncates_toward_zero(self, api):
        """PRD: "Truncation toward zero matters at the boundaries: a variance
        of −0.075 yields one downward step, not two, so a prior mod of 1.20
        revises to 1.19 (a floor would have produced 1.18)"

        Design: Corner/calculations/mod_revision_trunc_toward_zero
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-K4", gross_payroll_dollars=92500,
            experience_mod_factor=1.20)

        revisions = list_policy_mod_revisions(ctx)
        assert len(revisions) == 1
        assert revisions[0]["revised_mod_factor"] == 1.19, (
            "variance -0.075; trunc toward zero gives -1 step, not -2")

    def test_mod_revision_below_threshold_not_created(self, api):
        """PRD: "If the ratio's absolute value is below 0.05 (five percent),
        nothing happens."

        Design: Corner/calculations/mod_revision_below_threshold_not_created
        """
        ctx = setup_issued_standard_result(
            policy_number="WC-K5", gross_payroll_dollars=102000,
            experience_mod_factor=1.20)

        revisions = list_policy_mod_revisions(ctx)
        assert revisions == [], (
            "variance +0.02 is below the 0.05 threshold; no revision")


class TestZeroAdjustment:
    def test_zero_adjustment_creates_no_billing(self, api):
        """PRD: "A zero adjustment creates no billing at all."
        PRD: "A billed audit is closed by an `AuditManager` once two
        conditions hold: every billing transaction of the work order's result
        stands `PAID` or `APPLIED` (or no billing exists because the
        adjustment was zero), and the logical clock has passed strictly beyond
        `issued_at` plus thirty days, so the dispute window has elapsed."

        Design: Corner/calculations/zero_adjustment_creates_no_billing
        """
        ctx = setup_selected_work_order(
            policy_number="WC-K7", class_code="9000",
            rate_per_100_cents=1000, payroll_estimate_dollars=60000,
            experience_mod_factor=1.00, receive_requests=True)
        add_allocation(ctx, 60000, verify=True)
        submit_draft(ctx)
        result = issue_result(ctx, clock="2026-08-15T00:00:00Z")

        assert result["earned_premium_cents"] == 600000, (
            "round_half_up(60000 * 1000 / 100) = 600000 at mod 1.00")
        assert result["adjustment_cents"] == 0
        assert result_billings(ctx) == []

        set_clock("2026-09-15T00:00:00Z")
        closed = close_work_order(ctx)
        assert closed["status"] == "CLOSED"



class TestDraftPreconditions:
    def test_submit_draft_physical_before_fieldwork_rejected(self, api):
        """PRD: "A `PHYSICAL` or `REAUDIT` order drafts from
        `FIELD_WORK_DONE`; a `VOLUNTARY_REPORT` order drafts directly from
        `RECORDS_REQUESTED`, and attempting the wrong path is rejected with
        `ERR_INVALID_STATE_TRANSITION`."
        PRD endpoint table: GET /audit-work-orders/{id}/result — Get the work
        order's audit result (array of zero or one).

        Design: Corner/state_machines/submit_draft_physical_before_fieldwork_rejected
        """
        ctx = setup_selected_work_order(
            policy_number="WC-S2", estimated_annual_premium_cents=2000000,
            minimum_premium_cents=100000, receive_requests=True)

        resp = api.submit_draft(ctx["work_order"]["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        results, meta = validate_paginated(
            api.get_work_order_result(ctx["work_order"]["id"], MANAGER))
        assert results == [], "No result may exist after the rejected draft"

    def test_submit_draft_blocked_by_open_records_request(self, api):
        """PRD: "Every records request of the work order must first be
        `RECEIVED` or `WAIVED`; an `OPEN` or `OVERDUE` request blocks drafting
        with `ERR_OPEN_RECORDS_REQUESTS`."

        Design: Difficulty/cross_entity_state_dependency/submit_draft_requires_all_records_terminal
        """
        ctx = setup_selected_work_order(
            policy_number="WC-1400",
            request_types=("PAYROLL_SUMMARY", "SUBCONTRACTOR_LIST"))
        receive_request(ctx, ctx["requests"][0])
        # ctx["requests"][1] (SUBCONTRACTOR_LIST) stays OPEN.

        resp = api.submit_draft(ctx["work_order"]["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_OPEN_RECORDS_REQUESTS)

    def test_submit_draft_succeeds_once_all_records_terminal(self, api):
        """PRD: "Every records request of the work order must first be
        `RECEIVED` or `WAIVED`; an `OPEN` or `OVERDUE` request blocks drafting
        with `ERR_OPEN_RECORDS_REQUESTS`."
        PRD: "Submission creates the **AuditResult** — at most one ever exists
        per work order — in `PRELIMINARY` status with `variant` `STANDARD`,
        records the caller in `drafted_by_user_id`, links it via
        `audit_work_order_id`, moves the work order to `RESULT_DRAFTED`, and
        increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/submit_draft_requires_all_records_terminal
        """
        ctx = setup_selected_work_order(
            policy_number="WC-1400",
            request_types=("PAYROLL_SUMMARY", "SUBCONTRACTOR_LIST"))
        receive_request(ctx, ctx["requests"][0])
        blocked = api.submit_draft(ctx["work_order"]["id"],
                                   ctx["auditor_headers"])
        validate_error(blocked, ApiErrorId.ERR_OPEN_RECORDS_REQUESTS)

        receive_request(ctx, ctx["requests"][1])
        result = submit_draft(ctx)

        assert result["status"] == "PRELIMINARY"
        assert result["variant"] == "STANDARD"
        assert result["audit_work_order_id"] == ctx["work_order"]["id"]
        assert refresh_work_order(ctx)["status"] == "RESULT_DRAFTED"
