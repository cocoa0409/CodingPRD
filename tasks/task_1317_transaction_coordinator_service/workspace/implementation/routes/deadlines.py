"""Deadlines."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, touch, pub, pub_list, fmt_dt
from response import ok_object, ok_list
from services import calc

bp = Blueprint("deadlines", __name__)


@bp.get("/tc/deadlines/<deadlineId>")
def get_deadline(deadlineId):
    mw.auth()
    rec = mw.get_or_404("deadline", deadlineId)
    return ok_object(pub("deadline", rec))


@bp.get("/tc/deadlines")
def list_deadlines():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.deadlines.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    recs = mw.filter_eq(recs, "kind", request.args.get("kind"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("deadline", page), limit, offset, total)


@bp.post("/tc/deadlines/<deadlineId>/mark-met")
def mark_met(deadlineId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("deadline", deadlineId)
    file_rec = mw.own_file_chain(uid, rec, "deadline")
    if rec["status"] != "PENDING":
        E.raise_err(E.ERR_DEADLINE_INVALID_STATE, "Only a PENDING deadline can be marked met")
    if file_rec is None or file_rec["status"] not in ("ACTIVE", "PENDING_CLOSE"):
        E.raise_err(E.ERR_FILE_NOT_ACTIVE, "Owning file must be ACTIVE or PENDING_CLOSE")
    rec["status"] = "MET"
    rec["met_at"] = fmt_dt(store.now)
    touch(rec)
    calc.cancel_queued_reminders(rec["id"])
    return ok_object(pub("deadline", rec))


@bp.post("/tc/deadlines/<deadlineId>/waive")
def waive_deadline(deadlineId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("deadline", deadlineId)
    mw.own_file_chain(uid, rec, "deadline")
    if rec["status"] != "PENDING":
        E.raise_err(E.ERR_DEADLINE_INVALID_STATE, "Only a PENDING deadline can be waived")
    rec["status"] = "WAIVED"
    touch(rec)
    calc.cancel_queued_reminders(rec["id"])
    return ok_object(pub("deadline", rec))
