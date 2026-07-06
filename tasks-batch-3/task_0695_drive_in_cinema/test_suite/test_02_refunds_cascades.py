"""Refund-policy and transitive-cascade tests.

Covers Difficulty queue (dual_variant_calc refund, transitive_cascade depth-3) and Corner
queue (calculations weather pro-rata) instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_patron_headers,
    TEST_USERS,
    setup_double_feature_showtime,
    setup_venue_lot_film,
    create_showtime,
    make_reservation,
    create_paid_reservation,
    create_paid_concession_order,
    standard_concession_lines,
    create_concession_item,
    list_refunds_for_reservation,
    list_refunds_for_order,
)

OPERATOR = TEST_USERS["venue_operator_headers"]


# =====================================================================
# Difficulty: dual_variant_calc / refund_weather_pro_rata_vs_voluntary_tier
# (the SAME paid amount refunds differently by reason)
# =====================================================================
def test_voluntary_cancel_full_refund_48h_before(api):
    """PRD §3.6: "At 48 hours or more before start, the full amount is refunded (100
    percent). ... The refund is the `amount_paid_cents` multiplied by the applicable tier
    percentage, rounded half up once to a whole cent."

    Design: Difficulty/dual_variant_calc/refund_weather_pro_rata_vs_voluntary_tier
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-10T02:00:00Z",
        pricing_mode="PER_CAR", base_price_cents=2000, included_occupants=2,
        per_extra_person_cents=600, double_feature_surcharge_cents=1500, stall_count=10,
    )
    resv = create_paid_reservation(st, "patron-aaa", occupant_count=5)
    assert resv["amount_due_cents"] == 5300
    assert resv["amount_paid_cents"] == 5300
    cancelled = validate_success(
        api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-aaa"))
    )
    assert cancelled["payment_status"] == "REFUNDED"
    refunds = list_refunds_for_reservation(resv["id"])
    matching = [r for r in refunds if r["reason"] == "VOLUNTARY_CANCEL"]
    assert len(matching) == 1, f"expected exactly one VOLUNTARY_CANCEL refund, got {refunds}"
    assert matching[0]["amount_cents"] == 5300  # 48h+ -> 100%


def test_weather_cancel_pro_rata_half_refund(api):
    """PRD §3.6: "The refund is the `amount_paid_cents` multiplied by remaining features
    divided by total features, rounded half up once to a whole cent. A double feature
    stopped after the first feature thus refunds 50 percent even if the cancellation lands
    mid-event, independent of how close to start time it is."

    Design: Difficulty/dual_variant_calc/refund_weather_pro_rata_vs_voluntary_tier
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-10T02:00:00Z",
        pricing_mode="PER_CAR", base_price_cents=2000, included_occupants=2,
        per_extra_person_cents=600, double_feature_surcharge_cents=1500, stall_count=10,
    )
    resv = create_paid_reservation(st, "patron-aaa2", occupant_count=5)
    assert resv["amount_paid_cents"] == 5300
    # CANCELLATION weather event, 1 of 2 features remaining -> round_half_up(5300*1/2)=2650
    validate_success(
        api.create_weather_event(
            st["id"], {"severity": "CANCELLATION", "features_remaining": 1}, OPERATOR
        ),
        expected_status=201,
    )
    refunds = list_refunds_for_reservation(resv["id"])
    weather = [r for r in refunds if r["reason"] == "WEATHER"]
    assert len(weather) == 1, f"expected exactly one WEATHER refund, got {refunds}"
    assert weather[0]["amount_cents"] == 2650


# =====================================================================
# Difficulty: transitive_cascade / reservation_cancel_depth3_concession_refund
# =====================================================================
def test_reservation_cancel_depth3_concession_cascade(api):
    """PRD §3.5: "The cancellation then cascades: any concession order on this reservation
    whose `status` is `PENDING` or `PAID` is moved to `CANCELLED`, and if such an order was
    `PAID`, a further refund record for the full order total is created, attributing the
    refund to the reservation cascade."

    Design: Difficulty/transitive_cascade/reservation_cancel_depth3_concession_refund
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    lines, ids = standard_concession_lines(venue["id"])
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-20T02:00:00Z",
                         included_occupants=2)
    resv = create_paid_reservation(st, "patron-fff", occupant_count=2)
    assert resv["amount_paid_cents"] == 2000
    order = create_paid_concession_order(resv["id"], "patron-fff", lines)
    assert order["total_cents"] == 3000
    cancelled = validate_success(
        api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-fff"))
    )
    assert cancelled["occupancy_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    # Inspect the cascaded order through the reservation's concession-order list.
    orders = api.list_concession_orders(resv["id"], OPERATOR).json()["data"]
    target = [o for o in orders if o["id"] == order["id"]][0]
    assert target["status"] == "CANCELLED"
    # Refund records: one reservation VOLUNTARY_CANCEL (2000), one cascade order (3000).
    resv_refunds = [r for r in list_refunds_for_reservation(resv["id"]) if r["reason"] == "VOLUNTARY_CANCEL"]
    assert len(resv_refunds) == 1 and resv_refunds[0]["amount_cents"] == 2000
    order_refunds = [r for r in list_refunds_for_order(order["id"]) if r["reason"] == "RESERVATION_CASCADE"]
    assert len(order_refunds) == 1 and order_refunds[0]["amount_cents"] == 3000


def test_reservation_cancel_concession_order_refund_record_full_total(api):
    """PRD §3.6: "its `amount_cents` is the computed refund for reservation refunds, or the
    order's full `total_cents` for a cascaded concession refund."

    Design: Difficulty/transitive_cascade/reservation_cancel_depth3_concession_refund
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    lines, ids = standard_concession_lines(venue["id"])
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-21T02:00:00Z",
                         included_occupants=2)
    resv = create_paid_reservation(st, "patron-fff2", occupant_count=2)
    order = create_paid_concession_order(resv["id"], "patron-fff2", lines)
    validate_success(
        api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-fff2"))
    )
    order_refunds = list_refunds_for_order(order["id"])
    cascade = [r for r in order_refunds if r["reason"] == "RESERVATION_CASCADE"]
    assert len(cascade) == 1
    assert cascade[0]["source_type"] == "CONCESSION_ORDER"
    assert cascade[0]["amount_cents"] == order["total_cents"]


# =====================================================================
# Difficulty: transitive_cascade / showtime_weather_cancel_depth3_chain
# =====================================================================
def test_showtime_weather_cancel_depth3_chain(api):
    """PRD §3.10: "for every reservation on the showtime whose `occupancy_status` is
    `CONFIRMED`, `CHECKED_IN`, or `SCANNED`, the reservation is moved to `occupancy_status`
    `CANCELLED`, its stall and person counts are released, and any season-pass redemption it
    used is restored; and if that reservation's `payment_status` was `PAID`, a weather refund
    (pro-rated by `features_remaining` per §3.6) is computed, `payment_status` is set to
    `REFUNDED`, and a refund record with reason `WEATHER` is created."

    Design: Difficulty/transitive_cascade/showtime_weather_cancel_depth3_chain
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    lines, ids = standard_concession_lines(venue["id"])
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-22T02:00:00Z",
                         included_occupants=2)
    resv = create_paid_reservation(st, "patron-ggg", occupant_count=2)
    assert resv["amount_paid_cents"] == 2000
    order = create_paid_concession_order(resv["id"], "patron-ggg", lines)
    assert order["total_cents"] == 3000
    # single feature, features_remaining=1 of 1 -> full 2000
    validate_success(
        api.create_weather_event(
            st["id"], {"severity": "CANCELLATION", "features_remaining": 1}, OPERATOR
        ),
        expected_status=201,
    )
    showtime_after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert showtime_after["status"] == "CANCELLED"
    resv_after = validate_success(api.get_reservation(resv["id"], OPERATOR))
    assert resv_after["occupancy_status"] == "CANCELLED"
    assert resv_after["payment_status"] == "REFUNDED"
    orders = api.list_concession_orders(resv["id"], OPERATOR).json()["data"]
    target = [o for o in orders if o["id"] == order["id"]][0]
    assert target["status"] == "CANCELLED"
    weather = [r for r in list_refunds_for_reservation(resv["id"]) if r["reason"] == "WEATHER"]
    assert len(weather) == 1 and weather[0]["amount_cents"] == 2000
    cascade = [r for r in list_refunds_for_order(order["id"]) if r["reason"] == "RESERVATION_CASCADE"]
    assert len(cascade) == 1 and cascade[0]["amount_cents"] == 3000


