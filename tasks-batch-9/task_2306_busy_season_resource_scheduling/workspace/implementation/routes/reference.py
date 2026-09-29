"""Reference data: the logical clock, clients, the staff roster, availability
exceptions and review capacity windows."""

from datetime import timedelta

from flask import Blueprint, request

import db
import response
import validation
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_ENGAGEMENT_STAFF,
    ROLE_FIRM_ADMIN,
    ROLE_INDEPENDENCE_OFFICER,
    ROLE_SCHEDULING_MANAGER,
    authorize,
)
from routes import common
from services import calc, serialize

bp = Blueprint("reference", __name__)


# =============================================================================
# logical clock
# =============================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(ROLE_FIRM_ADMIN)
    body = validation.json_body()
    moment = validation.req_instant(body, "to_iso8601")
    db.set_clock(moment)
    today = moment.date()
    db.commit()
    return response.object_response(
        {
            "current_utc": db.iso_ts(moment),
            "current_date": today.isoformat(),
            "iso_week_start_date": calc.iso_week_start(today).isoformat(),
        }
    )


# =============================================================================
# Client
# =============================================================================
@bp.post("/clients")
def create_client():
    authorize(ROLE_FIRM_ADMIN)
    body = validation.json_body()
    name = validation.req_string(body, "name", 1, 120)
    industry_code = validation.req_enum(body, "industry_code", validation.INDUSTRY_CODES)
    pie = validation.opt_boolean(body, "public_interest_entity", False)
    fiscal_year_end = validation.req_date(body, "fiscal_year_end")

    row = db.new_row()
    row.update(
        {
            "name": name,
            "industry_code": industry_code,
            "public_interest_entity": pie,
            "fiscal_year_end": fiscal_year_end,
        }
    )
    db.clients[row["id"]] = row
    db.commit()
    return response.object_response(serialize.client(row), 201)


@bp.get("/clients/<client_id>")
def read_client(client_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_INDEPENDENCE_OFFICER,
    )
    row = validation.path_client(client_id)
    return response.object_response(serialize.client(row))


@bp.get("/clients")
def list_clients():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_INDEPENDENCE_OFFICER,
    )
    industry_code = common.q("industry_code")
    pie = common.q_bool("public_interest_entity")
    if common.has_invalid(pie):
        return common.empty_page()
    rows = db.by_seq(list(db.clients.values()))
    if industry_code is not None:
        rows = [r for r in rows if r["industry_code"] == industry_code]
    if pie is not None:
        rows = [r for r in rows if r["public_interest_entity"] is pie]
    return common.page(rows, serialize.client)


# =============================================================================
# StaffMember
# =============================================================================
@bp.post("/staff-members")
def create_staff_member():
    authorize(ROLE_FIRM_ADMIN)
    body = validation.json_body()
    full_name = validation.req_string(body, "full_name", 1, 120)
    level = validation.req_enum(body, "level", validation.LEVELS)
    service_center = validation.req_enum(body, "service_center", validation.SERVICE_CENTERS)
    specialization = validation.req_enum(
        body, "industry_specialization", validation.INDUSTRY_CODES
    )
    cpa_licensed = validation.req_boolean(body, "cpa_licensed")
    base_cap = validation.req_number(body, "base_weekly_cap_hours", calc.D("20.00"), calc.D("60.00"))
    rate = validation.req_number(body, "hourly_bill_rate", calc.D("50.00"), calc.D("900.00"))

    row = db.new_row()
    row.update(
        {
            "full_name": full_name,
            "level": level,
            "service_center": service_center,
            "industry_specialization": specialization,
            "cpa_licensed": cpa_licensed,
            "base_weekly_cap_hours": calc.r2(base_cap),
            "hourly_bill_rate": calc.r2(rate),
        }
    )
    db.staff_members[row["id"]] = row
    db.commit()
    return response.object_response(serialize.staff_member(row), 201)


@bp.get("/staff-members/<staff_member_id>")
def read_staff_member(staff_member_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
        ROLE_INDEPENDENCE_OFFICER,
    )
    row = validation.path_staff(staff_member_id)
    return response.object_response(serialize.staff_member(row))


@bp.get("/staff-members")
def list_staff_members():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_INDEPENDENCE_OFFICER,
    )
    level = common.q("level")
    service_center = common.q("service_center")
    specialization = common.q("industry_specialization")
    band = common.q("turnover_risk_band")
    rows = db.by_seq(list(db.staff_members.values()))
    if level is not None:
        rows = [r for r in rows if r["level"] == level]
    if service_center is not None:
        rows = [r for r in rows if r["service_center"] == service_center]
    if specialization is not None:
        rows = [r for r in rows if r["industry_specialization"] == specialization]
    if band is not None:
        rows = [r for r in rows if calc.turnover_risk_band(r) == band]
    return common.page(rows, serialize.staff_member)


