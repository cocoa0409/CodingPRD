"""Resource-temporal-overlap and compensating-invariant tests (PRD §3.2-§3.5).

Queue (A) difficulty instances covering the SKILLED bed-capacity pool, the
single-occupancy INDEPENDENT unit pool, and the occupy/release and
add/remove-second-person conservation invariants.
"""
from test_helpers import (
    activate_residency,
    create_unit,
    get_residency,
    get_unit,
    hold_bed,
    occupy_bed,
    open_residency,
    reserve_residency_via_assign,
    setup_active_residency,
    setup_community_and_plan,
    AD,
)
from test_helpers.api_client import api_client
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_bed_reservation_payload,
    create_second_person_payload,
)


def _AD():
    from test_helpers import make_admissions_director_headers
    return make_admissions_director_headers()


def _CC():
    from test_helpers import make_care_coordinator_headers
    return make_care_coordinator_headers()


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / skilled_bed_capacity_blocks_second_concurrent_hold
# ─────────────────────────────────────────────────────────────────────────────

def test_skilled_bed_capacity_one_blocks_second_concurrent_hold(api):
    """PRD §3.5: "a skilled unit cannot accept a new reservation when the number of
    its committed reservations — those currently `HELD` plus those currently
    `OCCUPIED` — already equals the unit's `bed_capacity`, in which case the hold is
    rejected with `ERR_BED_CAPACITY_EXCEEDED`."

    A SKILLED unit (bed_capacity 1) already carrying one HELD reservation rejects a
    second concurrent HELD reservation with ERR_BED_CAPACITY_EXCEEDED.

    Design: Difficulty/resource_temporal_overlap/skilled_bed_capacity_blocks_second_concurrent_hold
    """
    community, _plan, skilled_unit, r1, r2 = _two_active_with_skilled_unit("BedTown")
    hold_bed(r1["id"], skilled_unit["id"], 10)
    resp = api_client.create_bed_reservation(
        create_bed_reservation_payload(r2["id"], skilled_unit["id"], 10), _CC(),
    )
    validate_error(resp, ApiErrorId.ERR_BED_CAPACITY_EXCEEDED.value)


def test_skilled_bed_capacity_counts_held_reservation_against_pool(api):
    """PRD §3.5: "the number of its committed reservations — those currently `HELD`
    plus those currently `OCCUPIED` — already equals the unit's `bed_capacity`".

    Confirms that a single HELD (not yet OCCUPIED) reservation is already counted
    against the capacity-1 pool, so the second hold is refused.

    Design: Difficulty/resource_temporal_overlap/skilled_bed_capacity_blocks_second_concurrent_hold
    """
    community, _plan, skilled_unit, r1, r2 = _two_active_with_skilled_unit("BedTown2")
    first = hold_bed(r1["id"], skilled_unit["id"], 10)
    assert first["status"] == "HELD"
    resp = api_client.create_bed_reservation(
        create_bed_reservation_payload(r2["id"], skilled_unit["id"], 10), _CC(),
    )
    validate_error(resp, ApiErrorId.ERR_BED_CAPACITY_EXCEEDED.value)


def _two_active_with_skilled_unit(name: str):
    """Two ACTIVE residencies + one SKILLED unit (bed_capacity 1). Returns
    (community, plan, skilled_unit, r1, r2)."""
    community, plan = setup_community_and_plan(
        community_name=name,
        plan_overrides={"name": "B Plan", "contract_type": "TYPE_A",
                        "second_person_fee_cents": 0},
    )
    ui1 = create_unit(community["id"], unit_number="BI1", care_level="INDEPENDENT")
    ui2 = create_unit(community["id"], unit_number="BI2", care_level="INDEPENDENT")
    skilled_unit = create_unit(community["id"], unit_number="BSK",
                               care_level="SKILLED", bed_capacity=1)
    r1 = activate_residency(reserve_residency_via_assign(
        community, plan, ui1, resident_name="Bea 1"))
    r2 = activate_residency(reserve_residency_via_assign(
        community, plan, ui2, resident_name="Bea 2"))
    return community, plan, skilled_unit, r1, r2


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / independent_unit_single_occupancy_blocks_second_assignment
# ─────────────────────────────────────────────────────────────────────────────

