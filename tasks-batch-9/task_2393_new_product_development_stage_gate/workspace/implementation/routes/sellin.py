"""Customer sell-in and retailer reset windows (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("sellin", __name__)

BOOKABLE_DEV = ("PILOT_QUALIFIED", "LAUNCH_READY", "LAUNCHED", "IN_MARKET_FIX")
OUTCOMES = ("ACCEPTED", "DEFERRED", "REJECTED")


@bp.post("/innovation-projects/<project_id>/sell-in-presentations")
def create_presentation(project_id):
    M.authenticate("SalesAccountManager")
    project = common.project(project_id)
    data = V.body()
    retailer_id = V.id_field(data, "retailer_id")
    window_id = V.id_field(data, "shelf_reset_window_id")
    scheduled_raw, scheduled_dt = V.datetime_field(data, "scheduled_at")
    proposed = V.int_field(data, "proposed_sku_count", minimum=1)

    retailer = common.retailer(retailer_id)
    window = common.reset_window(window_id)

    if project["commercial_status"] == "SELL_IN_REJECTED":
        if project["dev_status"] in core.TERMINAL_DEV:
            E.fail(E.ERR_PROJECT_INVALID_STATE,
                   "dev_status %s does not admit a trade presentation."
                   % project["dev_status"])
    elif project["dev_status"] not in BOOKABLE_DEV:
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "dev_status %s does not admit a trade presentation."
               % project["dev_status"])

    if window["booked_slot_count"] >= window["max_presentations"]:
        E.fail(E.ERR_RESET_WINDOW_CAPACITY_FULL,
               "The reset window has no free slots.")

    if window["retailer_id"] != retailer["id"]:
        E.fail(E.ERR_WINDOW_RETAILER_MISMATCH,
               "The reset window belongs to another retailer.")
    if window["category"] != project["category"]:
        E.fail(E.ERR_WINDOW_CATEGORY_MISMATCH,
               "A %s project cannot take a %s reset slot."
               % (project["category"], window["category"]))
    case = core.authoritative_case(project["id"])
    channels = set()
    if case is not None:
        channels = {line["channel"] for line in core.case_lines(case["id"])}
    if retailer["channel"] not in channels:
        E.fail(E.ERR_CHANNEL_NOT_FORECAST,
               "Channel %s is not forecast on the authoritative business case."
               % retailer["channel"])

    lead = timedelta(days=retailer["presentation_lead_days"])
    if core.dt_of(window, "window_start") - scheduled_dt < lead:
        E.fail(E.ERR_PRESENTATION_LEAD_TIME_VIOLATION,
               "scheduled_at must precede window_start by at least %d days."
               % retailer["presentation_lead_days"])

    row = core.new_row(db.sell_in_presentations, {
        "project_id": project["id"],
        "retailer_id": retailer["id"],
        "shelf_reset_window_id": window["id"],
        "scheduled_at": scheduled_raw,
        "proposed_sku_count": proposed,
        "accepted_sku_count": None,
        "status": "PLANNED",
    })
    row["_dt_scheduled_at"] = scheduled_dt

    core.recompute_slots(window)
    if project["commercial_status"] in ("NOT_STARTED", "SELL_IN_REJECTED"):
        core.apply(project, {"commercial_status": "SELL_IN_SCHEDULED"})
    return R.object_response(row, 201)


@bp.get("/sell-in-presentations")
def list_presentations():
    M.reader()
    rows = M.apply_filters(db.rows(db.sell_in_presentations), {
        "project_id": "project_id",
        "retailer_id": "retailer_id",
        "shelf_reset_window_id": "shelf_reset_window_id",
        "status": "status",
    })
    rows = M.order(rows, [(lambda r: r["_dt_scheduled_at"], False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/sell-in-presentations/<presentation_id>")
def read_presentation(presentation_id):
    M.reader()
    return R.object_response(common.presentation(presentation_id))


@bp.post("/sell-in-presentations/<presentation_id>/present")
def present(presentation_id):
    M.authenticate("SalesAccountManager")
    row = common.presentation(presentation_id)

    if row["status"] != "PLANNED":
        E.fail(E.ERR_PRESENTATION_INVALID_STATE,
               "Only a PLANNED presentation may be presented; this one is %s."
               % row["status"])
    if clock.current_dt() < core.dt_of(row, "scheduled_at"):
        E.fail(E.ERR_PRESENTATION_NOT_DUE,
               "The scheduled instant has not been reached yet.")

    core.apply(row, {"status": "PRESENTED"})
    project = db.projects.get(row["project_id"])
    if project is not None and project["commercial_status"] == "SELL_IN_SCHEDULED":
        core.apply(project, {"commercial_status": "PRESENTED"})
    return R.object_response(row, 200)


@bp.post("/sell-in-presentations/<presentation_id>/record-outcome")
def record_outcome(presentation_id):
    M.authenticate("SalesAccountManager")
    row = common.presentation(presentation_id)
    data = V.body()
    outcome = V.enum_field(data, "outcome", OUTCOMES)
    accepted = V.int_field(data, "accepted_sku_count", required=False, minimum=0)

    if row["status"] != "PRESENTED":
        E.fail(E.ERR_PRESENTATION_INVALID_STATE,
               "Only a PRESENTED presentation takes an outcome; this one is %s."
               % row["status"])

    project = db.projects.get(row["project_id"])

    if outcome == "ACCEPTED":
        if accepted is None:
            E.fail(E.ERR_INVALID_REQUEST,
                   "Field 'accepted_sku_count' is required on the ACCEPTED "
                   "outcome.")
        if accepted > row["proposed_sku_count"]:
            E.fail(E.ERR_ACCEPTED_SKU_EXCEEDS_PROPOSED,
                   "accepted_sku_count %d exceeds the proposed %d."
                   % (accepted, row["proposed_sku_count"]))
        core.apply(row, {"status": "ACCEPTED", "accepted_sku_count": accepted})
        if project is not None:
            core.recompute_acv(project, {"commercial_status": "AUTHORIZED"})

    elif outcome == "DEFERRED":
        core.apply(row, {"status": "DEFERRED"})
        if project is not None:
            core.apply(project, {"commercial_status": "SELL_IN_SCHEDULED"})

    else:
        core.apply(row, {"status": "REJECTED"})
        window = db.shelf_reset_windows.get(row["shelf_reset_window_id"])
        if window is not None:
            core.recompute_slots(window)
        if project is not None:
            live = [p for p in core.project_presentations(project["id"])
                    if p["status"] in core.SLOT_HOLDING]
            if not live:
                core.apply(project, {"commercial_status": "SELL_IN_REJECTED"})

    return R.object_response(row, 200)


@bp.post("/sell-in-presentations/<presentation_id>/withdraw")
def withdraw(presentation_id):
    M.authenticate("SalesAccountManager")
    row = common.presentation(presentation_id)
    data = V.body()
    V.string_field(data, "reason", max_len=500)

    if row["status"] not in core.SLOT_HOLDING:
        E.fail(E.ERR_PRESENTATION_INVALID_STATE,
               "A %s presentation may not be withdrawn." % row["status"])
    project = db.projects.get(row["project_id"])
    if (row["status"] == "ACCEPTED" and project is not None
            and project["commercial_status"] == "SHIPPED"):
        E.fail(E.ERR_PRESENTATION_INVALID_STATE,
               "An accepted presentation may not be withdrawn once the project "
               "has shipped.")

    core.release_presentation(row, project, True)
    return R.object_response(row, 200)
