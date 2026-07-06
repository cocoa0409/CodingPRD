"""The weekly-menu revision loop and the four approval gates.

Queue A (Difficulty): non_linear_state_machine, cross_entity_state_dependency,
priority_pair_validation_conflict, boundary_precision_check.
Queue B (Corner): state_machines and validations sections.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ingredient, substitute_payload, feedback_payload,
    create_client, create_chef, create_active_plan, create_draft_menu, add_meal,
    propose, approve, reject, get_menu, get_meal, get_client,
    make_client_headers, make_chef_headers,
    setup_proposed_single_meal, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── non_linear_state_machine / cyclic_menu_reject_revision_loop ───────

def test_reject_returns_proposed_menu_to_draft(api):
    """PRD §3.4: "Rejecting it returns the menu from `PROPOSED` back to `DRAFT`,
    handing it to the chef for revision; this back-edge is intentional, so a menu
    can loop `DRAFT` → `PROPOSED` → `DRAFT` → `PROPOSED` as many times as needed
    before the household is satisfied."

    Design: Difficulty/non_linear_state_machine/cyclic_menu_reject_revision_loop
    """
    ctx = setup_proposed_single_meal(meal_kwargs={
        "meal_name": "Bowl", "meal_slot": "LUNCH",
        "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    rejected = validate_success(api.reject_menu(ctx["menu"]["id"],
                                make_client_headers(ctx["client"]["id"])), 200)
    assert rejected["status"] == "DRAFT"


def test_revision_loop_reproposes_then_approves(api):
    """PRD §3.4: "this back-edge is intentional, so a menu can loop `DRAFT` →
    `PROPOSED` → `DRAFT` → `PROPOSED` as many times as needed before the household
    is satisfied."
    PRD §3.4: "Approving it advances the menu from `PROPOSED` to `APPROVED`, but only
    after four gates all pass, evaluated after the base state check that the menu is
    actually `PROPOSED`".

    Design: Difficulty/non_linear_state_machine/cyclic_menu_reject_revision_loop
    """
    ctx = setup_proposed_single_meal(meal_kwargs={
        "meal_name": "Bowl", "meal_slot": "LUNCH",
        "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    client, chef, menu = ctx["client"], ctx["chef"], ctx["menu"]
    reject(menu, client)
    assert get_menu(menu["id"])["status"] == "DRAFT"
    reproposed = validate_success(api.propose_menu(menu["id"], make_chef_headers(chef["id"])), 200)
    assert reproposed["status"] == "PROPOSED"
    approved = validate_success(api.approve_menu(menu["id"], make_client_headers(client["id"])), 200)
    assert approved["status"] == "APPROVED"


# ─── state_machines corners: propose preconditions ────────────────────

def test_propose_menu_with_no_meals_rejected(api):
    """PRD §3.4: "A propose attempted on a menu with zero meals is rejected with
    `ERR_MENU_HAS_NO_MEALS`."

    Design: Corner/state_machines/propose_menu_with_no_meals_rejected
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    res = api.propose_menu(menu["id"], make_chef_headers(chef["id"]))
    validate_error(res, "ERR_MENU_HAS_NO_MEALS")


