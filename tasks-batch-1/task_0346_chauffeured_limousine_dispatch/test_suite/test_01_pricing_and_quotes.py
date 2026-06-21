"""Pricing engine: estimate vs final settlement, the pinned evaluation order,
hourly ceil-then-tier interaction, and the affiliate payout basis.

Every dollar figure here is the PRD's pinned-order calculation; the tests pin the
exact integer-cent results so a faithful PRD-only implementer reproduces them.
"""
from test_helpers import (
    validate_success,
    set_clock,
    provision_with_resources,
    create_account,
    create_vehicle_class,
    create_affiliate,
    create_chauffeur,
    create_vehicle,
    create_reservation,
    create_confirmed_reservation,
    quote_reservation,
    confirm_reservation,
    assign_in_house,
    dispatch_trip,
    post_wait_event,
    complete_trip,
    accept_farmout,
    api_client,
    TEST_USERS,
    create_farm_out_order_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/dual_variant_reservation_estimate_vs_final_fare
# ---------------------------------------------------------------------------
def _build_dual_variant_completed():
    """SEDAN base 5000 per_mile 250 wait_per_min 200 grace 15; account discount 10
    gratuity 20; POINT_TO_POINT 12.4mi tolls 350; 7 chargeable wait minutes."""
    set_clock("2026-07-01T09:00:00Z")
    account = create_account(negotiated_discount_pct=10, default_gratuity_pct=20,
                             cancellation_grace_minutes=120)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200,
                                  included_wait_minutes=15)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO", rest_buffer_minutes=20)
    veh = create_vehicle(vclass["id"], plate="BLK-1", turnaround_minutes=30)
    res = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                             pickup_at="2026-07-01T12:00:00Z", planned_drop_at="2026-07-01T13:00:00Z",
                             estimated_miles=12.4, tolls_cents=350)
    quoted = quote_reservation(res["id"])
    confirmed = confirm_reservation(res["id"])
    assign_in_house(res["id"], drv["id"], veh["id"], confirmed["version"])
    dispatch_trip(res["id"], drv["id"])
    post_wait_event(res["id"], "CHAUFFEUR_ARRIVED", "2026-07-01T12:05:00Z", drv["id"])
    post_wait_event(res["id"], "PASSENGER_BOARDED", "2026-07-01T12:27:00Z", drv["id"])
    final = complete_trip(res["id"], drv["id"])
    return quoted, final, res["id"]


def test_estimate_excludes_wait_charge_at_quote():
    """PRD §3.2: "Finally the estimate total is the discounted base plus the
    gratuity plus the reservation's tolls_cents. The estimate deliberately
    excludes any wait charge and any cancellation fee."

    Design: Difficulty/dual_variant_calc/dual_variant_reservation_estimate_vs_final_fare
    """
    quoted, _final, _rid = _build_dual_variant_completed()
    assert quoted["quote_estimate_total_cents"] == 9098, (
        f"Estimate must exclude wait: expected 9098, got {quoted['quote_estimate_total_cents']}"
    )


def test_final_folds_wait_into_base_before_discount_and_gratuity():
    """PRD §3.4: "the fare base now absorbs the actual wait charge before any
    discount or gratuity is taken, which is why a trip with chargeable wait
    settles for more than it was quoted, while a trip with zero chargeable wait
    and unchanged tolls settles for exactly the estimate."

    Design: Difficulty/dual_variant_calc/dual_variant_reservation_estimate_vs_final_fare
    """
    quoted, final, _rid = _build_dual_variant_completed()
    assert final["chargeable_wait_minutes"] == 7
    assert final["final_total_cents"] == 10610, (
        f"Final with 7 wait minutes folded in: expected 10610, got {final['final_total_cents']}"
    )
    assert final["final_total_cents"] - quoted["quote_estimate_total_cents"] == 1512


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/dual_variant_farmout_payout_basis_vs_customer_total
# ---------------------------------------------------------------------------
def _build_dual_variant_farmout():
    """SEDAN base 5000 per_mile 250; account discount 10 gratuity 20; SFO affiliate
    payout 70%; POINT_TO_POINT 12.4mi tolls 350; offer then accept."""
    account = create_account(negotiated_discount_pct=10, default_gratuity_pct=20)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200,
                                  included_wait_minutes=15)
    affiliate = create_affiliate(name="Bay Black Car", market_code="SFO", payout_share_pct=70)
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-07-02T12:00:00Z",
                                             planned_drop_at="2026-07-02T13:00:00Z",
                                             estimated_miles=12.4, tolls_cents=350)
    order = validate_success(
        api_client.create_farm_out_order(
            create_farm_out_order_payload(confirmed["id"], affiliate["id"], confirmed["version"]),
            DISPATCHER,
        ),
        201,
    )
    accept_farmout(order["id"], affiliate["id"])
    final_res = validate_success(api_client.get_reservation(confirmed["id"], DISPATCHER), 200)
    final_order = validate_success(api_client.get_farm_out_order(order["id"], DISPATCHER), 200)
    return final_order, final_res


def test_offered_payout_uses_raw_fare_base_only():
    """PRD §3.5: "The payout is that fare base multiplied by the affiliate's
    payout_share_pct divided by 100, rounded to whole cents."

    Design: Difficulty/dual_variant_calc/dual_variant_farmout_payout_basis_vs_customer_total
    """
    order, _res = _build_dual_variant_farmout()
    assert order["offered_payout_cents"] == 5670, (
        f"Payout on raw fare base 8100 * 70%: expected 5670, got {order['offered_payout_cents']}"
    )


