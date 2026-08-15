"""Buffer storage: per-day aggregate capacity, half-open adjacency, reservation
window gates, and the check-in/release inventory invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_facility,
    create_generator,
    create_reservation,
    create_storage_reservation_payload,
    create_stream,
    get_success_data,
    setup_facility_with_stream,
    validate_error,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]


def test_reservation_exceeding_daily_capacity_rejected(api):
    """PRD §3.7: "That aggregate is evaluated day by day: for each calendar day
    in the new reservation's half-open window, the system sums `tons` over all
    of the facility's existing reservations in `RESERVED` or `CHECKED_IN`
    status whose own half-open windows contain that day, and the reservation is
    rejected whenever that sum plus the new `tons` would exceed
    `capacity_tons`. A sum that merely equals capacity is allowed, and
    adjacency does not count as overlap — one reservation ending on a given day
    and another starting that same day share no day of coverage."

    Design: Difficulty/resource_temporal_overlap/storage_reservation_per_day_aggregate_capacity
    """
    ctx = setup_facility_with_stream(capacity_tons=1000)
    facility, stream = ctx["facility"], ctx["stream"]
    create_reservation(facility["id"], stream["id"],
                       start_date="2026-08-01", end_date="2026-08-10", tons=600)
    create_reservation(facility["id"], stream["id"],
                       start_date="2026-08-05", end_date="2026-08-15", tons=300)
    # Peak day total is now 900 (2026-08-05 through 2026-08-09).

    resp = api.create_storage_reservation(
        create_storage_reservation_payload(
            facility["id"], stream["id"],
            start_date="2026-08-07", end_date="2026-08-08", tons=101,
        ),
        BROKER,
    )
    validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)

    # 900 + 100 lands exactly on capacity 1000: equality is allowed.
    at_capacity = create_reservation(
        facility["id"], stream["id"],
        start_date="2026-08-07", end_date="2026-08-08", tons=100,
    )
    assert at_capacity["status"] == "RESERVED"


def test_adjacent_reservation_windows_do_not_overlap(api):
    """PRD §3.7: "A sum that merely equals capacity is allowed, and adjacency
    does not count as overlap — one reservation ending on a given day and
    another starting that same day share no day of coverage."

    Design: Difficulty/resource_temporal_overlap/storage_reservation_per_day_aggregate_capacity
    """
    ctx = setup_facility_with_stream(capacity_tons=1000)
    facility, stream = ctx["facility"], ctx["stream"]
    create_reservation(facility["id"], stream["id"],
                       start_date="2026-08-01", end_date="2026-08-10", tons=600)
    create_reservation(facility["id"], stream["id"],
                       start_date="2026-08-05", end_date="2026-08-15", tons=300)

    # Starts on the day the second reservation ends: no shared day of coverage.
    adjacent = create_reservation(
        facility["id"], stream["id"],
        start_date="2026-08-15", end_date="2026-08-20", tons=1000,
    )
    assert adjacent["status"] == "RESERVED"


def test_check_in_adds_tons_to_inventory(api):
    """PRD §3.7: "Checking material in moves it from `RESERVED` to `CHECKED_IN`
    and is only permitted within the window — the current logical date must
    fall on or after `start_date` and strictly before `end_date`, else
    `ERR_RESERVATION_WINDOW_INVALID`; check-in adds the reservation's `tons` to
    the facility's `current_inventory_tons` and advances the facility's
    `version` by one."

    Design: Difficulty/compensating_invariant/storage_check_in_release_conserves_inventory_tons
    """
    ctx = setup_facility_with_stream(capacity_tons=1000)
    facility, stream = ctx["facility"], ctx["stream"]
    assert facility["current_inventory_tons"] == pytest.approx(0)
    reservation = create_reservation(facility["id"], stream["id"], tons=400)

    # Default logical date 2026-08-01 is inside the [2026-08-01, 2026-08-10) window.
    checked_in = validate_success(
        api.check_in_storage_reservation(reservation["id"], BROKER), 200
    )
    assert checked_in["status"] == "CHECKED_IN"

    facility_after = get_success_data(api.get_storage_facility(facility["id"], BROKER))
    assert facility_after["current_inventory_tons"] == pytest.approx(400)
    assert facility_after["version"] == facility["version"] + 1


def test_release_restores_inventory_to_pre_reservation_level(api):
    """PRD §3.7: "Releasing moves a reservation from `CHECKED_IN` to terminal
    `RELEASED`, subtracting its `tons` from `current_inventory_tons` and again
    advancing the facility's `version`."
    PRD §3.7: "The facility's `current_inventory_tons` is therefore always the
    sum of `tons` across its `CHECKED_IN` reservations, and reading a facility
    reports that live figure."

    Design: Difficulty/compensating_invariant/storage_check_in_release_conserves_inventory_tons
    """
    ctx = setup_facility_with_stream(capacity_tons=1000)
    facility, stream = ctx["facility"], ctx["stream"]
    reservation = create_reservation(facility["id"], stream["id"], tons=400)
    validate_success(api.check_in_storage_reservation(reservation["id"], BROKER), 200)

    released = validate_success(
        api.release_storage_reservation(reservation["id"], BROKER), 200
    )
    assert released["status"] == "RELEASED"

    facility_after = get_success_data(api.get_storage_facility(facility["id"], BROKER))
    assert facility_after["current_inventory_tons"] == pytest.approx(0), (
        "check-in then release conserves inventory at its pre-reservation level"
    )
    assert facility_after["version"] == facility["version"] + 2


def test_reservation_material_not_accepted_returns_error(api):
    """PRD §3.7: "Two business checks follow in pipeline order: the stream's
    `material_type` must appear in the facility's `material_types_allowed`
    (else `ERR_MATERIAL_NOT_ACCEPTED`), and the per-day capacity aggregate must
    hold (else `ERR_STORAGE_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/reservation_material_not_accepted_returns_error
    """
    generator = create_generator()
    stream = create_stream(generator["id"])  # FLY_ASH
    facility = create_facility(material_types_allowed=["GYPSUM"], capacity_tons=1000)

    resp = api.create_storage_reservation(
        create_storage_reservation_payload(facility["id"], stream["id"]), BROKER
    )
    validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_ACCEPTED)


def test_reservation_inverted_window_returns_error(api):
    """PRD §3.7: "A reservation names the `facility_id` and the `stream_id` of
    the material to be stored, a half-open window from the inclusive
    `start_date` to the exclusive `end_date` — `end_date` must be after
    `start_date`, else `ERR_RESERVATION_WINDOW_INVALID` — and a strictly
    positive `tons` of committed capacity."

    Design: Corner/validations/reservation_inverted_window_returns_error
    """
    ctx = setup_facility_with_stream()
    facility, stream = ctx["facility"], ctx["stream"]

    resp = api.create_storage_reservation(
        create_storage_reservation_payload(
            facility["id"], stream["id"],
            start_date="2026-08-10", end_date="2026-08-01",
        ),
        BROKER,
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_INVALID)


def test_check_in_before_window_start_returns_error(api):
    """PRD §3.7: "Checking material in moves it from `RESERVED` to `CHECKED_IN`
    and is only permitted within the window — the current logical date must
    fall on or after `start_date` and strictly before `end_date`, else
    `ERR_RESERVATION_WINDOW_INVALID`"

    Design: Corner/validations/check_in_before_window_start_returns_error
    """
    ctx = setup_facility_with_stream()
    facility, stream = ctx["facility"], ctx["stream"]
    reservation = create_reservation(
        facility["id"], stream["id"],
        start_date="2026-08-10", end_date="2026-08-20", tons=100,
    )

    # Default logical date 2026-08-01 is before the window start.
    resp = api.check_in_storage_reservation(reservation["id"], BROKER)
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_INVALID)

    facility_after = get_success_data(api.get_storage_facility(facility["id"], BROKER))
    assert facility_after["current_inventory_tons"] == pytest.approx(0), (
        "a rejected check-in must not change inventory"
    )
