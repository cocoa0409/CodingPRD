"""Reminders (read-only surface; transitions are system-driven)."""
from flask import Blueprint, request

import middleware as mw
from db import store, pub, pub_list
from response import ok_object, ok_list

bp = Blueprint("reminders", __name__)


@bp.get("/tc/reminders/<reminderId>")
def get_reminder(reminderId):
    mw.auth()
    rec = mw.get_or_404("reminder", reminderId)
    return ok_object(pub("reminder", rec))


@bp.get("/tc/reminders")
def list_reminders():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.reminders.values())
    recs = mw.filter_eq(recs, "deadline_id", request.args.get("deadline_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("reminder", page), limit, offset, total)
