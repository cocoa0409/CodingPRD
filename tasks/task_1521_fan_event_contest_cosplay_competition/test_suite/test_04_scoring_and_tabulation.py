"""Scoring and tabulation: sheet_total rounding, dual-variant final scores,
trimmed-mean panel-size fallback, placement tie-breaks, judge referential
checks, tabulate preconditions, and the lock/reopen cycle.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_entry,
    assert_scoresheet,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

LEAD = TEST_USERS["contest_lead_headers"]


# ---------------------------------------------------------------------------
# Dual variant: identical sheets, different tabulation_method
# ---------------------------------------------------------------------------

def _dual_variant_scenario(tabulate=False):
    """One JUDGING contest with two categories (WEIGHTED_MEAN, TRIMMED_MEAN),
    each holding one PERFORMED entry with identical LOCKED sheets
    (8,9,7), (9,8,9), (6,7,6) -> sheet_totals 8.10, 8.70, 6.30."""
    return fx.setup_scored_contest(
        [
            {"name": "ArmorW", "tabulation_method": "WEIGHTED_MEAN",
             "prize_purse_cents": 100000,
             "entries": [{"title": "E1",
                          "sheets": [(8, 9, 7), (9, 8, 9), (6, 7, 6)]}]},
            {"name": "ArmorT", "tabulation_method": "TRIMMED_MEAN",
             "prize_purse_cents": 100000,
             "entries": [{"title": "E2",
                          "sheets": [(8, 9, 7), (9, 8, 9), (6, 7, 6)]}]},
        ],
        prize_budget_cents=100000,
        lock=True,
        tabulate=tabulate,
    )


def test_trimmed_vs_weighted_final_score(api):
    """PRD §3.5: "Under the `WEIGHTED_MEAN` variant, `final_score` is the mean of `sheet_total` over that set, rounded half-up to two decimal places. Under the `TRIMMED_MEAN` variant, when the set holds at least three sheets, exactly one highest `sheet_total` and exactly one lowest `sheet_total` are discarded (on ties only one instance of the extreme value is dropped) before the same rounded mean is taken over the remainder"
    PRD §3.5: "In that order, `placement_rank` is assigned 1 through N gap-free, and each ranked entry moves from `PERFORMED` to `PLACED`."

    Identical LOCKED sheet sets (sheet_totals 8.10, 8.70, 6.30) yield 7.70
    under WEIGHTED_MEAN but 8.10 under TRIMMED_MEAN.

    Design: Difficulty/dual_variant_calc/entry_score_trimmed_vs_weighted
    """
    scenario = _dual_variant_scenario()
    cat_w, cat_t = scenario["categories"]
    e1 = scenario["entries"][0][0]
    e2 = scenario["entries"][1][0]

    fx.tabulate_category(cat_w["id"])
    fx.tabulate_category(cat_t["id"])

    entry_w = fx.get_entry(e1["id"])
    entry_t = fx.get_entry(e2["id"])
    assert entry_w["final_score"] == pytest.approx(7.70, abs=0.001)
    assert entry_t["final_score"] == pytest.approx(8.10, abs=0.001)
    assert entry_w["placement_rank"] == 1
    assert entry_t["placement_rank"] == 1
    assert entry_w["status"] == "PLACED"
    assert entry_t["status"] == "PLACED"
    assert fx.get_category(cat_w["id"])["status"] == "TABULATED"
    assert fx.get_category(cat_t["id"])["status"] == "TABULATED"


def test_trimmed_vs_weighted_craftsmanship_mean_and_sheet_totals(api):
    """PRD §3.5: "At creation the system computes and stores `sheet_total`: half the `craftsmanship` score plus three-tenths of the `accuracy` score plus one-fifth of the `presentation` score, rounded half-up to two decimal places."
    PRD §3.5: "The `craftsmanship_mean` is the mean of the raw `craftsmanship` criterion across the same locked set, rounded half-up to two decimal places, and exists purely as the placement tie-breaker."
    PRD §3.5: "The input set is the entry's `LOCKED` scoresheets — `DRAFT`, `SUBMITTED`, and `VOID` sheets are excluded — pooling both phases with equal weight per sheet."

    The sheet set (8,9,7), (9,8,9), (6,7,6) produces sheet_totals
    8.10 / 8.70 / 6.30 at creation; the craftsmanship tie-break field is
    (8+9+6)/3 = 7.67 under both variants.

    Design: Difficulty/dual_variant_calc/entry_score_trimmed_vs_weighted
    """
    scenario = _dual_variant_scenario()
    cat_w, cat_t = scenario["categories"]

    for sheet in scenario["sheets"][0][0] + scenario["sheets"][1][0]:
        assert_scoresheet(sheet)
        assert sheet["status"] == "LOCKED"
    totals = sorted(s["sheet_total"] for s in scenario["sheets"][0][0])
    assert totals[0] == pytest.approx(6.30, abs=0.001)
    assert totals[1] == pytest.approx(8.10, abs=0.001)
    assert totals[2] == pytest.approx(8.70, abs=0.001)

    fx.tabulate_category(cat_w["id"])
    fx.tabulate_category(cat_t["id"])

    entry_w = fx.get_entry(scenario["entries"][0][0]["id"])
    entry_t = fx.get_entry(scenario["entries"][1][0]["id"])
    assert entry_w["craftsmanship_mean"] == pytest.approx(7.67, abs=0.001)
    assert entry_t["craftsmanship_mean"] == pytest.approx(7.67, abs=0.001)
    # Only the final_score differs across the two variants.
    assert entry_w["final_score"] == pytest.approx(7.70, abs=0.001)
    assert entry_t["final_score"] == pytest.approx(8.10, abs=0.001)


# ---------------------------------------------------------------------------
# Combinatorial formula: TRIMMED_MEAN panel-size branch
# ---------------------------------------------------------------------------

def test_trimmed_mean_falls_back_below_three_sheets(api):
    """PRD §3.5: "when the set holds fewer than three sheets, `TRIMMED_MEAN` falls back to the plain `WEIGHTED_MEAN` result."
    PRD §3.5: "Tabulation then computes, for each `PERFORMED` entry, the entry's `final_score` and `craftsmanship_mean`. The input set is the entry's `LOCKED` scoresheets — `DRAFT`, `SUBMITTED`, and `VOID` sheets are excluded — pooling both phases with equal weight per sheet."

    Two LOCKED sheets (10,10,10) -> 10.00 and (4,4,4) -> 4.00: no extremes
    are dropped, so the TRIMMED_MEAN category reports the plain mean 7.00.

    Design: Difficulty/combinatorial_formula/weighted_score_panel_size_branch
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Trim", "skill_division": "NOVICE",
          "tabulation_method": "TRIMMED_MEAN", "prize_purse_cents": 30000,
          "entries": [{"title": "E1", "sheets": [(10, 10, 10), (4, 4, 4)]}]}],
        prize_budget_cents=50000,
    )
    category = scenario["categories"][0]
    entry = scenario["entries"][0][0]

    fx.tabulate_category(category["id"])
    placed = fx.get_entry(entry["id"])
    assert placed["final_score"] == pytest.approx(7.00, abs=0.001)
    assert placed["craftsmanship_mean"] == pytest.approx(7.00, abs=0.001)
    assert placed["status"] == "PLACED"
    assert placed["placement_rank"] == 1


