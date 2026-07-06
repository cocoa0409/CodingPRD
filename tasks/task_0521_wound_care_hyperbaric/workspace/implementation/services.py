"""Shared business-logic helpers: clock, plan recompute, cascades, healing."""
from db import db, now_iso
from calc import (
    actual_healing_pct,
    projected_healing_pct,
    hbo_coverage_cents,
    _parse_dt,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def center_clock(center_id):
    c = db.centers.get(center_id)
    return c["current_utc"] if c else None


def patient_center_clock(patient):
    return center_clock(patient["center_id"])


# ---------------------------------------------------------------------------
# Common-field mutation helpers
# ---------------------------------------------------------------------------
def touch(entity):
    """Bump updated_at + version on a full-common-fields entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# HBO provisional recompute
# ---------------------------------------------------------------------------
def _patient_policy(plan):
    patient = db.patients.get(plan["patient_id"])
    if not patient:
        return None
    return db.payer_policies.get(patient["payer_policy_id"])


def recompute_provisional_hbo(plan):
    policy = _patient_policy(plan)
    if not policy:
        plan["provisional_hbo_covered_cents"] = 0
        return
    cap = policy["max_covered_hbo_sessions"]
    rate = policy["per_session_cents"]
    prov_n = sum(
        1 for s in db.hbo_sessions.values()
        if s["treatment_plan_id"] == plan["id"] and s["status"] in ("SCHEDULED", "COMPLETED")
    )
    plan["provisional_hbo_covered_cents"] = hbo_coverage_cents(prov_n, cap, rate)


def finalized_hbo(plan):
    policy = _patient_policy(plan)
    if not policy:
        return 0
    cap = policy["max_covered_hbo_sessions"]
    rate = policy["per_session_cents"]
    final_n = sum(
        1 for s in db.hbo_sessions.values()
        if s["treatment_plan_id"] == plan["id"] and s["status"] == "COMPLETED"
    )
    return hbo_coverage_cents(final_n, cap, rate)


# ---------------------------------------------------------------------------
# Healing trajectory over a patient's assessments
# ---------------------------------------------------------------------------
def _sorted_assessments_asc(patient_id):
    items = [a for a in db.wound_assessments.values() if a["patient_id"] == patient_id]
    # assessed_at ASC, tie created_at ASC; id never a decision input
    items.sort(key=lambda a: (_parse_dt(a["assessed_at"]), _parse_dt(a["created_at"])))
    return items


def compute_healing(plan):
    """Return (actual_pct, projected_pct) for the plan, or (None, None) if not computable."""
    patient_id = plan["patient_id"]
    asc = _sorted_assessments_asc(patient_id)
    baseline = db.wound_assessments.get(plan.get("baseline_assessment_id"))
    if not baseline or not asc:
        return None, None
    baseline_area = baseline["area_cm2"]
    latest = asc[-1]
    latest_area = latest["area_cm2"]
    actual = actual_healing_pct(baseline_area, latest_area)
    projected = None
    if len(asc) >= 2:
        prev = asc[-2]
        prev_area = prev["area_cm2"]
        days = (_parse_dt(latest["assessed_at"]) - _parse_dt(prev["assessed_at"])).total_seconds() / 86400.0
        if days > 0:
            projected = projected_healing_pct(prev_area, latest_area, days, baseline_area)
    return actual, projected


# ---------------------------------------------------------------------------
# Cascade: cancel SCHEDULED HBO sessions of a plan, release chamber slots
# ---------------------------------------------------------------------------
def cancel_scheduled_sessions_of_plan(plan):
    for s in db.hbo_sessions.values():
        if s["treatment_plan_id"] == plan["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
            chamber = db.chambers.get(s["chamber_id"])
            if chamber:
                chamber["occupied_slot_count"] -= 1
                touch(chamber)
