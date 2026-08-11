"""Getting there: runs, the two independent position pools, and fares."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_position_pool_conservation,
    book_position,
    cancel_session,
    charge_for,
    confirm_enrollment,
    create_active_participant,
    create_fee_band,
    create_open_session,
    create_transport_run,
    read_booking,
    read_enrollment,
    read_session,
    read_transport_run,
    request_enrollment,
    run_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, DISPATCH


def _boarding_full_run_on_a_one_slot_session():
    """A confirmed wheelchair rider holding the run's only accessible position.

    The run is created before the confirmation because sub-gate E consults the
    runs serving the session, and the booking is placed before the confirmation
    so the position is already committed to that enrolment.
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={"name": "Inclusive Bowling", "activity_type": "SPORTS"},
        slot_capacity=1,
    )
    who = create_active_participant(mobility_profile="WHEELCHAIR")
    run = create_transport_run(
        session["id"],
        pickup_start_at="2026-06-10T13:00:00Z",
        pickup_end_at="2026-06-10T13:45:00Z",
        fare_mode="FLAT",
        flat_fare_cents=1000,
        route_miles_x10=0,
        accessible_positions=1,
        ambulatory_seats=0,
    )
    enrollment = request_enrollment(
        who["participant"]["id"], session["id"], transport_requested=True
    )
    booking = book_position(run["id"], enrollment["id"], "ACCESSIBLE")
    enrollment = confirm_enrollment(enrollment["id"])
    return session, run, enrollment, booking


def test_session_cancel_withdraws_the_enrollment_and_cancels_its_booking():
    """PRD §3.1: "Hop 2, caused by hop 1, withdraws every enrolment on the session
    whose `enrollment_status` is `REQUESTED`, `WAITLISTED` or `CONFIRMED`;
    `slots_committed` and `one_to_one_committed` fall to 0 and `slots_available`
    and `one_to_one_available` are restored to their full pool sizes. Hop 3,
    caused by hop 2, cancels every transport booking of those enrolments whose
    status is `RESERVED` or `CONFIRMED`."

    Design: Difficulty/transitive_cascade/session_cancel_cascade_reaches_the_transport_run_counters
    """
    session, run, enrollment, booking = _boarding_full_run_on_a_one_slot_session()
    assert read_transport_run(run["id"])["status"] == "BOARDING_FULL"

    cancelled = cancel_session(session["id"])

    assert cancelled["status"] == "CANCELLED"
    assert read_enrollment(enrollment["id"])["enrollment_status"] == "WITHDRAWN"
    assert read_booking(booking["id"])["status"] == "CANCELLED"

    after_session = read_session(session["id"])
    assert after_session["slots_committed"] == 0
    assert after_session["slots_available"] == 1


def test_session_cancel_restores_the_accessible_pool_and_leaves_the_other_alone():
    """PRD §3.1: "Hop 4, caused by hop 3, decrements on each affected run either
    `accessible_committed` or `ambulatory_committed` — never both — restores the
    matching available counter, and moves a run that was `BOARDING_FULL` back to
    `PLANNED` as soon as either available counter rises above 0."
    PRD §3.3: "The charge is `VOIDED` when its enrolment's `enrollment_status` is
    `WITHDRAWN` or `DENIED`."

    Design: Difficulty/transitive_cascade/session_cancel_cascade_reaches_the_transport_run_counters
    """
    session, run, enrollment, _booking = _boarding_full_run_on_a_one_slot_session()

    before = read_transport_run(run["id"])
    assert before["status"] == "BOARDING_FULL"
    assert before["accessible_committed"] == 1
    assert before["accessible_available"] == 0

    cancel_session(session["id"])

    after = read_transport_run(run["id"])
    assert after["accessible_committed"] == 0
    assert after["accessible_available"] == 1
    assert after["ambulatory_committed"] == 0
    assert after["ambulatory_available"] == 0, "the other pool is never touched"
    assert_position_pool_conservation(after)
    assert charge_for(enrollment["id"])["status"] == "VOIDED"


