"""Validation precedence, numeric/temporal boundaries, and cross-entity guards.

Covers difficulty rules priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, and resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_applicant_headers, make_licensing_officer_headers,
    create_activity_category_payload, create_business_payload,
    create_application_payload, create_inspection_payload,
    record_inspection_payload, create_transfer_payload,
    TEST_USERS,
    setup_issued_license, setup_delinquent_license,
    get_license_fee_assessments, assessments_of_kind, set_clock,
)

OFFICER = TEST_USERS["licensing_officer_headers"]
INSPECTOR = TEST_USERS["inspection_officer_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
ISSUER = make_licensing_officer_headers("officer-issuer")


# ─── Rule 5: validation precedence conflicts ──────────────────────────────
def test_segregation_beats_other_checks_on_issue(api):
    """PRD §3.5: "the issuing officer's `X-User-ID` must differ from every
    `inspector_user_id` recorded on any inspection of this application: an officer
    who inspected the premises may not also issue its license. A violation of this
    segregation of duties is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_inspection_prereq_on_issue
    """
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="SOD_CAT", risk_tier="LOW", activity_base_risk=10,
            required_inspection_count=1, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="SOD Co", owner_name="SO",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "dual-officer"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 1, 0), INSPECTOR))
    get_success_data(api.approve_application(app["id"], OFFICER))

    # Issue acting as the SAME id that inspected -> segregation wins (state is valid).
    res = api.issue_application(app["id"], make_licensing_officer_headers("dual-officer"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


def test_state_beats_fiscal_on_surrender(api):
    """PRD §2.4: "State legality comes fifth: if the target resource is not in a
    state from which the requested transition is defined, the request is rejected
    with `ERR_INVALID_STATE` (HTTP 409). Only after these five tiers pass does the
    system evaluate the domain-specific business rules described throughout §2 and
    §3 (segregation of duties, inspection prerequisites, standing, transferability,
    zoning, renewal windows, revocation thresholds, outstanding fees, optimistic
    concurrency, and uniqueness)."
    PRD §3.7: "Surrender is the voluntary terminus, performed by an `Applicant` on
    an `ACTIVE` license, advancing it `ACTIVE → SURRENDERED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_surrender
    """
    # DELINQUENT license (not ACTIVE) with an unsettled assessment: both surrender
    # preconditions fail; the state check (tier 5) wins over the fiscal check.
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-07-15T00:00:00Z")
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    res = api.surrender_license(lic["id"], biz_h)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Rule 6: boundary precision ───────────────────────────────────────────
def test_delinquency_grace_boundary_day30_zero_penalty(api):
    """PRD §3.6: "If `days_overdue` is at most the 30-day grace period, the
    penalty rate is zero."
    PRD §3.6: "The delinquency assessment always opens a `RENEWAL_FEE`
    assessment for the renewal fee, and additionally opens a `DELINQUENCY_PENALTY`
    assessment for the penalty whenever the penalty is greater than zero."

    Design: Difficulty/boundary_precision_check/delinquency_grace_boundary_day30_vs_day31
    """
    # expires 2027-06-01; clock 2027-07-01 = exactly 30 days overdue -> 0 penalty.
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-07-01T00:00:00Z")
    lic = ctx["license"]
    assert lic["status"] == "DELINQUENT"
    ledger = get_license_fee_assessments(lic["id"])
    penalties = assessments_of_kind(ledger, "DELINQUENCY_PENALTY")
    assert penalties == [], f"expected no DELINQUENCY_PENALTY at day 30, got {penalties}"


def test_inspection_prereq_zero_count_boundary(api):
    """PRD §3.4: "Both branches share the same prerequisite: the count of this
    application's inspections whose `result` is `PASSED` must be at least the
    category's `required_inspection_count`. If too few passed inspections exist,
    approval is rejected with `ERR_INSPECTION_PREREQUISITE_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/inspection_prereq_empty_set_zero_count_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="PREREQ_CAT", risk_tier="LOW", activity_base_risk=10,
            required_inspection_count=1, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Prereq Co", owner_name="PC",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    get_success_data(api.zoning_check_application(app["id"], OFFICER))
    # Zero PASSED inspections though required_inspection_count == 1.
    res = api.approve_application(app["id"], OFFICER)
    validate_error(res, "ERR_INSPECTION_PREREQUISITE_NOT_MET", expected_status=409)


