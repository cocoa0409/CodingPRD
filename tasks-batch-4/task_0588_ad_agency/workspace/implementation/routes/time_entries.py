"""Time capture, approval and overtime (PRD 3.5)."""
from flask import Blueprint, g, request

import calc
import db
import response
import services
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("time_entries", __name__)

READ_ROLES = ["AgencyAdmin", "AccountManager", "CreativeLead", "MediaBuyer"]

_OPEN_STATUSES = ("SUBMITTED", "APPROVED", "BILLED")

_RATE_COLUMN = {
    "JUNIOR": "pinned_rate_junior_cents_per_hour",
    "SENIOR": "pinned_rate_senior_cents_per_hour",
    "DIRECTOR": "pinned_rate_director_cents_per_hour",
}


@bp.post("/time-entries")
@endpoint(["AccountManager", "CreativeLead", "MediaBuyer"])
def create_time_entry():
    b = validate.body()
    campaign_id = validate.req_str(b, "campaign_id")
    staff_id = validate.req_str(b, "staff_id")
    started_at = validate.req_datetime(b, "started_at")
    ended_at = validate.req_datetime(b, "ended_at")
    billable = validate.req_bool(b, "billable", required=False, default=True)

    if ended_at <= started_at:
        validate.bad("ended_at must be strictly after started_at.")
    if started_at.date() != ended_at.date():
        validate.bad("started_at and ended_at must fall on the same UTC calendar date.")
    minutes = int((ended_at - started_at).total_seconds() // 60)
    if minutes < 1:
        validate.bad("The worked interval must be at least one whole minute.")

    # Priority 6: body FKs, in the declared field order.
    campaign = services.must("campaign", campaign_id)
    staff = services.must("staff", staff_id)

    # Priority 7: nobody may log another person's hours.
    if g.user_id != staff_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Priority 11 / 12: the campaign and its SOW gates.
    services.campaign_gate(campaign)
    sow = services.must("sow", campaign["sow_id"])
    services.sow_gate(sow)

    work_date = started_at.date()

    # Priority 15: diary overlap on the same staff member (half-open interval).
    for other in db.TIME_ENTRIES.values():
        if other["staff_id"] != staff_id or other["status"] not in _OPEN_STATUSES:
            continue
        if started_at < other["_ended_at"] and other["_started_at"] < ended_at:
            raise ApiError("ERR_TIME_ENTRY_OVERLAP")

    # Priority 17 (i): the daily minute cap — non-billable rows count too.
    same_day = sum(
        t["minutes"]
        for t in db.TIME_ENTRIES.values()
        if t["staff_id"] == staff_id
        and t["_work_date"] == work_date
        and t["status"] in _OPEN_STATUSES
    )
    if same_day + minutes > calc.MAX_DAILY_MINUTES:
        raise ApiError("ERR_DAILY_MINUTES_EXCEEDED")

    # Pricing at creation: pinned rates only, straight line, no overtime uplift.
    if billable:
        pinned_rate = sow[_RATE_COLUMN[staff["grade"]]] or 0
        estimated = calc.straight_line_cents(minutes, pinned_rate)
    else:
        pinned_rate = 0
        estimated = 0
    internal_cost = calc.straight_line_cents(minutes, staff["cost_rate_cents_per_hour"])

    # Priority 17 (ii): the SOW labour cap, on the pre-request consumed figure.
    if sow["consumed_labor_cents"] + estimated > sow["labor_cap_cents"]:
        raise ApiError("ERR_SOW_LABOR_CAP_EXCEEDED")

    obj = db.base_entity()
    obj.update(
        {
            "campaign_id": campaign_id,
            "staff_id": staff_id,
            "approved_by_staff_id": None,
            "started_at": b["started_at"],
            "ended_at": b["ended_at"],
            "work_date": work_date.isoformat(),
            "minutes": minutes,
            "billable": billable,
            "pinned_rate_cents_per_hour": pinned_rate,
            "estimated_amount_cents": estimated,
            "regular_minutes": 0,
            "overtime_minutes": 0,
            "billable_amount_cents": 0,
            "internal_cost_cents": internal_cost,
            "status": "SUBMITTED",
            "_started_at": started_at,
            "_ended_at": ended_at,
            "_work_date": work_date,
        }
    )
    db.TIME_ENTRIES[obj["id"]] = obj

    services.recompute_sow_consumed_labor(sow)
    return response.created(db.public(obj))


@bp.get("/time-entries/<tid>")
@endpoint(READ_ROLES)
def get_time_entry(tid):
    return response.ok(db.public(services.must("time_entry", tid)))


@bp.get("/time-entries")
@endpoint(READ_ROLES)
def list_time_entries():
    limit, offset = validate.pagination()
    campaign_id = request.args.get("campaign_id")
    staff_id = request.args.get("staff_id")
    approved_by = request.args.get("approved_by_staff_id")
    status = request.args.get("status")
    rows = db.ordered(db.TIME_ENTRIES)
    if campaign_id:
        rows = [t for t in rows if t["campaign_id"] == campaign_id]
    if staff_id:
        rows = [t for t in rows if t["staff_id"] == staff_id]
    if approved_by:
        rows = [t for t in rows if t["approved_by_staff_id"] == approved_by]
    if status:
        rows = [t for t in rows if t["status"] == status]
    return response.listing(rows, limit, offset)


@bp.post("/time-entries/<tid>/approve")
@endpoint(["AccountManager"])
def approve_time_entry(tid):
    entry = services.must("time_entry", tid)

    # Priority 8: segregation of duties, ahead of the state check.
    if g.user_id == entry["staff_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if entry["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    campaign = services.must("campaign", entry["campaign_id"])
    services.campaign_gate(campaign)

    # Overtime is priced here, against the day's already-approved workload.
    prior_minutes = sum(
        t["minutes"]
        for t in db.TIME_ENTRIES.values()
        if t["id"] != entry["id"]
        and t["staff_id"] == entry["staff_id"]
        and t["_work_date"] == entry["_work_date"]
        and t["billable"]
        and t["status"] in ("APPROVED", "BILLED")
    )

    if entry["billable"]:
        regular, overtime = calc.overtime_split(entry["minutes"], prior_minutes)
        amount = calc.billable_amount(
            regular, overtime, entry["pinned_rate_cents_per_hour"]
        )
    else:
        regular, overtime, amount = 0, 0, 0

    entry["approved_by_staff_id"] = g.user_id
    entry["regular_minutes"] = regular
    entry["overtime_minutes"] = overtime
    entry["billable_amount_cents"] = amount
    entry["status"] = "APPROVED"
    services.touch(entry)
    return response.ok(db.public(entry))
