"""Approval's allocation write-back and the club-closure mass cancellation."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ADMIN_HQ_HEADERS,
    assert_event_dimensions,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.fixtures import (
    approve,
    credits_for_event,
    new_club,
    new_demo_event,
    new_manufacturer,
    new_non_food_product,
    set_clock,
    submit,
)
from test_helpers.types import (
    BookingAction,
    BookingStatus,
    ClubStatus,
    CreditReason,
    CreditStatus,
    DayPart,
    ProductCategory,
    ProgramTier,
    SettlementStatus,
    StaffingStatus,
)


def test_approval_writes_the_waterfall_draws_and_leaves_the_reserve_untouched(api):
    """PRD §3.3: "A successful approval writes `pool_cases_used`, `reserve_cases_used` and `allocated_sample_cases`; recomputes `required_support_count`, which reads 1 when the event is a `FOOD_SAMPLING` event whose `allocated_sample_cases` has reached at least 6 cases and reads 0 in every other case; stamps `approved_at` with the logical clock's current instant; and increments the event's `version` by 1."

    PRD §3.3: "The second bucket's remaining capacity is zero unless the vendor's `program_tier` is `PLATINUM`, in which case it is the SKU's `emergency_reserve_cases` less the reserve already consumed, floored at zero; the cases drawn from it are the smaller of the remaining need and that capacity."

    PRD §3.1: "When the caller also supplies a `product_id`, the same read adds the club-week sample position for that SKU: the `week_start_date` of the ISO week, the SKU's `weekly_sample_case_pool`, the `pool_cases_used` already drawn, the `pool_remaining`, the SKU's `emergency_reserve_cases`, the `reserve_cases_used`, and the `reserve_remaining`."

    Design: Corner/state_machines/approve_executes_its_declared_allocation_side_effects
    """
    vendor = new_manufacturer(
        api,
        legal_name="Lynbrooke Housewares",
        program_tier=ProgramTier.GOLD,
        credit_limit_cents=900_000,
        credit_terms_days=45,
    )
    club = new_club(api, club_number="C6011", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="LH-BLD-011",
        name="Immersion Blender",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=5900,
        samples_per_case=2,
        weekly_sample_case_pool=20,
        emergency_reserve_cases=4,
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=8,
    )
    submitted = submit(api, event["id"], vendor["id"])

    confirmed = validate_success(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.APPROVE}, make_club_headers(club["id"])
        )
    )

    assert_event_dimensions(
        confirmed,
        booking_status=BookingStatus.CONFIRMED,
        staffing_status=StaffingStatus.UNSTAFFED,
        settlement_status=SettlementStatus.UNBILLED,
    )
    assert confirmed["allocated_sample_cases"] == 8
    assert confirmed["pool_cases_used"] == 8
    assert confirmed["reserve_cases_used"] == 0
    assert confirmed["required_support_count"] == 0
    assert confirmed["approved_at"] is not None
    assert confirmed["version"] == submitted["version"] + 1

    capacity = validate_success(
        api.get_club_capacity(
            club["id"],
            make_manufacturer_headers(vendor["id"]),
            "2026-09-14",
            product_id=product["id"],
        )
    )
    assert capacity["weekly_sample_case_pool"] == 20
    assert capacity["pool_cases_used"] == 8
    assert capacity["pool_remaining"] == 12
    assert capacity["emergency_reserve_cases"] == 4
    assert capacity["reserve_cases_used"] == 0
    assert capacity["reserve_remaining"] == 4


def test_closing_a_club_spares_the_dates_already_behind_the_clock(api):
    """PRD §3.3: "Setting a club's `club_status` to `CLOSED` cancels every demo event at that club whose `booking_status` is `CONFIRMED` and whose `event_date` falls on or after the logical clock's UTC date."

    PRD §3.3: "Each of those events has its `cancellation_reason` set to `CLUB_CANCELLED`, receives the identical side-effect set as a club-initiated cancellation — including one `PENDING_APPROVAL` cancellation credit each — and has its `version` incremented by 1."

    PRD §3.3: "Events dated before the clock date are left alone, as are events that were never confirmed."

    PRD §3.3: "Coverage that stood at `UNSTAFFED` or `PARTIALLY_STAFFED` is first recomputed to `UNSTAFFED` and then locked; coverage that stood at `FULLY_STAFFED` moves directly to `CLOSED_OUT`, incrementing the event's `version` by 1."

    Design: Corner/state_machines/closing_a_club_cancels_only_its_future_confirmed_events
    """
    vendor = new_manufacturer(api, legal_name="Prattwood Homegoods")
    club = new_club(api, club_number="C6015", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="PW-LMP-015",
        name="Reading Lamp",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2700,
        samples_per_case=2,
        weekly_sample_case_pool=20,
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])

    past_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    future_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-10-05",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    submit(api, past_event["id"], vendor["id"])
    approve(api, past_event["id"], club["id"])
    submit(api, future_event["id"], vendor["id"])
    future_confirmed = approve(api, future_event["id"], club["id"])

    set_clock(api, "2026-09-20T00:00:00Z")

    closed_club = validate_success(
        api.update_club(club["id"], {"club_status": ClubStatus.CLOSED}, ADMIN_HQ_HEADERS)
    )
    assert closed_club["club_status"] == ClubStatus.CLOSED
    assert closed_club["version"] == club["version"] + 1

    cancelled = validate_success(api.get_demo_event(future_event["id"], vendor_headers))
    assert cancelled["booking_status"] == BookingStatus.CANCELLED
    assert cancelled["cancellation_reason"] == CreditReason.CLUB_CANCELLED
    assert cancelled["staffing_status"] == StaffingStatus.UNSTAFFED
    assert cancelled["version"] == future_confirmed["version"] + 1
    assert cancelled["allocated_sample_cases"] == 0

    spared = validate_success(api.get_demo_event(past_event["id"], vendor_headers))
    assert spared["booking_status"] == BookingStatus.CONFIRMED
    assert spared["cancellation_reason"] is None

    future_credits = credits_for_event(api, future_event["id"])
    assert len(future_credits) == 1
    assert future_credits[0]["credit_reason"] == CreditReason.CLUB_CANCELLED
    assert future_credits[0]["credit_status"] == CreditStatus.PENDING_APPROVAL
    assert credits_for_event(api, past_event["id"]) == []