def test_trimmed_mean_single_sheet_panel(api):
    """PRD §3.5: "when the set holds fewer than three sheets, `TRIMMED_MEAN` falls back to the plain `WEIGHTED_MEAN` result."

    A one-sheet panel: the single LOCKED sheet (8,9,7) -> sheet_total 8.10 is
    both the trimmed and weighted result; trimming would empty the set.

    Design: Difficulty/combinatorial_formula/weighted_score_panel_size_branch
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Trim", "skill_division": "NOVICE",
          "tabulation_method": "TRIMMED_MEAN", "prize_purse_cents": 30000,
          "entries": [{"title": "E1", "sheets": [(8, 9, 7)]}]}],
        prize_budget_cents=50000,
    )
    category = scenario["categories"][0]
    entry = scenario["entries"][0][0]

    fx.tabulate_category(category["id"])
    placed = fx.get_entry(entry["id"])
    assert placed["final_score"] == pytest.approx(8.10, abs=0.001)
    assert placed["craftsmanship_mean"] == pytest.approx(8.00, abs=0.001)
    assert placed["placement_rank"] == 1


# ---------------------------------------------------------------------------
# Placement tie-breaks
# ---------------------------------------------------------------------------

def test_placement_tiebreak_craftsmanship_mean(api):
    """PRD §3.5: "Entries are ordered by `final_score` descending; ties break by `craftsmanship_mean` descending; further ties break by `created_at` ascending; `id` is never used as a tie-break."

    Entry A sheets (9,8,5), (9,8,5), (5,9,0) and entry B sheets (7,8,8),
    (7,8,8), (6,6,6): both final_scores are 7.00; craftsmanship_mean
    7.67 vs 6.67 decides rank 1. Sheet (9,8,5) verifies sheet_total 7.90.

    Design: Corner/calculations/placement_tiebreak_craftsmanship_mean
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Armor", "tabulation_method": "WEIGHTED_MEAN",
          "prize_purse_cents": 100000,
          "entries": [
              {"title": "A", "sheets": [(9, 8, 5), (9, 8, 5), (5, 9, 0)]},
              {"title": "B", "sheets": [(7, 8, 8), (7, 8, 8), (6, 6, 6)]},
          ]}],
    )
    category = scenario["categories"][0]
    ea, eb = scenario["entries"][0]

    sheet_a1 = scenario["sheets"][0][0][0]
    assert sheet_a1["sheet_total"] == pytest.approx(7.90, abs=0.001)

    fx.tabulate_category(category["id"])
    entry_a = fx.get_entry(ea["id"])
    entry_b = fx.get_entry(eb["id"])
    assert entry_a["final_score"] == pytest.approx(7.00, abs=0.001)
    assert entry_b["final_score"] == pytest.approx(7.00, abs=0.001)
    assert entry_a["craftsmanship_mean"] == pytest.approx(7.67, abs=0.001)
    assert entry_b["craftsmanship_mean"] == pytest.approx(6.67, abs=0.001)
    assert entry_a["placement_rank"] == 1
    assert entry_b["placement_rank"] == 2


