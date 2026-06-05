"""Fare and billable-minute calculations: provisional vs final divergence,
the tiered/slow/cap formula, the sum-seconds-then-ceil rounding order, the
zero-minute boundary, and the low-income cap clamp.

All clock values are pinned via the test-driving clock so durations are
deterministic.
"""
from test_helpers import (
    validate_success,
    make_rider_headers,
    fixtures as fx,
)


def test_provisional_estimate_diverges_from_final_fare(api):
    """PRD §3.3: "The estimate is the plan's `unlock_fee_cents` plus 15 multiplied
    by the plan's `per_minute_cents`; if the plan's `daily_cap_cents` is greater
    than 0, the estimate is the lesser of that sum and the cap, and if the cap is
    0 the sum stands uncapped."
    PRD §3.5: "The gross fare is the plan's `unlock_fee_cents` plus the normal
    charge plus the slow charge."

    STANDARD plan (unlock 100, per_min 30). Provisional = 100 + 15*30 = 550.
    Trip rides 5 min, pauses 2 min, resumes, rides 1.5 min => 390 ride-seconds =>
    ceil(390/60)=7 billable minutes; final = 100 + 7*30 = 310. The two diverge.

    Design: Difficulty/dual_variant_calc/trip_provisional_vs_final_fare_diverge
    """
    plan, zone, vehicle, rider, trip = fx.setup_paused_resumed_trip([
        ("start", "2026-06-01T00:00:00Z"),
        ("pause", "2026-06-01T00:05:00Z"),
        ("resume", "2026-06-01T00:07:00Z"),
        ("end", "2026-06-01T00:08:30Z"),
    ])
    assert trip["estimated_fare_cents"] == 550, (
        f"provisional expected 550, got {trip['estimated_fare_cents']}")
    assert trip["billable_minutes"] == 7, (
        f"billable_minutes expected 7, got {trip['billable_minutes']}")
    assert trip["final_fare_cents"] == 310, (
        f"final expected 310, got {trip['final_fare_cents']}")
    assert trip["estimated_fare_cents"] != trip["final_fare_cents"]


