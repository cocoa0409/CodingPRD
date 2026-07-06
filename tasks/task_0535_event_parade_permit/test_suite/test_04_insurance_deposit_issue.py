"""Insurance (COI) acceptance checks, deposit underfunding, COI supersede/demote,
and issuance readiness gates (COI on file, deposit held, conditions acknowledged).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_applicant_headers, make_reviewer_headers, officer_headers,
    create_venue, create_applicant, create_closure_schedule, create_application,
    set_clock, get_reviews_by_department,
    setup_conditionally_approved, setup_under_review, STAFFING,
)
import test_helpers.factories as F


# ==========================================================================
# COI accept checks (queue A priority pair + queue B singles)
# ==========================================================================
def test_coverage_vs_coi_expiry_priority(api):
    """PRD §3.6: "Accepting a COI requires that it is SUBMITTED ..., that its
    coverage_amount is at least the application's required_coverage_min (else
    ERR_COI_COVERAGE_INSUFFICIENT, HTTP 402), and that its expires_at is strictly
    after the application's occupy_end (else ERR_COI_EXPIRES_BEFORE_EVENT)." PRD §2.6:
    the checks are evaluated so that "the COI expiry and coverage checks" run "in the
    order laid out through §3", the earlier masking the later.

    Design: Difficulty/priority_pair_validation_conflict/coverage_vs_coi_expiry_priority
    """
    set_clock("2026-05-01T00:00:00Z")
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    app = create_application(venue["id"], applicant["id"], event_kind="FESTIVAL",
                             expected_attendance=3000,
                             occupy_start="2026-06-10T10:00:00Z",
                             occupy_end="2026-06-10T14:00:00Z")
    # COI both under-covered (500000 < 1200000) AND expires before event (2026-06-01)
    coi = validate_success(api.submit_coi(app["id"],
                                          F.create_coi_payload(carrier="Cheap Ins",
                                                              coverage_amount=500000,
                                                              expires_at="2026-06-01T00:00:00Z"),
                                          hdrs), expected_status=201)
    resp = api.accept_coi(app["id"], coi["id"], officer_headers())
    # expiry check (temporal) precedes coverage check per §3 ordering
    validate_error(resp, ApiErrorId.ERR_COI_EXPIRES_BEFORE_EVENT, expected_status=409)


def test_coi_expiry_before_event_alone_rejected(api):
    """PRD §3.6: "that its expires_at is strictly after the application's occupy_end
    (else ERR_COI_EXPIRES_BEFORE_EVENT)." (Second angle on the same priority pair:
    when only the temporal check would fail — coverage is sufficient — the expiry
    error is still what surfaces, confirming it is a genuine independent trigger, not
    merely a masking artifact.)

    Design: Difficulty/priority_pair_validation_conflict/coverage_vs_coi_expiry_priority
    """
    set_clock("2026-05-01T00:00:00Z")
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    app = create_application(venue["id"], applicant["id"], event_kind="FESTIVAL",
                             expected_attendance=3000,
                             occupy_start="2026-06-10T10:00:00Z",
                             occupy_end="2026-06-10T14:00:00Z")
    # coverage sufficient (1,200,000) but expires before event (2026-06-01 < occupy_end)
    coi = validate_success(api.submit_coi(app["id"],
                                          F.create_coi_payload(carrier="OK Cover Expired",
                                                              coverage_amount=1_200_000,
                                                              expires_at="2026-06-01T00:00:00Z"),
                                          hdrs), expected_status=201)
    resp = api.accept_coi(app["id"], coi["id"], officer_headers())
    validate_error(resp, ApiErrorId.ERR_COI_EXPIRES_BEFORE_EVENT, expected_status=409)


def test_coi_coverage_insufficient_rejected(api):
    """PRD §3.6: "that its coverage_amount is at least the application's
    required_coverage_min (else ERR_COI_COVERAGE_INSUFFICIENT, HTTP 402)".

    Design: Corner/validations/coi_coverage_insufficient_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    app = create_application(venue["id"], applicant["id"], event_kind="FESTIVAL",
                             expected_attendance=3000,
                             occupy_start="2026-07-06T10:00:00Z",
                             occupy_end="2026-07-06T14:00:00Z")
    # coverage 900000 < 1200000; expiry valid (2027) so only coverage fails
    coi = validate_success(api.submit_coi(app["id"],
                                          F.create_coi_payload(carrier="Thin Ins",
                                                              coverage_amount=900000,
                                                              expires_at="2027-01-01T00:00:00Z"),
                                          hdrs), expected_status=201)
    resp = api.accept_coi(app["id"], coi["id"], officer_headers())
    validate_error(resp, ApiErrorId.ERR_COI_COVERAGE_INSUFFICIENT, expected_status=402)


