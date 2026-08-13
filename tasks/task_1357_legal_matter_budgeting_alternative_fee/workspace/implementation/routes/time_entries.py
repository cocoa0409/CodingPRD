"""TimeEntry endpoints (PRD §3.4)."""
from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_NOT_OPEN,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_PERIOD_CLOSED,
    ERR_TASK_CODE_NOT_BUDGETED,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("time_entries", __name__)

LITIGATION_STAGES = {"INTAKE", "PLEADINGS", "DISCOVERY", "PRETRIAL", "TRIAL", "APPEAL"}
READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner",
              "ManagingPartner", "Timekeeper")


@bp.post("/firms/<firmId>/matters/<matterId>/time_entries")
def create_time_entry(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "Timekeeper", "BillingPartner")
    firm = util.get_firm(firmId)
    matter = util.get_matter_scoped(firmId, matterId)
    data = util.body()
    util.require_fields(data, [
        "timekeeper_id", "task_code", "litigation_stage",
        "hours_worked_milli", "hourly_rate_cents", "entry_date",
    ])
    timekeeper_id = util.check_string(data, "timekeeper_id")
    tk = db.timekeepers.get(timekeeper_id)
    if tk is None or tk.get("firm_id") != firmId:
        from errors import err_not_found
        raise err_not_found(f"Timekeeper {timekeeper_id} not found")
    task_code = util.check_string(data, "task_code")
    stage = util.check_enum(data, "litigation_stage", LITIGATION_STAGES)
    hours = util.check_int(data, "hours_worked_milli", minimum=1)
    rate = util.check_int(data, "hourly_rate_cents", minimum=0)
    y, m, d = util.parse_iso_date(data.get("entry_date"), "entry_date")

    # Line-level floor rounding, pinned at creation (PRD §2.5 / §3.4).
    billable = (int(hours) * int(rate)) // 1000
    period_index = util.period_index_for_date(firm, y, m, d)

    entry = util.new_resource()
    entry.update({
        "matter_id": matter["id"],
        "firm_id": firmId,
        "timekeeper_id": timekeeper_id,
        "task_code": task_code,
        "litigation_stage": stage,
        "hours_worked_milli": hours,
        "hourly_rate_cents": rate,
        "billable_amount_cents": billable,
        "entry_date": data.get("entry_date"),
        "period_index": period_index,
        "status": "DRAFT",
        "written_down_amount_cents": 0,
    })
    db.time_entries[entry["id"]] = entry
    return success_object(entry, 201)


@bp.get("/firms/time_entries/<entryId>")
def get_time_entry(entryId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    entry = util.get_entry_flat(entryId)
    return success_object(entry, 200)


@bp.get("/firms/time_entries")
def list_time_entries():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters([
        "firm_id", "matter_id", "timekeeper_id", "status", "task_code", "period_index",
    ])
    items = util.apply_filters(list(db.time_entries.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/time_entries")
def list_time_entries_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    filters = util.query_filters(["status", "task_code", "period_index"])
    items = [e for e in db.time_entries.values() if e.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/time_entries/<entryId>/submit")
def submit_time_entry(firmId, entryId):
    ctx = get_context()
    require_roles(ctx, "Timekeeper", "BillingPartner")
    firm = util.get_firm(firmId)
    entry = util.get_entry_scoped(firmId, entryId)
    if entry["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT time entry can be submitted", 409)
    matter = db.matters.get(entry["matter_id"])
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")

    # Four guards in fixed order (PRD §3.4).
    if matter["status"] not in ("ACTIVE", "REOPENED"):
        raise ApiError(ERR_MATTER_NOT_OPEN,
                       "Matter not in ACTIVE/REOPENED for time entry submission", 409)
    client = db.clients.get(matter.get("client_id"))
    if client is None or client.get("status") != "ACTIVE":
        raise ApiError(ERR_CLIENT_NOT_ACTIVE,
                       "Client SUSPENDED or CLOSED; blocks new time entries", 409)
    if int(entry.get("period_index", 0)) <= int(firm.get("closed_through_period_index", -1)):
        raise ApiError(ERR_PERIOD_CLOSED,
                       "Entry date's fiscal period is at or before closed_through_period_index", 409)
    covered = any(
        p.get("matter_id") == matter["id"]
        and p.get("task_code") == entry.get("task_code")
        and p.get("status") == "ACTIVE"
        for p in db.phase_budgets.values()
    )
    if not covered:
        raise ApiError(ERR_TASK_CODE_NOT_BUDGETED,
                       "Time entry task_code does not match any ACTIVE PhaseBudget", 409)

    entry["status"] = "SUBMITTED"
    util.touch(entry)
    return success_object(entry, 200)


@bp.post("/firms/<firmId>/time_entries/<entryId>/approve")
def approve_time_entry(firmId, entryId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    firm = util.get_firm(firmId)
    entry = util.get_entry_scoped(firmId, entryId)
    if entry["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a SUBMITTED time entry can be approved", 409)
    entry["status"] = "APPROVED"
    util.touch(entry)

    matter = db.matters.get(entry["matter_id"])
    if matter is not None:
        derived.recompute_phase_actuals(matter["id"])
        derived.recompute_matter(matter)
        matter["last_activity_period_index"] = int(firm.get("current_period_index", 0))
        util.touch(matter)
    return success_object(entry, 200)


@bp.post("/firms/<firmId>/time_entries/<entryId>/mark_billed")
def mark_billed_time_entry(firmId, entryId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    entry = util.get_entry_scoped(firmId, entryId)
    if entry["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only an APPROVED time entry can be marked billed", 409)
    entry["status"] = "BILLED"
    util.touch(entry)
    matter = db.matters.get(entry["matter_id"])
    if matter is not None:
        derived.recompute_phase_actuals(matter["id"])
    return success_object(entry, 200)


@bp.post("/firms/<firmId>/time_entries/<entryId>/reject")
def reject_time_entry(firmId, entryId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    entry = util.get_entry_scoped(firmId, entryId)
    if entry["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT or SUBMITTED time entry can be rejected", 409)
    entry["status"] = "REJECTED"
    util.touch(entry)
    return success_object(entry, 200)
