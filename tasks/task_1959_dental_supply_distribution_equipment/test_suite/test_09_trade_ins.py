"""Trade-ins: dual-variant appraisal, terminal lockdown, one-credit-per-sale guards."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_practice,
    create_product,
    create_trade_in_payload,
    create_equipment_sale_payload,
    setup_confirmed_sale,
    create_accepted_trade_in,
    make_practice_manager_headers,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def test_trade_in_appraise_twice_rejected(api):
    """PRD §3.6: "Appraisal is the `SalesRep`'s call, moving `REQUESTED` → `APPRAISED` by
    choosing a `valuation_method`." — appraisal is undefined from APPRAISED.
    PRD §2.8: "the requested transition must exist from the resource's current state,
    terminal states reject every transition, and violations yield `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/trade_in_appraise_twice_rejected
    """
    practice = create_practice(name="P TI", credit_limit_cents=1000000)
    trade_in = validate_success(
        api.create_trade_in(
            create_trade_in_payload(
                practice["id"], description="compressor", equipment_age_months=24,
                condition="NEEDS_REPAIR", category_base_value_cents=500000,
            ),
            SALES,
        ),
        201,
    )
    appraised = validate_success(
        api.appraise_trade_in(trade_in["id"], {"valuation_method": "MARKET_VALUE"}, SALES), 200
    )
    # round_half_up(500000 x 0.98^24 x 0.6) == 184734
    assert appraised["appraised_value_cents"] == 184734

    res = api.appraise_trade_in(trade_in["id"], {"valuation_method": "SCRAP_VALUE"}, SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_trade_in(trade_in["id"], ADMIN), 200)
    assert after["valuation_method"] == "MARKET_VALUE"
    assert after["appraised_value_cents"] == 184734, "Rejected re-appraisal changes nothing"


def test_trade_in_market_vs_scrap_divergence(api):
    """PRD §3.6: "Under `MARKET_VALUE`, the unit depreciates exponentially with age and is
    then graded by condition: multiply `category_base_value_cents` by 0.98 raised to the
    power of `equipment_age_months` (two percent monthly depreciation), multiply by the
    condition factor — 1.0 for `WORKING`, 0.6 for `NEEDS_REPAIR`, 0.2 for `SCRAP` — and
    round half up to whole cents" and "Under `SCRAP_VALUE`, age and base value are ignored
    entirely and a flat salvage table applies: 25,000 cents for `WORKING`, 10,000 cents for
    `NEEDS_REPAIR`, 4,000 cents for `SCRAP`."

    Design: Difficulty/dual_variant_calc/trade_in_market_vs_scrap_divergence
    """
    practice = create_practice(name="P Trade", region="R9", credit_limit_cents=1000000)
    ti1 = validate_success(
        api.create_trade_in(
            create_trade_in_payload(practice["id"], description="autoclave"), SALES
        ),
        201,
    )
    ti2 = validate_success(
        api.create_trade_in(
            create_trade_in_payload(practice["id"], description="autoclave twin"), SALES
        ),
        201,
    )
    mv = validate_success(
        api.appraise_trade_in(ti1["id"], {"valuation_method": "MARKET_VALUE"}, SALES), 200
    )
    sv = validate_success(
        api.appraise_trade_in(ti2["id"], {"valuation_method": "SCRAP_VALUE"}, SALES), 200
    )
    # Identical inputs: base 1000000, age 12, WORKING.
    assert mv["appraised_value_cents"] == 784717, "round_half_up(1000000 x 0.98^12 x 1.0)"
    assert sv["appraised_value_cents"] == 25000, "Flat salvage table for WORKING"
    assert mv["appraised_value_cents"] != sv["appraised_value_cents"]


def test_trade_in_market_vs_scrap_divergence_second_inputs(api):
    """PRD §3.6: "multiply by the condition factor — 1.0 for `WORKING`, 0.6 for
    `NEEDS_REPAIR`, 0.2 for `SCRAP`" and "Under `SCRAP_VALUE`, age and base value are
    ignored entirely and a flat salvage table applies: 25,000 cents for `WORKING`, 10,000
    cents for `NEEDS_REPAIR`, 4,000 cents for `SCRAP`."

    Design: Difficulty/dual_variant_calc/trade_in_market_vs_scrap_divergence
    """
    practice = create_practice(name="P Trade2", credit_limit_cents=1000000)
    ti1 = validate_success(
        api.create_trade_in(
            create_trade_in_payload(
                practice["id"], description="chair", equipment_age_months=24,
                condition="NEEDS_REPAIR", category_base_value_cents=500000,
            ),
            SALES,
        ),
        201,
    )
    ti2 = validate_success(
        api.create_trade_in(
            create_trade_in_payload(
                practice["id"], description="chair twin", equipment_age_months=24,
                condition="NEEDS_REPAIR", category_base_value_cents=500000,
            ),
            SALES,
        ),
        201,
    )
    mv = validate_success(
        api.appraise_trade_in(ti1["id"], {"valuation_method": "MARKET_VALUE"}, SALES), 200
    )
    sv = validate_success(
        api.appraise_trade_in(ti2["id"], {"valuation_method": "SCRAP_VALUE"}, SALES), 200
    )
    assert mv["appraised_value_cents"] == 184734, "round_half_up(500000 x 0.98^24 x 0.6)"
    assert sv["appraised_value_cents"] == 10000, "Flat salvage table for NEEDS_REPAIR"


def test_trade_in_market_value_floor_applies(api):
    """PRD §3.6: "a floor then applies, so the appraised value is the greater of that
    rounded figure and ten percent of the category base value, itself rounded half up to
    whole cents."

    Design: Corner/calculations/trade_in_market_value_floor_applies
    """
    practice = create_practice(name="P Fl", credit_limit_cents=1000000)
    trade_in = validate_success(
        api.create_trade_in(
            create_trade_in_payload(
                practice["id"], description="ancient drill", equipment_age_months=600,
                condition="WORKING", category_base_value_cents=100000,
            ),
            SALES,
        ),
        201,
    )
    appraised = validate_success(
        api.appraise_trade_in(trade_in["id"], {"valuation_method": "MARKET_VALUE"}, SALES), 200
    )
    # raw = 100000 x 0.98^600 x 1.0 ~= 0.54 cents; the 10% floor (10000) binds.
    assert appraised["appraised_value_cents"] == 10000


def test_second_trade_in_on_same_sale_rejected(api):
    """PRD §3.6: "the sale must not already carry a trade-in (at most one per sale), else
    `ERR_TRADE_IN_ALREADY_APPLIED`" and "Applying stamps the sale's `trade_in_id` and
    `trade_in_credit_cents` with the trade-in and its appraised value".

    Design: Corner/validations/second_trade_in_on_same_sale_rejected
    """
    practice = create_practice(name="P Ta", credit_limit_cents=10000000)
    product = create_product(sku="EQ-19", kind="EQUIPMENT", unit_price_cents=500000,
                             warranty_months=12)
    sale = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"]), SALES
        ),
        201,
    )
    validate_success(api.confirm_equipment_sale(sale["id"], SALES), 200)

    ti1 = create_accepted_trade_in(practice["id"], description="old chair 1",
                                   equipment_age_months=60, category_base_value_cents=100000)
    ti2 = create_accepted_trade_in(practice["id"], description="old chair 2",
                                   equipment_age_months=60, category_base_value_cents=100000)
    applied = validate_success(
        api.apply_trade_in_to_sale(ti1["id"], {"equipment_sale_id": sale["id"]}, SALES), 200
    )
    assert applied["status"] == "CREDITED"

    res = api.apply_trade_in_to_sale(ti2["id"], {"equipment_sale_id": sale["id"]}, SALES)
    validate_error(res, ApiErrorId.ERR_TRADE_IN_ALREADY_APPLIED)

    ti2_after = validate_success(api.get_trade_in(ti2["id"], ADMIN), 200)
    assert ti2_after["status"] == "ACCEPTED"
    sale_after = validate_success(api.get_equipment_sale(sale["id"], ADMIN), 200)
    assert sale_after["trade_in_id"] == ti1["id"]
    assert sale_after["trade_in_credit_cents"] == 25000


def test_trade_in_credit_exceeds_sale_price(api):
    """PRD §3.6: "the `appraised_value_cents` must not exceed the sale's
    `sale_price_cents`, else `ERR_TRADE_IN_CREDIT_EXCEEDS_PRICE`".

    Design: Corner/validations/trade_in_credit_exceeds_sale_price
    """
    practice = create_practice(name="P Tc", credit_limit_cents=10000000)
    product = create_product(sku="EQ-20", name="Stool", kind="EQUIPMENT",
                             unit_price_cents=50000, warranty_months=6)
    sale = validate_success(
        api.create_equipment_sale(
            create_equipment_sale_payload(practice["id"], product["id"],
                                          sale_price_cents=20000),
            SALES,
        ),
        201,
    )
    validate_success(api.confirm_equipment_sale(sale["id"], SALES), 200)
    trade_in = create_accepted_trade_in(
        practice["id"], description="old stool", equipment_age_months=30,
        category_base_value_cents=80000,
    )
    assert trade_in["appraised_value_cents"] == 25000, "SCRAP_VALUE for WORKING"

    res = api.apply_trade_in_to_sale(trade_in["id"], {"equipment_sale_id": sale["id"]}, SALES)
    validate_error(res, ApiErrorId.ERR_TRADE_IN_CREDIT_EXCEEDS_PRICE)
    after = validate_success(api.get_trade_in(trade_in["id"], ADMIN), 200)
    assert after["status"] == "ACCEPTED"
