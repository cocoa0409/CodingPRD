"""Venue buffered overlap, EV-window closed overlap, voter conservation, capacity, closing.

Difficulty queue A: resource_temporal_overlap/hearing_venue_buffer_conflict,
resource_temporal_overlap/ev_window_touching_date_conflict,
compensating_invariant/population_conserved_on_assign_then_remove,
compensating_invariant/voters_conserved_on_polling_reassignment.
Corner queue B: validations/polling_capacity_exceeded_rejected,
validations/polling_assignment_bad_date_range,
errors/close_polling_place_in_use_rejected,
errors/hearing_venue_jurisdiction_mismatch.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_f1_hearing_scheduled, create_jurisdiction, add_block, create_precinct,
    create_polling_place, create_venue, assign_precinct_to_place,
    drive_to_comment_open, setup_f1, ApiErrorId, TEST_USERS,
)
from test_helpers import create_plan, create_district, assign_block
from test_helpers.factories import (
    create_hearing_payload, create_polling_assignment_payload,
)

CART = TEST_USERS["cartographer_headers"]
DEMO = TEST_USERS["demographer_headers"]
CHAIR = TEST_USERS["chair_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------- resource_temporal_overlap: venue buffer
def test_second_hearing_within_setup_buffer_conflicts(api):
    """PRD §3.4: "the new hearing conflicts with an existing one at the same venue
    when the new hearing's start falls before the existing hearing's end plus 60
    minutes and the existing hearing's start falls before the new hearing's end
    plus 60 minutes; such a collision is rejected with ERR_VENUE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_venue_buffer_conflict
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jto")  # H1 [10:00,11:00) at venue V
    resp = api.create_hearing(ctx["pid"], create_hearing_payload(
        venue_id=ctx["vid"], scheduled_start="2026-06-01T11:30:00Z", scheduled_end="2026-06-01T12:30:00Z"), CHAIR)
    validate_error(resp, ApiErrorId.ERR_VENUE_TIME_CONFLICT.value)


def test_hearing_after_full_buffer_gap_allowed(api):
    """PRD §3.4: "Back-to-back hearings are permitted only when at least 60 minutes
    separate the end of one from the start of the next."

    A hearing starting 12:00 (exactly 60 min after the 11:00 end) is allowed.

    Design: Difficulty/resource_temporal_overlap/hearing_venue_buffer_conflict
    """
    ctx = setup_f1_hearing_scheduled(api, jname="Jto2")  # H1 [10:00,11:00) at venue V
    created = validate_success(api.create_hearing(ctx["pid"], create_hearing_payload(
        venue_id=ctx["vid"], scheduled_start="2026-06-01T12:00:00Z", scheduled_end="2026-06-01T13:00:00Z"), CHAIR), 201)
    assert created["status"] == "SCHEDULED"


