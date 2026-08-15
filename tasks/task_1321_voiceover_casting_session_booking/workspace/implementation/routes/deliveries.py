"""Delivery endpoints: file delivery advances IN_SESSION -> DELIVERED and invoices."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import DB, clock_now, new_id, next_seq, now_wall
from middleware import auth, json_body
from response import ok, ok_list
from services import (
    REVISION_WINDOW_HOURS, base_record, delivery_json, lazy_read_tick,
    paginate, session_fee_final, sorted_rows, touch,
)

bp = Blueprint("deliveries", __name__)

READ_ROLES = ["CastingDirector", "Client", "StudioEngineer"]


def _create_invoice(project_id, kind, talent_amount, commission, session_id=None):
    inv = base_record()
    inv.update({
        "project_id": project_id,
        "invoice_kind": kind,
        "talent_amount_cents": talent_amount,
        "agent_commission_cents": commission,
        "total_cents": talent_amount + commission,
        "status": "PENDING",
        "issued_at": None,
        "_session_id": session_id,
    })
    DB["invoices"][inv["id"]] = inv
    return inv


@bp.post("/projects/<pid>/deliveries")
def create_delivery(pid):
    auth(["StudioEngineer"])
    p = DB["projects"].get(pid)
    if p is None:
        raise errors.not_found("Project not found")
    body = json_body()
    # priority 3: body FK existence, scoped to the project
    sid = body.get("session_id")
    sess = DB["sessions"].get(sid) if isinstance(sid, str) else None
    if sess is None or sess["project_id"] != pid:
        raise errors.not_found("Session not found on this project")
    # priority 5: state
    if p["status"] != "IN_SESSION":
        raise errors.invalid_state("Project is not IN_SESSION")
    project_sessions = [s for s in DB["sessions"].values() if s["project_id"] == pid]
    if not any(s["status"] == "COMPLETED" for s in project_sessions):
        raise errors.invalid_state("At least one COMPLETED session is required to deliver")
    if any(s["session_kind"] == "PICKUP" and s["status"] in ("CONFIRMED", "TENTATIVE")
           for s in project_sessions):
        raise errors.invalid_state("Outstanding PICKUP work blocks delivery")
    # priority 11: shape
    if not isinstance(body.get("file_url"), str) or not body.get("file_url"):
        raise errors.invalid_request("Missing required field: file_url")
    now = clock_now()
    rec = {
        "id": new_id(),
        "created_at": now_wall(),
        "_seq": next_seq(),
        "project_id": pid,
        "session_id": sid,
        "file_url": body["file_url"],
        "delivered_at": now,
        "revision_window_hours": REVISION_WINDOW_HOURS,
        "revision_window_closes_at": now + timedelta(hours=REVISION_WINDOW_HOURS),
        "revision_requested": False,
    }
    DB["deliveries"][rec["id"]] = rec
    p["status"] = "DELIVERED"
    touch(p)
    # Invoicing moment: BUYOUT from usage terms; SESSION_FEE for every COMPLETED
    # PRIMARY/RETAKE session not yet invoiced.
    uts = [u for u in DB["usage_terms"].values() if u["project_id"] == pid]
    if uts:
        ut = uts[0]
        _create_invoice(pid, "BUYOUT", ut["talent_payout_cents"], ut["agent_commission_cents"])
    invoiced_sessions = {
        i.get("_session_id") for i in DB["invoices"].values()
        if i["project_id"] == pid and i["invoice_kind"] == "SESSION_FEE"
    }
    for s in sorted_rows("sessions"):
        if (s["project_id"] == pid and s["status"] == "COMPLETED"
                and s["session_kind"] in ("PRIMARY", "RETAKE")
                and s["id"] not in invoiced_sessions):
            fee = session_fee_final(s)
            _create_invoice(pid, "SESSION_FEE", fee, 0, session_id=s["id"])
    return ok(delivery_json(rec), 201)


@bp.get("/projects/<pid>/deliveries")
def list_project_deliveries(pid):
    auth(READ_ROLES)
    lazy_read_tick()
    if DB["projects"].get(pid) is None:
        raise errors.not_found("Project not found")
    rows = [d for d in sorted_rows("deliveries") if d["project_id"] == pid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([delivery_json(d) for d in page], total, limit, offset)


@bp.get("/deliveries")
def list_deliveries():
    auth(READ_ROLES)
    lazy_read_tick()
    rows = sorted_rows("deliveries")
    sid = request.args.get("session_id")
    if sid is not None:
        rows = [d for d in rows if d["session_id"] == sid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([delivery_json(d) for d in page], total, limit, offset)


@bp.get("/deliveries/<did>")
def get_delivery(did):
    auth(READ_ROLES)
    lazy_read_tick()
    rec = DB["deliveries"].get(did)
    if rec is None:
        raise errors.not_found("Delivery not found")
    return ok(delivery_json(rec))
