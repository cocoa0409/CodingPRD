"""LoyaltyMember routes (PRD §3.1; SCAFFOLD §1.5).

RBAC (§1.7):
  POST /loyalty-members                  Anonymous, StudioStaff, StudioManager
  GET  /loyalty-members/{id}             StudioStaff, StudioManager, LoyaltyMember(own)
  GET  /loyalty-members                  StudioStaff, StudioManager
  POST /loyalty-members/{id}/suspend     StudioManager
  POST /loyalty-members/{id}/reactivate  StudioManager
  GET  /loyalty-members/{id}/ledger      StudioStaff, StudioManager, LoyaltyMember(own)
  GET  /loyalty-members/{id}/visits      StudioStaff, StudioManager, LoyaltyMember(own)
  GET  /loyalty-members/{id}/enrollments StudioStaff, StudioManager, LoyaltyMember(own)
  GET  /loyalty-members/{id}/party-bookings StudioStaff, StudioManager, LoyaltyMember(own)
"""

from flask import Blueprint, request

from db import db, new_id, stamp_common, touch
from errors import invalid_state
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers
from services.lookup import get_member, assert_member_owns
from services.validation import require_body, require_str

bp = Blueprint("loyalty_members", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
STAFF_MANAGER_MEMBER = {"StudioStaff", "StudioManager", "LoyaltyMember"}


@bp.route("/loyalty-members", methods=["POST"])
def create_member():
    caller = get_caller()
    require_roles(caller, {"Anonymous", "StudioStaff", "StudioManager"})
    payload = require_body(request.get_json(silent=True))
    email = require_str(payload, "email")
    full_name = require_str(payload, "full_name")
    phone = require_str(payload, "phone")

    record = {
        "id": new_id(),
        "email": email.lower(),  # lowercased on store (PRD §3.1)
        "full_name": full_name,
        "phone": phone,
        "tier": "BRONZE",
        "point_balance": 0,
        "lifetime_points_earned": 0,
        "status": "ACTIVE",
    }
    stamp_common(record)
    db.loyalty_members[record["id"]] = record
    return success(serializers.member(record), status=201)


@bp.route("/loyalty-members/<member_id>", methods=["GET"])
def fetch_member(member_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    member = get_member(member_id)
    assert_member_owns(caller, member["id"])
    return success(serializers.member(member))


@bp.route("/loyalty-members", methods=["GET"])
def list_members():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    limit, offset = parse_pagination(request.args)
    email = request.args.get("email")
    records = list(db.loyalty_members.values())
    if email is not None:
        needle = email.lower()
        records = [r for r in records if r["email"] == needle]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.member(r) for r in window], limit, offset, total)


@bp.route("/loyalty-members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    member = get_member(member_id)
    member["status"] = "SUSPENDED"
    touch(member)
    return success(serializers.member(member))


@bp.route("/loyalty-members/<member_id>/reactivate", methods=["POST"])
def reactivate_member(member_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    member = get_member(member_id)
    member["status"] = "ACTIVE"
    touch(member)
    return success(serializers.member(member))


@bp.route("/loyalty-members/<member_id>/ledger", methods=["GET"])
def list_ledger(member_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    member = get_member(member_id)
    assert_member_owns(caller, member["id"])
    limit, offset = parse_pagination(request.args)
    records = [e for e in db.ledger_entries.values() if e["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.ledger_entry(r) for r in window], limit, offset, total)


@bp.route("/loyalty-members/<member_id>/visits", methods=["GET"])
def list_member_visits(member_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    member = get_member(member_id)
    assert_member_owns(caller, member["id"])
    limit, offset = parse_pagination(request.args)
    records = [v for v in db.studio_visits.values() if v["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.studio_visit(r) for r in window], limit, offset, total)


@bp.route("/loyalty-members/<member_id>/enrollments", methods=["GET"])
def list_member_enrollments(member_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    member = get_member(member_id)
    assert_member_owns(caller, member["id"])
    limit, offset = parse_pagination(request.args)
    records = [e for e in db.enrollments.values() if e["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.enrollment(r) for r in window], limit, offset, total)


@bp.route("/loyalty-members/<member_id>/party-bookings", methods=["GET"])
def list_member_bookings(member_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    member = get_member(member_id)
    assert_member_owns(caller, member["id"])
    limit, offset = parse_pagination(request.args)
    records = [b for b in db.party_bookings.values() if b["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.party_booking(r) for r in window], limit, offset, total)
