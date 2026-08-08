"""Audits, the underpayment assessment formula, and the finding cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_assessment,
    TEST_USERS, make_authority_headers, make_operator_headers,
)
from test_helpers import (
    create_active_franchise, create_paid_report, create_accepted_report,
    set_clock, open_audit, finalize_finding, setup_open_audit_on_paid_report,
    setup_issued_assessment, get_franchise,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: assessment_tiered_penalty_plus_interest_mode_a ----
def test_assessment_principal_interest_penalty_components(api):
    """PRD 3.5 (Hop 1): "Its `principal_cents` is the audited fee ... minus the
    target report's `amount_paid_cents`. Its `days_late` is the whole number of
    days from the target report's `period_end_date` to the audit's
    `finalized_at`. Its `interest_cents` is the principal times a daily interest
    rate of 0.0005 ... times `days_late`, rounded half up."
    PRD 3.5 (Hop 1): "when the underpayment fraction is at least 0.10, the
    penalty is 15 percent of principal".

    Design: Difficulty/combinatorial_formula/assessment_tiered_penalty_plus_interest_mode_a
    """
    fr, rr, au, assessment = setup_issued_assessment(api)
    assert_assessment(assessment)
    assert assessment["principal_cents"] == 1000
    assert assessment["days_late"] == 100
    assert assessment["interest_cents"] == 50
    assert assessment["penalty_cents"] == 150


def test_assessment_total_is_sum_of_components(api):
    """PRD 3.5 (Hop 1): "The assessment's `total_cents` is the sum of
    `principal_cents`, `interest_cents`, and `penalty_cents`, and its
    `amount_paid_cents` starts at 0."

    Design: Difficulty/combinatorial_formula/assessment_tiered_penalty_plus_interest_mode_a
    """
    fr, rr, au, assessment = setup_issued_assessment(api)
    assert assessment["total_cents"] == 1200
    assert assessment["amount_paid_cents"] == 0


# ---- Difficulty: audit_finding_depth3_cascade ----
def test_finding_creates_issued_assessment(api):
    """PRD 3.5 (Hop 1): "A new `Assessment` is created at `status` `ISSUED`,
    linked to the finalized audit through `audit_id`, with `issued_by_user_id`
    copied from the audit's `finalized_by_user_id`."

    Design: Difficulty/transitive_cascade/audit_finding_depth3_cascade
    """
    fr, rr, au, assessment = setup_issued_assessment(api)
    assert assessment["status"] == "ISSUED"
    assert assessment["audit_id"] == au["id"]
    assert assessment["issued_by_user_id"] == "authority-lead"


def test_finding_cascades_report_and_franchise(api):
    """PRD 3.5 (Hop 2): "The target report advances from `UNDER_AUDIT` to
    `ADJUSTED`".
    PRD 3.5 (Hop 3): "The franchise's compliance axis flips from `COMPLIANT` or
    `CURED` to `IN_VIOLATION`".

    Design: Difficulty/transitive_cascade/audit_finding_depth3_cascade
    """
    fr, rr, au, assessment = setup_issued_assessment(api)
    report = validate_success(api.get_revenue_report(rr["id"], AUTHORITY), 200)
    assert report["status"] == "ADJUSTED"
    franchise = get_franchise(api, fr["id"])
    assert franchise["compliance_status"] == "IN_VIOLATION"


# ---- Difficulty: assessment_issue_then_waive_conserves_total_owed ----
def test_issue_then_waive_conserves_total_owed(api):
    """PRD 3.1: "Issuing an assessment and then waiving it therefore leaves
    `total_owed_cents` exactly where it stood before the assessment existed."
    PRD 3.5: "a waiver moves the assessment to `WAIVED` and recomputes
    `total_owed_cents` so the waived assessment leaves the outstanding set".

    Design: Difficulty/compensating_invariant/assessment_issue_then_waive_conserves_total_owed
    """
    fr, rr, au, assessment = setup_issued_assessment(api, issuer_user_id="authority-lead")
    owed_after_finding = get_franchise(api, fr["id"])["total_owed_cents"]
    assert owed_after_finding == 1200

    # A different authority user performs the waiver (segregation of duties).
    validate_success(api.waive_assessment(assessment["id"], make_authority_headers("authority-review")), 200)
    assert get_franchise(api, fr["id"])["total_owed_cents"] == 0


def test_waive_sets_assessment_waived(api):
    """PRD 3.5: "An authority waives an assessment from `ISSUED` or `DISPUTED`,
    subject to the segregation-of-duties rule of Section 2.10; a waiver moves the
    assessment to `WAIVED`".

    Design: Difficulty/compensating_invariant/assessment_issue_then_waive_conserves_total_owed
    """
    fr, rr, au, assessment = setup_issued_assessment(api, issuer_user_id="authority-lead")
    data = validate_success(api.waive_assessment(assessment["id"], make_authority_headers("authority-review")), 200)
    assert data["status"] == "WAIVED"


# ---- Difficulty: audit_period_closed_interval_shared_endpoint_overlap ----
def _two_accepted_reports_and_open_audit(api):
    fr = create_active_franchise(api)
    rr1 = create_accepted_report(api, fr["id"], period_start_date="2026-01-01",
                                 period_end_date="2026-03-31",
                                 residential_gross_cents=100000, commercial_gross_cents=40000,
                                 advertising_gross_cents=20000)
    rr2 = create_accepted_report(api, fr["id"], period_start_date="2026-04-01",
                                 period_end_date="2026-06-30",
                                 residential_gross_cents=110000, commercial_gross_cents=45000,
                                 advertising_gross_cents=22000)
    au1 = open_audit(api, fr["id"], rr1["id"], period_start_date="2026-01-01",
                     period_end_date="2026-03-31")
    return fr, rr1, rr2, au1


def test_audit_shared_endpoint_period_overlap_rejected(api):
    """PRD 3.5: "Audit periods are **closed** date intervals with no clearance
    buffer: two audits overlap when the later of their two start dates is at or
    before the earlier of their two end dates, so even a single shared endpoint
    date counts as an overlap and the create is rejected with
    `ERR_AUDIT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/audit_period_closed_interval_shared_endpoint_overlap
    """
    fr, rr1, rr2, au1 = _two_accepted_reports_and_open_audit(api)
    # New period [2026-03-31, 2026-06-30] shares only the endpoint 2026-03-31.
    resp = api.create_audit(
        {"franchise_id": fr["id"], "target_report_id": rr2["id"],
         "period_start_date": "2026-03-31", "period_end_date": "2026-06-30"}, AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP.value, 409)


def test_audit_adjacent_period_allowed(api):
    """PRD 3.5: "two audits overlap when the later of their two start dates is at
    or before the earlier of their two end dates". (An adjacent period whose
    start is strictly after the existing end does not overlap.)

    Design: Difficulty/resource_temporal_overlap/audit_period_closed_interval_shared_endpoint_overlap
    """
    fr, rr1, rr2, au1 = _two_accepted_reports_and_open_audit(api)
    # New period [2026-04-01, 2026-06-30]: start 04-01 is after existing end 03-31.
    resp = api.create_audit(
        {"franchise_id": fr["id"], "target_report_id": rr2["id"],
         "period_start_date": "2026-04-01", "period_end_date": "2026-06-30"}, AUTHORITY)
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"


# ---- Corner: audit_finalize_clean_restores_report_no_assessment ----
def test_audit_finalize_clean_restores_report(api):
    """PRD 3.5: "A **clean** finalize moves the audit to `COMPLETED_CLEAN` and
    restores the target report to whatever status it held before the audit —
    `ACCEPTED` or `PAID`."

    Design: Corner/state_machines/audit_finalize_clean_restores_report_no_assessment
    """
    fr, rr, au = setup_open_audit_on_paid_report(api)
    data = validate_success(api.finalize_audit(au["id"], {"finding": "CLEAN"}, make_authority_headers("authority-lead")), 200)
    assert data["status"] == "COMPLETED_CLEAN"
    report = validate_success(api.get_revenue_report(rr["id"], AUTHORITY), 200)
    assert report["status"] == "PAID"


# ---- Corner: audit_finding_without_underpayment_returns_error ----
def test_finding_without_underpayment_returns_error(api):
    """PRD 3.5: "A finding is only legitimate when the total audited gross
    strictly exceeds the total reported gross of the target report; if it does
    not exceed it, the finalize is rejected with `ERR_AUDIT_NO_UNDERPAYMENT`."

    Design: Corner/validations/audit_finding_without_underpayment_returns_error
    """
    fr, rr, au = setup_open_audit_on_paid_report(api)
    resp = api.finalize_audit(
        au["id"],
        {"finding": "FINDING", "audited_gross_residential_cents": 100010,
         "audited_gross_commercial_cents": 50010, "audited_gross_advertising_cents": 33330},
        make_authority_headers("authority-lead"))
    validate_error(resp, ApiErrorId.ERR_AUDIT_NO_UNDERPAYMENT.value, 409)


# ---- Corner (rbac): assessment_waive_by_issuer_segregation_of_duties ----
def test_issuer_cannot_waive_segregation_of_duties(api):
    """PRD 2.10: "That same user is forbidden from later waiving the assessment:
    a waiver whose `X-User-ID` equals the assessment's `issued_by_user_id` is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/rbac/assessment_waive_by_issuer_segregation_of_duties
    """
    fr, rr, au, assessment = setup_issued_assessment(api, issuer_user_id="authority-lead")
    resp = api.waive_assessment(assessment["id"], make_authority_headers("authority-lead"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
