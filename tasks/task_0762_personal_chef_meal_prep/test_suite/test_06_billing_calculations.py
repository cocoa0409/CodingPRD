"""Invoice gross under the two billing modes, session payouts, and payment
settlement against the wallet ledger.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): cross_cutting_complexity_layers (pay flow).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ingredient,
    create_client, create_chef, create_active_plan, create_draft_menu, add_meal,
    propose, approve, skip, schedule_session, start_session, complete_session,
    setup_approved_single_meal, setup_cooked_single_meal, cook_menu_with_meals,
    invoice_for_menu, get_client, make_client_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

_SOUP = {"meal_name": "Soup", "meal_slot": "LUNCH", "servings": 2,
         "ingredients": [ingredient("broth", 1, "batch", 3333)]}
_STEW = {"meal_name": "Stew", "meal_slot": "DINNER", "servings": 2,
         "ingredients": [ingredient("beans", 1, "batch", 3333)]}


# ─── dual_variant_calc / invoice PER_WEEK vs PER_MEAL ─────────────────

def test_per_week_invoice_gross_is_6000(api):
    """PRD §3.9: "The grocery markup itself is the frozen grocery cost multiplied by
    that tier percent, divided by 100, rounded half up to whole cents."
    PRD §3.9: "The gross amount is the sum of the base fee, the grocery markup, and the
    household surcharge."

    Design: Difficulty/dual_variant_calc/dual_variant_invoice_perweek_vs_permeal
    """
    ctx = cook_menu_with_meals("PER_WEEK", [_SOUP, _STEW], household_size=2,
                               weekly_base_fee_cents=5000)
    assert ctx["invoice"]["gross_amount_cents"] == 6000


def test_per_meal_invoice_gross_is_9600(api):
    """PRD §3.9: "for each cooked meal, take that meal's `meal_grocery_cost_cents`,
    multiply it by 120 and divide by 100 (a 20 percent markup), round that marked-up
    grocery figure half up to whole cents, and then add the client's `per_meal_fee_cents`;
    the gross amount is the sum of these per-meal charges over all cooked meals."

    Design: Difficulty/dual_variant_calc/dual_variant_invoice_perweek_vs_permeal
    """
    ctx = cook_menu_with_meals("PER_MEAL", [_SOUP, _STEW], household_size=2,
                               weekly_base_fee_cents=5000, per_meal_fee_cents=800)
    assert ctx["invoice"]["gross_amount_cents"] == 9600


# ─── combinatorial_formula / PER_WEEK tiered markup + surcharge ───────

def test_per_week_gross_combines_base_markup_and_surcharge(api):
    """PRD §3.9: "Second, a household surcharge: for each household member above the
    first two, 500 cents is charged — that is, the greater of zero and the household
    size minus two, multiplied by 500 cents. Third, the flat `weekly_base_fee_cents`.
    The gross amount is the sum of the base fee, the grocery markup, and the household
    surcharge."

    Design: Difficulty/combinatorial_formula/combinatorial_perweek_tiered_markup_and_surcharge
    """
    feast = {"meal_name": "Feast", "meal_slot": "DINNER", "servings": 4,
             "ingredients": [ingredient("steak", 1, "kg", 20000)]}
    ctx = cook_menu_with_meals("PER_WEEK", [feast], household_size=4,
                               weekly_base_fee_cents=5000)
    # 12% of 20000 = 2400 markup; (4-2)*500 = 1000 surcharge; 5000 base -> 8400.
    assert ctx["invoice"]["gross_amount_cents"] == 8400


def test_per_week_markup_snapshot_is_tier2_twelve_percent(api):
    """PRD §3.9: "12 percent when it is at least 15000 but below 30000 cents".
    PRD §3.4: "it records `markup_pct_snapshot` — the grocery markup tier percent
    selected from the frozen grocery cost, one of 15, 12, or 10".

    Design: Difficulty/combinatorial_formula/combinatorial_perweek_tiered_markup_and_surcharge
    """
    feast = {"meal_name": "Feast", "meal_slot": "DINNER", "servings": 4,
             "ingredients": [ingredient("steak", 1, "kg", 20000)]}
    ctx = cook_menu_with_meals("PER_WEEK", [feast], household_size=4,
                               weekly_base_fee_cents=5000)
    assert ctx["menu"]["markup_pct_snapshot"] == 12


# ─── combinatorial_formula / PER_MEAL round-each-then-sum ─────────────

def test_per_meal_rounds_each_meal_then_sums_to_9600(api):
    """PRD §3.9: "for each cooked meal, take that meal's `meal_grocery_cost_cents`,
    multiply it by 120 and divide by 100 (a 20 percent markup), round that marked-up
    grocery figure half up to whole cents, and then add the client's `per_meal_fee_cents`;
    the gross amount is the sum of these per-meal charges over all cooked meals."

    Design: Difficulty/combinatorial_formula/combinatorial_permeal_round_each_then_sum
    """
    ctx = cook_menu_with_meals("PER_MEAL", [_SOUP, _STEW], household_size=2,
                               per_meal_fee_cents=800)
    assert ctx["invoice"]["gross_amount_cents"] == 9600


def test_per_meal_is_not_sum_then_round(api):
    """PRD §3.9: "Each meal's marked-up grocery is rounded first and the rounded
    charges are then summed — summing the raw figures and rounding once at the end is
    explicitly not the method and would yield a different total."

    Design: Difficulty/combinatorial_formula/combinatorial_permeal_round_each_then_sum
    """
    ctx = cook_menu_with_meals("PER_MEAL", [_SOUP, _STEW], household_size=2,
                               per_meal_fee_cents=800)
    # round-each: round(3333*1.2)=4000 each; +800 fee -> 4800 each -> 9600.
    # sum-then-round would give 9599; the pinned order yields 9600.
    assert ctx["invoice"]["gross_amount_cents"] == 9600
    assert ctx["invoice"]["gross_amount_cents"] != 9599


# ─── dual_variant_calc / session payout provisional vs final ──────────

def test_provisional_payout_from_scheduled_hours(api):
    """PRD §3.6: "its `provisional_payout_cents` is fixed at this moment: it is the
    scheduled duration in hours — the difference between `scheduled_end` and
    `scheduled_start`, taken in total seconds and divided by 3600, which may be
    fractional — multiplied by the chef's `hourly_rate_cents`, rounded half up to whole
    cents."

    Design: Difficulty/dual_variant_calc/dual_variant_session_payout_provisional_vs_final
    """
    ctx = setup_approved_single_meal(meal_kwargs={
        "meal_name": "Roast", "meal_slot": "DINNER",
        "ingredients": [ingredient("chicken", 1, "kg", 4000)]})
    # Chef default rate 6000/hr; scheduled 3 hours -> 18000.
    session = schedule_session(ctx["menu"], ctx["chef"],
                               "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    assert session["provisional_payout_cents"] == 18000


def test_final_payout_from_actual_hours(api):
    """PRD §3.7: "The session's `final_payout_cents` is then set using the same payout
    formula as the provisional figure but over the actual worked interval: the actual
    duration in hours — the difference between `actual_end` and `actual_start` in total
    seconds divided by 3600 — multiplied by the chef's `hourly_rate_cents`, rounded half
    up to whole cents."

    Design: Difficulty/dual_variant_calc/dual_variant_session_payout_provisional_vs_final
    """
    ctx = setup_cooked_single_meal(
        meal_kwargs={"meal_name": "Roast", "meal_slot": "DINNER",
                     "ingredients": [ingredient("chicken", 1, "kg", 4000)]},
        scheduled_start="2026-03-03T09:00:00Z", scheduled_end="2026-03-03T12:00:00Z",
        clock_at_start="2026-03-03T09:00:00Z", clock_at_complete="2026-03-03T11:30:00Z")
    # Actual worked 2.5 hours at 6000/hr -> 15000, diverging from the 18000 provisional.
    assert ctx["session"]["final_payout_cents"] == 15000
    assert ctx["session"]["provisional_payout_cents"] == 18000


# ─── cross_cutting / pay applies wallet credit, blocks double pay ─────

def test_invoice_pay_applies_credit_and_blocks_second_pay(api):
    """PRD §3.8: "Skipping moves the menu from `APPROVED` to `SKIPPED` and grants a
    credit: the client's `weekly_base_fee_cents` is added to their `wallet_credit_cents`."
    PRD §3.9: "Payment draws down the wallet: `credit_applied_cents` is set to the lesser
    of the client's current `wallet_credit_cents` and the invoice's `gross_amount_cents`,
    that amount is subtracted from the client's wallet balance, and the invoice's
    `net_amount_cents` is set to the gross amount minus the applied credit."
    PRD §3.9: "an attempt to pay an invoice not currently `ISSUED` is rejected with
    `ERR_INVALID_INVOICE_STATE`."

    Design: Corner/cross_cutting_complexity_layers/invoice_pay_applies_wallet_credit_and_blocks_double_pay
    """
    client = create_client(billing_mode="PER_WEEK", weekly_base_fee_cents=5000)
    chef = create_chef()
    plan = create_active_plan(client)
    client_h = make_client_headers(client["id"])

    # menu1 -> approved -> skipped grants a 5000 wallet credit.
    menu1 = create_draft_menu(client, chef, plan, week_start_date="2026-03-09T00:00:00Z")
    add_meal(menu1, chef, meal_name="M1", meal_slot="LUNCH",
             ingredients=[ingredient("rice", 1, "batch", 4000)])
    propose(menu1, chef)
    approve(menu1, client)
    skip(menu1, client)

    # menu2 (grocery 4000) cooked -> invoice gross 5600 (5000 base + 600 markup) ISSUED.
    menu2 = create_draft_menu(client, chef, plan, week_start_date="2026-03-16T00:00:00Z")
    add_meal(menu2, chef, meal_name="M2", meal_slot="DINNER",
             ingredients=[ingredient("beans", 1, "batch", 4000)])
    propose(menu2, chef)
    approve(menu2, client)
    session = schedule_session(menu2, chef, "2026-03-04T09:00:00Z", "2026-03-04T10:00:00Z")
    session = start_session(session, chef)
    complete_session(session, chef)
    invoice = invoice_for_menu(menu2["id"])
    assert invoice["gross_amount_cents"] == 5600

    paid = validate_success(api.pay_invoice(invoice["id"], client_h), 200)
    assert paid["credit_applied_cents"] == 5000
    assert paid["net_amount_cents"] == 600
    assert get_client(client["id"])["wallet_credit_cents"] == 0

    # A second pay on the now-PAID invoice is rejected.
    validate_error(api.pay_invoice(invoice["id"], client_h), "ERR_INVALID_INVOICE_STATE")
