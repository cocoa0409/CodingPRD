"""Police holds as a cross-cutting freeze: the execute cascade, hold-gated loan
redemption and inventory sale, and police-safety precedence over the grace check."""
from test_helpers import (
    validate_success, validate_error,
    constants,
    factories as f,
    fixtures as fx,
    make_officer_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]
LAW = TEST_USERS["law_headers"]


def _drawer_balance(api, shop_id):
    return api.get_shop_drawer(shop_id, MANAGER).json()["data"][0]["balance_cents"]


def _ledger(api, loan_id):
    return api.list_loan_transactions(loan_id, OFFICER).json()["data"]


# ── Difficulty: depth-3 execute cascade (hold EXECUTED -> loan VOIDED ->
#    VOID_REVERSAL appended -> drawer back to 0) ──

def test_police_execute_surrenders_item_and_voids_loan(api):
    """PRD §3.10: "It moves the hold to `EXECUTED` and surrenders the named subject: a
    pawn-item subject moves to `RELEASED_TO_POLICE`. If that surrendered pawn item is
    collateral on a loan that is still live (`ACTIVE` or `POLICE_HELD`), the loan is
    voided — it moves to `VOIDED`".

    Design: Difficulty/transitive_cascade/police_execute_cascade_depth3
    """
    ctx = fx.setup_active_loan(police_reporting_enabled=True, serial_number="SN-9")
    hold = fx.place_pawn_item_hold(ctx["item"]["id"], case_number="CASE-1")
    validate_success(api.execute_police_hold(hold["id"], LAW), 200)
    item = validate_success(api.get_item(ctx["item"]["id"], OFFICER), 200)
    assert item["status"] == "RELEASED_TO_POLICE"
    loan = validate_success(api.get_loan(ctx["loan"]["id"], OFFICER), 200)
    assert loan["status"] == "VOIDED"


def test_police_execute_appends_void_reversal_and_restores_drawer(api):
    """PRD §3.10: "a `FinanceTransaction` of kind `VOID_REVERSAL` is appended with a
    positive `amount_cents` equal to the loan's `principal_cents`, and the drawer's
    `balance_cents` increases by that principal, returning the disbursed cash."

    Design: Difficulty/transitive_cascade/police_execute_cascade_depth3
    """
    ctx = fx.setup_active_loan(police_reporting_enabled=True, serial_number="SN-9")
    assert _drawer_balance(api, ctx["shop"]["id"]) == -20000
    hold = fx.place_pawn_item_hold(ctx["item"]["id"], case_number="CASE-1")
    validate_success(api.execute_police_hold(hold["id"], LAW), 200)
    ledger = _ledger(api, ctx["loan"]["id"])
    rev = next(t for t in ledger if t["kind"] == "VOID_REVERSAL")
    assert rev["amount_cents"] == 20000
    assert _drawer_balance(api, ctx["shop"]["id"]) == 0


# ── Difficulty: Loan redeem blocked while collateral PoliceHold ACTIVE,
#    then permitted once RELEASED ──

