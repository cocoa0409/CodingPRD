"""Ticket pricing, reduced-fare discount, the fare cap, and revenue apportionment."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_passenger_headers,
    allocation_for_code, sum_allocations,
)
from test_helpers import fixtures as fx


# ==========================================================================
# dual_variant_calc / apportionment_zone_count_vs_distance_diverge_revenue_domain
# ==========================================================================

def test_apportionment_distance_variant_splits_by_zone_miles(api):
    """PRD 3.3: "under `DISTANCE` the weight is the sum of their zone-mile values, where
    zone 1 is 10 miles, zone 2 is 20, zone 3 is 30, zone 4 is 40, zone 5 is 50, and zone 6
    is 60."
    PRD 3.3: "Each participating agency's raw share is the total purchase price multiplied
    by its weight and divided by the sum of all participating weights, computed as an exact
    ratio and then floored to whole cents."

    Design: Difficulty/dual_variant_calc/apportionment_zone_count_vs_distance_diverge_revenue_domain
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp = fx.create_fare_product(api, apportionment_method="DISTANCE")
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    assert tkt["purchase_price_cents"] == 1000
    assert tkt["apportionment_method"] == "DISTANCE"
    assert allocation_for_code(tkt, "A")["amount_cents"] == 166
    assert allocation_for_code(tkt, "B")["amount_cents"] == 333
    assert allocation_for_code(tkt, "C")["amount_cents"] == 501
    assert sum_allocations(tkt) == 1000


def test_apportionment_zone_count_variant_splits_by_shared_zone_count(api):
    """PRD 3.3: "under `ZONE_COUNT` the weight is the count of those shared zones"
    PRD 3.3: "The cents left over after flooring — the total minus the sum of the floors —
    are handed out one cent at a time to agencies ordered by weight descending, breaking
    ties by agency creation timestamp ascending, until no leftover remains."

    Design: Difficulty/dual_variant_calc/apportionment_zone_count_vs_distance_diverge_revenue_domain
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp = fx.create_fare_product(api, apportionment_method="ZONE_COUNT")
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    assert tkt["purchase_price_cents"] == 1000
    assert tkt["apportionment_method"] == "ZONE_COUNT"
    assert allocation_for_code(tkt, "A")["amount_cents"] == 334
    assert allocation_for_code(tkt, "B")["amount_cents"] == 333
    assert allocation_for_code(tkt, "C")["amount_cents"] == 333
    assert sum_allocations(tkt) == 1000


# ==========================================================================
# combinatorial_formula / ticket_price_nonlinear_reduced_peak_cap_mode_a
# ==========================================================================

def test_reduced_peak_price_applies_discount_before_cap(api):
    """PRD 3.3: "If the reduced fare applies, compute a discount equal to the subtotal
    multiplied by fifty percent, rounded half up, and subtract that discount from the
    subtotal; if it does not apply, the running price is simply the subtotal. Finally, cap
    the result at the fare ceiling of 5000 cents, taking the smaller of the running price
    and that ceiling as the purchase price."

    Design: Difficulty/combinatorial_formula/ticket_price_nonlinear_reduced_peak_cap_mode_a
    """
    pax, _app = fx.setup_reduced_fare_passenger(api, category="STUDENT")
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK", use_reduced_fare=True)
    assert tkt["reduced_fare_applied"] is True
    assert tkt["purchase_price_cents"] == 650


def test_reduced_price_capped_at_fare_ceiling(api):
    """PRD 3.3: "Finally, cap the result at the fare ceiling of 5000 cents, taking the
    smaller of the running price and that ceiling as the purchase price. The half-up
    rounding applies only to the discount step."

    Design: Difficulty/combinatorial_formula/ticket_price_nonlinear_reduced_peak_cap_mode_a
    """
    pax, _app = fx.setup_reduced_fare_passenger(api, category="STUDENT")
    # subtotal 11000, reduced discount round_half_up(5500)=5500 -> 5500, then capped to 5000.
    fp = fx.create_fare_product(api, base_fare_cents=11000, peak_surcharge_cents=0)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK", use_reduced_fare=True)
    assert tkt["reduced_fare_applied"] is True
    assert tkt["purchase_price_cents"] == 5000


# ==========================================================================
# combinatorial_formula / apportionment_rounding_floor_then_remainder_mode_b
# ==========================================================================

def test_apportionment_single_leftover_cent_goes_to_earliest_agency(api):
    """PRD 3.3: "The cents left over after flooring — the total minus the sum of the floors
    — are handed out one cent at a time to agencies ordered by weight descending, breaking
    ties by agency creation timestamp ascending, until no leftover remains."

    Design: Difficulty/combinatorial_formula/apportionment_rounding_floor_then_remainder_mode_b
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp = fx.create_fare_product(api, apportionment_method="ZONE_COUNT")
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")  # price 1000
    assert allocation_for_code(tkt, "A")["amount_cents"] == 334
    assert allocation_for_code(tkt, "B")["amount_cents"] == 333
    assert allocation_for_code(tkt, "C")["amount_cents"] == 333
    assert sum_allocations(tkt) == 1000


