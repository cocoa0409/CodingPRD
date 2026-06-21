"""Composite setup helpers.

Each test runs against a freshly-launched empty server, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Helpers use the
lenient get_success_data() validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_course_payload,
    create_golfer_payload,
    create_score_payload,
    create_tee_time_payload,
    create_booking_payload,
    create_handicap_revision_payload,
)
from .test_users import make_proshop_headers, make_golfer_headers


# A clock instant safe for the standard future-dated slots used below.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Set the server clock as ProShop."""
    return get_success_data(api_client.set_clock(to_iso8601, make_proshop_headers()))


def create_course(**overrides) -> dict:
    """Create a Course as ProShop. Returns the Course object."""
    return get_success_data(
        api_client.create_course(create_course_payload(**overrides), make_proshop_headers())
    )


def create_golfer(**overrides) -> dict:
    """Register a Golfer as ProShop. Returns the Golfer object."""
    return get_success_data(
        api_client.create_golfer(create_golfer_payload(**overrides), make_proshop_headers())
    )


def create_tee_time(course_id, start_utc, local_hour, group_type, **overrides) -> dict:
    """Publish a TeeTime as ProShop. Returns the TeeTime object."""
    return get_success_data(
        api_client.create_tee_time(
            create_tee_time_payload(course_id, start_utc, local_hour, group_type, **overrides),
            make_proshop_headers(),
        )
    )


def post_score(golfer_id, course_id, played_on, adjusted_gross_score, **overrides) -> dict:
    """Post a Score as ProShop. Returns the Score object."""
    return get_success_data(
        api_client.create_score(
            create_score_payload(golfer_id, course_id, played_on, adjusted_gross_score, **overrides),
            make_proshop_headers(),
        )
    )


def void_score(score_id) -> dict:
    """Void a Score as ProShop. Returns the updated Score object."""
    return get_success_data(api_client.void_score(score_id, make_proshop_headers()))


def run_refresh(effective_utc) -> dict:
    """Run a monthly handicap refresh as ProShop. Returns the HandicapRevision object."""
    return get_success_data(
        api_client.create_handicap_revision(
            create_handicap_revision_payload(effective_utc), make_proshop_headers()
        )
    )


def book_as_golfer(tee_time_id, golfer_id, expected_version, **overrides) -> dict:
    """Create a booking acting as the owning Golfer (identity threaded from golfer_id).
    Returns the Booking object."""
    return get_success_data(
        api_client.create_booking(
            tee_time_id,
            create_booking_payload(golfer_id, expected_version, **overrides),
            make_golfer_headers(golfer_id),
        )
    )


def cancel_as_golfer(booking_id, golfer_id) -> dict:
    """Cancel a booking acting as the owning Golfer. Returns the updated Booking."""
    return get_success_data(
        api_client.cancel_booking(booking_id, make_golfer_headers(golfer_id))
    )


def fetch_tee_time(tee_time_id) -> dict:
    return get_success_data(api_client.get_tee_time(tee_time_id, make_proshop_headers()))


def fetch_booking(booking_id) -> dict:
    return get_success_data(api_client.get_booking(booking_id, make_proshop_headers()))


def fetch_golfer(golfer_id) -> dict:
    return get_success_data(api_client.get_golfer(golfer_id, make_proshop_headers()))


def fetch_score(score_id) -> dict:
    return get_success_data(api_client.get_score(score_id, make_proshop_headers()))


# ---------------------------------------------------------------------------
# Tier 2/3: Composite hierarchies for the booking workflows
# ---------------------------------------------------------------------------

def setup_course_and_golfer(course_overrides=None, golfer_overrides=None, set_clock_to=DEFAULT_CLOCK):
    """Clock + one Course + one Golfer. Returns (course, golfer)."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    course = create_course(**(course_overrides or {}))
    golfer = create_golfer(**(golfer_overrides or {}))
    return course, golfer


def setup_open_slot(course_overrides=None, group_type="FOURSOME",
                    start_utc="2026-06-20T09:00:00Z", local_hour=9, set_clock_to=DEFAULT_CLOCK):
    """Clock + Course + one OPEN TeeTime. Returns (course, tee_time)."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    course = create_course(**(course_overrides or {}))
    tee_time = create_tee_time(course["id"], start_utc, local_hour, group_type)
    return course, tee_time


def setup_confirmed_booking(course_overrides=None, group_type="FOURSOME",
                            start_utc="2026-06-20T09:00:00Z", local_hour=9,
                            membership_tier="PUBLIC", set_clock_to=DEFAULT_CLOCK):
    """Clock + Course + Golfer + OPEN slot + one CONFIRMED booking.
    Returns (course, golfer, tee_time, booking)."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    course = create_course(**(course_overrides or {}))
    golfer = create_golfer(membership_tier=membership_tier)
    tee_time = create_tee_time(course["id"], start_utc, local_hour, group_type)
    booking = book_as_golfer(tee_time["id"], golfer["id"], tee_time["version"])
    return course, golfer, tee_time, booking


def setup_full_twosome(course_overrides=None, start_utc="2026-06-20T09:00:00Z",
                       local_hour=9, set_clock_to=DEFAULT_CLOCK):
    """Clock + Course + a TWOSOME slot filled to capacity by two PUBLIC golfers (GA, GB).
    Returns (course, tee_time, golfer_a, golfer_b, booking_a, booking_b)."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    course = create_course(**(course_overrides or {}))
    ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
    gb = create_golfer(full_name="GB", membership_tier="PUBLIC")
    tt = create_tee_time(course["id"], start_utc, local_hour, "TWOSOME")
    bk_a = book_as_golfer(tt["id"], ga["id"], tt["version"])
    tt_after_a = fetch_tee_time(tt["id"])
    bk_b = book_as_golfer(tt["id"], gb["id"], tt_after_a["version"])
    return course, tt, ga, gb, bk_a, bk_b


def add_standby(tee_time_id, golfer):
    """Join the given golfer to a slot's standby queue. Returns the standby Booking."""
    tt = fetch_tee_time(tee_time_id)
    return book_as_golfer(tee_time_id, golfer["id"], tt["version"], join_standby=True)
