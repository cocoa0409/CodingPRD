"""Forfeiture cascade, resale pricing (list vs floor), the grace boundary,
direct resale at/below floor, and the reverse-forfeiture recall conservation."""
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


# ── Difficulty: forfeit two-hop cascade spawns a priced inventory item ──

def test_forfeit_spawns_inventory_with_cost_basis(api):
    """PRD §3.7: "First, the loan moves to `FORFEITED` and its pawn item moves to
    `FORFEITED`, and the system computes the **cost basis** — the unrecovered debt the
    shop is owed at the forfeiture instant. This cost basis is exactly the redemption
    payoff of §3.4 evaluated at the forfeiture moment (the clock at or after
    `grace_end_at`), reusing the same round-per-period rule."

    Design: Difficulty/transitive_cascade/forfeit_cascade_depth2_spawns_priced_inventory
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    # At grace_end (60 days, 2 periods): 20000 + 200 + 2*2500 = 25200.
    assert inv["cost_basis_cents"] == 25200
    assert inv["status"] == "AVAILABLE"


def test_forfeit_spawns_exactly_one_inventory_with_list_price(api):
    """PRD §3.7: "Second, that cost basis drives the creation of a new `InventoryItem`
    in `AVAILABLE` status."
    PRD §3.7: "The `list_price_cents` is the forward-looking, optimistic target: take the
    `appraised_value_cents`, multiply by the quantity ten-thousand plus the resale markup
    of 3500 basis points (that is, a thirty-five-percent markup), divide by 10000, then
    round that raw figure half-up to the nearest whole dollar (a whole multiple of 100
    cents), and finally clamp the result upward to be no less than the `cost_basis_cents`
    so the listing never sits below cost."

    Design: Difficulty/transitive_cascade/forfeit_cascade_depth2_spawns_priced_inventory
    """
    ctx = fx.setup_forfeited_inventory()
    all_inv = fx.get_inventory_for_loan(ctx["loan"]["id"])
    assert len(all_inv) == 1
    # 40000 * 1.35 = 54000 -> $540.00 -> 54000; clamp up to 25200 keeps 54000.
    assert all_inv[0]["list_price_cents"] == 54000


# ── Difficulty: list_price vs floor_price diverge from identical forfeit inputs ──

def test_resale_list_price_forward_markup(api):
    """PRD §3.7: "The `list_price_cents` is the forward-looking, optimistic target: take
    the `appraised_value_cents`, multiply by the quantity ten-thousand plus the resale
    markup of 3500 basis points (that is, a thirty-five-percent markup), divide by 10000,
    then round that raw figure half-up to the nearest whole dollar (a whole multiple of
    100 cents), and finally clamp the result upward to be no less than the
    `cost_basis_cents` so the listing never sits below cost."

    Design: Difficulty/dual_variant_calc/resale_list_vs_floor_diverge_on_inventory_item
    """
    ctx = fx.setup_forfeited_inventory()
    assert ctx["inventory"]["list_price_cents"] == 54000


def test_resale_floor_price_equals_cost_basis_and_diverges_from_list(api):
    """PRD §3.7: "the `floor_price_cents` is set equal to the `cost_basis_cents` — the
    pessimistic, cost-recovery minimum below which the item may never be sold."

    Design: Difficulty/dual_variant_calc/resale_list_vs_floor_diverge_on_inventory_item
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    assert inv["floor_price_cents"] == 25200
    assert inv["list_price_cents"] != inv["floor_price_cents"]


# ── Difficulty: forfeit at the exact grace_end instant is allowed (>= boundary) ──

def test_forfeit_at_exact_grace_end_succeeds(api):
    """PRD §3.7: "Forfeiture is permitted only when the loan is `IN_GRACE`, the simulated
    clock has reached or passed the loan's `grace_end_at`, and the loan's
    `police_hold_flag` is false."

    Design: Difficulty/boundary_precision_check/grace_end_exact_instant_allows_forfeit
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.GRACE_END)  # exactly grace_end_at (origination + 60d)
    forfeited = validate_success(api.forfeit_loan(ctx["loan"]["id"], MANAGER), 200)
    assert forfeited["status"] == "FORFEITED"


def test_forfeit_before_grace_end_returns_grace_not_elapsed(api):
    """PRD §3.7: "A forfeiture attempted before the clock reaches `grace_end_at` is
    rejected with `ERR_GRACE_NOT_ELAPSED`".

    Design: Difficulty/boundary_precision_check/grace_end_exact_instant_allows_forfeit
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_45)  # day 45: IN_GRACE but before grace_end day 60
    res = api.forfeit_loan(ctx["loan"]["id"], MANAGER)
    validate_error(res, "ERR_GRACE_NOT_ELAPSED", 409)


# ── Corner: forfeit before grace (term passed) yields grace-not-elapsed ──

