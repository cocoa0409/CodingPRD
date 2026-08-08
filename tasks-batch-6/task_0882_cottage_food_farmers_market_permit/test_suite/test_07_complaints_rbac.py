"""Complaint segregation of duties and role/auth enforcement."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_producer_headers, make_inspector_headers, TEST_USERS,
    create_permit_payload,
    register_producer, create_registered_producer,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def test_complaint_review_by_filer_rejected(api):
    """PRD §2.7: "Any later review or resolution of that complaint must be performed by a
    different user: the acting `X-User-ID` must not equal `filed_by_user_id`. A reviewer
    or resolver who is the same person as the filer is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/complaint_review_by_filer_returns_segregation_of_duties
    """
    producer = register_producer(api, business_name="CompCo")
    filer = make_inspector_headers("insp-1")
    complaint = validate_success(api.create_complaint(
        {"producer_id": producer["id"], "category": "LABELING", "description": "no allergen line"}, filer), 201)
    resp = api.review_complaint(complaint["id"], filer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
    after = get_success_data(api.get_complaint(complaint["id"], INSPECTOR))
    assert after["status"] == "RECEIVED"


def test_complaint_review_by_distinct_user_succeeds(api):
    """PRD §3.6: "Advancing a complaint to `UNDER_REVIEW` records the reviewer in
    `reviewed_by_user_id` and, per the segregation-of-duties rule of §2.7, requires that
    the reviewer's `X-User-ID` differ from `filed_by_user_id`, failing with
    `ERR_SEGREGATION_OF_DUTIES` otherwise."

    Design: Corner/state_machines/complaint_sod_distinct_reviewer_succeeds
    """
    producer = register_producer(api, business_name="Comp2 Co")
    filer = make_inspector_headers("insp-1")
    reviewer = make_inspector_headers("insp-2")
    complaint = validate_success(api.create_complaint(
        {"producer_id": producer["id"], "category": "ILLNESS", "description": "reported illness"}, filer), 201)
    reviewed = validate_success(api.review_complaint(complaint["id"], reviewer), 200)
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == "insp-2"


def test_producer_cannot_issue_permit(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/producer_cannot_issue_permit_unauthorized
    """
    producer = create_registered_producer(api, business_name="Rb Co")
    pid = producer["id"]
    ph = make_producer_headers(pid)
    permit = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_A"), ph), 201)
    validate_success(api.submit_permit(permit["id"], ph), 200)
    resp = api.issue_permit(permit["id"], ph)  # issue is HealthInspector-exclusive
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/rbac/missing_auth_context_returns_400
    """
    resp = api.create_producer(
        {"business_name": "NoAuth", "operator_name": "Na A", "contact_email": "na@x.com",
         "county": "Alameda", "water_source": "PUBLIC"}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT.value, 400)