def test_propose_already_proposed_menu_rejected(api):
    """PRD §3.4: "Once a menu has meals on it, the authoring chef proposes it to the
    household, advancing the menu from `DRAFT` to `PROPOSED`."
    PRD §3.9: "an illegal menu transition is rejected with `ERR_INVALID_MENU_STATE`".

    Design: Corner/state_machines/propose_twice_idempotency_rejected
    """
    ctx = setup_proposed_single_meal(meal_kwargs={
        "meal_name": "One", "meal_slot": "LUNCH",
        "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    res = api.propose_menu(ctx["menu"]["id"], make_chef_headers(ctx["chef"]["id"]))
    validate_error(res, "ERR_INVALID_MENU_STATE")


# ─── cross_entity_state_dependency / approve_requires_dietary_plan_active ─

def test_second_plan_supersedes_prior_active_plan(api):
    """PRD §3.2: "When a client creates a newer plan, the system supersedes the prior
    one: the previously `ACTIVE` plan for that client transitions to `SUPERSEDED`, and
    the new plan becomes the `ACTIVE` one."

    Design: Difficulty/cross_entity_state_dependency/approve_requires_dietary_plan_active
    """
    client = create_client()
    plan1 = create_active_plan(client)
    refreshed = get_client(client["id"])
    create_active_plan(refreshed, daily_calorie_target=2200)
    plan1_after = validate_success(api.get_dietary_plan(plan1["id"], ADMIN), 200)
    assert plan1_after["status"] == "SUPERSEDED"


def test_approve_menu_against_superseded_plan_rejected(api):
    """PRD §3.4: "The `DietaryPlan` referenced by the menu's `dietary_plan_id` must
    currently be in `ACTIVE` status; if it has been superseded, approval is rejected
    with `ERR_DIETARY_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/approve_requires_dietary_plan_active
    """
    client = create_client()
    chef = create_chef()
    plan1 = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan1)
    add_meal(menu, chef, meal_name="Bowl", meal_slot="LUNCH",
             ingredients=[ingredient("rice", 1, "batch", 4000)])
    propose(menu, chef)
    # A new plan supersedes plan1 (client version has advanced since plan1's create).
    refreshed = get_client(client["id"])
    create_active_plan(refreshed, daily_calorie_target=2200)
    res = api.approve_menu(menu["id"], make_client_headers(client["id"]))
    validate_error(res, "ERR_DIETARY_PLAN_NOT_ACTIVE")


# ─── validations corners: single-gate approval failures ───────────────

def test_approve_over_budget_rejected(api):
    """PRD §3.4: "The menu's `grocery_cost_cents` must be no greater than the client's
    `weekly_grocery_budget_cents`; if it exceeds the budget, approval is rejected with
    `ERR_GROCERY_BUDGET_EXCEEDED`."

    Design: Corner/validations/approve_over_budget_pure_fiscal_rejected
    """
    ctx = setup_proposed_single_meal(
        client_kwargs={"weekly_grocery_budget_cents": 10000},
        meal_kwargs={"meal_name": "Lux", "meal_slot": "DINNER",
                     "ingredients": [ingredient("truffle", 1, "kg", 30000)]})
    res = api.approve_menu(ctx["menu"]["id"], make_client_headers(ctx["client"]["id"]))
    validate_error(res, "ERR_GROCERY_BUDGET_EXCEEDED")


def test_approve_equipment_unavailable_rejected(api):
    """PRD §3.4: "Every meal's `required_equipment` must be a subset of the client's
    `available_equipment`; if any required piece is missing from the kitchen, approval
    is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Corner/validations/approve_equipment_unavailable_pure_constraint_rejected
    """
    ctx = setup_proposed_single_meal(
        client_kwargs={"available_equipment": ["OVEN"]},
        meal_kwargs={"meal_name": "SV", "meal_slot": "DINNER",
                     "required_equipment": ["SOUS_VIDE"],
                     "ingredients": [ingredient("egg", 1, "ea", 4000)]})
    res = api.approve_menu(ctx["menu"]["id"], make_client_headers(ctx["client"]["id"]))
    validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")


def test_substitute_introducing_allergen_rejected(api):
    """PRD §3.5: "if the replacement (or any remaining active ingredient) would carry
    an allergen listed in the client's dietary-plan `allergen_tags`, the substitution
    is rejected with `ERR_ALLERGEN_CONFLICT`."

    Design: Corner/validations/substitute_introduces_allergen_rejected
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client, allergen_tags=["NUTS"])
    menu = create_draft_menu(client, chef, plan)
    meal = add_meal(menu, chef, meal_name="Saute", meal_slot="DINNER",
                    ingredients=[ingredient("oil", 1, "cup", 2000)])
    res = api.substitute_ingredient(
        meal["id"],
        substitute_payload("oil", "peanut oil", 1, "cup", 3000, replacement_allergen_tags=["NUTS"]),
        make_chef_headers(chef["id"]),
    )
    validate_error(res, "ERR_ALLERGEN_CONFLICT")
    # The rejected substitution leaves the meal's cost unchanged.
    assert get_meal(meal["id"])["meal_grocery_cost_cents"] == 2000


def test_feedback_before_meal_cooked_rejected(api):
    """PRD §3.5: "Feedback attempted on a meal that has not yet reached `COOKED` is
    rejected with `ERR_MEAL_NOT_COOKED`."

    Design: Corner/validations/feedback_before_cooked_rejected
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    meal = add_meal(menu, chef, meal_name="Raw", meal_slot="LUNCH",
                    ingredients=[ingredient("rice", 1, "batch", 4000)])
    res = api.feedback_meal(meal["id"], feedback_payload(5, "great"),
                            make_client_headers(client["id"]))
    validate_error(res, "ERR_MEAL_NOT_COOKED")


# ─── priority_pair_validation_conflict / conflict_state_beats_fiscal ──

def test_approve_draft_over_budget_reports_state_not_fiscal(api):
    """PRD §3.4: "Approving it advances the menu from `PROPOSED` to `APPROVED`, but
    only after four gates all pass, evaluated after the base state check that the menu
    is actually `PROPOSED`".
    PRD §3.9: "an illegal menu transition is rejected with `ERR_INVALID_MENU_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_fiscal_on_approve
    """
    # DRAFT (never proposed) menu whose grocery 30000 also exceeds the 10000 budget.
    client = create_client(weekly_grocery_budget_cents=10000)
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    add_meal(menu, chef, meal_name="Lux", meal_slot="DINNER",
             ingredients=[ingredient("caviar", 1, "kg", 30000)])
    # Approve without proposing: the base state check fires before the budget gate.
    res = api.approve_menu(menu["id"], make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_MENU_STATE")


def test_approve_proposed_over_budget_reports_fiscal(api):
    """PRD §3.4: "The menu's `grocery_cost_cents` must be no greater than the client's
    `weekly_grocery_budget_cents`; if it exceeds the budget, approval is rejected with
    `ERR_GROCERY_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_fiscal_on_approve
    """
    # Same over-budget grocery, but the menu IS proposed, so the fiscal gate is reached.
    ctx = setup_proposed_single_meal(
        client_kwargs={"weekly_grocery_budget_cents": 10000},
        meal_kwargs={"meal_name": "Lux", "meal_slot": "DINNER",
                     "ingredients": [ingredient("caviar", 1, "kg", 30000)]})
    res = api.approve_menu(ctx["menu"]["id"], make_client_headers(ctx["client"]["id"]))
    validate_error(res, "ERR_GROCERY_BUDGET_EXCEEDED")


# ─── boundary_precision_check / boundary_markup_tier_at_exactly_15000 ─

def test_grocery_exactly_15000_selects_12pct_tier(api):
    """PRD §3.9: "15 percent when the frozen grocery cost is below 15000 cents, 12
    percent when it is at least 15000 but below 30000 cents, and 10 percent when it is
    30000 cents or more (the boundaries are inclusive at the lower tier's exit, so a
    grocery cost of exactly 15000 selects 12 percent while 14999 selects 15 percent,
    and exactly 30000 selects 10 percent)."

    Design: Difficulty/boundary_precision_check/boundary_markup_tier_at_exactly_15000
    """
    ctx = setup_proposed_single_meal(meal_kwargs={
        "meal_name": "Mid", "meal_slot": "DINNER",
        "ingredients": [ingredient("salmon", 1, "kg", 15000)]})
    approved = validate_success(
        api.approve_menu(ctx["menu"]["id"], make_client_headers(ctx["client"]["id"])), 200)
    assert approved["grocery_cost_cents"] == 15000
    assert approved["markup_pct_snapshot"] == 12


def test_grocery_14999_selects_15pct_tier(api):
    """PRD §3.9: "a grocery cost of exactly 15000 selects 12 percent while 14999
    selects 15 percent".

    Design: Difficulty/boundary_precision_check/boundary_markup_tier_at_exactly_15000
    """
    ctx = setup_proposed_single_meal(meal_kwargs={
        "meal_name": "Mid", "meal_slot": "DINNER",
        "ingredients": [ingredient("salmon", 1, "kg", 14999)]})
    approved = validate_success(
        api.approve_menu(ctx["menu"]["id"], make_client_headers(ctx["client"]["id"])), 200)
    assert approved["grocery_cost_cents"] == 14999
    assert approved["markup_pct_snapshot"] == 15