def test_placement_tiebreak_created_at_order(api):
    """PRD §3.5: "Entries are ordered by `final_score` descending; ties break by `craftsmanship_mean` descending; further ties break by `created_at` ascending; `id` is never used as a tie-break."
    PRD §2.7: "it supplies the timestamps written to `created_at` and `updated_at` across the system."

    Both entries tie fully (8.0 / 8.0); the logical clock is advanced between
    the two creations so created_at orders them: the earlier entry wins.

    Design: Corner/calculations/placement_tiebreak_created_at_order
    """
    contest = fx.create_contest(prize_budget_cents=100000)
    category = fx.create_category(contest["id"], prize_purse_cents=100000)
    fx.open_registration(contest["id"])

    fx.set_logical_clock("2026-08-01T00:00:00Z")
    c1 = fx.create_contestant(full_name="C One")
    e1 = fx.create_entry(c1, category["id"], title="First")
    fx.set_logical_clock("2026-08-01T00:01:00Z")
    c2 = fx.create_contestant(full_name="C Two")
    e2 = fx.create_entry(c2, category["id"], title="Second")

    fx.approve_entry_safety(e1["id"])
    fx.approve_entry_safety(e2["id"])
    fx.grant_livestream_consent(c1)
    fx.grant_livestream_consent(c2)
    fx.advance_contest_to_judging(contest["id"])
    judge = fx.create_judge(contest["id"], [category["id"]])
    fx.perform_entry(e1["id"], 1)
    fx.perform_entry(e2["id"], 2)
    fx.submit_sheet(e1["id"], judge, 8, 8, 8)
    fx.submit_sheet(e2["id"], judge, 8, 8, 8)
    fx.lock_category_scoresheets(category["id"])

    fx.tabulate_category(category["id"])
    entry1 = fx.get_entry(e1["id"])
    entry2 = fx.get_entry(e2["id"])
    assert entry1["final_score"] == pytest.approx(8.00, abs=0.001)
    assert entry2["final_score"] == pytest.approx(8.00, abs=0.001)
    assert entry1["craftsmanship_mean"] == pytest.approx(8.00, abs=0.001)
    assert entry2["craftsmanship_mean"] == pytest.approx(8.00, abs=0.001)
    assert entry1["created_at"] < entry2["created_at"]
    assert entry1["placement_rank"] == 1
    assert entry2["placement_rank"] == 2


# ---------------------------------------------------------------------------
# Judge referential checks
# ---------------------------------------------------------------------------

