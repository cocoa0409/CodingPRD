"""The adaptive equipment cage: fit, inspection, availability and holds."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_equipment_unit_conservation,
    create_active_participant,
    create_equipment_item,
    create_fee_band,
    create_open_session,
    item_version,
    read_equipment_item,
    read_reservation,
    record_inspection,
    request_enrollment,
    reserve_equipment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORD

TRIKE_PROGRAM = {
    "name": "Adaptive Trike Club",
    "activity_type": "SPORTS",
    "required_equipment_model_code": "TRIKE_ADAPT",
    "required_equipment_size_code": "M",
}
GRIP_PROGRAM = {
    "name": "Adaptive Rowing",
    "activity_type": "SPORTS",
    "required_equipment_model_code": "GRIP_AID",
    "required_equipment_size_code": "M",
}


def _weight_boundary_fixture():
    """Two serialized trikes rated 40 kg and 39 kg, and a 40 kg participant."""
    create_fee_band()
    _program, session = create_open_session(program_overrides=TRIKE_PROGRAM)
    fitting = create_equipment_item(
        weight_capacity_kg=40, serial_number="TA-0001", inspection_due_date="2026-12-31"
    )
    too_small = create_equipment_item(
        weight_capacity_kg=39, serial_number="TA-0002", inspection_due_date="2026-12-31"
    )
    who = create_active_participant(weight_kg=40)
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    return session, fitting, too_small, enrollment


def test_equipment_capacity_equal_to_participant_weight_fits():
    """PRD §2.10 rung 49: "**Sub-gate D, head rung.** On equipment-reservation
    creation, and on the confirmation/promotion walk when the programme declares
    a `required_equipment_model_code`, the item's `model_code` and `size_code`
    match the programme's requirement and its `weight_capacity_kg` is at least
    the participant's `weight_kg` — otherwise `ERR_EQUIPMENT_FIT_MISMATCH` (422).
    Equal capacity fits."
    PRD §3.6: "On success the reservation is filed in `status` `HELD` with
    `return_condition` null, the item's `pooled_held` rises by one and
    `pooled_available` falls by one, and the item's `version` rises by one."

    Design: Difficulty/boundary_precision_check/equipment_weight_capacity_equal_to_participant_weight_fits
    """
    _session, fitting, _too_small, enrollment = _weight_boundary_fixture()

    reservation = reserve_equipment(enrollment["id"], fitting["id"])
    assert reservation["status"] == "HELD"

    item = read_equipment_item(fitting["id"])
    assert item["pooled_held"] == 1
    assert item["pooled_available"] == 0
    assert_equipment_unit_conservation(item)


def test_equipment_capacity_one_kilogram_short_is_a_fit_mismatch():
    """PRD §3.6: "The **fit** condition: the item's `model_code` equals the
    programme's `required_equipment_model_code`, its `size_code` equals the
    programme's `required_equipment_size_code` exactly, and its
    `weight_capacity_kg` is greater than or equal to the participant's
    `weight_kg`. The weight tolerance is zero, so a participant of 90 kilograms
    fits a chair rated at exactly 90 and does not fit one rated at 89."
    PRD §3.6: "The three sub-gate D rungs are evaluated in order against the
    item: a fit failure is `ERR_EQUIPMENT_FIT_MISMATCH`, a condition or
    inspection failure is `ERR_EQUIPMENT_INSPECTION_OVERDUE`, and an availability
    failure is `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/equipment_weight_capacity_equal_to_participant_weight_fits
    """
    _session, _fitting, too_small, enrollment = _weight_boundary_fixture()

    validate_error(
        api_client.create_equipment_reservation(
            {
                "enrollment_id": enrollment["id"],
                "equipment_item_id": too_small["id"],
                "expected_item_version": item_version(too_small["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_EQUIPMENT_FIT_MISMATCH.value,
        expected_status=422,
    )

    item = read_equipment_item(too_small["id"])
    assert item["pooled_held"] == 0
    assert item["pooled_available"] == 1


def _three_enrollments_and_two_kinds_of_item():
    create_fee_band()
    _program, session = create_open_session(
        program_overrides=GRIP_PROGRAM, slot_capacity=3
    )
    pooled = create_equipment_item(
        item_kind="POOLED", model_code="GRIP_AID", size_code="M", weight_capacity_kg=100,
        pooled_total=2, serial_number=None, inspection_due_date=None,
    )
    serialized = create_equipment_item(
        model_code="GRIP_AID", size_code="M", weight_capacity_kg=100,
        serial_number="GA-0001", inspection_due_date="2026-12-31", pooled_total=1,
    )
    people = [
        ("Ada Rivera", "2010-03-04", "HH-1", 40),
        ("Ben Osei", "2009-07-15", "HH-2", 45),
        ("Cleo Vance", "2008-11-02", "HH-3", 50),
    ]
    enrollments = []
    for name, dob, household, weight in people:
        who = create_active_participant(
            legal_name=name, date_of_birth=dob, household_id=household, weight_kg=weight
        )
        enrollments.append(request_enrollment(who["participant"]["id"], session["id"]))
    return pooled, serialized, enrollments


def test_pooled_item_admits_two_concurrent_holds_and_refuses_the_third():
    """PRD §3.6: "A `POOLED` row is a bag of fungible units tracked only by
    count: its `serial_number` and `inspection_due_date` are both null, and its
    `pooled_total` is the number of units held, which must be at least 1."
    PRD §3.6: "And the **availability** condition: `pooled_available` is at least
    1. That last predicate carries two different occupancy semantics under one
    formula — for a serialized unit, whose `pooled_total` is 1, it means
    exclusive possession; for a pooled row it means aggregate capacity up to
    `pooled_total` concurrent holds."

    Design: Difficulty/resource_temporal_overlap/pooled_item_admits_two_concurrent_holds_serialized_item_admits_one
    """
    pooled, _serialized, enrollments = _three_enrollments_and_two_kinds_of_item()

    first = reserve_equipment(enrollments[0]["id"], pooled["id"])
    second = reserve_equipment(enrollments[1]["id"], pooled["id"])
    assert first["status"] == "HELD"
    assert second["status"] == "HELD"

    item = read_equipment_item(pooled["id"])
    assert item["pooled_held"] == 2
    assert item["pooled_available"] == 0
    assert_equipment_unit_conservation(item)

    validate_error(
        api_client.create_equipment_reservation(
            {
                "enrollment_id": enrollments[2]["id"],
                "equipment_item_id": pooled["id"],
                "expected_item_version": item_version(pooled["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value,
        expected_status=409,
    )


def test_serialized_item_admits_exactly_one_hold():
    """PRD §3.6: "A `SERIALIZED` row is one physical unit with an identity and an
    inspection cycle: it carries a `serial_number` and an `inspection_due_date`,
    both required for this kind, and its `pooled_total` is 1."
    PRD §2.10 rung 51: "**Sub-gate D, continued.** The item's `pooled_available`
    is at least 1 — otherwise `ERR_EQUIPMENT_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/pooled_item_admits_two_concurrent_holds_serialized_item_admits_one
    """
    _pooled, serialized, enrollments = _three_enrollments_and_two_kinds_of_item()

    held = reserve_equipment(enrollments[0]["id"], serialized["id"])
    assert held["status"] == "HELD"
    item = read_equipment_item(serialized["id"])
    assert item["pooled_held"] == 1
    assert item["pooled_available"] == 0

    validate_error(
        api_client.create_equipment_reservation(
            {
                "enrollment_id": enrollments[1]["id"],
                "equipment_item_id": serialized["id"],
                "expected_item_version": item_version(serialized["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value,
        expected_status=409,
    )


def test_inspection_failure_voids_the_items_held_reservations():
    """PRD §3.6: "`FAIL` is accepted from `SERVICEABLE` and from `INSPECTION_DUE`
    and lands on `OUT_OF_SERVICE`."
    PRD §3.6: "Hop 2, caused by hop 1, moves every reservation on that item whose
    status is `HELD` to `VOIDED_INSPECTION_FAIL`. Hop 3, caused by hop 2, lowers
    `pooled_held` once per voided reservation and recomputes `pooled_available`
    accordingly."

    Design: Corner/state_machines/inspection_failure_voids_the_items_held_reservations
    """
    create_fee_band()
    _program, session = create_open_session(program_overrides=TRIKE_PROGRAM)
    item = create_equipment_item(
        weight_capacity_kg=100, serial_number="TA-0001", inspection_due_date="2026-12-31"
    )
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    reservation = reserve_equipment(enrollment["id"], item["id"])

    after_fail = record_inspection(item["id"], "FAIL")
    assert after_fail["condition_status"] == "OUT_OF_SERVICE"

    assert read_reservation(reservation["id"])["status"] == "VOIDED_INSPECTION_FAIL"
    refreshed = read_equipment_item(item["id"])
    assert refreshed["pooled_held"] == 0
    assert refreshed["pooled_available"] == 1
    assert refreshed["pooled_checked_out"] == 0
    assert_equipment_unit_conservation(refreshed)


def test_overdue_inspection_blocks_the_equipment_reservation():
    """PRD §2.10 rung 50: "**Sub-gate D, continued.** For a `SERIALIZED` item, its
    `condition_status` is `SERVICEABLE` and its `inspection_due_date` is on or
    after the session's date — otherwise `ERR_EQUIPMENT_INSPECTION_OVERDUE`
    (409). Pooled items skip the inspection clause. This rung also guards
    equipment check-out."
    PRD §3.6: "The **inspection** condition: either the item is `POOLED`, which
    has no inspection cycle at all, or its `inspection_due_date` falls on or
    after the session's calendar date."

    Design: Corner/validations/overdue_inspection_blocks_the_equipment_reservation
    """
    create_fee_band()
    _program, session = create_open_session(program_overrides=TRIKE_PROGRAM)
    item = create_equipment_item(
        weight_capacity_kg=100, serial_number="TA-0003", inspection_due_date="2026-06-01"
    )
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    validate_error(
        api_client.create_equipment_reservation(
            {
                "enrollment_id": enrollment["id"],
                "equipment_item_id": item["id"],
                "expected_item_version": item_version(item["id"]),
            },
            COORD,
        ),
        ApiErrorId.ERR_EQUIPMENT_INSPECTION_OVERDUE.value,
        expected_status=409,
    )

    refreshed = read_equipment_item(item["id"])
    assert refreshed["condition_status"] == "SERVICEABLE", (
        "a rejected reservation must not take the item out of service"
    )
    assert refreshed["pooled_held"] == 0
    assert refreshed["pooled_available"] == 1
    _rows, meta = validate_paginated(
        api_client.list_equipment_reservations(
            ADMIN, params={"enrollment_id": enrollment["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_stale_equipment_item_version_rejects_the_second_reservation():
    """PRD §2.9: "Creating an equipment reservation
    (`POST /recreation/equipment-reservations`) must carry `expected_item_version`
    matching the current `version` of the `EquipmentItem` named by
    `equipment_item_id`. That version advances on every hold, check-out, return,
    release, inspection and condition change."
    PRD §2.9: "If the echoed number is not equal to the parent's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is written."

    Design: Corner/cross_cutting_complexity_layers/stale_equipment_item_version_rejects_the_second_reservation
    """
    create_fee_band()
    _program, session = create_open_session(program_overrides=GRIP_PROGRAM)
    item = create_equipment_item(
        item_kind="POOLED", model_code="GRIP_AID", size_code="M", weight_capacity_kg=100,
        pooled_total=2, serial_number=None, inspection_due_date=None,
    )
    stale_version = item["version"]
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    first = validate_success(
        api_client.create_equipment_reservation(
            {
                "enrollment_id": enrollment["id"],
                "equipment_item_id": item["id"],
                "expected_item_version": stale_version,
            },
            COORD,
        ),
        expected_status=201,
    )
    assert first["status"] == "HELD"

    validate_error(
        api_client.create_equipment_reservation(
            {
                "enrollment_id": enrollment["id"],
                "equipment_item_id": item["id"],
                "expected_item_version": stale_version,
            },
            COORD,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )

    refreshed = read_equipment_item(item["id"])
    assert refreshed["pooled_held"] == 1
    assert refreshed["pooled_available"] == 1
