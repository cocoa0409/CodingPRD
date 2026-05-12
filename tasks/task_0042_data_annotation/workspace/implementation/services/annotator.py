"""Annotator services: tier computation, suspension cascade, rate updates."""

from __future__ import annotations

import db
from money import round_half_up_4dp
from config import (
    TIER_RANK,
    EXPERT_PASS,
    EXPERT_GOLDEN,
    EXPERT_MIN_PACKAGES,
    SENIOR_PASS,
    SENIOR_GOLDEN,
    SENIOR_MIN_PACKAGES,
    SUSPEND_PASS_RATE_THRESHOLD,
    SUSPEND_GOLDEN_THRESHOLD,
    LOOKBACK_PACKAGES,
    REPEATED_DISPUTE_THRESHOLD,
    DISPUTE_WINDOW_PACKAGES,
)
from services.audit import queue_event


def initial_tier_from_score(score) -> str:
    if score >= 95:
        return "EXPERT"
    if score >= 80:
        return "SENIOR"
    return "JUNIOR"


def tier_rank(t: str) -> int:
    return TIER_RANK.get(t, 0)


def recompute_golden_hit_rate(annotator_id: str) -> float:
    subs = db.find_many("submissions", annotator_id=annotator_id)
    hits = sum(s.get("golden_correct", 0) for s in subs)
    total = sum(s.get("golden_total", 0) for s in subs)
    if total == 0:
        return 1.0
    return round_half_up_4dp(hits / total)


def recompute_chronological_rates(annotator_id: str) -> tuple[float, float]:
    """Return (rolling_pass_rate, lifetime_pass_rate) using chronological running aggregator.

    The annotator's `submitted_count` and `approved_count` are running counters
    maintained at every transition that records a submission outcome. Lifetime
    rate is approved/submitted; rolling rate uses the most recent
    LOOKBACK_PACKAGES outcomes recorded in the annotator's outcome history.
    """
    a = db.find_by_id("annotators", annotator_id)
    if not a:
        return 1.0, 1.0
    submitted = a.get("submitted_count", 0)
    approved = a.get("approved_count", 0)
    history = a.get("outcome_history", [])  # list of bool
    if submitted == 0:
        lifetime = 1.0
    else:
        lifetime = round_half_up_4dp(approved / submitted)
    window = history[-LOOKBACK_PACKAGES:]
    if not window:
        rolling = 1.0
    else:
        rolling = round_half_up_4dp(sum(1 for x in window if x) / len(window))
    return rolling, lifetime


def recompute_tier(annotator: dict) -> str:
    """Compute the annotator's tier from current rolling/golden/submitted counters.
    Suspension overlay handled separately.
    """
    rolling = annotator.get("rolling_pass_rate", 1.0)
    golden = annotator.get("golden_hit_rate", 1.0)
    submitted = annotator.get("submitted_count", 0)
    if rolling >= EXPERT_PASS and golden >= EXPERT_GOLDEN and submitted >= EXPERT_MIN_PACKAGES:
        return "EXPERT"
    if rolling >= SENIOR_PASS and golden >= SENIOR_GOLDEN and submitted >= SENIOR_MIN_PACKAGES:
        return "SENIOR"
    return "JUNIOR"


def should_suspend(annotator: dict) -> bool:
    rolling = annotator.get("rolling_pass_rate", 1.0)
    golden = annotator.get("golden_hit_rate", 1.0)
    return rolling < SUSPEND_PASS_RATE_THRESHOLD or golden < SUSPEND_GOLDEN_THRESHOLD


def apply_suspension_cascade(annotator: dict, write_log_fn=None):
    """Force tier→JUNIOR, status→SUSPENDED, revert IN_PROGRESS/REWORK_PENDING packages to POOL.
    Emits annotator.suspended IM event.
    """
    if annotator.get("status") == "SUSPENDED":
        return  # already suspended

    prev_status = annotator.get("status")
    db.update("annotators", annotator["id"], {
        "tier": "JUNIOR",
        "status": "SUSPENDED",
    })

    # Revert each in-progress / rework_pending package owned by this annotator.
    for pkg in db.all_rows("task_packages"):
        if pkg.get("assigned_annotator_id") != annotator["id"]:
            continue
        if pkg.get("status") not in {"IN_PROGRESS", "REWORK_PENDING"}:
            continue
        prev_state = pkg["status"]
        db.update("task_packages", pkg["id"], {
            "status": "POOL",
            "assigned_annotator_id": None,
            "claimed_at": None,
            "deadline_at": None,
        })
        if write_log_fn:
            write_log_fn(pkg["id"], prev_state, "POOL", system=True)

    queue_event("IM", "annotator.suspended", annotator["id"])


