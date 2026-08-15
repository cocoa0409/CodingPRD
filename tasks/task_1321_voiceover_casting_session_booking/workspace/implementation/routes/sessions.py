"""Session booking endpoints: create/confirm/complete/cancel + listings."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import DB, clock_now, parse_iso
from middleware import auth, json_body
from response import ok, ok_list
from services import (
    SESSION_KINDS, base_record, lazy_read_tick, paginate, session_fee_final,
    session_json, sorted_rows, touch,
)

bp = Blueprint("sessions", __name__)

READ_ROLES = ["CastingDirector", "Client", "Talent", "StudioEngineer"]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _get_session(sid):
    s = DB["sessions"].get(sid)
    if s is None:
        raise errors.not_found("Session not found")
    return s


def _overlaps(studio_id, talent_id, start, end, exclude_id=None):
    """Half-open overlap against CONFIRMED sessions, per studio and per talent."""
    for s in DB["sessions"].values():
        if s["status"] != "CONFIRMED" or s["id"] == exclude_id:
            continue
        same_resource = s["studio_id"] == studio_id or (
            talent_id is not None and s["talent_id"] == talent_id
        )
        if same_resource and s["start_at"] < end and start < s["end_at"]:
            return True
    return False


@bp.post("/projects/<pid>/sessions")
def create_session(pid):
    auth(["CastingDirector"])
    p = DB["projects"].get(pid)
    if p is None:
        raise errors.not_found("Project not found")
    body = json_body()
    # priority 3: body FK existence
    sid = body.get("studio_id")
    studio = DB["studios"].get(sid) if isinstance(sid, str) else None
    if sid is not None and studio is None:
        raise errors.not_found("Studio not found")
    # priority 5: state — sessions are scheduled once the project has been cast
    # (CAST) and while production is underway (IN_SESSION, e.g. pickup work after
    # the primary session completes). Any other state is rejected.
    if p["status"] not in ("CAST", "IN_SESSION"):
        raise errors.invalid_state("Sessions can only be created once the project is CAST")
    # priority 8: overlap — the requested interval must not collide with any
    # CONFIRMED session sharing the same studio or the same talent (half-open
    # rule of PRD §2.9). Computable only when start_at/duration_minutes parse;
    # malformed shapes fall through to the priority-11 shape check below.
    _start_probe = parse_iso(body.get("start_at"))
    _dur_probe = body.get("duration_minutes")
    if _start_probe is not None and _is_int(_dur_probe) and _dur_probe >= 0:
        _end_probe = _start_probe + timedelta(minutes=_dur_probe)
        if _overlaps(sid, p["selected_talent_id"], _start_probe, _end_probe):
            raise errors.session_overlap()
    # priority 9: directed-patch capability (checked before shape, per priorities)
    if body.get("directed_patch") is True and studio is not None and not studio["has_directed_patch"]:
        raise errors.patch_not_supported()
    # priority 11: shape
    for field in ("studio_id", "session_kind", "directed_patch", "start_at", "duration_minutes"):
        if body.get(field) is None:
            raise errors.invalid_request(f"Missing required field: {field}")
    if body["session_kind"] not in SESSION_KINDS:
        raise errors.invalid_request("Invalid session_kind")
    if not isinstance(body["directed_patch"], bool):
        raise errors.invalid_request("directed_patch must be a boolean")
    start = parse_iso(body["start_at"])
    if start is None:
        raise errors.invalid_request("start_at must be a valid ISO 8601 timestamp")
    if not _is_int(body["duration_minutes"]) or body["duration_minutes"] < 15:
        raise errors.invalid_request("duration_minutes must be an integer >= 15")
    rec = base_record()
    rec.update({
        "project_id": pid,
        "talent_id": p["selected_talent_id"],  # denormalized at booking time
        "studio_id": sid,
        "session_kind": body["session_kind"],
        "directed_patch": body["directed_patch"],
        "start_at": start,
        "duration_minutes": body["duration_minutes"],
        "status": "TENTATIVE",
        "end_at": start + timedelta(minutes=body["duration_minutes"]),
        "_completed_at": None,
    })
    DB["sessions"][rec["id"]] = rec
    return ok(session_json(rec), 201)


@bp.get("/projects/<pid>/sessions")
def list_project_sessions(pid):
    auth(READ_ROLES)
    lazy_read_tick()
    if DB["projects"].get(pid) is None:
        raise errors.not_found("Project not found")
    rows = [s for s in sorted_rows("sessions") if s["project_id"] == pid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([session_json(s) for s in page], total, limit, offset)


@bp.get("/sessions")
def list_sessions():
    auth(READ_ROLES)
    lazy_read_tick()
    rows = sorted_rows("sessions")
    tid = request.args.get("talent_id")
    sid = request.args.get("studio_id")
    if tid is not None:
        rows = [s for s in rows if s["talent_id"] == tid]
    if sid is not None:
        rows = [s for s in rows if s["studio_id"] == sid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([session_json(s) for s in page], total, limit, offset)


@bp.get("/sessions/<sid>")
def get_session(sid):
    auth(READ_ROLES)
    lazy_read_tick()
    return ok(session_json(_get_session(sid)))


@bp.post("/sessions/<sid>/confirm")
def confirm_session(sid):
    auth(["CastingDirector"])
    s = _get_session(sid)
    # priority 5: state (session must be TENTATIVE; studio must be OPEN)
    if s["status"] != "TENTATIVE":
        raise errors.invalid_state("Only a TENTATIVE session can be confirmed")
    studio = DB["studios"].get(s["studio_id"])
    if studio is None or studio["status"] != "OPEN":
        raise errors.invalid_state("Studio is not OPEN")
    # priority 6: temporal — a session whose start has passed cannot be confirmed
    if clock_now() >= s["start_at"]:
        raise errors.temporal("Session start_at has already passed")
    # priority 8: overlap re-checked at confirm time (booking landscape may have
    # changed since creation)
    if _overlaps(s["studio_id"], s["talent_id"], s["start_at"], s["end_at"], exclude_id=s["id"]):
        raise errors.session_overlap()
    # priority 12: pickup/retake prerequisites
    if s["session_kind"] == "PICKUP":
        if not any(
            x["project_id"] == s["project_id"] and x["session_kind"] == "PRIMARY" and x["status"] == "COMPLETED"
            for x in DB["sessions"].values()
        ):
            raise errors.pickup_prereq("PICKUP requires an existing COMPLETED PRIMARY session")
    if s["session_kind"] == "RETAKE":
        from services import latest_delivery
        d = latest_delivery(s["project_id"])
        if d is None or not d["revision_requested"]:
            raise errors.pickup_prereq("RETAKE requires revision_requested=true on the project's delivery")
    s["status"] = "CONFIRMED"
    touch(s)
    # side effect: confirming while the project is CAST moves it to IN_SESSION
    p = DB["projects"].get(s["project_id"])
    if p is not None and p["status"] == "CAST":
        p["status"] = "IN_SESSION"
        touch(p)
    return ok(session_json(s))


@bp.post("/sessions/<sid>/complete")
def complete_session(sid):
    auth(["StudioEngineer"])
    s = _get_session(sid)
    if s["status"] not in ("TENTATIVE", "CONFIRMED"):
        raise errors.invalid_state("Session is already in a terminal state")
    if clock_now() < s["end_at"]:
        raise errors.temporal("Session cannot be completed before its end_at")
    s["status"] = "COMPLETED"
    s["_completed_at"] = clock_now()
    touch(s)
    # PICKUP sessions invoice immediately; PRIMARY/RETAKE defer to delivery.
    if s["session_kind"] == "PICKUP":
        fee = session_fee_final(s)
        inv = base_record()
        inv.update({
            "project_id": s["project_id"],
            "invoice_kind": "PICKUP_FEE",
            "talent_amount_cents": fee,
            "agent_commission_cents": 0,
            "total_cents": fee,
            "status": "PENDING",
            "issued_at": None,
            "_session_id": s["id"],
        })
        DB["invoices"][inv["id"]] = inv
    return ok(session_json(s))


@bp.post("/sessions/<sid>/cancel")
def cancel_session(sid):
    auth(["CastingDirector"])
    s = _get_session(sid)
    if s["status"] not in ("TENTATIVE", "CONFIRMED"):
        raise errors.invalid_state("Session is already in a terminal state")
    if clock_now() >= s["start_at"]:
        raise errors.temporal("Session can only be cancelled strictly before its start_at")
    s["status"] = "CANCELLED"
    touch(s)
    return ok(session_json(s))
