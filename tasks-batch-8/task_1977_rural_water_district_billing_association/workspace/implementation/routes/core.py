"""Clock, districts, service areas, members."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (ALL_ROLES, body, get_district, get_scoped, opt_enum,
                        req_int, req_str, require_roles)
from response import ok_list, ok_object, paginate
from services import (new_common, recompute_reserve, ser_area,
                      ser_district, ser_member, touch)

bp = Blueprint("core", __name__)

MEMBER_CLASSES = ["RESIDENTIAL", "COMMERCIAL", "AGRICULTURAL"]
NON_TERMINAL_MEMBER = ("APPLIED", "ACTIVE", "SUSPENDED")


# ------------------------------------------------------------------- clock

@bp.post("/_clock/set_current_utc")
@require_roles(ALL_ROLES)
def set_clock(user_id, role):
    b = body()
    raw = req_str(b, "to_iso8601")
    try:
        dt = db.parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO8601 datetime")
    db.set_clock(dt, raw)
    return ok_object({"current_utc": raw})


# --------------------------------------------------------------- districts

@bp.post("/districts")
@require_roles(["SystemAdmin"])
def create_district(user_id, role):
    b = body()
    name = req_str(b, "district_name")
    principal = req_int(b, "usda_loan_principal_cents", minimum=0)
    annual = req_int(b, "annual_debt_service_cents", strict_minimum=1)
    d = new_common()
    d.update({
        "district_name": name,
        "usda_loan_principal_cents": principal,
        "annual_debt_service_cents": annual,
        "reserve_target_cents": annual,
        "reserve_balance_cents": 0,
        "reserve_deficit_cents": annual,
        "covenant_status": "RESERVE_DEFICIENT",
        "active_rate_schedule_id": None,
        "current_billing_epoch": 0,
        "boil_order_active": False,
        "_forfeited_credits": [],
    })
    recompute_reserve(d)
    db.districts[d["id"]] = d
    return ok_object(ser_district(d), 201)


@bp.get("/districts/<district_id>")
@require_roles(ALL_ROLES)
def get_district_by_id(user_id, role, district_id):
    return ok_object(ser_district(get_district(district_id)))


@bp.get("/districts")
@require_roles(ALL_ROLES)
def list_districts(user_id, role):
    items = list(db.districts.values())
    filt = request.args.get("active_rate_schedule_id")
    if filt is not None:
        items = [d for d in items if d.get("active_rate_schedule_id") == filt]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_district(d) for d in page], limit, offset, total)


# ------------------------------------------------------------ service areas

@bp.post("/districts/<district_id>/service-areas")
@require_roles(["SystemAdmin"])
def create_area(user_id, role, district_id):
    b = body()
    name = req_str(b, "area_name")
    acres = req_int(b, "boundary_acres", strict_minimum=1)
    d = get_district(district_id)
    a = new_common()
    a.update({
        "district_id": d["id"],
        "area_name": name,
        "boundary_acres": acres,
        "status": "ACTIVE",
    })
    db.service_areas[a["id"]] = a
    return ok_object(ser_area(a), 201)


@bp.get("/districts/<district_id>/service-areas")
@require_roles(ALL_ROLES)
def list_areas(user_id, role, district_id):
    d = get_district(district_id)
    items = [a for a in db.service_areas.values() if a["district_id"] == d["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_area(a) for a in page], limit, offset, total)


@bp.get("/districts/<district_id>/service-areas/<area_id>")
@require_roles(ALL_ROLES)
def get_area(user_id, role, district_id, area_id):
    d = get_district(district_id)
    a = get_scoped(db.service_areas, area_id, d["id"], "ERR_AREA_NOT_FOUND", "ServiceArea")
    return ok_object(ser_area(a))


@bp.post("/districts/<district_id>/service-areas/<area_id>/retire")
@require_roles(["SystemAdmin"])
def retire_area(user_id, role, district_id, area_id):
    d = get_district(district_id)
    a = get_scoped(db.service_areas, area_id, d["id"], "ERR_AREA_NOT_FOUND", "ServiceArea")
    if a["status"] not in ("ACTIVE", "ANNEXED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Service area is not in a retirable state")
    for m in db.members.values():
        if (m["district_id"] == d["id"] and m["service_area_id"] == a["id"]
                and m["membership_status"] in NON_TERMINAL_MEMBER):
            raise ApiError("ERR_AREA_IN_USE", 409, "Service area still has non-terminal members")
    a["status"] = "RETIRED"
    touch(a)
    return ok_object(ser_area(a))


def area_serviceable(district_id, area_id):
    a = db.service_areas.get(area_id)
    if a is None or a["district_id"] != district_id:
        raise ApiError("ERR_AREA_NOT_SERVICEABLE", 422, "Service area does not belong to this district")
    if a["status"] not in ("ACTIVE", "ANNEXED_IN"):
        raise ApiError("ERR_AREA_NOT_SERVICEABLE", 422, "Service area is not ACTIVE or ANNEXED_IN")
    return a


# ----------------------------------------------------------------- members

@bp.post("/districts/<district_id>/members")
@require_roles(["BillingClerk"])
def create_member(user_id, role, district_id):
    b = body()
    legal_name = req_str(b, "legal_name")
    area_id = req_str(b, "service_area_id")
    member_class = opt_enum(b, "member_class", MEMBER_CLASSES, "RESIDENTIAL")
    d = get_district(district_id)
    area_serviceable(d["id"], area_id)
    m = new_common()
    m.update({
        "district_id": d["id"],
        "legal_name": legal_name,
        "service_area_id": area_id,
        "member_class": member_class,
        "membership_status": "APPLIED",
        "credit_balance_cents": 0,
        "consecutive_delinquent_cycles": 0,
    })
    db.members[m["id"]] = m
    return ok_object(ser_member(m), 201)


@bp.get("/districts/<district_id>/members")
@require_roles(ALL_ROLES)
def list_members(user_id, role, district_id):
    d = get_district(district_id)
    items = [m for m in db.members.values() if m["district_id"] == d["id"]]
    ms = request.args.get("membership_status")
    if ms is not None:
        items = [m for m in items if m["membership_status"] == ms]
    sa = request.args.get("service_area_id")
    if sa is not None:
        items = [m for m in items if m["service_area_id"] == sa]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_member(m) for m in page], limit, offset, total)


@bp.get("/districts/<district_id>/members/<member_id>")
@require_roles(ALL_ROLES)
def get_member(user_id, role, district_id, member_id):
    d = get_district(district_id)
    m = get_scoped(db.members, member_id, d["id"], "ERR_MEMBER_NOT_FOUND", "Member")
    return ok_object(ser_member(m))


@bp.post("/districts/<district_id>/members/<member_id>/approve")
@require_roles(["BillingClerk"])
def approve_member(user_id, role, district_id, member_id):
    d = get_district(district_id)
    m = get_scoped(db.members, member_id, d["id"], "ERR_MEMBER_NOT_FOUND", "Member")
    if m["membership_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not in APPLIED status")
    area_serviceable(d["id"], m["service_area_id"])
    m["membership_status"] = "ACTIVE"
    touch(m)
    return ok_object(ser_member(m))


@bp.post("/districts/<district_id>/members/<member_id>/terminate")
@require_roles(["BoardDirector"])
def terminate_member(user_id, role, district_id, member_id):
    d = get_district(district_id)
    m = get_scoped(db.members, member_id, d["id"], "ERR_MEMBER_NOT_FOUND", "Member")
    if m["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Terminate requires membership_status ACTIVE")
    for t in db.taps.values():
        if t["district_id"] == d["id"] and t["member_id"] == m["id"] and t["status"] != "ABANDONED":
            raise ApiError("ERR_OPEN_INVOICES_EXIST", 409, "All taps must be ABANDONED before termination")
    for inv in db.invoices.values():
        if (inv["district_id"] == d["id"] and inv["member_id"] == m["id"]
                and inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID")):
            raise ApiError("ERR_OPEN_INVOICES_EXIST", 409, "Open invoices exist for this member")
    if m["credit_balance_cents"] > 0:
        # Forfeited to the district; surfaces as an ANNUAL_TRUE_UP reserve
        # entry at the next cycle close.
        d["_forfeited_credits"].append(m["credit_balance_cents"])
        m["credit_balance_cents"] = 0
    m["membership_status"] = "TERMINATED"
    touch(m)
    return ok_object(ser_member(m))