def test_showtime_weather_cancel_full_refund_single_feature(api):
    """PRD §3.6: "Let the total feature count be 2 for a double feature and 1 for a single
    feature; let the remaining features be the smaller of the weather event's
    `features_remaining` and that total. The refund is the `amount_paid_cents` multiplied by
    remaining features divided by total features, rounded half up once to a whole cent."

    Design: Difficulty/transitive_cascade/showtime_weather_cancel_depth3_chain
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-23T02:00:00Z",
                         included_occupants=2)
    resv = create_paid_reservation(st, "patron-ggg2", occupant_count=2)
    assert resv["amount_paid_cents"] == 2000
    validate_success(
        api.create_weather_event(
            st["id"], {"severity": "CANCELLATION", "features_remaining": 1}, OPERATOR
        ),
        expected_status=201,
    )
    weather = [r for r in list_refunds_for_reservation(resv["id"]) if r["reason"] == "WEATHER"]
    # single feature: 1/1 -> full 2000
    assert len(weather) == 1 and weather[0]["amount_cents"] == 2000


# =====================================================================
# Corner: calculations / weather_per_person_pro_rata_partial
# =====================================================================
def test_weather_per_person_pro_rata_partial(api):
    """PRD §3.6: "The refund is the `amount_paid_cents` multiplied by remaining features
    divided by total features, rounded half up once to a whole cent."

    Design: Corner/calculations/weather_per_person_pro_rata_partial
    """
    venue, lot, f1, f2, st = setup_double_feature_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-08-06T02:00:00Z",
        pricing_mode="PER_PERSON", base_price_cents=900,
        double_feature_surcharge_cents=1500, person_capacity=200,
    )
    resv = create_paid_reservation(st, "patron-wpp", occupant_count=4)
    assert resv["amount_paid_cents"] == 5100
    validate_success(
        api.create_weather_event(
            st["id"], {"severity": "CANCELLATION", "features_remaining": 1}, OPERATOR
        ),
        expected_status=201,
    )
    resv_after = validate_success(api.get_reservation(resv["id"], OPERATOR))
    assert resv_after["payment_status"] == "REFUNDED"
    weather = [r for r in list_refunds_for_reservation(resv["id"]) if r["reason"] == "WEATHER"]
    # round_half_up(5100 * 1/2) = 2550
    assert len(weather) == 1 and weather[0]["amount_cents"] == 2550
