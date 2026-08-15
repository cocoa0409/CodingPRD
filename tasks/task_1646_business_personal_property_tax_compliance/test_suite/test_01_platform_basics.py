"""Platform-wide contracts: response envelope, request context, existence,
pagination defaults, enum well-formedness, and read-after-write consistency."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_asset,
    create_asset_payload,
    create_class_rule_payload,
    create_client_payload,
    create_jurisdiction_payload,
    create_client_account,
    create_jurisdiction_account,
    new_analyst,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_response_envelope_success_and_error_shapes(api, firm_admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`." and "The `response_type` is either
    "object" for a single resource or "array" for a list of resources." and
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shapes
    """
    res = api.create_client(
        create_client_payload(legal_name="EnvCo", contact_email="env@x.com"),
        firm_admin_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert body["data"]["legal_name"] == "EnvCo"

    err_res = api.get_client(NON_EXISTENT_UUID, firm_admin_headers)
    assert err_res.status_code == 404
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


def test_create_client_missing_required_returns_invalid_request(api, firm_admin_headers):
    """PRD §2.9: "Body well-formedness: required fields present, enum values valid,
    integer ranges respected (`acquisition_cost_cents` strictly positive,
    `exemption_pct` and `abatement_pct` between 1 and 100 inclusive,
    `installment_count` between 1 and 4 inclusive, `last_tax_year` at least
    `first_tax_year`, `effective_date` strictly earlier than `expiration_date`),
    and `asset_tag` unique within its client — otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)." and PRD §3.1: "A engagement begins when a `FirmAdmin` onboards a
    client account with the client's `legal_name` and `contact_email`."

    Design: Corner/entities/create_client_missing_required_returns_invalid_request
    """
    res = api.create_client({"legal_name": "NoEmailCo"}, firm_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_get_asset_not_found_returns_404(api, firm_admin_headers):
    """PRD §2.4: "For any operation involving nested resources, the server validates
    path identifiers from left to right: the first identifier in the path that does
    not correspond to an existing resource produces an `ERR_NOT_FOUND` (HTTP 404)
    response, before any later path segment, request body, or business rule is
    examined."

    Design: Corner/entities/get_asset_not_found_returns_404
    """
    res = api.get_asset("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", firm_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_asset_list_pagination_defaults(api, firm_admin_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned;
    it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter sets the number of items skipped and defaults to 0." and "Unless
    otherwise specified, every list endpoint returns resources sorted by
    `created_at` in ascending order."

    Design: Corner/entities/asset_list_pagination_defaults
    """
    client = create_client_account(legal_name="PageCo", contact_email="page@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Page County")
    for i in range(1, 12):
        asset = validate_success(api.create_asset(
            create_asset_payload(client["id"], jurisdiction["id"],
                                 asset_tag=f"PG{i:02d}"),
            analyst["headers"]), 201)
        assert_asset(asset)

    data, meta = validate_paginated(
        api.list_assets(analyst["headers"], params={"client_id": client["id"]}))
    assert len(data) == 10, f"default page should hold 10 assets, got {len(data)}"
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    created = [a["created_at"] for a in data]
    assert created == sorted(created), "assets must be sorted by created_at ascending"

    data2, meta2 = validate_paginated(api.list_assets(
        analyst["headers"], params={"client_id": client["id"], "offset": 10}))
    assert len(data2) == 1
    assert meta2["total_count"] == 11
    assert meta2["has_more"] is False


def test_class_rule_invalid_enum_rejected(api, firm_admin_headers):
    """PRD §2.9: "Body well-formedness: required fields present, enum values valid,
    integer ranges respected (`acquisition_cost_cents` strictly positive,
    `exemption_pct` and `abatement_pct` between 1 and 100 inclusive,
    `installment_count` between 1 and 4 inclusive, `last_tax_year` at least
    `first_tax_year`, `effective_date` strictly earlier than `expiration_date`),
    and `asset_tag` unique within its client — otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)." and PRD §3.1: "A class rule names its owning `jurisdiction_id`
    and a `category` of `MACHINERY`, `FURNITURE`, `COMPUTER`, `VEHICLE`,
    `INVENTORY`, or `LEASEHOLD_IMPROVEMENT`"

    Design: Corner/entities/class_rule_invalid_enum_rejected
    """
    jurisdiction = create_jurisdiction_account(county_name="Enum County")
    res = api.create_class_rule(
        create_class_rule_payload(jurisdiction["id"], category="TOOLS"),
        firm_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, carrying an unrecognized role
    value, or carrying an identifier that fails to resolve for an entity-backed
    role is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400)." and PRD §2.9:
    "Incoming requests are checked against a fixed, ascending sequence of rules,
    and the first failing rule determines the error response — earlier checks mask
    later ones."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    # No X-User-ID / X-User-Role headers at all; the id does not exist either,
    # and request context (rule 1) must mask existence (rule 3).
    res = api.get_client("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                         {"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_CONTEXT_HEADER, expected_status=400)


def test_immediate_read_after_write_consistency(api, firm_admin_headers):
    """PRD §3.1: "The account is created with its `forecast_sequence` at zero; this
    counter records how many forecasts have ever been published for the client and
    increments by one on each publication." and PRD §2.4: "`created_at`, an ISO 8601
    UTC timestamp with three fractional digits recording when the resource was
    created"

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    res = api.create_client(
        create_client_payload(legal_name="ImmCo", contact_email="imm@x.com"),
        firm_admin_headers)
    created = validate_success(res, 201)

    got = validate_success(api.get_client(created["id"], firm_admin_headers), 200)
    assert got["legal_name"] == "ImmCo"
    assert got["forecast_sequence"] == 0
    assert isinstance(got["version"], int)
    assert got["created_at"] == created["created_at"], (
        "created_at must read back identically right after the write"
    )
