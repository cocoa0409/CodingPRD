"""Retention sweeps (PRD §3.9) and the logical clock endpoint (PRD §2.5)."""
import db
import serializers
import util
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, fmt_dt, new_id, next_seq, parse_dt

bp = Blueprint("retention", __name__)


@bp.post("/talent/retention-sweeps")
def retention_sweep():
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    util.get_body()
    now = db.get_now()
    purged_ids = []
    for a in list(db.stores["assessments"].values()):
        if a["admin_status"] != "COMPLETED":
            continue
        if a["retention_expires_at"] is None:
            continue
        if not (now > a["retention_expires_at"]):
            continue
        # COMPLETED -> PURGED
        expiry_snapshot = a["retention_expires_at"]
        a["admin_status"] = "PURGED"
        a["raw_score"] = None
        a["composite_score"] = None
        a["completed_at"] = None
        a["purged_at"] = now
        if a["feedback_status"] == "NOT_SENT":
            a["feedback_status"] = "NOT_APPLICABLE"
        bump(a)
        # Redact every scorecard for this (cycle, candidate)
        for sc in db.stores["scorecards"].values():
            sess = db.stores["sessions"].get(sc["session_id"])
            if sess is None:
                continue
            if sess["cycle_id"] == a["cycle_id"] and sess["candidate_id"] == a["candidate_id"]:
                if not sc["redacted"]:
                    sc["redacted"] = True
                    sc["ratings"] = None
                    sc["weighted_total"] = None
                    bump(sc)
        # Append the purge event
        evt = {
            "id": new_id(),
            "candidate_assessment_id": a["id"],
            "event_type": "ASSESSMENT_PURGED",
            "executed_by_user_id": ctx.user_id,
            "retention_expires_at_snapshot": expiry_snapshot,
            "created_at": now,
            "_created": now,
            "_seq": next_seq(),
        }
        db.stores["purge_events"][evt["id"]] = evt
        # Decrement the parent cycle's count
        cyc = db.stores["cycles"].get(a["cycle_id"])
        if cyc is not None:
            cyc["active_candidate_count"] = max(0, cyc["active_candidate_count"] - 1)
        purged_ids.append(a["id"])
    return success_object({
        "purged_count": len(purged_ids),
        "purged_assessment_ids": purged_ids,
    })


@bp.post("/talent/_clock/set_current_utc")
def set_clock():
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    body = util.get_body()
    to = parse_dt(body.get("to_iso8601"), "to_iso8601")
    db.set_now(to)
    expired, lapsed = core.materialize_time_transitions(to)
    return success_object({
        "now": fmt_dt(to),
        "instruments_expired": expired,
        "calibrations_lapsed": lapsed,
    })
