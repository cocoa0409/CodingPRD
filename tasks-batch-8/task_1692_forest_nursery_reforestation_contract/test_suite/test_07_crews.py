"""Crew scheduling: overlap buffer, capacity conservation, and lifecycle guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId, TEST_USERS,
    create_landowner, create_seed_zone, create_order, create_contract,
    create_crew, create_assignment, confirm_assignment,
)

CO = TEST_USERS["contract_officer_headers"]


def _two_contract_world():
    """Zone, landowner, two orders, two DRAFT contracts."""
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    lo = create_landowner()
    o1 = create_order(lo["id"], z_dst["id"], 1000)
    o2 = create_order(lo["id"], z_dst["id"], 1000)
    c1 = create_contract(lo["id"], o1["id"], z_dst["id"], acres=2)
    c2 = create_contract(lo["id"], o2["id"], z_dst["id"], acres=2)
    return {"zone": z_dst, "landowner": lo, "o1": o1, "o2": o2, "c1": c1, "c2": c2}


def test_cross_contract_assignment_without_buffer_rejected(api):
    """PRD §3.5: "a crew's `SCHEDULED` and `CONFIRMED` intervals must never
    intersect, with assignments on the same contract allowed to abut exactly
    (one's `start_date` equal to the other's `end_date`), while assignments on
    different contracts must leave a full day of buffer — the new interval
    starts at least one day after the existing one ends, or ends at least one
    day before the existing one starts; violations are rejected with
    `ERR_CREW_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/crew_assignment_cross_contract_buffer
    """
    w = _two_contract_world()
    crew = create_crew(capacity_per_day=100000)
    create_assignment(crew["id"], w["c1"]["id"], "2027-04-01", "2027-04-05", 800)

    res = api.create_crew_assignment(
        {"crew_id": crew["id"], "planting_contract_id": w["c2"]["id"],
         "start_date": "2027-04-05", "end_date": "2027-04-07",
         "planned_seedlings": 200}, CO
    )
    validate_error(res, ApiErrorId.ERR_CREW_OVERLAP)


def test_cross_contract_assignment_with_buffer_allowed(api):
    """PRD §3.5: "assignments on different contracts must leave a full day of
    buffer — the new interval starts at least one day after the existing one
    ends, or ends at least one day before the existing one starts; violations
    are rejected with `ERR_CREW_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/crew_assignment_cross_contract_buffer
    """
    w = _two_contract_world()
    crew = create_crew(capacity_per_day=100000)
    create_assignment(crew["id"], w["c1"]["id"], "2027-04-01", "2027-04-05", 800)

    res = api.create_crew_assignment(
        {"crew_id": crew["id"], "planting_contract_id": w["c2"]["id"],
         "start_date": "2027-04-06", "end_date": "2027-04-08",
         "planned_seedlings": 200}, CO
    )
    created = validate_success(res, 201)
    assert is_valid_uuid(created["id"]), (
        "a start exactly one day after the predecessor's end satisfies the "
        "cross-contract buffer"
    )


def test_crew_assignment_same_contract_adjacency_allowed(api):
    """PRD §3.5: "a crew's `SCHEDULED` and `CONFIRMED` intervals must never
    intersect, with assignments on the same contract allowed to abut exactly
    (one's `start_date` equal to the other's `end_date`)"

    Design: Corner/state_machines/crew_assignment_same_contract_adjacency_allowed
    """
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    lo = create_landowner()
    order = create_order(lo["id"], z_dst["id"], 100)
    contract = create_contract(lo["id"], order["id"], z_dst["id"], acres=1)
    crew = create_crew()
    create_assignment(crew["id"], contract["id"], "2027-04-01", "2027-04-05", 100)

    res = api.create_crew_assignment(
        {"crew_id": crew["id"], "planting_contract_id": contract["id"],
         "start_date": "2027-04-05", "end_date": "2027-04-08",
         "planned_seedlings": 100}, CO
    )
    created = validate_success(res, 201)
    assert is_valid_uuid(created["id"]), (
        "same-contract adjacency (start == prior end) must not collide"
    )


def _crew_capacity_world():
    """One crew (5000/day) and one DRAFT contract."""
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    lo = create_landowner()
    order = create_order(lo["id"], z_dst["id"], 1000)
    contract = create_contract(lo["id"], order["id"], z_dst["id"], acres=2)
    crew = create_crew(capacity_per_day=5000)
    return {"contract": contract, "crew": crew}


def test_crew_capacity_exceeded_rejected(api):
    """PRD §3.5: "an assignment's daily load is its `planned_seedlings` divided
    by the interval's length in days, rounded up to a whole seedling per day,
    and the crew's free capacity on any date is its `capacity_per_day` less the
    daily loads of its `SCHEDULED` and `CONFIRMED` assignments covering that
    date; the new assignment's daily load may not exceed the crew's remaining
    capacity over its interval, otherwise `ERR_CREW_CAPACITY_EXCEEDED`"

    Design: Difficulty/compensating_invariant/crew_capacity_conserved_across_assign_release
    """
    w = _crew_capacity_world()
    create_assignment(w["crew"]["id"], w["contract"]["id"],
                      "2027-04-01", "2027-04-05", 20000)  # 5000/day: full

    res = api.create_crew_assignment(
        {"crew_id": w["crew"]["id"], "planting_contract_id": w["contract"]["id"],
         "start_date": "2027-04-06", "end_date": "2027-04-07",
         "planned_seedlings": 6000}, CO
    )
    validate_error(res, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)


def test_release_restores_crew_capacity(api):
    """PRD §3.5: "Releasing a `SCHEDULED` or `CONFIRMED` assignment restores the
    crew's capacity" and "the new assignment's daily load may not exceed the
    crew's remaining capacity over its interval, otherwise
    `ERR_CREW_CAPACITY_EXCEEDED`"

    Design: Difficulty/compensating_invariant/crew_capacity_conserved_across_assign_release
    """
    w = _crew_capacity_world()
    a1 = create_assignment(w["crew"]["id"], w["contract"]["id"],
                           "2027-04-01", "2027-04-05", 20000)

    released = get_success_data(api.release_crew_assignment(a1["id"], CO))
    assert released["status"] == "RELEASED", "manual release must compensate"

    res = api.create_crew_assignment(
        {"crew_id": w["crew"]["id"], "planting_contract_id": w["contract"]["id"],
         "start_date": "2027-04-01", "end_date": "2027-04-05",
         "planned_seedlings": 20000}, CO
    )
    created = validate_success(res, 201)
    assert is_valid_uuid(created["id"]), (
        "ceil(20000/4) = 5000 equals the restored capacity and must pass"
    )


def test_release_already_released_assignment_rejected(api):
    """PRD §3.5: "Releasing a `SCHEDULED` or `CONFIRMED` assignment restores the
    crew's capacity" and PRD §2.6: "State legality: the state machine's
    from-state permits the requested transition — otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/release_already_released_assignment_rejected
    """
    w = _crew_capacity_world()
    a1 = create_assignment(w["crew"]["id"], w["contract"]["id"],
                           "2027-04-01", "2027-04-03", 100)

    released = get_success_data(api.release_crew_assignment(a1["id"], CO))
    assert released["status"] == "RELEASED"

    res = api.release_crew_assignment(a1["id"], CO)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_assignment_requires_contract_in_prep_states(api):
    """PRD §3.5: "Confirming an assignment moves it from `SCHEDULED` to
    `CONFIRMED` and requires the contract to be in `SITE_PREP`,
    `READY_TO_PLANT`, or `BLOCKED`." and PRD §2.6: "State legality: the state
    machine's from-state permits the requested transition — otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Corner/validations/confirm_assignment_requires_contract_in_prep_states
    """
    w = _crew_capacity_world()  # contract still DRAFT
    a1 = create_assignment(w["crew"]["id"], w["contract"]["id"],
                           "2027-04-01", "2027-04-03", 100)

    res = api.confirm_crew_assignment(a1["id"], CO)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
