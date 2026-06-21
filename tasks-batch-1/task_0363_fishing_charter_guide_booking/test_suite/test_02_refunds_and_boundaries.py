"""Cancellation refunds and numeric boundary precision: the weather-waiver vs
lead-time refund divergence, the 72h refund boundary, and the bag-limit equality
boundary at settlement. Covers difficulty-design dual-variant refund and
boundary-precision instances rooted in §3.8 of the PRD.
"""
from test_helpers import (
    validate_success,
    make_captain_headers,
    pin_clock,
    create_marina,
    create_dock_slot,
    create_boat,
    create_captain,
    create_customer,
    create_charter,
    create_booking,
    pay_deposit,
    reserve_slot,
    assign_captain,
    assign_mate,
    create_mate,
    create_permit,
    file_catch_report,
    get_charter,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER, make_customer_headers


def _build_scheduled_inshore(name, depart_at, return_at, clock):
    """Marina+slot+boat+captain+customer+charter, captain assigned, slot reserved,
    booking party 2 paid 5000, scheduled. Returns (charter_id, booking_id,
    customer_id, captain_id)."""
    pin_clock(clock)
    marina = create_marina(name=name)
    slot = create_dock_slot(marina["id"], slot_label="S1")
    boat = create_boat(marina["id"], name=name + "boat")
    captain = create_captain(marina["id"])
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], base_seat_price_cents=10000,
                             seats_total=6, depart_at=depart_at, return_at=return_at)
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    pay_deposit(booking["id"], customer["id"], 5000)
    api_client.schedule_charter(charter["id"], FLEET_MANAGER)
    return charter["id"], booking["id"], customer["id"], captain["id"]


# ===========================================================================
# Difficulty: dual_variant_calc / refund_weather_waiver_vs_lead_time_tier
# ===========================================================================

def test_refund_full_under_weather_waiver(api):
    """PRD §3.8: "If the booking's `weather_waiver` is true — meaning it was
    cancelled while its charter sat in `WEATHER_HOLD` — the lead-time tiers are
    ignored entirely and the full `deposit_paid_cents` is refunded."

    Charter put on WEATHER_HOLD -> booking weather_waiver=true; cancel during hold
    -> full 5000 refund.

    Design: Difficulty/dual_variant_calc/refund_weather_waiver_vs_lead_time_tier
    """
    ch_id, bk_id, cust_id, cap_id = _build_scheduled_inshore(
        "Waiver Marina", "2026-07-10T12:00:00Z", "2026-07-10T16:00:00Z",
        "2026-07-01T00:00:00Z")
    api_client.weather_hold_charter(ch_id, make_captain_headers(cap_id))
    res = api.cancel_booking(bk_id, make_customer_headers(cust_id))
    booking = validate_success(res, expected_status=200)
    assert booking["weather_waiver"] is True
    assert booking["refund_cents"] == 5000, booking["refund_cents"]


def test_refund_partial_under_lead_time_tier(api):
    """PRD §3.8: "if the lead is at least 24 hours but less than 72, half the
    deposit is refunded — `deposit_paid_cents` multiplied by 50, divided by 100,
    rounded half up to a whole cent."

    Clock 2026-07-01, depart 2026-07-03 = 48h lead (in [24,72)) -> 50% of 5000 =
    2500; weather_waiver false (charter stays SCHEDULED).

    Design: Difficulty/dual_variant_calc/refund_weather_waiver_vs_lead_time_tier
    """
    ch_id, bk_id, cust_id, _ = _build_scheduled_inshore(
        "LeadTime Marina", "2026-07-03T00:00:00Z", "2026-07-03T04:00:00Z",
        "2026-07-01T00:00:00Z")
    res = api.cancel_booking(bk_id, make_customer_headers(cust_id))
    booking = validate_success(res, expected_status=200)
    assert booking["weather_waiver"] is False
    assert booking["refund_cents"] == 2500, booking["refund_cents"]


# ===========================================================================
# Difficulty: boundary_precision_check / refund_lead_time_72h_boundary_inclusive
# ===========================================================================

def test_refund_full_at_exactly_72h_lead(api):
    """PRD §3.8: "If the lead is at least 72 hours, the full `deposit_paid_cents`
    is refunded ... The boundaries are inclusive on the lower side: exactly 72
    hours of lead yields a full refund."

    Clock 2026-12-07T12:00:00Z, depart 2026-12-10T12:00:00Z = exactly 72h ->
    full 5000 refund.

    Design: Difficulty/boundary_precision_check/refund_lead_time_72h_boundary_inclusive
    """
    ch_id, bk_id, cust_id, _ = _build_scheduled_inshore(
        "Bnd Marina", "2026-12-10T12:00:00Z", "2026-12-10T16:00:00Z",
        "2026-12-07T12:00:00Z")
    res = api.cancel_booking(bk_id, make_customer_headers(cust_id))
    booking = validate_success(res, expected_status=200)
    assert booking["refund_cents"] == 5000, booking["refund_cents"]