def test_apportionment_two_leftover_cents_go_to_two_earliest_agencies(api):
    """PRD 3.3: "are handed out one cent at a time to agencies ordered by weight
    descending, breaking ties by agency creation timestamp ascending, until no leftover
    remains."
    PRD 3.3: "The resulting allocation sums exactly to the purchase price."

    Design: Difficulty/combinatorial_formula/apportionment_rounding_floor_then_remainder_mode_b
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    # subtotal 1001 (base 701 + peak 300 on PEAK): 1001/3 -> floor 333 each, remainder 2.
    fp = fx.create_fare_product(api, base_fare_cents=701, peak_surcharge_cents=300,
                                apportionment_method="ZONE_COUNT")
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    assert tkt["purchase_price_cents"] == 1001
    assert allocation_for_code(tkt, "A")["amount_cents"] == 334
    assert allocation_for_code(tkt, "B")["amount_cents"] == 334
    assert allocation_for_code(tkt, "C")["amount_cents"] == 333
    assert sum_allocations(tkt) == 1001


# ==========================================================================
# cross_entity_state_dependency / ticket_reduced_fare_depends_on_passenger_eligibility
# ==========================================================================

def test_reduced_fare_granted_when_passenger_eligibility_valid(api):
    """PRD 3.3: "If `use_reduced_fare` is requested, the passenger must currently hold a
    reduced-fare category other than none and a `reduced_fare_valid_until` that is at or
    after the current clock instant"
    PRD 3.3: "When the request is valid the ticket's `reduced_fare_applied` flag is set true
    and the discount is taken; otherwise the flag is false."

    Design: Difficulty/cross_entity_state_dependency/ticket_reduced_fare_depends_on_passenger_eligibility
    """
    pax, _app = fx.setup_reduced_fare_passenger(api, category="STUDENT")
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK", use_reduced_fare=True)
    assert tkt["reduced_fare_applied"] is True
    assert tkt["purchase_price_cents"] == 500


def test_reduced_fare_rejected_when_passenger_not_eligible(api):
    """PRD 3.3: "otherwise the purchase is rejected with `ERR_REDUCED_FARE_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/ticket_reduced_fare_depends_on_passenger_eligibility
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    pax = fx.create_passenger(api)  # reduced_fare_category NONE
    resp = api.create_ticket(
        {"passenger_id": pax["id"], "fare_product_id": fp["id"],
         "travel_period": "OFF_PEAK", "use_reduced_fare": True},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REDUCED_FARE_NOT_ELIGIBLE.value)


# ==========================================================================
# Corner: wallet ledger and purchase-time guards
# ==========================================================================

def test_wallet_debit_on_purchase_reconciles_balance(api):
    """PRD 2.8: "It falls when credit is applied toward a purchase or an exchange, and when
    an issued service credit is later voided."
    PRD 2.8: "the balance always equals the sum of issued service credits plus approved
    wallet refunds plus exchange credits, minus the wallet amounts spent on tickets."

    Design: Corner/cross_cutting_complexity_layers/wallet_debit_on_purchase_reconciles_balance
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    pax = fx.create_passenger(api)
    tkt_a = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    rr = fx.request_refund(api, tkt_a["id"], pax["id"], refund_destination="WALLET")
    fx.approve_refund(api, rr["id"])  # wallet now 1300 - 200 = 1100
    tkt_b = validate_success(
        api.create_ticket(
            {"passenger_id": pax["id"], "fare_product_id": fp["id"],
             "travel_period": "PEAK", "wallet_apply_cents": 500},
            make_passenger_headers(pax["id"]),
        ),
        201,
    )
    assert tkt_b["wallet_applied_cents"] == 500
    assert tkt_b["purchase_price_cents"] == 1300
    passenger = fx.get_passenger(api, pax["id"])
    assert passenger["wallet_credit_cents"] == 600


def test_purchase_unknown_fare_product_returns_not_found(api):
    """PRD 2.6: "a missing fare product yields `ERR_FARE_PRODUCT_NOT_FOUND`"
    PRD 2.6: "All existence failures return HTTP 404."

    Design: Corner/validations/purchase_unknown_fare_product_returns_not_found
    """
    fx.set_clock(api)
    pax = fx.create_passenger(api)
    resp = api.create_ticket(
        {"passenger_id": pax["id"],
         "fare_product_id": "11111111-1111-4111-8111-111111111111",
         "travel_period": "PEAK"},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FARE_PRODUCT_NOT_FOUND.value)


def test_purchase_with_insufficient_wallet_returns_402(api):
    """PRD 2.8: "Any attempt to spend more wallet credit than the passenger currently holds
    is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 402). This guard applies both when
    purchasing a ticket and when exchanging one."

    Design: Corner/validations/purchase_with_insufficient_wallet_returns_402
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)  # wallet 0
    resp = api.create_ticket(
        {"passenger_id": pax["id"], "fare_product_id": fp["id"],
         "travel_period": "PEAK", "wallet_apply_cents": 500},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)
