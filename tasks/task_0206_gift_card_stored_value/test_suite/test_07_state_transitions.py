"""State-machine transitions: invalid transitions, terminal lockdown, preconditions,
auto-transitions, valid transitions, and side-effect cascades.

Queue B (Corner) section state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_program, issue_card, create_active_card, create_campaign,
    setup_program_and_active_card, place_hold, flag_card,
    draft_redemption, settle_redemption, set_clock,
    setup_open_replacement,
    activate_card_payload, reload_card_payload, create_redemption_payload,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]
_FRAUD = TEST_USERS["fraud_analyst_headers"]


def test_activate_already_active_card_rejected(api):
    """PRD §3.3: "The card must currently be INACTIVE — activating a card in any other
    lifecycle state is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/activate_already_active_card_returns_invalid_state
    """
    program, card = setup_program_and_active_card(settled_cents=4000)
    res = api.activate_card(card["id"], activate_card_payload(1000), _STORE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["settled_balance_cents"] == 4000, "no second LOAD posted"


def test_void_already_voided_redemption_rejected(api):
    """PRD §2.8 / §3.5: a redemption's terminal VOIDED state — "A DRAFT redemption may instead
    be voided by a StoreAssociate (DRAFT to VOIDED) ... is permitted only while the status is
    DRAFT (otherwise ERR_INVALID_STATE)."

    Design: Corner/state_machines/void_already_voided_redemption_terminal_lockdown
    """
    program, card = setup_program_and_active_card(settled_cents=4000)
    redemption = draft_redemption(program["id"], 1000, [card["id"]])
    validate_success(api.void_redemption(redemption["id"], _STORE), 200)
    res = api.void_redemption(redemption["id"], _STORE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_flag_inactive_card_rejected(api):
    """PRD §3.7: "Flagging a card moves its risk_status CLEAR to FLAGGED and is permitted only
    when the card's lifecycle_status is ACTIVE or EXHAUSTED (ERR_INVALID_STATE)."

    Design: Corner/state_machines/flag_inactive_card_rejected_lifecycle_guard
    """
    program = create_program()
    card = issue_card(program["id"])  # INACTIVE
    res = api.flag_card(card["id"], _FRAUD)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_card_auto_exhausts_when_balance_hits_zero(api):
    """PRD §3.5: "any card whose settled balance reaches zero auto-transitions ACTIVE to
    EXHAUSTED as a cascade."

    Design: Corner/state_machines/card_auto_exhausts_when_balance_hits_zero
    """
    program, card = setup_program_and_active_card(settled_cents=2000)
    redemption = draft_redemption(program["id"], 2000, [card["id"]])
    validate_success(settle_redemption(redemption["id"], redemption["version"]), 200)
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["settled_balance_cents"] == 0
    assert after["lifecycle_status"] == "EXHAUSTED"


def test_reload_revives_exhausted_card(api):
    """PRD §3.3: "Reviving an EXHAUSTED card via reload makes it ACTIVE again."

    Design: Corner/state_machines/reload_revives_exhausted_card_to_active
    """
    program, card = setup_program_and_active_card(settled_cents=2000)
    redemption = draft_redemption(program["id"], 2000, [card["id"]])
    validate_success(settle_redemption(redemption["id"], redemption["version"]), 200)
    # Card is now EXHAUSTED; reload revives it.
    validate_success(api.reload_card(card["id"], reload_card_payload(1500), _STORE), 200)
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["lifecycle_status"] == "ACTIVE"
    assert after["settled_balance_cents"] == 1500


def test_freeze_releases_active_holds_cascade(api):
    """PRD §3.7: "as a cascade, every AuthorizationHold on the card whose status is ACTIVE is
    released to RELEASED and pending_hold_cents recomputes to zero."

    Design: Corner/state_machines/freeze_releases_active_holds_cascade
    """
    program, card = setup_program_and_active_card(settled_cents=5000)
    h1 = place_hold(card["id"], 1000)
    place_hold(card["id"], 500)
    flag_card(card["id"])
    validate_success(api.freeze_card(card["id"], _FRAUD), 200)
    hold_after = validate_success(api.get_hold(h1["id"], _FRAUD), 200)
    assert hold_after["status"] == "RELEASED"
    card_after = validate_success(api.get_card(card["id"], _FRAUD), 200)
    assert card_after["pending_hold_cents"] == 0
    assert card_after["settled_balance_cents"] == 5000
    assert card_after["available_balance_cents"] == 5000


def test_release_active_hold_restores_available_balance(api):
    """PRD §3.4: "A StoreAssociate may release an ACTIVE hold whose expiry has not yet passed:
    the hold moves ACTIVE to RELEASED, its pending_hold_cents contribution is removed so
    available_balance_cents rises back by the held amount, and settled_balance_cents is
    unchanged."

    Design: Corner/state_machines/hold_release_on_active_hold
    """
    program, card = setup_program_and_active_card(settled_cents=5000, hold_ttl_seconds=900)
    hold = place_hold(card["id"], 2000)
    released = validate_success(api.release_hold(hold["id"], _STORE), 200)
    assert released["status"] == "RELEASED"
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    assert after["pending_hold_cents"] == 0
    assert after["available_balance_cents"] == 5000


def test_reject_replacement_leaves_card_intact(api):
    """PRD §3.7: "A FraudAnalyst may reject an OPEN request (OPEN to REJECTED, no card
    mutation, must be OPEN else ERR_INVALID_STATE)."

    Design: Corner/state_machines/replacement_reject_no_card_mutation
    """
    program, card, replacement = setup_open_replacement(settled_cents=3000, reason="LOST")
    rejected = validate_success(api.reject_replacement(replacement["id"], _FRAUD), 200)
    assert rejected["status"] == "REJECTED"
    after = validate_success(api.get_card(card["id"], _FRAUD), 200)
    assert after["lifecycle_status"] == "ACTIVE"
    assert after["settled_balance_cents"] == 3000


def test_campaign_sync_status_scheduled_to_active(api):
    """PRD §3.1: "while the current instant is at or after window_start and before window_end,
    the campaign becomes ACTIVE (SCHEDULED to ACTIVE)."

    Design: Corner/state_machines/campaign_sync_status_scheduled_to_active
    """
    program = create_program()
    campaign = create_campaign(program["id"], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z",
                               name="Winter", bonus_pct=0.10)
    set_clock("2026-02-01T00:00:00Z")
    synced = validate_success(api.sync_campaign_status(campaign["id"], _ADMIN), 200)
    assert synced["status"] == "ACTIVE"