# ==========================================================================
# COI supersede demotes prior accepted (queue B)
# ==========================================================================
def test_coi_supersede_demotes_prior_accepted(api):
    """PRD §3.6: "accepting a COI demotes any previously ACCEPTED certificate back to
    SUBMITTED; the flag coi_on_file is true precisely when there exists an ACCEPTED
    certificate meeting the coverage minimum." PRD §3.6: acceptance "recomputes the
    application's coi_on_file to true."

    Design: Corner/cross_cutting_complexity_layers/coi_supersede_demotes_prior_accepted
    """
    set_clock("2026-05-01T00:00:00Z")
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    app = create_application(venue["id"], applicant["id"], event_kind="FESTIVAL",
                             expected_attendance=3000,
                             occupy_start="2026-07-18T10:00:00Z",
                             occupy_end="2026-07-18T14:00:00Z")
    coi1 = validate_success(api.submit_coi(app["id"],
                                           F.create_coi_payload(carrier="First Ins",
                                                               coverage_amount=1_200_000,
                                                               expires_at="2027-01-01T00:00:00Z"),
                                           hdrs), expected_status=201)
    coi2 = validate_success(api.submit_coi(app["id"],
                                           F.create_coi_payload(carrier="Second Ins",
                                                               coverage_amount=1_500_000,
                                                               expires_at="2027-06-01T00:00:00Z"),
                                           hdrs), expected_status=201)
    api.accept_coi(app["id"], coi1["id"], officer_headers())
    api.accept_coi(app["id"], coi2["id"], officer_headers())
    cois = validate_success(api.list_coi(app["id"], officer_headers()))
    by_id = {c["id"]: c for c in cois}
    assert by_id[coi1["id"]]["status"] == "SUBMITTED"  # demoted
    assert by_id[coi2["id"]]["status"] == "ACCEPTED"
    app_now = validate_success(api.get_application(app["id"], officer_headers()))
    assert app_now["coi_on_file"] is True


# ==========================================================================
# Deposit underfunded (queue B)
# ==========================================================================
def test_deposit_underfunded_rejected(api):
    """PRD §3.6: "The Applicant pays a Deposit by supplying an amount, which must be
    at least the application's deposit_required or the payment is rejected with
    ERR_DEPOSIT_UNDERFUNDED (HTTP 402)."

    Design: Corner/validations/deposit_underfunded_rejected
    """
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-07-05T10:00:00Z",
                                       occupy_end="2026-07-05T14:00:00Z",
                                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    # deposit_required is 500 for MEDIUM; 400 < 500
    resp = api.pay_deposit(app_id, F.create_deposit_payload(400), hdrs)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNDERFUNDED, expected_status=402)


# ==========================================================================
# Issuance gates (queue A + queue B)
# ==========================================================================
def test_issue_requires_coi_accepted(api):
    """PRD §3.7: "Issuance requires that the application is CONDITIONALLY_APPROVED ...,
    that coi_on_file is true, meaning an accepted certificate meets
    required_coverage_min (else ERR_COI_NOT_ON_FILE)".

    Design: Difficulty/cross_entity_state_dependency/issue_requires_coi_accepted
    """
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-06-14T10:00:00Z",
                                       occupy_end="2026-06-14T14:00:00Z",
                                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    # Submit COI but do NOT accept; pay a valid deposit; no mandatory conditions
    api.submit_coi(app_id, F.create_coi_payload(coverage_amount=1_200_000,
                                                expires_at="2027-01-01T00:00:00Z"), hdrs)
    api.pay_deposit(app_id, F.create_deposit_payload(500), hdrs)
    resp = api.issue_application(app_id, officer_headers())
    validate_error(resp, ApiErrorId.ERR_COI_NOT_ON_FILE, expected_status=409)
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["coi_on_file"] is False
    assert app["status"] == "CONDITIONALLY_APPROVED"