def test_provisional_estimate_value_at_unlock(api):
    """PRD §3.3: "The estimate is the plan's `unlock_fee_cents` plus 15 multiplied
    by the plan's `per_minute_cents`; if the plan's `daily_cap_cents` is greater
    than 0, the estimate is the lesser of that sum and the cap, and if the cap is
    0 the sum stands uncapped."

    STANDARD plan unlock 100, per_min 30, cap 0 => estimated_fare_cents == 550 at
    the moment of unlock (forward-looking, segment-independent).

    Design: Difficulty/dual_variant_calc/trip_provisional_vs_final_fare_diverge
    """
    plan, zone, vehicle = fx.setup_world()
    rider = fx.create_funded_rider(plan["id"])
    fx.set_clock("2026-06-01T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    resp = api.create_trip({"rider_id": rider["id"], "vehicle_id": vehicle["id"]}, headers)
    trip = validate_success(resp, 201)
    assert trip["estimated_fare_cents"] == 550, (
        f"provisional expected 550, got {trip['estimated_fare_cents']}")
    assert trip["status"] == "ACTIVE"


def test_standard_fine_amount_is_base(api):
    """PRD §3.5: "The penalty amount is a base parking fine of 2,500 cents for a
    rider on any plan other than `LOW_INCOME`; for a rider whose current plan code
    is `LOW_INCOME`, the amount is that base reduced by 40 percent — that is, 2,500
    multiplied by one minus 0.40 — rounded half-up to a whole cent."

    A STANDARD rider ending in NO_PARK is fined exactly 2500 cents.

    Design: Difficulty/dual_variant_calc/fine_standard_vs_low_income_amount_diverge
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-01T01:00:00Z", "2026-06-01T01:02:00Z", amount_cents=10000)
    assert fine["reason"] == "BAD_PARKING_NO_PARK"
    assert fine["amount_cents"] == 2500, f"STANDARD fine expected 2500, got {fine['amount_cents']}"


def test_low_income_fine_amount_is_reduced_40_percent(api):
    """PRD §3.5: "The penalty amount is a base parking fine of 2,500 cents for a
    rider on any plan other than `LOW_INCOME`; for a rider whose current plan code
    is `LOW_INCOME`, the amount is that base reduced by 40 percent — that is, 2,500
    multiplied by one minus 0.40 — rounded half-up to a whole cent."

    A LOW_INCOME rider ending in NO_PARK is fined 1500 cents (2500 * 0.60).

    Design: Difficulty/dual_variant_calc/fine_standard_vs_low_income_amount_diverge
    """
    std = fx.create_standard_plan()
    li = fx.create_low_income_plan()
    ok_zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    np_zone = fx.create_zone(zone_type="NO_PARK", priority=3)
    vehicle = fx.create_vehicle(ok_zone["id"])
    rider = fx.make_low_income_rider(std["id"], li["id"], amount_cents=10000)
    headers = make_rider_headers(rider["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-01T01:00:00Z")
    fx.end_trip(rider, trip, np_zone["id"], "2026-06-01T01:02:00Z")
    fine = fx._fetch_only_fine(rider)
    assert fine["reason"] == "BAD_PARKING_NO_PARK"
    assert fine["amount_cents"] == 1500, f"LOW_INCOME fine expected 1500, got {fine['amount_cents']}"


def test_final_fare_slow_zone_discount_and_unlock(api):
    """PRD §3.5: "The slow charge is the slow minutes multiplied by the plan's
    `per_minute_cents` multiplied by one minus the plan's `slow_zone_discount_pct`,
    rounded half-up to a whole cent before it is combined."
    PRD §3.5: "The gross fare is the plan's `unlock_fee_cents` plus the normal
    charge plus the slow charge."

    Wholly-SLOW 6-minute STANDARD trip, slow_zone_discount_pct 0.50:
    unlock 100 + round(6*30*0.5)=90 => 190.

    Design: Difficulty/combinatorial_formula/final_fare_tiered_with_cap_and_slow_branch
    """
    plan = fx.create_standard_plan(slow_zone_discount_pct=0.50)
    slow_zone = fx.create_zone(name="Slow Park", zone_type="SLOW", priority=4, max_speed_kph=10)
    ok_zone = fx.create_zone(name="OK", zone_type="RIDE_OK", priority=6)
    vehicle = fx.create_vehicle(slow_zone["id"])
    rider = fx.create_funded_rider(plan["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-02T00:00:00Z")
    trip = fx.end_trip(rider, trip, ok_zone["id"], "2026-06-02T00:06:00Z")
    assert trip["billable_minutes"] == 6, f"expected 6 minutes, got {trip['billable_minutes']}"
    assert trip["final_fare_cents"] == 190, f"expected 190, got {trip['final_fare_cents']}"


def test_final_fare_slow_zone_debits_wallet_by_discounted_amount(api):
    """PRD §3.5: "First, the wallet is charged: a `WalletTransaction` of type
    `TRIP_CHARGE` is created carrying the negative `final_fare_cents`, and
    `Rider.wallet_balance_cents` is reduced by the final fare."
    PRD §3.5: "The slow charge is the slow minutes multiplied by the plan's
    `per_minute_cents` multiplied by one minus the plan's `slow_zone_discount_pct`,
    rounded half-up to a whole cent before it is combined."

    The wholly-SLOW 6-minute STANDARD trip (slow_disc 0.50) charges 190 to the
    wallet: a funded 5000 wallet drops to 4810, confirming the discounted fare is
    what is actually debited.

    Design: Difficulty/combinatorial_formula/final_fare_tiered_with_cap_and_slow_branch
    """
    plan = fx.create_standard_plan(slow_zone_discount_pct=0.50)
    slow_zone = fx.create_zone(name="Slow Park", zone_type="SLOW", priority=4, max_speed_kph=10)
    ok_zone = fx.create_zone(name="OK", zone_type="RIDE_OK", priority=6)
    vehicle = fx.create_vehicle(slow_zone["id"])
    rider = fx.create_funded_rider(plan["id"], amount_cents=5000)
    headers = make_rider_headers(rider["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-02T00:00:00Z")
    trip = fx.end_trip(rider, trip, ok_zone["id"], "2026-06-02T00:06:00Z")
    assert trip["final_fare_cents"] == 190, f"expected 190, got {trip['final_fare_cents']}"
    rider_after = validate_success(api.get_rider(rider["id"], headers))
    assert rider_after["wallet_balance_cents"] == 4810, (
        f"expected wallet 5000-190=4810, got {rider_after['wallet_balance_cents']}")


def test_billable_minutes_sum_seconds_then_ceil(api):
    """PRD §3.4: "The system first sums the `duration_seconds` of every `RIDE`
    segment of the trip (pause segments contribute nothing), then converts that
    total to minutes by dividing by 60 and rounding up to the next whole minute; a
    total of 0 ride-seconds yields 0 billable minutes."
    PRD §3.4: "This sum-the-seconds-then-round-up order is deliberate and is not
    the same as rounding each segment to minutes individually and summing — the two
    diverge at sub-minute boundaries."

    Two RIDE segments of 70s each: ceil((70+70)/60)=ceil(140/60)=3, not 2+2=4.
    Fare = 100 + 3*30 = 190.

    Design: Difficulty/combinatorial_formula/billable_minutes_sum_seconds_then_ceil_rounding_order
    """
    plan, zone, vehicle, rider, trip = fx.setup_paused_resumed_trip([
        ("start", "2026-06-03T00:00:00Z"),
        ("pause", "2026-06-03T00:01:10Z"),
        ("resume", "2026-06-03T00:03:00Z"),
        ("end", "2026-06-03T00:04:10Z"),
    ])
    assert trip["billable_minutes"] == 3, (
        f"sum-then-ceil expected 3, got {trip['billable_minutes']}")
    assert trip["final_fare_cents"] == 190, f"expected 190, got {trip['final_fare_cents']}"


def test_billable_minutes_two_70s_segments_total_three(api):
    """PRD §3.4: "The system first sums the `duration_seconds` of every `RIDE`
    segment of the trip (pause segments contribute nothing), then converts that
    total to minutes by dividing by 60 and rounding up to the next whole minute; a
    total of 0 ride-seconds yields 0 billable minutes."

    The two closed RIDE segments are 70s and 70s; the trip's billable_minutes is
    ceil(140/60) == 3, which is observable directly on the completed trip.

    Design: Difficulty/combinatorial_formula/billable_minutes_sum_seconds_then_ceil_rounding_order
    """
    plan, zone, vehicle, rider, trip = fx.setup_paused_resumed_trip([
        ("start", "2026-06-03T00:00:00Z"),
        ("pause", "2026-06-03T00:01:10Z"),
        ("resume", "2026-06-03T00:03:00Z"),
        ("end", "2026-06-03T00:04:10Z"),
    ])
    assert trip["billable_minutes"] == 3, (
        f"sum-then-ceil expected 3, got {trip['billable_minutes']}")


def test_zero_billable_minutes_charges_unlock_only(api):
    """PRD §3.4: "a total of 0 ride-seconds yields 0 billable minutes."
    PRD §3.5: "The gross fare is the plan's `unlock_fee_cents` plus the normal
    charge plus the slow charge."

    A trip ended in the same second it started has 0 ride seconds, so
    billable_minutes == 0 and final_fare_cents == the unlock fee 100 only.

    Design: Difficulty/boundary_precision_check/trip_zero_billable_minutes_charges_unlock_only
    """
    plan, zone, vehicle = fx.setup_world()
    rider = fx.create_funded_rider(plan["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-10T00:00:00Z")
    # End at the same clock instant — no clock advance.
    trip = fx.end_trip(rider, trip, zone["id"])
    assert trip["billable_minutes"] == 0, f"expected 0 minutes, got {trip['billable_minutes']}"
    assert trip["final_fare_cents"] == 100, f"expected 100, got {trip['final_fare_cents']}"


def test_zero_billable_minutes_debits_only_unlock_fee(api):
    """PRD §3.4: "a total of 0 ride-seconds yields 0 billable minutes."
    PRD §3.5: "First, the wallet is charged: a `WalletTransaction` of type
    `TRIP_CHARGE` is created carrying the negative `final_fare_cents`, and
    `Rider.wallet_balance_cents` is reduced by the final fare."

    A same-instant start/end charges only the unlock fee: a funded 5000 wallet
    drops to exactly 4900 (5000 - 100), confirming no per-minute charge accrues at
    the zero-minute boundary.

    Design: Difficulty/boundary_precision_check/trip_zero_billable_minutes_charges_unlock_only
    """
    plan, zone, vehicle = fx.setup_world()
    rider = fx.create_funded_rider(plan["id"], amount_cents=5000)
    headers = make_rider_headers(rider["id"])
    trip = fx.start_trip(rider, vehicle, "2026-06-10T00:00:00Z")
    trip = fx.end_trip(rider, trip, zone["id"])
    assert trip["billable_minutes"] == 0
    assert trip["final_fare_cents"] == 100
    rider_after = validate_success(api.get_rider(rider["id"], headers))
    assert rider_after["wallet_balance_cents"] == 4900, (
        f"expected wallet 4900, got {rider_after['wallet_balance_cents']}")


def test_low_income_fare_lands_exactly_at_cap(api):
    """PRD §3.5: "The fare stored in `final_fare_cents` is that gross figure when
    the plan's `daily_cap_cents` is 0, and otherwise the lesser of the gross figure
    and the cap."

    LOW_INCOME (unlock 50, per_min 15, cap 500). 30 billable minutes: gross
    50 + 30*15 = 500 == cap => charged exactly 500.

    Design: Corner/calculations/low_income_fare_uses_low_income_rates_and_cap
    """
    std = fx.create_standard_plan()
    li = fx.create_low_income_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"])
    rider = fx.make_low_income_rider(std["id"], li["id"], amount_cents=5000, household_size=1,
                                     annual_income_cents=2000000)
    trip = fx.start_trip(rider, vehicle, "2026-07-06T00:00:00Z")
    trip = fx.end_trip(rider, trip, zone["id"], "2026-07-06T00:30:00Z")
    assert trip["billable_minutes"] == 30, f"expected 30 minutes, got {trip['billable_minutes']}"
    assert trip["final_fare_cents"] == 500, f"expected cap 500, got {trip['final_fare_cents']}"


def test_daily_cap_clamps_fare_above_cap(api):
    """PRD §3.5: "The fare stored in `final_fare_cents` is that gross figure when
    the plan's `daily_cap_cents` is 0, and otherwise the lesser of the gross figure
    and the cap."

    LOW_INCOME 31 billable minutes: gross 50 + 31*15 = 515, clamped by min() to
    the cap 500.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_daily_cap_clamps_above_cap
    """
    std = fx.create_standard_plan()
    li = fx.create_low_income_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"])
    rider = fx.make_low_income_rider(std["id"], li["id"], amount_cents=5000, household_size=1,
                                     annual_income_cents=2000000)
    trip = fx.start_trip(rider, vehicle, "2026-07-23T00:00:00Z")
    trip = fx.end_trip(rider, trip, zone["id"], "2026-07-23T00:31:00Z")
    assert trip["billable_minutes"] == 31, f"expected 31 minutes, got {trip['billable_minutes']}"
    assert trip["final_fare_cents"] == 500, f"gross 515 clamped to 500, got {trip['final_fare_cents']}"
