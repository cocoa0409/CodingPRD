"""Participant onboarding, commodity catalogue, and the daily price sheet (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_commodity,
    create_customer,
    create_shipper_payload,
    post_daily_price,
    set_clock,
    setup_market_day,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN_HEADERS, RECEIVER_HEADERS, SALES_HEADERS


def test_create_shipper_missing_required_field_returns_validation(api):
    """PRD §3.1: "A shipper is registered with its legal `name` and `paca_license`;
    the shipper's `status` starts at `ACTIVE` and its `trust_exposure_cents` starts at 0."
    PRD §5: "ERR_VALIDATION | 422".

    Design: Corner/entities/create_shipper_missing_required_field_returns_validation
    """
    resp = api.create_shipper({"paca_license": "PACA-001"}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_customer_defaults_applied_on_create(api):
    """PRD §3.1: "A customer is registered with `name`, `credit_limit_cents`, an
    optional `terms_days` (defaulting to 10), and an optional `paca_special_agreement`
    flag (defaulting to false)."
    PRD §3.1: "A customer's `status` begins at `ACTIVE`"

    Design: Corner/entities/customer_defaults_applied_on_create
    """
    resp = api.create_customer({"name": "Buyer D", "credit_limit_cents": 500000},
                               ADMIN_HEADERS)
    data = validate_success(resp, 201)
    assert data["terms_days"] == 10
    assert data["paca_special_agreement"] is False
    assert data["status"] == "ACTIVE"
    assert data["credit_exposure_cents"] == 0


def test_commodity_invalid_ethylene_class_returns_validation(api):
    """PRD §3.1: "an `ethylene_class` drawn from `PRODUCER`, `SENSITIVE`, or `NEUTRAL`"
    PRD §5: "ERR_VALIDATION | 422".

    Design: Corner/entities/commodity_invalid_ethylene_class_returns_validation
    """
    resp = api.create_commodity(
        {"code": "XXX", "name": "Mystery", "ethylene_class": "EXPLOSIVE",
         "temp_min_f": 34, "temp_max_f": 40}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_daily_price_mid_price_computed(api):
    """PRD §3.1: "The server computes `mid_price` as the arithmetic mean of
    `low_price` and `high_price`, rounded half-up to two decimal places."

    Design: Corner/entities/daily_price_mid_price_computed
    """
    commodity = create_commodity(code="TOM", name="Tomato", temp_min_f=45, temp_max_f=55)
    resp = api.create_daily_price(
        {"commodity_id": commodity["id"], "market_date": "2026-05-01",
         "low_price": 8.00, "high_price": 12.02}, ADMIN_HEADERS)
    data = validate_success(resp, 201)
    assert data["mid_price"] == pytest.approx(10.01), (
        f"mean of 8.00 and 12.02 rounded half-up to 2dp must be 10.01, "
        f"got {data['mid_price']}")


def test_second_daily_price_for_same_key_returns_duplicate_price(api):
    """PRD §3.1: "Only one price row may exist per `(commodity_id, market_date)`
    pair; a duplicate post is rejected with `ERR_DUPLICATE_PRICE` (HTTP 409)."

    Design: Corner/errors/second_daily_price_for_same_key_returns_duplicate_price
    """
    commodity = create_commodity(code="TOM", name="Tomato")
    post_daily_price(commodity["id"], market_date="2026-05-01",
                     low_price=8.00, high_price=12.00)
    resp = api.create_daily_price(
        {"commodity_id": commodity["id"], "market_date": "2026-05-01",
         "low_price": 9.00, "high_price": 11.00}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRICE)


def test_lot_create_without_daily_price_returns_price_not_posted(api):
    """PRD §3.1: "a lot cannot be created for a `(commodity_id, market_date)` that
    has no posted row — such a create fails with `ERR_PRICE_NOT_POSTED`"

    Design: Corner/validations/lot_create_without_daily_price_returns_price_not_posted
    """
    base = setup_market_day()  # price posted for 2026-05-01 only
    resp = api.create_purchase_lot(
        {"shipper_id": base["shipper"]["id"], "commodity_id": base["commodity"]["id"],
         "market_date": "2026-05-02", "quantity_units": 10,
         "shipper_unit_price": 10.00, "declared_grade": "US1"}, RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_PRICE_NOT_POSTED)


def test_lot_price_outside_daily_band_returns_price_out_of_range(api):
    """PRD §3.1: "the agreed `shipper_unit_price` must lie within the day's
    `[low_price, high_price]` band, inclusive on both ends, or the create is
    rejected with `ERR_PRICE_OUT_OF_RANGE`."

    Design: Corner/validations/lot_price_outside_daily_band_returns_price_out_of_range
    """
    base = setup_market_day()  # band [8.00, 12.00]
    ok = api.create_purchase_lot(
        {"shipper_id": base["shipper"]["id"], "commodity_id": base["commodity"]["id"],
         "market_date": "2026-05-01", "quantity_units": 10,
         "shipper_unit_price": 12.00, "declared_grade": "US1"}, RECEIVER_HEADERS)
    validate_success(ok, 201)  # exactly the high bound is inclusive -> accepted

    too_high = api.create_purchase_lot(
        {"shipper_id": base["shipper"]["id"], "commodity_id": base["commodity"]["id"],
         "market_date": "2026-05-01", "quantity_units": 10,
         "shipper_unit_price": 12.01, "declared_grade": "US1"}, RECEIVER_HEADERS)
    validate_error(too_high, ApiErrorId.ERR_PRICE_OUT_OF_RANGE)

    too_low = api.create_purchase_lot(
        {"shipper_id": base["shipper"]["id"], "commodity_id": base["commodity"]["id"],
         "market_date": "2026-05-01", "quantity_units": 10,
         "shipper_unit_price": 7.99, "declared_grade": "US1"}, RECEIVER_HEADERS)
    validate_error(too_low, ApiErrorId.ERR_PRICE_OUT_OF_RANGE)


def test_customer_create_terms_over_30_returns_terms_exceeded(api):
    """PRD §3.1: "PACA prompt-payment rules cap `terms_days` at 30 unless the buyer
    has a written special agreement on file; a create or update that sets
    `terms_days` greater than 30 while `paca_special_agreement` is false is rejected
    with `ERR_TERMS_EXCEEDED`."

    Design: Corner/validations/customer_create_terms_over_30_returns_terms_exceeded
    """
    denied = api.create_customer(
        {"name": "Buyer Slow", "credit_limit_cents": 500000, "terms_days": 31},
        ADMIN_HEADERS)
    validate_error(denied, ApiErrorId.ERR_TERMS_EXCEEDED)

    allowed = api.create_customer(
        {"name": "Buyer Agreed", "credit_limit_cents": 500000, "terms_days": 31,
         "paca_special_agreement": True}, ADMIN_HEADERS)
    data = validate_success(allowed, 201)
    assert data["terms_days"] == 31
    assert data["paca_special_agreement"] is True
