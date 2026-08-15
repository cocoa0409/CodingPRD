"""Loyalty members, vehicles, points adjustments and ledger (PRD 3.4, 2.9)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_DUPLICATE_NETWORK_ENROLLMENT, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_NOT_FOUND,
)
from middleware import authorized, scope_member
from response import success_object
from routes.helpers import list_from, public
from services import loyalty
from services.core import new_record, touch
from validate import (
    get_body, opt_int, req_str, require_path_resource, valid_int,
)

bp = Blueprint("members", __name__)

READ_ROLES = ["GeneralManager", "Cashier", "ShiftManager", "FuelDeskLead"]
VEHICLE_TYPES = ["TRACTOR", "BOX_TRUCK", "RV", "AUTO"]
MEMBER_LIST_ROLES = ["GeneralManager", "Cashier", "LoyaltyMember"]


@bp.post("/loyalty-members")
def create_member():
    authorized(["Cashier", "GeneralManager"])
    body = get_body()
    fleet = None
    if body.get("fleet_account_id") is not None:
        fleet = db["fleet_accounts"].get(body["fleet_account_id"]) \
            if isinstance(body.get("fleet_account_id"), str) else None
        if fleet is None:
            raise_error(ERR_NOT_FOUND, "fleet_account_id does not resolve")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    cap = opt_int(body, "stack_cap_points", 500, non_negative=True)
    rec = new_record("loyalty_members", {
        "full_name": full_name,
        "email": email,
        "fleet_account_id": fleet["id"] if fleet else None,
        "stack_cap_points": cap,
        "points_balance": 0,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


def _member_scoped(rid, caller):
    """Load the member, applying priority-3 identity scoping by path id."""
    if caller.role == "LoyaltyMember" and caller.user_id != rid:
        from errors import ERR_FORBIDDEN
        raise_error(ERR_FORBIDDEN, "member may only access its own record")
    return require_path_resource("loyalty_members", rid)


@bp.get("/loyalty-members/<rid>")
def get_member(rid):
    caller = authorized(READ_ROLES + ["LoyaltyMember"])
    member = _member_scoped(rid, caller)
    # Lazy expiry evaluation (PRD 2.5/2.9): points_balance is always the sum of
    # remaining_points over lots whose expires_at is strictly later than the
    # current logical clock, evaluated at read time — a pure derivation, so no
    # version bump (mirrors the site retail-mirror read pattern).
    loyalty.recompute_member_balance(member, bump=False)
    return success_object(public(member))


@bp.post("/loyalty-members/<rid>/suspend")
def suspend_member(rid):
    authorized(["GeneralManager"])
    member = require_path_resource("loyalty_members", rid)
    if member["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "member is not ACTIVE")
    member["status"] = "SUSPENDED"
    touch(member)
    return success_object(public(member))


@bp.post("/loyalty-members/<rid>/reactivate")
def reactivate_member(rid):
    authorized(["GeneralManager"])
    member = require_path_resource("loyalty_members", rid)
    if member["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "member is not SUSPENDED")
    member["status"] = "ACTIVE"
    touch(member)
    return success_object(public(member))


@bp.post("/loyalty-members/<rid>/close")
def close_member(rid):
    authorized(["GeneralManager"])
    member = require_path_resource("loyalty_members", rid)
    if member["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "member cannot be closed from its current state")
    member["status"] = "CLOSED"
    # Cancel every enrollment still in PENDING/ACTIVE/SUSPENDED
    for enr in db["enrollments"].values():
        if enr["loyalty_member_id"] == member["id"] \
                and enr["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            enr["status"] = "CANCELLED"
            touch(enr)
    loyalty.forfeit_all_points(member)
    touch(member)
    return success_object(public(member))


@bp.post("/loyalty-members/<rid>/adjustments")
def adjust_points(rid):
    authorized(["GeneralManager"])
    member = require_path_resource("loyalty_members", rid)
    body = get_body()
    delta = body.get("points_delta")
    if not valid_int(delta) or delta == 0:
        raise_error(ERR_INVALID_REQUEST, "points_delta must be a non-zero integer")
    req_str(body, "reason")
    if delta > 0:
        lot = loyalty.grant_lot(member["id"], delta, "ADJUSTMENT", member["id"])
    else:
        lot = loyalty.clawback_newest(member["id"], -delta, "ADJUSTMENT", member["id"])
    return success_object(public(lot), status=201)


@bp.get("/loyalty-members/<rid>/points-ledger")
def points_ledger(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    lots = [l for l in db["points_lots"].values() if l["loyalty_member_id"] == member["id"]]
    return list_from(lots)


@bp.post("/loyalty-members/<rid>/vehicles")
def register_vehicle(rid):
    caller = authorized(["LoyaltyMember", "Cashier", "GeneralManager"])
    member = _member_scoped(rid, caller)
    body = get_body()
    plate = req_str(body, "plate")
    vtype = body.get("vehicle_type")
    if vtype not in VEHICLE_TYPES:
        raise_error(ERR_INVALID_REQUEST, "vehicle_type must be TRACTOR, BOX_TRUCK, RV or AUTO")
    for v in db["vehicles"].values():
        if v["plate"] == plate:
            raise_error(ERR_INVALID_REQUEST, "plate is already registered")
    rec = new_record("vehicles", {
        "loyalty_member_id": member["id"],
        "plate": plate,
        "vehicle_type": vtype,
    })
    return success_object(public(rec), status=201)


@bp.get("/loyalty-members/<rid>/vehicles")
def list_vehicles(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    vehicles = [v for v in db["vehicles"].values() if v["loyalty_member_id"] == member["id"]]
    return list_from(vehicles)


@bp.post("/loyalty-members/<rid>/discount-enrollments")
def enroll_member(rid):
    caller = authorized(["LoyaltyMember", "Cashier", "GeneralManager"])
    member = _member_scoped(rid, caller)
    body = get_body()
    network = None
    if body.get("network_program_id") is not None:
        network = db["networks"].get(body["network_program_id"]) \
            if isinstance(body.get("network_program_id"), str) else None
        if network is None:
            raise_error(ERR_NOT_FOUND, "network_program_id does not resolve")
    if network is None:
        raise_error(ERR_INVALID_REQUEST, "network_program_id is required")
    # p25: no duplicate enrollment of the same member in the same network
    for enr in db["enrollments"].values():
        if enr["loyalty_member_id"] == member["id"] \
                and enr["network_program_id"] == network["id"] \
                and enr["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            raise_error(ERR_DUPLICATE_NETWORK_ENROLLMENT,
                        "member already enrolled in this network")
    rec = new_record("enrollments", {
        "network_program_id": network["id"],
        "loyalty_member_id": member["id"],
        "status": "PENDING",
    })
    return success_object(public(rec), status=201)


@bp.get("/loyalty-members/<rid>/discount-enrollments")
def list_member_enrollments(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    enrs = [e for e in db["enrollments"].values() if e["loyalty_member_id"] == member["id"]]
    return list_from(enrs)


@bp.get("/loyalty-members/<rid>/fuel-sales")
def member_fuel_sales(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    sales = [s for s in db["fuel_sales"].values() if s["loyalty_member_id"] == member["id"]]
    return list_from(sales)


@bp.get("/loyalty-members/<rid>/parking-reservations")
def member_parking(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    res = [r for r in db["parking_reservations"].values() if r["loyalty_member_id"] == member["id"]]
    return list_from(res)


@bp.get("/loyalty-members/<rid>/service-tickets")
def member_service_tickets(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    tickets = [t for t in db["service_tickets"].values() if t["loyalty_member_id"] == member["id"]]
    return list_from(tickets)


@bp.get("/loyalty-members/<rid>/store-sales")
def member_store_sales(rid):
    caller = authorized(MEMBER_LIST_ROLES)
    member = _member_scoped(rid, caller)
    sales = [s for s in db["store_sales"].values() if s["loyalty_member_id"] == member["id"]]
    return list_from(sales)
