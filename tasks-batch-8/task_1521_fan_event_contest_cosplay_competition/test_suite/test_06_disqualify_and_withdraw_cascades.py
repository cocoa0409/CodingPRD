"""Disqualification's transitive cascade, terminal-state lockdown, and
entry_count reconciliation on withdraw.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

LEAD = TEST_USERS["contest_lead_headers"]


def _tabulation_contest():
    """Contest advanced to TABULATION: single category TABULATED with
    e1 rank 1 (sheet 9,9,9) and e2 rank 2 (sheet 8,8,8), both LOCKED."""
    scenario = fx.setup_tabulated_category(
        prize_purse_cents=100000, prize_budget_cents=100000,
        entry_sheets=[[(9, 9, 9)], [(8, 8, 8)]],
    )
    fx.transition_contest(scenario["contest"]["id"], "TABULATION")
    return scenario


def test_disqualify_cascades_sheets_category_contest(api):
    """PRD §3.8: "Link one: every scoresheet of the entry in `DRAFT`, `SUBMITTED`, or `LOCKED` is voided, moving it to the terminal `VOID` state. Link two: voiding sheets breaks the locked-sheet completeness of a `TABULATED` category, so the tabulation reopen cascade of §3.5 fires — the category reverts to `SCORING` and sibling placements are cleared. Link three: a category leaving `TABULATED` breaks the all-categories-tabulated invariant of a contest in `TABULATION`, so the contest auto-reverts to `JUDGING`."
    PRD §3.8: "When the disqualified entry was itself `PLACED`, its `placement_rank` is cleared as part of the revert."

    Design: Difficulty/transitive_cascade/disqualify_cascade_sheets_category_contest
    """
    scenario = _tabulation_contest()
    contest = scenario["contest"]
    category = scenario["categories"][0]
    e1, e2 = scenario["entries"][0]
    s1, s2 = scenario["sheets"][0][0][0], scenario["sheets"][0][1][0]

    disqualified = validate_success(api.disqualify_entry(e1["id"], LEAD))
    assert disqualified["status"] == "DISQUALIFIED"
    assert disqualified["placement_rank"] is None

    # Link 1: the disqualified entry's LOCKED sheet is voided; the sibling's
    # sheet is untouched.
    assert fx.get_scoresheet(s1["id"])["status"] == "VOID"
    assert fx.get_scoresheet(s2["id"])["status"] == "LOCKED"

    # Link 2: the category reverts and sibling placements are cleared.
    assert fx.get_category(category["id"])["status"] == "SCORING"
    entry2 = fx.get_entry(e2["id"])
    assert entry2["status"] == "PERFORMED"
    assert entry2["placement_rank"] is None

    # Link 3: the contest auto-reverts from TABULATION to JUDGING.
    assert fx.get_contest(contest["id"])["status"] == "JUDGING"


def test_disqualify_revokes_pending_award_and_restores_budget(api):
    """PRD §3.8: "In parallel, the direct fan-out releases resources: any `BOOKED` pre-judging slot of the entry returns to `OPEN` with `booked_entry_id` cleared; any `QUEUED` or `ON_STAGE` performance slot of the entry is marked `SKIPPED` followed by stage sequence compaction; and any prize award of the entry still in `PENDING` or `APPROVED` is revoked with its `value_cents` restored to the contest budget."
    PRD §3.1: "The invariant `prize_budget_cents == budget_reserved_cents + budget_available_cents` holds at all times."

    Design: Difficulty/transitive_cascade/disqualify_cascade_sheets_category_contest
    """
    scenario = _tabulation_contest()
    contest = scenario["contest"]
    category = scenario["categories"][0]
    e1 = scenario["entries"][0][0]

    award = fx.create_award(category["id"], 1, creator_id="tr_1")
    assert fx.get_contest(contest["id"])["budget_reserved_cents"] == 50000

    disqualified = validate_success(api.disqualify_entry(e1["id"], LEAD))
    assert disqualified["status"] == "DISQUALIFIED"

    award_after = fx.get_prize_award(award["id"])
    assert award_after["status"] == "REVOKED"
    contest_after = fx.get_contest(contest["id"])
    assert contest_after["budget_reserved_cents"] == 0
    assert contest_after["budget_available_cents"] == 100000


# ---------------------------------------------------------------------------
# Terminal lockdown and entry_count reconciliation
# ---------------------------------------------------------------------------

def test_withdrawn_entry_is_terminal(api):
    """PRD §3.3: "Withdrawal is the contestant's own exit and is permitted from `SUBMITTED`, `SAFETY_REJECTED`, `SAFETY_APPROVED`, `PREJUDGED`, or `STAGE_QUEUED`; attempts from any other state are rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "Disqualification by a `ContestLead` is the most far-reaching action in the system and is permitted from any entry state other than `WITHDRAWN` or `DISQUALIFIED` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/withdraw_terminal_lockdown
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, category["id"], title="E1")
    headers = fx.contestant_headers(contestant)
    validate_success(api.withdraw_entry(entry["id"], headers))

    resp_withdraw = api.withdraw_entry(entry["id"], headers)
    validate_error(resp_withdraw, ApiErrorId.ERR_INVALID_STATE)

    resp_disqualify = api.disqualify_entry(entry["id"], LEAD)
    validate_error(resp_disqualify, ApiErrorId.ERR_INVALID_STATE)

    assert fx.get_entry(entry["id"])["status"] == "WITHDRAWN"


def test_category_entry_count_reconciles_on_withdraw(api):
    """PRD §3.1: "A category also carries a computed `entry_count`: the number of its entries whose status is neither `WITHDRAWN` nor `DISQUALIFIED`."
    PRD §2.9: "The system maintains alignment between parent and child resources automatically, without requiring the client to issue compensating calls."

    Design: Corner/cross_cutting_layers/category_entry_count_reconciles_on_withdraw
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    c1 = fx.create_contestant(full_name="C One")
    c2 = fx.create_contestant(full_name="C Two")
    e1 = fx.create_entry(c1, category["id"], title="E1")
    fx.create_entry(c2, category["id"], title="E2")

    assert fx.get_category(category["id"])["entry_count"] == 2

    validate_success(api.withdraw_entry(e1["id"], fx.contestant_headers(c1)))
    assert fx.get_category(category["id"])["entry_count"] == 1
