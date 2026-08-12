"""Immediate-use steam sterilization (IUSS) exceptions."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, logical_now, ok, ok_list,
    opt_string, paginate, pagination, query_str, req_fk, req_justification,
)

bp = Blueprint("iuss", __name__)


@bp.post("/spd/iuss-exceptions")
def create_iuss_exception():
    actor = auth(("SpdTechnician", "SpdSupervisor"))
    body = get_body()
    tray = req_fk(body, "tray_id", store.TRAYS, "Tray")
    case = req_fk(body, "case_id", store.OR_CASES, "ORCase")
    justification = req_justification(body, "justification")

    # p6 state gates
    if tray["status"] not in ("DECONTAMINATED", "ASSEMBLED"):
        raise ApiError("ERR_IUSS_TRAY_NOT_ELIGIBLE", 409,
                       "IUSS tray must be DECONTAMINATED or ASSEMBLED.")
    if case["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_CASE_TERMINAL_FOR_IUSS", 409,
                       "IUSS case_id references a terminal case.")

    # p9 rolling-window rate gate: the 4th event in the window is
    # supervisor-only
    prospective = domain.iuss_count_7d() + 1
    if prospective >= domain.SUPERVISOR_THRESHOLD and \
            actor.role != "SpdSupervisor":
        raise ApiError("ERR_IUSS_RATE_EXCEEDED", 403,
                       "The rolling 168h IUSS window already holds >= 3 "
                       "events; the 4th and later require SpdSupervisor.")

    tray["status"] = "IN_USE"
    store.touch(tray)

    record = store.new_record()
    record.update({
        "tray_id": tray["id"],
        "case_id": case["id"],
        "justification": justification,
        "logged_by_id": actor.user_id,
        "logged_at": logical_now(),
        "status": "DOCUMENTED",
        "review_note": None,
    })
    store.IUSS_EXCEPTIONS[record["id"]] = record
    return created(views.iuss_view(record))


@bp.get("/spd/iuss-exceptions")
def list_iuss_exceptions():
    auth(ANY)
    limit, offset = pagination()
    tray_id = query_str("tray_id")
    case_id = query_str("case_id")
    logged_by_id = query_str("logged_by_id")
    rows = [r for r in store.IUSS_EXCEPTIONS.values()
            if (tray_id is None or r["tray_id"] == tray_id)
            and (case_id is None or r["case_id"] == case_id)
            and (logged_by_id is None or r["logged_by_id"] == logged_by_id)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.iuss_view(r) for r in page], limit, offset, total)


@bp.get("/spd/iuss-exceptions/<iuss_id>")
def get_iuss_exception(iuss_id):
    auth(ANY)
    record = store.fetch(store.IUSS_EXCEPTIONS, iuss_id)
    return ok(views.iuss_view(record))


@bp.post("/spd/iuss-exceptions/<iuss_id>/review")
def review_iuss_exception(iuss_id):
    auth(("QualityAuditor",))
    record = store.fetch(store.IUSS_EXCEPTIONS, iuss_id)
    body = get_body()
    review_note = opt_string(body, "review_note", min_len=0)
    if record["status"] != "DOCUMENTED":
        raise ApiError("ERR_IUSS_ALREADY_REVIEWED", 409,
                       "review requires IUSS exception DOCUMENTED.")
    record["status"] = "REVIEWED"
    if review_note is not None:
        record["review_note"] = review_note
    store.touch(record)
    return ok(views.iuss_view(record))
