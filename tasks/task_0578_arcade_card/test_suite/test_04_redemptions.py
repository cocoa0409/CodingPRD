"""Redemption lifecycle: hold-vs-settled repricing, fulfill/cancel fork, points and
stock conservation, OCC stale-card version, and the reservation guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    redemption_payload,
)
from test_helpers.fixtures import (
    create_member, issue_card, activate_card, reload_card, get_card,
    create_attraction, create_prize, play, reserve_redemption,
    setup_funded_points_card, setup_reserved_redemption,
)

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# --- Difficulty: redemption_hold_vs_settled ---
def test_points_hold_valued_at_reserve_price(api):
    """PRD §3.4: "The `points_hold` is valued at reserve time as the prize's `points_price`
    at that moment multiplied by the `quantity`."

    Design: Difficulty/dual_variant_calc/redemption_hold_vs_settled
    """
    ctx = setup_reserved_redemption(api, prize_price=500, stock_qty=100, quantity=2, plays=2)
    redemption = validate_success(api.get_redemption(ctx["redemption_id"], ATTENDANT))
    assert redemption["points_hold"] == 1000


def test_points_settled_at_fulfill_price_diverges_from_hold(api):
    """PRD §3.4: "Fulfilling it moves `RESERVED → FULFILLED` and settles at the *current*
    price: `points_settled` is the prize's `points_price` at fulfill time multiplied by the
    `quantity`. ... The card is charged the settlement delta — the settled amount minus the
    original hold — so the card's `ticket_points_balance` decreases by that difference."

    Design: Difficulty/dual_variant_calc/redemption_hold_vs_settled
    """
    ctx = setup_reserved_redemption(api, prize_price=500, stock_qty=100, quantity=2, plays=2)
    validate_success(api.update_prize_item(ctx["prize_id"], {"points_price": 600}, MANAGER))
    fulfilled = validate_success(api.fulfill_redemption(ctx["redemption_id"], ATTENDANT))
    assert fulfilled["points_hold"] == 1000
    assert fulfilled["points_settled"] == 1200
    assert fulfilled["points_hold"] != fulfilled["points_settled"]
    assert get_card(api, ctx["card_id"])["ticket_points_balance"] == 800


# --- Difficulty: redemption_fork_fulfill_vs_cancel ---
def _two_reserved_on_shared_prize(api):
    prize = create_prize(api, points_price=500, stock_qty=10)
    f1 = setup_funded_points_card(api, plays=1, points_award=1000)
    r1 = reserve_redemption(api, f1["card_id"], prize["id"], 1, f1["version"])
    f2 = setup_funded_points_card(api, plays=1, points_award=1000)
    r2 = reserve_redemption(api, f2["card_id"], prize["id"], 1, f2["version"])
    return prize, r1, r2


def test_fulfill_branch_retires_stock(api):
    """PRD §3.4: "A `POINTS_SETTLE` ledger entry is appended with a points delta equal to the
    negative of the settlement delta, the prize's `reserved_qty` decreases by the `quantity`,
    and its `stock_qty` also decreases by the `quantity`, retiring the physical units."

    Design: Difficulty/non_linear_state_machine/redemption_fork_fulfill_vs_cancel
    """
    prize, r1, r2 = _two_reserved_on_shared_prize(api)
    fulfilled = validate_success(api.fulfill_redemption(r1["id"], ATTENDANT))
    assert fulfilled["status"] == "FULFILLED"
    validate_success(api.cancel_redemption(r2["id"], ATTENDANT))
    prize_now = validate_success(api.get_prize_item(prize["id"], MANAGER))
    assert prize_now["stock_qty"] == 9


def test_cancel_branch_leaves_stock_unchanged(api):
    """PRD §3.4: "Cancelling instead moves `RESERVED → CANCELLED` and unwinds the reservation
    cleanly: the full `points_hold` is added back to the card's `ticket_points_balance`, a
    `POINTS_REFUND` ledger entry is appended with a positive points delta equal to the hold,
    and the prize's `reserved_qty` decreases by the `quantity` while its `stock_qty` is left
    unchanged."

    Design: Difficulty/non_linear_state_machine/redemption_fork_fulfill_vs_cancel
    """
    prize, r1, r2 = _two_reserved_on_shared_prize(api)
    validate_success(api.fulfill_redemption(r1["id"], ATTENDANT))
    cancelled = validate_success(api.cancel_redemption(r2["id"], ATTENDANT))
    assert cancelled["status"] == "CANCELLED"
    prize_now = validate_success(api.get_prize_item(prize["id"], MANAGER))
    assert prize_now["reserved_qty"] == 0


# --- Difficulty: points_outstanding_conserved_reserve_cancel ---
def test_cancel_refunds_full_hold_to_card(api):
    """PRD §3.4: "the full `points_hold` is added back to the card's `ticket_points_balance`,
    a `POINTS_REFUND` ledger entry is appended with a positive points delta equal to the hold".

    Design: Difficulty/compensating_invariant/points_outstanding_conserved_reserve_cancel
    """
    ctx = setup_reserved_redemption(api, prize_price=500, stock_qty=10, quantity=2, plays=1)
    validate_success(api.cancel_redemption(ctx["redemption_id"], ATTENDANT))
    assert get_card(api, ctx["card_id"])["ticket_points_balance"] == 1000
    redemption = validate_success(api.get_redemption(ctx["redemption_id"], ATTENDANT))
    assert redemption["status"] == "CANCELLED"


def test_cancel_releases_reservation_without_touching_stock(api):
    """PRD §3.4: "the prize's `reserved_qty` decreases by the `quantity` while its `stock_qty`
    is left unchanged."

    Design: Difficulty/compensating_invariant/points_outstanding_conserved_reserve_cancel
    """
    ctx = setup_reserved_redemption(api, prize_price=500, stock_qty=10, quantity=2, plays=1)
    validate_success(api.cancel_redemption(ctx["redemption_id"], ATTENDANT))
    prize_now = validate_success(api.get_prize_item(ctx["prize_id"], MANAGER))
    assert prize_now["reserved_qty"] == 0
    assert prize_now["stock_qty"] == 10


# --- Corner: occ_redemption_stale_card_version ---
def test_second_redemption_with_stale_card_version_rejected(api):
    """PRD §2.8: "If another writer — a prior redemption or a game play on the same card — has
    advanced the card's `version` since the client read it, the reservation is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because the client's view of the points available to hold
    is stale."

    Design: Corner/cross_cutting_complexity_layers/occ_redemption_stale_card_version
    """
    prize = create_prize(api, points_price=500, stock_qty=100)
    funded = setup_funded_points_card(api, plays=2, points_award=1000)  # 2000 points
    v0 = funded["version"]
    first = validate_success(api.create_redemption(
        redemption_payload(funded["card_id"], prize["id"], 1, v0), ATTENDANT), 201)
    assert first["status"] == "RESERVED"
    resp = api.create_redemption(
        redemption_payload(funded["card_id"], prize["id"], 1, v0), ATTENDANT)  # stale v0
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


# --- Corner: fulfill_already_fulfilled_redemption_invalid_state ---
def test_fulfill_already_fulfilled_rejected(api):
    """PRD §3.4: "Fulfilling or cancelling anything not currently `RESERVED` is rejected with
    `ERR_INVALID_REDEMPTION_STATE` (409); both `FULFILLED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/fulfill_already_fulfilled_redemption_invalid_state
    """
    ctx = setup_reserved_redemption(api, prize_price=500, stock_qty=10, quantity=1, plays=1)
    validate_success(api.fulfill_redemption(ctx["redemption_id"], ATTENDANT))
    resp = api.fulfill_redemption(ctx["redemption_id"], ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REDEMPTION_STATE, 409)
    redemption = validate_success(api.get_redemption(ctx["redemption_id"], ATTENDANT))
    assert redemption["status"] == "FULFILLED"


# --- Corner: redeem_discontinued_prize_unavailable ---
def test_reserve_on_discontinued_prize_rejected(api):
    """PRD §3.4: "the prize must be `AVAILABLE`, else `ERR_PRIZE_UNAVAILABLE` (409)".

    Design: Corner/validations/redeem_discontinued_prize_unavailable
    """
    funded = setup_funded_points_card(api, plays=1, points_award=1000)
    prize = create_prize(api, points_price=100, stock_qty=5)
    validate_success(api.update_prize_item(prize["id"], {"status": "DISCONTINUED"}, MANAGER))
    resp = api.create_redemption(
        redemption_payload(funded["card_id"], prize["id"], 1, funded["version"]), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_PRIZE_UNAVAILABLE, 409)


# --- Corner: redeem_over_available_stock_insufficient ---
def test_reserve_over_available_stock_rejected(api):
    """PRD §3.4: "the prize's available units — its `stock_qty` minus its `reserved_qty` —
    must be at least the requested `quantity`, else `ERR_INSUFFICIENT_STOCK` (409)".

    Design: Corner/validations/redeem_over_available_stock_insufficient
    """
    funded = setup_funded_points_card(api, plays=1, points_award=1000)
    prize = create_prize(api, points_price=100, stock_qty=5)
    resp = api.create_redemption(
        redemption_payload(funded["card_id"], prize["id"], 6, funded["version"]), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK, 409)


# --- Corner: redeem_insufficient_points ---
def test_reserve_with_insufficient_points_rejected(api):
    """PRD §3.4: "the card's `ticket_points_balance` must be at least the points hold, else
    `ERR_INSUFFICIENT_POINTS` (402)".

    Design: Corner/validations/redeem_insufficient_points
    """
    member = create_member(api)
    card = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])  # 0 points
    prize = create_prize(api, points_price=500, stock_qty=5)
    resp = api.create_redemption(
        redemption_payload(card["id"], prize["id"], 1, card["version"]), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS, 402)
