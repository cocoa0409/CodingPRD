"""Second tests for every difficulty-design instance.

Each test below targets the SAME difficulty instance as its counterpart in files
01-04 but asserts a different observable that the instance's PRD rule still
uniquely determines (a distinct side effect, the boundary's other side, or the
priority ladder with the higher-priority failure removed). Together with files
01-04 this gives every difficulty instance >= 2 tagged tests.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, fixtures as fx,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── dual_variant_calc ──────────────────────────────────────────────────────
def test_bonded_line_excise_recorded_on_capture(api):
    """PRD §3.7: "it sets the line's `line_excise_cents` to the line's `qty` times the bonded lot's `excise_band_cents_per_unit`"

    Design: Difficulty/dual_variant_calc/provisional_vs_settled_total_diverge_on_bonded_line
    """
    fx.set_clock()
    cust = fx.create_verified_customer("dv1b@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage(
        "DV-W-1B", category="WINE", abv_pct=13.50, list_price_cents=5000, case_pack_size=6,
        tax_status="BONDED", qty_on_hand=6, excise_band_cents_per_unit=80, vintage_year=2019)

    order = fx.build_submitted_order(cust, vint["id"], 6, channel="POS")
    fx.authorize(cust, order["id"])
    fx.capture(order["id"])

    data = validate_success(api_client.list_order_lines(order["id"], make_customer_headers(cust["id"])))
    assert len(data) == 1
    assert data[0]["line_excise_cents"] == 480, \
        f"line_excise should be 6*80=480, got {data[0]['line_excise_cents']}"


def test_compliance_score_exactly_two_is_watch_not_blocked(api):
    """PRD §3.2: "add 2 if the customer is not age-verified ... a score of 1 or 2 yields `WATCH`; a score greater than 2 yields `BLOCKED`. The boundary is pinned: a score of exactly 2 is `WATCH`, not `BLOCKED`, and a `WATCH` customer may still submit orders"

    Design: Difficulty/dual_variant_calc/customer_compliance_score_vs_order_cost_independent_domains
    """
    fx.set_clock()
    cust = fx.register_customer("dv2b@x.com", ship_state_code="CA")  # unverified only: score 2
    customer = get_success_data(api_client.get_customer(cust["id"], COMPLIANCE))
    assert customer["compliance_status"] == "WATCH", \
        f"score 2 (unverified, no rejected scan) => WATCH, got {customer['compliance_status']}"


# ─── combinatorial_formula ──────────────────────────────────────────────────
def test_mixed_units_below_twelve_earn_no_discount(api):
    """PRD §3.6: "Mixed-case units earn the mixed-case rate of ten percent only when the total discountable unit count is at least 12; otherwise mixed-case units earn nothing."
    PRD §3.6: "when the total discountable unit count is below 12, the mixed-case units earn zero and only any full-case units earn fifteen percent."

    Design: Difficulty/combinatorial_formula/case_discount_mixed_and_full_three_input_nonlinear
    """
    fx.set_clock()
    cust = fx.create_verified_customer("cf1b@x.com", ship_state_code="CA")
    # Single line qty 5, pack 6 -> 0 full-case units, 5 mixed units, total 5 < 12 -> discount 0.
    _, vint, _ = fx.setup_released_vintage("CF-A-B", list_price_cents=2000, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2022, abv_pct=13.00)
    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 5)
    submitted = fx.submit_order(cust, order["id"])
    assert submitted["discount_cents"] == 0, \
        f"5 mixed units below the 12-unit tier earn no discount, got {submitted['discount_cents']}"


def test_full_case_only_discount_is_full_value_times_rate(api):
    """PRD §3.6: "when every discountable line's `qty` is an exact multiple of its `case_pack_size`, the mixed-case value is zero and the discount is simply the full-case value times fifteen percent rounded half up"

    Design: Difficulty/combinatorial_formula/case_discount_rounding_per_component_then_sum_order_pinned
    """
    fx.set_clock()
    cust = fx.create_verified_customer("cf2b@x.com", ship_state_code="CA")
    # qty 6, pack 6, price 85 -> full_value 510 -> 510*0.15=76.5 -> round half up 77, mixed 0.
    _, vint, _ = fx.setup_released_vintage("CF-RA-B", list_price_cents=85, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2023, abv_pct=13.00)
    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 6)
    submitted = fx.submit_order(cust, order["id"])
    assert submitted["discount_cents"] == 77, \
        f"full-case-only discount round_half_up(510*0.15)=77, got {submitted['discount_cents']}"


# ─── non_linear_state_machine ───────────────────────────────────────────────
def test_authorize_leaves_fulfillment_submitted(api):
    """PRD §3.7: "A `Customer` or `StoreAssociate` authorizes payment, advancing `payment_status` `UNPAID → AUTHORIZED`; this requires the order to be `UNPAID` on the payment dimension and `SUBMITTED` on the fulfillment dimension"

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions_evolve_independently
    """
    fx.set_clock()
    cust = fx.create_verified_customer("nl1b@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("NL-1B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    order = fx.build_submitted_order(cust, vint["id"], 2, channel="POS")
    authed = fx.authorize(cust, order["id"])

    assert authed["payment_status"] == "AUTHORIZED"
    assert authed["fulfillment_status"] == "SUBMITTED", \
        f"fulfillment stays SUBMITTED while payment advances, got {authed['fulfillment_status']}"


def test_counter_increments_round_count_and_records_counter_price(api):
    """PRD §3.9: "The `Customer` may counter a quote, advancing `QUOTED → COUNTERED`, setting `customer_counter_price_cents` from the request body and incrementing `round_count` by one."

    Design: Difficulty/non_linear_state_machine/special_order_cyclic_quote_counter_revision_loop
    """
    fx.set_clock()
    cust = fx.register_customer("nl2b@x.com", ship_state_code="CA")
    cust_h = make_customer_headers(cust["id"])
    so = fx.create_special_order(cust, description="rare", requested_qty=1)
    get_success_data(api_client.quote_special_order(so["id"], {"quoted_unit_price_cents": 9000}, ASSOCIATE))

    countered = validate_success(api_client.counter_special_order(
        so["id"], {"customer_counter_price_cents": 7000}, cust_h))
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 1, f"round_count should be 1, got {countered['round_count']}"
    assert countered["customer_counter_price_cents"] == 7000


# ─── transitive_cascade ─────────────────────────────────────────────────────
def test_capture_repoints_line_to_taxed_lot(api):
    """PRD §3.7: "it mints or appends a `TAXED` inventory lot for the same vintage and increases that taxed lot's `qty_on_hand` by the line's `qty`; and it repoints the line's `lot_id` to the taxed lot."

    Design: Difficulty/transitive_cascade/capture_bonded_withdrawal_line_to_bonded_lot_to_taxed_lot_depth3
    """
    fx.set_clock()
    cust = fx.create_verified_customer("tc1b@x.com", ship_state_code="CA")
    _, vint, blot = fx.setup_released_vintage(
        "TC-1B", category="SPIRITS", abv_pct=40.00, list_price_cents=4000, case_pack_size=6,
        tax_status="BONDED", qty_on_hand=4, excise_band_cents_per_unit=60, vintage_year=2018)
    order = fx.build_submitted_order(cust, vint["id"], 4, channel="POS")
    fx.authorize(cust, order["id"])
    fx.capture(order["id"])

    data = validate_success(api_client.list_order_lines(order["id"], make_customer_headers(cust["id"])))
    line = data[0]
    assert line["lot_id"] != blot["id"], "line lot_id must be repointed off the bonded lot to the taxed lot"
    taxed = get_success_data(api_client.get_lot(line["lot_id"], ASSOCIATE))
    assert taxed["tax_status"] == "TAXED", f"repointed lot must be TAXED, got {taxed['tax_status']}"
    assert taxed["qty_on_hand"] == 4, f"taxed lot should hold the 4 withdrawn units, got {taxed['qty_on_hand']}"


def test_shipment_return_restores_lot_on_hand_and_units_committed(api):
    """PRD §3.10: "the owning order is cancelled from `READY` via the same compensation as an order cancel — reservations released, lot quantities restored, and the compliance-window row deactivated."
    PRD §3.3: "Next, each affected vintage's `units_committed` is recomputed"

    Design: Difficulty/transitive_cascade/shipment_return_cancels_order_releases_reservation_depth2
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         requires_adult_signature=False)
    cust = fx.create_verified_customer("tc2b@x.com", ship_state_code="TX")
    _, vint, lot = fx.setup_released_vintage("TC-2B", list_price_cents=3000, case_pack_size=6,
                                             qty_on_hand=10, vintage_year=2020)
    order, shipment = fx.build_dispatched_shipment(cust, vint["id"], 3, "TX")
    get_success_data(api_client.return_shipment(shipment["id"], ASSOCIATE))

    lot_after = get_success_data(api_client.get_lot(lot["id"], ASSOCIATE))
    assert lot_after["qty_on_hand"] == 10, f"qty_on_hand should be restored to 10, got {lot_after['qty_on_hand']}"
    vint_after = get_success_data(api_client.get_vintage(vint["id"], ASSOCIATE))
    assert vint_after["units_committed"] == 0, \
        f"units_committed should drop back to 0, got {vint_after['units_committed']}"


