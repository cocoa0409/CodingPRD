"""Daily reconciliation: expected-liability snapshot, variance branching, CLOSED-card
exclusion, terminal-state guard, and duplicate-day rejection."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, issue_card, activate_card, reload_card, close_card,
    create_prize, open_reconciliation, count_reconciliation,
)

MANAGER = TEST_USERS["manager_headers"]


# --- Corner: reconciliation_reconciled_zero_variance ---
def test_reconciliation_reconciled_on_zero_variance(api):
    """PRD §3.8: "The system computes `variance_chip_cents` as the counted chip liability minus
    the expected chip liability, and `variance_prize_units` as the counted prize units minus
    the expected prize units. The reconciliation then branches on the result: if both variances
    are exactly zero it moves `OPEN → RECONCILED`; if either variance is non-zero it moves
    `OPEN → DISCREPANCY`."

    Design: Corner/calculations/reconciliation_reconciled_zero_variance
    """
    set_clock(api, "2026-05-03T00:00:00Z")
    create_prize(api, points_price=100, stock_qty=5, name="Bear")
    member = create_member(api)
    card = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])
    reload_card(api, card["id"], 6_000)
    recon = open_reconciliation(api, "2026-05-03")
    assert recon["expected_chip_liability_cents"] == 6_000
    assert recon["expected_prize_units"] == 5
    counted = count_reconciliation(api, recon["id"], 6_000, 5)
    assert counted["variance_chip_cents"] == 0
    assert counted["status"] == "RECONCILED"


# --- Corner: reconciliation_discrepancy_nonzero_variance ---
def test_reconciliation_discrepancy_on_nonzero_variance(api):
    """PRD §3.8: "if both variances are exactly zero it moves `OPEN → RECONCILED`; if either
    variance is non-zero it moves `OPEN → DISCREPANCY`."

    Design: Corner/calculations/reconciliation_discrepancy_nonzero_variance
    """
    set_clock(api, "2026-05-04T00:00:00Z")
    member = create_member(api)
    card = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])
    reload_card(api, card["id"], 6_000)
    recon = open_reconciliation(api, "2026-05-04")
    counted = count_reconciliation(api, recon["id"], 5_900, 0)  # 5900 - 6000
    assert counted["variance_chip_cents"] == -100
    assert counted["status"] == "DISCREPANCY"


# --- Corner: reconciliation_excludes_closed_cards ---
def test_open_snapshot_excludes_closed_cards(api):
    """PRD §3.8: "The `expected_chip_liability_cents` is the sum, over every game card whose
    status is `ACTIVE` or `FROZEN`, of that card's `chip_balance_cents` plus its
    `bonus_chip_balance_cents`; `CLOSED` cards are excluded."

    Design: Corner/cross_cutting_complexity_layers/reconciliation_excludes_closed_cards
    """
    set_clock(api, "2026-05-06T00:00:00Z")
    member = create_member(api)
    card_a = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])
    reload_card(api, card_a["id"], 6_000)
    close_card(api, card_a["id"])
    card_b = activate_card(api, issue_card(api, owner_member_id=member["id"])["id"])
    reload_card(api, card_b["id"], 3_000)
    recon = open_reconciliation(api, "2026-05-06")
    assert recon["expected_chip_liability_cents"] == 3_000


# --- Corner: count_non_open_reconciliation_invalid_state ---
def test_count_on_reconciled_reconciliation_rejected(api):
    """PRD §3.8: "This is permitted only while the reconciliation is `OPEN`, else
    `ERR_INVALID_RECONCILIATION_STATE` (409)."

    Design: Corner/state_machines/count_non_open_reconciliation_invalid_state
    """
    set_clock(api, "2026-05-02T00:00:00Z")
    recon = open_reconciliation(api, "2026-05-02")  # empty venue -> expected 0/0
    count_reconciliation(api, recon["id"], 0, 0)  # -> RECONCILED
    resp = api.count_reconciliation(recon["id"], {"counted_chip_liability_cents": 0,
                                                  "counted_prize_units": 0}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_RECONCILIATION_STATE, 409)
    assert validate_success(api.get_reconciliation(recon["id"], MANAGER))["status"] == "RECONCILED"


# --- Corner: duplicate_reconciliation_day_rejected ---
def test_duplicate_reconciliation_day_rejected(api):
    """PRD §3.8: "a manager opens a `DailyReconciliation` for a `business_day` (a `YYYY-MM-DD`
    UTC date, unique across reconciliations; a duplicate is rejected with
    `ERR_RECON_DUPLICATE_DAY`, 409)."

    Design: Corner/validations/duplicate_reconciliation_day_rejected
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    open_reconciliation(api, "2026-05-05")
    resp = api.create_reconciliation({"business_day": "2026-05-05"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_RECON_DUPLICATE_DAY, 409)
