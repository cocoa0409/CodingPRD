"""Validation-precedence conflicts: when two rules of different categories co-occur,
the earlier-ordered check (per PRD §2.8) determines the returned error."""
from test_helpers import (
    validate_success, validate_error,
    create_meal_plan_payload, create_delivery_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_active_route,
    create_assessed_client,
    create_meal_plan_for,
    get_client_version,
    schedule_delivery,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
ROUTE_MGR = TEST_USERS["route_manager_headers"]


def _setup_state_vs_capacity(api):
    """Route (cap 2) full for 2026-03-02 via an ACTIVE client H; plus an ASSESSED client A
    with an ACTIVE plan on the same route. Returns A's ids."""
    ar = create_active_route(api, max_meals_per_run=2)
    route_id = ar["route"]["id"]
    # Client H: ACTIVE, HOT plan meal_count 2, one scheduled delivery filling capacity.
    hc = create_assessed_client(api)
    h_plan = create_meal_plan_for(api, hc["client"]["id"], hc["assessment"]["id"], route_id,
                                  meal_type="HOT", meals_per_day=2)
    validate_success(api.activate_client(hc["client"]["id"], INTAKE), 200)
    schedule_delivery(api, h_plan["id"], "2026-03-02")
    # Client A: only ASSESSED (never activated), ACTIVE plan on the same route.
    ac = create_assessed_client(api)
    a_plan = create_meal_plan_for(api, ac["client"]["id"], ac["assessment"]["id"], route_id,
                                  meal_type="HOT", meals_per_day=2)
    return {"a_client_id": ac["client"]["id"], "a_plan_id": a_plan["id"]}


def test_client_not_active_beats_route_capacity(api):
    """PRD §2.8: "(9) state preconditions on the target and referenced resources ... (13)
    other business constraints such as zone matching and route capacity ... Lower-numbered
    checks always take precedence, so a request that violates several rules surfaces the
    earliest-ordered failure."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_delivery_create
    """
    ctx = _setup_state_vs_capacity(api)
    # Client A is ASSESSED (state violation, check 9) AND the route is full (capacity, check 13).
    resp = api.create_delivery(create_delivery_payload(ctx["a_plan_id"], "2026-03-02"), ROUTE_MGR)
    validate_error(resp, "ERR_CLIENT_NOT_ACTIVE", 409)


def test_capacity_surfaces_once_state_violation_cleared(api):
    """PRD §2.8: "(9) state preconditions on the target and referenced resources ... (13)
    other business constraints such as zone matching and route capacity ... Lower-numbered
    checks always take precedence, so a request that violates several rules surfaces the
    earliest-ordered failure."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_delivery_create
    """
    ctx = _setup_state_vs_capacity(api)
    # Remove the state violation by activating client A; only the capacity violation remains.
    validate_success(api.activate_client(ctx["a_client_id"], INTAKE), 200)
    resp = api.create_delivery(create_delivery_payload(ctx["a_plan_id"], "2026-03-02"), ROUTE_MGR)
    validate_error(resp, "ERR_ROUTE_CAPACITY_EXCEEDED", 409)


def _setup_referential_vs_therapeutic(api):
    """Two ASSESSED clients A and B, each with a FINALIZED assessment (therapeutic_diet
    _required false), and an ACTIVE route in zone Z1. Returns ids and A's observed version."""
    ar = create_active_route(api)
    route_id = ar["route"]["id"]
    ac = create_assessed_client(api)
    bc = create_assessed_client(api, client_overrides={"phone": "555-0104"})
    a_version = get_client_version(api, ac["client"]["id"])
    return {
        "route_id": route_id,
        "a_client_id": ac["client"]["id"],
        "a_assessment_id": ac["assessment"]["id"],
        "b_assessment_id": bc["assessment"]["id"],
        "a_version": a_version,
    }


def test_assessment_client_mismatch_beats_therapeutic_diet_mismatch(api):
    """PRD §2.8: "(8) referential consistency between referenced resources; (9) state
    preconditions on the target and referenced resources; (10) cross-entity state
    preconditions; (11) domain safety checks such as therapeutic-diet matching ... Lower-
    numbered checks always take precedence, so a request that violates several rules
    surfaces the earliest-ordered failure."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_therapeutic_safety_on_plan_create
    """
    ctx = _setup_referential_vs_therapeutic(api)
    # assessment_id belongs to client B (referential, check 8) AND meal_type THERAPEUTIC on an
    # assessment with therapeutic_diet_required false (safety, check 11) — referential wins.
    payload = create_meal_plan_payload(
        ctx["b_assessment_id"], ctx["route_id"], ctx["a_version"],
        meal_type="THERAPEUTIC", therapeutic_diet_type="RENAL",
    )
    resp = api.create_meal_plan(ctx["a_client_id"], payload, ROUTE_MGR)
    validate_error(resp, "ERR_ASSESSMENT_CLIENT_MISMATCH", 422)


def test_therapeutic_mismatch_surfaces_once_referential_cleared(api):
    """PRD §2.8: "(8) referential consistency between referenced resources ... (11) domain
    safety checks such as therapeutic-diet matching ... Lower-numbered checks always take
    precedence, so a request that violates several rules surfaces the earliest-ordered
    failure."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_therapeutic_safety_on_plan_create
    """
    ctx = _setup_referential_vs_therapeutic(api)
    # Use A's OWN assessment (clears the referential violation); the THERAPEUTIC safety
    # violation (assessment's therapeutic_diet_required is false) now surfaces.
    payload = create_meal_plan_payload(
        ctx["a_assessment_id"], ctx["route_id"], ctx["a_version"],
        meal_type="THERAPEUTIC", therapeutic_diet_type="RENAL",
    )
    resp = api.create_meal_plan(ctx["a_client_id"], payload, ROUTE_MGR)
    validate_error(resp, "ERR_THERAPEUTIC_DIET_MISMATCH", 422)
