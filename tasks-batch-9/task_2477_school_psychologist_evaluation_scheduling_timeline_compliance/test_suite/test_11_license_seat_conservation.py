"""Seat assignment and seat release as a forward action and its compensator."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    SeatStatus,
    api_client,
    assert_license_seat_conservation,
    assert_scoring_license_seat,
    fixtures,
    is_iso8601_timestamp,
    license_seat_payload,
)
from test_helpers.test_users import TEST_USERS

SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]


def _instrument_with_both_seats_taken():
    """Two of two seats handed out, leaving a third psychologist waiting."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Pinecrest Middle",
        building_code="PC18",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=600,
    )
    holder_a = fixtures.create_psychologist(
        [school["id"]],
        full_name="Omar Diaz",
        employee_number="E-1016",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    holder_b = fixtures.create_psychologist(
        [school["id"]],
        full_name="Pia Lund",
        employee_number="E-1017",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    waiting = fixtures.create_psychologist(
        [school["id"]],
        full_name="Quinn Ahmed",
        employee_number="E-1018",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    instrument = fixtures.create_instrument(
        name="BASC-3",
        instrument_code="BASC3",
        protocol_stock_count=6,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1200,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    seat_a = fixtures.assign_license_seat(instrument["id"], holder_a["id"])
    seat_b = fixtures.assign_license_seat(instrument["id"], holder_b["id"])
    return instrument, seat_a, seat_b, waiting


def test_an_exhausted_pool_refuses_the_next_seat():
    """Both seats out means the free count is zero and the invariant reads 2 = 2 + 0.

    "For every instrument, the sum of the seats currently in `ASSIGNED` status plus `license_seats_free` equals `license_seat_total`."

    Design: Difficulty/compensating_invariant/license_seat_release_restores_seat_conservation
    """
    instrument, _, _, waiting = _instrument_with_both_seats_taken()

    before = fixtures.get_instrument(instrument["id"])
    assert before["license_seat_total"] == 2
    assert before["license_seats_free"] == 0
    assert_license_seat_conservation(before, fixtures.instrument_seats(instrument["id"]))

    response = api_client.assign_license_seat(
        instrument["id"], license_seat_payload(waiting["id"]), SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_LICENSE_SEATS_EXHAUSTED.value, 409)
    assert len(fixtures.instrument_seats(instrument["id"])) == 2
    assert fixtures.psychologist_seats(waiting["id"]) == []


def test_releasing_one_seat_raises_the_free_count_by_exactly_one():
    """The compensating action returns one unit of capacity and no more.

    "Releasing a seat moves it `ASSIGNED → RELEASED`, stamps `released_at` with the current clock instant, and raises the instrument's free-seat count by one, conserving `license_seat_total` as described in §2.12."

    Design: Difficulty/compensating_invariant/license_seat_release_restores_seat_conservation
    """
    instrument, seat_a, seat_b, _ = _instrument_with_both_seats_taken()

    released = fixtures.release_license_seat(instrument["id"], seat_a["id"])

    assert_scoring_license_seat(released)
    assert released["status"] == SeatStatus.RELEASED.value
    assert is_iso8601_timestamp(released["released_at"])

    after = fixtures.get_instrument(instrument["id"])
    assert after["license_seats_free"] == 1
    seats = fixtures.instrument_seats(instrument["id"])
    assert_license_seat_conservation(after, seats)

    # Releasing one seat never disturbs the other holder.
    still_held = {row["id"]: row for row in seats}[seat_b["id"]]
    assert still_held["status"] == SeatStatus.ASSIGNED.value
    assert still_held["released_at"] is None


def test_the_freed_seat_is_immediately_re_assignable_and_no_row_is_deleted():
    """The pool refills, the invariant holds again, and three rows survive.

    "Seats are never deleted — the population of `ASSIGNED` plus `RELEASED` seats only grows — and only `ASSIGNED` seats occupy capacity."

    Design: Difficulty/compensating_invariant/license_seat_release_restores_seat_conservation
    """
    instrument, seat_a, _, waiting = _instrument_with_both_seats_taken()
    fixtures.release_license_seat(instrument["id"], seat_a["id"])

    response = api_client.assign_license_seat(
        instrument["id"], license_seat_payload(waiting["id"]), SUPERVISOR
    )

    fresh_seat = validate_success(response, 201)
    assert fresh_seat["status"] == SeatStatus.ASSIGNED.value
    assert fresh_seat["psychologist_id"] == waiting["id"]
    assert fresh_seat["id"] != seat_a["id"]

    after = fixtures.get_instrument(instrument["id"])
    assert after["license_seats_free"] == 0

    seats = fixtures.instrument_seats(instrument["id"])
    assert len(seats) == 3
    assert sorted(row["status"] for row in seats) == [
        SeatStatus.ASSIGNED.value,
        SeatStatus.ASSIGNED.value,
        SeatStatus.RELEASED.value,
    ]
    assert_license_seat_conservation(after, seats)
