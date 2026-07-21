"""Validation-priority conflicts, cross-entity state guards, and the campaign
window buffer.

Covers Difficulty priority_pair_validation_conflict, cross_entity_state_dependency
(card activate), and resource_temporal_overlap (campaign window).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_incentive_campaign_payload,
    TEST_USERS, make_merchant_admin_headers,
    setup_active_card_with_open_hold, setup_active_card_retired_program,
    setup_inactive_card_with_program_state, setup_program_with_one_campaign,
    api_client,
)

POS = TEST_USERS["pos_terminal_headers"]
ANY = TEST_USERS["any_headers"]


# ─────────── Difficulty: redeem state precondition beats fiscal check ───────────

def test_redeem_suspended_over_balance_returns_card_not_active(api):
    """PRD §3.4: "The redemption path evaluates its guards in this order: first the card must itself be `ACTIVE` — an `INACTIVE`, `SUSPENDED`, `EXPIRED`, `ESCHEATED`, or `CLOSED` card is rejected with `ERR_CARD_NOT_ACTIVE`; next the velocity rule is checked, yielding `ERR_VELOCITY_EXCEEDED` if it trips; and finally the amount must not exceed the current `balance_cents`, otherwise `ERR_INSUFFICIENT_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/redeem_state_beats_fiscal
    """
    _merchant, _program, _card, _hold = setup_active_card_with_open_hold(10000, reason="MANUAL")
    res = api.redeem_gift_card(_card["id"], {"amount_cents": 999999}, POS)
    validate_error(res, "ERR_CARD_NOT_ACTIVE")


def test_redeem_suspended_over_balance_leaves_balance_unchanged(api):
    """PRD §3.4: "The redemption path evaluates its guards in this order: first the card must itself be `ACTIVE` — an `INACTIVE`, `SUSPENDED`, `EXPIRED`, `ESCHEATED`, or `CLOSED` card is rejected with `ERR_CARD_NOT_ACTIVE`; next the velocity rule is checked, yielding `ERR_VELOCITY_EXCEEDED` if it trips; and finally the amount must not exceed the current `balance_cents`, otherwise `ERR_INSUFFICIENT_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/redeem_state_beats_fiscal
    """
    _merchant, _program, card, _hold = setup_active_card_with_open_hold(10000, reason="MANUAL")
    api.redeem_gift_card(card["id"], {"amount_cents": 999999}, POS)
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["balance_cents"] == 10000


# ─────────── Difficulty: reload referential check beats capacity constraint ───────────

def test_reload_retired_program_over_max_returns_program_not_active(api):
    """PRD §3.4: "The reload path checks, in order: the card must be `ACTIVE` (else `ERR_CARD_NOT_ACTIVE`); the owning program must be `ACTIVE`, so a reference to a `PAUSED` or `RETIRED` program is rejected with `ERR_PROGRAM_NOT_ACTIVE` before any capacity check; the amount must be at least the program's `min_load_cents`, otherwise `ERR_BELOW_MIN_LOAD` (HTTP 422); and the projected post-load balance must not exceed the program's `max_balance_cents`, otherwise `ERR_MAX_BALANCE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/reload_referential_beats_constraint
    """
    _merchant, _program, card = setup_active_card_retired_program(90000)
    res = api.reload_gift_card(card["id"], {"amount_cents": 50000}, POS)
    validate_error(res, "ERR_PROGRAM_NOT_ACTIVE")


def test_reload_retired_program_over_max_leaves_balance_unchanged(api):
    """PRD §3.4: "The reload path checks, in order: the card must be `ACTIVE` (else `ERR_CARD_NOT_ACTIVE`); the owning program must be `ACTIVE`, so a reference to a `PAUSED` or `RETIRED` program is rejected with `ERR_PROGRAM_NOT_ACTIVE` before any capacity check; the amount must be at least the program's `min_load_cents`, otherwise `ERR_BELOW_MIN_LOAD` (HTTP 422); and the projected post-load balance must not exceed the program's `max_balance_cents`, otherwise `ERR_MAX_BALANCE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/reload_referential_beats_constraint
    """
    _merchant, _program, card = setup_active_card_retired_program(90000)
    api.reload_gift_card(card["id"], {"amount_cents": 50000}, POS)
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["balance_cents"] == 90000


# ─────────── Difficulty: card activate requires owning program ACTIVE ───────────

def test_activate_card_on_paused_program_rejected(api):
    """PRD §3.4: "Activation is permitted only while the card is `INACTIVE` (else `ERR_INVALID_STATE`) and only while the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/card_activate_requires_program_active
    """
    _merchant, _program, card = setup_inactive_card_with_program_state("PAUSED")
    res = api.activate_gift_card(card["id"], POS)
    validate_error(res, "ERR_PROGRAM_NOT_ACTIVE")
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["status"] == "INACTIVE"


def test_activate_card_on_retired_program_rejected(api):
    """PRD §3.4: "Activation is permitted only while the card is `INACTIVE` (else `ERR_INVALID_STATE`) and only while the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/card_activate_requires_program_active
    """
    _merchant, _program, card = setup_inactive_card_with_program_state("RETIRED")
    res = api.activate_gift_card(card["id"], POS)
    validate_error(res, "ERR_PROGRAM_NOT_ACTIVE")
    after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert after["status"] == "INACTIVE"


# ─────────── Difficulty: campaign window 7-day buffer ───────────

def test_campaign_within_buffer_rejected(api):
    """PRD §3.2: "the closed window `[starts_at, ends_at]` of a new campaign must be separated from every other campaign on that program by at least seven days of buffer, so any pair of campaign windows on one program that fall within seven days of each other is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/campaign_window_buffer_overlap
    """
    merchant, program, _campaign = setup_program_with_one_campaign(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z")
    admin = make_merchant_admin_headers(merchant["id"])
    # Second window starts only 3 days after the first ends -> below the 7-day buffer.
    res = api.create_incentive_campaign(
        create_incentive_campaign_payload(
            program["id"], "2026-09-03T00:00:00Z", "2026-09-30T00:00:00Z",
            bonus_bps=1000, name="Sep"), admin)
    validate_error(res, "ERR_CAMPAIGN_WINDOW_OVERLAP")


def test_campaign_well_separated_accepted(api):
    """PRD §3.2: "the closed window `[starts_at, ends_at]` of a new campaign must be separated from every other campaign on that program by at least seven days of buffer, so any pair of campaign windows on one program that fall within seven days of each other is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/campaign_window_buffer_overlap
    """
    merchant, program, _campaign = setup_program_with_one_campaign(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z")
    admin = make_merchant_admin_headers(merchant["id"])
    # Second window is a full month later — comfortably beyond the 7-day buffer.
    res = api.create_incentive_campaign(
        create_incentive_campaign_payload(
            program["id"], "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z",
            bonus_bps=1000, name="Oct"), admin)
    campaign = validate_success(res, 201)
    assert campaign["card_program_id"] == program["id"]