def test_zone_mileage_fare_rounds_half_up_before_the_accessible_surcharge():
    """PRD §3.7: "Under the `ZONE_MILEAGE` variant `flat_fare_cents` plays no
    part; instead take the base fare of 300 cents multiplied by ten, add 85 cents
    multiplied by the run's `route_miles_x10`, divide the whole sum by ten, round
    half up to a whole cent, and only then add the surcharge."
    PRD §3.7: "A surcharge of 250 cents applies when and only when the
    `position_type` is `ACCESSIBLE`, and it is added **after** any rounding."
    PRD §3.7: "Immediately afterwards, a run whose `status` is `PLANNED` and
    whose `accessible_available` **and** `ambulatory_available` have **both**
    reached 0 moves to `BOARDING_FULL` — a run with one pool empty and the other
    still open stays `PLANNED`."

    Design: Corner/calculations/zone_mileage_fare_rounds_half_up_before_the_accessible_surcharge
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=3)
    wheelchair = create_active_participant(mobility_profile="WHEELCHAIR")
    ambulatory = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45,
        mobility_profile="AMBULATORY",
    )
    wheelchair_enrollment = request_enrollment(
        wheelchair["participant"]["id"], session["id"], transport_requested=True
    )
    ambulatory_enrollment = request_enrollment(
        ambulatory["participant"]["id"], session["id"], transport_requested=True
    )
    run = create_transport_run(
        session["id"],
        fare_mode="ZONE_MILEAGE",
        flat_fare_cents=0,
        route_miles_x10=73,
        accessible_positions=1,
        ambulatory_seats=1,
    )

    seat = book_position(run["id"], ambulatory_enrollment["id"], "AMBULATORY")
    assert seat["fare_cents"] == 921, (
        "(3000 + 85 * 73) / 10 is 920.5, which rounds half up to 921; "
        f"got {seat['fare_cents']}"
    )

    position = book_position(run["id"], wheelchair_enrollment["id"], "ACCESSIBLE")
    assert position["fare_cents"] == 1171, (
        f"921 plus the 250-cent accessible surcharge is 1171; got {position['fare_cents']}"
    )

    after = read_transport_run(run["id"])
    assert after["accessible_committed"] == 1
    assert after["ambulatory_committed"] == 1
    assert after["status"] == "BOARDING_FULL"


def test_transport_booking_rungs_reject_mismatch_window_and_full_seats():
    """PRD §2.10 rung 52: "**Sub-gate E, head rung.** On transport-booking
    creation, the requested `position_type` matches the participant's
    `mobility_profile` exactly — `WHEELCHAIR` requires `ACCESSIBLE` and
    `AMBULATORY` requires `AMBULATORY` — otherwise `ERR_POSITION_TYPE_MISMATCH`
    (422)."
    PRD §3.7: "Then the window rung: the run's `pickup_end_at` must fall at or
    before the session's `start_at` less a 15-minute arrival buffer, and its
    `pickup_start_at` must fall strictly before its `pickup_end_at`; equality
    exactly at the buffer boundary is accepted, and a violation is
    `ERR_TRANSPORT_WINDOW_MISMATCH`."
    PRD §3.7: "an accessible booking needs `accessible_available` of at least 1
    or fails with `ERR_ACCESSIBLE_POSITIONS_FULL`, and an ambulatory booking
    needs `ambulatory_available` of at least 1 or fails with
    `ERR_AMBULATORY_SEATS_FULL`."

    Design: Corner/validations/transport_booking_rungs_reject_mismatch_window_and_full_seats
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=3)
    wheelchair = create_active_participant(mobility_profile="WHEELCHAIR")
    ambulatory = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45,
        mobility_profile="AMBULATORY",
    )
    wheelchair_enrollment = request_enrollment(
        wheelchair["participant"]["id"], session["id"], transport_requested=True
    )
    ambulatory_enrollment = request_enrollment(
        ambulatory["participant"]["id"], session["id"], transport_requested=True
    )
    on_time = create_transport_run(
        session["id"],
        pickup_start_at="2026-06-10T13:00:00Z",
        pickup_end_at="2026-06-10T13:45:00Z",
        accessible_positions=1,
        ambulatory_seats=0,
    )
    too_late = create_transport_run(
        session["id"],
        pickup_start_at="2026-06-10T13:00:00Z",
        pickup_end_at="2026-06-10T13:46:00Z",
        accessible_positions=1,
        ambulatory_seats=1,
    )

    validate_error(
        api_client.create_transport_booking(
            {
                "transport_run_id": on_time["id"],
                "enrollment_id": wheelchair_enrollment["id"],
                "position_type": "AMBULATORY",
                "expected_run_version": run_version(on_time["id"]),
            },
            DISPATCH,
        ),
        ApiErrorId.ERR_POSITION_TYPE_MISMATCH.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_transport_booking(
            {
                "transport_run_id": too_late["id"],
                "enrollment_id": wheelchair_enrollment["id"],
                "position_type": "ACCESSIBLE",
                "expected_run_version": run_version(too_late["id"]),
            },
            DISPATCH,
        ),
        ApiErrorId.ERR_TRANSPORT_WINDOW_MISMATCH.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_transport_booking(
            {
                "transport_run_id": on_time["id"],
                "enrollment_id": ambulatory_enrollment["id"],
                "position_type": "AMBULATORY",
                "expected_run_version": run_version(on_time["id"]),
            },
            DISPATCH,
        ),
        ApiErrorId.ERR_AMBULATORY_SEATS_FULL.value,
        expected_status=409,
    )

    unchanged = read_transport_run(on_time["id"])
    assert unchanged["accessible_available"] == 1
    assert unchanged["ambulatory_available"] == 0
    _rows, meta = validate_paginated(
        api_client.list_transport_bookings(
            ADMIN, params={"transport_run_id": on_time["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_stale_transport_run_version_rejects_the_second_booking():
    """PRD §2.9: "Creating a transport booking
    (`POST /recreation/transport-bookings`) must carry `expected_run_version`
    matching the current `version` of the `TransportRun` named by
    `transport_run_id`. Because the accessible and ambulatory counters move
    independently, a stale version leaves the client unable to know which of the
    two pools it is competing for."
    PRD §2.9: "If the echoed number is not equal to the parent's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is written."

    Design: Corner/cross_cutting_complexity_layers/stale_transport_run_version_rejects_the_second_booking
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=3)
    wheelchair = create_active_participant(mobility_profile="WHEELCHAIR")
    ambulatory = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45,
        mobility_profile="AMBULATORY",
    )
    wheelchair_enrollment = request_enrollment(
        wheelchair["participant"]["id"], session["id"], transport_requested=True
    )
    ambulatory_enrollment = request_enrollment(
        ambulatory["participant"]["id"], session["id"], transport_requested=True
    )
    run = create_transport_run(session["id"], accessible_positions=1, ambulatory_seats=1)
    stale_version = run["version"]

    first = validate_success(
        api_client.create_transport_booking(
            {
                "transport_run_id": run["id"],
                "enrollment_id": wheelchair_enrollment["id"],
                "position_type": "ACCESSIBLE",
                "expected_run_version": stale_version,
            },
            DISPATCH,
        ),
        expected_status=201,
    )
    assert first["position_type"] == "ACCESSIBLE"

    validate_error(
        api_client.create_transport_booking(
            {
                "transport_run_id": run["id"],
                "enrollment_id": ambulatory_enrollment["id"],
                "position_type": "AMBULATORY",
                "expected_run_version": stale_version,
            },
            DISPATCH,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )

    retry = validate_success(
        api_client.create_transport_booking(
            {
                "transport_run_id": run["id"],
                "enrollment_id": ambulatory_enrollment["id"],
                "position_type": "AMBULATORY",
                "expected_run_version": run_version(run["id"]),
            },
            DISPATCH,
        ),
        expected_status=201,
    )
    assert retry["position_type"] == "AMBULATORY"

    after = read_transport_run(run["id"])
    assert after["accessible_committed"] == 1
    assert after["ambulatory_committed"] == 1
    assert after["status"] == "BOARDING_FULL"