def update_after_inspection_outcome(
    annotator_id: str,
    *,
    approved: bool,
    log_fn=None,
):
    """Bump submitted/approved counters and outcome history; recompute rates.
    Run *after* the package transition has committed.
    """
    a = db.find_by_id("annotators", annotator_id)
    if not a:
        return

    submitted = a.get("submitted_count", 0) + 1
    approved_count = a.get("approved_count", 0) + (1 if approved else 0)
    history = list(a.get("outcome_history", []))
    history.append(bool(approved))

    db.update("annotators", annotator_id, {
        "submitted_count": submitted,
        "approved_count": approved_count,
        "outcome_history": history,
    })

    # Recompute golden_hit_rate from current submissions table.
    golden = recompute_golden_hit_rate(annotator_id)
    db.update("annotators", annotator_id, {"golden_hit_rate": golden})

    # Recompute chronological rates with updated counters/history.
    rolling, lifetime = recompute_chronological_rates(annotator_id)
    db.update("annotators", annotator_id, {
        "rolling_pass_rate": rolling,
        "lifetime_pass_rate": lifetime,
    })

    # Implicit tier_recompute + suspension overlay.
    a = db.find_by_id("annotators", annotator_id)
    if a.get("status") == "ACTIVE":
        if should_suspend(a):
            apply_suspension_cascade(a, write_log_fn=log_fn)
        else:
            new_tier = recompute_tier(a)
            if new_tier != a.get("tier"):
                db.update("annotators", annotator_id, {"tier": new_tier})


def projected_pass_rate(annotator_id: str) -> dict:
    """Variant B: scan all QualityInspection rows; latest appeal decision per
    inspection wins. Returns rolling/lifetime rates."""
    inspections = db.find_many("inspections")
    # Map inspection_id → resolved outcome (APPROVED bool) using latest appeal
    # decision per inspection if any.
    appeals_by_inspection = {}
    for ap in db.all_rows("appeals"):
        appeals_by_inspection.setdefault(ap["inspection_id"], []).append(ap)

    # Outcome resolution per inspection (only those for the given annotator):
    history = []
    for ins in sorted(inspections, key=lambda r: r.get("created_at") or ""):
        pkg = db.find_by_id("task_packages", ins["package_id"])
        if not pkg:
            continue
        # Submission references
        sub = db.find_by_id("submissions", ins["submission_id"])
        if not sub or sub.get("annotator_id") != annotator_id:
            continue
        if ins.get("outcome") in (None,):
            continue  # not yet finalized

        # Determine "resolved approved" considering latest appeal.
        approved = ins.get("outcome") == "PASS"
        appeals = appeals_by_inspection.get(ins["id"], [])
        if appeals:
            latest = sorted(appeals, key=lambda a: a.get("updated_at") or a.get("created_at") or "")[-1]
            if latest.get("status") == "UPHELD":
                approved = True
            elif latest.get("status") == "REJECTED":
                # Rejected appeal does not change the inspection-level outcome
                # but if the inspection itself was DISPUTED with no upheld appeal,
                # treat as not-approved.
                if ins.get("outcome") == "DISPUTED":
                    approved = False
        history.append(approved)

    if not history:
        return {"rolling_pass_rate": 1.0, "lifetime_pass_rate": 1.0}

    lifetime = round_half_up_4dp(sum(1 for h in history if h) / len(history))
    window = history[-LOOKBACK_PACKAGES:]
    rolling = round_half_up_4dp(sum(1 for h in window if h) / len(window))
    return {
        "rolling_pass_rate": rolling,
        "lifetime_pass_rate": lifetime,
    }


def trailing_rejected_appeals(annotator_id: str) -> int:
    """Count REJECTED appeals over the trailing DISPUTE_WINDOW_PACKAGES packages
    submitted by this annotator.
    """
    a = db.find_by_id("annotators", annotator_id)
    if not a:
        return 0
    history_pkgs = a.get("dispute_history", [])  # list of bool: rejected appeal flag per package
    window = history_pkgs[-DISPUTE_WINDOW_PACKAGES:]
    return sum(1 for v in window if v)


def push_dispute_history(annotator_id: str, rejected: bool):
    a = db.find_by_id("annotators", annotator_id)
    if not a:
        return
    history = list(a.get("dispute_history", []))
    history.append(bool(rejected))
    db.update("annotators", annotator_id, {"dispute_history": history})
