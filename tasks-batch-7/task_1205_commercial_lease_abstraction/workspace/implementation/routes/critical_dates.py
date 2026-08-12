"""CriticalDate endpoints."""

from datetime import timedelta

from flask import Blueprint

from db import db, new_resource, touch, clock
from errors import err
from response import success_object
from services import calc
from services.validate import (
    body, req_int, req_enum, req_date, opt_string, filter_arg_str,
)
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("critical_dates", __name__)

CD_KINDS = {
    "OPTION_EXERCISE", "NOTICE_DEADLINE", "EXPIRATION",
    "RENEWAL_WINDOW_OPEN", "RENEWAL_WINDOW_CLOSE", "AUDIT_WINDOW_CLOSE",
}
EXERCISABLE_KINDS = {
    "OPTION_EXERCISE", "RENEWAL_WINDOW_OPEN", "RENEWAL_WINDOW_CLOSE",
}


@bp.post("/lease-admin/leases/<lease_id>/critical-dates")
def create_critical_date(lease_id):
    get_lease_or_404(lease_id)
    data = body()
    kind = req_enum(data, "kind", CD_KINDS)
    due_date = req_date(data, "due_date")
    advance_notice_days = req_int(data, "advance_notice_days", min_v=0)
    linked_amendment_id = opt_string(data, "linked_amendment_id")
    # Temporal well-formedness (pipeline step 5): due_date must not be past.
    if calc.d(due_date) < clock.current().date():
        err("ERR_INVALID_DATE_RANGE",
            "due_date must not be in the past")
    cid, common = new_resource()
    cd = {
        **common,
        "lease_id": lease_id,
        "kind": kind,
        "due_date": due_date,
        "advance_notice_days": advance_notice_days,
        "status": "PENDING",
        "linked_amendment_id": linked_amendment_id,
    }
    db["critical_dates"][cid] = cd
    return success_object(cd, status=201)


@bp.get("/lease-admin/leases/<lease_id>/critical-dates")
def list_lease_critical_dates(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [c for c in db["critical_dates"].values()
         if c["lease_id"] == lease_id],
        filters=[
            (filter_arg_str("kind"), lambda r, v: r["kind"] == v),
            (filter_arg_str("status"), lambda r, v: r["status"] == v),
        ])


@bp.get("/lease-admin/critical-dates/<cd_id>")
def get_critical_date(cd_id):
    return success_object(
        get_child_or_404("critical_dates", cd_id, "CriticalDate"))


@bp.get("/lease-admin/critical-dates")
def list_critical_dates_filtered():
    return list_response(db["critical_dates"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("linked_amendment_id"),
         lambda r, v: r["linked_amendment_id"] == v),
        (filter_arg_str("kind"), lambda r, v: r["kind"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/critical-dates/<cd_id>/notify")
def notify_critical_date(cd_id):
    cd = get_child_or_404("critical_dates", cd_id, "CriticalDate")
    if cd["status"] != "PENDING":
        err("ERR_INVALID_STATE", "Notify requires status == PENDING")
    today = clock.current().date()
    due = calc.d(cd["due_date"])
    # Window checks (pipeline step 13).
    if today < due - timedelta(days=cd["advance_notice_days"]):
        err("ERR_NOTIFICATION_NOT_YET_DUE",
            "Notification is not yet due")
    if today >= due:
        err("ERR_NOTIFICATION_WINDOW_MISSED",
            "Notification window has been missed")
    cd["status"] = "NOTIFIED"
    touch(cd)
    return success_object(cd)


@bp.post("/lease-admin/critical-dates/<cd_id>/exercise")
def exercise_critical_date(cd_id):
    from services.validate import req_string
    cd = get_child_or_404("critical_dates", cd_id, "CriticalDate")
    data = body()
    linked_amendment_id = req_string(data, "linked_amendment_id")
    if cd["status"] not in ("PENDING", "NOTIFIED"):
        err("ERR_INVALID_STATE",
            "Exercise requires status PENDING or NOTIFIED")
    if cd["kind"] not in EXERCISABLE_KINDS:
        err("ERR_NOT_EXERCISABLE",
            "This kind of critical date is not exercisable")
    amendment = db["amendments"].get(linked_amendment_id)
    if amendment is None or amendment["status"] != "APPLIED":
        err("ERR_AMENDMENT_NOT_APPLIED",
            "linked_amendment_id must reference an APPLIED Amendment")
    today = clock.current().date()
    if today > calc.d(cd["due_date"]):
        err("ERR_DATE_PASSED", "The due date has passed")
    cd["linked_amendment_id"] = linked_amendment_id
    cd["status"] = "EXERCISED"
    touch(cd)
    return success_object(cd)


@bp.post("/lease-admin/critical-dates/<cd_id>/lapse")
def lapse_critical_date(cd_id):
    cd = get_child_or_404("critical_dates", cd_id, "CriticalDate")
    if cd["status"] not in ("PENDING", "NOTIFIED"):
        err("ERR_INVALID_STATE",
            "Lapse requires status PENDING or NOTIFIED")
    today = clock.current().date()
    if today <= calc.d(cd["due_date"]):
        err("ERR_DATE_PASSED", "The due date has not yet passed")
    cd["status"] = "LAPSED"
    touch(cd)
    return success_object(cd)


@bp.post("/lease-admin/critical-dates/<cd_id>/waive")
def waive_critical_date(cd_id):
    cd = get_child_or_404("critical_dates", cd_id, "CriticalDate")
    if cd["status"] not in ("PENDING", "NOTIFIED"):
        err("ERR_INVALID_STATE",
            "Waive requires status PENDING or NOTIFIED")
    cd["status"] = "WAIVED"
    touch(cd)
    return success_object(cd)
