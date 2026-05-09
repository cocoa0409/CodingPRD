"""Locations, reservations, capacity, permits, weather, intervals.

Covers PRD §3.3 (locations, reservations, permits, weather), §2.10
(validation priority).
Difficulty design: boundary_precision_check/location_capacity_unit_exhaustion,
resource_temporal_overlap/location_overlap_half_open_interval_arithmetic,
cross_entity_state_dependency/scene_schedule_depends_on_locationreservation_state,
non_linear_state_machine/location_reservation_reschedule_branch.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_location_payload,
    create_location_reservation_payload,
    patch_permit_status_payload,
    patch_weather_status_payload,
    schedule_scene_payload,
    reschedule_scene_payload,
    setup_production_with_categories,
    create_location,
    create_scene_in_production,
    create_held_reservation,
    confirm_reservation_with_permit_and_weather,
    iso,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


def test_create_reservation_lands_in_held(api):
    """PRD §3.3: "A new reservation lands in `HELD`."

    Claim: a fresh POST /location-reservations returns status=HELD.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene["id"],
            unit_label="MAIN",
            start_at=iso(2026, 4, 1, 9),
            end_at=iso(2026, 4, 1, 17),
        ),
        PC,
    )
    reservation = validate_success(res, 201)
    assert reservation["status"] == "HELD"


def test_reservation_initial_permit_status_pending_when_required(api):
    """PRD §3.3: "Its `permit_status` is initialized to `PENDING` if the
    location's `requires_permit` is true, and `NOT_REQUIRED` otherwise."

    Claim: reservation on permit-required location → permit_status=PENDING.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, requires_permit=True)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
    )
    assert reservation["permit_status"] == "PENDING"
    assert reservation["weather_status"] == "UNKNOWN"


def test_reservation_initial_permit_not_required_when_location_does_not_require(api):
    """PRD §3.3: "Its `permit_status` is initialized to `PENDING` if the
    location's `requires_permit` is true, and `NOT_REQUIRED` otherwise."

    Claim: reservation on non-permit location → permit_status=NOT_REQUIRED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, requires_permit=False)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
    )
    assert reservation["permit_status"] == "NOT_REQUIRED"


def test_confirm_rejects_when_permit_required_but_not_approved(api):
    """PRD §3.3: "if the underlying location's `requires_permit` is true, the
    reservation's `permit_status` must equal `APPROVED` (otherwise
    `ERR_PERMIT_REQUIRED`, HTTP 409)(...)."

    # difficulty: cross_entity_state_dependency/scene_schedule_depends_on_locationreservation_state
    Claim: confirm with permit_status=PENDING on permit-required location →
    ERR_PERMIT_REQUIRED (409).
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, requires_permit=True)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
    )
    res = api.confirm_reservation(reservation["id"], PC)
    validate_error(res, "ERR_PERMIT_REQUIRED", expected_status=409)


def test_confirm_succeeds_after_permit_approved(api):
    """PRD §3.3: confirm requires permit_status == APPROVED on permit-required
    locations.

    # difficulty: cross_entity_state_dependency/scene_schedule_depends_on_locationreservation_state
    Claim: after PATCH permit_status=APPROVED, confirm succeeds and
    reservation transitions HELD→CONFIRMED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, requires_permit=True)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
    )
    validate_success(api.patch_permit_status(
        reservation["id"],
        patch_permit_status_payload(permit_status="APPROVED"),
        PC,
    ), 200)
    confirmed = validate_success(api.confirm_reservation(reservation["id"], PC), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_confirm_rejects_when_weather_blocked(api):
    """PRD §3.3: "the reservation's `weather_status` must not be `BLOCKED`
    (otherwise `ERR_WEATHER_BLOCKED`, HTTP 409)(...)."

    Claim: confirm with weather_status=BLOCKED → ERR_WEATHER_BLOCKED (409).
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, requires_permit=False)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
    )
    validate_success(api.patch_weather_status(
        reservation["id"],
        patch_weather_status_payload(weather_status="BLOCKED"),
        PC,
    ), 200)
    res = api.confirm_reservation(reservation["id"], PC)
    validate_error(res, "ERR_WEATHER_BLOCKED", expected_status=409)


def test_release_held_reservation(api):
    """PRD §3.3: "A reservation may instead be released from `HELD` to
    `RELEASED` at any time."

    Claim: release on HELD → RELEASED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
    )
    released = validate_success(api.release_reservation(reservation["id"], PC), 200)
    assert released["status"] == "RELEASED"