def test_redeem_blocked_while_police_hold_active(api):
    """PRD §3.6: "Redemption against a loan whose `police_hold_flag` is true, or that is
    `POLICE_HELD`, is blocked with `ERR_POLICE_HOLD_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/loan_redeem_blocked_by_policehold_state
    """
    ctx = fx.setup_active_loan(police_reporting_enabled=True, serial_number="SN-3")
    fx.place_pawn_item_hold(ctx["item"]["id"], case_number="CASE-3")
    res = api.redeem_loan(ctx["loan"]["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_POLICE_HOLD_ACTIVE", 409)


def test_redeem_permitted_after_police_hold_released(api):
    """PRD §3.10: "Releasing a hold is a `LawEnforcement` action permitted while the hold
    is `ACTIVE`. It moves the hold to `RELEASED` and clears the `police_hold_flag` on the
    linked loan provided no other `ACTIVE` hold still names that collateral; when the flag
    clears, a loan that was `POLICE_HELD` returns to `ACTIVE`".
    PRD §3.6: "A `LoanOfficer` may redeem a loan that is `ACTIVE` or `IN_GRACE` with
    `police_hold_flag` false, when the redemption payoff is paid in full."

    Design: Difficulty/cross_entity_state_dependency/loan_redeem_blocked_by_policehold_state
    """
    ctx = fx.setup_active_loan(police_reporting_enabled=True, serial_number="SN-3")
    hold = fx.place_pawn_item_hold(ctx["item"]["id"], case_number="CASE-3")
    validate_success(api.release_police_hold(hold["id"], LAW), 200)
    redeemed = validate_success(api.redeem_loan(
        ctx["loan"]["id"], make_officer_headers("officer-1")), 200)
    assert redeemed["status"] == "REDEEMED"


# ── Difficulty: InventoryItem sell blocked while inventory PoliceHold ACTIVE,
#    permitted after RELEASED ──

def test_inventory_sell_blocked_while_police_hold_active(api):
    """PRD §3.8: "The sale is permitted only when the item is `AVAILABLE`, no `ACTIVE`
    police hold names it ... an active hold blocks the sale with `ERR_POLICE_HOLD_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/inventory_sell_blocked_by_inventory_policehold_state
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    fx.place_inventory_item_hold(inv["id"], case_number="CASE-4")
    res = api.sell_inventory(inv["id"], f.sell_inventory_payload(54000), MANAGER)
    validate_error(res, "ERR_POLICE_HOLD_ACTIVE", 409)


def test_inventory_sell_permitted_after_police_hold_released(api):
    """PRD §3.10: "Releasing a hold is a `LawEnforcement` action permitted while the hold
    is `ACTIVE`. It moves the hold to `RELEASED`".
    PRD §3.8: "On success the item records its `sold_price_cents`, moves to `SOLD`, and
    the drawer's `balance_cents` increases by the sale price."

    Design: Difficulty/cross_entity_state_dependency/inventory_sell_blocked_by_inventory_policehold_state
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    hold = fx.place_inventory_item_hold(inv["id"], case_number="CASE-4")
    validate_success(api.release_police_hold(hold["id"], LAW), 200)
    sold = validate_success(api.sell_inventory(
        inv["id"], f.sell_inventory_payload(54000), MANAGER), 200)
    assert sold["status"] == "SOLD"


# ── Difficulty: police-safety (priority 7) outranks the grace temporal check (priority 10) ──

def test_police_hold_blocks_forfeit_before_grace_with_police_error(api):
    """PRD §3.7: "an `ACTIVE` police hold on the collateral or a `POLICE_HELD` loan blocks
    it with `ERR_POLICE_HOLD_ACTIVE`."
    PRD §3.10: "A loan in `ACTIVE` or `IN_GRACE` thus moves to `POLICE_HELD`, and while
    `POLICE_HELD` all of redeem, extend, renew, and forfeit are frozen."

    Design: Difficulty/priority_pair_validation_conflict/police_safety_beats_grace_temporal
    """
    ctx = fx.setup_active_loan(police_reporting_enabled=True, serial_number="SN-7")
    fx.place_pawn_item_hold(ctx["item"]["id"], case_number="CASE-2")
    # Day 14: well before grace_end (day 60), and the loan is POLICE_HELD.
    fx.set_clock("2026-01-15T00:00:00.000Z")
    res = api.forfeit_loan(ctx["loan"]["id"], MANAGER)
    validate_error(res, "ERR_POLICE_HOLD_ACTIVE", 409)


def test_police_held_loan_status_after_hold_placed(api):
    """PRD §3.10: "Placing a hold on a pawn item that is currently collateral on a live
    loan sets that loan's `police_hold_flag` to true, moves the loan to `POLICE_HELD`".

    Design: Difficulty/priority_pair_validation_conflict/police_safety_beats_grace_temporal
    """
    ctx = fx.setup_active_loan(police_reporting_enabled=True, serial_number="SN-7")
    fx.place_pawn_item_hold(ctx["item"]["id"], case_number="CASE-2")
    loan = validate_success(api.get_loan(ctx["loan"]["id"], OFFICER), 200)
    assert loan["status"] == "POLICE_HELD"
    assert loan["police_hold_flag"] is True