@bp.get("/staff-members/<staff_member_id>/workload")
def read_workload(staff_member_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    staff = validation.path_staff(staff_member_id)
    raw = common.q("week_start_date")
    if raw is None:
        week_start = calc.current_week_start()
    else:
        week_start = validation.parse_iso_date("week_start_date", raw)
        validation.require_monday("week_start_date", week_start)

    committed = calc.committed_hours(staff["id"], week_start)
    logged = calc.logged_hours_in_week(staff["id"], week_start)
    cap = calc.effective_weekly_cap(staff, week_start)
    base = calc.D(staff["base_weekly_cap_hours"])
    if committed <= base:
        status = "GREEN"
    elif committed <= cap:
        status = "AMBER"
    else:
        status = "RED"
    return response.object_response(
        {
            "staff_member_id": staff["id"],
            "week_start_date": week_start.isoformat(),
            "committed_hours": serialize.num(committed),
            "logged_hours": serialize.num(logged),
            "effective_weekly_cap_hours": serialize.num(cap),
            "daily_capacity_hours": serialize.num(
                calc.r2(cap / calc.STANDARD_WORK_DAYS_PER_WEEK)
            ),
            "approved_waiver_hours": serialize.num(
                calc.approved_waiver_hours(staff["id"], week_start)
            ),
            "remaining_week_hours": serialize.num(calc.r2(cap - committed)),
            "workload_status": status,
            "burnout_risk_score_actual": serialize.num(calc.burnout_risk_score_actual(staff)),
            "burnout_risk_score_committed": serialize.num(
                calc.burnout_risk_score_committed(staff)
            ),
            "turnover_risk_band": calc.turnover_risk_band(staff),
        }
    )


@bp.get("/staff-members/<staff_member_id>/availability-exceptions")
def list_staff_exceptions(staff_member_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    staff = validation.path_staff(staff_member_id)
    exception_type = common.q("exception_type")
    rows = calc.exceptions_of_staff(staff["id"])
    if exception_type is not None:
        rows = [r for r in rows if r["exception_type"] == exception_type]
    return common.page(rows, serialize.availability_exception)


# =============================================================================
# AvailabilityException
# =============================================================================
@bp.post("/availability-exceptions")
def create_availability_exception():
    authorize(ROLE_FIRM_ADMIN)
    body = validation.json_body()
    staff = validation.body_fk(body, "staff_member_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND")

    validation.req_string(body, "staff_member_id")
    exception_type = validation.req_enum(body, "exception_type", validation.EXCEPTION_TYPES)
    start_date = validation.req_date(body, "start_date")
    end_date = validation.req_date(body, "end_date")
    hours = validation.req_number(body, "available_hours_per_day", calc.D("0.00"), calc.D("8.00"))

    if end_date < start_date:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must be on or after start_date.")

    for existing in calc.exceptions_of_staff(staff["id"]):
        if calc.ranges_intersect(
            existing["start_date"], existing["end_date"], start_date, end_date
        ):
            raise ApiError(
                "ERR_EXCEPTION_OVERLAP",
                "The window overlaps an existing availability exception of this staff member.",
            )

    row = db.new_row(versioned=False)
    row.update(
        {
            "staff_member_id": staff["id"],
            "exception_type": exception_type,
            "start_date": start_date,
            "end_date": end_date,
            "available_hours_per_day": calc.r2(hours),
        }
    )
    db.availability_exceptions[row["id"]] = row
    db.commit()
    return response.object_response(serialize.availability_exception(row), 201)


# =============================================================================
# ReviewCapacityWindow
# =============================================================================
@bp.post("/review-capacity-windows")
def create_review_window():
    authorize(ROLE_FIRM_ADMIN)
    body = validation.json_body()
    reviewer = validation.body_fk(
        body, "reviewer_staff_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )

    validation.req_string(body, "reviewer_staff_id")
    week_start = validation.req_date(body, "week_start_date")
    capacity = validation.req_number(
        body, "review_capacity_hours", calc.D("0"), calc.D("40.00"), exclusive_min=True
    )

    validation.require_monday("week_start_date", week_start)

    if calc.find_review_window(reviewer["id"], week_start) is not None:
        raise ApiError(
            "ERR_DUPLICATE_REVIEW_WINDOW",
            "This reviewer already holds a window for that ISO week.",
        )

    if not calc.review_capable(reviewer):
        raise ApiError(
            "ERR_REVIEW_OWNER_NOT_ELIGIBLE", "The nominated reviewer is not review-capable."
        )

    row = db.new_row()
    row.update(
        {
            "reviewer_staff_id": reviewer["id"],
            "week_start_date": week_start,
            "review_capacity_hours": calc.r2(capacity),
        }
    )
    db.review_windows[row["id"]] = row
    db.commit()
    return response.object_response(serialize.review_window(row), 201)


@bp.get("/review-capacity-windows/<review_capacity_window_id>")
def read_review_window(review_capacity_window_id):
    authorize(ROLE_FIRM_ADMIN, ROLE_SCHEDULING_MANAGER, ROLE_ENGAGEMENT_PARTNER)
    row = validation.path_review_window(review_capacity_window_id)
    return response.object_response(serialize.review_window(row))


@bp.get("/review-capacity-windows")
def list_review_windows():
    authorize(ROLE_FIRM_ADMIN, ROLE_SCHEDULING_MANAGER, ROLE_ENGAGEMENT_PARTNER)
    reviewer_staff_id = common.q("reviewer_staff_id")
    week_start = common.q_date("week_start_date")
    if common.has_invalid(week_start):
        return common.empty_page()
    rows = db.by_seq(list(db.review_windows.values()))
    if reviewer_staff_id is not None:
        rows = [r for r in rows if r["reviewer_staff_id"] == reviewer_staff_id]
    if week_start is not None:
        rows = [r for r in rows if r["week_start_date"] == week_start]
    return common.page(rows, serialize.review_window)