def test_independent_unit_single_occupancy_blocks_second_assignment(api):
    """PRD §3.2: "The target unit must be `AVAILABLE`, or the action is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    An INDEPENDENT unit already OCCUPIED by one RESERVED residency rejects a second
    assign-unit with ERR_UNIT_NOT_AVAILABLE.

    Design: Difficulty/resource_temporal_overlap/independent_unit_single_occupancy_blocks_second_assignment
    """
    community, plan = setup_community_and_plan(
        community_name="SoloTown",
        plan_overrides={"name": "S Plan", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="SU1", care_level="INDEPENDENT")
    r1 = open_residency(community, plan, resident_name="Sol 1", dob="1921-01-01")
    r2 = open_residency(community, plan, resident_name="Sol 2", dob="1920-01-01")
    validate_success(api_client.assign_unit(r1["id"], {"unit_id": unit["id"]}, _AD()))
    resp = api_client.assign_unit(r2["id"], {"unit_id": unit["id"]}, _AD())
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)


def test_independent_unit_collision_leaves_second_residency_deposit_held(api):
    """PRD §3.2: "From `DEPOSIT_HELD` the residency forks down one of two paths"; and
    "The target unit must be `AVAILABLE`, or the action is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    When the second assign-unit is rejected for an occupied unit, the rejected
    residency stays DEPOSIT_HELD (the failed transition is a no-op on its state).

    Design: Difficulty/resource_temporal_overlap/independent_unit_single_occupancy_blocks_second_assignment
    """
    community, plan = setup_community_and_plan(
        community_name="SoloTown2",
        plan_overrides={"name": "S Plan", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="SU1", care_level="INDEPENDENT")
    r1 = open_residency(community, plan, resident_name="Sol 1", dob="1921-01-01")
    r2 = open_residency(community, plan, resident_name="Sol 2", dob="1920-01-01")
    validate_success(api_client.assign_unit(r1["id"], {"unit_id": unit["id"]}, _AD()))
    api_client.assign_unit(r2["id"], {"unit_id": unit["id"]}, _AD())
    r2_after = get_residency(r2["id"])
    assert r2_after["status"] == "DEPOSIT_HELD", (
        f"rejected residency must remain DEPOSIT_HELD, got {r2_after['status']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / bed_occupy_then_release_conserves_available_skilled_units
# ─────────────────────────────────────────────────────────────────────────────

def test_bed_occupy_consumes_then_release_restores_skilled_unit(api):
    """PRD §3.5: "Occupying ... flips the skilled unit's `status` to `OCCUPIED`,
    consuming the bed."
    PRD §3.5: "Releasing an `OCCUPIED` reservation requires it to be `OCCUPIED`, else
    `ERR_BED_RESERVATION_NOT_RELEASABLE`, and frees its skilled unit by setting that
    unit's `status` back to `AVAILABLE`."

    The skilled unit is OCCUPIED after occupy and AVAILABLE again after release,
    conserving the available-skilled-unit count with no drift.

    Design: Difficulty/compensating_invariant/bed_occupy_then_release_conserves_available_skilled_units
    """
    community, skilled_unit, brid = _active_with_held_skilled_bed("Conserve A")
    assert get_unit(skilled_unit["id"])["status"] == "AVAILABLE"  # pre-occupy
    occupy_bed(brid)
    assert get_unit(skilled_unit["id"])["status"] == "OCCUPIED", (
        "skilled unit must be OCCUPIED after occupy"
    )
    validate_success(api_client.release_bed_reservation(brid, _CC()))
    assert get_unit(skilled_unit["id"])["status"] == "AVAILABLE", (
        "skilled unit must return to AVAILABLE after release — conserved, no drift"
    )


def test_bed_release_after_occupy_drives_reservation_released(api):
    """PRD §3.5: "Releasing an `OCCUPIED` reservation requires it to be `OCCUPIED`,
    else `ERR_BED_RESERVATION_NOT_RELEASABLE`, and frees its skilled unit".

    The reservation itself reaches the RELEASED terminal state after the
    occupy→release round-trip.

    Design: Difficulty/compensating_invariant/bed_occupy_then_release_conserves_available_skilled_units
    """
    community, skilled_unit, brid = _active_with_held_skilled_bed("Conserve A2")
    occupy_bed(brid)
    released = validate_success(api_client.release_bed_reservation(brid, _CC()))
    assert released["status"] == "RELEASED", (
        f"reservation must reach RELEASED, got {released['status']}"
    )


def _active_with_held_skilled_bed(name: str):
    """ACTIVE residency + one SKILLED unit AVAILABLE with a HELD reservation.
    Returns (community, skilled_unit, brid)."""
    community, plan = setup_community_and_plan(
        community_name=name,
        plan_overrides={"name": "CA Plan", "contract_type": "TYPE_A",
                        "second_person_fee_cents": 0},
    )
    ind_unit = create_unit(community["id"], unit_number="CAI", care_level="INDEPENDENT")
    skilled_unit = create_unit(community["id"], unit_number="CAS",
                               care_level="SKILLED", bed_capacity=1)
    active = activate_residency(reserve_residency_via_assign(community, plan, ind_unit))
    br = hold_bed(active["id"], skilled_unit["id"], 10)
    return community, skilled_unit, br["id"]


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / second_person_add_then_remove_conserves_active_occupant_count
# ─────────────────────────────────────────────────────────────────────────────

def test_second_person_add_sets_flag_then_remove_clears_it(api):
    """PRD §3.4: "Adding the second person sets the residency's `has_second_person`
    to true and bumps the residency's `version` by one".
    PRD §3.4: "Removing a second person drives it from `ACTIVE` to `REMOVED`, clears
    the residency's `has_second_person` back to false, and again bumps the
    residency's `version`."

    has_second_person flips true on add and false on remove, conserving the
    occupant count back to its original single-occupant state.

    Design: Difficulty/compensating_invariant/second_person_add_then_remove_conserves_active_occupant_count
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Conserve B",
        plan_overrides={"name": "CB Plan", "second_person_fee_cents": 150_000},
    )
    sp = validate_success(api_client.add_second_person(
        active["id"],
        create_second_person_payload(full_name="Spouse", date_of_birth="1919-02-02"),
        _AD(),
    ), expected_status=201)
    assert get_residency(active["id"])["has_second_person"] is True, (
        "has_second_person must be true after add"
    )
    validate_success(api_client.remove_second_person(sp["id"], _AD()))
    assert get_residency(active["id"])["has_second_person"] is False, (
        "has_second_person must be false after remove — occupant count conserved"
    )


def test_second_person_remove_marks_record_removed(api):
    """PRD §3.4: "Removing a second person drives it from `ACTIVE` to `REMOVED`".

    The SecondPerson record itself reaches the REMOVED status after removal,
    completing the add→remove conservation round-trip.

    Design: Difficulty/compensating_invariant/second_person_add_then_remove_conserves_active_occupant_count
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Conserve B2",
        plan_overrides={"name": "CB Plan", "second_person_fee_cents": 150_000},
    )
    sp = validate_success(api_client.add_second_person(
        active["id"],
        create_second_person_payload(full_name="Spouse", date_of_birth="1919-02-02"),
        _AD(),
    ), expected_status=201)
    removed = validate_success(api_client.remove_second_person(sp["id"], _AD()))
    assert removed["status"] == "REMOVED", (
        f"second person must reach REMOVED, got {removed['status']}"
    )
