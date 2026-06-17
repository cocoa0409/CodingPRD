"""Wait-time grace boundary and the lead-time cancellation tiers.

The wait calculation floors raw minutes and subtracts the class grace; the
cancellation calculation buckets lead time against the account grace into
FREE / TIER1 / TIER2 / NO_SHOW. Boundaries are tested at the exact edge.
"""
from test_helpers import (
    set_clock,
    create_account,
    create_vehicle_class,
    create_chauffeur,
    create_vehicle,
    create_reservation,
    create_quoted_reservation,
    quote_reservation,
    confirm_reservation,
    assign_in_house,
    dispatch_trip,
    post_wait_event,
    api_client,
    TEST_USERS,
    make_chauffeur_headers,
    trip_event_payload,
    wait_event_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_en_route(grace=15, drop="2026-07-11T13:00:00Z", pickup="2026-07-11T12:00:00Z"):
    """SEDAN with the given wait grace; reservation assigned + dispatched (EN_ROUTE),
    chauffeur arrived. Returns (reservation_id, chauffeur_id)."""
    account = create_account(negotiated_discount_pct=0, default_gratuity_pct=0)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200,
                                  included_wait_minutes=grace)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-5")
    res = create_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                             pickup_at=pickup, planned_drop_at=drop, estimated_miles=10)
    quote_reservation(res["id"])
    confirmed = confirm_reservation(res["id"])
    assign_in_house(res["id"], drv["id"], veh["id"], confirmed["version"])
    dispatch_trip(res["id"], drv["id"])
    return res["id"], drv["id"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/boundary_wait_exactly_grace_yields_zero_chargeable
# ---------------------------------------------------------------------------
def test_wait_exactly_grace_yields_zero_chargeable():
    """PRD §3.4: "The chargeable wait is the raw wait minus the grace when that
    difference is positive, and zero otherwise — so a wait of exactly the grace
    yields zero chargeable minutes, and the first chargeable minute is the one
    immediately past the grace."

    Design: Difficulty/boundary_precision_check/boundary_wait_exactly_grace_yields_zero_chargeable
    """
    rid, drv = _setup_en_route(grace=15)
    post_wait_event(rid, "CHAUFFEUR_ARRIVED", "2026-07-11T12:05:00Z", drv)
    final = api_client.create_wait_event(
        rid, wait_event_payload("PASSENGER_BOARDED", "2026-07-11T12:20:00Z"),
        make_chauffeur_headers(drv),
    )
    from test_helpers import validate_success
    boarded = validate_success(final, 201)  # WaitEvent created
    res = validate_success(api_client.get_reservation(rid, DISPATCHER), 200)
    assert res["chargeable_wait_minutes"] == 0, (
        f"raw 15 == grace 15 => 0 chargeable, got {res['chargeable_wait_minutes']}"
    )
    assert res["trip_status"] == "PASSENGER_ABOARD"
    assert boarded["kind"] == "PASSENGER_BOARDED"


def test_wait_one_minute_past_grace_is_first_chargeable_minute():
    """PRD §3.4: "so a wait of exactly the grace yields zero chargeable minutes,
    and the first chargeable minute is the one immediately past the grace."

    Design: Difficulty/boundary_precision_check/boundary_wait_exactly_grace_yields_zero_chargeable
    """
    rid, drv = _setup_en_route(grace=15)
    post_wait_event(rid, "CHAUFFEUR_ARRIVED", "2026-07-11T12:05:00Z", drv)
    post_wait_event(rid, "PASSENGER_BOARDED", "2026-07-11T12:21:00Z", drv)  # raw 16
    from test_helpers import validate_success
    res = validate_success(api_client.get_reservation(rid, DISPATCHER), 200)
    assert res["chargeable_wait_minutes"] == 1, (
        f"raw 16 - grace 15 => first chargeable minute, got {res['chargeable_wait_minutes']}"
    )


# The "first chargeable minute" corner case is exercised by the just-over-grace
# boundary test above; no separate test is emitted for it.


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/boundary_cancellation_lead_exactly_grace_is_free
# ---------------------------------------------------------------------------
def test_cancellation_lead_exactly_grace_is_free():
    """PRD §3.7: "If the lead is at least the grace, the tier is FREE and the fee
    is zero." ... "a lead exactly equal to the grace is FREE"

    Design: Difficulty/boundary_precision_check/boundary_cancellation_lead_exactly_grace_is_free
    """
    set_clock("2026-07-12T10:00:00Z")
    account = create_account(negotiated_discount_pct=10, default_gratuity_pct=20,
                             cancellation_grace_minutes=120)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-07-12T12:00:00Z",
                                       planned_drop_at="2026-07-12T13:00:00Z",
                                       estimated_miles=12.4, tolls_cents=350)
    from test_helpers import validate_success
    cancelled = validate_success(
        api_client.create_trip_event(quoted["id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    assert cancelled["cancellation_fee_cents"] == 0, (
        f"lead 120 == grace 120 => FREE (fee 0), got {cancelled['cancellation_fee_cents']}"
    )
    assert cancelled["trip_status"] == "CANCELLED"


def test_cancellation_one_minute_inside_grace_is_tier1():
    """PRD §3.7: "Otherwise, if the lead is at least sixty minutes, the tier is
    TIER1 and the fee is the penalty base times twenty-five percent, rounded to
    whole cents."

    Design: Difficulty/boundary_precision_check/boundary_cancellation_lead_exactly_grace_is_free
    """
    # Clock 10:01, pickup 12:00 => lead 119 (< grace 120, >= 60) => TIER1.
    set_clock("2026-07-12T10:01:00Z")
    account = create_account(negotiated_discount_pct=10, default_gratuity_pct=20,
                             cancellation_grace_minutes=120)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-07-12T12:00:00Z",
                                       planned_drop_at="2026-07-12T13:00:00Z",
                                       estimated_miles=12.4, tolls_cents=350)
    from test_helpers import validate_success
    cancelled = validate_success(
        api_client.create_trip_event(quoted["id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    assert cancelled["cancellation_fee_cents"] == 1823, (
        f"lead 119 inside grace => TIER1 25% of 7290 = 1823, got {cancelled['cancellation_fee_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner/calculations/calc_cancellation_tier1_quarter_penalty
# ---------------------------------------------------------------------------
def test_cancellation_tier1_quarter_penalty_at_lead_90():
    """PRD §3.7: "Otherwise, if the lead is at least sixty minutes, the tier is
    TIER1 and the fee is the penalty base times twenty-five percent, rounded to
    whole cents."

    Design: Corner/calculations/calc_cancellation_tier1_quarter_penalty
    """
    set_clock("2026-08-10T10:30:00Z")
    account = create_account(negotiated_discount_pct=10, default_gratuity_pct=20,
                             cancellation_grace_minutes=120)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-08-10T12:00:00Z",
                                       planned_drop_at="2026-08-10T13:00:00Z",
                                       estimated_miles=12.4, tolls_cents=350)
    from test_helpers import validate_success
    cancelled = validate_success(
        api_client.create_trip_event(quoted["id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    assert cancelled["cancellation_fee_cents"] == 1823, (
        f"lead 90 => TIER1 25% of penalty_base 7290 = 1823, got {cancelled['cancellation_fee_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner/calculations/calc_cancellation_noshow_full_penalty
# ---------------------------------------------------------------------------
def test_cancellation_noshow_full_penalty_after_pickup():
    """PRD §3.7: "Otherwise — pickup has already passed — the tier is NO_SHOW and
    the fee is the full penalty base."

    Design: Corner/calculations/calc_cancellation_noshow_full_penalty
    """
    set_clock("2026-08-11T09:00:00Z")
    account = create_account(negotiated_discount_pct=10, default_gratuity_pct=20,
                             cancellation_grace_minutes=120)
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    quoted = create_quoted_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                       pickup_at="2026-08-11T12:00:00Z",
                                       planned_drop_at="2026-08-11T13:00:00Z",
                                       estimated_miles=12.4, tolls_cents=350)
    set_clock("2026-08-11T12:05:00Z")  # pickup has passed; lead -5
    from test_helpers import validate_success
    cancelled = validate_success(
        api_client.create_trip_event(quoted["id"], trip_event_payload("CANCEL"), DISPATCHER), 200
    )
    assert cancelled["cancellation_fee_cents"] == 7290, (
        f"lead -5 => NO_SHOW full penalty base 7290, got {cancelled['cancellation_fee_cents']}"
    )
