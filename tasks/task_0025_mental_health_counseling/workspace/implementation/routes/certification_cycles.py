"""Certification cycle endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import audit
from services.validation import get_body, optional_str


bp = Blueprint("certification_cycles", __name__)


def _public(c: dict) -> dict:
    return db.public(c)


def _supervision_hours_in_window(counselor_id, win_start, win_end):
    total = 0.0
    for s in db.supervision_sessions.values():
        if s["counselor_id"] != counselor_id:
            continue
        if s["status"] != "APPROVED":
            continue
        approved_at = s.get("_approved_at")
        if approved_at is None:
            continue
        if win_start <= approved_at <= win_end:
            total += float(s["duration_hours"])
    return total


def _ce_hours_in_window(counselor_id, win_start, win_end):
    total = 0.0
    for r in db.ce_records.values():
        if r["counselor_id"] != counselor_id:
            continue
        if r["status"] != "APPROVED":
            continue
        approved_at = r.get("_approved_at")
        if approved_at is None:
            continue
        if win_start <= approved_at <= win_end:
            total += float(r["hours_credited"])
    return total


@bp.route("/counseling/counselors/<id>/certification-cycles", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_cycle(id):
    counselor = db.counselors.get(id)
    if counselor is None:
        raise err("ERR_NOT_FOUND", f"Counselor {id} not found")

    # Determine next index
    existing = [c for c in db.certification_cycles.values() if c["counselor_id"] == id]
    if not existing:
        next_index = 1
        win_start = parse_iso(counselor["created_at"])
        win_end = win_start + timedelta(days=365)
        req_sup = 40
    else:
        # Must not have an OPEN/UNDER_REVIEW cycle
        for c in existing:
            if c["status"] in ("OPEN", "UNDER_REVIEW"):
                raise err("ERR_INVALID_STATE",
                          f"Counselor already has an active cycle in status {c['status']}")
        latest = max(existing, key=lambda x: x["cycle_index"])
        next_index = latest["cycle_index"] + 1
        win_start = parse_iso(latest["window_end_at"])
        win_end = win_start + timedelta(days=730)
        req_sup = 20

    cyc = {
        "counselor_id": id,
        "cycle_index": next_index,
        "required_supervision_hours": req_sup,
        "required_ce_hours": 12,
        "window_start_at": iso(win_start),
        "window_end_at": iso(win_end),
        "status": "OPEN",
        "decided_at": None,
        "decided_by_user_id": None,
    }
    db.stamp_create(cyc, common_fields=True)
    db.certification_cycles[cyc["id"]] = cyc
    return success(_public(cyc), 201)


@bp.route("/counseling/certification-cycles/<id>/submit", methods=["POST"])
@require_auth(roles={"Counselor"})
def submit_cycle(id):
    cyc = db.certification_cycles.get(id)
    if cyc is None:
        raise err("ERR_NOT_FOUND", f"CertificationCycle {id} not found")
    if g.user_id != cyc["counselor_id"]:
        raise err("ERR_FORBIDDEN", "Counselor may only submit own cycle")
    if cyc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE",
                  f"Cycle status {cyc['status']} not submittable")

    counselor = db.counselors[cyc["counselor_id"]]
    cur = now()
    win_start = parse_iso(cyc["window_start_at"])
    win_end = parse_iso(cyc["window_end_at"])

    if cur >= win_end:
        raise err("ERR_INVALID_STATE", "Cycle window has expired")
    if parse_iso(counselor["license_expires_at"]) <= cur:
        raise err("ERR_INVALID_STATE", "Counselor license has expired")

    sup_hours = _supervision_hours_in_window(counselor["id"], win_start, win_end)
    ce_hours = _ce_hours_in_window(counselor["id"], win_start, win_end)

    if sup_hours < cyc["required_supervision_hours"]:
        raise err("ERR_INVALID_STATE",
                  f"Supervision hours {sup_hours} < required {cyc['required_supervision_hours']}")
    if ce_hours < cyc["required_ce_hours"]:
        raise err("ERR_INVALID_STATE",
                  f"CE hours {ce_hours} < required {cyc['required_ce_hours']}")

    cyc["status"] = "UNDER_REVIEW"
    db.stamp_update(cyc)
    return success(_public(cyc))


def _check_recert_sod(cyc: dict, admin_user_id):
    """Admin must not have created any SupervisionSession contributing to this cycle."""
    counselor_id = cyc["counselor_id"]
    win_start = parse_iso(cyc["window_start_at"])
    win_end = parse_iso(cyc["window_end_at"])
    for s in db.supervision_sessions.values():
        if s["counselor_id"] != counselor_id:
            continue
        if s["status"] != "APPROVED":
            continue
        approved_at = s.get("_approved_at")
        if approved_at is None:
            continue
        if not (win_start <= approved_at <= win_end):
            continue
        # The "creator" of the SupervisionSession is the supervisee (counselor_id)
        # — but the SoD rule pins to the admin (decided_by_user_id) not having
        # created any of the contributing rows. In practice, admins don't create
        # supervision rows; counselors do. We check whether the admin's user_id
        # appears as the supervisor_id on any contributing row (the admin
        # acting also as supervisor would be a SoD breach).
        if s.get("supervisor_id") == admin_user_id:
            return False
        # Or the admin matches the supervisee (counselor_id) — also SoD breach.
        if s.get("counselor_id") == admin_user_id:
            return False
    return True


@bp.route("/counseling/certification-cycles/<id>/approve", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def approve_cycle(id):
    cyc = db.certification_cycles.get(id)
    if cyc is None:
        raise err("ERR_NOT_FOUND", f"CertificationCycle {id} not found")
    if cyc["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", f"Cycle status {cyc['status']} cannot be approved")

    if not _check_recert_sod(cyc, g.user_id):
        raise err("ERR_RECERT_SOD",
                  "Admin must not have created supervision rows contributing to this cycle")

    cyc["status"] = "APPROVED"
    cyc["decided_at"] = iso(now())
    cyc["decided_by_user_id"] = g.user_id
    db.stamp_update(cyc)

    counselor = db.counselors[cyc["counselor_id"]]
    if counselor["status"] == "PENDING_CERT" and cyc["cycle_index"] == 1:
        counselor["status"] = "ACTIVE"
        db.stamp_update(counselor)
    elif counselor["status"] == "SUSPENDED":
        counselor["status"] = "ACTIVE"
        db.stamp_update(counselor)

    # Auto-create next cycle
    next_start = parse_iso(cyc["window_end_at"])
    next_end = next_start + timedelta(days=730)
    next_cyc = {
        "counselor_id": counselor["id"],
        "cycle_index": cyc["cycle_index"] + 1,
        "required_supervision_hours": 20,
        "required_ce_hours": 12,
        "window_start_at": iso(next_start),
        "window_end_at": iso(next_end),
        "status": "OPEN",
        "decided_at": None,
        "decided_by_user_id": None,
    }
    db.stamp_create(next_cyc, common_fields=True)
    db.certification_cycles[next_cyc["id"]] = next_cyc

    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="RECERT_DECISION",
        target_entity="CertificationCycle", target_id=cyc["id"],
        payload_summary={"decision": "APPROVED"},
    )
    return success(_public(cyc))


@bp.route("/counseling/certification-cycles/<id>/reject", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def reject_cycle(id):
    cyc = db.certification_cycles.get(id)
    if cyc is None:
        raise err("ERR_NOT_FOUND", f"CertificationCycle {id} not found")
    if cyc["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", f"Cycle status {cyc['status']} cannot be rejected")
    if not _check_recert_sod(cyc, g.user_id):
        raise err("ERR_RECERT_SOD",
                  "Admin must not have created supervision rows contributing to this cycle")

    body = get_body()
    reason = optional_str(body, "reason")

    cyc["status"] = "REJECTED"
    cyc["decided_at"] = iso(now())
    cyc["decided_by_user_id"] = g.user_id
    db.stamp_update(cyc)

    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="RECERT_DECISION",
        target_entity="CertificationCycle", target_id=cyc["id"],
        payload_summary={"decision": "REJECTED", "reason": reason} if reason else {"decision": "REJECTED"},
    )
    return success(_public(cyc))


@bp.route("/counseling/certification-cycles", methods=["GET"])
@require_auth(roles={"Counselor", "PlatformAdmin"})
def list_cycles():
    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    status = request.args.get("status")

    items = list(db.certification_cycles.values())
    if g.user_role == "Counselor":
        items = [c for c in items if c["counselor_id"] == g.user_id]
    if counselor_id:
        items = [c for c in items if c["counselor_id"] == counselor_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(c) for c in page], limit, offset, total)
