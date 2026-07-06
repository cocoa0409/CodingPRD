"""Compensating-invariant conservation: the wallet ledger under skip/resume, the
grocery total under substitute/reverse-substitute, and the vacation-window guard.

Queue A (Difficulty): compensating_invariant.
Queue B (Corner): state_machines (skip precondition).
"""
from test_helpers import (
    validate_error, get_success_data,
    ingredient, substitute_payload,
    create_client, create_chef, create_active_plan, create_draft_menu, add_meal,
    skip, resume, set_clock, get_client, get_menu, get_meal,
    setup_approved_single_meal, make_client_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

_BOWL = {"meal_name": "Bowl", "meal_slot": "LUNCH",
         "ingredients": [ingredient("rice", 1, "batch", 4000)]}


# ─── compensating_invariant / wallet skip then resume ─────────────────

def test_skip_grants_wallet_credit(api):
    """PRD §3.8: "Skipping moves the menu from `APPROVED` to `SKIPPED` and grants a
    credit: the client's `weekly_base_fee_cents` is added to their `wallet_credit_cents`."

    Design: Difficulty/compensating_invariant/wallet_credit_skip_then_resume_conserved
    """
    ctx = setup_approved_single_meal(client_kwargs={"weekly_base_fee_cents": 5000},
                                     meal_kwargs=_BOWL)
    skip(ctx["menu"], ctx["client"])
    assert get_client(ctx["client"]["id"])["wallet_credit_cents"] == 5000


def test_resume_reverses_skip_credit_to_zero(api):
    """PRD §3.8: "Resuming a skipped week moves the menu from `SKIPPED` back to
    `APPROVED` and compensates exactly: the same `weekly_base_fee_cents` that the skip
    added is subtracted back out of the wallet."

    Design: Difficulty/compensating_invariant/wallet_credit_skip_then_resume_conserved
    """
    ctx = setup_approved_single_meal(client_kwargs={"weekly_base_fee_cents": 5000},
                                     meal_kwargs=_BOWL)
    skip(ctx["menu"], ctx["client"])
    resume(ctx["menu"], ctx["client"])
    assert get_client(ctx["client"]["id"])["wallet_credit_cents"] == 0
    assert get_menu(ctx["menu"]["id"])["status"] == "APPROVED"


# ─── compensating_invariant / grocery substitute then reverse ─────────

def test_substitute_recomputes_menu_grocery_cost(api):
    """PRD §3.5: "Both the meal's `meal_grocery_cost_cents` and the parent menu's
    `grocery_cost_cents` are then recomputed."

    Design: Difficulty/compensating_invariant/grocery_cost_substitute_then_reverse_conserved
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    meal = add_meal(menu, chef, meal_name="Roast", meal_slot="DINNER",
                    ingredients=[ingredient("beef", 1, "kg", 5000)])
    from test_helpers import make_chef_headers
    get_success_data(api.substitute_ingredient(
        meal["id"], substitute_payload("beef", "lamb", 1, "kg", 8000),
        make_chef_headers(chef["id"])))
    assert get_menu(menu["id"])["grocery_cost_cents"] == 8000


def test_reverse_substitute_conserves_menu_grocery_cost(api):
    """PRD §3.5: "The grocery-cost figure is a conserved quantity: substituting an
    ingredient and then reverse-substituting back leaves the menu total equal to the
    sum of the active line items, because the swapped-out ingredient no longer
    contributes and the added one does."

    Design: Difficulty/compensating_invariant/grocery_cost_substitute_then_reverse_conserved
    """
    from test_helpers import make_chef_headers
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    chef_h = make_chef_headers(chef["id"])
    meal = add_meal(menu, chef, meal_name="Roast", meal_slot="DINNER",
                    ingredients=[ingredient("beef", 1, "kg", 5000)])
    get_success_data(api.substitute_ingredient(
        meal["id"], substitute_payload("beef", "lamb", 1, "kg", 8000), chef_h))
    assert get_menu(menu["id"])["grocery_cost_cents"] == 8000
    get_success_data(api.substitute_ingredient(
        meal["id"], substitute_payload("lamb", "beef", 1, "kg", 5000), chef_h))
    assert get_menu(menu["id"])["grocery_cost_cents"] == 5000


# ─── state_machines corner / skip after week started ──────────────────

def test_skip_after_week_started_rejected(api):
    """PRD §3.8: "Both skip and resume are only permitted while the logical clock is
    strictly before the menu's `week_start_date`; once the service week has begun,
    either attempt is rejected with `ERR_WEEK_ALREADY_STARTED`."

    Design: Corner/state_machines/skip_after_week_started_rejected
    """
    ctx = setup_approved_single_meal(meal_kwargs=_BOWL,
                                     week_start_date="2026-03-09T00:00:00Z")
    # Advance the logical clock to the week start (no longer strictly before it).
    set_clock("2026-03-09T00:00:00Z")
    res = api.skip_menu(ctx["menu"]["id"], make_client_headers(ctx["client"]["id"]))
    validate_error(res, "ERR_WEEK_ALREADY_STARTED")
