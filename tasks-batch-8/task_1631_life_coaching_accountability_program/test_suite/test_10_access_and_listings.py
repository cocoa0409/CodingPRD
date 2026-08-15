"""RBAC denials and allowances, plus list-endpoint pagination/filtering."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    add_member,
    book_session,
    create_client,
    create_coach,
    create_open_cohort,
    create_cohort_payload,
    make_client_headers,
    make_coach_headers,
    reset_clock,
    set_clock,
    setup_active_enrollment,
    setup_multi_client_active_enrollments,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["practice_manager_headers"]


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request with a missing or unrecognized `X-User-Role`, or
    one missing `X-User-ID` where the role requires it, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    reset_clock()
    coach = create_coach(verify=False)
    resp = api.get_coach(coach["id"], NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_client_cannot_verify_credential_returns_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint —
    or whose entity-backed identity does not own the target resource, such as
    a client acting on another client's enrollment or a coach completing
    another coach's session — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: "credential verification is performed by a `PracticeManager`,
    never by the coach themself".

    Design: Corner/validations/client_cannot_verify_credential_returns_forbidden
    """
    reset_clock()
    coach = create_coach(verify=False)
    client = create_client()
    resp = api.verify_credential(
        coach["id"], make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    from test_helpers import get_coach
    assert get_coach(coach["id"])["credential_status"] == "PENDING_VERIFICATION"


def test_client_cannot_cancel_other_clients_session_returns_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint —
    or whose entity-backed identity does not own the target resource, such as
    a client acting on another client's enrollment or a coach completing
    another coach's session — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/client_cannot_cancel_other_clients_session_returns_forbidden
    """
    ctx = setup_multi_client_active_enrollments(2)
    client_a, client_b = ctx["clients"]
    enr_a = ctx["enrollments"][0]
    sess = book_session(
        enr_a["id"], client_a, scheduled_start="2026-08-10T10:00:00Z")
    resp = api.cancel_session(sess["id"], make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    from test_helpers import get_session
    assert get_session(sess["id"])["session_status"] == "SCHEDULED"


def test_coach_cannot_approve_refund_returns_forbidden(api):
    """PRD §3.9: "Adjudication belongs to the `PracticeManager`."
    PRD §2.1: "A request whose role is not permitted for the endpoint — or
    whose entity-backed identity does not own the target resource, such as a
    client acting on another client's enrollment or a coach completing
    another coach's session — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/coach_cannot_approve_refund_returns_forbidden
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    resp = api.create_refund_request(
        {"enrollment_id": enrollment["id"]}, make_client_headers(client["id"]))
    rr = validate_success(resp, expected_status=201)
    resp = api.approve_refund_request(
        rr["id"], make_coach_headers(ctx["coach_a"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    data = validate_success(api.get_refund_request(rr["id"], PM))
    assert data["refund_status"] == "PENDING"


def test_platform_admin_cannot_open_cohort_returns_forbidden(api):
    """PRD §3.7: "A cohort begins `DRAFT`; the facilitating coach opens it —
    `DRAFT` to `OPEN`". (PRD §4 lists only Coach under the open endpoint's
    authorized roles.)
    PRD §2.1: "A request whose role is not permitted for the endpoint — or
    whose entity-backed identity does not own the target resource, such as a
    client acting on another client's enrollment or a coach completing
    another coach's session — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_open_cohort_returns_forbidden
    """
    reset_clock()
    coach = create_coach()
    resp = api.create_cohort(
        create_cohort_payload(coach["id"], title="Admin Test", capacity=3),
        make_coach_headers(coach["id"]),
    )
    cohort = validate_success(resp, expected_status=201)
    resp = api.open_cohort(cohort["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    from test_helpers import get_cohort
    assert get_cohort(cohort["id"])["cohort_status"] == "DRAFT"


def test_coach_can_read_shared_get_endpoints(api):
    """PRD §4 routes `GET /coaching/enrollments` to "PlatformAdmin,
    PracticeManager, Coach, Client" as authorized roles, and PRD §3.3 states
    "Enrollment records list with filters `client_id`, `coach_id`,
    `program_tier_id`, `discovery_call_id`, and `lifecycle_status`".
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    (The endpoint table in PRD §4 lists GET /coaching/enrollments with
    authorized roles PlatformAdmin, PracticeManager, Coach, Client.)

    Design: Corner/rbac/coach_can_read_shared_get_endpoints
    """
    reset_clock()
    coach = create_coach(verify=False)
    resp = api.list_enrollments(make_coach_headers(coach["id"]))
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 0
    assert data == []


def test_list_enrollments_pagination_defaults_and_filter(api):
    """PRD §3.3: "Enrollment records list with filters `client_id`,
    `coach_id`, `program_tier_id`, `discovery_call_id`, and
    `lifecycle_status`". PRD §2.3: "If not provided, it defaults to 10, with
    a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `offset` parameter specifies the number of items to skip
    and defaults to 0."
    PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."
    PRD §2.2: the envelope carries "meta.api_request_id" and
    "meta.api_request_timestamp" on every response.

    Design: Corner/endpoints/list_enrollments_pagination_defaults_and_filter
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    other_client = create_client()

    resp = api.list_enrollments(PM, params={"client_id": client["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 1 and data[0]["id"] == enrollment["id"]
    body = resp.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]

    resp = api.list_enrollments(PM, params={"client_id": other_client["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0
    assert data == []
