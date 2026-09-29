"""The two-bucket case waterfall, the club-day read and the shift pads."""

from datetime import datetime
from decimal import Decimal

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    STAFF_OPS_HEADERS,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.fixtures import (
    approve,
    assign,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_manufacturer,
    new_non_food_product,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    BookingStatus,
    DayPart,
    ProductCategory,
    ProgramTier,
)


def _instant(value):
    """Parse an ISO-8601 UTC instant, tolerating the optional fractional part."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decimal2(value):
    """Coerce a two-decimal API value into an exact Decimal for comparison."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_the_reserve_bucket_opens_for_platinum_and_stays_shut_for_gold(api):
    """PRD §3.3: "The second bucket's remaining capacity is zero unless the vendor's `program_tier` is `PLATINUM`, in which case it is the SKU's `emergency_reserve_cases` less the reserve already consumed, floored at zero; the cases drawn from it are the smaller of the remaining need and that capacity."

    PRD §3.3: "The first bucket's remaining capacity is the SKU's `weekly_sample_case_pool` less the pool already consumed, floored at zero; the cases drawn from it are the smaller of `requested_sample_cases` and that remaining capacity."

    PRD §3.3: "A partial allocation, where the waterfall supplies at least one case but fewer than requested, is perfectly acceptable for a `NON_FOOD_DEMO` event, and equally acceptable for a `FOOD_SAMPLING` event that still reaches the two-case floor."

    Design: Corner/calculations/allocation_waterfall_stops_at_bucket_one_unless_the_tier_is_platinum
    """
    club = new_club(
        api,
        club_number="C6019",
        name="Tarnbeck Club 6019",
        daily_event_capacity=4,
        food_station_count=1,
    )
    gold_vendor = new_manufacturer(
        api,
        legal_name="Tarnbeck Household",
        program_tier=ProgramTier.GOLD,
        credit_limit_cents=900_000,
        credit_terms_days=45,
    )
    platinum_vendor = new_manufacturer(
        api,
        legal_name="Ulverwood Electronics",
        program_tier=ProgramTier.PLATINUM,
        credit_limit_cents=900_000,
        credit_terms_days=60,
    )
    gold_product = new_non_food_product(
        api,
        gold_vendor["id"],
        sku="TH-BRM-019",
        name="Push Broom",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1900,
        samples_per_case=2,
        weekly_sample_case_pool=5,
        emergency_reserve_cases=6,
    )
    platinum_product = new_non_food_product(
        api,
        platinum_vendor["id"],
        sku="UE-SPK-019",
        name="Bluetooth Speaker",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=6400,
        samples_per_case=2,
        weekly_sample_case_pool=5,
        emergency_reserve_cases=6,
    )

    gold_event = new_demo_event(
        api,
        gold_vendor["id"],
        club["id"],
        gold_product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=8,
    )
    platinum_event = new_demo_event(
        api,
        platinum_vendor["id"],
        club["id"],
        platinum_product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=8,
    )
    submit(api, gold_event["id"], gold_vendor["id"])
    submit(api, platinum_event["id"], platinum_vendor["id"])

    gold_confirmed = approve(api, gold_event["id"], club["id"])
    platinum_confirmed = approve(api, platinum_event["id"], club["id"])

    assert gold_confirmed["booking_status"] == BookingStatus.CONFIRMED
    assert gold_confirmed["allocated_sample_cases"] == 5
    assert gold_confirmed["pool_cases_used"] == 5
    assert gold_confirmed["reserve_cases_used"] == 0
    assert gold_confirmed["requested_sample_cases"] == 8
    assert gold_confirmed["required_support_count"] == 0

    assert platinum_confirmed["allocated_sample_cases"] == 8
    assert platinum_confirmed["pool_cases_used"] == 5
    assert platinum_confirmed["reserve_cases_used"] == 3

    platinum_position = validate_success(
        api.get_club_capacity(
            club["id"],
            make_club_headers(club["id"]),
            "2026-09-14",
            product_id=platinum_product["id"],
        )
    )
    assert platinum_position["pool_remaining"] == 0
    assert platinum_position["reserve_remaining"] == 3


