"""Authentication, authorization, error envelope, and logical-clock monotonicity."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_customer, create_part, create_aog_request_payload, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    this declared set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/auth_header_missing_returns_unauthenticated
    """
    res = api.list_customers(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_role_not_permitted_for_quote_create(api, warehouse_operator_headers):
    """PRD §2.1: "A request whose role is not permitted for the targeted
    endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §2.11: gate 2 authorization runs before business evaluation, so an
    empty body from a WarehouseOperator still surfaces ERR_FORBIDDEN.

    Design: Corner/validations/role_not_permitted_forbidden
    """
    res = api.create_quote({}, warehouse_operator_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_authorization_precedes_existence(api, warranty_approver_headers):
    """PRD §2.11: "the server evaluates them in a fixed priority order so the
    surfaced error is deterministic. Lower-numbered gates run first" — gate 2
    is "The role must be permitted for the endpoint" and gate 3 is "Path
    identifiers are validated left to right".

    Design: Corner/validations/authz_beats_existence_on_path
    """
    res = api.suspend_customer(NON_EXISTENT_UUID, warranty_approver_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_platformops_denied_business_surface(api, platform_ops_headers):
    """PRD §2.1: "`PlatformOps` holds no business-surface permissions at all;
    it exists solely to operate the logical clock and the operations sweep
    described in §2.10 and §3.9."

    Design: Corner/rbac/platformops_denied_business_surface
    """
    res = api.create_customer(
        {"name": "X", "country_code": "US", "credit_limit_cents": 1000},
        platform_ops_headers,
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_compliance_officer_cannot_create_shipment(api, compliance_officer_headers):
    """PRD §2.8: "the screening decision itself belongs exclusively to the
    `ComplianceOfficer`, who is deliberately kept away from the physical flow
    of goods: a compliance officer can certify trace documentation and record
    screening outcomes but can never allocate, tender, or deliver."
    PRD §4: POST /aog/shipments is authorized for WarehouseOperator only.

    Design: Corner/rbac/compliance_officer_cannot_create_shipment
    """
    res = api.create_shipment({}, compliance_officer_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_adjuster_cannot_approve_role_exclusive(api, warranty_adjuster_headers):
    """PRD §3.8: "The decision then belongs to a `WarrantyApprover`" — the
    approve capability is approver-exclusive, and per §2.11 gate 2 the role
    check runs before existence, so a WarrantyAdjuster gets ERR_FORBIDDEN even
    for a non-existent claim id.

    Design: Corner/rbac/adjuster_cannot_approve_role_exclusive
    """
    res = api.approve_warranty_claim(NON_EXISTENT_UUID, warranty_adjuster_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_error_envelope_shape_on_400(api, finance_controller_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with response_type "error" and data carrying
    error_id and message; "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §3.1: credit_limit_cents is "a `credit_limit_cents` ceiling that must
    be zero or positive".

    Design: Corner/endpoints/error_envelope_shape_on_400
    """
    res = api.create_customer(
        {"name": "BadEnum", "country_code": "US", "credit_limit_cents": -5},
        finance_controller_headers,
    )
    err = validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    assert isinstance(err.get("message"), str) and err["message"], (
        "error data.message must be a non-empty string"
    )
    body = res.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]


def test_clock_regression_rejected(api, platform_ops_headers,
                                   finance_controller_headers):
    """PRD §2.10: "The clock is monotonic: an attempt to move it backwards is
    rejected with `ERR_CLOCK_REGRESSION`."
    PRD §3.3: "a hard dispatch deadline `needed_by_utc` that must lie strictly
    after the current clock — a deadline in the past or at the present instant
    is rejected with `ERR_NEEDED_BY_IN_PAST`." Filing with needed_by equal to
    the unmoved clock must still fail, proving the regression never took.

    Design: Corner/errors/clock_regression_rejected
    """
    ok = validate_success(api.set_clock("2026-05-10T00:00:00Z", platform_ops_headers))
    assert ok["current_utc"].startswith("2026-05-10T00:00:00")

    res = api.set_clock("2026-05-09T00:00:00Z", platform_ops_headers)
    validate_error(res, "ERR_CLOCK_REGRESSION", expected_status=400)

    # Clock must still read 2026-05-10: a needed_by equal to that instant is
    # not strictly after the clock, so the create must be refused.
    customer = create_customer(name="ClockAir")
    part = create_part()
    res = api.create_aog_request(
        create_aog_request_payload(
            customer["id"], part["id"], needed_by_utc="2026-05-10T00:00:00Z"
        ),
        AGENT,
    )
    validate_error(res, "ERR_NEEDED_BY_IN_PAST", expected_status=422)
