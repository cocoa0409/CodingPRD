"""StaffMember routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, opt_str, paginate,
                     sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("staff", __name__)


def staff_view(s):
    return {k: s[k] for k in (
        "id", "exhibitor_id", "convention_id", "full_name", "role_label",
        "badge_status", "created_at", "updated_at", "version")}


def _live_application(exhibitor_id, convention_id, statuses):
    for a in db.applications.values():
        if a["exhibitor_id"] == exhibitor_id and a["convention_id"] == convention_id \
                and a["status"] in statuses:
            return a
    return None


@bp.route("/staff-members", methods=["POST"])
def create_staff_member():
    user_id, _ = require_roles("Exhibitor")
    body = get_json_body()
    convention_id = require_str(body, "convention_id")
    full_name = require_str(body, "full_name")
    role_label = opt_str(body, "role_label")
    conv = db.conventions.get(convention_id)
    if conv is None:
        fail("ERR_NOT_FOUND", "convention_id does not exist")
    if _live_application(user_id, convention_id, ("CONTRACTED", "PLACED")) is None:
        fail("ERR_STAFF_NOT_ALLOWED_YET",
             "Staff registration requires a CONTRACTED or PLACED application")
    s = {
        "id": db.new_id(),
        "exhibitor_id": user_id,
        "convention_id": convention_id,
        "full_name": full_name,
        "role_label": role_label,
        "badge_status": "NONE",
    }
    db.stamp_created(s)
    db.staff_members[s["id"]] = s
    return success_object(staff_view(s), 201)


@bp.route("/staff-members", methods=["GET"])
def list_staff_members():
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    items = list(db.staff_members.values())
    if role == "Exhibitor":
        items = [s for s in items if s["exhibitor_id"] == user_id]
    for f in ("exhibitor_id", "convention_id", "badge_status"):
        v = request.args.get(f)
        if v is not None:
            if role == "Exhibitor" and f == "exhibitor_id":
                continue  # already coerced
            items = [s for s in items if s[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([staff_view(s) for s in page], limit, offset, total)


@bp.route("/staff-members/<staffMemberId>", methods=["GET"])
def get_staff_member(staffMemberId):
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    s = get_or_404(db.staff_members, staffMemberId)
    if role == "Exhibitor" and s["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own staff only")
    return success_object(staff_view(s), 200)


@bp.route("/staff-members/<staffMemberId>/issue-badge", methods=["POST"])
def issue_badge(staffMemberId):
    user_id, role = require_roles("Exhibitor", "OperationsStaff")
    s = get_or_404(db.staff_members, staffMemberId)
    if role == "Exhibitor" and s["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own staff only")
    if s["badge_status"] != "NONE":
        fail("ERR_INVALID_TRANSITION", "issue-badge requires badge_status NONE")
    exhibitor = db.exhibitors[s["exhibitor_id"]]
    conv = db.conventions[s["convention_id"]]
    app = _live_application(s["exhibitor_id"], s["convention_id"], ("PLACED",))
    if app is None:
        fail("ERR_INVALID_TRANSITION",
             "The exhibitor's application must be PLACED")
    if conv["phase"] not in ("LOGISTICS", "LIVE"):
        fail("ERR_PHASE_PRECONDITION",
             "Badges may be issued only in LOGISTICS or LIVE")
    # compliance gate before allocation gate
    if exhibitor["standing"] in ("SUSPENDED", "EVICTED"):
        fail("ERR_COMPLIANCE_HOLD", "Exhibitor standing blocks badge issuance")
    for t in db.issue_tickets.values():
        if t["exhibitor_id"] == s["exhibitor_id"] and t["convention_id"] == s["convention_id"] \
                and t["severity"] == "CRITICAL" \
                and t["status"] in ("OPEN", "TRIAGED", "ESCALATED"):
            fail("ERR_COMPLIANCE_HOLD",
                 "Unresolved CRITICAL issue blocks badge issuance")
    issued = sum(1 for m in db.staff_members.values()
                 if m["exhibitor_id"] == s["exhibitor_id"]
                 and m["convention_id"] == s["convention_id"]
                 and m["badge_status"] == "ISSUED")
    allocation = app["included_badges"] + app["purchased_extra_badges"]
    if issued >= allocation:
        fail("ERR_BADGE_ALLOCATION_EXHAUSTED",
             "No badge allocation remaining")
    s["badge_status"] = "ISSUED"
    db.touch(s)
    return success_object(staff_view(s), 200)


@bp.route("/staff-members/<staffMemberId>/revoke-badge", methods=["POST"])
def revoke_badge(staffMemberId):
    require_roles("OperationsStaff", "ShowDirector")
    s = get_or_404(db.staff_members, staffMemberId)
    if s["badge_status"] != "ISSUED":
        fail("ERR_INVALID_TRANSITION", "revoke-badge requires badge_status ISSUED")
    s["badge_status"] = "REVOKED"
    db.touch(s)
    return success_object(staff_view(s), 200)
