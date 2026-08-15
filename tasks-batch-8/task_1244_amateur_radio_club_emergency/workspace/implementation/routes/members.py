"""Member endpoints (PRD §3.1): registration, profile, status, dues renewal."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_CALLSIGN_TAKEN, ERR_DUES_LAPSED, ERR_INVALID_STATE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    LICENSE_CLASSES, as_dt, as_enum, as_int, as_str, bad_request, body_json,
    need, reject_unknown_fields,
)

bp = Blueprint("members", __name__)

MEMBERSHIP_STATUSES = {"PENDING", "ACTIVE", "LAPSED", "SUSPENDED"}
READ_ALL = {"ClubAdmin", "Member", "EmergencyCoordinator", "NetControl", "ExamLiaison"}
LIST_ROLES = {"ClubAdmin", "EmergencyCoordinator", "NetControl", "ExamLiaison"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


@bp.post("/members")
def create_member():
    _auth({"ClubAdmin"})
    body = body_json(request)
    reject_unknown_fields(body, {"callsign", "full_name", "license_class",
                                 "license_expires_at"})
    callsign = as_str(need(body, "callsign"), "callsign")
    full_name = as_str(need(body, "full_name"), "full_name")
    license_class = as_enum(need(body, "license_class"), "license_class",
                            LICENSE_CLASSES)
    license_expires_at = as_dt(need(body, "license_expires_at"),
                               "license_expires_at")
    # callsign unique club-wide, case-insensitive (ERR_CALLSIGN_TAKEN)
    for m in db.STORE["members"].values():
        if m["callsign"].lower() == callsign.lower():
            raise ApiError(ERR_CALLSIGN_TAKEN, 409,
                           "callsign already registered: %s" % callsign)
    member = {
        "callsign": callsign,
        "full_name": full_name,
        "license_class": license_class,
        "license_expires_at": license_expires_at,
        "membership_status": "PENDING",
        "dues_paid_through": None,
        "equipment_privilege": "GOOD_STANDING",
    }
    svc.stamp_new(member)
    db.STORE["members"][member["id"]] = member
    return success(svc.ser_member(member), "object", 201)


@bp.get("/members")
def list_members():
    _auth(LIST_ROLES)
    membership_status = request.args.get("membership_status")
    readiness_tier = request.args.get("readiness_tier")
    items = []
    for m in svc.sorted_records("members"):
        if membership_status is not None and m["membership_status"] != membership_status:
            continue
        ser = svc.ser_member(m)
        if readiness_tier is not None and ser["readiness_tier"] != readiness_tier:
            continue
        items.append(ser)
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/members/<mid>")
def get_member(mid):
    _auth(READ_ALL)
    member = svc.get_member(mid)
    return success(svc.ser_member(member), "object", 200)


@bp.patch("/members/<mid>")
def patch_member(mid):
    _auth({"ClubAdmin"})
    member = svc.get_member(mid)
    body = body_json(request)
    reject_unknown_fields(body, {"full_name", "license_class",
                                 "license_expires_at"})
    if "full_name" in body:
        member["full_name"] = as_str(body["full_name"], "full_name")
    if "license_class" in body:
        member["license_class"] = as_enum(body["license_class"],
                                          "license_class", LICENSE_CLASSES)
    if "license_expires_at" in body:
        member["license_expires_at"] = as_dt(body["license_expires_at"],
                                             "license_expires_at")
    svc.touch(member)
    return success(svc.ser_member(member), "object", 200)


@bp.post("/members/<mid>/set-status")
def set_member_status(mid):
    _auth({"ClubAdmin"})
    member = svc.get_member(mid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", MEMBERSHIP_STATUSES)
    current = member["membership_status"]
    if to == "SUSPENDED" and current == "ACTIVE":
        member["membership_status"] = "SUSPENDED"
    elif to == "ACTIVE" and current == "SUSPENDED":
        # Reinstatement requires dues strictly in the future (ERR_DUES_LAPSED).
        dpt = member["dues_paid_through"]
        if dpt is None or dpt <= db.now():
            raise ApiError(ERR_DUES_LAPSED, 409,
                           "reinstatement requires dues_paid_through > now")
        member["membership_status"] = "ACTIVE"
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move membership_status from %s to %s"
                       % (current, to))
    svc.touch(member)
    return success(svc.ser_member(member), "object", 200)


@bp.post("/members/<mid>/renew")
def renew_member(mid):
    """calculations.membership_renewal: base = max(clock, paid-through or
    epoch); dues_paid_through = base + periods * 365 days (1 year per period)."""
    _auth({"ClubAdmin"})
    member = svc.get_member(mid)
    body = body_json(request)
    reject_unknown_fields(body, {"periods"})
    periods = as_int(need(body, "periods"), "periods")
    if periods < 1:
        bad_request("periods must be >= 1")
    current = member["membership_status"]
    if current not in ("PENDING", "LAPSED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot renew a member in status %s" % current)
    base = member["dues_paid_through"] or svc.EPOCH
    if db.now() > base:
        base = db.now()
    member["dues_paid_through"] = _add_periods(base, periods)
    if current in ("PENDING", "LAPSED"):
        member["membership_status"] = "ACTIVE"
    svc.touch(member)
    amount = periods * svc.ANNUAL_DUES_CENTS
    data = svc.ser_member(member)
    data["renewal_amount_cents"] = amount
    return success(data, "object", 200)


def _add_periods(base, periods):
    """One renewal period is 365 days, i.e. one membership year (PRD §2.8)."""
    years = base.year + periods
    try:
        return base.replace(year=years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years.
        return base.replace(year=years, day=28)
