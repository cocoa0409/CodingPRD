"""Reload arithmetic: pinned tier-before-accrual evaluation order, loyalty-tier
thresholds, anonymous cards, the balance cap, card operability, and the ledger."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_game_card_payload,
)
from test_helpers.fixtures import (
    create_member, issue_card, activate_card, reload_card, freeze_card,
    get_card, get_card_ledger, create_attraction, play,
)

CASHIER = TEST_USERS["cashier_headers"]


def _member_active_card(api):
    member = create_member(api)
    card = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])
    return member, card


# --- Difficulty: reload_bonus_pinned_eval_order (pinned tier-before-accrual) ---
def test_reload_crossing_threshold_grants_zero_bonus_from_pre_reload_tier(api):
    """PRD §3.2: "First, the member's tier is read from their current `lifetime_spend_cents`,
    before this reload's amount is added. That pre-reload tier selects the bonus rate: a
    `NONE` member earns no bonus, a `SILVER` member earns five percent, a `GOLD` member earns
    ten percent, and a `PLATINUM` member earns twenty percent."

    Design: Difficulty/combinatorial_formula/reload_bonus_pinned_eval_order
    """
    member, card = _member_active_card(api)
    reload_card(api, card["id"], 44_000)  # lifetime 44000, tier NONE
    updated = reload_card(api, card["id"], 6_000)  # pre-reload tier NONE -> bonus 0
    assert updated["bonus_chip_balance_cents"] == 0
    assert updated["chip_balance_cents"] == 50_000


def test_reload_recomputes_stored_tier_after_accrual(api):
    """PRD §3.2: "Fourth, and only now, the member's `lifetime_spend_cents` grows by
    `amount_cents`, and their `membership_tier` is recomputed from that new lifetime spend."
    PRD §3.2: "a member is `PLATINUM` at 500,000 cents or more, otherwise `GOLD` at 200,000
    cents or more, otherwise `SILVER` at 50,000 cents or more, otherwise `NONE`."

    Design: Difficulty/combinatorial_formula/reload_bonus_pinned_eval_order
    """
    member, card = _member_active_card(api)
    reload_card(api, card["id"], 44_000)
    reload_card(api, card["id"], 6_000)
    got = validate_success(api.get_member(member["id"], CASHIER))
    assert got["lifetime_spend_cents"] == 50_000
    assert got["membership_tier"] == "SILVER"


# --- Difficulty: tier_threshold_exact_50000 (boundary precision) ---
def test_tier_flips_silver_at_exactly_50000(api):
    """PRD §3.2: "a member is `PLATINUM` at 500,000 cents or more, otherwise `GOLD` at
    200,000 cents or more, otherwise `SILVER` at 50,000 cents or more, otherwise `NONE`."

    Design: Difficulty/boundary_precision_check/tier_threshold_exact_50000
    """
    member, card = _member_active_card(api)
    reload_card(api, card["id"], 44_000)
    reload_card(api, card["id"], 6_000)  # lifetime exactly 50000
    got = validate_success(api.get_member(member["id"], CASHIER))
    assert got["lifetime_spend_cents"] == 50_000
    assert got["membership_tier"] == "SILVER"


def test_tier_stays_none_just_below_50000(api):
    """PRD §3.2: "a member is `PLATINUM` at 500,000 cents or more, otherwise `GOLD` at
    200,000 cents or more, otherwise `SILVER` at 50,000 cents or more, otherwise `NONE`."

    Design: Difficulty/boundary_precision_check/tier_threshold_exact_50000
    """
    member, card = _member_active_card(api)
    reload_card(api, card["id"], 44_000)
    reload_card(api, card["id"], 5_000)  # lifetime 49000 (< 50000)
    got = validate_success(api.get_member(member["id"], CASHIER))
    assert got["lifetime_spend_cents"] == 49_000
    assert got["membership_tier"] == "NONE"


# --- Corner: reload_anonymous_card_no_bonus ---
def test_reload_anonymous_card_grants_no_bonus(api):
    """PRD §3.2: "When a card has no owner (`owner_member_id` is null), there is no member to
    score: the effective tier is `NONE`, the bonus is zero, and no lifetime spend is accrued."

    Design: Corner/calculations/reload_anonymous_card_no_bonus
    """
    card = activate_card(api, issue_card(api)["id"])  # anonymous
    updated = reload_card(api, card["id"], 1_000)
    assert updated["chip_balance_cents"] == 1_000
    assert updated["bonus_chip_balance_cents"] == 0


# --- Corner: reload_over_cap_active_card ---
def test_reload_over_balance_cap_rejected(api):
    """PRD §3.2: "the resulting `chip_balance_cents` must not exceed the per-card cap of
    100,000 cents ($1,000.00), and a reload that would breach it is rejected with
    `ERR_CARD_BALANCE_CAP_EXCEEDED` (422)."

    Design: Corner/validations/reload_over_cap_active_card
    """
    member, card = _member_active_card(api)
    reload_card(api, card["id"], 96_000)
    resp = api.reload_game_card(card["id"], {"amount_cents": 6_000}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_CARD_BALANCE_CAP_EXCEEDED, 422)
    assert get_card(api, card["id"])["chip_balance_cents"] == 96_000


# --- Corner: reload_inactive_card_not_active ---
def test_reload_inactive_card_rejected(api):
    """PRD §2.10: "for a reload, a game play, or a redemption reservation, the target card
    must be `ACTIVE`. A `FROZEN` card yields `ERR_CARD_FROZEN` (409); an `INACTIVE` or
    `CLOSED` card yields `ERR_CARD_NOT_ACTIVE` (409)."

    Design: Corner/validations/reload_inactive_card_not_active
    """
    card = issue_card(api)  # never activated -> INACTIVE
    resp = api.reload_game_card(card["id"], {"amount_cents": 1_000}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE, 409)


# --- Corner: reload_appends_ledger_entry_side_effect ---
def test_reload_appends_reload_and_bonus_grant_ledger_entries(api):
    """PRD §3.2: "Each successful reload appends a `RELOAD` ledger entry recording the
    purchased credit, and — only when the bonus is greater than zero — a `BONUS_GRANT` entry
    recording the promotional credit; the card's `version` increments."

    Design: Corner/endpoints/reload_appends_ledger_entry_side_effect
    """
    member, card = _member_active_card(api)
    reload_card(api, card["id"], 60_000)  # lifetime 60000 -> SILVER
    updated = reload_card(api, card["id"], 6_000)  # pre-reload SILVER -> 5% bonus = 300
    assert updated["bonus_chip_balance_cents"] == 300
    ledger = get_card_ledger(api, card["id"])
    bonus_grants = [e for e in ledger if e["entry_type"] == "BONUS_GRANT"]
    assert any(e["bonus_delta_cents"] == 300 for e in bonus_grants)
    reload_chips = sorted(e["chip_delta_cents"] for e in ledger if e["entry_type"] == "RELOAD")
    assert reload_chips == [6_000, 60_000]


# --- Corner: derived_balance_matches_ledger_sum ---
def test_chip_balance_equals_ledger_delta_sum(api):
    """PRD §2.7: "At any moment a card's `chip_balance_cents` equals the sum of
    `chip_delta_cents` across its entries, its `bonus_chip_balance_cents` equals the sum of
    `bonus_delta_cents`, and its `ticket_points_balance` equals the sum of `points_delta`."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_matches_ledger_sum
    """
    card = activate_card(api, issue_card(api)["id"])  # anonymous
    attraction = create_attraction(api, chip_cost_cents=200, points_award=10)
    reload_card(api, card["id"], 1_000)
    play(api, card["id"], attraction["id"])  # cost 200
    card_now = get_card(api, card["id"])
    ledger = get_card_ledger(api, card["id"])
    assert card_now["chip_balance_cents"] == 800
    assert sum(e["chip_delta_cents"] for e in ledger) == 800
