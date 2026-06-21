"""Companion tests for every difficulty instance — each asserts a second, distinct,
PRD-derived facet of the same rule (a different numeric point, the opposite branch,
or a side-effect the primary test does not assert). Provides the second required
coverage per difficulty instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_application_under_review, setup_application_approved,
    setup_issued_policy, setup_issued_policy_with_gross_11250, setup_lapsed_policy,
    setup_application_in_exam_pending,
    create_product, create_underwriter, create_draft_application, submit_application,
    attach_completed_exam, add_mib_check, set_clock,
    make_on_cycle_payment, fetch_policy, draw_loan, add_beneficiary,
    make_underwriter_headers, make_policyowner_headers,
    EXAM_PREFERRED, EXAM_STANDARD,
)


# ─── Rule 1: dual_variant_calc ────────────────────────
def test_provisional_final_diverge_preferred_larger_face(api):
    """PRD §3.5: "Consequently the final premium differs from the provisional whenever
    the assessed class is anything other than `STANDARD`."
    PRD §3.5: "`PREFERRED` uses 850 milli-units"

    Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_diverge_on_application
    """
    # face 100000000 -> thousands 1000, base 250000. Non-tobacco PREFERRED:
    # provisional round(250000*1000/1000)=250000; final round(250000*850/1000)=212500.
    ctx = setup_application_approved(
        exam_overrides=dict(EXAM_PREFERRED),
        applicant_overrides={"tobacco_use": False},
        app_overrides={"requested_face_amount_cents": 100_000_000},
    )
    app = ctx["application"]
    assert app["provisional_annual_premium_cents"] == 250000, app
    assert app["final_annual_premium_cents"] == 212500, app
    assert app["final_annual_premium_cents"] != app["provisional_annual_premium_cents"]


def test_risk_build_only_variant_stays_standard_without_impairment(api):
    """PRD §3.4: "Where neither tobacco use nor any flagged check applies, the total
    equals the build debits alone"
    PRD §3.4: "a total of at least 50 but below 100 yields `STANDARD`, also with a table
    rating of 0"

    Design: Difficulty/dual_variant_calc/risk_build_only_vs_impaired_diverge_on_risk_assessment
    """
    # Same build 50 (h70/w210/bp120) but NON-tobacco -> total 50 -> STANDARD (the build-only
    # branch that the impaired variant diverges from).
    ctx = setup_application_under_review(
        exam_overrides=dict(EXAM_STANDARD),
        applicant_overrides={"tobacco_use": False},
    )
    ra, _ = validate_paginated(
        api.get_risk_assessment(ctx["application"]["id"], make_underwriter_headers(ctx["u2"]["id"]))
    )
    assert ra[0]["build_debits"] == 50, ra
    assert ra[0]["total_debits"] == 50, ra
    assert ra[0]["risk_class"] == "STANDARD", ra
    assert ra[0]["table_rating"] == 0, ra


# ─── Rule 2: combinatorial_formula ────────────────────
def test_final_premium_table_2_multiplier(api):
    """PRD §3.5: "a `TABLE_N` class uses 1000 plus N times 250 milli-units, where N is the
    table rating"
    PRD §3.5: "The premium is the after-tobacco figure multiplied by this class multiplier
    divided by 1000, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/final_premium_three_input_nonlinear_table_multiplier_mode_a
    """
    # Build 100 (h70/w210/bp145) + tobacco 50 = total 150 -> TABLE_2 (mult 1500).
    # face 50000000 tobacco: base 125000 -> after_tobacco 187500 -> *1500/1000 = 281250.
    ctx = setup_application_approved(
        exam_overrides={"height_inches": 70, "weight_pounds": 210, "systolic_bp": 145},
        applicant_overrides={"tobacco_use": True},
        app_overrides={"requested_face_amount_cents": 50_000_000},
    )
    app = ctx["application"]
    assert app["final_annual_premium_cents"] == 281250, app


def test_final_premium_round_per_step_odd_base_half_cent(api):
    """PRD §2.6: "The premium engine performs this rounding once per multiplication step
    in a pinned order rather than once at the end, so that intermediate results are
    themselves whole cents"
    PRD §3.5: "The premium is the after-tobacco figure multiplied by this class multiplier
    divided by 1000, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/premium_round_per_step_not_round_at_end_mode_b
    """
    # face 10100000 -> thousands 101 (odd), base_rate 101 -> base 10201 (odd).
    # Tobacco STANDARD (build 0 + tobacco 50 = 50): after_tobacco round(10201*1500/1000)
    # = round(15301.5) = 15302; premium round(15302*1000/1000) = 15302.
    ctx = setup_application_approved(
        product_overrides={"base_annual_rate_per_thousand_cents": 101},
        exam_overrides=dict(EXAM_PREFERRED),  # build 0 so total = tobacco 50 -> STANDARD
        applicant_overrides={"tobacco_use": True},
        app_overrides={"requested_face_amount_cents": 10_100_000},
    )
    app = ctx["application"]
    assert app["final_annual_premium_cents"] == 15302, app


# ─── Rule 3: non_linear_state_machine ─────────────────
def test_revision_cycle_repins_ordering_underwriter(api):
    """PRD §3.3: "ordering a new exam falls the case back from `UNDER_REVIEW` to
    `EXAM_PENDING`, re-pins the ordering underwriter, and bumps the version."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_under_review_back_to_exam_pending
    """
    ctx = setup_application_under_review(exam_overrides=dict(EXAM_PREFERRED))
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    reordered = validate_success(api.order_exam(app_id, u1_h))
    # The revision back-edge lands in EXAM_PENDING (no linear pipeline has this).
    assert reordered["status"] == "EXAM_PENDING", reordered
    assert reordered["ordering_underwriter_id"] == ctx["u1"]["id"], reordered


def test_policy_grace_does_not_force_contestability_flip(api):
    """PRD §2.7: "A single mutation may touch either dimension, both, or neither, and the
    two are stored on the same policy row."
    PRD §3.8: "This evolution is entirely separate from the funding lifecycle"

    Design: Difficulty/non_linear_state_machine/policy_parallel_lifecycle_and_contestability_dimensions
    """
    # Advance only past the due date (GRACE) but not the contestability window: lifecycle
    # moves while contestability stays put -> the two dimensions are independent.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    set_clock("2027-06-02T00:00:00Z")
    policy = fetch_policy(ctx["policy"]["id"], ctx["applicant"]["id"])
    assert policy["lifecycle_status"] == "GRACE", policy
    assert policy["contestability_status"] == "CONTESTABLE", policy


# ─── Rule 4: transitive_cascade ───────────────────────
def test_issue_cascade_sets_policy_face_and_premium(api):
    """PRD §3.6: "The new policy copies its `face_amount_cents` from the application's
    requested face amount and its `annual_premium_cents` from the application's final
    premium."
    PRD §3.6: "It creates exactly one `Policy` for the application, in `lifecycle_status`
    `IN_FORCE` and `contestability_status` `CONTESTABLE`."

    Design: Difficulty/transitive_cascade/issue_cascade_depth3_policy_cashvalue_gross_net
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy = ctx["policy"]
    assert policy["lifecycle_status"] == "IN_FORCE", policy
    assert policy["contestability_status"] == "CONTESTABLE", policy
    assert policy["face_amount_cents"] == 50_000_000, policy
    assert policy["annual_premium_cents"] == 125000, policy


