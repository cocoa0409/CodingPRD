"""Numeric and cardinality boundaries: the travel-surcharge mid-tier threshold (>= inclusive)
and the empty-quote (zero line items) send boundary. Translates Difficulty rule
boundary_precision_check.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_customer_payload, create_route_payload, create_property_payload,
    create_quote_payload, create_line_item_payload,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]


def _draft_quote(api, stories=1, **prop_kwargs):
    cust = validate_success(api.create_customer(create_customer_payload(email=f"b{id(prop_kwargs)}@x.com"), DISP), 201)
    route = validate_success(api.create_route(create_route_payload(name="BZ"), DISP), 201)
    prop = validate_success(
        api.create_property(create_property_payload(cust["id"], route["id"], stories=stories, **prop_kwargs), DISP), 201)
    quote = validate_success(api.create_quote(create_quote_payload(prop["id"], prop["version"]), DISP), 201)
    return quote


def test_travel_surcharge_mid_tier_boundary_is_inclusive(api):
    """PRD §3.2: "Otherwise, if `subtotal_cents` is at least 1,500,000 cents (fifteen
    thousand dollars), the surcharge is half of the flat travel charge, that is, 7,500 cents
    divided by two."
    PRD §3.2: "Note that a subtotal of exactly 1,500,000 cents falls in the half-travel
    branch, not the full-travel branch, because the comparison is "at least"."

    Design: Difficulty/boundary_precision_check/travel_surcharge_mid_tier_boundary_ge_inclusive
    """
    quote = _draft_quote(api, stories=1, siding_sqft=100000)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("SIDING", "HOUSE_WASH", 100000), DISP), 201)
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    # 100000 * 15 * 1.0 * 1.0 = 1,500,000 == MID -> half of 7500 = 3750.
    assert sent["subtotal_cents"] == 1500000, sent["subtotal_cents"]
    assert sent["travel_surcharge_cents"] == 3750, sent["travel_surcharge_cents"]
    assert sent["total_cents"] == 1503750, sent["total_cents"]


def test_travel_surcharge_just_below_mid_tier_pays_full(api):
    """PRD §3.2: "Otherwise the surcharge is the full flat travel charge of 7,500 cents
    (seventy-five dollars)."

    Design: Difficulty/boundary_precision_check/travel_surcharge_mid_tier_boundary_ge_inclusive
    """
    # 99999 sqft SIDING/HOUSE_WASH 1-story => 99999*15 = 1,499,985 < 1,500,000 -> full 7500.
    quote = _draft_quote(api, stories=1, siding_sqft=100000)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("SIDING", "HOUSE_WASH", 99999), DISP), 201)
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    assert sent["subtotal_cents"] == 1499985, sent["subtotal_cents"]
    assert sent["travel_surcharge_cents"] == 7500, sent["travel_surcharge_cents"]


def test_send_empty_quote_rejected(api):
    """PRD §3.2: "A quote may be sent only when it holds at least one line item. Sending a
    quote that has an empty line-item set is rejected with `ERR_QUOTE_EMPTY`."

    Design: Difficulty/boundary_precision_check/send_empty_quote_zero_line_items_rejected
    """
    quote = _draft_quote(api, stories=1)
    resp = api.send_quote(quote["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_QUOTE_EMPTY.value)


def test_send_quote_with_one_line_item_succeeds(api):
    """PRD §3.2: "A quote may be sent only when it holds at least one line item."

    Design: Difficulty/boundary_precision_check/send_empty_quote_zero_line_items_rejected
    """
    quote = _draft_quote(api, stories=1, siding_sqft=500)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("SIDING", "HOUSE_WASH", 500), DISP), 201)
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    assert sent["status"] == "SENT", sent["status"]