def test_customer_total_and_operator_payout_diverge_on_same_trip():
    """PRD §3.5: "The same trip therefore carries two legitimate but divergent
    value figures: the customer's final_total_cents on the reservation
    (post-discount, gratuity-inclusive, toll-inclusive) and the affiliate's
    offered_payout_cents on the order (raw fare base only)."

    Design: Difficulty/dual_variant_calc/dual_variant_farmout_payout_basis_vs_customer_total
    """
    order, res = _build_dual_variant_farmout()
    assert res["final_total_cents"] == 9098, (
        f"Customer final on farm-out accept (0 wait): expected 9098, got {res['final_total_cents']}"
    )
    assert order["offered_payout_cents"] != res["final_total_cents"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/combinatorial_hourly_ceil_then_tiered_discount_gratuity
# ---------------------------------------------------------------------------
def test_hourly_quote_ceils_hours_then_applies_discount_and_override_gratuity():
    """PRD §3.2: "for an HOURLY trip, the booked charter_hours are rounded up to
    the next whole hour and multiplied by the class's hourly_rate_cents"

    Design: Difficulty/combinatorial_formula/combinatorial_hourly_ceil_then_tiered_discount_gratuity
    """
    account = create_account(company_name="Globex", billing_email="ap@globex.com",
                             negotiated_discount_pct=25, default_gratuity_pct=20)
    vclass = create_vehicle_class(code="SUV", base_fare_cents=7000, per_mile_cents=300,
                                  hourly_rate_cents=15000, wait_per_minute_cents=250,
                                  included_wait_minutes=15)
    res = create_reservation(account["id"], vclass["id"], trip_type="HOURLY",
                             pickup_at="2026-07-03T18:00:00Z", planned_drop_at="2026-07-03T22:00:00Z",
                             charter_hours=3.2, gratuity_pct_override=15, tolls_cents=0)
    quoted = quote_reservation(res["id"])
    assert quoted["quote_estimate_total_cents"] == 51750, (
        f"ceil(3.2)=4 * 15000=60000, *0.75=45000, +15% grat 6750 => 51750, "
        f"got {quoted['quote_estimate_total_cents']}"
    )


def test_hourly_quote_advances_reservation_to_quoted():
    """PRD §3.2: "When a Dispatcher quotes a DRAFT reservation with action set to
    QUOTE, it advances DRAFT → QUOTED."

    Design: Difficulty/combinatorial_formula/combinatorial_hourly_ceil_then_tiered_discount_gratuity
    """
    account = create_account(company_name="Globex", billing_email="ap@globex.com",
                             negotiated_discount_pct=25, default_gratuity_pct=20)
    vclass = create_vehicle_class(code="SUV", base_fare_cents=7000, per_mile_cents=300,
                                  hourly_rate_cents=15000, wait_per_minute_cents=250)
    res = create_reservation(account["id"], vclass["id"], trip_type="HOURLY",
                             pickup_at="2026-07-03T18:00:00Z", planned_drop_at="2026-07-03T22:00:00Z",
                             charter_hours=3.2, gratuity_pct_override=15, tolls_cents=0)
    quoted = quote_reservation(res["id"])
    assert quoted["trip_status"] == "QUOTED"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/combinatorial_circular_eval_order_discount_then_gratuity_then_tolls
# ---------------------------------------------------------------------------
def test_gratuity_taken_on_discounted_base_then_tolls_added_last():
    """PRD §3.2: "Then gratuity is taken on the discounted base: the gratuity
    percent is the reservation's gratuity_pct_override when present and otherwise
    the account's default_gratuity_pct, and the gratuity is the discounted base
    multiplied by that percent divided by 100, rounded to whole cents."

    Design: Difficulty/combinatorial_formula/combinatorial_circular_eval_order_discount_then_gratuity_then_tolls
    """
    account = create_account(company_name="Initech", billing_email="ap@initech.com",
                             negotiated_discount_pct=10, default_gratuity_pct=20)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    res = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                             pickup_at="2026-07-04T12:00:00Z", planned_drop_at="2026-07-04T13:00:00Z",
                             estimated_miles=12.4, tolls_cents=350)
    quoted = quote_reservation(res["id"])
    assert quoted["quote_estimate_total_cents"] == 9098, (
        f"discounted_base 7290 -> grat 1458 -> +tolls 350 = 9098, "
        f"got {quoted['quote_estimate_total_cents']}"
    )


def test_tolls_are_not_discounted_or_gratuity_bearing():
    """PRD §3.2: "a tolls_cents pass-through amount (defaulting to 0, required to
    be zero or greater, and treated as a pass-through that is added after gratuity
    and never discounted or gratuity-bearing)"

    Design: Difficulty/combinatorial_formula/combinatorial_circular_eval_order_discount_then_gratuity_then_tolls
    """
    # Same base/discount/gratuity, with and without tolls; the delta must be
    # exactly the tolls amount (tolls neither discounted nor gratuity-bearing).
    account = create_account(company_name="Initech", billing_email="ap@initech.com",
                             negotiated_discount_pct=10, default_gratuity_pct=20)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    res_no_tolls = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                      pickup_at="2026-07-04T12:00:00Z",
                                      planned_drop_at="2026-07-04T13:00:00Z",
                                      estimated_miles=12.4, tolls_cents=0)
    q0 = quote_reservation(res_no_tolls["id"])
    res_tolls = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                   pickup_at="2026-07-04T14:00:00Z",
                                   planned_drop_at="2026-07-04T15:00:00Z",
                                   estimated_miles=12.4, tolls_cents=350)
    q1 = quote_reservation(res_tolls["id"])
    assert q0["quote_estimate_total_cents"] == 8748
    assert q1["quote_estimate_total_cents"] - q0["quote_estimate_total_cents"] == 350, (
        "Adding 350 tolls must raise the total by exactly 350 (tolls never discounted/gratuity-bearing)"
    )
