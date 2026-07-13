"""Gameplay settlement: waterfall chip debit, exact-balance boundary, bonus-only
variant, and the attraction-OPEN cross-entity gate."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    create_member, issue_card, activate_card, reload_card, get_card,
    create_attraction, play, setup_confirmed_booking,
)

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def _funded_card(api, reload_amount, chip_cost, points_award=10):
    member = create_member(api)
    card = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])
    reload_card(api, card["id"], reload_amount)
    attraction = create_attraction(api, chip_cost_cents=chip_cost, points_award=points_award)
    return card, attraction


# --- Difficulty: gameplay_exact_balance_boundary ---
def test_play_succeeds_at_exact_balance(api):
    """PRD §3.3: "Before charging, the card's combined promotional and purchased chips must
    be at least the cost; if `bonus_chip_balance_cents` plus `chip_balance_cents` is less than
    the cost the play is rejected with `ERR_INSUFFICIENT_CHIP_BALANCE` (402)."

    Design: Difficulty/boundary_precision_check/gameplay_exact_balance_boundary
    """
    card, attraction = _funded_card(api, reload_amount=200, chip_cost=200, points_award=10)
    result = validate_success(api.create_game_play(
        {"card_id": card["id"], "attraction_id": attraction["id"]}, ATTENDANT), 201)
    assert result["chip_from_stored_cents"] == 200
    assert result["points_awarded"] == 10
    assert get_card(api, card["id"])["chip_balance_cents"] == 0


def test_second_play_at_zero_balance_rejected(api):
    """PRD §3.3: "if `bonus_chip_balance_cents` plus `chip_balance_cents` is less than the
    cost the play is rejected with `ERR_INSUFFICIENT_CHIP_BALANCE` (402)."

    Design: Difficulty/boundary_precision_check/gameplay_exact_balance_boundary
    """
    card, attraction = _funded_card(api, reload_amount=200, chip_cost=200, points_award=10)
    play(api, card["id"], attraction["id"])  # exhausts balance to 0
    resp = api.create_game_play(
        {"card_id": card["id"], "attraction_id": attraction["id"]}, ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CHIP_BALANCE, 402)


# --- Corner: gameplay_bonus_only_variant ---
def test_play_draws_entirely_from_bonus_when_it_covers_cost(api):
    """PRD §3.3: "the portion drawn from bonus, recorded as `chip_from_bonus_cents`, is the
    smaller of the card's `bonus_chip_balance_cents` and the cost; the remaining cost is drawn
    from purchased value and recorded as `chip_from_stored_cents`. ... When the bonus balance
    alone covers the whole cost, the stored portion is zero and purchased value is untouched."

    Design: Corner/calculations/gameplay_bonus_only_variant
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    card0 = ctx["card_ids"][0]  # provisioned ACTIVE card, bonus 1000, stored 0
    attraction = create_attraction(api, chip_cost_cents=200, points_award=5)
    result = validate_success(api.create_game_play(
        {"card_id": card0, "attraction_id": attraction["id"]}, ATTENDANT), 201)
    assert result["chip_from_bonus_cents"] == 200
    assert result["chip_from_stored_cents"] == 0
    card_now = get_card(api, card0)
    assert card_now["bonus_chip_balance_cents"] == 800
    assert card_now["chip_balance_cents"] == 0


# --- Difficulty: gameplay_requires_attraction_open (cross-entity state dependency) ---
def test_play_on_maintenance_attraction_rejected(api):
    """PRD §3.3: "the attraction must be `OPEN`, or the play is rejected with
    `ERR_ATTRACTION_NOT_OPEN` (409)."

    Design: Difficulty/cross_entity_state_dependency/gameplay_requires_attraction_open
    """
    card, attraction = _funded_card(api, reload_amount=500, chip_cost=100, points_award=10)
    validate_success(api.update_attraction(attraction["id"], {"status": "MAINTENANCE"}, MANAGER))
    resp = api.create_game_play(
        {"card_id": card["id"], "attraction_id": attraction["id"]}, ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_ATTRACTION_NOT_OPEN, 409)


def test_play_succeeds_after_attraction_reopened(api):
    """PRD §3.3: "the attraction must be `OPEN`, or the play is rejected with
    `ERR_ATTRACTION_NOT_OPEN` (409). The cost of the play is a snapshot of the attraction's
    `chip_cost_cents` at play time, recorded on the resulting `GamePlay` as its own
    `chip_cost_cents`."

    Design: Difficulty/cross_entity_state_dependency/gameplay_requires_attraction_open
    """
    card, attraction = _funded_card(api, reload_amount=500, chip_cost=100, points_award=10)
    validate_success(api.update_attraction(attraction["id"], {"status": "MAINTENANCE"}, MANAGER))
    api.create_game_play({"card_id": card["id"], "attraction_id": attraction["id"]}, ATTENDANT)
    validate_success(api.update_attraction(attraction["id"], {"status": "OPEN"}, MANAGER))
    validate_success(api.create_game_play(
        {"card_id": card["id"], "attraction_id": attraction["id"]}, ATTENDANT), 201)
    assert get_card(api, card["id"])["chip_balance_cents"] == 400
