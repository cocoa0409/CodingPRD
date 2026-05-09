"""KR score and Objective progress recompute (with cascade up)."""

import db
from util import round4


def compute_kr_score(kr: dict) -> float:
    mt = kr.get("measurement_type")
    if mt in ("NUMERIC", "PERCENTAGE"):
        sv = kr.get("start_value")
        tv = kr.get("target_value")
        cv = kr.get("current_value")
        if sv is None or tv is None:
            raw = 0.0
        else:
            if cv is None:
                cv = sv
            denom = tv - sv
            if denom == 0:
                raw = 1.0 if cv >= tv else 0.0
            else:
                raw = (cv - sv) / denom
    elif mt == "MILESTONE":
        ms = kr.get("milestones") or []
        total = len(ms)
        if total == 0:
            raw = 0.0
        else:
            done = sum(1 for m in ms if m.get("completed"))
            raw = done / total
    else:
        raw = 0.0
    clamped = max(0.0, min(1.0, raw))
    return round4(clamped)


def recompute_kr_score(kr: dict):
    kr["score"] = compute_kr_score(kr)


def compute_objective_progress(objective: dict) -> float:
    """Per-PRD §3.4: per-term-rounded weighted sum, then round result to 4dp."""
    obj_id = objective["id"]
    active_krs = [kr for kr in db.key_results.values()
                  if kr.get("objective_id") == obj_id and kr.get("status") == "ACTIVE"]
    active_children = [o for o in db.objectives.values()
                       if o.get("parent_objective_id") == obj_id and o.get("status") == "ACTIVE"]
    if active_krs:
        total = 0.0
        for kr in active_krs:
            s = round4(kr.get("score") or 0.0)
            w = float(kr.get("weight") or 0.0)
            total += s * w
        return round4(total)
    if active_children:
        total = 0.0
        for c in active_children:
            p = round4(c.get("progress") or 0.0)
            w = float(c.get("weight") or 0.0)
            total += p * w
        return round4(total)
    return 0.0


def recompute_objective_progress(objective: dict, *, cascade_up=True):
    """Recompute progress for objective, then cascade up."""
    objective["progress"] = compute_objective_progress(objective)
    objective["kr_count"] = sum(1 for kr in db.key_results.values()
                                if kr.get("objective_id") == objective["id"]
                                and kr.get("status") == "ACTIVE")
    objective["child_count"] = sum(1 for o in db.objectives.values()
                                   if o.get("parent_objective_id") == objective["id"]
                                   and o.get("status") == "ACTIVE")
    if cascade_up:
        parent_id = objective.get("parent_objective_id")
        if parent_id:
            parent = db.objectives.get(parent_id)
            if parent:
                recompute_objective_progress(parent, cascade_up=True)