def test_judge_conflict_of_interest(api):
    """PRD §3.5: "If the judge has a `linked_contestant_id` and that contestant holds a non-terminal entry in the scoresheet entry's category, the request is rejected with `ERR_JUDGE_CONFLICT`."

    The conflict is category-scoped: the judge may not score ANY entry of the
    category their linked contestant competes in.

    Design: Corner/validations/judge_conflict_of_interest_returns_409
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    c1 = fx.create_contestant(full_name="C One")
    c2 = fx.create_contestant(full_name="C Two")
    e1 = fx.create_entry(c1, category["id"], title="E1")
    e2 = fx.create_entry(c2, category["id"], title="E2")
    fx.approve_entry_safety(e2["id"])
    fx.grant_livestream_consent(c2)
    fx.advance_contest_to_judging(contest["id"])
    judge = fx.create_judge(contest["id"], [category["id"]],
                            linked_contestant_id=c1["id"])
    fx.perform_entry(e2["id"], 1)

    resp = api.create_scoresheet(
        {"entry_id": e2["id"], "phase": "STAGE",
         "craftsmanship": 8, "accuracy": 8, "presentation": 8},
        fx.judge_headers(judge),
    )
    validate_error(resp, ApiErrorId.ERR_JUDGE_CONFLICT)


def test_duplicate_scoresheet_same_judge_phase(api):
    """PRD §3.5: "And if a non-`VOID` scoresheet already exists for the same `(judge_id, entry_id, phase)` triple, the request is rejected with `ERR_DUPLICATE_SCORESHEET`."

    The second create fails even while the first sheet is still DRAFT.

    Design: Corner/validations/duplicate_scoresheet_same_judge_phase_returns_409
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Armor", "entries": [{"title": "E1", "sheets": []}]}],
        prize_budget_cents=50000, lock=False,
    )
    category = scenario["categories"][0]
    entry = scenario["entries"][0][0]
    judge = fx.create_judge(scenario["contest"]["id"], [category["id"]])

    resp1 = api.create_scoresheet(
        {"entry_id": entry["id"], "phase": "STAGE",
         "craftsmanship": 8, "accuracy": 8, "presentation": 8},
        fx.judge_headers(judge),
    )
    sheet = validate_success(resp1, 201)
    assert sheet["status"] == "DRAFT"

    resp2 = api.create_scoresheet(
        {"entry_id": entry["id"], "phase": "STAGE",
         "craftsmanship": 7, "accuracy": 7, "presentation": 7},
        fx.judge_headers(judge),
    )
    validate_error(resp2, ApiErrorId.ERR_DUPLICATE_SCORESHEET)


# ---------------------------------------------------------------------------
# Tabulate preconditions
# ---------------------------------------------------------------------------

