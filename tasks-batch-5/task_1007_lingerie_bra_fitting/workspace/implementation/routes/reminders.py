"""ReplacementReminder endpoints (PRD §3.7)."""
from flask import Blueprint, g

import store
import api as h
import serialize as s
from errors import ApiError

bp = Blueprint("reminders", __name__)


@bp.get("/boutique/reminders/<rid>")
def get_reminder(rid):
    h.require_role("Customer", "StoreManager", "BillingClerk")
    rec = h.lookup("reminders", rid)
    if g.role == "Customer":
        h.owner_guard(rec["customer_id"])
    return h.success(s.reminder_out(rec))


@bp.get("/boutique/reminders")
def list_reminders():
    h.require_role("Customer", "StoreManager", "BillingClerk")
    customer_id = h.filter_arg("customer_id")
    order_line_id = h.filter_arg("order_line_id")
    status = h.filter_arg("status")

    def pred(r):
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if order_line_id is not None and r["order_line_id"] != order_line_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return h.list_response("reminders", s.reminder_out, pred)


@bp.post("/boutique/reminders/<rid>/send")
def send_reminder(rid):
    h.require_role("StoreManager")
    rem = h.lookup("reminders", rid)
    if rem["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if store.clock_now() < rem["due_date"]:
        raise ApiError("ERR_REMINDER_NOT_DUE")
    rem["status"] = "SENT"
    store.touch(rem)
    return h.success(s.reminder_out(rem))


@bp.post("/boutique/reminders/<rid>/dismiss")
def dismiss_reminder(rid):
    h.require_role("Customer", "StoreManager")
    rem = h.lookup("reminders", rid)
    h.owner_guard(rem["customer_id"])
    if rem["status"] not in ("SCHEDULED", "SENT"):
        raise ApiError("ERR_INVALID_STATE")
    rem["status"] = "DISMISSED"
    store.touch(rem)
    return h.success(s.reminder_out(rem))