# ─── Rule 7: cross-entity state dependencies ──────────────────────────────
def test_submit_requires_business_good_standing(api):
    """PRD §3.2: "Two preconditions guard the submission: the application must
    currently be in `DRAFT`, and the referenced business must be in `GOOD`
    standing — a business whose standing is not `GOOD` causes the submission to
    fail with `ERR_BUSINESS_NOT_IN_GOOD_STANDING` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_business_good_standing
    """
    # First license driven DELINQUENT so the business standing != GOOD; a second
    # DRAFT application's submit is then blocked.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "STD_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz = ctx["business"]
    biz_h = ctx["biz_headers"]
    cat = ctx["category"]
    set_clock("2027-07-15T00:00:00Z")
    demoted = get_success_data(api.assess_delinquency(lic["id"], OFFICER))
    assert demoted["status"] == "DELINQUENT"

    app2 = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    res = api.submit_application(app2["id"], biz_h)
    validate_error(res, "ERR_BUSINESS_NOT_IN_GOOD_STANDING", expected_status=409)


def test_transfer_approve_requires_license_active(api):
    """PRD §3.9: "A `LicensingOfficer` approves a requested transfer (`REQUESTED →
    APPROVED`), which additionally requires that the license be `ACTIVE`".
    PRD §3.9: "A transfer may only target a license that is `ACTIVE`; at request,
    approval, and completion, a license that is `DELINQUENT`, `REVOKED`, or
    `SURRENDERED` causes rejection with `ERR_LICENSE_NOT_TRANSFERABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_license_active
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "TRF_MED", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    seller = ctx["business"]
    seller_h = ctx["biz_headers"]
    buyer = get_success_data(api.create_business(
        create_business_payload(legal_name="Buyer Co", owner_name="BU",
                                zone_code="C1"), APPLICANT))
    tr = get_success_data(api.create_transfer(
        create_transfer_payload(lic["id"], seller["id"], buyer["id"]), seller_h))
    set_clock("2027-07-15T00:00:00Z")
    get_success_data(api.assess_delinquency(lic["id"], OFFICER))  # license -> DELINQUENT

    res = api.approve_transfer(tr["id"], OFFICER)
    validate_error(res, "ERR_LICENSE_NOT_TRANSFERABLE", expected_status=409)


# ─── Rule 8: temporal-interval boundaries ─────────────────────────────────
def test_renewal_window_closed_before_lower_bound(api):
    """PRD §3.6: "Renewal is only permitted once the renewal window has opened —
    that is, when the current clock instant is at or after the license's
    `expires_on` minus the renewal window of 60 days. A renewal attempted before
    that window opens is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/renewal_window_half_open_lower_bound
    """
    # expires 2027-06-01; clock 2027-03-31 = 62 days before expiry, window opens
    # at day 60 (2027-04-02), so the window is still CLOSED.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "WIN_MED", "risk_tier": "MEDIUM", "activity_base_risk": 20,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    set_clock("2027-03-31T00:00:00Z")
    res = api.renew_license(lic["id"], biz_h)
    validate_error(res, "ERR_RENEWAL_WINDOW_CLOSED", expected_status=409)


def test_revocation_threshold_not_reached_at_exactly_90(api):
    """PRD §3.7: "It is gated on time: revocation is only permitted once
    `days_overdue` exceeds the revocation threshold of 90 days; an attempt before
    that threshold is rejected with `ERR_REVOCATION_THRESHOLD_NOT_REACHED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/revocation_threshold_closed_upper_interval
    """
    # expires 2027-06-01; clock 2027-08-30 = exactly 90 days overdue -> NOT yet
    # over threshold (strictly greater than 90 required).
    ctx = setup_delinquent_license(risk_tier="MEDIUM",
                                   overdue_clock="2027-08-30T00:00:00Z")
    lic = ctx["license"]
    assert lic["status"] == "DELINQUENT"
    res = api.revoke_license(lic["id"], OFFICER)
    validate_error(res, "ERR_REVOCATION_THRESHOLD_NOT_REACHED", expected_status=409)
