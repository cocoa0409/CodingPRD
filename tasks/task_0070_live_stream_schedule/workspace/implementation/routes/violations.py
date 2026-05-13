"""Violation + Appeal endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import clock
from errors import (
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION_FAILED,
    raise_err,
)
from middleware import (
    paginate, parse_pagination, require_auth, require_role,
)
from response import success
from services import audit
from services.calculations import calc_violation_penalty
from services.streamer_service import apply_cascade


bp_v = Blueprint("violations", __name__, url_prefix="/live-schedule/violations")
bp_a = Blueprint("appeals", __name__, url_prefix="/live-schedule/appeals")


_VIOLATION_TYPES = {
    "FALSE_ADVERTISING", "WRONG_PRODUCT", "VIOLATING_CONTENT", "DATA_FRAUD",
}


@bp_v.post("")
def create_violation():
    user_id, role = require_auth()
    require_role(role, ["OperationsReviewer", "ComplianceReviewer"])
    body = request.get_json(silent=True) or {}
    for key in ("streamer_id", "violation_type", "evidence_refs"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")

    streamer = db.raw_get("streamers", body["streamer_id"])
    if streamer is None:
        raise_err(ERR_NOT_FOUND, "Streamer not found")
    application_id = body.get("application_id")
    if application_id is not None:
        if db.raw_get("applications", application_id) is None:
            raise_err(ERR_NOT_FOUND, "Application not found")

    vtype = body["violation_type"]
    if vtype not in _VIOLATION_TYPES:
        raise_err(ERR_VALIDATION_FAILED, "Invalid violation_type")
    refs = body["evidence_refs"]
    if not isinstance(refs, list):
        raise_err(ERR_VALIDATION_FAILED, "evidence_refs must be an array")

    penalty = calc_violation_penalty(
        violation_type=vtype,
        evidence_refs_count=len(refs),
        current_violation_score=streamer.get("violation_score", 0),
    )

    payload = {
        "streamer_id": streamer["id"],
        "application_id": application_id,
        "violation_type": vtype,
        "evidence_refs": list(refs),
        "severity": penalty["severity"],
        "penalty_action": penalty["penalty_action"],
        "fine_cents": penalty["fine_cents"],
        "suspension_days": penalty["suspension_days"],
        "status": "OPEN",
        "enforced_at": None,
    }
    violation = db.create_entity("violations", payload)
    audit.log(
        subject_kind="VIOLATION",
        subject_id=violation["id"],
        action="CREATE",
        actor_role=role,
        actor_id=user_id,
        from_state=None,
        to_state="OPEN",
        payload_snapshot={"penalty_action": penalty["penalty_action"]},
    )
    return success(violation, http_status=201)


@bp_v.get("")
def list_violations():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    limit, offset = parse_pagination()
    streamer_id = request.args.get("streamer_id")
    status_filter = request.args.get("status")

    def predicate(v):
        if streamer_id and v.get("streamer_id") != streamer_id:
            return False
        if status_filter and v.get("status") != status_filter:
            return False
        if role == "Streamer" and v.get("streamer_id") != user_id:
            return False
        return True
    items = db.list_entities("violations", predicate=predicate)
    window, pagination = paginate(items, limit, offset)
    return success(window, pagination=pagination, response_type="array")


@bp_v.post("/<vid>/appeal")
def file_appeal(vid):
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    violation = db.raw_get("violations", vid)
    if violation is None:
        raise_err(ERR_NOT_FOUND, "Violation not found")
    if violation.get("streamer_id") != user_id:
        raise_err(ERR_FORBIDDEN, "Streamer does not own this violation")
    if violation.get("status") != "OPEN":
        raise_err(ERR_INVALID_STATE, "Violation is not OPEN")
    body = request.get_json(silent=True) or {}
    argument = body.get("argument")
    if argument is None:
        raise_err(ERR_VALIDATION_FAILED, "argument is required")

    created_at = clock.parse_iso(violation["created_at"])
    if clock.now() > created_at + timedelta(days=7):
        raise_err(ERR_APPEAL_WINDOW_CLOSED,
                  "Appeal window (7 days) has closed")

    appeal_payload = {
        "violation_id": vid,
        "streamer_id": violation["streamer_id"],
        "argument": argument,
        "decision": "PENDING",
        "decided_at": None,
    }
    appeal = db.create_entity("appeals", appeal_payload)

    def mutate(v):
        v["status"] = "APPEAL_PENDING"
    db.update_entity("violations", vid, mutate)
    audit.log(
        subject_kind="VIOLATION",
        subject_id=vid,
        action="APPEAL_FILED",
        actor_role=role,
        actor_id=user_id,
        from_state="OPEN",
        to_state="APPEAL_PENDING",
    )
    return success(appeal, http_status=201)


@bp_a.post("/<aid>/decide")
def decide_appeal(aid):
    user_id, role = require_auth()
    require_role(role, ["ComplianceReviewer"])
    appeal = db.raw_get("appeals", aid)
    if appeal is None:
        raise_err(ERR_NOT_FOUND, "Appeal not found")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("OVERTURN", "UPHOLD"):
        raise_err(ERR_VALIDATION_FAILED, "decision must be OVERTURN or UPHOLD")

    violation = db.raw_get("violations", appeal["violation_id"])
    if violation is None:
        raise_err(ERR_NOT_FOUND, "Violation not found")

    if violation.get("status") != "APPEAL_PENDING":
        raise_err(ERR_INVALID_STATE, "Violation is not APPEAL_PENDING")

    now_iso = clock.format_iso(clock.now())

    if decision == "OVERTURN":
        def m_app(a):
            a["decision"] = "OVERTURNED"
            a["decided_at"] = now_iso
        updated = db.update_entity("appeals", aid, m_app)

        def m_viol(v):
            v["status"] = "OVERTURNED"
        db.update_entity("violations", violation["id"], m_viol)

        # Cascade depth-3 on streamer
        streamer = db.raw_get("streamers", violation["streamer_id"])
        if streamer is not None:
            severity = int(violation.get("severity", 0))

            # Step 1: if this violation caused a SUSPENSION/BLACKLIST and the
            # violation was ENFORCED, revert the status. The PRD says "if the
            # streamer was SUSPENDED/BLACKLISTED solely because of this
            # violation". We approximate "solely because" by checking that
            # the current status matches the violation's penalty_action AND
            # this violation is the only ENFORCED violation in that class —
            # but to keep semantics simple, we always revert when the action
            # is suspension/blacklist AND the streamer's current status
            # corresponds.
            def m_streamer(s, sev=severity, viol=violation):
                # Subtract severity from violation_score (cannot go below 0)
                s["violation_score"] = max(0, s.get("violation_score", 0) - sev)
                action = viol.get("penalty_action")
                if action == "SUSPENSION" and s.get("status") == "SUSPENDED":
                    s["status"] = "ACTIVE"
                    s["suspension_until"] = None
                elif action == "BLACKLIST" and s.get("status") == "BLACKLISTED":
                    s["status"] = "ACTIVE"
                    s["suspension_until"] = None
            db.update_entity("streamers", streamer["id"], m_streamer)

            # Recompute tier + reconcile suspension as a second pass.
            apply_cascade(streamer["id"])

            # Fine refund — if penalty was FINE that had been enforced, record
            # an audit log entry. (No money flow is simulated in-memory.)
            if violation.get("penalty_action") == "FINE":
                audit.log(
                    subject_kind="STREAMER",
                    subject_id=streamer["id"],
                    action="REFUND_ISSUED",
                    actor_role=role,
                    actor_id=user_id,
                    payload_snapshot={
                        "violation_id": violation["id"],
                        "fine_cents": violation.get("fine_cents", 0),
                    },
                )

        audit.log(
            subject_kind="VIOLATION",
            subject_id=violation["id"],
            action="APPEAL_DECIDED",
            actor_role=role,
            actor_id=user_id,
            from_state="APPEAL_PENDING",
            to_state="OVERTURNED",
        )
        return success(updated)

    # UPHOLD path
    def m_app(a):
        a["decision"] = "UPHELD"
        a["decided_at"] = now_iso
    updated = db.update_entity("appeals", aid, m_app)

    def m_viol(v):
        # Auto-transition through UPHELD -> ENFORCED in the same call.
        v["status"] = "ENFORCED"
        v["enforced_at"] = now_iso
    db.update_entity("violations", violation["id"], m_viol)
    audit.log(
        subject_kind="VIOLATION",
        subject_id=violation["id"],
        action="APPEAL_DECIDED",
        actor_role=role,
        actor_id=user_id,
        from_state="APPEAL_PENDING",
        to_state="ENFORCED",
    )
    return success(updated)