def test_refund_partial_just_below_72h_lead(api):
    """PRD §3.8: "if the lead is at least 24 hours but less than 72, half the
    deposit is refunded — `deposit_paid_cents` multiplied by 50, divided by 100,
    rounded half up to a whole cent."

    Clock 2026-12-07T13:00:00Z, depart 2026-12-10T12:00:00Z = 71h (just below the
    72h boundary) -> partial 50% of 5000 = 2500, confirming the boundary is the
    threshold.

    Design: Difficulty/boundary_precision_check/refund_lead_time_72h_boundary_inclusive
    """
    ch_id, bk_id, cust_id, _ = _build_scheduled_inshore(
        "Bnd Marina 2", "2026-12-10T12:00:00Z", "2026-12-10T16:00:00Z",
        "2026-12-07T13:00:00Z")
    res = api.cancel_booking(bk_id, make_customer_headers(cust_id))
    booking = validate_success(res, expected_status=200)
    assert booking["refund_cents"] == 2500, booking["refund_cents"]


# ===========================================================================
# Difficulty: boundary_precision_check / bag_limit_exact_equal_allowed_on_settle
# ===========================================================================

def _build_sailed_offshore_with_catch(name, bag_limit):
    """OFFSHORE charter through SAILED with permit daily_bag_limit=bag_limit.
    Returns (charter_id, captain_id)."""
    pin_clock("2026-12-10T06:00:00Z")
    marina = create_marina(name=name)
    slot = create_dock_slot(marina["id"], slot_label="H1", max_boat_length_ft=50)
    boat = create_boat(marina["id"], name=name + "boat", length_ft=42,
                       passenger_capacity=8, offshore_rated=True)
    permit = create_permit(daily_bag_limit=bag_limit)
    captain = create_captain(marina["id"], uscg_license_grade="MASTER_100")
    mate = create_mate(marina["id"], certified_offshore=True)
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], trip_type="OFFSHORE",
                             permit_id=permit["id"], base_seat_price_cents=30000,
                             seats_total=8, depart_at="2026-12-10T06:00:00Z",
                             return_at="2026-12-10T18:00:00Z")
    assign_captain(charter["id"], captain["id"])
    assign_mate(charter["id"], mate["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    pay_deposit(booking["id"], customer["id"], 15000)
    api_client.schedule_charter(charter["id"], FLEET_MANAGER)
    api_client.sail_charter(charter["id"], make_captain_headers(captain["id"]))
    return charter["id"], captain["id"]


def test_settle_allowed_when_catch_total_equals_bag_limit(api):
    """PRD §3.8: "Settlement requires the charter to be `SAILED` ... and, when a
    permit is attached, the kept-fish `catch_total` to be within the permit's
    `daily_bag_limit` (else `ERR_BAG_LIMIT_EXCEEDED`)."

    permit daily_bag_limit 10; catch reports keep exactly 10 (8 + (4-2)) ->
    catch_total 10 == 10 settles successfully.

    Design: Difficulty/boundary_precision_check/bag_limit_exact_equal_allowed_on_settle
    """
    ch_id, cap_id = _build_sailed_offshore_with_catch("Bag Marina", 10)
    file_catch_report(ch_id, cap_id, "Mahi", 8, released_count=0)
    file_catch_report(ch_id, cap_id, "Tuna", 4, released_count=2)
    res = api.settle_charter(ch_id, FLEET_MANAGER)
    charter = validate_success(res, expected_status=200)
    assert charter["catch_total"] == 10, charter["catch_total"]
    assert charter["status"] == "SETTLED"


def test_catch_total_counts_only_kept_fish(api):
    """PRD §3.6: "A charter's `catch_total` is the running tally of **kept** fish
    across all of its catch reports — for each report, its `fish_count` minus its
    `released_count`, summed over every report filed against the charter. Released
    fish never count toward this total."

    Reports 8 kept + (4 caught, 2 released = 2 kept) -> catch_total 10.

    Design: Difficulty/boundary_precision_check/bag_limit_exact_equal_allowed_on_settle
    """
    ch_id, cap_id = _build_sailed_offshore_with_catch("Bag Marina 2", 10)
    file_catch_report(ch_id, cap_id, "Mahi", 8, released_count=0)
    file_catch_report(ch_id, cap_id, "Tuna", 4, released_count=2)
    fresh = get_charter(ch_id)
    assert fresh["catch_total"] == 10, fresh["catch_total"]
