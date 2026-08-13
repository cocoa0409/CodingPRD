"""Employees: CRUD, status lifecycle, lane advancement, transcript."""
from decimal import Decimal
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch, now, fiscal_year
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_EMPLOYEE_NOT_ACTIVE, ERR_COMPLIANCE_HOLD, ERR_LANE_MAX_REACHED, \
    ERR_ADVANCEMENT_WINDOW_CLOSED, ERR_ADVANCEMENT_ALREADY_THIS_FY, \
    ERR_LANE_CREDITS_INSUFFICIENT
from serializers import ser_employee, ser_entry, lane_balance_decimal, \
    compliance_standing_of
from services import LANE_ORDER, drop_registration, promotion_sweep
from validate import req_str, req_enum

bp = Blueprint("employees", __name__)

LANES = tuple(LANE_ORDER)
KINDS = ("TEACHER", "ADMIN", "SPECIALIST")


def get_employee_or_404(eid):
    e = store.employees.get(eid)
    if e is None:
        raise err(ERR_NOT_FOUND, "employee not found")
    return e


@bp.post("/pd/employees")
def create_employee():
    require_role("PDCoordinator")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    kind = req_enum(body, "employee_kind", KINDS)
    building_id = req_str(body, "primary_building_id")
    base_lane = req_enum(body, "base_lane", LANES)
    if store.buildings.get(building_id) is None:
        raise err(ERR_NOT_FOUND, "primary_building_id not found")
    for e in store.employees.values():
        if e["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique")
    e = new_resource()
    e.update({
        "full_name": full_name,
        "email": email,
        "employee_kind": kind,
        "primary_building_id": building_id,
        "base_lane": base_lane,
        "current_lane": base_lane,
        "status": "ACTIVE",
        "last_advancement_fiscal_year": None,
        "_adv_count": 0,
    })
    store.employees[e["id"]] = e
    return ok(ser_employee(e), 201)


@bp.get("/pd/employees/<eid>")
def get_employee(eid):
    require_any_role()
    return ok(ser_employee(get_employee_or_404(eid)), 200)


@bp.get("/pd/employees")
def list_employees():
    require_any_role()
    items = store.employees.values()
    pb = request.args.get("primary_building_id")
    if pb is not None:
        items = [e for e in items if e["primary_building_id"] == pb]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    lane = request.args.get("current_lane")
    if lane is not None:
        items = [e for e in items if e["current_lane"] == lane]
    return paginate([ser_employee(e) for e in sort_by_created(items)])


@bp.post("/pd/employees/<eid>/set-status")
def set_status(eid):
    require_role("PDCoordinator")
    emp = get_employee_or_404(eid)
    body = get_body()
    target = req_enum(body, "status", ("ACTIVE", "ON_LEAVE", "SEPARATED"))
    cur = emp["status"]
    valid = ((cur == "ACTIVE" and target in ("ON_LEAVE", "SEPARATED")) or
             (cur == "ON_LEAVE" and target in ("ACTIVE", "SEPARATED")))
    if not valid:
        raise err(ERR_INVALID_STATE, "invalid employee status transition")
    emp["status"] = target
    touch(emp)
    if target == "SEPARATED":
        # Cascade: WAITLISTED -> WITHDRAWN; REGISTERED in PUBLISHED /
        # REGISTRATION_CLOSED sections -> DROPPED (release + sweep per seat).
        regs = [r for r in store.registrations.values()
                if r["teacher_id"] == emp["id"]]
        regs.sort(key=lambda r: r["_seq"])
        for r in regs:
            if r["status"] == "WAITLISTED":
                r["status"] = "WITHDRAWN"
                touch(r)
            elif r["status"] == "REGISTERED":
                section = store.sections.get(r["section_id"])
                if section is not None and section["status"] in (
                        "PUBLISHED", "REGISTRATION_CLOSED"):
                    drop_registration(r)  # releases + promotion sweep
    return ok(ser_employee(emp), 200)


@bp.post("/pd/employees/<eid>/advance-lane")
def advance_lane(eid):
    require_role("PDCoordinator")
    get_body()
    emp = get_employee_or_404(eid)
    # Gates evaluated in the PRD 3.9 pinned order.
    if emp["status"] != "ACTIVE":
        raise err(ERR_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
    if compliance_standing_of(emp) != "COMPLIANT":
        raise err(ERR_COMPLIANCE_HOLD, "employee has an ESCALATED assignment")
    if emp["current_lane"] == "DOC":
        raise err(ERR_LANE_MAX_REACHED, "already at top lane")
    ts = now()
    if ts.month not in (8, 9):
        raise err(ERR_ADVANCEMENT_WINDOW_CLOSED,
                  "lane advancement only in logical months 8 and 9")
    fy = fiscal_year(ts)
    if emp["last_advancement_fiscal_year"] == fy:
        raise err(ERR_ADVANCEMENT_ALREADY_THIS_FY,
                  "lane already advanced this fiscal year")
    if lane_balance_decimal(emp) < Decimal("12.0"):
        raise err(ERR_LANE_CREDITS_INSUFFICIENT, "lane_credit_balance < 12.0")
    idx = LANE_ORDER.index(emp["current_lane"])
    emp["current_lane"] = LANE_ORDER[idx + 1]
    emp["_adv_count"] = emp.get("_adv_count", 0) + 1
    emp["last_advancement_fiscal_year"] = fy
    touch(emp)
    return ok(ser_employee(emp), 200)


@bp.get("/pd/employees/<eid>/transcript")
def employee_transcript(eid):
    require_any_role()
    emp = get_employee_or_404(eid)
    items = [e for e in store.transcript_entries.values()
             if e["employee_id"] == emp["id"]]
    fy = request.args.get("fiscal_year")
    if fy is not None:
        try:
            fy_i = int(fy)
            items = [e for e in items if e["fiscal_year"] == fy_i]
        except ValueError:
            items = []
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    ctl = request.args.get("counts_toward_lane")
    if ctl is not None:
        if ctl.lower() == "true":
            items = [e for e in items if e["counts_toward_lane"] is True]
        elif ctl.lower() == "false":
            items = [e for e in items if e["counts_toward_lane"] is False]
    return paginate([ser_entry(e) for e in sort_by_created(items)])