def test_the_club_day_read_counts_only_the_live_bookings(api):
    """PRD §3.1: "Supplied with an `event_date`, it reports the `club_id`, that `event_date`, the club's `daily_event_capacity`, the `confirmed_count` of live events on that date, the `remaining_slots` still open — which is the capacity less the confirmed count, floored at zero so it never reads negative — the `food_station_count`, the `food_confirmed_count` of live food events, and a `category_counts` object breaking the live events down by merchandising category."

    PRD §3.1: "When the caller also supplies a `product_id`, the same read adds the club-week sample position for that SKU: the `week_start_date` of the ISO week, the SKU's `weekly_sample_case_pool`, the `pool_cases_used` already drawn, the `pool_remaining`, the SKU's `emergency_reserve_cases`, the `reserve_cases_used`, and the `reserve_remaining`."

    PRD §3.3: "Note that only events in `CONFIRMED` or `COMPLETED` consume the pool at all: draft, submitted and cancelled events consume nothing, which is precisely what makes revocation and cancellation exact compensations."

    Design: Corner/calculations/capacity_read_reports_the_calendar_utilization_scope_for_one_day
    """
    vendor = new_manufacturer(api, legal_name="Vennhollow Goods", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6020",
        name="Vennhollow Club 6020",
        daily_event_capacity=4,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="VG-HNG-020",
        name="Cedar Hangers",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=900,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    confirmed_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=6,
    )
    submit(api, confirmed_event["id"], vendor["id"])
    approve(api, confirmed_event["id"], club["id"])

    draft_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.AFTERNOON,
        requested_sample_cases=2,
    )

    reading = validate_success(
        api.get_club_capacity(
            club["id"],
            make_manufacturer_headers(vendor["id"]),
            "2026-09-14",
            product_id=product["id"],
        )
    )

    assert reading["club_id"] == club["id"]
    assert reading["event_date"] == "2026-09-14"
    assert reading["daily_event_capacity"] == 4
    assert reading["confirmed_count"] == 1
    assert reading["remaining_slots"] == 3
    assert reading["food_station_count"] == 1
    assert reading["food_confirmed_count"] == 0
    assert reading["category_counts"][ProductCategory.HOUSEHOLD] == 1
    assert sum(reading["category_counts"].values()) == 1
    assert reading["week_start_date"] == "2026-09-14"
    assert reading["weekly_sample_case_pool"] == 20
    assert reading["pool_cases_used"] == 6
    assert reading["pool_remaining"] == 14
    assert reading["emergency_reserve_cases"] == 0
    assert reading["reserve_cases_used"] == 0
    assert reading["reserve_remaining"] == 0

    still_draft = validate_success(
        api.get_demo_event(draft_event["id"], make_manufacturer_headers(vendor["id"]))
    )
    assert still_draft["booking_status"] == BookingStatus.DRAFT


def test_the_shift_pads_widen_the_day_part_window_asymmetrically(api):
    """PRD §2.5: "Setup begins 45 minutes before the window opens, giving the assignment's `scheduled_start_utc`, and teardown runs for 75 minutes after the window closes, giving `scheduled_end_utc`."

    PRD §2.5: "A `MORNING` demo runs from 09:00Z to 13:00Z, a `MIDDAY` demo from 12:00Z to 16:00Z, and an `AFTERNOON` demo from 15:00Z to 19:00Z, all on the event's `event_date`."

    PRD §3.6: "`hours_worked` is the elapsed time from `check_in_at` to `check_out_at` expressed in hours and rounded half-up to two decimal places, and it reads 0.00 for as long as either stamp is unset."

    Design: Corner/calculations/assignment_shift_window_applies_the_setup_and_teardown_constants
    """
    vendor = new_manufacturer(api, legal_name="Brackenridge Wares", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6025",
        name="Brackenridge Club 6025",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="BW-CLK-025",
        name="Wall Clock",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2100,
        samples_per_case=2,
        weekly_sample_case_pool=20,
    )
    worker = new_demonstrator(
        api, club["id"], full_name="Cato Meiring", hourly_rate_cents=2000
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=3,
    )
    assert _instant(event["event_window_start_utc"]) == _instant("2026-09-14T12:00:00Z")
    assert _instant(event["event_window_end_utc"]) == _instant("2026-09-14T16:00:00Z")

    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])

    assignment = assign(api, event["id"], worker["id"], AssignmentRole.LEAD)

    assert _instant(assignment["scheduled_start_utc"]) == _instant("2026-09-14T11:15:00Z")
    assert _instant(assignment["scheduled_end_utc"]) == _instant("2026-09-14T17:15:00Z")
    assert _instant(assignment["scheduled_start_utc"]) != _instant(
        event["event_window_start_utc"]
    )
    assert _decimal2(assignment["hours_worked"]) == Decimal("0.00")
    assert _decimal2(assignment["billable_hours"]) == Decimal("0.00")
    assert assignment["travel_authorized"] is False

    read_back = validate_success(api.get_assignment(assignment["id"], STAFF_OPS_HEADERS))
    assert _instant(read_back["scheduled_start_utc"]) == _instant("2026-09-14T11:15:00Z")
    assert _instant(read_back["scheduled_end_utc"]) == _instant("2026-09-14T17:15:00Z")
