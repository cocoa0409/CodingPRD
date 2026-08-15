"""Shared entity helpers: base fields, mutation touch, cascades."""
from datetime import datetime, timezone

import clock
import db
from services.risk import PIA_RISK_THRESHOLD, screening_score

OPEN_ASSESSMENT_STATUSES = ("TRIGGERED", "IN_REVIEW", "CHANGES_REQUESTED")


def base_entity():
    ts = clock.now()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    """Every mutation (including cascade-driven) bumps version by exactly 1
    and refreshes updated_at."""
    entity["version"] += 1
    entity["updated_at"] = clock.now()


def created_asc(items):
    """created_at ASC; Python's stable sort keeps insertion order on ties."""
    return sorted(items, key=lambda e: e["created_at"])


# --- Assessments --------------------------------------------------------------

def has_open_assessment(activity_id):
    return any(
        a["activity_id"] == activity_id and a["status"] in OPEN_ASSESSMENT_STATUSES
        for a in db.assessments.values()
    )


def create_assessment(activity, trigger_reason):
    assessment = base_entity()
    assessment.update({
        "activity_id": activity["id"],
        "trigger_reason": trigger_reason,
        "screening_score": activity["risk_score"],
        "final_score": None,
        "submitted_by_user_id": None,
        "status": "TRIGGERED",
    })
    db.assessments[assessment["id"]] = assessment
    return assessment


# --- Cross-border transfer cascade helpers ------------------------------------

def suspend_transfers_for_activity(activity_id):
    targets = [t for t in db.transfers.values()
               if t["activity_id"] == activity_id and t["status"] == "APPROVED"]
    for t in created_asc(targets):
        t["status"] = "SUSPENDED"
        t["suspension_reason"] = "ACTIVITY_HOLD"
        touch(t)


def reinstate_transfers_for_activity(activity_id):
    targets = [t for t in db.transfers.values()
               if t["activity_id"] == activity_id
               and t["status"] == "SUSPENDED"
               and t["suspension_reason"] == "ACTIVITY_HOLD"]
    for t in created_asc(targets):
        t["status"] = "APPROVED"
        t["suspension_reason"] = None
        touch(t)


# --- Activity auto-resume ------------------------------------------------------

def maybe_resume_activity(activity):
    """COMPLIANCE_HOLD -> ACTIVE when no CONSENT_STALE purposes and no open
    assessments remain; reinstates ACTIVITY_HOLD-suspended transfers."""
    if activity["status"] != "COMPLIANCE_HOLD":
        return False
    has_stale = any(
        p["activity_id"] == activity["id"] and p["status"] == "CONSENT_STALE"
        for p in db.purposes.values()
    )
    if has_stale or has_open_assessment(activity["id"]):
        return False
    activity["status"] = "ACTIVE"
    touch(activity)
    reinstate_transfers_for_activity(activity["id"])
    return True


# --- DataElement reclassification cascade --------------------------------------

def reclassification_cascade(element):
    affected = [a for a in db.activities.values()
                if element["id"] in a["data_element_ids"]
                and a["status"] in ("DRAFT", "ACTIVE", "COMPLIANCE_HOLD")]
    for activity in created_asc(affected):
        was_required = activity["pia_required"]
        activity["risk_score"] = screening_score(activity)
        activity["pia_required"] = activity["risk_score"] >= PIA_RISK_THRESHOLD
        # hop 3: linked ACTIVE activities move to COMPLIANCE_HOLD.
        held = False
        if activity["status"] == "ACTIVE":
            activity["status"] = "COMPLIANCE_HOLD"
            held = True
        # Exactly one version bump per touched entity per cascade (PRD 2.9).
        touch(activity)
        # hop 2: pia_required flip false -> true auto-creates a PIA when no
        # open assessment exists for the activity.
        if (not was_required and activity["pia_required"]
                and not has_open_assessment(activity["id"])):
            create_assessment(activity, "RECLASSIFICATION")
        _ = held  # hold applied above; no transfer suspension on hold


# --- Notice window semantics ----------------------------------------------------

_FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; a null `to` is open-ended. Adjacent
    windows (shared boundary instant) do not overlap."""
    a_to_eff = a_to if a_to is not None else _FAR_FUTURE
    b_to_eff = b_to if b_to is not None else _FAR_FUTURE
    return a_from < b_to_eff and b_from < a_to_eff


def select_current_published_notice(scope):
    """The current PUBLISHED notice in scope: the one whose window contains
    the logical clock; if none contains it, the one with the latest
    effective_from; tie-break created_at ASC."""
    published = [n for n in db.notices.values()
                 if n["scope"] == scope and n["status"] == "PUBLISHED"]
    if not published:
        return None
    now = clock.now()
    containing = [n for n in published
                  if n["effective_from"] <= now
                  and (n["effective_to"] is None or now < n["effective_to"])]
    if containing:
        containing.sort(key=lambda n: n["created_at"])
        return containing[0]
    published.sort(key=lambda n: n["created_at"])
    latest_from = max(n["effective_from"] for n in published)
    for n in published:
        if n["effective_from"] == latest_from:
            return n
    return None
