"""Temporal-overlap conflicts (exam validity windows; premium coverage intervals) and
beneficiary share-tier conservation.

Covers difficulty rules resource_temporal_overlap and compensating_invariant
(beneficiary instance), plus the corner beneficiary-share instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_application_in_exam_pending, setup_issued_policy,
    make_on_cycle_payment, add_beneficiary,
    make_underwriter_headers, make_policyowner_headers,
    EXAM_STANDARD,
)


def test_paramed_exam_validity_window_overlap_rejected(api):
    """PRD §3.3: "That test treats two exams' validity windows as overlapping exactly when
    each window's start falls strictly before the other window's exclusive end; two windows
    that merely touch end-to-start do not overlap, so adjacency is permitted."
    PRD §3.3: "If the exam being completed has a validity window that overlaps the window of
    any already-`COMPLETED` exam on the same application, completion is rejected with
    `ERR_EXAM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/paramed_exam_validity_window_overlap_closed_adjacency_allowed
    """
    ctx = setup_application_in_exam_pending()
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    # First COMPLETED exam dated 2026-01-10 -> window [2026-01-10, 2026-07-09) (180 days).
    e1 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                 "exam_date": "2026-01-10"}, u1_h), expected_status=201)
    validate_success(api.complete_paramed_exam(e1["id"], u1_h))
    # Second exam dated 2026-04-01 -> window [2026-04-01, 2026-09-28) OVERLAPS the first.
    e2 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 165, "systolic_bp": 122,
                 "exam_date": "2026-04-01"}, u1_h), expected_status=201)
    resp = api.complete_paramed_exam(e2["id"], u1_h)
    validate_error(resp, ApiErrorId.ERR_EXAM_WINDOW_OVERLAP.value)
    unchanged = validate_success(api.get_paramed_exam(e2["id"], u1_h))
    assert unchanged["status"] == "ORDERED", unchanged


def test_premium_coverage_period_overlap_rejected(api):
    """PRD §3.7: "Two payments' coverage intervals are considered overlapping exactly when
    one interval's start falls strictly before the other's end and that other's start falls
    strictly before the first's end; because the intervals are half-open, a payment whose
    coverage starts exactly where a prior payment's coverage ends does not overlap and is
    allowed."
    PRD §3.7: "A payment whose coverage interval overlaps an existing payment's interval on
    the same policy — for instance, an attempt to re-fund an already-funded anniversary — is
    rejected with `ERR_COVERAGE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/premium_coverage_period_overlap_half_open_abutment_allowed
    """
    # The on-cycle payment funds [2027-06-01, 2028-06-01) (default coverage start ==
    # next_premium_due_date). A re-fund of coverage_period_start 2027-06-01 funds the
    # identical interval [2027-06-01, 2028-06-01), which overlaps it -> rejected.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    make_on_cycle_payment(policy_id, applicant_id, 125000)  # funds 2027-06-01..2028-06-01
    resp = api.create_premium_payment(
        policy_id, {"amount_cents": 125000, "coverage_period_start": "2027-06-01"}, po_h
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value)
    payments, meta = validate_paginated(api.list_premium_payments(policy_id, po_h))
    # Issuing creates no PremiumPayment (PRD §3.6 lays down only a CashValueEntry), so
    # exactly the one accepted on-cycle payment stands; the overlapping re-fund was rejected.
    assert meta["total_count"] == 1, meta


def test_primary_beneficiary_share_total_conserved_at_100(api):
    """PRD §3.9: "Shares are validated per designation tier: after adding a beneficiary, the
    sum of `share_pct` across the `PRIMARY` tier must equal 100, and if any contingent
    beneficiary exists, the `CONTINGENT` tier's shares must likewise sum to 100; otherwise
    the operation is rejected with `ERR_BENEFICIARY_SHARE_INVALID`."

    Design: Difficulty/compensating_invariant/primary_beneficiary_share_total_conserved_at_100
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    # One PRIMARY at 100 (tier total 100).
    add_beneficiary(policy_id, applicant_id, full_name="Primary One",
                    designation="PRIMARY", share_pct=100)
    # A second PRIMARY at 100 would push the tier to 200 -> rejected; total stays 100.
    resp = api.create_beneficiary(
        policy_id, {"full_name": "Primary Two", "designation": "PRIMARY", "share_pct": 100}, po_h
    )
    validate_error(resp, ApiErrorId.ERR_BENEFICIARY_SHARE_INVALID.value)
    bens, _ = validate_paginated(api.list_beneficiaries(policy_id, po_h))
    primaries = [b for b in bens if b["designation"] == "PRIMARY"]
    assert len(primaries) == 1, bens
    assert primaries[0]["share_pct"] == 100, primaries


def test_beneficiary_primary_share_not_100_rejected(api):
    """PRD §3.9: "after adding a beneficiary, the sum of `share_pct` across the `PRIMARY`
    tier must equal 100 ... otherwise the operation is rejected with
    `ERR_BENEFICIARY_SHARE_INVALID`."

    Design: Corner/validations/beneficiary_primary_share_not_100_rejected
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    # A single PRIMARY at 60 (tier total 60 != 100) is rejected.
    resp = api.create_beneficiary(
        policy_id, {"full_name": "Half Primary", "designation": "PRIMARY", "share_pct": 60}, po_h
    )
    validate_error(resp, ApiErrorId.ERR_BENEFICIARY_SHARE_INVALID.value)
