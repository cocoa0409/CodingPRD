"""Game tag census and quality index maintenance (PRD §2.11, §3.6)."""

import db
from calc import event_tag_quality_index
from util import num

CENSUS_FIELD = {
    "DRAFT": "draft_tag_count",
    "SUBMITTED": "submitted_tag_count",
    "ACCEPTED": "accepted_tag_count",
    "UNDER_CORRECTION": "under_correction_tag_count",
    "SUPERSEDED": "superseded_tag_count",
}


def move_census(game, from_status, to_status):
    """Move one tag row between census buckets; total_tag_count is untouched."""
    if from_status is not None:
        game[CENSUS_FIELD[from_status]] = game[CENSUS_FIELD[from_status]] - 1
    if to_status is not None:
        game[CENSUS_FIELD[to_status]] = game[CENSUS_FIELD[to_status]] + 1


def recompute_quality_index(game):
    """Recompute and write ``quality_index`` (4 decimals, round half up)."""
    scored = [t["confidence"] for t in db.tags_of_game(game["id"])
              if t["review_status"] in ("ACCEPTED", "UNDER_CORRECTION")]
    value = event_tag_quality_index(
        scored,
        game["approved_correction_count"],
        game["rejected_correction_count"],
        game["accepted_tag_count"],
    )
    game["quality_index"] = num(value)
    return value
