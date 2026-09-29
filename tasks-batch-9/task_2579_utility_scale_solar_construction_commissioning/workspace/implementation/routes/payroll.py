"""Certified payroll weeks, labor entries and week certification."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from errors import fail, invalid
from routes.common import filter_eq, paginate
from validate import ALL_ROLES, authorize, b, body, dy, e, i, n, s

bp = Blueprint("payroll", __name__)

CLASSIFICATIONS = ("ELECTRICIAN", "LABORER", "OPERATOR", "IRONWORKER")


@bp.post("/solar/projects/<project_id>/payroll-weeks")
def create_week(project_id):
    authorize("LaborComplianceOfficer")
    data = body(dy("week_start_date"))
    store.require_project(project_id)
    for week in store.payroll_weeks.values():
        if week["project_id"] == project_id and week["week_start_date"] == data["week_start_date"]:
            invalid("week_start_date already opened for this project")
    row = store.base()
    row.update(
        {
            "project_id": project_id,
            "week_start_date": data["week_start_date"],
            "status": "OPEN",
            "entry_count": 0,
            "total_hours": 0,
            "apprentice_hours": 0,
            "journeyworker_hours": 0,
            "apprentice_pct": 0,
            "certified_by_user_id": None,
            "certified_at": None,
        }
    )
    store.payroll_weeks[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/payroll-weeks/<week_id>")
def get_week(week_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_payroll_week(week_id))


@bp.get("/solar/projects/<project_id>/payroll-weeks")
def list_weeks(project_id):
    authorize(*ALL_ROLES)
    store.require_project(project_id)
    rows = store.children(store.payroll_weeks, "project_id", project_id)
    rows = sorted(rows, key=lambda r: (r["week_start_date"], r["created_at"], r["_seq"]))
    rows = filter_eq(rows, "status", validate.q("status"))
    return paginate(rows)


@bp.post("/solar/payroll-weeks/<week_id>/labor-entries")
def post_labor_entry(week_id):
    user_id = authorize("LaborComplianceOfficer")
    data = body(
        s("worker_ref"),
        e("classification", CLASSIFICATIONS),
        b("is_apprentice"),
        n("hours", gt=0),
        i("paid_rate_cents", ge=0),
        i("fringe_rate_cents", ge=0),
        i("prevailing_rate_cents", ge=0),
        dy("work_date"),
    )
    week = store.require_payroll_week(week_id)
    start = week["week_start_date"]
    if not (start <= data["work_date"] <= start + timedelta(days=6)):
        invalid("work_date must fall inside the payroll week")
    if week["status"] != "OPEN":
        fail("ERR_PAYROLL_WEEK_LOCKED")
    project = store.require_project(week["project_id"])

    shortfall = calc.entry_shortfall(
        data["paid_rate_cents"], data["fringe_rate_cents"], data["prevailing_rate_cents"]
    )
    if project["prevailing_wage_election"] == "STRICT" and shortfall > 0:
        fail("ERR_BELOW_PREVAILING_WAGE")

    row = store.base()
    row.update(
        {
            "payroll_week_id": week["id"],
            "worker_ref": data["worker_ref"],
            "classification": data["classification"],
            "is_apprentice": data["is_apprentice"],
            "hours": data["hours"],
            "paid_rate_cents": data["paid_rate_cents"],
            "fringe_rate_cents": data["fringe_rate_cents"],
            "prevailing_rate_cents": data["prevailing_rate_cents"],
            "work_date": data["work_date"],
            "status": "POSTED",
            "shortfall_cents_per_hour": shortfall,
            "restitution_cents": calc.entry_restitution(shortfall, data["hours"]),
            "posted_by_user_id": user_id,
            "void_reason": None,
        }
    )
    store.labor_entries[row["id"]] = row

    calc.recompute_week_ledger(week)
    store.touch(week)
    calc.recompute_project_hours(project)
    store.touch(project)
    return envelope.created(row)


@bp.get("/solar/payroll-weeks/<week_id>/labor-entries")
def list_labor_entries(week_id):
    authorize(*ALL_ROLES)
    store.require_payroll_week(week_id)
    rows = store.children(store.labor_entries, "payroll_week_id", week_id)
    rows = sorted(rows, key=lambda r: (r["work_date"], r["created_at"], r["_seq"]))
    rows = filter_eq(rows, "status", validate.q("status"))
    rows = filter_eq(rows, "is_apprentice", validate.qbool("is_apprentice"))
    return paginate(rows)


@bp.get("/solar/labor-entries/<entry_id>")
def get_labor_entry(entry_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_labor_entry(entry_id))


@bp.post("/solar/labor-entries/<entry_id>/void")
def void_labor_entry(entry_id):
    authorize("LaborComplianceOfficer")
    data = body(s("void_reason"))
    entry = store.require_labor_entry(entry_id)
    if entry["status"] != "POSTED":
        fail("ERR_LABOR_ENTRY_ALREADY_VOIDED")
    week = store.require_payroll_week(entry["payroll_week_id"])
    if week["status"] != "OPEN":
        fail("ERR_PAYROLL_WEEK_LOCKED")

    entry["status"] = "VOIDED"
    entry["void_reason"] = data["void_reason"]
    entry["restitution_cents"] = 0
    store.touch(entry)

    calc.recompute_week_ledger(week)
    store.touch(week)
    project = store.projects.get(week["project_id"])
    if project is not None:
        calc.recompute_project_hours(project)
        store.touch(project)
    return envelope.ok(entry)


@bp.post("/solar/payroll-weeks/<week_id>/certification")
def certify_week(week_id):
    user_id = authorize("LaborComplianceOfficer")
    body(s("note", required=False))
    week = store.require_payroll_week(week_id)
    if week["status"] != "OPEN":
        fail("ERR_PAYROLL_WEEK_LOCKED")
    if week["entry_count"] < 1:
        invalid("A payroll week needs at least one posted entry before certification")
    for entry in store.labor_entries.values():
        if (
            entry["payroll_week_id"] == week_id
            and entry["status"] == "POSTED"
            and entry["posted_by_user_id"] == user_id
        ):
            fail("ERR_SEGREGATION_OF_DUTIES")
    week["status"] = "CERTIFIED"
    week["certified_by_user_id"] = user_id
    week["certified_at"] = clock.now()
    store.touch(week)
    return envelope.ok(week)