# ─── Interval semantics: half-open [start_at, end_at) ────────────────────────

def test_invalid_interval_start_not_before_end(api):
    """PRD §3.3: "The interval must satisfy `start_at` strictly earlier than
    `end_at`(...). Violations yield `ERR_INVALID_INTERVAL` (HTTP 422)."

    Claim: start_at == end_at → ERR_INVALID_INTERVAL.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene["id"],
            start_at=iso(2026, 4, 1, 9),
            end_at=iso(2026, 4, 1, 9),
        ),
        PC,
    )
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_invalid_interval_outside_shoot_window(api):
    """PRD §3.3: "(...) and both must fall within the production's
    `shoot_window_start` and `shoot_window_end`. Violations yield
    `ERR_INVALID_INTERVAL` (HTTP 422)."

    Claim: reservation interval entirely after shoot_window_end →
    ERR_INVALID_INTERVAL.
    """
    prod, _ = setup_production_with_categories(
        api,
        shoot_window_start=iso(2026, 1, 1),
        shoot_window_end=iso(2026, 1, 31, 23, 59, 59),
    )
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    # Interval is in February — outside the window.
    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene["id"],
            start_at=iso(2026, 2, 5, 9),
            end_at=iso(2026, 2, 5, 17),
        ),
        PC,
    )
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_adjacent_intervals_do_not_overlap_half_open(api):
    """PRD §3.3: "two reservations overlap when the half-open interval from
    each candidate's `start_at` inclusive to its `end_at` exclusive
    intersects(...)."

    # difficulty: resource_temporal_overlap/location_overlap_half_open_interval_arithmetic
    Claim: with max_parallel_units=1, two adjacent reservations [10:00,12:00)
    and [12:00,14:00) on the same location are NOT overlapping (half-open
    arithmetic) — both succeed.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, max_parallel_units=1)
    scene_a = create_scene_in_production(api, production_id=prod["id"], scene_number="S-A")
    scene_b = create_scene_in_production(api, production_id=prod["id"], scene_number="S-B")

    res_a = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_a["id"],
            unit_label="UNIT_A",
            start_at=iso(2026, 4, 1, 10),
            end_at=iso(2026, 4, 1, 12),
        ),
        PC,
    )
    a = validate_success(res_a, 201)
    assert a["status"] == "HELD"

    res_b = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_b["id"],
            unit_label="UNIT_B",
            start_at=iso(2026, 4, 1, 12),
            end_at=iso(2026, 4, 1, 14),
        ),
        PC,
    )
    b = validate_success(res_b, 201)
    assert b["status"] == "HELD"


