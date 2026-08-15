"""Monthly sweep, ratio snapshots, program enrollment and fines, remediation
plans, exit review, and education assignments."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    ZERO_DENOMINATOR_SENTINEL_BPS,
    assert_education_assignment,
    assert_program_enrollment,
    assert_ratio_snapshot,
    create_enrollment,
    create_merchant,
    create_plan,
    create_rule,
    get_success_data,
    ingest_chargeback,
    ingest_sale,
    ingest_sales_batch,
    list_education,
    list_enrollments,
    list_fees,
    list_snapshots,
    make_merchant_user_headers,
    review_plan,
    run_clean_month,
    run_over_threshold_month,
    set_clock,
    setup_exited_enrollment,
    submit_plan,
    sweep,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def _setup_posted_vs_gross_merchant(api):
    """VISA merchant with 1000 July sales; 9 July chargebacks, one of which is
    REVERSED before the sweep."""
    create_rule(api, required_evidence_types=["RECEIPT", "DELIVERY_PROOF"])
    m = create_merchant(api, legal_name="Ratio M", reserve_rate_bps=0)
    ingest_sales_batch(api, m["id"], "S", 1000, 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    cbs = [
        ingest_chargeback(api, m["id"], f"S-{i:04d}", f"NC-{i}", 5000)
        for i in range(1, 10)
    ]
    get_success_data(api.reverse_chargeback(cbs[8]["id"], OPS))
    return m


def test_ratio_posted_basis_excludes_reversed_case(api):
    """PRD §3.9: "the `chargeback_count`, the posted-basis numerator of
    chargebacks with `received_at` inside the month whose `case_status` is not
    `REVERSED` at sweep time" and "Each swept merchant's
    `current_count_ratio_bps` refreshes to the `count_ratio_bps` of its most
    recent posted snapshot by `period_month`".

    Design: Difficulty/dual_variant_calc/ratio_posted_excludes_reversed_vs_gross_includes
    """
    m = _setup_posted_vs_gross_merchant(api)
    tally = sweep(api, "2026-07", merchant_id=m["id"])
    assert tally["snapshots_created"] == 1

    snaps = list_snapshots(api, m["id"])
    assert len(snaps) == 1
    snap = snaps[0]
    assert_ratio_snapshot(snap)
    assert snap["sales_count"] == 1000
    assert snap["chargeback_count"] == 8  # REVERSED excluded
    # round_half_up(10000 x 8 / 1000) = 80.
    assert snap["count_ratio_bps"] == 80

    merchant = get_success_data(api.get_merchant(m["id"], OPS))
    assert merchant["current_count_ratio_bps"] == 80


def test_ratio_gross_basis_includes_reversed_but_does_not_enroll(api):
    """PRD §3.9: "the `gross_chargeback_count`, the gross-basis numerator that
    includes `REVERSED` cases" — "so a reversed case still inflates the gross
    figure". "Threshold evaluation follows each snapshot on the posted basis"
    and "when no tier matches nothing happens — no enrollment, no counter
    change."

    Design: Difficulty/dual_variant_calc/ratio_posted_excludes_reversed_vs_gross_includes
    """
    m = _setup_posted_vs_gross_merchant(api)
    sweep(api, "2026-07", merchant_id=m["id"])

    snap = list_snapshots(api, m["id"])[0]
    assert snap["gross_chargeback_count"] == 9  # REVERSED included
    assert snap["gross_count_ratio_bps"] == 90
    # POSTED 80 < VDMP_STANDARD 90: no enrollment even though GROSS is at
    # threshold — enrollment consumes the posted basis only.
    assert list_enrollments(api, m["id"]) == []


def _setup_fine_ladder(api):
    """VISA merchant over the VDMP_STANDARD threshold (5 chargebacks per 50
    sales = 1000 bps) for four consecutive months 2026-04..2026-07."""
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="Fine M", reserve_rate_bps=0)
    tallies = []
    for month, prefix in (
        ("2026-04", "A4"),
        ("2026-05", "A5"),
        ("2026-06", "A6"),
        ("2026-07", "A7"),
    ):
        tallies.append(run_over_threshold_month(api, m["id"], month, prefix))
    return m, tallies


def test_program_fine_ladder_first_tier_months(api):
    """PRD §3.9: "The fine is the program's base amount — 250,000 cents for
    `VDMP_STANDARD` and `ECM`, 500,000 cents for `VDMP_EXCESSIVE` and `HECM` —
    multiplied by a tiered multiplier of the month count: face value for the
    first three months". "The fine lands as a `PROGRAM_FINE` `FeeAssessment`
    carrying the `enrollment_id` and `assessed_by_user_id` `system`."

    Design: Difficulty/combinatorial_formula/program_fine_tiered_escalation_ladder
    """
    m, tallies = _setup_fine_ladder(api)
    # The enrolling sweep already assesses the month-1 fine.
    assert tallies[0]["enrollments_created"] == 1
    assert tallies[0]["fines_assessed"] == 1

    enr = list_enrollments(api, m["id"])[0]
    fines = list_fees(api, enrollment_id=enr["id"])
    assert len(fines) == 4
    for fee in fines:
        assert fee["kind"] == "PROGRAM_FINE"
        assert fee["assessed_by_user_id"] == "system"
    # Months 1-3 at face value (multiplier 1.0 while months_over_count <= 3).
    assert [f["amount_cents"] for f in fines[:3]] == [250000, 250000, 250000]


def test_program_fine_ladder_tier_step_at_month_four(api):
    """PRD §3.9: "the enrollment's `months_over_count` is then incremented for
    an over-threshold month; and the fine is computed from the
    already-incremented count" and "multiplied by a tiered multiplier of the
    month count: face value for the first three months, one and a half times
    for months four through six, and double from the seventh month onward, with
    the result rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/program_fine_tiered_escalation_ladder
    """
    m, _tallies = _setup_fine_ladder(api)
    enr = get_success_data(
        api.get_program_enrollment(list_enrollments(api, m["id"])[0]["id"], RISK)
    )
    assert enr["months_over_count"] == 4
    assert enr["status"] == "ACTIVE"

    fines = list_fees(api, enrollment_id=enr["id"])
    # Month 4 prices from the already-incremented count 4: 250000 x 1.5.
    # The pre-increment count 3 would have priced 250000 — a tier step, not
    # linear growth.
    assert fines[3]["amount_cents"] == 375000


def test_advance_month_enrollment_cascade_creates_education_pair(api):
    """PRD §3.9: "Every enrollment creation cascades to merchant education: two
    `EducationAssignment` records are created for the merchant with
    `assigned_reason` `PROGRAM_ENROLLMENT` and an `enrollment_ref` naming the
    triggering enrollment — an informational reference, not a navigable foreign
    key. The assigned `module_code` pair depends on the program family:
    `VDMP_*` enrollments assign `CHARGEBACK_BASICS` plus
    `EVIDENCE_BEST_PRACTICE`, while `ECM` and `HECM` enrollments assign
    `CHARGEBACK_BASICS` plus `FRAUD_PREVENTION`."

    Design: Difficulty/transitive_cascade/advance_month_enrollment_cascade
    """
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="Sweep M", reserve_rate_bps=0)
    tally = run_over_threshold_month(api, m["id"], "2026-06", "J6")
    assert tally["snapshots_created"] == 1
    assert tally["enrollments_created"] == 1
    assert tally["fines_assessed"] == 1

    enr = list_enrollments(api, m["id"])[0]
    assert_program_enrollment(enr)
    assert enr["status"] == "ACTIVE"
    assert enr["enrolled_month"] == "2026-06"
    assert enr["months_over_count"] == 1
    assert enr["program_code"] == "VDMP_STANDARD"

    assignments = list_education(api, m["id"])
    assert len(assignments) == 2
    for assignment in assignments:
        assert_education_assignment(assignment)
        assert assignment["status"] == "ASSIGNED"
        assert assignment["enrollment_ref"] == enr["id"]
    assert {a["module_code"] for a in assignments} == {
        "CHARGEBACK_BASICS",
        "EVIDENCE_BEST_PRACTICE",
    }


def test_advance_month_enrollment_cascade_assesses_month_one_fine(api):
    """PRD §3.9: "Program fines follow a pinned evaluation order within the
    sweep: the snapshot is posted and its ratio computed first; the
    enrollment's `months_over_count` is then incremented for an over-threshold
    month; and the fine is computed from the already-incremented count. The
    fine is the program's base amount — 250,000 cents for `VDMP_STANDARD` and
    `ECM` ..." and "The fine lands as a `PROGRAM_FINE` `FeeAssessment` carrying
    the `enrollment_id` and `assessed_by_user_id` `system`."

    Design: Difficulty/transitive_cascade/advance_month_enrollment_cascade
    """
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="Sweep M", reserve_rate_bps=0)
    tally = run_over_threshold_month(api, m["id"], "2026-06", "J6")
    assert tally["fines_assessed"] == 1

    enr = list_enrollments(api, m["id"])[0]
    fines = list_fees(api, enrollment_id=enr["id"])
    assert len(fines) == 1
    fine = fines[0]
    assert fine["kind"] == "PROGRAM_FINE"
    assert fine["amount_cents"] == 250000  # month-1 base, multiplier 1.0
    assert fine["assessed_by_user_id"] == "system"
    assert fine["merchant_id"] == m["id"]


def _setup_threshold_edge_merchants(api):
    """M1: 1000 July sales + 9 July chargebacks (exactly 90 bps).
    M2: 1000 July sales + 8 July chargebacks (80 bps)."""
    create_rule(api, required_evidence_types=["RECEIPT"])
    m1 = create_merchant(api, legal_name="Edge M1", reserve_rate_bps=0)
    m2 = create_merchant(api, legal_name="Edge M2", reserve_rate_bps=0)
    ingest_sales_batch(api, m1["id"], "P1", 1000, 10000, "2026-07-10T00:00:00Z")
    ingest_sales_batch(api, m2["id"], "P2", 1000, 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    for i in range(1, 10):
        ingest_chargeback(api, m1["id"], f"P1-{i:04d}", f"NC-A{i}", 5000)
    for i in range(1, 9):
        ingest_chargeback(api, m2["id"], f"P2-{i:04d}", f"NC-B{i}", 5000)
    return m1, m2


def test_ratio_threshold_exactly_90_bps_enrolls(api):
    """PRD §3.9: "the standard tier `VDMP_STANDARD` matches at a
    `count_ratio_bps` of at least 90 with a `chargeback_count` of at least 5"
    and "Boundaries are inclusive, the higher tier wins when both match".

    Design: Difficulty/boundary_precision_check/ratio_threshold_exactly_90_bps_enrolls
    """
    m1, m2 = _setup_threshold_edge_merchants(api)
    tally = sweep(api, "2026-07")
    assert tally["snapshots_created"] == 2
    assert tally["enrollments_created"] == 1

    snap1 = list_snapshots(api, m1["id"])[0]
    assert snap1["count_ratio_bps"] == 90  # exactly the inclusive threshold
    enr = list_enrollments(api, m1["id"])
    assert len(enr) == 1
    assert enr[0]["program_code"] == "VDMP_STANDARD"


def test_ratio_threshold_one_below_enrolls_nothing(api):
    """PRD §3.9: "the standard tier `VDMP_STANDARD` matches at a
    `count_ratio_bps` of at least 90 with a `chargeback_count` of at least 5"
    and "when no tier matches nothing happens — no enrollment, no counter
    change."

    Design: Difficulty/boundary_precision_check/ratio_threshold_exactly_90_bps_enrolls
    """
    _m1, m2 = _setup_threshold_edge_merchants(api)
    sweep(api, "2026-07")

    snap2 = list_snapshots(api, m2["id"])[0]
    # 8/1000 is exactly 80 bps — one chargeback of difference below the line.
    assert snap2["count_ratio_bps"] == 80
    assert list_enrollments(api, m2["id"]) == []


def test_zero_denominator_sentinel_ratio_no_enrollment(api):
    """PRD §3.9: "a zero denominator with a positive numerator yields the
    sentinel value of 100,000 basis points, and zero activity in both yields
    zero". "the standard tier `VDMP_STANDARD` matches at a `count_ratio_bps` of
    at least 90 with a `chargeback_count` of at least 5" — the count floor is
    unmet even at the sentinel ratio.

    Design: Corner/calculations/zero_denominator_sentinel_ratio
    """
    create_rule(api, required_evidence_types=["RECEIPT"])
    m = create_merchant(api, legal_name="ZeroDenom M", reserve_rate_bps=0)
    # Both disputed sales occurred in MAY — outside the swept July denominator.
    ingest_sale(api, m["id"], "T-1", 10000, "2026-05-10T00:00:00Z")
    ingest_sale(api, m["id"], "T-2", 10000, "2026-05-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    ingest_chargeback(api, m["id"], "T-1", "NC-Z1", 10000)
    ingest_chargeback(api, m["id"], "T-2", "NC-Z2", 10000)

    sweep(api, "2026-07", merchant_id=m["id"])
    snap = list_snapshots(api, m["id"])[0]
    assert snap["sales_count"] == 0
    assert snap["chargeback_count"] == 2
    assert snap["count_ratio_bps"] == ZERO_DENOMINATOR_SENTINEL_BPS == 100000
    assert list_enrollments(api, m["id"]) == []


def test_repeat_sweep_skips_existing_snapshot(api):
    """PRD §3.9: "a repeat sweep of an already-posted (merchant, network,
    `period_month`) triple skips it" and "The checkpoint response tallies
    `snapshots_created`, `snapshots_skipped`, `enrollments_created`, and
    `fines_assessed`".

    Design: Corner/cross_cutting/repeat_sweep_skips_existing_snapshot
    """
    m = create_merchant(api, legal_name="Idem M", reserve_rate_bps=0)
    ingest_sales_batch(api, m["id"], "I", 10, 10000, "2026-07-10T00:00:00Z")
    sweep(api, "2026-07", merchant_id=m["id"])

    tally = sweep(api, "2026-07", merchant_id=m["id"])
    assert tally["snapshots_created"] == 0
    assert tally["snapshots_skipped"] == 1
    assert len(list_snapshots(api, m["id"])) == 1


def test_sweep_skips_merchant_without_activity(api):
    """PRD §3.9: "A snapshot is posted for every merchant × network combination
    with any sales or chargeback activity in that month".

    Design: Corner/cross_cutting/sweep_skips_inactive_merchant
    """
    m = create_merchant(api, legal_name="Idle M", reserve_rate_bps=0)
    tally = sweep(api, "2026-07", merchant_id=m["id"])
    assert tally["snapshots_created"] == 0
    assert list_snapshots(api, m["id"]) == []


def test_exit_review_without_plan_rejected(api):
    """PRD §3.9: "Two exit criteria must both hold, else the review fails with
    `ERR_EXIT_CRITERIA_NOT_MET`: an `APPROVED` remediation plan must exist for
    the enrollment, and at least three posted snapshots must exist for the
    merchant and network with the three most recent by `period_month` all
    strictly below the program threshold."

    Design: Corner/validations/exit_review_without_plan_rejected
    """
    m = create_merchant(api, legal_name="NoPlan M", reserve_rate_bps=0)
    enr = create_enrollment(api, m["id"], enrolled_month="2026-05")
    # Three consecutive under-threshold POSTED snapshots, but NO plan.
    for month, prefix in (("2026-06", "N6"), ("2026-07", "N7"), ("2026-08", "N8")):
        run_clean_month(api, m["id"], month, prefix)

    resp = api.exit_review_enrollment(enr["id"], {"exited_month": "2026-08"}, RISK)
    validate_error(resp, ApiErrorId.ERR_EXIT_CRITERIA_NOT_MET)


def test_exit_review_on_exited_rejected(api):
    """PRD §3.9: "Exit from a program is a `RiskOfficer` exit-review supplying
    the `exited_month`, permitted from `ACTIVE` or `REMEDIATION` — an
    already-`EXITED` enrollment rejects the review with
    `ERR_INVALID_ENROLLMENT_STATE`."

    Design: Corner/state_machines/exit_review_on_exited_rejected
    """
    bundle = setup_exited_enrollment(api)
    enr = bundle["enrollment"]
    assert enr["status"] == "EXITED"
    assert enr["exited_month"] == "2026-08"

    resp = api.exit_review_enrollment(enr["id"], {"exited_month": "2026-09"}, RISK)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE)


def test_enrollment_reentry_in_exit_month_conflicts(api):
    """PRD §3.9: "enrollment month ranges are closed intervals from
    `enrolled_month` to `exited_month` per (`merchant_id`, `network`,
    `program_code`) triple and must not overlap, so even re-enrollment in the
    prior exit month itself conflicts and is rejected with
    `ERR_ENROLLMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/enrollment_closed_month_overlap
    """
    bundle = setup_exited_enrollment(api)
    m = bundle["merchant"]
    enr = bundle["enrollment"]
    assert enr["status"] == "EXITED"  # approved plan + 3 clean snapshots
    assert enr["exited_month"] == "2026-08"

    # CLOSED interval semantics: the exit month itself still conflicts.
    resp = api.create_program_enrollment(
        {
            "merchant_id": m["id"],
            "network": "VISA",
            "program_code": "VDMP_STANDARD",
            "enrolled_month": "2026-08",
        },
        RISK,
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_OVERLAP)


def test_enrollment_month_after_exit_month_is_clean(api):
    """PRD §3.9: "enrollment month ranges are closed intervals from
    `enrolled_month` to `exited_month` per (`merchant_id`, `network`,
    `program_code`) triple and must not overlap" — the first month strictly
    after the closed range is outside it.

    Design: Difficulty/resource_temporal_overlap/enrollment_closed_month_overlap
    """
    bundle = setup_exited_enrollment(api)
    m = bundle["merchant"]

    resp = api.create_program_enrollment(
        {
            "merchant_id": m["id"],
            "network": "VISA",
            "program_code": "VDMP_STANDARD",
            "enrolled_month": "2026-09",
        },
        RISK,
    )
    re_enrolled = validate_success(resp, 201)
    assert re_enrolled["status"] == "ACTIVE"
    assert re_enrolled["months_over_count"] == 1


def test_remediation_plan_return_keeps_enrollment_active(api):
    """PRD §3.9: "`APPROVE` moves the plan to its terminal `APPROVED` state and
    the parent enrollment `ACTIVE` → `REMEDIATION`, while `RETURN` moves the
    plan to `RETURNED`, from which the merchant may edit and resubmit — the
    review cycle `SUBMITTED` → `RETURNED` → `SUBMITTED` repeats until
    approval."

    Design: Difficulty/non_linear_state_machine/remediation_plan_return_resubmit_cycle
    """
    m = create_merchant(api, legal_name="Plan M", reserve_rate_bps=0)
    enr = create_enrollment(api, m["id"], enrolled_month="2026-05")
    plan = create_plan(api, enr["id"], m["id"])
    submit_plan(api, plan["id"], m["id"])

    returned = review_plan(api, plan["id"], "RETURN", "insufficient detail")
    assert returned["status"] == "RETURNED"
    assert returned["reviewed_by_user_id"] is not None
    # Rejection does not move the enrollment.
    mid = get_success_data(api.get_program_enrollment(enr["id"], RISK))
    assert mid["status"] == "ACTIVE"


def test_remediation_plan_resubmit_and_approve_moves_enrollment(api):
    """PRD §3.9: "`APPROVE` moves the plan to its terminal `APPROVED` state and
    the parent enrollment `ACTIVE` → `REMEDIATION`" and "Either review records
    the reviewing user in `reviewed_by_user_id` and captures the optional
    `decision_note`."

    Design: Difficulty/non_linear_state_machine/remediation_plan_return_resubmit_cycle
    """
    m = create_merchant(api, legal_name="Plan M", reserve_rate_bps=0)
    enr = create_enrollment(api, m["id"], enrolled_month="2026-05")
    plan = create_plan(api, enr["id"], m["id"])
    submit_plan(api, plan["id"], m["id"])
    review_plan(api, plan["id"], "RETURN", "insufficient detail")

    # RETURNED -> SUBMITTED resubmission cycle, then approval.
    resubmitted = submit_plan(api, plan["id"], m["id"])
    assert resubmitted["status"] == "SUBMITTED"
    approved = review_plan(api, plan["id"], "APPROVE", "ok")
    assert approved["status"] == "APPROVED"
    assert approved["decision_note"] == "ok"

    final = get_success_data(api.get_program_enrollment(enr["id"], RISK))
    assert final["status"] == "REMEDIATION"


def test_plan_review_non_submitted_rejected(api):
    """PRD §3.9: "A `RiskOfficer` then reviews a `SUBMITTED` plan (reviewing a
    plan in any other state fails with `ERR_INVALID_PLAN_STATE`)".

    Design: Corner/state_machines/plan_review_non_submitted_rejected
    """
    m = create_merchant(api, legal_name="PlanGate M", reserve_rate_bps=0)
    enr = create_enrollment(api, m["id"], enrolled_month="2026-05")
    plan = create_plan(api, enr["id"], m["id"])
    assert plan["status"] == "DRAFT"

    resp = api.review_remediation_plan(plan["id"], {"decision": "APPROVE"}, RISK)
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_STATE)


def test_plan_create_second_open_plan_rejected(api):
    """PRD §3.9: "at most one plan per enrollment may be `DRAFT` or `SUBMITTED`
    at a time, and creating a second open plan fails with
    `ERR_INVALID_PLAN_STATE`."

    Design: Corner/state_machines/plan_create_second_open_rejected
    """
    m = create_merchant(api, legal_name="TwoPlan M", reserve_rate_bps=0)
    enr = create_enrollment(api, m["id"], enrolled_month="2026-05")
    plan1 = create_plan(api, enr["id"], m["id"], corrective_actions=("a1",))
    assert plan1["status"] == "DRAFT"

    resp = api.create_remediation_plan(
        {
            "enrollment_id": enr["id"],
            "root_cause_codes": ["POLICY_GAP"],
            "corrective_actions": ["a2"],
        },
        make_merchant_user_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_STATE)


def test_education_complete_twice_rejected(api):
    """PRD §3.9: "the owning `MerchantUser` completes it — while the merchant
    is `ACTIVE` and the assignment still `ASSIGNED`, else
    `ERR_MERCHANT_SUSPENDED` or `ERR_ASSIGNMENT_NOT_OPEN` respectively —
    moving it to `COMPLETED` with `completed_at` stamped."

    Design: Corner/state_machines/education_complete_twice_rejected
    """
    m = create_merchant(api, legal_name="Edu M", reserve_rate_bps=0)
    create_enrollment(api, m["id"], enrolled_month="2026-05")
    assignments = list_education(api, m["id"])
    # The enrollment cascade created the pair.
    assert len(assignments) == 2
    target = assignments[0]
    headers = make_merchant_user_headers(m["id"])

    completed = validate_success(api.complete_education_assignment(target["id"], headers))
    assert completed["status"] == "COMPLETED"
    assert completed.get("completed_at") is not None

    again = api.complete_education_assignment(target["id"], headers)
    validate_error(again, ApiErrorId.ERR_ASSIGNMENT_NOT_OPEN)
