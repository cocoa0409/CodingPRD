"""Property registration / AVM valuation and offer-issuance pricing.

Covers the provisional (offer-time) valuation surface: avm_value computation,
service fee, estimated concession, preliminary net proceeds, and the minimum
offerable-value floor.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_seller,
    assert_property,
    assert_offer,
    create_seller_payload,
    create_property_payload,
    issue_offer_payload,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_seller,
    create_property,
    setup_property_under_offer,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_create_property_computes_avm_and_initial_state(api):
    """PRD §3.1: "the platform immediately computes the property's automated
    valuation, `avm_value`, by taking `comp_median_value`, multiplying it by one
    plus `market_trend_pct`, and rounding the result half-up to two decimal places."
    PRD §3.1: "A newly registered property opens in `VALUED` status."
    PRD §3.1: "its `condition_score` starts null until a home assessment writes it"

    Design: Corner/entities/create_property_computes_avm_and_initial_state
    """
    seller = create_seller()
    payload = create_property_payload(
        seller["id"], comp_median_value=500000, market_trend_pct=0.02
    )
    data = validate_success(api.create_property(payload, _ANALYST), 201)
    assert_property(data)
    assert data["avm_value"] == 510000.00, data["avm_value"]
    assert data["status"] == "VALUED"
    assert data["version"] == 1
    assert data["condition_score"] is None


def test_create_property_missing_comp_median_value_returns_invalid_request(api):
    """PRD §2.7: "A missing required field, a value of the wrong type, or a value
    outside its declared enum or numeric range is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "the `comp_median_value` — the median sale price of the comparable
    set, in dollars, which must be zero or greater."

    Design: Corner/entities/create_property_missing_comp_median_value_returns_invalid_request
    """
    seller = create_seller()
    payload = {
        "seller_id": seller["id"],
        "address_line": "101 Oak",
        "zip_code": "90001",
        "bedrooms": 3,
        "living_area_sqft": 1800,
        # comp_median_value omitted
    }
    validate_error(api.create_property(payload, _ANALYST), ApiErrorId.ERR_INVALID_REQUEST)


def test_create_property_default_market_trend_pct_zero(api):
    """PRD §3.1: "The trend defaults to 0.0 and must lie between -0.50 and 0.50
    inclusive."
    PRD §3.1: "by taking `comp_median_value`, multiplying it by one plus
    `market_trend_pct`, and rounding the result half-up to two decimal places."

    Design: Corner/entities/create_property_default_market_trend_pct_zero
    """
    seller = create_seller()
    payload = {
        "seller_id": seller["id"],
        "address_line": "102 Oak",
        "zip_code": "90001",
        "bedrooms": 3,
        "living_area_sqft": 1800,
        "comp_median_value": 500000,
        # market_trend_pct omitted -> defaults 0.0
    }
    data = validate_success(api.create_property(payload, _ANALYST), 201)
    assert data["avm_value"] == 500000.00, data["avm_value"]
    assert data["market_trend_pct"] == 0.0


def test_seller_create_default_payout_method_ach(api):
    """PRD §3.1: "The `payout_method` accepts either `ACH` or `WIRE` and defaults
    to `ACH` when omitted."

    Design: Corner/entities/seller_create_default_payout_method_ach
    """
    payload = {"email": "ach-default@example.com", "full_name": "C Four"}
    data = validate_success(api.create_seller(payload, _ADMIN), 201)
    assert_seller(data)
    assert data["payout_method"] == "ACH"


def test_system_fields_generated_on_property_create(api):
    """PRD §3.1: "the platform immediately computes the property's automated
    valuation, `avm_value`"
    PRD §3.1: "A newly registered property opens in `VALUED` status."

    Design: Corner/entities/system_fields_generated_on_property_create
    """
    seller = create_seller()
    payload = create_property_payload(
        seller["id"], comp_median_value=500000, market_trend_pct=0.02
    )
    data = validate_success(api.create_property(payload, _ANALYST), 201)
    assert data["status"] == "VALUED"
    assert data["avm_value"] == 510000.00, data["avm_value"]


def test_service_fee_and_preliminary_proceeds_at_issuance(api):
    """PRD §3.2: "The `service_fee` is the snapshot multiplied by `service_fee_pct`,
    rounded half-up to two decimal places."
    PRD §3.2: "The provisional seller concession, `estimated_concession`, is the
    snapshot multiplied by one percent, rounded half-up to two decimal places."
    PRD §3.2: "The offer's provisional payout, `preliminary_net_proceeds`, is then
    the snapshot minus the `service_fee` minus the `estimated_concession`, rounded
    half-up to two decimal places"

    Design: Corner/calculations/service_fee_and_preliminary_proceeds_at_issuance
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(
        seller["id"], comp_median_value=500000, market_trend_pct=0.02
    )
    data = validate_success(
        api.issue_offer(prop["id"], issue_offer_payload(service_fee_pct=0.05), _ANALYST),
        201,
    )
    assert_offer(data)
    assert data["avm_value_snapshot"] == 510000.00, data["avm_value_snapshot"]
    assert data["service_fee"] == 25500.00, data["service_fee"]
    assert data["estimated_concession"] == 5100.00, data["estimated_concession"]
    assert data["preliminary_net_proceeds"] == 479400.00, data["preliminary_net_proceeds"]


def test_offer_preliminary_proceeds_provisional_value(api):
    """PRD §3.2: "The offer's provisional payout, `preliminary_net_proceeds`, is then
    the snapshot minus the `service_fee` minus the `estimated_concession`, rounded
    half-up to two decimal places; at issuance there is no assessment, so any repair
    credit is treated as zero and no lease-back is contemplated."

    Design: Difficulty/dual_variant_calc/net_proceeds_provisional_vs_final_diverge_on_transaction
    """
    seller, prop, offer = setup_property_under_offer(offer_overrides={"service_fee_pct": 0.05})
    assert offer["preliminary_net_proceeds"] == 479400.00, offer["preliminary_net_proceeds"]
    assert offer["avm_value_snapshot"] == 510000.00, offer["avm_value_snapshot"]


def test_property_below_min_value_floor_rejected(api):
    """PRD §3.2: "only when the property's `avm_value` is at least the minimum
    offerable value of 50,000 dollars; a property valued below that floor is
    rejected with `ERR_PROPERTY_BELOW_MIN_VALUE`."

    Design: Difficulty/boundary_precision_check/property_below_min_value_empty_offerable_floor
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(
        seller["id"], comp_median_value=48000, market_trend_pct=0
    )
    assert prop["avm_value"] == 48000.00, prop["avm_value"]
    validate_error(
        api.issue_offer(prop["id"], issue_offer_payload(service_fee_pct=0.05), _ANALYST),
        ApiErrorId.ERR_PROPERTY_BELOW_MIN_VALUE,
    )
    # Property remains VALUED after a rejected issuance.
    after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert after["status"] == "VALUED"


def test_property_below_min_value_property_stays_valued(api):
    """PRD §3.2: "On a successful first issuance the property transitions
    `VALUED → UNDER_OFFER`"
    PRD §3.2: "a property valued below that floor is rejected with
    `ERR_PROPERTY_BELOW_MIN_VALUE`."

    Design: Difficulty/boundary_precision_check/property_below_min_value_empty_offerable_floor
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(seller["id"], comp_median_value=48000, market_trend_pct=0)
    validate_error(
        api.issue_offer(prop["id"], issue_offer_payload(), _ANALYST),
        ApiErrorId.ERR_PROPERTY_BELOW_MIN_VALUE,
    )
    after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert after["status"] == "VALUED", after["status"]
    assert after["active_offer_id"] is None
