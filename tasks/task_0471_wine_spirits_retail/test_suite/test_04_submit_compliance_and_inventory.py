"""Submit-time business gates: age/blocked/growler/ship/allocation/ABC/inventory,
priority ordering, boundary precision, single-lot reservation, cross-entity preconditions,
and the customer compliance-scoring domain.

Covers difficulty queues priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, and dual_variant_calc
instance 2; plus corner queue validations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, fixtures as fx,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Difficulty: dual_variant_calc instance 2 (customer scoring domain) ──────
def test_customer_compliance_score_blocks_on_unverified_plus_rejected(api):
    """PRD §3.2: "start at zero; add 2 if the customer is not age-verified; add 1 for each `REJECTED` ID scan on file for the customer ... A final score of exactly 0 yields `CLEAR`; a score of 1 or 2 yields `WATCH`; a score greater than 2 yields `BLOCKED`."

    Design: Difficulty/dual_variant_calc/customer_compliance_score_vs_order_cost_independent_domains
    """
    fx.set_clock()
    cust = fx.register_customer("dv2@x.com", ship_state_code="CA")
    scan = fx.create_pending_scan(cust, id_expiry_date="2018-01-01")  # expired
    get_success_data(api_client.reject_id_scan(scan["id"], {"reject_reason": "EXPIRED"}, ASSOCIATE))

    customer = get_success_data(api_client.get_customer(cust["id"], COMPLIANCE))
    assert customer["compliance_status"] == "BLOCKED", \
        f"score 2 (unverified) + 1 (rejected) = 3 => BLOCKED, got {customer['compliance_status']}"
    assert customer["age_verified"] is False


# ─── Difficulty: priority_pair_validation_conflict ──────────────────────────
def test_age_not_verified_beats_insufficient_inventory(api):
    """PRD §2.10: "order submission runs its business checks in this pinned order: age verification (`ERR_AGE_NOT_VERIFIED`), then customer-blocked status (`ERR_CUSTOMER_BLOCKED`), then the growler/keg state ban (`ERR_GROWLER_KEG_STATE_BANNED`), then ship-state restriction (`ERR_SHIP_STATE_RESTRICTED`), then allocation cap (`ERR_ALLOCATION_LIMIT_EXCEEDED`), then the ABC monthly volume cap (`ERR_ABC_MONTHLY_LIMIT_EXCEEDED`), then single-lot inventory sufficiency (`ERR_INSUFFICIENT_INVENTORY`)."

    Design: Difficulty/priority_pair_validation_conflict/age_not_verified_beats_insufficient_inventory_on_submit
    """
    fx.set_clock()
    cust = fx.register_customer("pp1@x.com", ship_state_code="CA")  # NOT age-verified
    _, vint, _ = fx.setup_released_vintage("PP-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=1, vintage_year=2020)  # insufficient for qty 5

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 5)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_AGE_NOT_VERIFIED.value)


def test_ship_state_restricted_beats_abc_monthly_limit(api):
    """PRD §2.10: "then the growler/keg state ban (`ERR_GROWLER_KEG_STATE_BANNED`), then ship-state restriction (`ERR_SHIP_STATE_RESTRICTED`), then allocation cap (`ERR_ALLOCATION_LIMIT_EXCEEDED`), then the ABC monthly volume cap (`ERR_ABC_MONTHLY_LIMIT_EXCEEDED`)"

    Design: Difficulty/priority_pair_validation_conflict/ship_state_restricted_beats_abc_monthly_limit_referential_vs_constraint
    """
    fx.set_clock()
    fx.create_state_rule("NV", ship_allowed=False, growler_keg_allowed=True,
                         monthly_volume_limit_ml=100, requires_adult_signature=False)
    cust = fx.create_verified_customer("pp2@x.com", ship_state_code="NV")
    _, vint, _ = fx.setup_released_vintage("PP-2", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)

    order = fx.create_cart_order(cust, channel="SHIP", dest_state_code="NV")
    fx.add_line(cust, order["id"], vint["id"], 4)  # 3000ml > 100ml cap
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIP_STATE_RESTRICTED.value)


# ─── Difficulty: boundary_precision_check ───────────────────────────────────
def test_abc_monthly_volume_exactly_at_limit_allowed(api):
    """PRD §3.5: "The order is rejected with `ERR_ABC_MONTHLY_LIMIT_EXCEEDED` (HTTP 422) when that already-used volume plus this order's volume would be strictly greater than the destination state's `monthly_volume_limit_ml`; exactly reaching the limit is allowed."
    PRD §3.2: "add 3 if there exists any active compliance-window row whose running monthly used volume for its state and month is within 750 milliliters of that state's monthly cap ... a score greater than 2 yields `BLOCKED`."

    Design: Difficulty/boundary_precision_check/abc_monthly_volume_at_limit_allowed_strict_greater_than
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         monthly_volume_limit_ml=9000, requires_adult_signature=False)
    cust = fx.create_verified_customer("bp1@x.com", ship_state_code="TX")
    _, vint, _ = fx.setup_released_vintage("BP-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2020)

    order = fx.create_cart_order(cust, channel="SHIP", dest_state_code="TX")
    fx.add_line(cust, order["id"], vint["id"], 12)  # 750*12 = 9000 == cap
    submitted = fx.submit_order(cust, order["id"])
    assert submitted["fulfillment_status"] == "SUBMITTED", \
        f"order exactly at the 9000ml cap should submit, got {submitted['fulfillment_status']}"

    customer = get_success_data(api_client.get_customer(cust["id"], COMPLIANCE))
    assert customer["compliance_status"] == "BLOCKED", \
        f"at-cap window within 750ml grace => +3 => BLOCKED, got {customer['compliance_status']}"


def test_submit_empty_order_returns_empty_order_error(api):
    """PRD §3.3: "Submission is permitted only when the order is in `CART`, has at least one order line (an empty cart is rejected with `ERR_EMPTY_ORDER`)"

    Design: Difficulty/boundary_precision_check/submit_empty_order_zero_lines_returns_empty_order
    """
    fx.set_clock()
    cust = fx.create_verified_customer("bp2@x.com", ship_state_code="CA")
    order = fx.create_cart_order(cust, channel="POS")
    ver = fx.current_order_version(cust, order["id"])

    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


# ─── Difficulty: cross_entity_state_dependency ──────────────────────────────
def test_submit_requires_customer_age_verified(api):
    """PRD §3.4: "The acting customer's `age_verified` flag must be true — meaning a non-expired `VERIFIED` ID scan whose scanned date of birth proves an age of at least 21 is on file — or the submit is rejected with `ERR_AGE_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_customer_age_verified_order_to_customer
    """
    fx.set_clock()
    cust = fx.register_customer("ce1@x.com", ship_state_code="CA")
    fx.create_pending_scan(cust)  # scan stays PENDING, never verified
    _, vint, _ = fx.setup_released_vintage("CE-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=5, vintage_year=2020)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 2)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_AGE_NOT_VERIFIED.value)


def test_vintage_release_requires_inventory_stock(api):
    """PRD §3.1: "An `Admin` releases a non-allocated vintage, advancing `DRAFT → RELEASED`; this requires the vintage to be in `DRAFT`, its parent product to be non-allocated, and at least one inventory lot for the vintage to hold `qty_on_hand` of at least 1 — failing the stock requirement (or being called on an allocated product) yields `ERR_RELEASE_REQUIRES_STOCK`."

    Design: Difficulty/cross_entity_state_dependency/vintage_release_requires_inventory_lot_stock_vintage_to_lot
    """
    product = fx.create_product("CE-2", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2021, list_price_cents=3000, case_pack_size=6)

    resp = api_client.release_vintage(vint["id"], ADMIN)  # no lot exists
    validate_error(resp, ApiErrorId.ERR_RELEASE_REQUIRES_STOCK.value)


# ─── Difficulty: resource_temporal_overlap ──────────────────────────────────
def test_single_lot_no_split_insufficient_inventory(api):
    """PRD §3.5: "inventory sufficiency is checked last among the business rules: for each line there must be a single inventory lot of the vintage whose available units (`qty_on_hand` minus `qty_reserved`) are at least the line's `qty`; if no single lot can cover the line — splitting across lots is not allowed — the submit is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/single_lot_no_split_reservation_overlap_per_lot_capacity
    """
    fx.set_clock()
    cust = fx.create_verified_customer("rt1@x.com", ship_state_code="CA")
    product = fx.create_product("RT-1", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2020, list_price_cents=3000, case_pack_size=6)
    fx.create_lot(vint["id"], tax_status="TAXED", qty_on_hand=3)
    fx.create_lot(vint["id"], tax_status="TAXED", qty_on_hand=3)  # two lots of 3, none covers 4
    get_success_data(api_client.release_vintage(vint["id"], ADMIN))

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 4)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_allocation_cap_cumulative_across_orders(api):
    """PRD §3.5: "For each line whose parent product is allocation-controlled, the customer's existing committed-or-fulfilled units of that vintage plus the line's `qty` must not exceed the vintage's `allocation_cap_per_customer`; exceeding the cap rejects the submit with `ERR_ALLOCATION_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/allocation_cap_per_customer_cumulative_overlap_across_orders
    """
    fx.set_clock()
    cust = fx.create_verified_customer("rt2@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_allocation_open_vintage("RT-2", allocation_cap_per_customer=2,
                                                  list_price_cents=12000, case_pack_size=6,
                                                  qty_on_hand=10, vintage_year=2017)

    # First order commits qty 1 (1 of 2 used).
    fx.build_submitted_order(cust, vint["id"], 1, channel="POS")
    # Second order qty 2 -> cumulative 3 > cap 2.
    order2 = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order2["id"], vint["id"], 2)
    ver = fx.current_order_version(cust, order2["id"])
    resp = api_client.submit_order(order2["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_LIMIT_EXCEEDED.value)


# ─── Corner: validations ────────────────────────────────────────────────────
def test_growler_keg_state_banned_on_ship(api):
    """PRD §3.4: "For a `DELIVERY` or `SHIP` order, if any line's parent product is in the `GROWLER` or `KEG` category, the destination state's rule must have `growler_keg_allowed` true, or the submit is rejected with `ERR_GROWLER_KEG_STATE_BANNED` (HTTP 422)."

    Design: Corner/validations/growler_keg_state_banned_on_ship
    """
    fx.set_clock()
    fx.create_state_rule("UT", ship_allowed=True, growler_keg_allowed=False,
                         requires_adult_signature=False)
    cust = fx.create_verified_customer("gb1@x.com", ship_state_code="UT")
    _, vg, _ = fx.setup_released_vintage("GB-G", category="GROWLER",
                                         container_type="GROWLER_FILL", bottle_volume_ml=1900,
                                         abv_pct=5.00, list_price_cents=1500, case_pack_size=1,
                                         qty_on_hand=10, vintage_year=2026)

    order = fx.create_cart_order(cust, channel="SHIP", dest_state_code="UT")
    fx.add_line(cust, order["id"], vg["id"], 1)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_GROWLER_KEG_STATE_BANNED.value)


def test_submit_draft_vintage_not_purchasable(api):
    """PRD §3.3: "For every line, the parent vintage must be in `RELEASED` or `ALLOCATION_OPEN` status, or the submit is rejected with `ERR_VINTAGE_NOT_PURCHASABLE`."

    Design: Corner/validations/vintage_not_purchasable_draft_status_on_submit
    """
    fx.set_clock()
    cust = fx.create_verified_customer("np1@x.com", ship_state_code="CA")
    product = fx.create_product("NP-1", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2020, list_price_cents=3000, case_pack_size=6)
    fx.create_lot(vint["id"], tax_status="TAXED", qty_on_hand=5)  # lot exists, but never released

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 1)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_VINTAGE_NOT_PURCHASABLE.value)


def test_add_order_line_qty_zero_invalid_request(api):
    """PRD §2.10: "Field-level validity checks — legal enum values, quantities of at least 1, alcohol-by-volume within range, two-letter state codes, and the uniqueness constraints ... surface as `ERR_INVALID_REQUEST` (HTTP 400)"
    PRD §3.3: "A line is added to a `CART` order with the `vintage_id` being purchased and a `qty` of at least 1"

    Design: Corner/validations/ship_order_qty_below_one_returns_invalid_request
    """
    cust = fx.register_customer("q0@x.com", ship_state_code="CA")
    product = fx.create_product("Q0-1", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2020, list_price_cents=3000, case_pack_size=6)
    order = fx.create_cart_order(cust, channel="POS")

    resp = api_client.add_line(order["id"], {"vintage_id": vint["id"], "qty": 0},
                               make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