# --------------------------------------- resource_temporal_overlap: EV window
def _setup_two_precincts_one_place(api, jname):
    j = create_jurisdiction(api, name=jname, target_district_count=1)
    jid = j["id"]
    v1 = add_block(api, jid, geoid="V1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    v2 = add_block(api, jid, geoid="V2", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    p1 = create_precinct(api, jid, name="P1", census_block_ids=[v1["id"]])
    p2 = create_precinct(api, jid, name="P2", census_block_ids=[v2["id"]])
    pp = create_polling_place(api, jid, name="Gym", address="1 Main St", capacity=5000)
    return jid, p1, p2, pp


def test_ev_window_touching_endpoint_date_conflicts(api):
    """PRD §3.7: "Under closed-interval semantics - both endpoints inclusive - the
    new window conflicts with an existing ACTIVE assignment at the same polling
    place belonging to a different precinct when the new window's start date is on
    or before the existing window's end date and the existing window's start date
    is on or before the new window's end date; even a single shared date counts as
    a conflict. A collision is rejected with ERR_EV_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/ev_window_touching_date_conflict
    """
    jid, p1, p2, pp = _setup_two_precincts_one_place(api, "Jev")
    assign_precinct_to_place(api, p1["id"], pp["id"], "2026-06-01", "2026-06-05")
    pvr = validate_success(api.get_precinct(p2["id"], CLERK))["version"]
    resp = api.create_polling_assignment(p2["id"], create_polling_assignment_payload(
        polling_place_id=pp["id"], ev_start_date="2026-06-05", ev_end_date="2026-06-08",
        expected_precinct_version=pvr), CLERK)
    validate_error(resp, ApiErrorId.ERR_EV_WINDOW_CONFLICT.value)


def test_ev_window_non_touching_allowed(api):
    """PRD §3.7: "a polling place cannot host two overlapping early-voting windows
    for different precincts." Non-overlapping windows (no shared date) are allowed.

    Design: Difficulty/resource_temporal_overlap/ev_window_touching_date_conflict
    """
    jid, p1, p2, pp = _setup_two_precincts_one_place(api, "Jev2")
    assign_precinct_to_place(api, p1["id"], pp["id"], "2026-06-01", "2026-06-05")
    created = assign_precinct_to_place(api, p2["id"], pp["id"], "2026-06-06", "2026-06-08")
    assert created["status"] == "ACTIVE", "windows sharing no date must not conflict"


# --------------------------------------- compensating_invariant: voter conservation
def _setup_precinct_two_places(api, jname):
    j = create_jurisdiction(api, name=jname, target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="R1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    pp1 = create_polling_place(api, jid, name="PP1", address="1 A St", capacity=5000)
    pp2 = create_polling_place(api, jid, name="PP2", address="2 B St", capacity=5000)
    return jid, pr, pp1, pp2


def test_polling_reassignment_zeroes_old_place(api):
    """PRD §3.7: "Creating a new assignment for a precinct supersedes that
    precinct's prior ACTIVE polling assignment (moving it to SUPERSEDED),
    recomputes the assigned_registered_voters on both the old and the new polling
    place".

    Design: Difficulty/compensating_invariant/voters_conserved_on_polling_reassignment
    """
    jid, pr, pp1, pp2 = _setup_precinct_two_places(api, "Jvc")
    assign_precinct_to_place(api, pr["id"], pp1["id"], "2026-06-01", "2026-06-05")
    assign_precinct_to_place(api, pr["id"], pp2["id"], "2026-06-10", "2026-06-14")
    old = validate_success(api.get_polling_place(pp1["id"], CLERK))
    assert old["assigned_registered_voters"] == 0, "old place drops to 0 after reassignment"


def test_polling_reassignment_conserves_voters(api):
    """PRD §3.7: "a polling place's `assigned_registered_voters` is the sum of
    `registered_voters` over the precincts with an `ACTIVE` polling assignment to it".

    The precinct's 340 voters move whole from PP1 to PP2 (PP1=0, PP2=340).

    Design: Difficulty/compensating_invariant/voters_conserved_on_polling_reassignment
    """
    jid, pr, pp1, pp2 = _setup_precinct_two_places(api, "Jvc2")
    assign_precinct_to_place(api, pr["id"], pp1["id"], "2026-06-01", "2026-06-05")
    assign_precinct_to_place(api, pr["id"], pp2["id"], "2026-06-10", "2026-06-14")
    old = validate_success(api.get_polling_place(pp1["id"], CLERK))
    new = validate_success(api.get_polling_place(pp2["id"], CLERK))
    assert new["assigned_registered_voters"] == 340, f"new place holds all 340 voters, got {new['assigned_registered_voters']}"
    assert old["assigned_registered_voters"] + new["assigned_registered_voters"] == 340, "voters conserved, no drift"


# --------------------------------------- compensating_invariant: population conserved
def _setup_assign_then_remove(api, jname):
    """Jurisdiction (total 2000); District 1 holds block A(1049); block B(951)
    assigned to District 1 too, then removed. Returns (jid, pid, d1, d2, baB)."""
    j = create_jurisdiction(api, name=jname, target_district_count=2)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1049, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=951, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Pco")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    d2 = create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], blkA["id"])
    baB = assign_block(api, pid, d1["id"], blkB["id"])
    return jid, pid, d1["id"], d2["id"], baB["id"]


def test_district_population_restored_after_assign_then_remove(api):
    """PRD §3.2: "Removal moves the assignment to REMOVED and recomputes the
    district and plan metrics as a compensating adjustment."

    After assigning then removing block B, District 1 returns to 1049.

    Design: Difficulty/compensating_invariant/population_conserved_on_assign_then_remove
    """
    jid, pid, d1, d2, baB = _setup_assign_then_remove(api, "Jco")
    validate_success(api.remove_block_assignment(baB, CART))
    districts = validate_success(api.list_districts(pid, CART))
    dd1 = next(x for x in districts if x["id"] == d1)
    assert dd1["assigned_population"] == 1049, f"D1 returns to 1049 after remove, got {dd1['assigned_population']}"


def test_population_partition_conserved_after_remove(api):
    """PRD §3.2: "Its assigned_population is the sum of population over the census
    blocks reached through the district's ACTIVE block assignments; superseded and
    removed assignments are excluded."

    Sum of districts' assigned_population plus the unassigned block equals the
    jurisdiction's total_population (2000), with no drift.

    Design: Difficulty/compensating_invariant/population_conserved_on_assign_then_remove
    """
    jid, pid, d1, d2, baB = _setup_assign_then_remove(api, "Jco2")
    validate_success(api.remove_block_assignment(baB, CART))
    districts = validate_success(api.list_districts(pid, CART))
    dd1 = next(x for x in districts if x["id"] == d1)
    dd2 = next(x for x in districts if x["id"] == d2)
    assert dd2["assigned_population"] == 0, "District 2 holds no blocks"
    juris = validate_success(api.get_jurisdiction(jid, CART))
    assigned = dd1["assigned_population"] + dd2["assigned_population"]
    unassigned = 951  # block B, returned to the unassigned pool
    assert assigned + unassigned == juris["total_population"] == 2000, "population partition conserved"


# --------------------------------------- corner: capacity exceeded
def test_polling_capacity_exceeded_rejected(api):
    """PRD §3.7: "assigning a precinct must not push that total strictly above the
    place's capacity; an assignment that would exceed capacity is rejected with
    ERR_POLLING_CAPACITY_EXCEEDED."

    Design: Corner/validations/polling_capacity_exceeded_rejected
    """
    j = create_jurisdiction(api, name="Jcap", target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="R1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])  # 340 provisional voters
    pp = create_polling_place(api, jid, name="Small", address="9 St", capacity=300)
    pvr = pr["version"]
    resp = api.create_polling_assignment(pr["id"], create_polling_assignment_payload(
        polling_place_id=pp["id"], ev_start_date="2026-06-01", ev_end_date="2026-06-05",
        expected_precinct_version=pvr), CLERK)
    validate_error(resp, ApiErrorId.ERR_POLLING_CAPACITY_EXCEEDED.value)


# --------------------------------------- corner: bad EV date range
def test_polling_assignment_bad_date_range_rejected(api):
    """PRD §3.7: "the inclusive early-voting window ev_start_date and ev_end_date
    (dates in YYYY-MM-DD form, with the end on or after the start, or
    ERR_INVALID_DATE_RANGE)".

    Design: Corner/validations/polling_assignment_bad_date_range
    """
    j = create_jurisdiction(api, name="Jdr", target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="R1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    pp = create_polling_place(api, jid, name="PP", address="9 St", capacity=5000)
    resp = api.create_polling_assignment(pr["id"], create_polling_assignment_payload(
        polling_place_id=pp["id"], ev_start_date="2026-06-05", ev_end_date="2026-06-01",
        expected_precinct_version=pr["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


# --------------------------------------- corner: close place in use
def test_close_polling_place_in_use_rejected(api):
    """PRD §3.7: "A polling place may be closed once it has no active polling
    assignment ... closing one that still has an active assignment is rejected with
    ERR_POLLING_PLACE_IN_USE."

    Design: Corner/errors/close_polling_place_in_use_rejected
    """
    j = create_jurisdiction(api, name="Jpu", target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="R1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    pp = create_polling_place(api, jid, name="PP", address="9 St", capacity=5000)
    assign_precinct_to_place(api, pr["id"], pp["id"], "2026-06-01", "2026-06-05")
    validate_error(api.close_polling_place(pp["id"], CLERK), ApiErrorId.ERR_POLLING_PLACE_IN_USE.value)


# --------------------------------------- corner: hearing venue jurisdiction mismatch
def test_hearing_venue_jurisdiction_mismatch_rejected(api):
    """PRD §3.4: "The hearing records its `plan_id`, starts in `SCHEDULED`, and the
    venue must belong to the plan's jurisdiction (`ERR_VENUE_JURISDICTION_MISMATCH`)."

    Design: Corner/errors/hearing_venue_jurisdiction_mismatch
    """
    j1 = create_jurisdiction(api, name="J1", target_district_count=1)
    j1id = j1["id"]
    j2 = create_jurisdiction(api, name="J2", target_district_count=1, state_code="NV")
    v2 = create_venue(api, j2["id"], name="Foreign Hall", capacity=100)
    blkA = add_block(api, j1id, geoid="A", population=1000, voting_age_population=800, minority_vap=200, registered_voters=600)
    from test_helpers import create_plan, create_district, assign_block
    from test_helpers.factories import create_compliance_check_payload
    plan = create_plan(api, j1id, name="P1")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    assign_block(api, pid, d1["id"], blkA["id"])
    validate_success(api.submit_review(pid, CART))
    validate_success(api.create_compliance_check(pid, create_compliance_check_payload("POPULATION_DEVIATION"), DEMO), 201)
    validate_success(api.open_comment(pid, CHAIR))
    resp = api.create_hearing(pid, create_hearing_payload(
        venue_id=v2["id"], scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T11:00:00Z"), CHAIR)
    validate_error(resp, ApiErrorId.ERR_VENUE_JURISDICTION_MISMATCH.value)
