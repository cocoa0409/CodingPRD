"""RBAC denial, four-eyes SoD, OCC, plan fork, scenario compare, reads, pagination.

Corner queue B: rbac/cartographer_cannot_adopt,
rbac/adopt_by_creator_segregation_of_duties, rbac/demographer_cannot_submit_comment,
cross_cutting_complexity_layers/block_assignment_stale_plan_version_conflict,
cross_cutting_complexity_layers/plan_fork_deep_copies_districts_and_assignments,
endpoints/list_block_assignments_by_district, endpoints/scenario_comparison_reports_deltas,
endpoints/list_pagination_envelope, entities/create_jurisdiction_returns_computed_defaults,
entities/jurisdiction_totals_recompute_on_block_add, entities/get_jurisdiction_not_found,
entities/compliance_check_is_immutable_no_version, entities/incumbent_retained_computed_true.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_f1, setup_f1_held_hearing, create_jurisdiction, add_block, create_plan,
    create_district, assign_block, assert_compliance_check,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS, make_headers,
)
from test_helpers.factories import (
    create_jurisdiction_payload, create_block_assignment_payload, create_district_payload,
    create_comment_payload, create_compliance_check_payload,
)

CART = TEST_USERS["cartographer_headers"]
DEMO = TEST_USERS["demographer_headers"]
CHAIR = TEST_USERS["chair_headers"]


# ------------------------------------------------ rbac: role denial
def test_cartographer_cannot_adopt_plan(api):
    """PRD §2.1: "CommissionChair ... rejects or adopts plans." A Cartographer is
    not permitted to adopt, so the request is ERR_UNAUTHORIZED (PRD §2.1: "When the
    headers are well-formed but the role is not permitted to perform the requested
    operation, the request is rejected with ERR_UNAUTHORIZED").

    Design: Corner/rbac/cartographer_cannot_adopt
    """
    j = create_jurisdiction(api, name="Jrb", target_district_count=1)
    plan = create_plan(api, j["id"], name="P")
    validate_error(api.adopt_plan(plan["id"], CART), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_adopt_by_plan_creator_segregation_of_duties(api):
    """PRD §2.10: "the X-User-ID adopting a plan must differ from the plan's
    recorded created_by_user_id. An attempt by the plan's own creator to adopt it
    is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 403), even when every other
    adoption precondition is satisfied."

    Design: Corner/rbac/adopt_by_creator_segregation_of_duties
    """
    ctx = setup_f1_held_hearing(api, jname="Jsod")  # plan created by u_cart, compliant, HELD hearing
    creator_as_chair = make_headers("CommissionChair", "u_cart")
    validate_error(api.adopt_plan(ctx["pid"], creator_as_chair), ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_demographer_cannot_submit_comment(api):
    """PRD §2.1: "PublicParticipant - a member of the public who submits comments
    during the comment period." Only a PublicParticipant may submit comments, so a
    Demographer is ERR_UNAUTHORIZED.

    Design: Corner/rbac/demographer_cannot_submit_comment
    """
    j = create_jurisdiction(api, name="Jau", target_district_count=1)
    plan = create_plan(api, j["id"], name="P")
    resp = api.create_comment(plan["id"], create_comment_payload(commenter_name="X", comment_text="hi"), DEMO)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ------------------------------------------------ concurrency: stale plan version
def test_block_assignment_stale_plan_version_conflict(api):
    """PRD §2.7: "If `expected_plan_version` does not equal the plan's current
    `version`, the create is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/block_assignment_stale_plan_version_conflict
    """
    j = create_jurisdiction(api, name="Jocc", target_district_count=1)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    blkB = add_block(api, jid, geoid="B", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    plan = create_plan(api, jid, name="Pocc")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    pv0 = validate_success(api.get_plan(pid, CART))["version"]
    # First assignment succeeds and bumps plan.version.
    validate_success(api.create_block_assignment(pid, create_block_assignment_payload(
        district_id=d1["id"], census_block_id=blkA["id"], expected_plan_version=pv0), CART), 201)
    # Second assignment still carries the stale pre-assignment version.
    resp = api.create_block_assignment(pid, create_block_assignment_payload(
        district_id=d1["id"], census_block_id=blkB["id"], expected_plan_version=pv0), CART)
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION.value)


# ------------------------------------------------ fork deep copy
def test_plan_fork_deep_copies_districts_and_assignments(api):
    """PRD §3.2: "A plan may instead be forked from an existing scenario by
    supplying a parent_plan_id: on a forked create, every District of the parent
    and every ACTIVE block assignment of the parent are deep-copied into the new
    plan".

    Design: Corner/cross_cutting_complexity_layers/plan_fork_deep_copies_districts_and_assignments
    """
    ctx = setup_f1(api, jname="Jfk")
    p2 = create_plan(api, ctx["jid"], name="P2", parent_plan_id=ctx["pid"])
    forked = validate_success(api.get_plan(p2["id"], CART))
    assert forked["max_abs_deviation_pct"] == 4.90, "forked plan inherits the parent's 4.90 deviation"
    districts, meta = validate_paginated(api.list_districts(p2["id"], CART))
    assert meta["total_count"] == 2, f"fork copies both districts, got {meta['total_count']}"


# ------------------------------------------------ scenario comparison
def test_scenario_comparison_reports_zero_delta_for_identical_forks(api):
    """PRD §3.8: "the comparison reports the differences between the two plans'
    summary metrics: max_abs_deviation_pct_delta ... each computed as this plan's
    metric minus the other plan's metric".

    Design: Corner/endpoints/scenario_comparison_reports_deltas
    """
    ctx = setup_f1(api, jname="Jcmp")
    p2 = create_plan(api, ctx["jid"], name="P2", parent_plan_id=ctx["pid"])
    result = validate_success(api.get_comparison(ctx["pid"], p2["id"], DEMO))
    assert result["max_abs_deviation_pct_delta"] == 0, \
        f"identical forks differ by 0, got {result['max_abs_deviation_pct_delta']}"


# ------------------------------------------------ list block assignments by district
def test_list_block_assignments_by_district(api):
    """PRD §3.2: "Block assignments can be read individually or listed with optional
    plan_id, district_id, or census_block_id filters." The active assignment for the
    district appears in the filtered list.

    Design: Corner/endpoints/list_block_assignments_by_district
    """
    j = create_jurisdiction(api, name="Jls", target_district_count=1)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1000, voting_age_population=800, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="P")
    pid = plan["id"]
    d1 = create_district(api, pid, 1)
    ba = assign_block(api, pid, d1["id"], blkA["id"])
    data, _ = validate_paginated(api.list_block_assignments(CART, params={"district_id": d1["id"]}))
    match = [b for b in data if b["id"] == ba["id"]]
    assert match and match[0]["status"] == "ACTIVE", "district filter must return its ACTIVE assignment"


# ------------------------------------------------ pagination envelope
def test_census_blocks_list_pagination_envelope(api):
    """PRD §2.3: "The meta block of a list response reports limit, offset,
    total_count (the total number of matching records before pagination), and
    has_more (true when records remain beyond the current page)."

    Design: Corner/endpoints/list_pagination_envelope
    """
    j = create_jurisdiction(api, name="Jpg", target_district_count=1)
    jid = j["id"]
    add_block(api, jid, geoid="A", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    add_block(api, jid, geoid="B", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    resp = api.list_census_blocks(CART, params={"jurisdiction_id": jid})
    assert resp.json()["response_type"] == "array"
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, "two blocks fit the default page, so has_more is false"


# ------------------------------------------------ jurisdiction creation defaults
def test_create_jurisdiction_computed_defaults(api):
    """PRD §3.1: "At creation the jurisdiction's computed totals — `total_population`,
    `voting_age_population_total`, and `ideal_district_population` — all start at 0."
    PRD §2.4: "an integer that begins at 1 and increments by exactly 1 on every
    mutation of the resource."

    Design: Corner/entities/create_jurisdiction_returns_computed_defaults
    """
    created = validate_success(api.create_jurisdiction(
        create_jurisdiction_payload(name="J", state_code="CA", target_district_count=3), CART), 201)
    got = validate_success(api.get_jurisdiction(created["id"], CART))
    assert got["total_population"] == 0
    assert got["ideal_district_population"] == 0
    assert got["version"] == 1


def test_jurisdiction_totals_recompute_on_block_add(api):
    """PRD §3.1: "the jurisdiction's total_population becomes the sum of their
    population ... and its ideal_district_population becomes total_population divided
    by target_district_count as an exact quotient rounded to 4 decimal places."

    Design: Corner/entities/jurisdiction_totals_recompute_on_block_add
    """
    j = create_jurisdiction(api, name="J", target_district_count=3)
    jid = j["id"]
    add_block(api, jid, geoid="G1", population=600, voting_age_population=500, minority_vap=100, registered_voters=400)
    add_block(api, jid, geoid="G2", population=900, voting_age_population=700, minority_vap=200, registered_voters=500)
    got = validate_success(api.get_jurisdiction(jid, CART))
    assert got["total_population"] == 1500
    assert got["ideal_district_population"] == 500.0, f"1500/3 = 500.0, got {got['ideal_district_population']}"


def test_get_jurisdiction_not_found(api):
    """PRD §2.8: "the outer resource must exist before the inner one is examined. A
    missing jurisdiction yields `ERR_JURISDICTION_NOT_FOUND`".

    Design: Corner/entities/get_jurisdiction_not_found
    """
    validate_error(api.get_jurisdiction(NON_EXISTENT_UUID, CART),
                   ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)


def test_compliance_check_is_immutable_snapshot(api):
    """PRD §2.4: "a ComplianceCheck is an immutable snapshot. It carries only id and
    created_at - it has neither updated_at nor version".
    PRD §3.3: "For CONTIGUITY: PASS when every district in the plan is contiguous,
    FAIL otherwise."

    Design: Corner/entities/compliance_check_is_immutable_no_version
    """
    j = create_jurisdiction(api, name="J", target_district_count=1)
    plan = create_plan(api, j["id"], name="P")
    check = validate_success(api.create_compliance_check(
        plan["id"], create_compliance_check_payload("CONTIGUITY"), DEMO), 201)
    assert_compliance_check(check)
    assert check["result_status"] == "PASS", "no districts -> vacuously contiguous -> PASS"


def test_incumbent_retained_computed_true(api):
    """PRD §3.3: "A district's incumbent_retained flag is true precisely when the
    census block whose geoid equals the district's incumbent_home_geoid currently
    has an ACTIVE block assignment to that district".

    Design: Corner/entities/incumbent_retained_computed_true
    """
    j = create_jurisdiction(api, name="J", target_district_count=1)
    jid = j["id"]
    blkA = add_block(api, jid, geoid="A", population=1000, voting_age_population=800, minority_vap=200, registered_voters=600)
    plan = create_plan(api, jid, name="P")
    pid = plan["id"]
    d1 = create_district(api, pid, 1, incumbent_name="Rep. Lee", incumbent_home_geoid="A")
    assign_block(api, pid, d1["id"], blkA["id"])
    districts = validate_success(api.list_districts(pid, CART))
    d = next(x for x in districts if x["id"] == d1["id"])
    assert d["incumbent_retained"] is True, "incumbent's home block is assigned to the district"