def test_payment_cascade_appends_second_ledger_entry(api):
    """PRD §2.8: "The gross cash value, `gross_cash_value_cents`, is always the exact
    integer sum of every `amount_cents` across the policy's cash-value entries"
    PRD §3.7: "A new `CashValueEntry` with reason `PREMIUM_ACCRUAL` for that increment is
    appended"

    Design: Difficulty/transitive_cascade/payment_cascade_depth2_cumulative_accrual_gross
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    make_on_cycle_payment(policy_id, applicant_id, 125000)
    entries, _ = validate_paginated(
        api.list_cash_value_entries(policy_id, make_policyowner_headers(applicant_id))
    )
    accruals = [e for e in entries if e["reason"] == "PREMIUM_ACCRUAL"]
    assert len(accruals) == 2, entries  # one at issue (3750), one at the 2nd payment (7500)
    assert sum(e["amount_cents"] for e in accruals) == 11250, accruals


# ─── Rule 5: priority_pair_validation_conflict ────────
def test_exam_pending_unchanged_after_blocked_approve(api):
    """PRD §2.11: "then whether the requested transition is even defined from the
    resource's current state (`ERR_INVALID_STATE`)."
    PRD §3.3: "it records the acting underwriter's `id` into the application's
    `ordering_underwriter_id`, pinning the subject of the later segregation check"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_approve_from_exam_pending
    """
    ctx = setup_application_in_exam_pending()
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    before = validate_success(api.get_application(app_id, u1_h))
    api.approve_application(app_id, {"expected_application_version": before["version"]}, u1_h)
    after = validate_success(api.get_application(app_id, u1_h))
    # The rejected approve leaves status, deciding underwriter, and final premium untouched.
    assert after["status"] == "EXAM_PENDING", after
    assert after["deciding_underwriter_id"] is None, after
    assert after["final_annual_premium_cents"] is None, after


def test_lapsed_policy_premium_payment_leaves_lifecycle_unchanged(api):
    """PRD §2.11: "then whether the requested transition is even defined from the
    resource's current state (`ERR_INVALID_STATE`)."
    PRD §3.7: "A payment accepted while the policy is `IN_FORCE` keeps it `IN_FORCE`; a
    payment accepted while it is in `GRACE` restores it to `IN_FORCE`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_premium_amount_mismatch_on_lapsed_policy
    """
    ctx = setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z", lapse_clock="2027-08-01T00:00:00Z")
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # Wrong amount on a LAPSED policy: state check dominates; lifecycle stays LAPSED.
    resp = api.create_premium_payment(
        policy_id, {"amount_cents": 1}, make_policyowner_headers(applicant_id)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = fetch_policy(policy_id, applicant_id)
    assert after["lifecycle_status"] == "LAPSED", after


# ─── Rule 6: boundary_precision_check ─────────────────
def test_loan_one_cent_over_available_rejected(api):
    """PRD §3.9: "A requested principal that exceeds the available amount is rejected with
    `ERR_LOAN_EXCEEDS_VALUE`, while a principal exactly equal to the available amount is
    permitted."

    Design: Difficulty/boundary_precision_check/loan_principal_equals_available_value_inclusive_boundary
    """
    # The >available side of the same boundary: cap 10125, 10126 rejected (X+1 companion).
    ctx = setup_issued_policy_with_gross_11250()
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    resp = api.create_policy_loan(
        policy_id, {"principal_cents": 10126, "expected_policy_version": ctx["policy_version"]},
        make_policyowner_headers(applicant_id),
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_EXCEEDS_VALUE.value)


def test_blood_pressure_band_136_fifty_debits(api):
    """PRD §3.4: "above 135 and at or below 150 contributes 50"
    PRD §3.4: "a total of at least 50 but below 100 yields `STANDARD`, also with a table
    rating of 0"

    Design: Difficulty/boundary_precision_check/blood_pressure_band_boundary_135_zero_debits_on_begin_review
    """
    # X+1 companion: systolic_bp 136 sits just above the inclusive 135 edge -> 50 bp debits.
    # h70/w160 -> BMI 22.955 (0 build) so build_debits = 0 + 50 = 50 -> STANDARD.
    ctx = setup_application_under_review(
        exam_overrides={"height_inches": 70, "weight_pounds": 160, "systolic_bp": 136},
        applicant_overrides={"tobacco_use": False},
    )
    ra, _ = validate_paginated(
        api.get_risk_assessment(ctx["application"]["id"], make_underwriter_headers(ctx["u2"]["id"]))
    )
    assert ra[0]["build_debits"] == 50, ra
    assert ra[0]["total_debits"] == 50, ra
    assert ra[0]["risk_class"] == "STANDARD", ra


# ─── Rule 7: cross_entity_state_dependency ────────────
def test_begin_review_succeeds_once_exam_completed(api):
    """PRD §3.4: "Once at least one exam on the application has reached `COMPLETED` and at
    least one MIB check exists, an underwriter begins review, advancing `EXAM_PENDING` to
    `UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/begin_review_requires_completed_paramed_exam_application_to_exam
    """
    # The positive companion: with the sibling exam COMPLETED, begin-review proceeds.
    ctx = setup_application_in_exam_pending()
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    u2_h = make_underwriter_headers(ctx["u2"]["id"])
    exam = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                 "exam_date": "2026-05-01"}, u1_h), expected_status=201)
    validate_success(api.complete_paramed_exam(exam["id"], u1_h))
    add_mib_check(app_id, ctx["u1"]["id"])
    reviewed = validate_success(api.begin_review(app_id, u2_h))
    assert reviewed["status"] == "UNDER_REVIEW", reviewed


def test_approve_succeeds_when_all_mib_clear(api):
    """PRD §3.5: "it requires that a risk assessment exist whose `risk_class` is neither
    `TABLE_7` nor `TABLE_8`, that every MIB check on the application carries a `CLEAR`
    result"

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_flagged_mib_check_application_to_mibcheck
    """
    # The CLEAR companion to the FLAGGED-blocks-approve rule: a CLEAR MIB check lets approve
    # through to APPROVED_OFFER.
    ctx = setup_application_under_review(
        exam_overrides=dict(EXAM_PREFERRED),
        mib_overrides={"mib_hit": False, "rx_flag_count": 0},
    )
    app_id = ctx["application"]["id"]
    u2_h = make_underwriter_headers(ctx["u2"]["id"])
    approved = validate_success(
        api.approve_application(app_id, {"expected_application_version": ctx["review_version"]}, u2_h)
    )
    assert approved["status"] == "APPROVED_OFFER", approved


# ─── Rule 8: resource_temporal_overlap ────────────────
def test_paramed_exam_adjacent_window_allowed(api):
    """PRD §3.3: "two windows that merely touch end-to-start do not overlap, so adjacency
    is permitted."

    Design: Difficulty/resource_temporal_overlap/paramed_exam_validity_window_overlap_closed_adjacency_allowed
    """
    # exam_validity_days 180; first exam 2026-01-10 -> window [2026-01-10, 2026-07-09).
    # A second exam dated exactly 2026-07-09 abuts the prior end -> no overlap, allowed.
    ctx = setup_application_in_exam_pending(product_overrides={"exam_validity_days": 180})
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    e1 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                 "exam_date": "2026-01-10"}, u1_h), expected_status=201)
    validate_success(api.complete_paramed_exam(e1["id"], u1_h))
    e2 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 165, "systolic_bp": 122,
                 "exam_date": "2026-07-09"}, u1_h), expected_status=201)
    completed = validate_success(api.complete_paramed_exam(e2["id"], u1_h))
    assert completed["status"] == "COMPLETED", completed


def test_premium_coverage_abutting_payment_allowed(api):
    """PRD §3.7: "because the intervals are half-open, a payment whose coverage starts
    exactly where a prior payment's coverage ends does not overlap and is allowed."

    Design: Difficulty/resource_temporal_overlap/premium_coverage_period_overlap_half_open_abutment_allowed
    """
    # The first on-cycle payment funds [2027-06-01, 2028-06-01) (default coverage
    # start == next_premium_due_date). A second payment whose coverage starts
    # exactly at 2028-06-01 (where the prior interval ends) abuts and is accepted.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    first = validate_success(
        api.create_premium_payment(policy_id, {"amount_cents": 125000}, po_h),
        expected_status=201,
    )  # funds [2027-06-01, 2028-06-01)
    payment = validate_success(
        api.create_premium_payment(
            policy_id, {"amount_cents": 125000, "coverage_period_start": "2028-06-01"}, po_h),
        expected_status=201,
    )  # funds [2028-06-01, 2029-06-01) -> abuts the prior end, allowed
    assert payment["policy_id"] == policy_id, payment
    payments, meta = validate_paginated(api.list_premium_payments(policy_id, po_h))
    assert meta["total_count"] == 2, meta


# ─── Rule 9: compensating_invariant ───────────────────
def test_loan_repay_restores_policy_version_advances(api):
    """PRD §3.9: "Repaying a loan advances it from `ACTIVE` to `REPAID`."
    PRD §2.8: "The net cash value, `net_cash_value_cents`, is the gross less the total
    principal of currently active loans, never allowed to fall below zero."

    Design: Difficulty/compensating_invariant/loan_draw_then_repay_conserves_gross_cash_value
    """
    # Companion: net is gross-minus-ACTIVE-principal; once the loan is REPAID it no longer
    # counts, so net returns to gross. Uses a different principal (3000) than the primary.
    ctx = setup_issued_policy_with_gross_11250()
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    loan = draw_loan(policy_id, applicant_id, 3000, ctx["policy_version"])
    mid = fetch_policy(policy_id, applicant_id)
    assert mid["net_cash_value_cents"] == 8250, mid  # 11250 - 3000
    validate_success(api.repay_policy_loan(loan["id"], po_h))
    after = fetch_policy(policy_id, applicant_id)
    assert after["net_cash_value_cents"] == 11250, after
    assert after["outstanding_loan_principal_cents"] == 0, after


def test_contingent_tier_share_must_sum_to_100(api):
    """PRD §3.9: "if any contingent beneficiary exists, the `CONTINGENT` tier's shares must
    likewise sum to 100; otherwise the operation is rejected with
    `ERR_BENEFICIARY_SHARE_INVALID`."

    Design: Difficulty/compensating_invariant/primary_beneficiary_share_total_conserved_at_100
    """
    # Companion on the conserved-percentage invariant: a valid 100% PRIMARY tier exists, but
    # a CONTINGENT at 60 leaves the contingent tier at 60 != 100 -> rejected; PRIMARY stays 100.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    add_beneficiary(policy_id, applicant_id, full_name="Primary", designation="PRIMARY", share_pct=100)
    resp = api.create_beneficiary(
        policy_id, {"full_name": "Contingent", "designation": "CONTINGENT", "share_pct": 60}, po_h
    )
    validate_error(resp, ApiErrorId.ERR_BENEFICIARY_SHARE_INVALID.value)
    bens, _ = validate_paginated(api.list_beneficiaries(policy_id, po_h))
    primaries = [b for b in bens if b["designation"] == "PRIMARY"]
    assert len(primaries) == 1 and primaries[0]["share_pct"] == 100, bens
