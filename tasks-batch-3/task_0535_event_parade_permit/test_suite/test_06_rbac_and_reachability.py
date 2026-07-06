"""Role-based access control (exclusive-operation denial, ownership, missing
headers) and child-collection reverse-reachability by FK.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    ApiErrorId,
    build_user_headers,
    make_applicant_headers, make_reviewer_headers, officer_headers,
    create_venue, create_applicant, create_closure_schedule, create_application,
    add_segment, setup_under_review,
)
import test_helpers.factories as F


# ==========================================================================
# RBAC: exclusive-operation denied (queue B)
# ==========================================================================
def test_reviewer_cannot_issue_permit(api):
    """PRD §2.1: "When the headers are present and valid but the caller's role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)." PRD §4 (endpoint): "POST
    /permit-applications/{id}/issue ... PermitOfficer".

    Design: Corner/rbac/reviewer_cannot_issue_permit
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="PARADE",
                             expected_attendance=500,
                             occupy_start="2026-07-10T10:00:00Z",
                             occupy_end="2026-07-10T14:00:00Z")
    resp = api.issue_application(app["id"], make_reviewer_headers("POLICE"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


# ==========================================================================
# RBAC: ownership isolation (queue B)
# ==========================================================================
def test_applicant_cannot_submit_others_application(api):
    """PRD §2.1: "every applicant-restricted action on that application verifies that
    X-User-ID equals applicant_user_id; a mismatch is rejected with
    ERR_NOT_APPLICATION_OWNER (HTTP 403)." PRD §3.4: "The caller must own the
    application or the submit is rejected with ERR_NOT_APPLICATION_OWNER."

    Design: Corner/rbac/applicant_cannot_submit_others_application
    """
    venue = create_venue(max_capacity=6000, setup_buffer_minutes=60)
    schedule = create_closure_schedule(min_gap_minutes=30)
    owner = create_applicant(org_name="Owner", contact_email="own@x.com")
    intruder = create_applicant(org_name="Intruder", contact_email="int@x.com")
    app = create_application(venue["id"], owner["id"], event_kind="PARADE",
                             expected_attendance=500,
                             occupy_start="2026-07-11T10:00:00Z",
                             occupy_end="2026-07-11T14:00:00Z")
    add_segment(app["id"], owner["id"], schedule["id"], segment_label="CC 1",
                closure_start="2026-07-11T09:00:00Z", closure_end="2026-07-11T15:00:00Z")
    resp = api.submit_for_review(app["id"], {"expected_venue_version": venue["version"]},
                                 make_applicant_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_APPLICATION_OWNER, expected_status=403)


# ==========================================================================
# RBAC: missing/invalid user context header (queue B)
# ==========================================================================
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or its value is not a recognized,
    well-formed identifier/role, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)." PRD §2.1: "The system
    recognizes exactly three roles, spelled precisely as follows: Applicant,
    DepartmentReviewer, and PermitOfficer."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = build_user_headers("someone", "NoSuchRole")
    resp = api.create_venue(F.create_venue_payload(name="V", venue_type="PARK",
                                                   max_capacity=6000),
                            bad_headers)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        ApiErrorId.ERR_UNAUTHORIZED,
    ])


# ==========================================================================
# Reverse-reachability: conditions by review (queue B)
# ==========================================================================
def test_conditions_reverse_reachable_by_review(api):
    """PRD §4 (endpoint): "GET /permit-applications/{appId}/reviews/{reviewId}/conditions
    — List conditions imposed by a review". PRD §3.5: a condition "records the
    department_review_id of the review that imposed it".

    Design: Corner/endpoints/conditions_reverse_reachable_by_review
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="PARADE",
                             occupy_start="2026-07-15T10:00:00Z",
                             occupy_end="2026-07-15T14:00:00Z")
    app_id = ctx["application"]["id"]
    police = ctx["reviews"]["POLICE"]
    cond = validate_success(api.add_condition(app_id, police,
                                              {"text": "Add barricades", "mandatory": True},
                                              make_reviewer_headers("POLICE")),
                            expected_status=201)
    resp = api.list_review_conditions(app_id, police, officer_headers())
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    for c in data:
        assert c["department_review_id"] == police


# ==========================================================================
# Reverse-reachability: COI by application (queue B)
# ==========================================================================
def test_coi_reverse_reachable_by_application(api):
    """PRD §4 (endpoint): "GET /permit-applications/{appId}/coi — List an
    application's COIs". PRD §3.6: the COI is submitted against a specific
    application (it belongs to that application).

    Design: Corner/endpoints/coi_deposit_invoice_debrief_reverse_reachable
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    app = create_application(venue["id"], applicant["id"], event_kind="FESTIVAL",
                             expected_attendance=3000,
                             occupy_start="2026-07-16T10:00:00Z",
                             occupy_end="2026-07-16T14:00:00Z")
    api.submit_coi(app["id"], F.create_coi_payload(coverage_amount=1_200_000,
                                                   expires_at="2027-01-01T00:00:00Z"), hdrs)
    resp = api.list_coi(app["id"], officer_headers())
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    for c in data:
        assert c["application_id"] == app["id"]
