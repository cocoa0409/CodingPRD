"""Planting contracts: required-seedlings sizing, readiness gate, start-planting
preconditions, and the planting-quantity floor."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_landowner, create_seed_zone, create_order, create_contract,
    create_crew, create_assignment, confirm_assignment,
    setup_ready_world, set_clock,
)

CO = TEST_USERS["contract_officer_headers"]


def test_required_seedlings_large_site_surcharge(api):
    """PRD §3.5: "At creation the server computes `required_seedlings`: the
    `acres` multiplied by `trees_per_acre`, multiplied by one plus the effective
    contingency fraction, with the product rounded up to a whole seedling. The
    effective contingency is the contract's `contingency_pct` alone for sites
    under 50 acres, and the `contingency_pct` plus a further 0.05 large-site
    surcharge when the contract covers at least 50 acres."

    Design: Corner/calculations/required_seedlings_large_site_surcharge
    """
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    lo = create_landowner()
    o1 = create_order(lo["id"], z_dst["id"], 22000)
    o2 = create_order(lo["id"], z_dst["id"], 23000)

    c49 = create_contract(lo["id"], o1["id"], z_dst["id"],
                          acres=49, trees_per_acre=400, contingency_pct=0.1)
    assert c49["required_seedlings"] == 21560, (
        f"ceil(49 * 400 * 1.10) = 21560 with no surcharge below 50 acres, "
        f"got {c49['required_seedlings']}"
    )

    c50 = create_contract(lo["id"], o2["id"], z_dst["id"],
                          acres=50, trees_per_acre=400, contingency_pct=0.1)
    assert c50["required_seedlings"] == 23000, (
        f"ceil(50 * 400 * 1.15) = 23000 with the surcharge at exactly 50 acres, "
        f"got {c50['required_seedlings']}"
    )


def _under_allocated_world(api):
    """Contract requiring 18060 seedlings with only 10000 allocated; site prep
    recorded and verified; not yet marked ready."""
    ctx = setup_ready_world(
        acres=40, trees_per_acre=430, contingency_pct=0.05,
        order_quantity=19000, allocation_quantity=10000,
        do_mark_ready=False,
    )
    return ctx


def test_mark_ready_under_allocated_rejected(api):
    """PRD §3.5: "Marking a contract ready moves it from `SITE_PREP` or
    `BLOCKED` to `READY_TO_PLANT` and requires two things: verified site prep,
    and a fully covered supply order whose `allocated_quantity` reaches the
    contract's `required_seedlings` — a shortfall is rejected with
    `ERR_ORDER_UNDER_ALLOCATED`."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_rejected_when_order_under_allocated
    """
    ctx = _under_allocated_world(api)
    assert ctx["required_seedlings"] == 18060
    assert ctx["order"]["allocated_quantity"] == 10000

    res = api.mark_ready(ctx["contract"]["id"], CO)
    validate_error(res, ApiErrorId.ERR_ORDER_UNDER_ALLOCATED)


def test_mark_ready_under_allocated_no_transition(api):
    """PRD §3.5: "Marking a contract ready moves it from `SITE_PREP` or
    `BLOCKED` to `READY_TO_PLANT` and requires two things: verified site prep,
    and a fully covered supply order whose `allocated_quantity` reaches the
    contract's `required_seedlings` — a shortfall is rejected with
    `ERR_ORDER_UNDER_ALLOCATED`."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_rejected_when_order_under_allocated
    """
    ctx = _under_allocated_world(api)
    res = api.mark_ready(ctx["contract"]["id"], CO)
    validate_error(res, ApiErrorId.ERR_ORDER_UNDER_ALLOCATED)

    contract = get_success_data(api.get_planting_contract(ctx["contract"]["id"], CO))
    assert contract["status"] == "SITE_PREP", (
        f"a rejected mark-ready must leave the contract in SITE_PREP, got {contract['status']}"
    )


def test_start_planting_gate_violations(api):
    """PRD §3.5: "At least one `CONFIRMED` crew assignment of the contract must
    cover the current date within its half-open interval." and "The herbicide's
    age — the current date minus `herbicide_applied_on` — must be at least 14
    days and at most 120 days, both bounds inclusive; outside that efficacy
    window the start is rejected with `ERR_SITE_PREP_WINDOW_INVALID`."

    Design: Corner/state_machines/start_planting_gate_violations
    """
    ctx = setup_ready_world(herbicide_applied_on="2027-03-22",
                            prep_clock="2027-03-25T00:00:00Z")
    contract_id = ctx["contract"]["id"]

    set_clock("2027-04-01T00:00:00Z")
    res_no_crew = api.start_planting(contract_id, CO)
    validate_error(res_no_crew, ApiErrorId.ERR_INVALID_STATE)

    crew = create_crew()
    asg = create_assignment(crew["id"], contract_id, "2027-04-01", "2027-04-03", 4000)
    confirm_assignment(asg["id"])

    res_young_prep = api.start_planting(contract_id, CO)
    validate_error(res_young_prep, ApiErrorId.ERR_SITE_PREP_WINDOW_INVALID)

    contract = get_success_data(api.get_planting_contract(contract_id, CO))
    assert contract["status"] == "READY_TO_PLANT", (
        "neither failed start-planting attempt may move the contract; "
        f"got {contract['status']}"
    )


def test_complete_planting_below_floor_rejected(api):
    """PRD §3.5: "On the initial planting — when the contract's
    `obligation_count` is zero — the recorded quantity must be at least the
    contract's `acres` multiplied by `trees_per_acre`, with an exact match
    passing" and "Either shortfall is rejected with
    `ERR_PLANTING_QUANTITY_SHORT`." and "every `CONFIRMED` crew assignment of
    the contract is automatically marked `COMPLETED`"

    Design: Corner/validations/complete_planting_below_floor_rejected
    """
    ctx = setup_ready_world()
    contract_id = ctx["contract"]["id"]
    crew = create_crew()
    asg = create_assignment(crew["id"], contract_id, "2027-04-01", "2027-04-03", 4000)
    confirm_assignment(asg["id"])
    set_clock("2027-04-01T00:00:00Z")
    start_res = api.start_planting(contract_id, CO)
    get_success_data(start_res)

    short = api.complete_planting(contract_id, {"planted_qty": 3999}, CO)
    validate_error(short, ApiErrorId.ERR_PLANTING_QUANTITY_SHORT)

    completed = get_success_data(
        api.complete_planting(contract_id, {"planted_qty": 4000}, CO)
    )
    assert completed["status"] == "PLANTED", (
        "exactly acres * trees_per_acre (4000) must pass the floor"
    )

    asg_after = get_success_data(api.get_crew_assignment(asg["id"], CO))
    assert asg_after["status"] == "COMPLETED", (
        "a successful complete-planting auto-completes CONFIRMED assignments"
    )
