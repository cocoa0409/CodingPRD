"""Property onboarding, response envelope, and logical-clock defaults."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_property, create_property_payload,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]


def test_property_create_applies_defaults(api):
    """PRD section 3.1: "New properties begin with `posture` `NORMAL` and a
    `granted_purpose_count` of zero."
    PRD section 2.5: "`version` (integer):** starts at 1 and increments by one
    on every mutation of that resource."

    Design: Corner/entities/property_create_applies_defaults
    """
    res = api.create_property(
        create_property_payload(name="D", sale_share_designation="SELLS_AND_SHARES"), ADMIN
    )
    assert res.status_code == 201, f"expected 201, got {res.status_code}"
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["posture"] == "NORMAL"
    assert prop["granted_purpose_count"] == 0
    assert prop["version"] == 1


def test_property_create_invalid_enum_rejected(api):
    """PRD section 2.8: "Malformed payloads — missing required fields, type
    mismatches, enum values outside the declared sets — are rejected with
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/property_create_invalid_enum_rejected
    """
    res = api.create_property(
        create_property_payload(name="X", sale_share_designation="MAYBE"), ADMIN
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_property_create_client_id_input_ignored(api):
    """PRD section 2.5: "Clients supplying `id` or `version` inside creation
    payloads are ignored — the server mints its own."

    Design: Corner/entities/property_create_client_id_input_ignored
    """
    payload = create_property_payload(name="S", sale_share_designation="SHARES_ONLY")
    payload["id"] = "11111111-1111-1111-1111-111111111111"
    payload["version"] = 99
    prop = validate_success(api.create_property(payload, ADMIN), 201)
    assert prop["id"] != "11111111-1111-1111-1111-111111111111", (
        "server must mint its own id, ignoring the client-supplied one"
    )
    assert prop["version"] == 1


def test_property_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (`ERR_PROPERTY_NOT_FOUND`, ...)."

    Design: Corner/entities/property_get_not_found_returns_404
    """
    res = api.get_property(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_FOUND)


def test_success_envelope_shape(api):
    """PRD section 2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" with
    "`response_type` ... "object" for a single resource".

    Design: Corner/endpoints/success_envelope_shape
    """
    res = api.create_property(
        create_property_payload(name="ENV", sale_share_designation="SELLS_AND_SHARES"), ADMIN
    )
    body = res.json()
    assert res.status_code == 201
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    assert isinstance(body["data"].get("id"), str)


def test_error_envelope_shape(api):
    """PRD section 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" — "The `error_id` is a unique, machine-readable
    string that identifies the specific error" and "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape
    """
    res = api.get_property(NON_EXISTENT_UUID, ANY)
    body = res.json()
    assert res.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_PROPERTY_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0


def test_default_clock_pinned(api):
    """PRD section 2.4: "At startup the logical clock reads exactly
    `2026-05-01T00:00:00Z`."

    Design: Corner/cross_cutting_layers/default_clock_pinned
    """
    prop = get_success_data(
        api.create_property(create_property_payload(name="P", sale_share_designation="NO_SALE_NO_SHARE"), ADMIN)
    )
    from test_helpers import create_visitor_payload
    vis = validate_success(
        api.create_visitor(
            create_visitor_payload(prop["id"], external_ref="clk@x.com", jurisdiction_code="US-CA"),
            ANON,
        ),
        201,
    )
    # §2.4 pins the startup instant to 2026-05-01T00:00:00Z and §2.5 renders
    # created_at "with three fractional digits", so the stamped value is .000Z.
    assert vis["created_at"] == "2026-05-01T00:00:00.000Z"