def test_overlapping_interval_rejected_when_capacity_exhausted(api):
    """PRD §3.3: "if accepting this reservation would tie or exceed the cap,
    the create is rejected with `ERR_LOCATION_OVER_CAPACITY` (HTTP 409)."

    # difficulty: resource_temporal_overlap/location_overlap_half_open_interval_arithmetic
    Claim: with max_parallel_units=1, an overlapping interval [11:30,13:00)
    rejected against existing [10:00,12:00).
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, max_parallel_units=1)
    scene_a = create_scene_in_production(api, production_id=prod["id"], scene_number="S-A")
    scene_b = create_scene_in_production(api, production_id=prod["id"], scene_number="S-B")

    api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_a["id"],
            unit_label="UNIT_A",
            start_at=iso(2026, 4, 1, 10),
            end_at=iso(2026, 4, 1, 12),
        ),
        PC,
    )

    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_b["id"],
            unit_label="UNIT_B",
            start_at=iso(2026, 4, 1, 11, 30),
            end_at=iso(2026, 4, 1, 13),
        ),
        PC,
    )
    validate_error(res, "ERR_LOCATION_OVER_CAPACITY", expected_status=409)


def test_capacity_unit_exhaustion_zero_slot_boundary(api):
    """PRD §3.3: "The set of overlapping reservations at the same `location_id`
    (...) must contain fewer than `max_parallel_units` rows; if accepting
    this reservation would tie or exceed the cap, the create is rejected
    with `ERR_LOCATION_OVER_CAPACITY` (HTTP 409)."

    # difficulty: boundary_precision_check/location_capacity_unit_exhaustion_zero_slot_boundary
    Claim: with max_parallel_units=2 and two existing overlapping HELD
    reservations, a third overlapping reservation is rejected.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, max_parallel_units=2)
    scene_a = create_scene_in_production(api, production_id=prod["id"], scene_number="S-A")
    scene_b = create_scene_in_production(api, production_id=prod["id"], scene_number="S-B")
    scene_c = create_scene_in_production(api, production_id=prod["id"], scene_number="S-C")

    api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_a["id"],
            unit_label="MAIN",
            start_at=iso(2026, 4, 1, 9),
            end_at=iso(2026, 4, 1, 17),
        ),
        PC,
    )
    api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_b["id"],
            unit_label="B_UNIT",
            start_at=iso(2026, 4, 1, 9),
            end_at=iso(2026, 4, 1, 17),
        ),
        PC,
    )
    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_c["id"],
            unit_label="THIRD_UNIT",
            start_at=iso(2026, 4, 1, 10),
            end_at=iso(2026, 4, 1, 12),
        ),
        PC,
    )
    validate_error(res, "ERR_LOCATION_OVER_CAPACITY", expected_status=409)


def test_unit_label_must_be_unique_among_overlapping(api):
    """PRD §3.3: "The `unit_label` must be unique among all currently-
    overlapping reservations at the same location(...)."

    Claim: two overlapping reservations on the same location with
    unit_label=MAIN → second rejected with ERR_LOCATION_OVER_CAPACITY.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api, max_parallel_units=2)
    scene_a = create_scene_in_production(api, production_id=prod["id"], scene_number="S-A")
    scene_b = create_scene_in_production(api, production_id=prod["id"], scene_number="S-B")

    api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_a["id"],
            unit_label="MAIN",
            start_at=iso(2026, 4, 1, 9),
            end_at=iso(2026, 4, 1, 17),
        ),
        PC,
    )
    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod["id"],
            scene_id=scene_b["id"],
            unit_label="MAIN",  # duplicate
            start_at=iso(2026, 4, 1, 10),
            end_at=iso(2026, 4, 1, 12),
        ),
        PC,
    )
    validate_error(res, "ERR_LOCATION_OVER_CAPACITY", expected_status=409)


def test_reference_mismatch_when_scene_belongs_to_different_production(api):
    """PRD §2.5: "ERR_REFERENCE_MISMATCH (HTTP 422) is reserved for foreign-key
    fields supplied in request bodies — for instance a `LocationReservation`
    whose `scene_id` belongs to one production but is submitted under a
    `production_id` belonging to another."

    Claim: reservation body with mismatched scene_id/production_id →
    ERR_REFERENCE_MISMATCH.
    """
    prod_a, _ = setup_production_with_categories(api)
    prod_b, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene_a = create_scene_in_production(api, production_id=prod_a["id"])

    res = api.create_location_reservation(
        create_location_reservation_payload(
            location_id=location["id"],
            production_id=prod_b["id"],   # mismatch
            scene_id=scene_a["id"],
            start_at=iso(2026, 4, 1, 9),
            end_at=iso(2026, 4, 1, 17),
        ),
        PC,
    )
    validate_error(res, "ERR_REFERENCE_MISMATCH", expected_status=422)
