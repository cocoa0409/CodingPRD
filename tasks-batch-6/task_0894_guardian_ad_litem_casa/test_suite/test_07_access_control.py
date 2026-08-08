"""Global contract surface: header authentication, role/ownership authorization,
and list pagination.

Queue B (Corner): validations (missing header), rbac denials, endpoints
(pagination).
"""
from test_helpers import (
    validate_paginated,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_supervisor,
    make_supervisor_headers,
    setup_submitted_expense,
    setup_submitted_report,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_missing_user_context_header_rejected(api):
    """PRD 2.1: "When either header is missing or does not carry a recognized
    value, the request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/validations/missing_user_context_header_returns_400
    """
    resp = api.list_volunteers({})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_volunteer_pagination_reports_total_and_has_more(api):
    """PRD 2.3: "The limit parameter caps the number of items returned; when
    omitted it defaults to 10, and it is constrained to a minimum of 1 and a
    maximum of 100."
    PRD 2.3: "Every list response echoes limit, offset, total_count, and has_more
    inside the meta object."

    Design: Corner/endpoints/list_volunteers_pagination_has_more
    """
    get_success_data(api.create_volunteer(
        {"full_name": "Val One", "email": "v1@casa.org", "home_zip": "94601"}, ADMIN))
    get_success_data(api.create_volunteer(
        {"full_name": "Val Two", "email": "v2@casa.org", "home_zip": "94602"}, ADMIN))
    data, meta = validate_paginated(api.list_volunteers(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_volunteer_cannot_approve_expense(api):
    """PRD 2.1: "When a caller holds a valid role but that role — or the ownership
    relationship it implies — does not permit the requested operation, the request
    is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/volunteer_cannot_approve_expense_unauthorized
    """
    base = setup_submitted_expense(api, budget=20000, total_miles=50, other_expense_cents=0)
    resp = api.approve_expense(base["expense_claim_id"], base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_foreign_supervisor_cannot_review_report(api):
    """PRD 3.6: "Review is performed only by the case's own supervisor; an attempt
    by any other supervisor is ERR_UNAUTHORIZED."

    Design: Corner/rbac/foreign_supervisor_cannot_review_report_unauthorized
    """
    base = setup_submitted_report(api)
    s2 = create_supervisor(api, email="s2@casa.org", full_name="Sup Two")
    resp = api.review_report(
        base["report_id"], {"decision": "APPROVE"}, make_supervisor_headers(s2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_supervisor_cannot_register_volunteer(api):
    """PRD 2.1: "When a caller holds a valid role but that role — or the ownership
    relationship it implies — does not permit the requested operation, the request
    is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/supervisor_cannot_register_volunteer_unauthorized
    """
    s1 = create_supervisor(api, email="s1@casa.org")
    resp = api.create_volunteer(
        {"full_name": "Sneaky", "email": "x@casa.org", "home_zip": "94601"},
        make_supervisor_headers(s1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
