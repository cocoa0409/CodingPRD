"""Trader and CurrencyPair onboarding tests — PRD §3.1."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_currency_pair,
    assert_trader,
    create_currency_pair_payload,
    create_trader_payload,
    validate_error,
    validate_success,
)


def test_create_trader_returns_active_status(api, risk_officer_headers):
    """PRD §3.1: "The newly minted trader's `status` field is initialised to
    `ACTIVE`; it remains there until either a settlement-failure cascade or
    an explicit risk-officer action drives it to `SUSPENDED`."

    Claim: a freshly created Trader has status == "ACTIVE".
    """
    res = api.create_trader(
        create_trader_payload(name="Alice", desk_code="G10_SPOT"),
        risk_officer_headers,
    )
    trader = validate_success(res, 201)
    assert_trader(trader)
    assert trader["status"] == "ACTIVE"
    assert trader["name"] == "Alice"
    assert trader["desk_code"] == "G10_SPOT"
    assert trader["version"] == 1


def test_get_nonexistent_trader_returns_not_found(api, risk_officer_headers):
    """PRD §2.9: "path-id existence raises `ERR_NOT_FOUND`".

    Claim: GET /fx-risk/traders/{missing-uuid} → ERR_NOT_FOUND, HTTP 404.
    """
    res = api.get_trader(NON_EXISTENT_UUID, risk_officer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# ===========================================================================
# CurrencyPair format validation — PRD §3.1
# ===========================================================================
def test_create_currency_pair_returns_pair(api, risk_officer_headers):
    """PRD §3.1: pair carries a six-letter `code` in `BASE_QUOTE` form;
    `base_ccy` and `quote_ccy` MUST agree with the first three and last
    three letters of `code` respectively.

    Claim: a well-formed pair (EURUSD / EUR / USD) is accepted.
    """
    res = api.create_currency_pair(
        create_currency_pair_payload(
            code="GBPUSD", base_ccy="GBP", quote_ccy="USD",
            mid_rate=1.250000, daily_volatility=0.005000,
        ),
        risk_officer_headers,
    )
    pair = validate_success(res, 201)
    assert_currency_pair(pair)
    assert pair["code"] == "GBPUSD"
    assert pair["base_ccy"] == "GBP"
    assert pair["quote_ccy"] == "USD"


@pytest.mark.parametrize("bad_code", [
    "EURUS",       # 5 letters
    "EURUSDX",     # 7 letters
    "eurusd",      # lowercase
    "EUR1SD",      # contains digit
    "EUR USD",     # contains space
])
def test_currency_pair_bad_code_format_rejected(api, risk_officer_headers, bad_code):
    """PRD §3.1: "The pair is rejected with `ERR_INVALID_PAIR_FORMAT` (HTTP
    422) when `code` is not exactly six uppercase letters, when the slices
    disagree with the supplied `base_ccy`/`quote_ccy`, or when a row with
    the same `code` already exists."

    Claim: any code not matching the six-uppercase-letter shape →
    ERR_INVALID_PAIR_FORMAT (422).
    """
    base = bad_code[0:3] if len(bad_code) >= 3 else "EUR"
    quote = bad_code[3:6] if len(bad_code) >= 6 else "USD"
    res = api.create_currency_pair(
        create_currency_pair_payload(
            code=bad_code, base_ccy=base, quote_ccy=quote,
        ),
        risk_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_PAIR_FORMAT.value, expected_status=422,
    )


def test_currency_pair_slice_mismatch_rejected(api, risk_officer_headers):
    """PRD §3.1: "The pair is rejected with `ERR_INVALID_PAIR_FORMAT` (HTTP
    422) when ... the slices disagree with the supplied `base_ccy`/
    `quote_ccy` ..."

    Claim: code="EURUSD" but base_ccy="GBP" → ERR_INVALID_PAIR_FORMAT.
    """
    res = api.create_currency_pair(
        create_currency_pair_payload(
            code="EURUSD", base_ccy="GBP", quote_ccy="USD",
        ),
        risk_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_PAIR_FORMAT.value, expected_status=422,
    )


def test_currency_pair_duplicate_code_rejected(api, risk_officer_headers):
    """PRD §3.1: "The pair is rejected with `ERR_INVALID_PAIR_FORMAT` (HTTP
    422) when ... a row with the same `code` already exists."

    Claim: a second create with the same `code` → ERR_INVALID_PAIR_FORMAT.
    """
    api.create_currency_pair(
        create_currency_pair_payload(code="USDJPY", base_ccy="USD", quote_ccy="JPY"),
        risk_officer_headers,
    )
    res = api.create_currency_pair(
        create_currency_pair_payload(
            code="USDJPY", base_ccy="USD", quote_ccy="JPY", mid_rate=150.0,
        ),
        risk_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_PAIR_FORMAT.value, expected_status=422,
    )
