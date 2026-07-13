"""Reservation preconditions, bed conservation, OCC, and shelter terminal lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NONEXISTENT_UUID,
    create_incident, create_active_incident, create_zone, order_zone,
    create_shelter, create_registrant, create_assignment, set_shelter_status,
    TEST_USERS,
)

COMMANDER = TEST_USERS["commander_headers"]
SHELTER = TEST_USERS["shelter_headers"]


def test_assignment_create_zone_none_rejected(api):
    """PRD 3.4: "The household's owning zone must be under order — its `order_level` must be `VOLUNTARY` or `MANDATORY` — otherwise the reservation is rejected with `ERR_ZONE_NOT_UNDER_ORDER`."

    Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_zone_under_order
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])  # left at order_level NONE
    shelter = create_shelter(inc["id"], physical_capacity=10)
    reg = create_registrant(zone["id"], party_size=2)

    resp = api.create_shelter_assignment(
        {"registrant_id": reg["id"], "shelter_id": shelter["id"],
         "expected_registrant_version": reg["version"]},
        SHELTER,
    )
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_UNDER_ORDER)


def test_assignment_create_zone_under_order_succeeds(api):
    """PRD 3.4: "The household's owning zone must be under order — its `order_level` must be `VOLUNTARY` or `MANDATORY` — otherwise the reservation is rejected with `ERR_ZONE_NOT_UNDER_ORDER`."
    PRD 3.4: "On success the new assignment copies the household's `party_size` (this is the bed count it consumes), begins `RESERVED`, adds that `party_size` to the shelter's `reserved_beds`"

    Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_zone_under_order
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    shelter = create_shelter(inc["id"], physical_capacity=10)
    reg = create_registrant(zone["id"], party_size=2)

    data = validate_success(
        api.create_shelter_assignment(
            {"registrant_id": reg["id"], "shelter_id": shelter["id"],
             "expected_registrant_version": reg["version"]},
            SHELTER,
        ),
        201,
    )
    assert data["status"] == "RESERVED"
    assert data["party_size"] == 2


def test_reserved_beds_returns_to_zero_after_cancel(api):
    """PRD 2.7: "Reserved and occupied beds are strictly conserved: reserving a household adds its `party_size` to `reserved_beds`, and cancelling that reservation subtracts exactly the same `party_size`, so a reserve-then-cancel pair leaves `reserved_beds` unchanged"

    Design: Difficulty/compensating_invariant/reserved_beds_conserved_across_create_then_cancel
    """
    inc = create_active_incident(name="Delta Flood", jurisdiction="Sacramento", hazard_type="FLOOD")
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    shelter = create_shelter(inc["id"], physical_capacity=10)
    reg = create_registrant(zone["id"], party_size=4)

    asg = validate_success(
        api.create_shelter_assignment(
            {"registrant_id": reg["id"], "shelter_id": shelter["id"],
             "expected_registrant_version": reg["version"]},
            SHELTER,
        ),
        201,
    )
    api.set_shelter_assignment_status(asg["id"], {"action": "CANCEL"}, SHELTER)

    data = validate_success(api.get_shelter(shelter["id"], SHELTER))
    assert data["reserved_beds"] == 0


def test_reserved_beds_four_between_create_and_cancel(api):
    """PRD 3.4: "A `CANCEL` moves a `RESERVED` assignment to `CANCELLED`, releases its `party_size` from `reserved_beds`, and clears the household's `current_assignment_id`."

    Design: Difficulty/compensating_invariant/reserved_beds_conserved_across_create_then_cancel
    """
    inc = create_active_incident(name="Delta Flood", jurisdiction="Sacramento", hazard_type="FLOOD")
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    shelter = create_shelter(inc["id"], physical_capacity=10)
    reg = create_registrant(zone["id"], party_size=4)

    asg = validate_success(
        api.create_shelter_assignment(
            {"registrant_id": reg["id"], "shelter_id": shelter["id"],
             "expected_registrant_version": reg["version"]},
            SHELTER,
        ),
        201,
    )
    mid = validate_success(api.get_shelter(shelter["id"], SHELTER))
    assert mid["reserved_beds"] == 4

    cancelled = validate_success(
        api.set_shelter_assignment_status(asg["id"], {"action": "CANCEL"}, SHELTER)
    )
    assert cancelled["status"] == "CANCELLED"


def test_assignment_create_stale_registrant_version_conflict(api):
    """PRD 2.4: "a create whose `expected_registrant_version` does not equal the target `Registrant`'s current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/assignment_create_stale_registrant_version_conflict
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    shelter = create_shelter(inc["id"], physical_capacity=10)
    reg = create_registrant(zone["id"], party_size=2)
    stale_version = reg["version"]

    # First create advances the registrant's version to 2.
    create_assignment(reg["id"], shelter["id"], stale_version)

    resp = api.create_shelter_assignment(
        {"registrant_id": reg["id"], "shelter_id": shelter["id"],
         "expected_registrant_version": stale_version},
        SHELTER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_assignment_create_shelter_fk_not_found(api):
    """PRD 2.9: "then existence of every foreign key referenced in the request body (again the matching `ERR_..._NOT_FOUND`), then the optimistic-concurrency check on the household version (`ERR_STALE_VERSION`)"

    Design: Corner/cross_cutting_complexity_layers/assignment_create_shelter_fk_not_found
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    reg = create_registrant(zone["id"], party_size=2)

    resp = api.create_shelter_assignment(
        {"registrant_id": reg["id"], "shelter_id": NONEXISTENT_UUID,
         "expected_registrant_version": reg["version"]},
        SHELTER,
    )
    validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND)


def test_shelter_closed_terminal_reopen_returns_invalid_state(api):
    """PRD 3.4: "A coordinator opens a shelter by moving it `STANDBY → OPEN`, which is permitted only when `staffed_capacity_now` is greater than zero — at least one `SCHEDULED` shift must cover the current clock — and is otherwise rejected with `ERR_INVALID_STATE`."
    PRD 3.4: "`CLOSED` is terminal."

    Design: Corner/state_machines/shelter_closed_terminal_reopen_returns_invalid_state
    """
    inc = create_incident()
    shelter = create_shelter(inc["id"], physical_capacity=50)
    set_shelter_status(shelter["id"], "CLOSED")  # STANDBY -> CLOSED

    resp = api.set_shelter_status(shelter["id"], {"state": "OPEN"}, SHELTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
