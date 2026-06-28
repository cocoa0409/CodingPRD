"""Entity CRUD, defaults, computed fields, enums, immutability, and listing.

Translates corner-design instances under section: entities (queue B).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    assert_fund, assert_investor,
    set_clock, create_fund, create_share_class, create_approved_investor,
    create_subscription, settle_subscription,
    create_fund_payload, create_investor_payload, create_share_class_payload,
    NON_EXISTENT_UUID,
    make_fund_manager_headers, make_anonymous_headers, make_operator_headers,
)

FM = make_fund_manager_headers()
ANON = make_anonymous_headers()
OP = make_operator_headers()


def test_create_fund_returns_201_with_bootstrap_nav(api):
    """PRD §3.1: "A newly created fund is `OPEN`; the system initializes its `shares_outstanding`
    to 0, its `total_capital_cents` to 0, and its `current_valuation_seq` to 0, and bootstraps its
    `nav_per_share_cents` to 1000 — that is, ten dollars par per share — because no shares yet
    exist to divide the net asset value across."

    Design: Corner/entities/create_fund_returns_201_with_bootstrap_nav
    """
    res = api.create_fund(
        {"name": "Fund E1", "vehicle_type": "REIT",
         "gross_asset_value_cents": 500_000, "total_liabilities_cents": 0}, FM)
    fund = validate_success(res, 201)
    assert_fund(fund)
    assert fund["status"] == "OPEN"
    assert fund["nav_per_share_cents"] == 1000
    assert fund["shares_outstanding"] == 0
    assert fund["total_capital_cents"] == 0
    assert fund["current_valuation_seq"] == 0
    assert fund["version"] == 1


def test_get_fund_not_found_returns_404(api):
    """PRD §2.5: "the first identifier in the path that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_fund_not_found_returns_404
    """
    res = api.get_fund(NON_EXISTENT_UUID, FM)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_investor_missing_required_field_returns_invalid_request(api):
    """PRD §3.3: "Registration supplies an `email` (globally unique ...), a `full_name`, an
    optional `accredited_status` ... and the declared `annual_income_cents` and `net_worth_cents`
    that will drive the non-accredited investment cap."
    PRD §3.9: "a malformed body — a missing required field, a wrong type, or an invalid enum value
    — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_investor_missing_required_field_returns_invalid_request
    """
    res = api.create_investor(
        {"email": "m@x.com", "full_name": "M", "annual_income_cents": 8_000_000}, ANON)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_investor_accredited_status_defaults_non_accredited(api):
    """PRD §3.3: "an optional `accredited_status` of `NON_ACCREDITED` or `ACCREDITED` (defaulting
    to `NON_ACCREDITED`)".
    PRD §3.3: "A freshly registered investor has `suitability_status` of `PENDING`".

    Design: Corner/entities/investor_accredited_status_defaults_non_accredited
    """
    res = api.create_investor(
        {"email": "def@x.com", "full_name": "Def",
         "annual_income_cents": 8_000_000, "net_worth_cents": 12_000_000}, ANON)
    inv = validate_success(res, 201)
    assert inv["accredited_status"] == "NON_ACCREDITED"
    assert inv["suitability_status"] == "PENDING"


def test_fund_nav_recomputed_after_valuation_post(api):
    """PRD §3.1: "it recomputes `nav_per_share_cents` from the newly written net assets, and it
    freezes that just-computed NAV onto the valuation record as `resulting_nav_per_share_cents` so
    the historical price for that quarter is preserved."
    PRD §3.1: "it assigns the valuation a monotonic per-fund `seq` (the first valuation on a fund
    is `seq` 1 ...), ... it advances the fund's `current_valuation_seq` to match".

    1000 shares, gross 1,000,000, liab 0 -> net 1,000,000 / 1000 = 1000.

    Design: Corner/entities/fund_nav_recomputed_after_valuation_post
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    val = get_success_data(api.create_valuation(
        fund["id"], {"period_label": "2026-Q1", "gross_asset_value_cents": 1_000_000,
                     "total_liabilities_cents": 0}, FM))
    assert val["resulting_nav_per_share_cents"] == 1000
    fund_after = get_success_data(api.get_fund(fund["id"], FM))
    assert fund_after["nav_per_share_cents"] == 1000
    assert fund_after["current_valuation_seq"] == 1


def test_fund_system_fields_ignored_from_input(api):
    """PRD §3.1: "A newly created fund is `OPEN`; the system initializes its `shares_outstanding`
    to 0".

    Design: Corner/entities/fund_system_fields_input_ignored
    """
    res = api.create_fund(
        {"name": "Fund SF", "vehicle_type": "PARTNERSHIP",
         "gross_asset_value_cents": 0, "total_liabilities_cents": 0,
         "status": "WINDING_DOWN", "shares_outstanding": 999}, FM)
    fund = validate_success(res, 201)
    assert fund["status"] == "OPEN"
    assert fund["shares_outstanding"] == 0


def test_fund_invalid_vehicle_type_enum_returns_invalid_request(api):
    """PRD §3.1: "a `vehicle_type`, which is one of `REIT` or `PARTNERSHIP`."
    PRD §3.9: "a malformed body — a missing required field, a wrong type, or an invalid enum value
    — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/fund_invalid_vehicle_type_enum_returns_invalid_request
    """
    res = api.create_fund(
        {"name": "Bad", "vehicle_type": "LLC",
         "gross_asset_value_cents": 0, "total_liabilities_cents": 0}, FM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_valuation_first_seq_is_one(api):
    """PRD §3.1: "it assigns the valuation a monotonic per-fund `seq` (the first valuation on a
    fund is `seq` 1, and each subsequent posting is one greater)".
    PRD §2.4: "A `Valuation` and a `DistributionAllocation` are immutable audit records minted once
    and never modified; each carries only `id` and `created_at`, and neither has an `updated_at`
    field nor a `version` field."

    Design: Corner/entities/valuation_immutable_no_version_field
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    val = get_success_data(api.create_valuation(
        fund["id"], {"period_label": "2026-Q1", "gross_asset_value_cents": 1_000_000,
                     "total_liabilities_cents": 0}, FM))
    assert val["seq"] == 1
    assert "version" not in val
    assert "updated_at" not in val


def test_share_class_create_wrong_parent_fund_returns_not_found(api):
    """PRD §2.5: "the parent must be resolved before the child is even looked up, and the first
    identifier in the path that does not resolve produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/share_class_create_wrong_parent_fund_returns_not_found
    """
    res = api.create_share_class(
        NON_EXISTENT_UUID,
        {"class_code": "A", "min_investment_cents": 100_000, "mgmt_fee_bps": 100}, FM)
    validate_error(res, "ERR_NOT_FOUND")


def test_list_funds_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned ... Each list
    response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/entities/list_funds_pagination_envelope
    """
    create_fund(name="F1", vehicle_type="REIT")
    create_fund(name="F2", vehicle_type="PARTNERSHIP")
    data, meta = validate_paginated(api.list_funds(FM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert len(data) == 1
    assert meta["has_more"] is True