# ─── priority_pair_validation_conflict ──────────────────────────────────────
def test_insufficient_inventory_surfaces_when_age_ok(api):
    """PRD §2.10: "age verification (`ERR_AGE_NOT_VERIFIED`) ... then single-lot inventory sufficiency (`ERR_INSUFFICIENT_INVENTORY`)."
    PRD §3.5: "if no single lot can cover the line — splitting across lots is not allowed — the submit is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/age_not_verified_beats_insufficient_inventory_on_submit
    """
    fx.set_clock()
    cust = fx.create_verified_customer("pp1b@x.com", ship_state_code="CA")  # age IS verified now
    _, vint, _ = fx.setup_released_vintage("PP-1B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=1, vintage_year=2020)
    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 5)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_abc_monthly_limit_surfaces_when_ship_allowed(api):
    """PRD §2.10: "then ship-state restriction (`ERR_SHIP_STATE_RESTRICTED`) ... then the ABC monthly volume cap (`ERR_ABC_MONTHLY_LIMIT_EXCEEDED`)"
    PRD §3.5: "The order is rejected with `ERR_ABC_MONTHLY_LIMIT_EXCEEDED` (HTTP 422) when that already-used volume plus this order's volume would be strictly greater than the destination state's `monthly_volume_limit_ml`"

    Design: Difficulty/priority_pair_validation_conflict/ship_state_restricted_beats_abc_monthly_limit_referential_vs_constraint
    """
    fx.set_clock()
    fx.create_state_rule("NV", ship_allowed=True, growler_keg_allowed=True,
                         monthly_volume_limit_ml=100, requires_adult_signature=False)
    cust = fx.create_verified_customer("pp2b@x.com", ship_state_code="NV")
    _, vint, _ = fx.setup_released_vintage("PP-2B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    order = fx.create_cart_order(cust, channel="SHIP", dest_state_code="NV")
    fx.add_line(cust, order["id"], vint["id"], 4)  # 3000ml > 100ml
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_ABC_MONTHLY_LIMIT_EXCEEDED.value)


