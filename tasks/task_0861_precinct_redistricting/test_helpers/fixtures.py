"""Composite setup helpers.

The database is empty before every test (the runner restarts the server per
test), so every helper builds its preconditions from scratch using only
PRD-declared endpoints. Helpers use get_success_data() so setup failures surface
as clear "Setup failed" errors.

Header convention (all roles opaque, see test_users.py):
  CART  -> Cartographer  (X-User-ID u_cart; becomes plan.created_by_user_id)
  DEMO  -> Demographer
  CHAIR -> CommissionChair (X-User-ID u_chair; distinct from creator, adopts)
  CLERK -> ElectionClerk
  PUBLIC-> PublicParticipant
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_jurisdiction_payload, create_census_block_payload, create_plan_payload,
    create_district_payload, create_block_assignment_payload, create_precinct_payload,
    create_polling_place_payload, create_polling_assignment_payload, create_venue_payload,
    create_hearing_payload, create_comment_payload, create_compliance_check_payload,
)

CART = TEST_USERS["cartographer_headers"]
DEMO = TEST_USERS["demographer_headers"]
CHAIR = TEST_USERS["chair_headers"]
CLERK = TEST_USERS["clerk_headers"]
PUBLIC = TEST_USERS["public_headers"]

# The F1 canonical partition (§ design index): ideal 1000; D1 +4.90%, D2 -4.90%.
BLOCK_A = {"geoid": "A", "population": 1049, "voting_age_population": 800, "minority_vap": 500, "registered_voters": 700}
BLOCK_B = {"geoid": "B", "population": 951, "voting_age_population": 700, "minority_vap": 200, "registered_voters": 600}


# --------------------------------------------------------------------- primitives
def create_jurisdiction(api, name="J1", target_district_count=2, required_mm=0, state_code="CA"):
    payload = create_jurisdiction_payload(
        name=name, state_code=state_code, target_district_count=target_district_count,
        required_majority_minority_districts=required_mm,
    )
    return get_success_data(api.create_jurisdiction(payload, CART))


def add_block(api, jid, geoid, population, voting_age_population, minority_vap, registered_voters):
    payload = create_census_block_payload(
        geoid=geoid, population=population, voting_age_population=voting_age_population,
        minority_vap=minority_vap, registered_voters=registered_voters,
    )
    return get_success_data(api.create_census_block(jid, payload, CART))


def create_plan(api, jid, name="P1", parent_plan_id=None):
    payload = create_plan_payload(name=name)
    if parent_plan_id is not None:
        payload["parent_plan_id"] = parent_plan_id
    return get_success_data(api.create_plan(jid, payload, CART))


def create_district(api, plan_id, district_number, **overrides):
    payload = create_district_payload(district_number=district_number, **overrides)
    return get_success_data(api.create_district(plan_id, payload, CART))


def assign_block(api, plan_id, district_id, block_id, headers=CART):
    """Assign a block to a district, auto-reading the plan's current version for OCC."""
    pv = get_success_data(api.get_plan(plan_id, headers))["version"]
    payload = create_block_assignment_payload(
        district_id=district_id, census_block_id=block_id, expected_plan_version=pv,
    )
    return get_success_data(api.create_block_assignment(plan_id, payload, headers))


def create_precinct(api, jid, name="PR", census_block_ids=None):
    payload = create_precinct_payload(name=name)
    if census_block_ids is not None:
        payload["census_block_ids"] = census_block_ids
    return get_success_data(api.create_precinct(jid, payload, CLERK))


def create_polling_place(api, jid, name="Gym", address="1 Main St", capacity=5000):
    payload = create_polling_place_payload(name=name, address=address, capacity=capacity)
    return get_success_data(api.create_polling_place(jid, payload, CLERK))


def create_venue(api, jid, name="City Hall", capacity=100):
    payload = create_venue_payload(name=name, capacity=capacity)
    return get_success_data(api.create_venue(jid, payload, CLERK))


