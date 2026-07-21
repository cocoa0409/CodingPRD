"""Activation, redemption, reload, balance API, and their numeric boundaries.

Covers the Difficulty boundary_precision instances (velocity count, inclusive
max-balance) and the Corner calculation/validation instances for card value
movement.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    reload_payload, redeem_payload,
    assert_gift_card,
    TEST_USERS, make_pos_terminal_headers,
    setup_single_active_card, setup_velocity_scenario,
    setup_active_card_with_running_campaign, get_batch_cards, commit_batch,
    create_active_merchant, create_active_program, api_client,
)

POS = TEST_USERS["pos_terminal_headers"]
ANY = TEST_USERS["any_headers"]


# ─────────── Corner: activation / balance projection ───────────

def test_activation_loads_balance_to_initial_load(api):
    """PRD §3.4: "On activation the system posts an `ACTIVATION_LOAD` ledger entry whose `amount_cents` equals the positive `initial_load_cents`, sets `activated_at` to the current clock, sets `expires_at` to the activation instant plus the program's `expiry_months`, sets `last_activity_at` to the same instant, and moves the card to `ACTIVE`."

    Design: Corner/entities/card_balance_equals_activation_load
    """
    merchant = create_active_merchant()
    program = create_active_program(merchant["id"])
    batch = commit_batch(merchant["id"], program["id"], 1, 5000)
    card = get_batch_cards(batch["id"])[0]
    res = api.activate_gift_card(card["id"], POS)
    activated = validate_success(res, 200)
    assert_gift_card(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["balance_cents"] == 5000


def test_activation_immediately_reflected_in_read(api):
    """PRD §3.4: "On activation the system posts an `ACTIVATION_LOAD` ledger entry whose `amount_cents` equals the positive `initial_load_cents`, sets `activated_at` to the current clock, sets `expires_at` to the activation instant plus the program's `expiry_months`, sets `last_activity_at` to the same instant, and moves the card to `ACTIVE`."

    Design: Corner/consistency_model/immediate_consistency_activation_reflected_in_read
    """
    _merchant, _program, _batch, card = setup_single_active_card(5000)
    fetched = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert fetched["balance_cents"] == 5000
    assert fetched["status"] == "ACTIVE"


def test_balance_api_returns_status_balance_currency(api):
    """PRD §3.4: "The balance API lets a `POSTerminal` (or any authenticated reader) look up a card's live standing without mutating it, returning the card's `card_number`, its `status`, its projected `balance_cents`, and the program `currency`."

    Design: Corner/endpoints/get_card_balance_api_returns_status_and_balance
    """
    _merchant, _program, _batch, card = setup_single_active_card(5000)
    res = api.get_gift_card_balance(card["id"], POS)
    data = validate_success(res, 200)
    assert data["status"] == "ACTIVE"
    assert data["balance_cents"] == 5000
    assert data["currency"] == "USD"
    assert data["card_number"] == card["card_number"]


# ─────────── Corner: redemption / reload validations ───────────

def test_redeem_to_zero_auto_closes_card(api):
    """PRD §3.4: "if the redemption brings the card's `balance_cents` to exactly 0 the card auto-closes from `ACTIVE` to the terminal `CLOSED` state."

    Design: Corner/calculations/redeem_to_zero_auto_closes_card
    """
    _merchant, _program, _batch, card = setup_single_active_card(5000)
    res = api.redeem_gift_card(card["id"], redeem_payload(5000), POS)
    updated = validate_success(res, 200)
    assert updated["balance_cents"] == 0
    assert updated["status"] == "CLOSED"


def test_redeem_over_balance_rejected(api):
    """PRD §3.4: "and finally the amount must not exceed the current `balance_cents`, otherwise `ERR_INSUFFICIENT_BALANCE`."

    Design: Corner/validations/redeem_exceeds_balance_returns_insufficient_balance
    """
    _merchant, _program, _batch, card = setup_single_active_card(5000)
    res = api.redeem_gift_card(card["id"], redeem_payload(6000), POS)
    validate_error(res, "ERR_INSUFFICIENT_BALANCE")
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["balance_cents"] == 5000


def test_reload_below_min_load_rejected(api):
    """PRD §3.4: "the amount must be at least the program's `min_load_cents`, otherwise `ERR_BELOW_MIN_LOAD` (HTTP 422)"

    Design: Corner/validations/reload_below_min_load_returns_below_min_load
    """
    _merchant, _program, _batch, card = setup_single_active_card(5000)
    res = api.reload_gift_card(card["id"], reload_payload(100), POS)
    validate_error(res, "ERR_BELOW_MIN_LOAD")


def test_reload_over_max_balance_rejected(api):
    """PRD §3.4: "and the projected post-load balance must not exceed the program's `max_balance_cents`, otherwise `ERR_MAX_BALANCE_EXCEEDED`. The projected post-load balance is the existing balance plus the reload amount plus any incentive bonus that would be granted."

    Design: Corner/validations/reload_over_max_balance_returns_max_balance_exceeded
    """
    _merchant, _program, _batch, card = setup_single_active_card(90000)
    res = api.reload_gift_card(card["id"], reload_payload(10001), POS)
    validate_error(res, "ERR_MAX_BALANCE_EXCEEDED")
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["balance_cents"] == 90000


def test_reload_with_running_campaign_grants_incentive_bonus(api):
    """PRD §3.4: "If, at the reload instant, an `IncentiveCampaign` on the card's program is `RUNNING` (the clock is within its inclusive window), the system additionally posts an `INCENTIVE_BONUS` entry whose positive `amount_cents` is the reload amount multiplied by that campaign's `bonus_bps`, divided by 10000, rounded half up to a whole cent, and it stamps the card's `incentive_campaign_id` with that campaign."

    Design: Corner/calculations/reload_with_running_campaign_adds_incentive_bonus
    """
    _merchant, _program, campaign, card = setup_active_card_with_running_campaign(
        unit_load_cents=5000, bonus_bps=1000)
    res = api.reload_gift_card(card["id"], reload_payload(10000), POS)
    updated = validate_success(res, 200)
    assert updated["balance_cents"] == 16000  # 5000 + 10000 + 1000 bonus
    assert updated["incentive_campaign_id"] == campaign["id"]


# ─────────── Difficulty: velocity count boundary ───────────

def test_velocity_fifth_redemption_at_cap_allowed(api):
    """PRD §3.4: "The redemption is rejected with `ERR_VELOCITY_EXCEEDED` when the including-count exceeds `max_count` or the including-amount exceeds `max_amount_cents`; the boundary is strict, so a count or amount exactly equal to the cap is allowed."

    Design: Difficulty/boundary_precision_check/velocity_count_boundary_on_redeem
    """
    _merchant, _program, card, _rule = setup_velocity_scenario(
        prior_redemptions=4, redemption_amount=1000, max_count=5, max_amount_cents=50000)
    # This is the 5th in-window redemption: count 5 == cap, allowed.
    res = api.redeem_gift_card(card["id"], redeem_payload(1000), POS)
    updated = validate_success(res, 200)
    assert updated["balance_cents"] == 5000  # 10000 - 5*1000


def test_velocity_sixth_redemption_over_cap_rejected(api):
    """PRD §3.4: "The redemption is rejected with `ERR_VELOCITY_EXCEEDED` when the including-count exceeds `max_count` or the including-amount exceeds `max_amount_cents`; the boundary is strict, so a count or amount exactly equal to the cap is allowed."

    Design: Difficulty/boundary_precision_check/velocity_count_boundary_on_redeem
    """
    _merchant, _program, card, _rule = setup_velocity_scenario(
        prior_redemptions=5, redemption_amount=1000, max_count=5, max_amount_cents=50000)
    # This is the 6th in-window redemption: count 6 > 5, rejected.
    res = api.redeem_gift_card(card["id"], redeem_payload(1000), POS)
    validate_error(res, "ERR_VELOCITY_EXCEEDED")
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["balance_cents"] == 5000  # unchanged by the rejected redemption


# ─────────── Difficulty: inclusive max-balance boundary on reload ───────────

def test_reload_exactly_to_max_balance_accepted(api):
    """PRD §3.4: "and the projected post-load balance must not exceed the program's `max_balance_cents`, otherwise `ERR_MAX_BALANCE_EXCEEDED`. The projected post-load balance is the existing balance plus the reload amount plus any incentive bonus that would be granted."

    Design: Difficulty/boundary_precision_check/max_balance_inclusive_boundary_on_reload
    """
    _merchant, _program, _batch, card = setup_single_active_card(90000)
    res = api.reload_gift_card(card["id"], reload_payload(10000), POS)  # -> exactly 100000
    updated = validate_success(res, 200)
    assert updated["balance_cents"] == 100000
    assert updated["status"] == "ACTIVE"


def test_reload_one_below_max_balance_accepted(api):
    """PRD §3.4: "and the projected post-load balance must not exceed the program's `max_balance_cents`, otherwise `ERR_MAX_BALANCE_EXCEEDED`. The projected post-load balance is the existing balance plus the reload amount plus any incentive bonus that would be granted."

    Design: Difficulty/boundary_precision_check/max_balance_inclusive_boundary_on_reload
    """
    _merchant, _program, _batch, card = setup_single_active_card(90000)
    res = api.reload_gift_card(card["id"], reload_payload(9999), POS)  # -> 99999, below cap
    updated = validate_success(res, 200)
    assert updated["balance_cents"] == 99999
    assert updated["status"] == "ACTIVE"
