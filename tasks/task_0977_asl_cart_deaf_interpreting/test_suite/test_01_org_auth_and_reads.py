"""Organization onboarding, user-context auth, role-vs-existence ordering, and shared reads."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    build_user_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_org_payload,
    set_clock,
    create_org,
    create_draft_request,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def test_create_org_with_required_fields_returns_201():
    """PRD §3.1: "A `PlatformAdmin` onboards a requesting organization by supplying
    its display `name`, its `org_type` — one of `MEDICAL`, `LEGAL`, `EDUCATION`, or
    `GENERAL`, declaring the primary ADA service context — and its `credit_limit_cents`,
    the maximum outstanding exposure the platform will tolerate for the org. A new
    organization starts `ACTIVE` with `version` 1."
    PRD §3.1: "It is recomputed on every read as the sum of `amount_due_cents` over
    that organization's invoices whose `issue_status` is `ISSUED` and whose
    `payment_status` is not `PAID`."

    Design: Corner/entities/create_org_with_required_fields_returns_201
    """
    set_clock("2026-05-01T00:00:00Z")
    resp = api_client.create_org(
        create_org_payload(name="Metro Hospital", org_type="MEDICAL",
                           credit_limit_cents=500000),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["status"] == "ACTIVE", f"new org must start ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"new org must start at version 1, got {data['version']}"
    assert data["outstanding_balance_cents"] == 0, (
        "with no ISSUED invoices the read-time aggregation sums to 0"
    )
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601"


def test_get_nonexistent_ids_return_404s():
    """PRD §2.8: "Each missing resource maps to a dedicated not-found error:
    `ERR_ORG_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`,
    `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AVAILABILITY_WINDOW_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_CREDIT_MEMO_NOT_FOUND`,
    `ERR_STRIKE_NOT_FOUND`, and `ERR_REPORT_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/get_nonexistent_ids_return_404s
    """
    set_clock("2026-05-01T00:00:00Z")
    cases = [
        (api_client.get_request, ApiErrorId.ERR_REQUEST_NOT_FOUND),
        (api_client.get_org, ApiErrorId.ERR_ORG_NOT_FOUND),
        (api_client.get_interpreter, ApiErrorId.ERR_INTERPRETER_NOT_FOUND),
        (api_client.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api_client.get_report, ApiErrorId.ERR_REPORT_NOT_FOUND),
    ]
    for getter, expected in cases:
        resp = getter(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, expected)


def test_missing_auth_role_header_returns_400():
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming the capacity in which they act. The
    declared roles are `PlatformAdmin`, `OrgRequester`, `Interpreter`, `QualityReviewer`,
    `BillingClerk`, and `Any`. A request missing either header, or naming a role
    outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_role_header_returns_400
    """
    anonymous = build_user_headers("test-anon-1", "Anonymous")
    resp = api_client.create_org(
        {"name": "X", "org_type": "MEDICAL", "credit_limit_cents": 1000},
        anonymous,
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_check_precedes_existence_returns_unauthorized():
    """PRD §2.10: "When several validations could reject the same request, they are
    evaluated in a fixed twelve-tier order, and the earliest failing tier determines
    the error returned." and "Third, role permission (`ERR_UNAUTHORIZED_ROLE`).
    Fourth, entity-backed ownership (`ERR_FORBIDDEN_OWNERSHIP`). Fifth, existence of
    every path- and body-referenced identifier, left to right (the not-found catalog
    of §2.8)."
    PRD §4: POST /interpreters/{id}/activate is authorized for PlatformAdmin only.

    Design: Corner/validations/role_check_precedes_existence_returns_unauthorized
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    org_headers = build_user_headers(org["id"], "OrgRequester")
    resp = api_client.activate_interpreter(NON_EXISTENT_UUID, org_headers)
    # Role tier (third) fires before the existence tier (fifth): 403, not 404.
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_all_roles_can_read_shared_get_endpoints():
    """PRD §2.1: "The `Any` role is not an operational actor; it denotes that any
    authenticated declared role may perform read operations."
    PRD §4: GET /requests/{id} is authorized for Any.

    Design: Corner/rbac/all_roles_can_read_shared_get_endpoints
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    req = create_draft_request(
        org["id"],
        consumer_name="Dee Af",
        modality="VRI",
        ada_context="GENERAL",
        scheduled_start="2026-06-10T14:00:00Z",
        scheduled_end="2026-06-10T15:00:00Z",
        onsite_address=None,
        estimated_mileage=0,
    )
    from test_helpers import (
        make_org_requester_headers,
        make_interpreter_headers,
        create_interpreter_payload,
        get_success_data,
    )
    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(), ADMIN))
    readers = [
        ADMIN,
        make_org_requester_headers(org["id"]),
        make_interpreter_headers(interp["id"]),
        REVIEWER,
        CLERK,
    ]
    payloads = []
    for headers in readers:
        resp = api_client.get_request(req["id"], headers)
        payloads.append(validate_success(resp, 200))
    for payload in payloads[1:]:
        assert payload == payloads[0], "every declared role reads the same payload"
    assert payloads[0]["id"] == req["id"]
