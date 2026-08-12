"""Loaner sets: booking with tiered intake deadline, receive, mark-ready."""
from datetime import timedelta

from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, logical_now, ok, ok_list, paginate,
    pagination, query_str, req_fk, req_int, req_string,
)

bp = Blueprint("loaners", __name__)


@bp.post("/spd/loaner-sets")
def create_loaner_set():
    auth(("OrScheduler",))
    body = get_body()
    vendor = req_string(body, "vendor")
    case = req_fk(body, "case_id", store.OR_CASES, "ORCase")
    tray_count = req_int(body, "tray_count", minimum=1)

    lead_hours = (domain.BULK_LEAD_HOURS if tray_count >= domain.BULK_THRESHOLD
                  else domain.STANDARD_LEAD_HOURS)
    due_by = case["scheduled_start_at"] - timedelta(hours=lead_hours)

    record = store.new_record()
    record.update({
        "vendor": vendor,
        "case_id": case["id"],
        "tray_count": tray_count,
        "due_by": due_by,
        "received_at": None,
        "received_late": False,
        "status": "BOOKED",
    })
    store.LOANER_SETS[record["id"]] = record
    return created(views.loaner_view(record))


@bp.get("/spd/loaner-sets")
def list_loaner_sets():
    auth(ANY)
    limit, offset = pagination()
    case_id = query_str("case_id")
    status = query_str("status")
    rows = [r for r in store.LOANER_SETS.values()
            if (case_id is None or r["case_id"] == case_id)
            and (status is None or r["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.loaner_view(r) for r in page], limit, offset, total)


@bp.get("/spd/loaner-sets/<loaner_id>")
def get_loaner_set(loaner_id):
    auth(ANY)
    record = store.fetch(store.LOANER_SETS, loaner_id)
    return ok(views.loaner_view(record))


@bp.post("/spd/loaner-sets/<loaner_id>/receive")
def receive_loaner_set(loaner_id):
    auth(("SpdTechnician",))
    record = store.fetch(store.LOANER_SETS, loaner_id)
    if record["status"] != "BOOKED":
        raise ApiError("ERR_LOANER_NOT_BOOKED", 409,
                       "receive requires loaner BOOKED.")
    now = logical_now()
    record["received_at"] = now
    # strictly greater is late; arrival exactly at due_by is on time
    if now > record["due_by"]:
        record["status"] = "LATE_RECEIVED"
        record["received_late"] = True
    else:
        record["status"] = "RECEIVED"
        record["received_late"] = False
    store.touch(record)
    return ok(views.loaner_view(record))


@bp.post("/spd/loaner-sets/<loaner_id>/mark-ready")
def mark_loaner_ready(loaner_id):
    auth(("SpdTechnician",))
    record = store.fetch(store.LOANER_SETS, loaner_id)
    if record["status"] not in ("RECEIVED", "LATE_RECEIVED"):
        raise ApiError("ERR_LOANER_NOT_RECEIVED", 409,
                       "mark-ready requires loaner RECEIVED or LATE_RECEIVED.")
    record["status"] = "READY"
    store.touch(record)
    return ok(views.loaner_view(record))