def test_issue_succeeds_once_coi_accepted(api):
    """PRD §3.6: acceptance "moves the certificate SUBMITTED → ACCEPTED and recomputes
    the application's coi_on_file to true." PRD §3.7: "When these hold, the
    application transitions CONDITIONALLY_APPROVED → ISSUED, every PLANNED route
    segment moves to ACTIVE". (Second angle: the same cross-entity gate now
    satisfied — an ACCEPTED sibling COI makes coi_on_file true and issuance proceeds.)

    Design: Difficulty/cross_entity_state_dependency/issue_requires_coi_accepted
    """
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-08-14T10:00:00Z",
                                       occupy_end="2026-08-14T14:00:00Z",
                                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    coi = validate_success(api.submit_coi(app_id,
                                          F.create_coi_payload(coverage_amount=1_200_000,
                                                              expires_at="2027-01-01T00:00:00Z"),
                                          hdrs), expected_status=201)
    api.accept_coi(app_id, coi["id"], officer_headers())
    api.pay_deposit(app_id, F.create_deposit_payload(500), hdrs)
    resp = api.issue_application(app_id, officer_headers())
    app = validate_success(resp, expected_status=200)
    assert app["status"] == "ISSUED"
    assert app["coi_on_file"] is True


def test_issue_without_deposit_rejected(api):
    """PRD §3.7: "that a Deposit exists in HELD with an amount at least deposit_required
    (else ERR_DEPOSIT_NOT_HELD)".

    Design: Corner/validations/issue_without_deposit_rejected
    """
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-07-09T10:00:00Z",
                                       occupy_end="2026-07-09T14:00:00Z",
                                       set_clock_first=True)
    app_id = ctx["application"]["id"]
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    coi = validate_success(api.submit_coi(app_id,
                                          F.create_coi_payload(coverage_amount=1_200_000,
                                                              expires_at="2027-01-01T00:00:00Z"),
                                          hdrs), expected_status=201)
    api.accept_coi(app_id, coi["id"], officer_headers())
    # no deposit paid
    resp = api.issue_application(app_id, officer_headers())
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_HELD, expected_status=409)


def test_issue_with_unacknowledged_conditions_rejected(api):
    """PRD §3.7: "that every mandatory PermitCondition is ACKNOWLEDGED (else
    ERR_UNACKNOWLEDGED_CONDITIONS)". PRD §3.5: "A mandatory condition must be
    acknowledged before the permit can be issued."

    Design: Corner/validations/issue_with_unacknowledged_conditions_rejected
    """
    set_clock()
    # Reach UNDER_REVIEW, POLICE attaches a mandatory condition then approves,
    # others approve -> CONDITIONALLY_APPROVED with the condition still PROPOSED.
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="FESTIVAL",
                             occupy_start="2026-07-08T10:00:00Z",
                             occupy_end="2026-07-08T14:00:00Z")
    app_id = ctx["application"]["id"]
    applicant_id = ctx["applicant"]["id"]
    reviews = ctx["reviews"]
    hdrs = make_applicant_headers(applicant_id)
    api.add_condition(app_id, reviews["POLICE"],
                      {"text": "Provide traffic marshals", "mandatory": True},
                      make_reviewer_headers("POLICE"))
    for dept in ["POLICE", "FIRE", "EMS", "PUBLIC_WORKS"]:
        api.approve_review(app_id, reviews[dept], STAFFING[dept], make_reviewer_headers(dept))
    coi = validate_success(api.submit_coi(app_id,
                                          F.create_coi_payload(coverage_amount=1_200_000,
                                                              expires_at="2027-01-01T00:00:00Z"),
                                          hdrs), expected_status=201)
    api.accept_coi(app_id, coi["id"], officer_headers())
    api.pay_deposit(app_id, F.create_deposit_payload(500), hdrs)
    resp = api.issue_application(app_id, officer_headers())
    validate_error(resp, ApiErrorId.ERR_UNACKNOWLEDGED_CONDITIONS, expected_status=409)
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "CONDITIONALLY_APPROVED"