def test_forfeit_before_grace_returns_grace_not_elapsed_corner(api):
    """PRD §3.7: "A forfeiture attempted before the clock reaches `grace_end_at` is
    rejected with `ERR_GRACE_NOT_ELAPSED`".

    Design: Corner/state_machines/forfeit_before_grace_returns_grace_not_elapsed
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_45)  # day 45 -> IN_GRACE, grace_end is day 60
    res = api.forfeit_loan(ctx["loan"]["id"], MANAGER)
    validate_error(res, "ERR_GRACE_NOT_ELAPSED", 409)


# ── Difficulty: sell at exactly floor_price is allowed (>= boundary) ──

def test_sell_at_exact_floor_price_allowed(api):
    """PRD §3.8: "The sale is permitted only when the item is `AVAILABLE`, no `ACTIVE`
    police hold names it, and the offered `sold_price_cents` is at or above the item's
    `floor_price_cents`."
    PRD §3.8: "On success the item records its `sold_price_cents`, moves to `SOLD`, and
    the drawer's `balance_cents` increases by the sale price."

    Design: Difficulty/boundary_precision_check/sell_at_exact_floor_price_allowed
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    assert inv["floor_price_cents"] == 25200
    sold = validate_success(api.sell_inventory(
        inv["id"], f.sell_inventory_payload(25200), MANAGER), 200)
    assert sold["status"] == "SOLD"
    assert sold["sold_price_cents"] == 25200


def test_sell_below_floor_returns_price_below_floor(api):
    """PRD §3.8: "A price below the floor is rejected with `ERR_PRICE_BELOW_FLOOR`".

    Design: Difficulty/boundary_precision_check/sell_at_exact_floor_price_allowed
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    res = api.sell_inventory(inv["id"], f.sell_inventory_payload(25199), MANAGER)
    validate_error(res, "ERR_PRICE_BELOW_FLOOR", 422)


# ── Corner: sell below floor (dedicated error instance) ──

def test_sell_below_floor_returns_price_below_floor_corner(api):
    """PRD §3.8: "A price below the floor is rejected with `ERR_PRICE_BELOW_FLOOR`".

    Design: Corner/errors/sell_below_floor_returns_price_below_floor
    """
    ctx = fx.setup_forfeited_inventory()
    res = api.sell_inventory(ctx["inventory"]["id"], f.sell_inventory_payload(25199), MANAGER)
    validate_error(res, "ERR_PRICE_BELOW_FLOOR", 422)


# ── Difficulty: recall conserves the item-population count ──

def test_recall_returns_item_to_pledged_and_loan_to_in_grace(api):
    """PRD §3.8: "Recall moves the inventory item to `RECALLED`, returns the source loan
    to `IN_GRACE` so it is redeemable again, and returns the pawn item to `PLEDGED`."

    Design: Difficulty/compensating_invariant/recall_conserves_item_population_count
    """
    ctx = fx.setup_forfeited_inventory()
    inv = ctx["inventory"]
    recalled = validate_success(api.recall_inventory(inv["id"], MANAGER), 200)
    assert recalled["status"] == "RECALLED"
    item = validate_success(api.get_item(ctx["item"]["id"], OFFICER), 200)
    assert item["status"] == "PLEDGED"
    loan = validate_success(api.get_loan(ctx["loan"]["id"], OFFICER), 200)
    assert loan["status"] == "IN_GRACE"


def test_recall_conserves_item_population_count(api):
    """PRD §2.8: "for any shop, the combined count of pawn items currently `PLEDGED` plus
    inventory items currently `AVAILABLE` or `ON_LAYAWAY` is preserved by a
    forfeit-then-recall pair, so reversing a forfeiture never creates or destroys an item."

    Design: Difficulty/compensating_invariant/recall_conserves_item_population_count
    """
    ctx = fx.setup_forfeited_inventory()
    shop_id = ctx["shop"]["id"]

    def population():
        items = api.list_items(OFFICER, params={"shop_id": shop_id}).json()["data"]
        inv = api.list_inventory(MANAGER, params={"shop_id": shop_id}).json()["data"]
        pledged = len([i for i in items if i["status"] == "PLEDGED"])
        on_floor = len([i for i in inv if i["status"] in ("AVAILABLE", "ON_LAYAWAY")])
        return pledged + on_floor

    before = population()       # forfeited: 0 pledged + 1 available = 1
    assert before == 1
    validate_success(api.recall_inventory(ctx["inventory"]["id"], MANAGER), 200)
    after = population()        # recalled: 1 pledged + 0 available = 1
    assert after == 1


# ── Corner: a LoanOfficer cannot forfeit (ShopManager-exclusive) ──

def test_loanofficer_cannot_forfeit(api):
    """PRD §3.7: "When the grace window has fully elapsed without redemption, a
    `ShopManager` may forfeit the loan, converting the collateral into shop inventory."
    PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/loanofficer_cannot_forfeit
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.GRACE_END)
    res = api.forfeit_loan(ctx["loan"]["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_FORBIDDEN_ROLE", 403)
