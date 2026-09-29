"""Committed windows, the mobilisation buffer and the shared trench openings."""
from test_helpers import (
    CANON_COMMITMENT_DAYS,
    CANCELLATION_REASON,
    NON_EXISTENT_UUID,
    approve_plan,
    cancel_commitment,
    commit_window,
    commitment_payload,
    draft_determination,
    grant_permit,
    identify_conflict,
    issue_determination,
    make_construction_engineer_headers,
    make_utility_coordinator_headers,
    make_utility_owner_rep_headers,
    open_slot,
    read_commitment,
    read_conflict,
    read_owner,
    read_slot,
    register_facility,
    register_owner,
    register_project,
    report_complete,
    select_resolution,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
    world_plan_approved,
    world_slot_and_commitment,
)

LONG_DUCT_BANK = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 100.0,
    "station_end": 240.0,
    "offset_ft": 12.5,
    "depth_in": 48,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

FIBER_REACH = {
    "facility_type": "FIBER_CONDUIT",
    "station_begin": 200.0,
    "station_end": 240.0,
    "offset_ft": 9.0,
    "depth_in": 36,
    "material": "HDPE conduit",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

SECOND_DUCT_BANK = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 300.0,
    "station_end": 340.0,
    "offset_ft": 11.0,
    "depth_in": 44,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

TRENCH_PLAN = {
    "estimated_cost_cents": 12_000_000,
    "replacement_in_kind_cost_cents": 12_000_000,
    "proposed_capacity_ratio": 1.00,
    "work_days": 8,
    "joint_trench_requested": True,
}


def _relocate_reach(api, project_id, facility_id, *, conflict_overrides=None, plan_overrides=None):
    """Carry one facility through a conflict, an issued determination and an approved plan."""
    conflict = identify_conflict(api, project_id, facility_id, **(conflict_overrides or {}))
    select_resolution(api, conflict["id"], "RELOCATE")
    determination = draft_determination(api, conflict["id"])
    issue_determination(api, determination["id"])
    plan = submit_plan(api, conflict["id"], **(plan_overrides or {}))
    grant_permit(api, conflict["id"])
    plan = approve_plan(api, plan["id"])
    return {"conflict_id": conflict["id"], "plan_id": plan["id"], "plan": plan}


def _two_reaches_on_one_facility(api):
    """One facility hosting two conflicts, each with its own approved plan."""
    project = register_project(api, name="SR-14 Single Facility Reach")
    owner = register_owner(api)
    facility = register_facility(api, owner["id"], **LONG_DUCT_BANK)
    reach_a = _relocate_reach(
        api,
        project["id"],
        facility["id"],
        conflict_overrides={"conflict_station": 120.0, "clearance_deficiency_in": 18},
    )
    reach_b = _relocate_reach(
        api,
        project["id"],
        facility["id"],
        conflict_overrides={"conflict_station": 210.0, "clearance_deficiency_in": 12},
        plan_overrides={
            "estimated_cost_cents": 12_000_000,
            "replacement_in_kind_cost_cents": 12_000_000,
            "proposed_capacity_ratio": 1.00,
            "work_days": 8,
        },
    )
    first = commit_window(api, reach_a["plan_id"], owner["id"])
    return {
        "project_id": project["id"],
        "owner_id": owner["id"],
        "facility_id": facility["id"],
        "reach_a": reach_a,
        "reach_b": reach_b,
        "commitment_a": first,
    }


def test_a_window_two_days_clear_of_the_last_one_still_collides_on_the_buffer(api):
    """PRD 3.7: "The window must not collide with any other commitment on the same
    `facility_id` that is in `COMMITTED` or `IN_PROGRESS`, and collision is tested
    with a mobilisation buffer of 3 days added to each end: the proposal is
    rejected when the new window's start falls before the existing window's end
    advanced by 3 days *and* the existing window's start falls before the new
    window's end advanced by 3 days."

    Design: Difficulty/resource_temporal_overlap/facility_occupancy_windows_excluded_by_a_three_day_mobilization_buffer
    """
    world = _two_reaches_on_one_facility(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == (
        CANON_COMMITMENT_DAYS
    )

    validate_error(
        api.create_commitment(
            commitment_payload(
                world["reach_b"]["plan_id"],
                window_start="2027-04-22T00:00:00Z",
                window_end="2027-05-04T00:00:00Z",
                committed_work_days=8,
                phase_dependency="AFTER_GRADING",
            ),
            rep,
        ),
        "ERR_FACILITY_WINDOW_CONFLICT",
    )

    assert read_conflict(api, world["reach_b"]["conflict_id"])["status"] == (
        "RELOCATION_PLANNED"
    )
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == (
        CANON_COMMITMENT_DAYS
    )
    rows, meta = validate_paginated(
        api.list_commitments(
            make_utility_coordinator_headers(), {"facility_id": world["facility_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["commitment_a"]["id"]


def test_a_window_starting_exactly_at_the_buffer_edge_is_admitted(api):
    """PRD 3.7: "Because `window_end` is exclusive, a window running from the first
    instant of 5 April 2027 to the first instant of 20 April 2027 contributes 15
    days."

    Design: Difficulty/resource_temporal_overlap/facility_occupancy_windows_excluded_by_a_three_day_mobilization_buffer
    """
    world = _two_reaches_on_one_facility(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])

    second = validate_success(
        api.create_commitment(
            commitment_payload(
                world["reach_b"]["plan_id"],
                window_start="2027-04-23T00:00:00Z",
                window_end="2027-05-05T00:00:00Z",
                committed_work_days=8,
                phase_dependency="AFTER_GRADING",
            ),
            rep,
        ),
        201,
    )
    assert second["status"] == "COMMITTED"
    assert second["facility_id"] == world["facility_id"]

    assert read_conflict(api, world["reach_a"]["conflict_id"])["status"] == (
        "RELOCATION_SCHEDULED"
    )
    assert read_conflict(api, world["reach_b"]["conflict_id"])["status"] == (
        "RELOCATION_SCHEDULED"
    )
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == 27


def _three_reaches_sharing_a_trench(api):
    """A two-seat trench opening and three separate facilities that may occupy it."""
    project = register_project(api, name="SR-14 Shared Trench")
    owner = register_owner(api)
    slot = open_slot(
        api,
        project["id"],
        segment_code="SEG-B-STA-300-360",
        trench_open_start="2027-05-01T00:00:00Z",
        trench_open_end="2027-05-15T00:00:00Z",
        max_occupants=2,
    )
    facility_a = register_facility(
        api,
        owner["id"],
        **{**SECOND_DUCT_BANK, "station_begin": 300.0, "station_end": 320.0, "offset_ft": 12.5, "depth_in": 48},
    )
    facility_b = register_facility(
        api,
        owner["id"],
        **{
            "facility_type": "FIBER_CONDUIT",
            "station_begin": 330.0,
            "station_end": 345.0,
            "offset_ft": 10.0,
            "depth_in": 36,
            "material": "HDPE conduit",
            "installed_year": 1968,
            "occupancy_basis": "PRIVATE_EASEMENT",
            "record_source": "AS_BUILT",
        },
    )
    facility_c = register_facility(
        api,
        owner["id"],
        **{
            "facility_type": "GAS_MAIN",
            "station_begin": 350.0,
            "station_end": 360.0,
            "offset_ft": 14.0,
            "depth_in": 42,
            "material": "Coated steel",
            "installed_year": 1968,
            "occupancy_basis": "PRIVATE_EASEMENT",
            "record_source": "AS_BUILT",
        },
    )
    reach_a = _relocate_reach(
        api,
        project["id"],
        facility_a["id"],
        conflict_overrides={"conflict_station": 310.0, "clearance_deficiency_in": 12},
        plan_overrides=TRENCH_PLAN,
    )
    reach_b = _relocate_reach(
        api,
        project["id"],
        facility_b["id"],
        conflict_overrides={"conflict_station": 340.0, "clearance_deficiency_in": 9},
        plan_overrides=TRENCH_PLAN,
    )
    reach_c = _relocate_reach(
        api,
        project["id"],
        facility_c["id"],
        conflict_overrides={"conflict_station": 355.0, "clearance_deficiency_in": 11},
        plan_overrides=TRENCH_PLAN,
    )
    first = commit_window(
        api,
        reach_a["plan_id"],
        owner["id"],
        window_start="2027-05-01T00:00:00Z",
        window_end="2027-05-15T00:00:00Z",
        committed_work_days=8,
        phase_dependency="AFTER_GRADING",
        joint_trench_slot_id=slot["id"],
    )
    return {
        "project_id": project["id"],
        "owner_id": owner["id"],
        "slot_id": slot["id"],
        "reach_a": reach_a,
        "reach_b": reach_b,
        "reach_c": reach_c,
        "commitment_a": first,
    }


def test_a_slot_window_one_day_past_the_opening_is_not_contained(api):
    """PRD 3.7: "When a `joint_trench_slot_id` is supplied, the commitment window
    must be fully contained in the slot's opening, tested inclusively at both ends
    — the slot's `trench_open_start` at or before `window_start`, and `window_end`
    at or before the slot's `trench_open_end` — failing which the request is
    refused with `ERR_TRENCH_WINDOW_NOT_CONTAINED`; and the slot's
    `occupant_count` must be strictly below its `max_occupants`, failing which it
    is refused with `ERR_TRENCH_SLOT_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/joint_trench_slot_containment_is_inclusive_and_capacity_counts_overlaps
    """
    world = _three_reaches_sharing_a_trench(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])
    occupied = read_slot(api, world["slot_id"])
    assert occupied["occupant_count"] == 1
    assert occupied["status"] == "OPEN"

    validate_error(
        api.create_commitment(
            commitment_payload(
                world["reach_b"]["plan_id"],
                window_start="2027-05-02T00:00:00Z",
                window_end="2027-05-16T00:00:00Z",
                committed_work_days=8,
                phase_dependency="AFTER_GRADING",
                joint_trench_slot_id=world["slot_id"],
            ),
            rep,
        ),
        "ERR_TRENCH_WINDOW_NOT_CONTAINED",
    )

    after = read_slot(api, world["slot_id"])
    assert after["occupant_count"] == 1
    assert after["status"] == "OPEN"
    assert read_conflict(api, world["reach_b"]["conflict_id"])["status"] == (
        "RELOCATION_PLANNED"
    )


def test_occupants_may_overlap_each_other_until_the_slot_reaches_capacity(api):
    """PRD 3.6: "`occupant_count` is the number of schedule commitments referencing
    the slot whose `status` is `COMMITTED` or `IN_PROGRESS`, and the slot's
    `status` is `OPEN` while `occupant_count` is below `max_occupants` and `FULL`
    once `occupant_count` has reached `max_occupants`."

    Design: Difficulty/resource_temporal_overlap/joint_trench_slot_containment_is_inclusive_and_capacity_counts_overlaps
    """
    world = _three_reaches_sharing_a_trench(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])

    second = validate_success(
        api.create_commitment(
            commitment_payload(
                world["reach_b"]["plan_id"],
                window_start="2027-05-02T00:00:00Z",
                window_end="2027-05-15T00:00:00Z",
                committed_work_days=8,
                phase_dependency="AFTER_GRADING",
                joint_trench_slot_id=world["slot_id"],
            ),
            rep,
        ),
        201,
    )
    assert second["status"] == "COMMITTED"
    assert second["joint_trench_slot_id"] == world["slot_id"]

    full = read_slot(api, world["slot_id"])
    assert full["occupant_count"] == 2
    assert full["status"] == "FULL"

    validate_error(
        api.create_commitment(
            commitment_payload(
                world["reach_c"]["plan_id"],
                window_start="2027-05-03T00:00:00Z",
                window_end="2027-05-14T00:00:00Z",
                committed_work_days=8,
                phase_dependency="AFTER_GRADING",
                joint_trench_slot_id=world["slot_id"],
            ),
            rep,
        ),
        "ERR_TRENCH_SLOT_AT_CAPACITY",
    )

    after = read_slot(api, world["slot_id"])
    assert after["occupant_count"] == 2
    assert after["status"] == "FULL"
    assert read_conflict(api, world["reach_c"]["conflict_id"])["status"] == (
        "RELOCATION_PLANNED"
    )


def _one_seat_trench_and_two_reaches(api):
    """A single-seat opening spanning the whole construction period, already taken."""
    project = register_project(api, name="SR-14 Widening Section 3")
    owner = register_owner(api)
    slot = open_slot(
        api,
        project["id"],
        segment_code="SEG-A-STA-100-240",
        trench_open_start="2027-03-01T00:00:00Z",
        trench_open_end="2028-06-30T00:00:00Z",
        max_occupants=1,
    )
    facility_a = register_facility(api, owner["id"])
    facility_b = register_facility(api, owner["id"], **FIBER_REACH)
    reach_a = _relocate_reach(
        api,
        project["id"],
        facility_a["id"],
        plan_overrides={"joint_trench_requested": True},
    )
    reach_b = _relocate_reach(
        api,
        project["id"],
        facility_b["id"],
        conflict_overrides={"conflict_station": 220.0, "clearance_deficiency_in": 10},
        plan_overrides={
            "estimated_cost_cents": 20_000_000,
            "replacement_in_kind_cost_cents": 20_000_000,
            "proposed_capacity_ratio": 1.00,
            "work_days": 9,
            "joint_trench_requested": True,
        },
    )
    commit_window(
        api,
        reach_a["plan_id"],
        owner["id"],
        joint_trench_slot_id=slot["id"],
    )
    taken = read_slot(api, slot["id"])
    assert taken["occupant_count"] == 1
    assert taken["status"] == "FULL"
    return {
        "project_id": project["id"],
        "owner_id": owner["id"],
        "slot_id": slot["id"],
        "reach_a": reach_a,
        "reach_b": reach_b,
    }


def test_the_construction_window_rung_answers_before_the_slot_capacity_rung(api):
    """PRD 2.9: "The commitment window lies inside the project's construction
    window: `window_start` at or after `construction_start_date`, and `window_end`
    at or before `construction_end_date` — otherwise
    `ERR_WINDOW_OUTSIDE_CONSTRUCTION` (422). Applies to commitment creation."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_twentytwo_beats_constraint_priority_twentyfive_on_commitment_create
    """
    world = _one_seat_trench_and_two_reaches(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])

    validate_error(
        api.create_commitment(
            commitment_payload(
                world["reach_b"]["plan_id"],
                window_start="2028-07-05T00:00:00Z",
                window_end="2028-07-20T00:00:00Z",
                committed_work_days=9,
                phase_dependency="ANY_PHASE",
                joint_trench_slot_id=world["slot_id"],
            ),
            rep,
        ),
        "ERR_WINDOW_OUTSIDE_CONSTRUCTION",
    )

    slot = read_slot(api, world["slot_id"])
    assert slot["occupant_count"] == 1
    assert slot["status"] == "FULL"
    assert read_conflict(api, world["reach_b"]["conflict_id"])["status"] == (
        "RELOCATION_PLANNED"
    )
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == (
        CANON_COMMITMENT_DAYS
    )


def test_moving_the_same_window_inside_construction_exposes_the_full_slot(api):
    """PRD 2.9: "When a `joint_trench_slot_id` is supplied, the slot's
    `occupant_count` is strictly below its `max_occupants` — otherwise
    `ERR_TRENCH_SLOT_AT_CAPACITY`. Applies to commitment creation."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_twentytwo_beats_constraint_priority_twentyfive_on_commitment_create
    """
    world = _one_seat_trench_and_two_reaches(api)
    rep = make_utility_owner_rep_headers(world["owner_id"])

    validate_error(
        api.create_commitment(
            commitment_payload(
                world["reach_b"]["plan_id"],
                window_start="2027-06-05T00:00:00Z",
                window_end="2027-06-20T00:00:00Z",
                committed_work_days=9,
                phase_dependency="ANY_PHASE",
                joint_trench_slot_id=world["slot_id"],
            ),
            rep,
        ),
        "ERR_TRENCH_SLOT_AT_CAPACITY",
    )

    slot = read_slot(api, world["slot_id"])
    assert slot["occupant_count"] == 1
    assert slot["status"] == "FULL"
    assert read_conflict(api, world["reach_b"]["conflict_id"])["status"] == (
        "RELOCATION_PLANNED"
    )
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == (
        CANON_COMMITMENT_DAYS
    )


def test_cancelling_the_only_occupant_frees_the_slot_the_owner_and_the_conflict(api):
    """PRD 3.7: "The commitment moves to `CANCELLED`, which is terminal, and three
    compensating links restore what creation consumed: the owner's
    `open_commitment_days` returns to exactly its pre-creation value; any occupied
    slot's `occupant_count` decrements and its `status` returns to `OPEN` if it had
    become `FULL`; and the conflict returns `RELOCATION_SCHEDULED →
    RELOCATION_PLANNED` once no commitment of that conflict remains in `COMMITTED`
    or `IN_PROGRESS`."

    Design: Corner/state_machines/cancelling_the_only_commitment_compensates_slot_owner_and_conflict_together
    """
    world = world_slot_and_commitment(api, slot_overrides={"max_occupants": 1})
    assert world["slot"]["occupant_count"] == 1
    assert world["slot"]["status"] == "FULL"
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == (
        CANON_COMMITMENT_DAYS
    )
    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_SCHEDULED"

    cancelled = cancel_commitment(
        api, world["commitment_id"], world["owner_id"], CANCELLATION_REASON
    )
    assert cancelled["status"] == "CANCELLED"

    freed = read_slot(api, world["slot_id"])
    assert freed["occupant_count"] == 0
    assert freed["status"] == "OPEN"
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == 0
    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_PLANNED"

    rebooked = commit_window(
        api,
        world["plan_id"],
        world["owner_id"],
        joint_trench_slot_id=world["slot_id"],
    )
    assert rebooked["status"] == "COMMITTED"

    retaken = read_slot(api, world["slot_id"])
    assert retaken["occupant_count"] == 1
    assert retaken["status"] == "FULL"
    assert read_owner(api, world["owner_id"])["open_commitment_days"] == (
        CANON_COMMITMENT_DAYS
    )


def test_open_commitment_days_sums_the_open_set_and_reverses_to_zero(api):
    """PRD 3.7: "It is the sum, over that owner's commitments whose `status` is
    `COMMITTED` or `IN_PROGRESS`, of the number of days between each commitment's
    `window_start` and `window_end`."

    Design: Corner/calculations/open_commitment_days_treats_window_end_as_exclusive_and_reverses_cleanly
    """
    project = register_project(api)
    owner = register_owner(api)
    facility_a = register_facility(api, owner["id"])
    facility_b = register_facility(api, owner["id"], **SECOND_DUCT_BANK)
    reach_a = _relocate_reach(api, project["id"], facility_a["id"])
    reach_b = _relocate_reach(
        api,
        project["id"],
        facility_b["id"],
        conflict_overrides={"conflict_station": 320.0, "clearance_deficiency_in": 14},
        plan_overrides={
            "estimated_cost_cents": 5_000_000,
            "replacement_in_kind_cost_cents": 5_000_000,
            "proposed_capacity_ratio": 1.00,
            "work_days": 4,
        },
    )

    first = commit_window(api, reach_a["plan_id"], owner["id"])
    assert read_owner(api, owner["id"])["open_commitment_days"] == 15

    second = commit_window(
        api,
        reach_b["plan_id"],
        owner["id"],
        window_start="2027-05-05T00:00:00Z",
        window_end="2027-05-17T00:00:00Z",
        committed_work_days=4,
        phase_dependency="AFTER_GRADING",
    )
    assert read_owner(api, owner["id"])["open_commitment_days"] == 27

    cancel_commitment(
        api, second["id"], owner["id"], "Second reach deferred to the next season."
    )
    assert read_owner(api, owner["id"])["open_commitment_days"] == 15

    completed = report_complete(
        api, first["id"], owner["id"], "Complete well inside the window."
    )
    assert completed["status"] == "COMPLETE"
    assert completed["late_days"] == 0
    assert read_owner(api, owner["id"])["open_commitment_days"] == 0
    assert read_commitment(api, second["id"])["status"] == "CANCELLED"


def test_a_commitment_stores_the_slot_link_and_is_found_from_both_directions(api):
    """PRD 3.7: "When a slot was named, the slot's `occupant_count` increments and
    its `status` becomes `FULL` at the moment `occupant_count` reaches
    `max_occupants`."

    Design: Corner/endpoints/commitment_links_to_a_joint_trench_slot_and_fills_its_occupancy
    """
    world = world_plan_approved(api, plan_overrides={"joint_trench_requested": True})
    engineer = make_construction_engineer_headers()
    slot = open_slot(api, world["project_id"], segment_code="SEG-A-104")
    assert slot["occupant_count"] == 0
    assert slot["status"] == "OPEN"

    commitment = commit_window(
        api, world["plan_id"], world["owner_id"], joint_trench_slot_id=slot["id"]
    )
    assert commitment["joint_trench_slot_id"] == slot["id"]

    occupied = read_slot(api, slot["id"])
    assert occupied["occupant_count"] == 1
    assert occupied["status"] == "OPEN"

    linked, linked_meta = validate_paginated(
        api.list_commitments(engineer, {"joint_trench_slot_id": slot["id"]})
    )
    assert linked_meta["total_count"] == 1
    assert linked[0]["id"] == commitment["id"]

    slots, slots_meta = validate_paginated(
        api.list_project_joint_trench_slots(
            world["project_id"], make_utility_coordinator_headers()
        )
    )
    assert slots_meta["total_count"] == 1
    assert slots[0]["id"] == slot["id"]

    validate_error(
        api.create_commitment(
            commitment_payload(
                world["plan_id"],
                window_start="2027-04-23T00:00:00Z",
                window_end="2027-05-01T00:00:00Z",
                joint_trench_slot_id=NON_EXISTENT_UUID,
            ),
            make_utility_owner_rep_headers(world["owner_id"]),
        ),
        "ERR_SLOT_NOT_FOUND",
    )
    _, after_meta = validate_paginated(
        api.list_commitments(engineer, {"plan_id": world["plan_id"]})
    )
    assert after_meta["total_count"] == 1
