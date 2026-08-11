from decimal import Decimal

from flask import Blueprint

import db
import response
import serializers
from errors import raise_err
from middleware import check_member_ownership, require_roles
from routes._common import as_decimal, as_str, body, req_field
from services.calc import waitlist_promotion_scan

bp = Blueprint("members", __name__)


@bp.post("/api/members")
def create_member():
    require_roles(["COOP_ADMIN"])
    data = body()
    name = as_str(req_field(data, "name"), "name")
    code = as_str(req_field(data, "member_code"), "member_code")
    miles = as_decimal(req_field(data, "haul_distance_miles"), "haul_distance_miles")
    if miles < 0:
        raise_err("ERR_INVALID_REQUEST", "haul_distance_miles must be >= 0")
    for m in db.members.values():
        if m["member_code"] == code:
            raise_err("ERR_INVALID_REQUEST", "member_code must be unique")

    m = db.stamp_new({
        "name": name,
        "member_code": code,
        "haul_distance_miles": miles,
        "status": "ACTIVE",
        "net_ledger_cents": 0,
        "deterioration_loss_lbs": Decimal("0"),
    })
    db.members[m["id"]] = m
    return response.success(serializers.member(m), 201)


@bp.get("/api/members/<member_id>")
def get_member(member_id):
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    m = db.members.get(member_id)
    if not m:
        raise_err("ERR_NOT_FOUND", "Member not found")
    check_member_ownership(user_id, role, m["id"])
    return response.success(serializers.member(m), 200)


@bp.post("/api/members/<member_id>/suspend")
def suspend_member(member_id):
    require_roles(["COOP_ADMIN"])
    m = db.members.get(member_id)
    if not m:
        raise_err("ERR_NOT_FOUND", "Member not found")
    if m["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Member is not ACTIVE")
    m["status"] = "SUSPENDED"
    db.touch(m)
    # cascade: cancel REQUESTED/WAITLISTED/CONFIRMED bookings; CONFIRMED releases
    # booked_tons and triggers waitlist promotion scan at the station
    affected_stations = []
    for b in list(db.bookings.values()):
        if b["member_id"] != member_id:
            continue
        if b["status"] in ("REQUESTED", "WAITLISTED"):
            b["status"] = "CANCELLED"
            db.touch(b)
        elif b["status"] == "CONFIRMED":
            b["status"] = "CANCELLED"
            db.touch(b)
            st = db.stations.get(b["station_id"])
            if st:
                st["booked_tons"] = st["booked_tons"] - b["estimated_tons"]
                db.touch(st)
                affected_stations.append(st["id"])
    for sid in affected_stations:
        st = db.stations.get(sid)
        if st:
            waitlist_promotion_scan(st)
    return response.success(serializers.member(m), 200)


@bp.post("/api/members/<member_id>/reinstate")
def reinstate_member(member_id):
    require_roles(["COOP_ADMIN"])
    m = db.members.get(member_id)
    if not m:
        raise_err("ERR_NOT_FOUND", "Member not found")
    if m["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Member is not SUSPENDED")
    m["status"] = "ACTIVE"
    db.touch(m)
    return response.success(serializers.member(m), 200)
