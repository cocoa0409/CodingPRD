"""Card lifecycle transitions and the frozen-vs-cap validation precedence."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    create_member, issue_card, activate_card, reload_card, freeze_card, get_card,
)

MANAGER = TEST_USERS["manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def _member_active_card(api):
    member = create_member(api)
    return activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])


# --- Difficulty: frozen_beats_balance_cap (priority pair) ---
def test_frozen_card_reload_returns_card_frozen_not_cap(api):
    """PRD §2.10: "This ordering is authoritative: for example, a mid-flight freeze that
    renders a card non-operable surfaces at step 5 as `ERR_CARD_FROZEN` before any transition,
    concurrency, or fiscal check further down the list is even considered."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_balance_cap
    """
    card = _member_active_card(api)
    reload_card(api, card["id"], 96_000)
    freeze_card(api, card["id"])
    resp = api.reload_game_card(card["id"], {"amount_cents": 6_000}, CASHIER)  # frozen AND over cap
    validate_error(resp, ApiErrorId.ERR_CARD_FROZEN, 409)


def test_frozen_reload_leaves_balance_unmutated(api):
    """PRD §2.10: "for a reload, a game play, or a redemption reservation, the target card
    must be `ACTIVE`. A `FROZEN` card yields `ERR_CARD_FROZEN` (409)".

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_balance_cap
    """
    card = _member_active_card(api)
    reload_card(api, card["id"], 96_000)
    freeze_card(api, card["id"])
    api.reload_game_card(card["id"], {"amount_cents": 6_000}, CASHIER)
    assert get_card(api, card["id"])["chip_balance_cents"] == 96_000


# --- Corner: freeze_inactive_card_invalid_card_state ---
def test_freeze_inactive_card_rejected(api):
    """PRD §3.1: "Any lifecycle trigger — activate, freeze, or close — attempted from a state
    the transition table forbids is rejected with `ERR_INVALID_CARD_STATE` (409)".

    Design: Corner/state_machines/freeze_inactive_card_invalid_card_state
    """
    member = create_member(api)
    card = issue_card(api, owner_member_id=member["id"])  # INACTIVE (freeze needs ACTIVE)
    resp = api.freeze_game_card(card["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_CARD_STATE, 409)
    assert get_card(api, card["id"])["status"] == "INACTIVE"