def assign_precinct_to_place(api, precinct_id, place_id, ev_start_date, ev_end_date):
    """Create a polling assignment, auto-reading the precinct's version for OCC."""
    pvr = get_success_data(api.get_precinct(precinct_id, CLERK))["version"]
    payload = create_polling_assignment_payload(
        polling_place_id=place_id, ev_start_date=ev_start_date, ev_end_date=ev_end_date,
        expected_precinct_version=pvr,
    )
    return get_success_data(api.create_polling_assignment(precinct_id, payload, CLERK))


def get_precinct_of_block(api, block_id):
    """Read a block, then read the precinct it currently points at."""
    blk = get_success_data(api.get_census_block(block_id, CLERK))
    return get_success_data(api.get_precinct(blk["precinct_id"], CLERK))


# ------------------------------------------------------------- F1 plan composites
def setup_f1(api, jname="J1", required_mm=0):
    """F1 canonical partition: 2 districts, +4.90%/-4.90%, full partition, contiguous.

    Returns dict: jid, blkA, blkB, pid, d1, d2.
    """
    j = create_jurisdiction(api, name=jname, target_district_count=2, required_mm=required_mm)
    jid = j["id"]
    blkA = add_block(api, jid, **BLOCK_A)
    blkB = add_block(api, jid, **BLOCK_B)
    plan = create_plan(api, jid, name="P1")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    d2 = create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d2["id"], blkB["id"])
    return {"jid": jid, "blkA": blkA["id"], "blkB": blkB["id"], "pid": pid,
            "d1": d1["id"], "d2": d2["id"]}


def drive_to_comment_open(api, ctx):
    """DRAFT -> UNDER_REVIEW -> (POPULATION_DEVIATION check) -> COMMENT_OPEN."""
    get_success_data(api.submit_review(ctx["pid"], CART))
    get_success_data(api.create_compliance_check(
        ctx["pid"], create_compliance_check_payload("POPULATION_DEVIATION"), DEMO))
    get_success_data(api.open_comment(ctx["pid"], CHAIR))
    return ctx


def schedule_hearing(api, ctx, venue_id=None, start="2026-06-01T10:00:00Z",
                     end="2026-06-01T11:00:00Z", venue_name="City Hall", venue_capacity=100):
    """Schedule a hearing on a COMMENT_OPEN/HEARING_SCHEDULED plan. Creates a venue
    if none is supplied. Stores vid/h1 into ctx."""
    if venue_id is None:
        venue_id = create_venue(api, ctx["jid"], name=venue_name, capacity=venue_capacity)["id"]
    h = get_success_data(api.create_hearing(
        ctx["pid"], create_hearing_payload(venue_id=venue_id, scheduled_start=start, scheduled_end=end), CHAIR))
    ctx["vid"] = venue_id
    ctx["h1"] = h["id"]
    return ctx


def setup_f1_hearing_scheduled(api, jname="J1", required_mm=0):
    """F1 plan driven to HEARING_SCHEDULED with one SCHEDULED hearing H1 at
    [2026-06-01T10:00, 11:00) at venue V. Returns ctx with jid,pid,d1,d2,vid,h1."""
    ctx = setup_f1(api, jname=jname, required_mm=required_mm)
    drive_to_comment_open(api, ctx)
    schedule_hearing(api, ctx)
    return ctx


def setup_f1_held_hearing(api, jname="J1", required_mm=0, hold_at="2026-06-01T10:00:00Z"):
    """F1 plan at HEARING_SCHEDULED with hearing H1 marked HELD (clock advanced)."""
    ctx = setup_f1_hearing_scheduled(api, jname=jname, required_mm=required_mm)
    get_success_data(api.set_clock({"to_iso8601": hold_at}, CHAIR))
    get_success_data(api.hold_hearing(ctx["h1"], CHAIR))
    return ctx
