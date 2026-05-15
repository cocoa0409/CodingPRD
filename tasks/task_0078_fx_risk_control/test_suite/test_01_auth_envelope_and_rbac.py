"""Auth, response envelope and RBAC tests.

Citations refer to PRD.md sections in the workspace.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_currency_pair_payload,
    create_trader_payload,
    setup_trader_with_limits,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_counterparty_payload


# ===========================================================================
# Auth header presence — PRD §2.1
# ===========================================================================
def test_missing_both_headers_returns_auth_required(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

    Claim: omitting both X-User-ID and X-User-Role → ERR_AUTH_REQUIRED, 401.
    """
    res = api.create_trader(create_trader_payload(), {})
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401)


def test_missing_user_id_returns_auth_required(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

    Claim: omitting X-User-ID while sending X-User-Role → ERR_AUTH_REQUIRED.
    """
    res = api.create_trader(
        create_trader_payload(), {"X-User-Role": "RiskOfficer"},
    )
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401)


def test_missing_user_role_returns_auth_required(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

    Claim: omitting X-User-Role while sending X-User-ID → ERR_AUTH_REQUIRED.
    """
    res = api.create_trader(
        create_trader_payload(), {"X-User-ID": "anybody"},
    )
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401)


def test_empty_user_id_returns_auth_required(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

    Claim: empty-string X-User-ID is treated as missing.
    """
    res = api.create_trader(
        create_trader_payload(),
        {"X-User-ID": "", "X-User-Role": "RiskOfficer"},
    )
    validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401)


# ===========================================================================
# Role gating — PRD §2.1 / §4
# ===========================================================================
def test_trader_cannot_create_trader(api, trader_fallback_headers):
    """PRD §2.1: "If both are present but the role is not permitted to
    invoke the requested endpoint per the role-to-endpoint matrix implicit
    in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Claim: Trader-role caller is not authorized for POST /fx-risk/traders
    (which §4 restricts to RiskOfficer) → ERR_FORBIDDEN.
    """
    res = api.create_trader(create_trader_payload(), trader_fallback_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_compliance_officer_cannot_create_trader(api, compliance_officer_headers):
    """PRD §2.1 / §4: POST /fx-risk/traders is restricted to RiskOfficer.

    Claim: a ComplianceOfficer caller is not authorized for trader creation
    → ERR_FORBIDDEN (HTTP 403).
    """
    res = api.create_trader(create_trader_payload(), compliance_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_settlement_operator_cannot_create_currency_pair(api, settlement_operator_headers):
    """PRD §2.1 / §4: POST /fx-risk/currency-pairs is restricted to
    RiskOfficer.

    Claim: SettlementOperator → ERR_FORBIDDEN.
    """
    res = api.create_currency_pair(
        create_currency_pair_payload(code="GBPUSD", base_ccy="GBP", quote_ccy="USD"),
        settlement_operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_risk_officer_cannot_create_counterparty(api, risk_officer_headers):
    """PRD §2.1 / §4: POST /fx-risk/counterparties is restricted to
    ComplianceOfficer.

    Claim: RiskOfficer caller → ERR_FORBIDDEN.
    """
    res = api.create_counterparty(
        create_counterparty_payload(), risk_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_market_data_cannot_create_trade(api):
    """PRD §2.1: "MarketDataSystem ... permitted only to push quotes and
    force stop-loss re-evaluation, never to mutate business entities
    directly."

    Claim: a MarketDataSystem caller posting to /fx-risk/trades →
    ERR_FORBIDDEN.
    """
    res = api.create_trade(
        {"pair_code": "EURUSD", "side": "BUY", "notional_base": 100.0,
         "entry_rate": 1.000000, "counterparty_id": "00000000-0000-0000-0000-000000000000"},
        TEST_USERS["market_data_headers"],
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
def test_success_envelope_shape_on_trader_create(api, risk_officer_headers):
    """PRD §2.2: success envelope carries `meta`, `response_type` and `data`;
    `meta` includes `api_request_id` (starts with `req_`) and an ISO 8601
    `api_request_timestamp`.

    Claim: a successful trader creation returns this exact envelope shape.
    """
    res = api.create_trader(create_trader_payload(), risk_officer_headers)
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body and isinstance(body["meta"], dict)
    assert "response_type" in body and body["response_type"] == "object"
    assert "data" in body and isinstance(body["data"], dict)
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_'; got {meta['api_request_id']!r}"
    )
    assert isinstance(meta.get("api_request_timestamp"), str)


def test_error_envelope_shape(api):
    """PRD §2.2 (error format): error body carries `meta`, `response_type`
    set to "error", and `data` with `error_id` and `message`.

    Claim: a missing-auth request returns this exact error envelope shape.
    """
    res = api.create_trader(create_trader_payload(), {})
    assert res.status_code == 401
    body = res.json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"] and "message" in body["data"]
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


# ===========================================================================
# desk_code allowed values — PRD §3.1
# ===========================================================================
@pytest.mark.parametrize("desk_code", ["INVALID_DESK", "g10_spot", "", "BONDS"])
def test_invalid_desk_code_rejected_as_validation(api, risk_officer_headers, desk_code):
    """PRD §3.1: "The `desk_code` must be one of the three permitted desk
    strings — `G10_SPOT`, `EM_FX`, or `OPTIONS` — otherwise the registration
    is rejected as a generic input failure."

    Claim: any desk_code outside that triple is rejected. Per PRD §2.9 the
    generic-input failure code is ERR_VALIDATION.
    """
    res = api.create_trader(
        create_trader_payload(desk_code=desk_code), risk_officer_headers,
    )
    assert res.status_code >= 400, (
        f"invalid desk_code {desk_code!r} must be rejected; got {res.status_code}"
    )
    assert res.json()["data"]["error_id"] in (
        "ERR_VALIDATION",
    ), (
        f"PRD §3.1 / §2.9: invalid desk_code is a generic input failure → "
        f"ERR_VALIDATION; got {res.json()['data']['error_id']!r}"
    )


@pytest.mark.parametrize("desk_code", ["G10_SPOT", "EM_FX", "OPTIONS"])
def test_each_permitted_desk_code_accepted(api, risk_officer_headers, desk_code):
    """PRD §3.1: "The `desk_code` must be one of the three permitted desk
    strings — `G10_SPOT`, `EM_FX`, or `OPTIONS`."

    Claim: each of the three permitted strings is accepted on create.
    """
    res = api.create_trader(
        create_trader_payload(desk_code=desk_code), risk_officer_headers,
    )
    trader = validate_success(res, expected_status=201)
    assert trader["desk_code"] == desk_code


# ===========================================================================
# Trader fetch is open to multiple roles — PRD §4
# ===========================================================================
def test_trader_can_fetch_own_trader(api):
    """PRD §4: GET /fx-risk/traders/{id} is authorized for
    RiskOfficer, Trader, ComplianceOfficer.

    Claim: a Trader caller with X-User-ID == trader.id can fetch.
    """
    ctx = setup_trader_with_limits()
    res = api.get_trader(ctx["trader"]["id"], ctx["trader_headers"])
    trader = validate_success(res, 200)
    assert trader["id"] == ctx["trader"]["id"]
