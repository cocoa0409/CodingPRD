"""Supervision and CE record endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.validation import (
    get_body, require_str, require_number, require_int, optional_str,
)


bp = Blueprint("supervision", __name__)


def _public(s: dict) -> dict:
    return db.public(s)


def _has_supervision_overlap(supervisor_id: str, scheduled_at_dt) -> bool:
    """Symmetric 30-minute buffer overlap with non-REJECTED rows."""
    proposed_start = scheduled_at_dt - timedelta(minutes=30)
    proposed_end = scheduled_at_dt + timedelta(minutes=30)
    for s in db.supervision_sessions.values():
        if s["supervisor_id"] != supervisor_id:
            continue
        if s["status"] == "REJECTED":
            continue
        other_at = parse_iso(s["scheduled_at"])
        other_start = other_at - timedelta(minutes=30)
        other_end = other_at + timedelta(minutes=30)
        if proposed_start < other_end and other_start < proposed_end:
            return True
    return False


@bp.route("/counseling/supervision-sessions", methods=["POST"])
@require_auth(roles={"Counselor"})
def create_supervision():
    body = get_body()
    counselor_id = require_str(body, "counselor_id")
    supervisor_id = require_str(body, "supervisor_id")
    case_appointment_id = require_str(body, "case_appointment_id")
    scheduled_at = require_str(body, "scheduled_at")
    duration_hours = require_number(body, "duration_hours")
    discussion_notes = require_str(body, "discussion_notes")

    if g.user_id != counselor_id:
        raise err("ERR_FORBIDDEN", "Counselor may only log own supervision")

    counselor = db.counselors.get(counselor_id)
    if counselor is None:
        raise err("ERR_REF_NOT_FOUND", f"counselor_id {counselor_id} not found")
    supervisor = db.counselors.get(supervisor_id)
    if supervisor is None:
        raise err("ERR_REF_NOT_FOUND", f"supervisor_id {supervisor_id} not found")
    appt = db.appointments.get(case_appointment_id)
    if appt is None:
        raise err("ERR_REF_NOT_FOUND", f"case_appointment_id {case_appointment_id} not found")

    # Eligibility
    if supervisor_id == counselor_id:
        raise err("ERR_SUPERVISOR_INELIGIBLE",
                  "Supervisor cannot be the same as supervisee")
    if not (set(supervisor.get("specialty_tags", [])) & set(counselor.get("specialty_tags", []))):
        raise err("ERR_SUPERVISOR_INELIGIBLE",
                  "Supervisor specialties must overlap supervisee's")

    # SoD: supervisor must be the eventual approver. The supervisor must be a
    # Counselor row (which it is, since both ids resolve through db.counselors).
    # Beyond that, we ensure the supervisor has not also been the
    # decided_by_user_id of any of this counselor's CertificationCycle rows.
    # (Per the SoD rule pairing with priority 24/25.)
    for cyc in db.certification_cycles.values():
        if cyc["counselor_id"] != counselor_id:
            continue
        if cyc.get("decided_by_user_id") == supervisor_id:
            raise err("ERR_SUPERVISION_SOD",
                      "Supervisor has acted as recert decider for this counselor")

    # Case appointment must be COMPLETED and counselor's own
    if appt["counselor_id"] != counselor_id:
        raise err("ERR_INVALID_CASE",
                  "case_appointment must belong to the supervisee")
    if appt["status"] != "COMPLETED":
        raise err("ERR_INVALID_CASE",
                  "case_appointment must be COMPLETED")

    if not isinstance(duration_hours, (int, float)) or duration_hours < 0.5 or duration_hours > 4.0:
        raise err("ERR_VALIDATION",
                  "duration_hours must be in [0.5, 4.0]")

    try:
        sched_dt = parse_iso(scheduled_at)
    except ValueError:
        raise err("ERR_VALIDATION", "scheduled_at must be ISO 8601")

    if _has_supervision_overlap(supervisor_id, sched_dt):
        raise err("ERR_INVALID_STATE",
                  "Proposed supervision overlaps another supervision for this supervisor")

    s = {
        "counselor_id": counselor_id,
        "supervisor_id": supervisor_id,
        "case_appointment_id": case_appointment_id,
        "scheduled_at": scheduled_at,
        "duration_hours": float(duration_hours),
        "discussion_notes": discussion_notes,
        "evaluation_score": None,
        "status": "PENDING_REVIEW",
    }
    db.stamp_create(s, common_fields=True)
    db.supervision_sessions[s["id"]] = s
    return success(_public(s), 201)


@bp.route("/counseling/supervision-sessions/<id>/approve", methods=["POST"])
@require_auth(roles={"Supervisor"})
def approve_supervision(id):
    s = db.supervision_sessions.get(id)
    if s is None:
        raise err("ERR_NOT_FOUND", f"SupervisionSession {id} not found")
    if s["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE",
                  f"SupervisionSession status {s['status']} cannot be approved")
    if g.user_id != s["supervisor_id"]:
        raise err("ERR_FORBIDDEN",
                  "Only the named supervisor may approve this session")

    body = get_body()
    score = require_int(body, "evaluation_score")
    if score < 1 or score > 5:
        raise err("ERR_VALIDATION", "evaluation_score must be in [1, 5]")

    cur = now()
    s["status"] = "APPROVED"
    s["evaluation_score"] = score
    s["_approved_at"] = cur
    db.stamp_update(s)

    # Increment counselor.total_supervision_hours when within current open cycle window
    counselor = db.counselors[s["counselor_id"]]
    open_cycles = [c for c in db.certification_cycles.values()
                   if c["counselor_id"] == counselor["id"]
                   and c["status"] in ("OPEN", "UNDER_REVIEW")]
    in_window = False
    for cyc in open_cycles:
        ws = parse_iso(cyc["window_start_at"])
        we = parse_iso(cyc["window_end_at"])
        if ws <= cur <= we:
            in_window = True
            break
    if in_window:
        counselor["total_supervision_hours"] = float(counselor.get("total_supervision_hours", 0)) + float(s["duration_hours"])
        db.stamp_update(counselor)

    return success(_public(s))


@bp.route("/counseling/supervision-sessions/<id>/reject", methods=["POST"])
@require_auth(roles={"Supervisor"})
def reject_supervision(id):
    s = db.supervision_sessions.get(id)
    if s is None:
        raise err("ERR_NOT_FOUND", f"SupervisionSession {id} not found")
    if s["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE",
                  f"SupervisionSession status {s['status']} cannot be rejected")
    if g.user_id != s["supervisor_id"]:
        raise err("ERR_FORBIDDEN",
                  "Only the named supervisor may reject this session")
    s["status"] = "REJECTED"
    db.stamp_update(s)
    return success(_public(s))


@bp.route("/counseling/supervision-sessions", methods=["GET"])
@require_auth(roles={"Counselor", "Supervisor", "PlatformAdmin"})
def list_supervision():
    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    supervisor_id = request.args.get("supervisor_id")
    status = request.args.get("status")

    items = list(db.supervision_sessions.values())
    if g.user_role == "Counselor":
        items = [s for s in items if s["counselor_id"] == g.user_id]
    elif g.user_role == "Supervisor":
        items = [s for s in items if s["supervisor_id"] == g.user_id]
    if counselor_id:
        items = [s for s in items if s["counselor_id"] == counselor_id]
    if supervisor_id:
        items = [s for s in items if s["supervisor_id"] == supervisor_id]
    if status:
        items = [s for s in items if s["status"] == status]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(s) for s in page], limit, offset, total)


# ---- CE records ----

@bp.route("/counseling/ce-records", methods=["POST"])
@require_auth(roles={"Counselor"})
def create_ce():
    body = get_body()
    counselor_id = require_str(body, "counselor_id")
    course_title = require_str(body, "course_title")
    completed_at = require_str(body, "completed_at")
    hours_claimed = require_number(body, "hours_claimed")

    if g.user_id != counselor_id:
        raise err("ERR_FORBIDDEN", "Counselor may only log own CE")
    if db.counselors.get(counselor_id) is None:
        raise err("ERR_REF_NOT_FOUND", f"counselor_id {counselor_id} not found")

    try:
        parse_iso(completed_at)
    except ValueError:
        raise err("ERR_VALIDATION", "completed_at must be ISO 8601")

    if hours_claimed <= 0 or hours_claimed > 40:
        raise err("ERR_VALIDATION", "hours_claimed must be in (0, 40]")

    r = {
        "counselor_id": counselor_id,
        "course_title": course_title,
        "completed_at": completed_at,
        "hours_claimed": float(hours_claimed),
        "hours_credited": 0,
        "status": "PENDING_REVIEW",
    }
    db.stamp_create(r, common_fields=True)
    db.ce_records[r["id"]] = r
    return success(db.public(r), 201)


@bp.route("/counseling/ce-records/<id>/approve", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def approve_ce(id):
    r = db.ce_records.get(id)
    if r is None:
        raise err("ERR_NOT_FOUND", f"CE record {id} not found")
    if r["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE",
                  f"CE record status {r['status']} cannot be approved")
    cur = now()
    r["status"] = "APPROVED"
    r["hours_credited"] = float(r["hours_claimed"])
    r["_approved_at"] = cur
    db.stamp_update(r)

    counselor = db.counselors[r["counselor_id"]]
    open_cycles = [c for c in db.certification_cycles.values()
                   if c["counselor_id"] == counselor["id"]
                   and c["status"] in ("OPEN", "UNDER_REVIEW")]
    in_window = False
    for cyc in open_cycles:
        ws = parse_iso(cyc["window_start_at"])
        we = parse_iso(cyc["window_end_at"])
        if ws <= cur <= we:
            in_window = True
            break
    if in_window:
        counselor["total_ce_hours"] = float(counselor.get("total_ce_hours", 0)) + float(r["hours_credited"])
        db.stamp_update(counselor)

    return success(db.public(r))


@bp.route("/counseling/ce-records/<id>/reject", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def reject_ce(id):
    r = db.ce_records.get(id)
    if r is None:
        raise err("ERR_NOT_FOUND", f"CE record {id} not found")
    if r["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE",
                  f"CE record status {r['status']} cannot be rejected")
    body = get_body()
    optional_str(body, "reason")
    r["status"] = "REJECTED"
    r["hours_credited"] = 0
    db.stamp_update(r)
    return success(db.public(r))
