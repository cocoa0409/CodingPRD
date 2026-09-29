"""
Two scarce resources whose occupancy windows have opposite edge semantics.

An analyst's calendar is half-open once a debrief buffer is added to each booking;
a buyer person's cooling-off window is closed at both ends.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_ANALYST_SLOT_CONFLICT, ERR_CONTACT_COOLING_OFF_ACTIVE
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_field,
    assert_ledger,
    assert_money,
)
from test_helpers.fixtures import WinLossWorld


def _one_booking_from_two_to_three(world: WinLossWorld) -> WinLossWorld:
    """Two drawn losses with distinct buyer people, one already booked 14:00 to 15:00."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    deal_one = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.second_deal = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=260000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    contact_one = world.consented_contact(
        deal_id=deal_one["id"], incentive_eligibility="ELIGIBLE"
    )
    world.second_contact = world.consented_contact(
        deal_id=world.second_deal["id"],
        email="buyer2@brava.test",
        full_name="Cal Dos",
        incentive_eligibility="ELIGIBLE",
    )
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    world.schedule_interview(deal_id=deal_one["id"], buyer_contact_id=contact_one["id"])
    return world


def _one_person_interviewed_on_the_tenth_of_august(world: WinLossWorld) -> WinLossWorld:
    """The same buyer person on two deals, with a COMPLETED interview ending 15:00Z."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst(certified_until="2027-06-01T00:00:00.000Z")
    deal_one = world.create_deal(primary_competitor_id=world.competitor["id"])
    world.second_deal = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=260000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    contact_one = world.consented_contact(
        deal_id=deal_one["id"], incentive_eligibility="ELIGIBLE"
    )
    world.second_contact = world.consented_contact(
        deal_id=world.second_deal["id"],
        title_band="CHAMPION",
        incentive_eligibility="ELIGIBLE",
    )
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    world.schedule_interview(deal_id=deal_one["id"], buyer_contact_id=contact_one["id"])
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    world.first_contact = contact_one
    return world


def _second_booking(world: WinLossWorld, start: str, end: str):
    return world.api.create_interview(
        f.interview_payload(
            world.second_deal["id"],
            world.second_contact["id"],
            world.analyst["id"],
            scheduled_start_at=start,
            scheduled_end_at=end,
        ),
        world.analyst_headers,
    )


# ---------------------------------------------------------------------------
# The analyst calendar, buffered at each end
# ---------------------------------------------------------------------------


def test_a_zero_minute_gap_collides_with_the_earlier_debrief_buffer(world):
    """A booking starting the instant the first one ends is still inside the buffer.

    "a back-to-back booking with a gap of zero minutes **does** conflict, because the
    earlier interview's debrief buffer covers the later start"

    Design: Difficulty/resource_temporal_overlap/analyst_slot_conflict_uses_buffered_half_open_intervals
    """
    _one_booking_from_two_to_three(world)
    assert_analyst_workload(world.get_analyst(), 1, 75)

    validate_error(
        _second_booking(world, "2026-08-10T15:00:00.000Z", "2026-08-10T16:00:00.000Z"),
        ERR_ANALYST_SLOT_CONFLICT,
        409,
    )

    assert_analyst_workload(world.get_analyst(), 1, 75)
    assert_ledger(world.refresh_program(), 250.00, 0.00)


def test_a_gap_of_exactly_fifteen_minutes_is_accepted(world):
    """Touching the buffered end is not overlapping it.

    "and a gap of exactly fifteen minutes does **not** conflict"

    Design: Difficulty/resource_temporal_overlap/analyst_slot_conflict_uses_buffered_half_open_intervals
    """
    _one_booking_from_two_to_three(world)
    validate_error(
        _second_booking(world, "2026-08-10T15:00:00.000Z", "2026-08-10T16:00:00.000Z"),
        ERR_ANALYST_SLOT_CONFLICT,
        409,
    )

    body = validate_success(
        _second_booking(world, "2026-08-10T15:15:00.000Z", "2026-08-10T16:15:00.000Z"), 201
    )
    interview = body

    assert_field(interview, "status", "SCHEDULED")
    assert_money(interview["incentive_provisional_usd"], 250.00, "provisional")


def test_the_accepted_booking_reserves_a_second_slot_and_buffer(world):
    """The analyst now holds two open interviews and two buffered durations.

    "`committed_minutes` is the sum, over those same interviews, of the whole minutes
    between `scheduled_start_at` and `scheduled_end_at` plus a fifteen-minute debrief
    allowance per interview."

    Design: Difficulty/resource_temporal_overlap/analyst_slot_conflict_uses_buffered_half_open_intervals
    """
    _one_booking_from_two_to_three(world)
    validate_success(
        _second_booking(world, "2026-08-10T15:15:00.000Z", "2026-08-10T16:15:00.000Z"), 201
    )

    assert_analyst_workload(world.get_analyst(), 2, 150)
    assert_ledger(world.refresh_program(), 500.00, 0.00, "OPEN")


# ---------------------------------------------------------------------------
# The buyer person's cooling-off window, closed at both ends
# ---------------------------------------------------------------------------


def test_the_completed_interview_anchors_the_cooling_off_window(world):
    """The anchor is the person's completed end instant, recorded on the contact row.

    "the buyer contact's `completed_interview_count` increases by one and its
    `last_completed_interview_end_at` is set to `actual_end_at`"

    Design: Difficulty/resource_temporal_overlap/buyer_person_cooling_off_uses_closed_ninety_day_window_across_deals
    """
    _one_person_interviewed_on_the_tenth_of_august(world)

    contact = world.get_contact(world.first_contact["id"])
    assert contact["last_completed_interview_end_at"] == "2026-08-10T15:00:00.000Z", (
        f"anchor instant not recorded: {contact['last_completed_interview_end_at']}"
    )
    assert_field(contact, "completed_interview_count", 1)
    assert_money(world.get_interview()["incentive_final_usd"], 250.00, "final")
    assert_ledger(world.refresh_program(), 0.00, 250.00)


def test_a_start_exactly_ninety_days_after_the_anchor_is_still_inside_the_window(world):
    """The far edge is closed, and the collision is with the same person on another deal.

    "The window spans the ninety days before the requested start and is closed at
    both ends: an interview whose relevant instant lands exactly ninety days before
    the requested start is still inside the window and blocks the request with
    `ERR_CONTACT_COOLING_OFF_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/buyer_person_cooling_off_uses_closed_ninety_day_window_across_deals
    """
    _one_person_interviewed_on_the_tenth_of_august(world)

    validate_error(
        _second_booking(world, "2026-11-08T15:00:00.000Z", "2026-11-08T16:00:00.000Z"),
        ERR_CONTACT_COOLING_OFF_ACTIVE,
        409,
    )

    assert_ledger(world.refresh_program(), 0.00, 250.00)
    assert_analyst_workload(world.get_analyst(), 0, 0)


def test_a_start_one_day_beyond_the_window_is_accepted_and_priced_for_a_champion(world):
    """Ninety-one days out clears the window, and the new contact's band sets the base.

    "Otherwise a base amount is read from the buyer's `title_band` — 250.00 US
    dollars for `ECONOMIC_BUYER`, 175.00 for `CHAMPION`, 150.00 for `PROCUREMENT` and
    100.00 for `END_USER`."

    Design: Difficulty/resource_temporal_overlap/buyer_person_cooling_off_uses_closed_ninety_day_window_across_deals
    """
    _one_person_interviewed_on_the_tenth_of_august(world)
    validate_error(
        _second_booking(world, "2026-11-08T15:00:00.000Z", "2026-11-08T16:00:00.000Z"),
        ERR_CONTACT_COOLING_OFF_ACTIVE,
        409,
    )

    body = validate_success(
        _second_booking(world, "2026-11-09T15:00:00.000Z", "2026-11-09T16:00:00.000Z"), 201
    )
    interview = body

    assert_field(interview, "status", "SCHEDULED")
    assert_field(interview, "incentive_status", "COMMITTED")
    assert_money(interview["incentive_provisional_usd"], 175.00, "provisional")
    assert_ledger(world.refresh_program(), 175.00, 250.00, "OPEN")
    assert_analyst_workload(world.get_analyst(), 1, 75)