# ─── boundary_precision_check ───────────────────────────────────────────────
def test_abc_monthly_volume_one_over_limit_rejected(api):
    """PRD §3.5: "The order is rejected with `ERR_ABC_MONTHLY_LIMIT_EXCEEDED` (HTTP 422) when that already-used volume plus this order's volume would be strictly greater than the destination state's `monthly_volume_limit_ml`; exactly reaching the limit is allowed."

    Design: Difficulty/boundary_precision_check/abc_monthly_volume_at_limit_allowed_strict_greater_than
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         monthly_volume_limit_ml=9000, requires_adult_signature=False)
    cust = fx.create_verified_customer("bp1b@x.com", ship_state_code="TX")
    _, vint, _ = fx.setup_released_vintage("BP-1B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2020)
    order = fx.create_cart_order(cust, channel="SHIP", dest_state_code="TX")
    fx.add_line(cust, order["id"], vint["id"], 13)  # 750*13 = 9750 > 9000
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_ABC_MONTHLY_LIMIT_EXCEEDED.value)


def test_single_line_order_submits(api):
    """PRD §3.3: "Submission is permitted only when the order is in `CART`, has at least one order line (an empty cart is rejected with `ERR_EMPTY_ORDER`)"

    Design: Difficulty/boundary_precision_check/submit_empty_order_zero_lines_returns_empty_order
    """
    fx.set_clock()
    cust = fx.create_verified_customer("bp2b@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("BP-2B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 1)  # exactly one line
    submitted = fx.submit_order(cust, order["id"])
    assert submitted["fulfillment_status"] == "SUBMITTED", \
        f"an order with one line should submit, got {submitted['fulfillment_status']}"


# ─── cross_entity_state_dependency ──────────────────────────────────────────
def test_submit_succeeds_after_age_verified(api):
    """PRD §3.2: "On a successful verify, the owning customer's `age_verified` flips to true"
    PRD §3.4: "The acting customer's `age_verified` flag must be true ... or the submit is rejected with `ERR_AGE_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_customer_age_verified_order_to_customer
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ce1b@x.com", ship_state_code="CA")  # now verified
    _, vint, _ = fx.setup_released_vintage("CE-1B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=5, vintage_year=2020)
    submitted = fx.build_submitted_order(cust, vint["id"], 2, channel="POS")
    assert submitted["fulfillment_status"] == "SUBMITTED", \
        f"submit should succeed once age is verified, got {submitted['fulfillment_status']}"


def test_vintage_release_succeeds_with_stocked_lot(api):
    """PRD §3.1: "this requires the vintage to be in `DRAFT`, its parent product to be non-allocated, and at least one inventory lot for the vintage to hold `qty_on_hand` of at least 1"

    Design: Difficulty/cross_entity_state_dependency/vintage_release_requires_inventory_lot_stock_vintage_to_lot
    """
    product = fx.create_product("CE-2B", category="WINE")
    vint = fx.create_vintage(product["id"], vintage_year=2021, list_price_cents=3000, case_pack_size=6)
    fx.create_lot(vint["id"], tax_status="TAXED", qty_on_hand=1)  # one stocked lot
    released = validate_success(api_client.release_vintage(vint["id"], ADMIN))
    assert released["status"] == "RELEASED", f"vintage should release, got {released['status']}"


# ─── resource_temporal_overlap ──────────────────────────────────────────────
def test_single_lot_covering_line_submits(api):
    """PRD §3.5: "for each line there must be a single inventory lot of the vintage whose available units (`qty_on_hand` minus `qty_reserved`) are at least the line's `qty`"

    Design: Difficulty/resource_temporal_overlap/single_lot_no_split_reservation_overlap_per_lot_capacity
    """
    fx.set_clock()
    cust = fx.create_verified_customer("rt1b@x.com", ship_state_code="CA")
    # One lot of qty 4 fully covers a line of qty 4 (no split needed).
    _, vint, _ = fx.setup_released_vintage("RT-1B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=4, vintage_year=2020)
    submitted = fx.build_submitted_order(cust, vint["id"], 4, channel="POS")
    assert submitted["fulfillment_status"] == "SUBMITTED", \
        f"a single covering lot should satisfy the line, got {submitted['fulfillment_status']}"


def test_allocation_cap_exactly_at_limit_allowed(api):
    """PRD §3.5: "the customer's existing committed-or-fulfilled units of that vintage plus the line's `qty` must not exceed the vintage's `allocation_cap_per_customer`; exceeding the cap rejects the submit"

    Design: Difficulty/resource_temporal_overlap/allocation_cap_per_customer_cumulative_overlap_across_orders
    """
    fx.set_clock()
    cust = fx.create_verified_customer("rt2b@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_allocation_open_vintage("RT-2B", allocation_cap_per_customer=2,
                                                  list_price_cents=12000, case_pack_size=6,
                                                  qty_on_hand=10, vintage_year=2017)
    fx.build_submitted_order(cust, vint["id"], 1, channel="POS")  # 1 committed
    # Second order qty 1 -> cumulative 2 == cap 2, allowed (must not EXCEED).
    second = fx.build_submitted_order(cust, vint["id"], 1, channel="POS")
    assert second["fulfillment_status"] == "SUBMITTED", \
        f"cumulative exactly at cap (2==2) should submit, got {second['fulfillment_status']}"


# ─── compensating_invariant ─────────────────────────────────────────────────
def test_cancel_releases_line_reservation_state(api):
    """PRD §3.10: "Cancelling a `SUBMITTED` order ... advances `SUBMITTED → CANCELLED` and runs the compensation cascade: each line's `reservation_state` advances `COMMITTED → RELEASED`"

    Design: Difficulty/compensating_invariant/cancel_restores_lot_available_units_conserved
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ci1b@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("CI-1B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=5, vintage_year=2020)
    order = fx.build_submitted_order(cust, vint["id"], 2, channel="POS")
    get_success_data(api_client.cancel_order(order["id"], make_customer_headers(cust["id"])))

    data = validate_success(api_client.list_order_lines(order["id"], make_customer_headers(cust["id"])))
    assert data[0]["reservation_state"] == "RELEASED", \
        f"line reservation_state should be RELEASED after cancel, got {data[0]['reservation_state']}"


def test_cancel_deactivates_compliance_window(api):
    """PRD §3.5: "When the producing order is later cancelled or refunded, its compliance-window row's `active` flag is flipped to false so that the released volume no longer counts against the month's cap"

    Design: Difficulty/compensating_invariant/cancel_restores_monthly_compliance_volume_conserved
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         monthly_volume_limit_ml=1500, requires_adult_signature=False)
    cust = fx.create_verified_customer("ci2b@x.com", ship_state_code="TX")
    _, vint, _ = fx.setup_released_vintage("CI-2B", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2020)
    order = fx.build_submitted_order(cust, vint["id"], 2, channel="SHIP", dest_state_code="TX")
    get_success_data(api_client.cancel_order(order["id"], make_customer_headers(cust["id"])))

    data = validate_success(api_client.list_order_compliance_windows(order["id"], COMPLIANCE))
    assert len(data) >= 1, "the SHIP submit should have written a compliance-window row"
    assert all(row["active"] is False for row in data), \
        "the order's compliance-window row(s) must be deactivated after cancel"
