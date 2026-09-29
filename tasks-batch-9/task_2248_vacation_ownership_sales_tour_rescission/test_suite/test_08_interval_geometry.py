"""Two overlap geometries, one half-open with an end buffer and one closed."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Gallery capacity: strict comparisons, buffer on the end only
# ---------------------------------------------------------------------------


def _capacity_one_gallery_occupied_from_nine_to_eleven():
    """A single-slot gallery holding one 09:00-11:00 tour on 2026-08-16."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery(
        name="Kissimmee Sales Gallery",
        site_code="KISGAL",
        concurrent_tour_capacity=1,
        presentation_minutes=120,
        buffer_minutes=30,
    )
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    occupying = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-16T09:00:00Z",
    )
    assert_instant_equals(
        occupying["scheduled_end_utc"], "2026-08-16T11:00:00Z", "scheduled_end_utc"
    )
    return {
        "gallery": gallery,
        "channel": channel,
        "prospect": prospect,
        "occupying": occupying,
    }


def _book_at(scene, scheduled_start_utc):
    return api.create_tour_booking(
        fac.create_tour_booking_payload(
            scene["channel"]["id"],
            scene["prospect"]["id"],
            scene["gallery"]["id"],
            scheduled_start_utc=scheduled_start_utc,
        ),
        MARKETING,
    )


def test_the_buffered_end_admits_eleven_thirty_and_refuses_eleven_twenty_nine():
    """One minute short of the turnaround still overlaps; the exact instant does not.

    The PRD states: "With a 120-minute presentation and a 30-minute buffer, an
    existing interval from 09:00 to 11:00 leaves 11:30 available and refuses
    11:29."

    Design: Difficulty/resource_temporal_overlap/gallery_capacity_half_open_interval_with_end_buffer
    """
    scene = _capacity_one_gallery_occupied_from_nine_to_eleven()

    validate_error(
        _book_at(scene, "2026-08-16T11:29:00Z"),
        ApiErrorId.ERR_GALLERY_CAPACITY_EXCEEDED.value,
        409,
    )

    admitted = validate_success(_book_at(scene, "2026-08-16T11:30:00Z"), 201)
    assert_instant_equals(
        admitted["scheduled_start_utc"], "2026-08-16T11:30:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        admitted["scheduled_end_utc"], "2026-08-16T13:30:00Z", "scheduled_end_utc"
    )
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 2


def test_the_earlier_side_carries_the_buffer_on_the_candidate_end_instead():
    """A 06:30 tour ends at 08:30 and clears 09:00 with its own buffer; 06:31 does not.

    The PRD states: "An occupying booking overlaps the candidate when *both* of two
    comparisons hold, each of them strict: the occupying booking's start is earlier
    than the candidate's end plus the gallery's `buffer_minutes`, and the
    candidate's start is earlier than the occupying booking's `scheduled_end_utc`
    plus the same `buffer_minutes`."

    Design: Difficulty/resource_temporal_overlap/gallery_capacity_half_open_interval_with_end_buffer
    """
    scene = _capacity_one_gallery_occupied_from_nine_to_eleven()

    validate_error(
        _book_at(scene, "2026-08-16T06:31:00Z"),
        ApiErrorId.ERR_GALLERY_CAPACITY_EXCEEDED.value,
        409,
    )

    early = validate_success(_book_at(scene, "2026-08-16T06:30:00Z"), 201)
    assert_instant_equals(
        early["scheduled_end_utc"], "2026-08-16T08:30:00Z", "scheduled_end_utc"
    )

    late = validate_success(_book_at(scene, "2026-08-16T11:30:00Z"), 201)
    assert_instant_equals(
        late["scheduled_end_utc"], "2026-08-16T13:30:00Z", "scheduled_end_utc"
    )

    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 3


# ---------------------------------------------------------------------------
# Representative calendars: non-strict comparisons, symmetric 15-minute gap
# ---------------------------------------------------------------------------


def _one_representative_with_a_finished_morning_tour():
    """A four-slot gallery, one representative, and a 09:30-11:30 window on record."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery(
        name="Davenport Sales Gallery",
        site_code="DAVGAL",
        concurrent_tour_capacity=4,
        presentation_minutes=120,
        buffer_minutes=0,
    )
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    bookings = [
        fx.create_booking(
            channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=start
        )
        for start in (
            "2026-08-16T09:30:00Z",
            "2026-08-16T11:45:00Z",
            "2026-08-16T11:46:00Z",
        )
    ]

    fx.pin_clock("2026-08-16T09:30:00Z")
    checked_in = fx.check_in(bookings[0]["id"], False)
    assert checked_in["assigned_rep_id"] == representative["id"]
    presentation = fx.open_presentation(bookings[0]["id"], representative["id"])
    fx.acknowledge_required_disclosures(presentation["id"], representative["id"])
    fx.review_presentation(presentation["id"], "CLEAR", OFFICER_ALPHA)
    presentation = fx.complete_presentation(presentation["id"], representative["id"])

    assert_instant_equals(
        presentation["window_start_utc"], "2026-08-16T09:30:00Z", "window_start_utc"
    )
    assert_instant_equals(
        presentation["window_end_utc"], "2026-08-16T11:30:00Z", "window_end_utc"
    )
    return {
        "gallery": gallery,
        "representative": representative,
        "bookings": bookings,
    }


def test_a_tour_touching_the_reset_gap_finds_no_eligible_representative():
    """11:45 is exactly the busy end plus 15 minutes, and non-strict means collide.

    The PRD states: "An existing presentation window from 09:30 to 11:30 makes a
    candidate starting at 11:45 ineligible, since 11:45 is exactly the busy end
    plus 15 minutes, while a candidate starting at 11:46 remains eligible."

    Design: Difficulty/resource_temporal_overlap/representative_closed_interval_symmetric_reset_gap
    """
    scene = _one_representative_with_a_finished_morning_tour()

    rested = fx.read_representative(scene["representative"]["id"])
    assert rested["status"] == "ACTIVE"
    assert rested["tours_taken_count"] == 1

    fx.pin_clock("2026-08-16T11:45:00Z")
    refused = api.check_in_tour_booking(
        scene["bookings"][1]["id"], fac.check_in_payload(False), GALLERY
    )
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_REPRESENTATIVE.value, 409)

    unchanged = fx.read_booking(scene["bookings"][1]["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["assigned_rep_id"] is None
    assert fx.read_representative(scene["representative"]["id"])["status"] == "ACTIVE"


def test_one_minute_past_the_reset_gap_binds_the_same_representative_again():
    """The gallery admits both candidates, so only the calendar geometry separates them.

    The PRD states: "The candidate collides with that busy interval when *both*
    comparisons hold, each of them non-strict: the booking's start is at or before
    the busy end plus a 15-minute reset gap, and the busy start is at or before the
    booking's end plus the same 15-minute gap."

    Design: Difficulty/resource_temporal_overlap/representative_closed_interval_symmetric_reset_gap
    """
    scene = _one_representative_with_a_finished_morning_tour()
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 3

    fx.pin_clock("2026-08-16T11:46:00Z")
    accepted = validate_success(
        api.check_in_tour_booking(
            scene["bookings"][2]["id"], fac.check_in_payload(False), GALLERY
        )
    )
    assert accepted["status"] == "CHECKED_IN"
    assert accepted["assigned_rep_id"] == scene["representative"]["id"]

    assert fx.read_representative(scene["representative"]["id"])["status"] == "ON_TOUR"
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 3
