"""Point-of-sale: subsidy math (category filter + daily cap), wallet sufficiency,
allergen safety precedence, IN_SERVICE dependency, and compensating void
(PRD §2.8, §3.1, §3.3).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_session, create_pos, create_badge_transaction_payload, make_diner_headers,
)

ADMIN = TEST_USERS["site_admin_headers"]
MANAGER = TEST_USERS["cafeteria_manager_headers"]

CHICKEN = {"name": "Chicken", "category": "ENTREE", "price_cents": 900, "standard_recipe_cost_cents": 300}
SODA = {"name": "Soda", "category": "BEVERAGE", "price_cents": 200, "standard_recipe_cost_cents": 50}


def _raw_pos(api, emp_id, session_id, lines, payment_method="BADGE_PAYROLL"):
    return api.create_badge_transaction(
        create_badge_transaction_payload(emp_id, session_id, lines, payment_method=payment_method),
        make_diner_headers(emp_id))


# ─── Difficulty: combinatorial_formula — subsidy min/cap with category filter ──
def test_badge_subsidy_only_subsidizes_entree_categories(api):
    """PRD §3.3: "The subsidizable portion is the sum over only those lines whose menu item
    `category` is `ENTREE` or `HEALTHY` of `price_cents` times `qty` — sides, beverages, and
    desserts are never subsidized. The gross subsidy is that subsidizable amount multiplied
    by the site's `employer_subsidy_pct`, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/badge_subsidy_min_cap_nonlinear
    """
    ctx = setup_session(stage="IN_SERVICE", items=[CHICKEN, SODA])
    chick, soda = ctx["items"]
    txn = create_pos(ctx["employee"]["id"], ctx["session"]["id"],
                     [{"menu_item_id": chick["id"], "qty": 1}, {"menu_item_id": soda["id"], "qty": 1}])
    assert txn["subtotal_cents"] == 1100
    assert txn["subsidy_applied_cents"] == 450


def test_badge_subsidy_employee_charge_is_subtotal_minus_subsidy(api):
    """PRD §3.3: "The `subsidy_applied_cents` actually granted is the smaller of the gross
    subsidy and that remaining allowance. The `employee_charge_cents` is `subtotal_cents`
    minus `subsidy_applied_cents`."

    Design: Difficulty/combinatorial_formula/badge_subsidy_min_cap_nonlinear
    """
    ctx = setup_session(stage="IN_SERVICE", items=[CHICKEN, SODA])
    chick, soda = ctx["items"]
    txn = create_pos(ctx["employee"]["id"], ctx["session"]["id"],
                     [{"menu_item_id": chick["id"], "qty": 1}, {"menu_item_id": soda["id"], "qty": 1}])
    assert txn["employee_charge_cents"] == 650


# ─── Difficulty: boundary_precision_check — daily subsidy cap exhausted ──────
def test_subsidy_capped_exactly_at_daily_cap(api):
    """PRD §3.3: "The remaining daily allowance is the site's `daily_subsidy_cap_cents` minus
    the employee's `daily_subsidy_used_cents`, but never below 0. The `subsidy_applied_cents`
    actually granted is the smaller of the gross subsidy and that remaining allowance."

    Design: Difficulty/boundary_precision_check/subsidy_daily_cap_exhausted_boundary
    """
    ctx = setup_session(stage="IN_SERVICE", items=[CHICKEN])
    chick = ctx["items"][0]
    txn1 = create_pos(ctx["employee"]["id"], ctx["session"]["id"],
                      [{"menu_item_id": chick["id"], "qty": 3}])  # gross 1350, capped at 1000
    assert txn1["subsidy_applied_cents"] == 1000


def test_subsidy_zero_after_cap_exhausted(api):
    """PRD §3.3: "Regardless of method, the granted subsidy is added to
    `daily_subsidy_used_cents`."
    PRD §3.3: "The remaining daily allowance is the site's `daily_subsidy_cap_cents` minus
    the employee's `daily_subsidy_used_cents`, but never below 0."

    Design: Difficulty/boundary_precision_check/subsidy_daily_cap_exhausted_boundary
    """
    ctx = setup_session(stage="IN_SERVICE", items=[CHICKEN])
    chick = ctx["items"][0]
    create_pos(ctx["employee"]["id"], ctx["session"]["id"],
               [{"menu_item_id": chick["id"], "qty": 3}])  # drives used to exactly 1000
    txn2 = create_pos(ctx["employee"]["id"], ctx["session"]["id"],
                      [{"menu_item_id": chick["id"], "qty": 1}])
    assert txn2["subsidy_applied_cents"] == 0
    assert txn2["employee_charge_cents"] == 900


# ─── Difficulty: cross_entity_state_dependency — POS requires IN_SERVICE ─────
def test_pos_rejected_when_session_forecast_locked(api):
    """PRD §3.3: "The session must be `IN_SERVICE`, or the purchase is rejected with
    `ERR_SESSION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/pos_requires_session_in_service
    """
    ctx = setup_session(stage="FORECAST_LOCKED", items=[CHICKEN])
    res = _raw_pos(api, ctx["employee"]["id"], ctx["session"]["id"],
                   [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}])
    validate_error(res, ApiErrorId.ERR_SESSION_NOT_OPEN.value, expected_status=409)


def test_pos_rejected_when_session_planned(api):
    """PRD §3.3: "The session must be `IN_SERVICE`, or the purchase is rejected with
    `ERR_SESSION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/pos_requires_session_in_service
    """
    ctx = setup_session(stage="PLANNED", items=[CHICKEN])
    res = _raw_pos(api, ctx["employee"]["id"], ctx["session"]["id"],
                   [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}])
    validate_error(res, ApiErrorId.ERR_SESSION_NOT_OPEN.value, expected_status=409)


# ─── Difficulty: priority_pair_validation_conflict — allergen beats wallet ──
def test_allergen_conflict_reported_over_wallet_insufficiency_soy(api):
    """PRD §3.3: "no line's menu item may carry an allergen that appears in the employee's
    `restricted_allergens`; any intersection rejects the whole transaction with
    `ERR_ALLERGEN_CONFLICT`."
    PRD §2.8: "6. Allergen safety ... else `ERR_ALLERGEN_CONFLICT` (422)." precedes
    "10. Fiscal sufficiency ... `ERR_WALLET_INSUFFICIENT`".

    Design: Difficulty/priority_pair_validation_conflict/pos_allergen_safety_beats_wallet_fiscal
    """
    item = {**CHICKEN, "allergens": ["SOY"]}
    ctx = setup_session(stage="IN_SERVICE", items=[item],
                        employee_overrides={"restricted_allergens": ["SOY"], "wallet_balance_cents": 100})
    res = _raw_pos(api, ctx["employee"]["id"], ctx["session"]["id"],
                   [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}], payment_method="WALLET")
    validate_error(res, ApiErrorId.ERR_ALLERGEN_CONFLICT.value, expected_status=422)


def test_allergen_conflict_reported_over_wallet_insufficiency_peanuts(api):
    """PRD §3.3: "no line's menu item may carry an allergen that appears in the employee's
    `restricted_allergens`; any intersection rejects the whole transaction with
    `ERR_ALLERGEN_CONFLICT`."
    PRD §2.8: "6. Allergen safety ... else `ERR_ALLERGEN_CONFLICT` (422)." precedes
    "10. Fiscal sufficiency ... `ERR_WALLET_INSUFFICIENT`".

    Design: Difficulty/priority_pair_validation_conflict/pos_allergen_safety_beats_wallet_fiscal
    """
    item = {**CHICKEN, "allergens": ["PEANUTS"]}
    ctx = setup_session(stage="IN_SERVICE", items=[item],
                        employee_overrides={"restricted_allergens": ["PEANUTS"], "wallet_balance_cents": 100})
    res = _raw_pos(api, ctx["employee"]["id"], ctx["session"]["id"],
                   [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}], payment_method="WALLET")
    validate_error(res, ApiErrorId.ERR_ALLERGEN_CONFLICT.value, expected_status=422)


# ─── Difficulty: compensating_invariant — void restores employee money ──────
def test_wallet_txn_debits_wallet_and_records_subsidy(api):
    """PRD §3.3: "When the payment method is `WALLET` ... on success the wallet is debited by
    the employee charge. Regardless of method, the granted subsidy is added to
    `daily_subsidy_used_cents`."

    Design: Difficulty/compensating_invariant/pos_void_conserves_employee_money
    """
    ctx = setup_session(stage="IN_SERVICE", items=[CHICKEN],
                        employee_overrides={"wallet_balance_cents": 2000})
    emp_id = ctx["employee"]["id"]
    create_pos(emp_id, ctx["session"]["id"], [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}],
               payment_method="WALLET")  # charge 450, subsidy 450
    emp = validate_success(api.get_employee(emp_id, MANAGER), 200)
    assert emp["wallet_balance_cents"] == 1550
    assert emp["daily_subsidy_used_cents"] == 450


def test_void_restores_wallet_and_subsidy(api):
    """PRD §3.3: "Voiding is fully compensating: if the original payment was `WALLET`, the
    employee's `wallet_balance_cents` is credited back by the `employee_charge_cents`; the
    employee's `daily_subsidy_used_cents` is reduced by the `subsidy_applied_cents`, floored
    at 0."

    Design: Difficulty/compensating_invariant/pos_void_conserves_employee_money
    """
    ctx = setup_session(stage="IN_SERVICE", items=[CHICKEN],
                        employee_overrides={"wallet_balance_cents": 2000})
    emp_id = ctx["employee"]["id"]
    txn = create_pos(emp_id, ctx["session"]["id"], [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}],
                     payment_method="WALLET")
    validate_success(api.void_badge_transaction(txn["id"], MANAGER), 200)
    emp = validate_success(api.get_employee(emp_id, MANAGER), 200)
    assert emp["wallet_balance_cents"] == 2000
    assert emp["daily_subsidy_used_cents"] == 0


# ─── Corner: validations — terminated employee & wallet insufficiency ───────
def test_terminated_employee_pos_rejected(api):
    """PRD §3.1: "A site admin may `terminate` an employee, moving them from `ACTIVE` to the
    terminal `TERMINATED` state, after which any attempt to create a point-of-sale
    transaction for that employee is rejected with `ERR_EMPLOYEE_INACTIVE`."

    Design: Corner/validations/terminated_employee_pos_rejected
    """
    ctx = setup_session(stage="IN_SERVICE", items=[{"name": "Wrap", "category": "ENTREE",
                                                    "price_cents": 350, "standard_recipe_cost_cents": 120}])
    emp_id = ctx["employee"]["id"]
    validate_success(api.terminate_employee(emp_id, ADMIN), 200)
    res = _raw_pos(api, emp_id, ctx["session"]["id"], [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}])
    validate_error(res, ApiErrorId.ERR_EMPLOYEE_INACTIVE.value, expected_status=409)


def test_wallet_insufficient_rejected(api):
    """PRD §3.3: "When the payment method is `WALLET`, the employee's `wallet_balance_cents`
    must be at least the employee charge, or the purchase is rejected with
    `ERR_WALLET_INSUFFICIENT`."

    Design: Corner/validations/pure_wallet_insufficient_rejected
    """
    ctx = setup_session(
        stage="IN_SERVICE",
        site_overrides={"employer_subsidy_pct": 0.0, "daily_subsidy_cap_cents": 0},
        items=[{"name": "Wrap", "category": "SIDE", "price_cents": 900, "standard_recipe_cost_cents": 120}],
        employee_overrides={"wallet_balance_cents": 100},
    )
    res = _raw_pos(api, ctx["employee"]["id"], ctx["session"]["id"],
                   [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}], payment_method="WALLET")
    validate_error(res, ApiErrorId.ERR_WALLET_INSUFFICIENT.value, expected_status=409)
