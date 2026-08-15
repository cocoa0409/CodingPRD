"""Response envelope, auth-header, and request-shape validation claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    agent_payload,
    create_lead_source,
    create_team,
    lead_payload,
    lead_source_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["team_admin_headers"]


def test_response_envelope_success_and_error_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_success_and_error_shapes
    """
    team = create_team()

    res = api.get_team(team["id"], ADMIN)
    data = validate_success(res, 200)
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert data["id"] == team["id"]

    err_res = api.get_lead(NON_EXISTENT_UUID, ADMIN)
    validate_error(err_res, ApiErrorId.ERR_NOT_FOUND)
    ebody = err_res.json()
    assert ebody["response_type"] == "error"
    assert set(ebody["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert ebody["data"]["error_id"] == "ERR_NOT_FOUND"


def test_request_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.8: "First come the identity headers of §2.1, then role authorization."

    Design: Corner/errors/request_missing_auth_headers_rejected
    """
    create_team()
    # No X-User-ID / X-User-Role at all — the auth check fires before existence,
    # so even a nonexistent team id surfaces the header error, not a 404.
    res = api.get_team(NON_EXISTENT_UUID, {})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400)


def test_get_nonexistent_lead_returns_not_found(api):
    """PRD §2.8: "Fourth, existence: every id referenced in the path and in the body must exist, validated left-to-right, else `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_lead_returns_not_found
    """
    create_team()
    res = api.get_lead(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_lead_missing_required_field_rejected(api):
    """PRD §3.3: "A `TeamAdmin`, a `TeamLeader`, or a `ReferralPartner` creates a lead with `team_id`, `source_id`, `contact_name`, `contact_phone`, `contact_email`, and a strictly positive `expected_close_price_cents` that feeds projected source ROI."
    PRD §2.8: "Third, body well-formedness — required fields present, no undeclared fields (a strict schema under which computed or system-maintained fields sent by the client are rejected), enum values valid, datetimes parseable, and integer ranges respected — all failing as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_lead_missing_required_field_rejected
    """
    team = create_team()
    source = create_lead_source(team["id"], auto_route=False)
    payload = lead_payload(team["id"], source["id"], "+15125550160")
    del payload["contact_phone"]
    res = api.create_lead(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_source_with_invalid_enum_rejected(api):
    """PRD §3.3: "A `TeamAdmin` registers a lead source with `team_id`, a display `name` (for example, "Zillow Premier"), a `type` of `PORTAL`, `IDX_WEBSITE`, `PAID_AD`, `REFERRAL_PARTNER`, `SPHERE`, or `SIGN_CALL`, the `cost_per_lead_cents` attributed to each intake (zero or more), and the `monthly_budget_cents` spend ceiling (zero or more)."
    PRD §2.8: "Third, body well-formedness — required fields present, no undeclared fields (a strict schema under which computed or system-maintained fields sent by the client are rejected), enum values valid, datetimes parseable, and integer ranges respected — all failing as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_source_with_invalid_enum_rejected
    """
    team = create_team()
    payload = lead_source_payload(team["id"], name="Billboard", type="BILLBOARD")
    res = api.create_lead_source(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
