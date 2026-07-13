"""Standing meal-plan creation, weekly-meal-count calculation, suggested-contribution
pricing, referential/state guards, supersession, and OCC concurrency tests."""
from test_helpers import (
    validate_success, validate_error,
    create_assessment_payload, create_meal_plan_payload, update_client_payload,
    assert_meal_plan,
    TEST_USERS,
)
from test_helpers.fixtures import (
    setup_active_client_with_plan,
    setup_assessed_client_with_plan,
    setup_active_client_with_scheduled_delivery,
    create_active_route,
    create_assessed_client,
    get_client_version,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
NUTRITION = TEST_USERS["nutritionist_headers"]
ROUTE_MGR = TEST_USERS["route_manager_headers"]


# ---------------------------------------------------------------------------
# Suggested-contribution: provisional vs reconciled (dual-variant calc)
# ---------------------------------------------------------------------------
def test_provisional_monthly_contribution_at_intake_tier(api):
    """PRD §3.4: "It is the base meal cost of 725 cents multiplied by the tier factor for
    the client's `income_tier` — 0.15 for `TIER_A`, 0.35 for `TIER_B`, and 0.55 for
    `TIER_C` — with that single product rounded half-up to a whole number of cents."
    PRD §3.4: "The client-level monthly `suggested_contribution_cents` is that rounded
    per-meal amount multiplied by the projected monthly meals, where projected monthly
    meals is the active plan's `weekly_meal_count` multiplied by 4 weeks per month."

    Design: Difficulty/dual_variant_calc/contribution_provisional_vs_reconciled
    """
    # TIER_A (income 120000, household 1), HOT plan meals_per_day 2, delivery_days x3 -> weekly 6.
    # per-meal = round_half_up(725 * 0.15) = 109; monthly = 109 * (6 * 4) = 2616.
    scenario = setup_active_client_with_plan(api)
    assert scenario["client"]["income_tier"] == "TIER_A"
    summary = validate_success(api.get_client_summary(scenario["client"]["id"], ROUTE_MGR), 200)
    assert summary["suggested_contribution_cents"] == 2616, (
        f"expected provisional 2616, got {summary['suggested_contribution_cents']}"
    )


def test_reconciled_monthly_contribution_after_income_update(api):
    """PRD §3.1: "the client's suggested contribution is re-derived from the new tier — the
    reconciled figure replacing the one computed at intake, with the difference between them
    being the reconciliation delta."
    PRD §3.4: "The client-level monthly `suggested_contribution_cents` is that rounded
    per-meal amount multiplied by the projected monthly meals, where projected monthly
    meals is the active plan's `weekly_meal_count` multiplied by 4 weeks per month."

    Design: Difficulty/dual_variant_calc/contribution_provisional_vs_reconciled
    """
    scenario = setup_active_client_with_plan(api)
    client_id = scenario["client"]["id"]
    provisional = validate_success(api.get_client_summary(client_id, ROUTE_MGR), 200)
    assert provisional["suggested_contribution_cents"] == 2616
    # PATCH income to 200000 -> ratio 1.59 -> TIER_B; per-meal round_half_up(725*0.35)=254;
    # monthly = 254 * 24 = 6096.
    version = get_client_version(api, client_id)
    patched = validate_success(
        api.update_client(client_id, update_client_payload(version, monthly_income_cents=200000), INTAKE), 200
    )
    assert patched["income_tier"] == "TIER_B"
    reconciled = validate_success(api.get_client_summary(client_id, ROUTE_MGR), 200)
    assert reconciled["suggested_contribution_cents"] == 6096, (
        f"expected reconciled 6096, got {reconciled['suggested_contribution_cents']}"
    )
    assert reconciled["suggested_contribution_cents"] != provisional["suggested_contribution_cents"]


# ---------------------------------------------------------------------------
# Suggested-contribution: pinned round-per-meal-then-multiply
# ---------------------------------------------------------------------------
def test_per_meal_contribution_rounds_half_up(api):
    """PRD §3.4: "It is the base meal cost of 725 cents multiplied by the tier factor for
    the client's `income_tier` — 0.15 for `TIER_A`, 0.35 for `TIER_B`, and 0.55 for
    `TIER_C` — with that single product rounded half-up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/suggested_contribution_round_per_meal_then_multiply
    """
    # TIER_B (income 200000): 725 * 0.35 = 253.75 -> round_half_up -> 254.
    scenario = setup_active_client_with_plan(api, client_overrides={"monthly_income_cents": 200000})
    assert scenario["client"]["income_tier"] == "TIER_B"
    plan = validate_success(api.get_meal_plan(scenario["meal_plan"]["id"], ROUTE_MGR), 200)
    assert plan["suggested_contribution_per_meal_cents"] == 254, (
        f"expected per-meal 254, got {plan['suggested_contribution_per_meal_cents']}"
    )


def test_monthly_contribution_multiplies_already_rounded_per_meal(api):
    """PRD §2.6: "All monthly and aggregate money totals are then formed as exact integer
    products or sums of already-rounded per-meal figures and recorded amounts — they are
    never re-rounded."

    Design: Difficulty/combinatorial_formula/suggested_contribution_round_per_meal_then_multiply
    """
    # per-meal 254 * 24 projected meals = 6096 (round-per-meal-then-multiply);
    # multiply-then-round would give round(725*0.35*24)=6090.
    scenario = setup_active_client_with_plan(api, client_overrides={"monthly_income_cents": 200000})
    summary = validate_success(api.get_client_summary(scenario["client"]["id"], ROUTE_MGR), 200)
    assert summary["suggested_contribution_cents"] == 6096, (
        f"expected monthly 6096, got {summary['suggested_contribution_cents']}"
    )
    assert summary["suggested_contribution_cents"] != 6090


# ---------------------------------------------------------------------------
# weekly_meal_count / delivery meal_count meal_type branch
# ---------------------------------------------------------------------------
def test_frozen_plan_weekly_and_delivery_meal_count(api):
    """PRD §3.4: "For a `FROZEN` plan, meals arrive in a single weekly bulk run covering a
    full seven-day week, so the weekly count is `meals_per_day` multiplied by 7, capped at
    a maximum of 21 meals per week."
    PRD §3.5: "For a `FROZEN` plan, the single weekly bulk run carries the whole week's
    meals, so the delivery's `meal_count` equals the plan's `weekly_meal_count`."

    Design: Difficulty/combinatorial_formula/weekly_meal_count_meal_type_branch_min_cap
    """
    scenario = setup_active_client_with_scheduled_delivery(
        api, scheduled_date="2026-03-02", meal_type="FROZEN", meals_per_day=2, delivery_days=["MON"]
    )
    assert scenario["meal_plan"]["weekly_meal_count"] == 14, "FROZEN 2*7 = 14"
    assert scenario["delivery"]["meal_count"] == 14, "FROZEN delivery carries the whole week"


def test_hot_plan_weekly_and_delivery_meal_count(api):
    """PRD §3.4: "For a `HOT` or `THERAPEUTIC` plan, fresh meals arrive only on each service
    day, so the weekly count is `meals_per_day` multiplied by the number of `delivery_days`,
    again capped at 21."
    PRD §3.5: "For a `HOT` or `THERAPEUTIC` plan, each service-day delivery carries that
    day's meals, so the delivery's `meal_count` equals the plan's `meals_per_day`."

    Design: Difficulty/combinatorial_formula/weekly_meal_count_meal_type_branch_min_cap
    """
    scenario = setup_active_client_with_scheduled_delivery(
        api, scheduled_date="2026-03-09", meal_type="HOT", meals_per_day=2, delivery_days=["MON", "WED", "FRI"]
    )
    assert scenario["meal_plan"]["weekly_meal_count"] == 6, "HOT 2*3 = 6"
    assert scenario["delivery"]["meal_count"] == 2, "HOT delivery carries that day's meals"


def test_frozen_weekly_meal_count_capped_at_21(api):
    """PRD §3.4: "For a `FROZEN` plan, meals arrive in a single weekly bulk run covering a
    full seven-day week, so the weekly count is `meals_per_day` multiplied by 7, capped at
    a maximum of 21 meals per week."

    Design: Corner/calculations/frozen_weekly_meal_count_capped_at_21
    """
    # meals_per_day 3 -> 3*7 = 21 -> min(21, 21) = 21 (cap boundary).
    scenario = setup_assessed_client_with_plan(api, meal_type="FROZEN", meals_per_day=3, delivery_days=["MON"])
    plan = scenario["meal_plan"]
    assert_meal_plan(plan)
    assert plan["weekly_meal_count"] == 21


# ---------------------------------------------------------------------------
# Plan-create referential / state / safety guards
# ---------------------------------------------------------------------------
def test_meal_plan_route_zone_mismatch_rejected(api):
    """PRD §3.4: "The route's `zone` must equal the client's `address_zone`, else
    `ERR_ROUTE_ZONE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/route_zone_mismatch_rejected
    """
    ar = create_active_route(api, zone="Z2")  # route in Z2
    ac = create_assessed_client(api)           # client default zone Z1
    client_id = ac["client"]["id"]
    version = get_client_version(api, client_id)
    payload = create_meal_plan_payload(ac["assessment"]["id"], ar["route"]["id"], version)
    resp = api.create_meal_plan(client_id, payload, ROUTE_MGR)
    validate_error(resp, "ERR_ROUTE_ZONE_MISMATCH", 422)


def test_meal_plan_on_draft_assessment_rejected(api):
    """PRD §3.4: "The referenced assessment must be `FINALIZED`, else
    `ERR_ASSESSMENT_NOT_FINALIZED` (HTTP 409)."

    Design: Corner/validations/assessment_not_finalized_on_plan_rejected
    """
    ar = create_active_route(api)
    ac = create_assessed_client(api)  # assessment1 FINALIZED -> client ASSESSED
    client_id = ac["client"]["id"]
    # A second assessment left in DRAFT.
    draft = validate_success(
        api.create_assessment(client_id, create_assessment_payload(nutrition_determine_points=2, adl_score=1), NUTRITION), 201
    )
    version = get_client_version(api, client_id)
    payload = create_meal_plan_payload(draft["id"], ar["route"]["id"], version)
    resp = api.create_meal_plan(client_id, payload, ROUTE_MGR)
    validate_error(resp, "ERR_ASSESSMENT_NOT_FINALIZED", 409)


def test_therapeutic_plan_diet_type_mismatch_rejected(api):
    """PRD §3.4: "When the plan's `meal_type` is `THERAPEUTIC`, the referenced assessment
    must have `therapeutic_diet_required` set to true and its `therapeutic_diet_type` must
    equal the plan's `therapeutic_diet_type`; a mismatch on either yields
    `ERR_THERAPEUTIC_DIET_MISMATCH` (HTTP 422)."

    Design: Corner/validations/therapeutic_diet_mismatch_rejected
    """
    ar = create_active_route(api)
    ac = create_assessed_client(
        api, assessment_overrides={"therapeutic_diet_required": True, "therapeutic_diet_type": "RENAL"}
    )
    client_id = ac["client"]["id"]
    version = get_client_version(api, client_id)
    payload = create_meal_plan_payload(
        ac["assessment"]["id"], ar["route"]["id"], version,
        meal_type="THERAPEUTIC", therapeutic_diet_type="DIABETIC",
    )
    resp = api.create_meal_plan(client_id, payload, ROUTE_MGR)
    validate_error(resp, "ERR_THERAPEUTIC_DIET_MISMATCH", 422)


# ---------------------------------------------------------------------------
# Cancellation cascade / supersession / OCC
# ---------------------------------------------------------------------------
def test_cancel_meal_plan_cascades_scheduled_deliveries(api):
    """PRD §3.4: "it moves the plan from `ACTIVE` to `CANCELLED`, cancels every one of the
    plan's `SCHEDULED` deliveries as a cascade, and increments the plan's `version` by 1."

    Design: Corner/state_machines/meal_plan_cancel_cascades_scheduled_deliveries
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02")
    plan_id = scenario["meal_plan"]["id"]
    delivery_id = scenario["delivery"]["id"]
    cancelled = validate_success(api.cancel_meal_plan(plan_id, ROUTE_MGR), 200)
    assert cancelled["status"] == "CANCELLED"
    delivery = validate_success(api.get_delivery(delivery_id, ROUTE_MGR), 200)
    assert delivery["status"] == "CANCELLED", "the plan's SCHEDULED delivery is cascaded to CANCELLED"


def test_new_meal_plan_supersedes_prior_active_plan_immediately(api):
    """PRD §3.4: "creating a new plan supersedes the client's prior `ACTIVE` plan: that
    prior plan moves from `ACTIVE` to `CANCELLED`, every one of its `SCHEDULED` deliveries
    is cancelled in turn, and the client's `version` is incremented by 1."

    Design: Corner/consistency_model/meal_plan_supersede_visible_immediately
    """
    scenario = setup_assessed_client_with_plan(api)
    client_id = scenario["client"]["id"]
    plan1_id = scenario["meal_plan"]["id"]
    version = get_client_version(api, client_id)
    payload = create_meal_plan_payload(scenario["assessment"]["id"], scenario["route"]["id"], version)
    plan2 = validate_success(api.create_meal_plan(client_id, payload, ROUTE_MGR), 201)
    plan1 = validate_success(api.get_meal_plan(plan1_id, ROUTE_MGR), 200)
    assert plan1["status"] == "CANCELLED"
    assert plan2["status"] == "ACTIVE"


def test_stale_client_version_on_second_meal_plan_create_rejected(api):
    """PRD §2.5: "when a meal-plan creation is requested, the submitted
    `expected_client_version` must equal the target `Client`'s current `version`; if
    another writer has advanced the client's `version` since the caller last read it, the
    create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_client_version_on_meal_plan_create
    """
    ar = create_active_route(api)
    ac = create_assessed_client(api)
    client_id = ac["client"]["id"]
    observed_version = get_client_version(api, client_id)
    payload = create_meal_plan_payload(ac["assessment"]["id"], ar["route"]["id"], observed_version)
    # First create succeeds and advances Client.version past observed_version.
    validate_success(api.create_meal_plan(client_id, payload, ROUTE_MGR), 201)
    # Second create replays the now-stale observed_version.
    stale_payload = create_meal_plan_payload(ac["assessment"]["id"], ar["route"]["id"], observed_version)
    resp = api.create_meal_plan(client_id, stale_payload, ROUTE_MGR)
    validate_error(resp, "ERR_STALE_CLIENT_VERSION", 412)
