"""Optimistic concurrency on deal-scoped writes (PRD §2.7), auth/RBAC denials
(PRD §2.1), and the fixed response envelopes (PRD §2.2, §2.3)."""
from test_helpers import (
    ApiErrorId,
    add_property,
    create_deal,
    create_deal_payload,
    get_deal,
    setup_computed_scenario,
    setup_underwriting_env,
    validate_error,
    validate_paginated,
)


def test_scenario_create_stale_version_rejected(api, analyst_headers):
    """PRD §2.7: "Creating a `Scenario` against a deal — the request must carry
    `expected_deal_version`. If the deal's current `version` has advanced since
    the client last read it, the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412). This guards against the case where another writer has just
    advanced the deal's lifecycle (submitted it to IC, reopened it, or marked it
    dead) and the current writer's view of the deal's status is stale."
    PRD §3.1: "Each property creation bumps the parent deal's `version` by 1."
    — the interleaved property creation below is what advances the deal's
    version past the client's captured value.

    Design: Corner/endpoints/scenario_create_occ_stale_version_returns_412
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-OCC1"})
    deal_id = env["deal"]["id"]
    stale_version = env["deal"]["version"]

    add_property(deal_id, address_line="2 Second St")  # bumps deal.version

    res = api.create_scenario(deal_id, {
        "scenario_kind": "BASE",
        "assumption_id": env["assumption"]["id"],
        "occupancy_stress_pct": 90,
        "expected_deal_version": stale_version,
    }, analyst_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_ic_memo_create_stale_version_rejected(api, analyst_headers):
    """PRD §2.7: "Creating an `ICMemo` against a deal — same rule, same field,
    same rejection code. The request must carry `expected_deal_version`; a
    mismatch with the deal's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "Each property creation bumps the parent deal's `version` by 1."
    — the interleaved property creation below is what advances the deal's
    version past the client's captured value.

    Design: Corner/endpoints/ic_memo_create_occ_stale_version_returns_412
    """
    env = setup_computed_scenario(deal_overrides={"deal_code": "D-OCC2"})
    deal_id = env["deal"]["id"]
    stale_version = get_deal(deal_id)["version"]

    add_property(deal_id, address_line="2 Second St")  # bumps deal.version

    res = api.create_ic_memo(deal_id, {
        "scenario_id": env["scenario"]["id"],
        "recommendation": "PURSUE",
        "thesis": "t",
        "risks": "r",
        "expected_deal_version": stale_version,
    }, analyst_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_missing_role_header_returns_401(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. A request missing either header, presenting an empty
    `X-User-ID`, or carrying an `X-User-Role` value that is not one of the
    declared role names is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_401
    """
    headers = {"X-User-ID": "u-norole-1", "Content-Type": "application/json"}
    res = api.list_deals(headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_analyst_cannot_call_submit_ic(api, analyst_headers):
    """PRD §2.1: "A request whose role is not permitted for the requested
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`AssetManager` — senior reviewer; takes ownership of a deal once
    it moves into `UNDERWRITING`, submits deals to the IC, and marks rejected
    deals dead."

    Design: Corner/validations/analyst_cannot_call_submit_ic
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-RB1"})
    res = api.submit_ic(env["deal"]["id"], analyst_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_ic_member_cannot_create_deal(api, ic_member_headers):
    """PRD §2.1: "A request whose role is not permitted for the requested
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`Analyst` — deal originator; creates deals, enters rent roll and
    operating expense data, maintains market assumptions, builds scenarios,
    computes outputs, drafts IC memos, submits them, and reopens deals."

    Design: Corner/validations/ic_member_cannot_create_deal
    """
    res = api.create_deal(
        create_deal_payload(deal_code="D-RB2", target_purchase_price_cents=100),
        ic_member_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_list_endpoints_pagination_envelope(api, analyst_headers):
    """PRD §2.3: "All list endpoints accept `limit` and `offset` query
    parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0. Results are always sorted by `created_at` ascending
    (oldest first) unless stated otherwise. List responses include `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/list_endpoints_respond_with_pagination_envelope
    """
    for code in ("D-ENV1", "D-ENV2", "D-ENV3"):
        create_deal(deal_code=code, target_purchase_price_cents=100)

    rows, meta = validate_paginated(api.list_deals(analyst_headers))
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert len(rows) == 3
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta missing {field}"
    body = api.list_deals(analyst_headers).json()
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_error_response_uses_fixed_envelope(api, analyst_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.6: "If any path segment does not resolve, the request is rejected
    with `ERR_NOT_FOUND` (HTTP 404) before any other check runs."

    Design: Corner/endpoints/error_response_uses_fixed_envelope
    """
    res = api.get_deal("00000000-0000-0000-0000-000000000000", analyst_headers)
    error = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    assert error["error_id"] == "ERR_NOT_FOUND"
    body = res.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only the two fixed fields, got {sorted(body['meta'].keys())}"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
