"""Numerical calculations referenced by the scaffold.

Precision-sensitive computations use Decimal with ROUND_HALF_UP per PRD §2.9
and the per-calculation `precision` annotations in SCAFFOLD.yaml §1.3.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


# Constants from SCAFFOLD.yaml
W_COAUTHOR = 60
W_INSTITUTION = 30
W_EXCLUDED = 100
COI_CAP = 100
COI_REJECT_THRESHOLD = 50

W_TAG = 60
W_SUGGESTED = 30
W_LOAD = 10
REVIEWER_MAX_CONCURRENT = 3
EDITOR_ASSIGNMENT_WINDOW_DAYS = 5

WEIGHTS = {
    "ACCEPT": Decimal("1.215"),
    "MINOR_REVISION": Decimal("1.005"),
    "MAJOR_REVISION": Decimal("0.835"),
    "REJECT": Decimal("0.605"),
}

PLAGIARISM_THRESHOLD = Decimal("25.0")

MINOR_DAYS = 30
MAJOR_DAYS = 60


def round_half_up_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# C1: aggregated_category_from_recommendation_vote
# ---------------------------------------------------------------------------
def aggregated_category(
    submitted_recommendations: Iterable[str], associate_recommendation: str
) -> str:
    """Plurality among reviewer recommendations; ties broken by listing order.

    If the associate editor's recommendation_from_associate is TRANSFER, the
    aggregated_category is reported as ACCEPT.
    """
    if associate_recommendation == "TRANSFER":
        return "ACCEPT"
    order = ["ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT"]
    counts = {c: 0 for c in order}
    for rec in submitted_recommendations:
        if rec in counts:
            counts[rec] += 1
    # tie-break: pick the earliest in `order`
    best = order[0]
    for cat in order:
        if counts[cat] > counts[best]:
            best = cat
    return best


# ---------------------------------------------------------------------------
# C2: aggregate_score_from_ratings (Order A: round-per-reviewer THEN average)
# ---------------------------------------------------------------------------
def aggregate_score(reviews: list[dict]) -> Decimal:
    """reviews is a list of dicts with `rating` (int) and `recommendation` (str)."""
    if not reviews:
        return Decimal("0.00")
    per_reviewer: list[Decimal] = []
    for r in reviews:
        weight = WEIGHTS.get(r["recommendation"], Decimal("0"))
        raw = Decimal(int(r["rating"])) * weight
        per_reviewer.append(round_half_up_2(raw))
    total = sum(per_reviewer, Decimal("0"))
    avg = total / Decimal(len(reviews))
    return round_half_up_2(avg)


# ---------------------------------------------------------------------------
# C3a: conflict_of_interest_score
# ---------------------------------------------------------------------------
def coi_signals(
    author_rows: list[dict],
    reviewer_row: dict,
    excluded_reviewer_ids: list[str],
) -> tuple[bool, bool, bool]:
    """Return (signal_co_authorship, signal_same_institution, signal_excluded)."""
    reviewer_id = reviewer_row["id"]
    reviewer_collaborators = set(reviewer_row.get("recent_collaborator_ids") or [])
    reviewer_institution = reviewer_row.get("institution")

    signal_coauth = False
    signal_same_inst = False
    for a in author_rows:
        a_collab = set(a.get("recent_collaborator_ids") or [])
        if reviewer_id in a_collab or a["id"] in reviewer_collaborators:
            signal_coauth = True
        if a.get("institution") and a.get("institution") == reviewer_institution:
            signal_same_inst = True

    signal_excluded = reviewer_id in (excluded_reviewer_ids or [])
    return signal_coauth, signal_same_inst, signal_excluded


def coi_score_from_signals(s_coauth: bool, s_same_inst: bool, s_excluded: bool) -> int:
    raw = (
        (W_COAUTHOR if s_coauth else 0)
        + (W_INSTITUTION if s_same_inst else 0)
        + (W_EXCLUDED if s_excluded else 0)
    )
    return min(raw, COI_CAP)


# ---------------------------------------------------------------------------
# C3b: reviewer_match_score (load-subtractive variant, pinned)
# ---------------------------------------------------------------------------
def match_score(
    manuscript: dict,
    reviewer: dict,
) -> int:
    tag_match = 1 if manuscript["topic_tag"] in (reviewer.get("expertise_tags") or []) else 0
    suggested_bonus = 1 if reviewer["id"] in (manuscript.get("suggested_reviewer_ids") or []) else 0
    load_penalty = int(reviewer.get("active_assignments") or 0)
    raw = W_TAG * tag_match + W_SUGGESTED * suggested_bonus - W_LOAD * load_penalty
    return max(0, min(100, raw))


# ---------------------------------------------------------------------------
# C4: plagiarism_pass_fail
# ---------------------------------------------------------------------------
def plagiarism_result(similarity_percent: Decimal | float | int) -> str:
    s = similarity_percent if isinstance(similarity_percent, Decimal) else Decimal(str(similarity_percent))
    return "FAIL" if s >= PLAGIARISM_THRESHOLD else "PASS"
