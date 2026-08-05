"""Validation-priority conflicts, cross-entity state gates, body validations.

Difficulty queue A: priority_pair_validation_conflict/adopt_state_beats_compliance,
priority_pair_validation_conflict/merge_existence_beats_state,
cross_entity_state_dependency/block_remove_requires_editable_plan,
cross_entity_state_dependency/polling_assignment_requires_active_place.
Corner queue B: validations/block_assignment_district_plan_mismatch,
validations/block_assignment_cross_jurisdiction_block,
validations/duplicate_district_number_rejected,
entities/create_census_block_negative_population_rejected,
entities/census_block_vap_exceeds_population_rejected,
entities/duplicate_geoid_within_jurisdiction_rejected.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_jurisdiction, add_block, create_plan, create_district, assign_block,
    create_precinct, create_polling_place, drive_to_comment_open, setup_f1,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
)
from test_helpers.factories import (
    create_census_block_payload, create_district_payload, create_block_assignment_payload,
    create_polling_assignment_payload, merge_payload,
)

CART = TEST_USERS["cartographer_headers"]
CHAIR = TEST_USERS["chair_headers"]
CLERK = TEST_USERS["clerk_headers"]


# -------------------------------------- priority_pair: adopt state beats compliance
def _plan_under_review_noncompliant(api, jname):
    """Both blocks in District 1 (+/-100%, non-compliant); submitted to UNDER_REVIEW."""
    j = create_jurisdiction(api, name=jname, target_district_count=2)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1049, voting_age_population=800, minority_vap=500, registered_voters=700)
    blkB = add_block(api, jid, geoid="B", population=951, voting_age_population=700, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="Ppc")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    create_district(api, pid, 2)
    assign_block(api, pid, d1["id"], blkA["id"])
    assign_block(api, pid, d1["id"], blkB["id"])
    validate_success(api.submit_review(pid, CART))
    return pid


def test_adopt_under_review_reports_invalid_state_over_compliance(api):
    """PRD §2.11: "the checks are evaluated in a fixed priority order and the first
    failure is the one reported. The order is: ... (5) state - the target resource
    is in a state that permits the transition (ERR_INVALID_STATE); ... (11) the
    plan-compliance gate at adoption (ERR_PLAN_NOT_COMPLIANT)".

    Design: Difficulty/priority_pair_validation_conflict/adopt_state_beats_compliance
    """
    pid = _plan_under_review_noncompliant(api, "Jpc")
    validate_error(api.adopt_plan(pid, CHAIR), ApiErrorId.ERR_INVALID_STATE.value)


def test_adopt_under_review_leaves_status_unchanged(api):
    """PRD §2.11: "A lower-numbered failure always masks a higher-numbered one - for
    example, an unauthorized caller is told `ERR_UNAUTHORIZED` before any body field
    is examined." The masked adopt leaves the plan in UNDER_REVIEW.

    Design: Difficulty/priority_pair_validation_conflict/adopt_state_beats_compliance
    """
    pid = _plan_under_review_noncompliant(api, "Jpc2")
    api.adopt_plan(pid, CHAIR)
    plan = validate_success(api.get_plan(pid, CHAIR))
    assert plan["status"] == "UNDER_REVIEW", "rejected adopt must not change plan state"


# -------------------------------------- priority_pair: merge existence beats state
def _retired_precinct(api, jname):
    j = create_jurisdiction(api, name=jname, target_district_count=1)
    pr = create_precinct(api, j["id"], name="PR")  # no blocks
    validate_success(api.retire_precinct(pr["id"], CLERK))
    return pr


def test_merge_missing_target_reports_precinct_not_found(api):
    """PRD §2.11: "(3) existence of every path id ... ; (4) existence of every body
    foreign key; (5) state - the target resource is in a state that permits the
    transition (ERR_INVALID_STATE)". An unknown target_precinct_id (prio 4) masks
    the RETIRED-source state failure (prio 5).

    Design: Difficulty/priority_pair_validation_conflict/merge_existence_beats_state
    """
    pr = _retired_precinct(api, "Jm")
    validate_error(api.merge_precinct(pr["id"], merge_payload(NON_EXISTENT_UUID), CLERK),
                   ApiErrorId.ERR_PRECINCT_NOT_FOUND.value)


def test_merge_missing_target_leaves_source_retired(api):
    """PRD §2.8: "Foreign keys carried in a request body are validated the same way
    after the path is resolved." PRD §2.8: "an unknown `target_precinct_id` yields
    `ERR_PRECINCT_NOT_FOUND`". The masked merge leaves the source precinct in RETIRED.

    Design: Difficulty/priority_pair_validation_conflict/merge_existence_beats_state
    """
    pr = _retired_precinct(api, "Jm2")
    api.merge_precinct(pr["id"], merge_payload(NON_EXISTENT_UUID), CLERK)
    after = validate_success(api.get_precinct(pr["id"], CLERK))
    assert after["status"] == "RETIRED", "failed merge must not mutate the source precinct"


# -------------------------------------- cross_entity: block remove requires editable plan
def _comment_open_plan_with_active_assignment(api, jname):
    ctx = setup_f1(api, jname=jname)
    drive_to_comment_open(api, ctx)
    data, _ = validate_paginated(api.list_block_assignments(CART, params={"plan_id": ctx["pid"]}))
    ba1 = next(b for b in data if b["census_block_id"] == ctx["blkA"] and b["status"] == "ACTIVE")
    return ctx, ba1["id"]


def test_remove_block_on_comment_open_plan_invalid_state(api):
    """PRD §3.2: "A Cartographer may pull a block back out by removing its
    assignment, but only while the plan is in DRAFT or UNDER_REVIEW (otherwise
    ERR_INVALID_STATE)."

    Design: Difficulty/cross_entity_state_dependency/block_remove_requires_editable_plan
    """
    ctx, ba1 = _comment_open_plan_with_active_assignment(api, "Jce")
    validate_error(api.remove_block_assignment(ba1, CART), ApiErrorId.ERR_INVALID_STATE.value)


def test_remove_block_on_comment_open_leaves_assignment_active(api):
    """PRD §3.2: "Removal moves the assignment to `REMOVED` and recomputes the
    district and plan metrics as a compensating adjustment." The rejected removal
    leaves the assignment ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/block_remove_requires_editable_plan
    """
    ctx, ba1 = _comment_open_plan_with_active_assignment(api, "Jce2")
    api.remove_block_assignment(ba1, CART)
    ba = validate_success(api.get_block_assignment(ba1, CART))
    assert ba["status"] == "ACTIVE", "a rejected removal must leave the assignment ACTIVE"


# -------------------------------------- cross_entity: polling assign requires active place
def _precinct_and_closed_place(api, jname):
    j = create_jurisdiction(api, name=jname, target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="P1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    pp = create_polling_place(api, jid, name="Gym", address="1 Main St", capacity=1000)
    validate_success(api.close_polling_place(pp["id"], CLERK))
    return pr, pp


def test_polling_assignment_to_closed_place_invalid_state(api):
    """PRD §3.7: "The referenced polling place must be `ACTIVE`, or the request is
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/polling_assignment_requires_active_place
    """
    pr, pp = _precinct_and_closed_place(api, "Jpp")
    resp = api.create_polling_assignment(pr["id"], create_polling_assignment_payload(
        polling_place_id=pp["id"], ev_start_date="2026-06-01", ev_end_date="2026-06-05",
        expected_precinct_version=pr["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_polling_assignment_to_closed_place_creates_nothing(api):
    """PRD §3.7: "The referenced polling place must be `ACTIVE`, or the request is
    `ERR_INVALID_STATE`." A rejected create against a CLOSED place leaves the
    precinct with no active polling assignment.

    Design: Difficulty/cross_entity_state_dependency/polling_assignment_requires_active_place
    """
    pr, pp = _precinct_and_closed_place(api, "Jpp2")
    api.create_polling_assignment(pr["id"], create_polling_assignment_payload(
        polling_place_id=pp["id"], ev_start_date="2026-06-01", ev_end_date="2026-06-05",
        expected_precinct_version=pr["version"]), CLERK)
    data, meta = validate_paginated(api.list_polling_assignments(CLERK, params={"precinct_id": pr["id"]}))
    assert meta["total_count"] == 0, "no polling assignment should exist after a rejected create"


# -------------------------------------- corner: district / block cross-aggregate
def test_block_assignment_district_from_other_plan_rejected(api):
    """PRD §3.2: "The district must belong to the plan named in the path
    (ERR_DISTRICT_PLAN_MISMATCH)".

    Design: Corner/validations/block_assignment_district_plan_mismatch
    """
    j = create_jurisdiction(api, name="Jdm", target_district_count=1)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1000, voting_age_population=800, minority_vap=200, registered_voters=600)
    p1 = create_plan(api, jid, name="P1")
    p2 = create_plan(api, jid, name="P2")
    dx = create_district(api, p2["id"], 1)  # belongs to P2
    pv = validate_success(api.get_plan(p1["id"], CART))["version"]
    resp = api.create_block_assignment(p1["id"], create_block_assignment_payload(
        district_id=dx["id"], census_block_id=blkA["id"], expected_plan_version=pv), CART)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_PLAN_MISMATCH.value)


def test_block_assignment_cross_jurisdiction_block_rejected(api):
    """PRD §3.2: "the block must belong to the plan's jurisdiction
    (`ERR_BLOCK_JURISDICTION_MISMATCH`)."

    Design: Corner/validations/block_assignment_cross_jurisdiction_block
    """
    j1 = create_jurisdiction(api, name="J1", target_district_count=1)
    j2 = create_jurisdiction(api, name="J2", target_district_count=1, state_code="NV")
    blkZ = add_block(api, j2["id"], geoid="Z", population=1000, voting_age_population=800, minority_vap=200, registered_voters=600)
    p1 = create_plan(api, j1["id"], name="P1")
    d1 = create_district(api, p1["id"], 1)
    pv = validate_success(api.get_plan(p1["id"], CART))["version"]
    resp = api.create_block_assignment(p1["id"], create_block_assignment_payload(
        district_id=d1["id"], census_block_id=blkZ["id"], expected_plan_version=pv), CART)
    validate_error(resp, ApiErrorId.ERR_BLOCK_JURISDICTION_MISMATCH.value)


def test_duplicate_district_number_rejected(api):
    """PRD §3.2: "Creating a district requires a district_number - its ordinal, at
    least 1 and unique within the plan; a duplicate is rejected with
    ERR_DUPLICATE_DISTRICT_NUMBER."

    Design: Corner/validations/duplicate_district_number_rejected
    """
    j = create_jurisdiction(api, name="Jdd", target_district_count=2)
    plan = create_plan(api, j["id"], name="P")
    create_district(api, plan["id"], 1)
    validate_error(api.create_district(plan["id"], create_district_payload(district_number=1), CART),
                   ApiErrorId.ERR_DUPLICATE_DISTRICT_NUMBER.value)


# -------------------------------------- corner: census-block field validations
def test_census_block_negative_population_rejected(api):
    """PRD §3.1: "Population and all demographic counts must be non-negative;
    additionally `voting_age_population` may not exceed `population`".

    Design: Corner/entities/create_census_block_negative_population_rejected
    """
    j = create_jurisdiction(api, name="Jneg", target_district_count=1)
    resp = api.create_census_block(j["id"], create_census_block_payload(
        geoid="G1", population=-5, voting_age_population=500, minority_vap=100, registered_voters=400), CART)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_census_block_vap_exceeds_population_rejected(api):
    """PRD §3.1: "additionally `voting_age_population` may not exceed `population`,
    and `minority_vap` may not exceed `voting_age_population` — any violation is
    `ERR_VALIDATION`."

    Design: Corner/entities/census_block_vap_exceeds_population_rejected
    """
    j = create_jurisdiction(api, name="Jvap", target_district_count=1)
    resp = api.create_census_block(j["id"], create_census_block_payload(
        geoid="G1", population=800, voting_age_population=900, minority_vap=100, registered_voters=400), CART)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_duplicate_geoid_within_jurisdiction_rejected(api):
    """PRD §3.1: "its geoid (the Census GEOID, which serves as the block's business
    key and must be unique within the jurisdiction - a repeat yields
    ERR_DUPLICATE_GEOID)".

    Design: Corner/entities/duplicate_geoid_within_jurisdiction_rejected
    """
    j = create_jurisdiction(api, name="Jgeo", target_district_count=1)
    jid = j["id"]
    add_block(api, jid, geoid="G1", population=800, voting_age_population=600, minority_vap=100, registered_voters=400)
    resp = api.create_census_block(jid, create_census_block_payload(
        geoid="G1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300), CART)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_GEOID.value)