def test_tabulate_with_unlocked_sheets_rejected(api):
    """PRD §3.5: "Two preconditions apply, in order: first, no scoresheet of any entry in the category may remain in `DRAFT` or `SUBMITTED`, otherwise the request is rejected with `ERR_SCORESHEETS_NOT_LOCKED`; second, at least one entry of the category must be in `PERFORMED`, otherwise `ERR_NO_ELIGIBLE_ENTRIES`."
    PRD §3.5: "A `ContestLead` then locks the entire category in bulk: while the category is `SCORING` (otherwise `ERR_INVALID_STATE`), every `SUBMITTED` sheet of every entry in the category moves to `LOCKED`."

    Design: Corner/validations/tabulate_with_unlocked_sheets_returns_409
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Armor", "prize_purse_cents": 30000,
          "entries": [{"title": "E1", "sheets": [(9, 9, 9)]}]}],
        prize_budget_cents=50000, lock=False,
    )
    category = scenario["categories"][0]

    resp = api.tabulate_category(category["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_SCORESHEETS_NOT_LOCKED)
    assert fx.get_category(category["id"])["status"] == "SCORING"

    locked = fx.lock_category_scoresheets(category["id"])
    assert locked == 1
    result = fx.tabulate_category(category["id"])
    assert result["placed_entry_count"] == 1


def test_tabulate_with_zero_performed_entries_rejected(api):
    """PRD §3.5: "Two preconditions apply, in order: first, no scoresheet of any entry in the category may remain in `DRAFT` or `SUBMITTED`, otherwise the request is rejected with `ERR_SCORESHEETS_NOT_LOCKED`; second, at least one entry of the category must be in `PERFORMED`, otherwise `ERR_NO_ELIGIBLE_ENTRIES`."

    A category with no PERFORMED entries cannot tabulate even though the
    all-locked precondition is vacuously true.

    Design: Corner/validations/tabulate_with_zero_performed_returns_409
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    fx.advance_contest_to_judging(contest["id"])

    resp = api.tabulate_category(category["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES)


# ---------------------------------------------------------------------------
# Scoresheet lock/reopen cycle
# ---------------------------------------------------------------------------

def test_scoresheet_lock_reopen_lock_cycle(api):
    """PRD §3.5: "A `ContestLead` then locks the entire category in bulk: while the category is `SCORING` (otherwise `ERR_INVALID_STATE`), every `SUBMITTED` sheet of every entry in the category moves to `LOCKED`."
    PRD §3.5: "Should a correction be needed afterward, the lead may reopen a `LOCKED` sheet, returning it to `SUBMITTED`; if the sheet's category had already been tabulated, this reopen is one of the two triggers of the tabulation reopen cascade described below."

    DRAFT -> SUBMITTED -> LOCKED -> SUBMITTED -> LOCKED, and the second lock
    still feeds tabulation: the single (9,9,9) sheet (sheet_total 9.00) yields
    final_score 9.00.

    Design: Difficulty/non_linear_state_machine/scoresheet_lock_reopen_cycle
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Armor", "prize_purse_cents": 30000,
          "entries": [{"title": "E1", "sheets": [(9, 9, 9)]}]}],
        prize_budget_cents=50000, lock=False,
    )
    category = scenario["categories"][0]
    entry = scenario["entries"][0][0]
    sheet = scenario["sheets"][0][0][0]
    assert sheet["status"] == "SUBMITTED"

    locked = fx.lock_category_scoresheets(category["id"])
    assert locked == 1
    assert fx.get_scoresheet(sheet["id"])["status"] == "LOCKED"

    reopened = validate_success(api.reopen_scoresheet(sheet["id"], LEAD))
    assert reopened["status"] == "SUBMITTED"

    fx.lock_category_scoresheets(category["id"])
    assert fx.get_scoresheet(sheet["id"])["status"] == "LOCKED"

    fx.tabulate_category(category["id"])
    placed = fx.get_entry(entry["id"])
    assert placed["status"] == "PLACED"
    assert placed["final_score"] == pytest.approx(9.00, abs=0.001)
    assert placed["placement_rank"] == 1


def test_scoresheet_reopen_and_lock_state_gates(api):
    """PRD §3.5: "Should a correction be needed afterward, the lead may reopen a `LOCKED` sheet, returning it to `SUBMITTED`; if the sheet's category had already been tabulated, this reopen is one of the two triggers of the tabulation reopen cascade described below."
    PRD §3.5: "A `ContestLead` then locks the entire category in bulk: while the category is `SCORING` (otherwise `ERR_INVALID_STATE`), every `SUBMITTED` sheet of every entry in the category moves to `LOCKED`."

    The bulk lock is rejected once the category has left SCORING, and a reopen
    of a LOCKED sheet in a TABULATED category fires the reopen cascade.

    Design: Difficulty/non_linear_state_machine/scoresheet_lock_reopen_cycle
    """
    scenario = fx.setup_scored_contest(
        [{"name": "Armor", "prize_purse_cents": 30000,
          "entries": [{"title": "E1", "sheets": [(9, 9, 9)]}]}],
        prize_budget_cents=50000, lock=True, tabulate=True,
    )
    contest = scenario["contest"]
    category = scenario["categories"][0]
    entry = scenario["entries"][0][0]
    sheet = scenario["sheets"][0][0][0]

    # Bulk lock is gated on the category being SCORING; it is TABULATED now.
    resp_lock = api.lock_scoresheets(category["id"], LEAD)
    validate_error(resp_lock, ApiErrorId.ERR_INVALID_STATE)

    # Reopen the LOCKED sheet: allowed, and it reverts the category to SCORING.
    reopened = validate_success(api.reopen_scoresheet(sheet["id"], LEAD))
    assert reopened["status"] == "SUBMITTED"
    assert fx.get_category(category["id"])["status"] == "SCORING"
    entry_after = fx.get_entry(entry["id"])
    assert entry_after["status"] == "PERFORMED"
    assert entry_after["placement_rank"] is None
    assert entry_after["final_score"] is None
    assert entry_after["craftsmanship_mean"] is None
