"""The launch date lock, launch execution and post-launch tracking (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("launch", __name__)

LOCKABLE_COMMERCIAL = ("AUTHORIZED", "LOCK_SLIPPED")
TRACKED_DEV = ("LAUNCHED", "IN_MARKET_FIX")


@bp.post("/innovation-projects/<project_id>/launch-lock")
def launch_lock(project_id):
    M.authenticate("GateChair")
    project = common.project(project_id)
    data = V.body()
    launch_raw, launch_dt = V.datetime_field(data, "launch_date")
    window_id = V.id_field(data, "shelf_reset_window_id")
    window = common.reset_window(window_id)

    if (project["dev_status"] != "LAUNCH_READY"
            or project["commercial_status"] not in LOCKABLE_COMMERCIAL):
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "A launch lock requires dev_status LAUNCH_READY with "
               "commercial_status AUTHORIZED or LOCK_SLIPPED; this project is "
               "%s / %s." % (project["dev_status"], project["commercial_status"]))

    if window["category"] != project["category"]:
        E.fail(E.ERR_WINDOW_CATEGORY_MISMATCH,
               "A %s project cannot launch into a %s reset window."
               % (project["category"], window["category"]))

    formulation = core.current_formulation(project["id"])
    cleared = False
    if formulation is not None:
        for label in db.children(db.label_approvals, "formulation_id",
                                 formulation["id"]):
            if label["status"] in ("APPROVED", "CONDITIONAL"):
                cleared = True
                break
    if not cleared:
        E.fail(E.ERR_LABEL_NOT_APPROVED,
               "The current formulation carries no APPROVED or CONDITIONAL "
               "label approval.")

    if (launch_dt < core.dt_of(window, "window_start")
            or launch_dt > core.dt_of(window, "window_end")):
        E.fail(E.ERR_LAUNCH_DATE_OUTSIDE_WINDOW,
               "launch_date falls outside the reset window.")
    if launch_dt - clock.current_dt() < timedelta(days=calc.LOCK_LEAD_DAYS):
        E.fail(E.ERR_LOCK_LEAD_TIME_VIOLATION,
               "launch_date must be at least %d whole days out."
               % calc.LOCK_LEAD_DAYS)

    if project["launch_readiness_pct"] != core.HUNDRED:
        E.fail(E.ERR_LAUNCH_READINESS_INCOMPLETE,
               "launch_readiness_pct stands at %s%%."
               % project["launch_readiness_pct"])

    core.apply(project, {
        "commercial_status": "LAUNCH_LOCKED",
        "launch_date": launch_raw,
        "shelf_reset_window_id": window["id"],
    })
    project["_dt_launch_date"] = launch_dt
    return R.object_response(project, 200)


@bp.post("/innovation-projects/<project_id>/launch")
def launch_project(project_id):
    M.authenticate("GateChair")
    project = common.project(project_id)

    if (project["dev_status"] != "LAUNCH_READY"
            or project["commercial_status"] != "LAUNCH_LOCKED"):
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "A launch requires dev_status LAUNCH_READY with "
               "commercial_status LAUNCH_LOCKED; this project is %s / %s."
               % (project["dev_status"], project["commercial_status"]))

    launch_dt = core.dt_of(project, "launch_date")
    if launch_dt is None or clock.current_dt() < launch_dt:
        E.fail(E.ERR_LAUNCH_DATE_NOT_REACHED,
               "The locked launch date has not been reached yet.")
    if project["launch_readiness_pct"] != core.HUNDRED:
        E.fail(E.ERR_LAUNCH_READINESS_INCOMPLETE,
               "launch_readiness_pct stands at %s%%."
               % project["launch_readiness_pct"])

    core.apply(project, {
        "dev_status": "LAUNCHED",
        "commercial_status": "SHIPPED",
    })
    return R.object_response(project, 200)


@bp.post("/innovation-projects/<project_id>/post-launch-periods")
def create_period(project_id):
    M.authenticate("PortfolioAdmin")
    project = common.project(project_id)
    data = V.body()
    period_index = V.int_field(data, "period_index", minimum=1)
    actual_units = V.int_field(data, "actual_units", minimum=0)
    net_revenue = V.number_field(data, "actual_net_revenue_usd", minimum=0)
    gross_margin = V.number_field(data, "actual_gross_margin_usd")
    basis = V.enum_field(data, "attainment_basis", V.ATTAINMENT_BASES)

    if project["dev_status"] not in TRACKED_DEV:
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "Post-launch reporting requires dev_status LAUNCHED or "
               "IN_MARKET_FIX; this project is %s." % project["dev_status"])

    case = core.authoritative_case(project["id"])
    if case is None or case["status"] != "LOCKED":
        E.fail(E.ERR_NO_LOCKED_BUSINESS_CASE,
               "The project has no LOCKED authoritative business case.")

    existing = core.project_periods(project["id"])
    if period_index != len(existing) + 1:
        E.fail(E.ERR_PERIOD_SEQUENCE_VIOLATION,
               "period_index must be exactly %d." % (len(existing) + 1))

    plan_units = calc.plan_units_per_period(case["annual_units"])
    cumulative_actual = actual_units
    for row in existing:
        if row["period_index"] < period_index:
            cumulative_actual += row["actual_units"]

    cumulative_pct, trailing_pct = calc.post_launch_attainment(
        plan_units, cumulative_actual, actual_units, period_index)
    attainment = cumulative_pct if basis == "CUMULATIVE" else trailing_pct
    decision = calc.post_launch_decision(attainment)

    row = core.new_row(db.post_launch_periods, {
        "project_id": project["id"],
        "period_index": period_index,
        "actual_units": actual_units,
        "actual_net_revenue_usd": net_revenue,
        "actual_gross_margin_usd": gross_margin,
        "attainment_basis": basis,
        "plan_units_per_period": plan_units,
        "attainment_cumulative_pct": cumulative_pct,
        "attainment_trailing_pct": trailing_pct,
        "attainment_pct": attainment,
        "decision": decision,
    })

    changes = {"post_launch_decision": decision}
    if decision == "FIX":
        changes["dev_status"] = "IN_MARKET_FIX"
    elif decision == "CONTINUE":
        changes["dev_status"] = "LAUNCHED"
    else:
        changes["dev_status"] = "DISCONTINUED"
    core.apply(project, changes)
    if decision == "DISCONTINUE":
        core.winddown_cascade(project)

    return R.object_response(row, 201)


@bp.get("/innovation-projects/<project_id>/post-launch-periods")
def list_periods(project_id):
    M.reader()
    project = common.project(project_id)
    rows = M.order(core.project_periods(project["id"]),
                   [(M.by("period_index"), False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)
