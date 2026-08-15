"""ReferralPanelMember management (PRD section 3.7)."""
from flask import Blueprint, request

from db import db, new_id
from errors import ERR_PANEL_HAS_ACTIVE_PLACEMENTS, fail
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services import derived
from services.common import get_or_404, list_response, stamp_new, touch
from services.enums import CASE_TYPES, PANEL_STATUSES
from services.serialize import panel_member_json
from validators import (body, check_allowed, opt_enum, opt_int, opt_list,
                        opt_str, req_int, req_list, req_str)

bp = Blueprint("panel", __name__)


@bp.route("/referral-panel-members", methods=["POST"])
@require_roles(["ProgramDirector"])
def create_panel_member():
    b = body()
    check_allowed(b, ["full_name", "firm_name", "practice_areas", "counties",
                      "max_active_referrals"])
    rec = {
        "id": new_id(),
        "full_name": req_str(b, "full_name"),
        "firm_name": opt_str(b, "firm_name", ""),
        "practice_areas": req_list(b, "practice_areas",
                                   enum_values=CASE_TYPES),
        "counties": req_list(b, "counties"),
        "max_active_referrals": req_int(b, "max_active_referrals", min_v=1),
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.panel_members[rec["id"]] = rec
    return ok_object(panel_member_json(rec), 201)


@bp.route("/referral-panel-members/<pid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_panel_member(pid):
    return ok_object(panel_member_json(get_or_404(db.panel_members, pid)))


@bp.route("/referral-panel-members", methods=["GET"])
@require_roles(ALL_ROLES)
def list_panel_members():
    records = list(db.panel_members.values())
    status = request.args.get("status")
    if status is not None:
        records = [m for m in records if m["status"] == status]
    practice_area = request.args.get("practice_area")
    if practice_area is not None:
        records = [m for m in records if practice_area in m["practice_areas"]]
    county = request.args.get("county")
    if county is not None:
        records = [m for m in records if county in m["counties"]]
    return list_response(records, panel_member_json)


@bp.route("/referral-panel-members/<pid>", methods=["PATCH"])
@require_roles(["ProgramDirector"])
def update_panel_member(pid):
    rec = get_or_404(db.panel_members, pid)
    b = body()
    check_allowed(b, ["status", "max_active_referrals", "practice_areas",
                      "counties"])
    updates = {}
    if "status" in b:
        v = opt_enum(b, "status", PANEL_STATUSES)
        if v is not None:
            updates["status"] = v
    if "max_active_referrals" in b:
        v = opt_int(b, "max_active_referrals", min_v=1)
        if v is not None:
            updates["max_active_referrals"] = v
    if "practice_areas" in b:
        v = opt_list(b, "practice_areas", enum_values=CASE_TYPES)
        if v is not None:
            updates["practice_areas"] = v
    if "counties" in b:
        v = opt_list(b, "counties")
        if v is not None:
            updates["counties"] = v

    if updates.get("status", rec["status"]) == "INACTIVE":
        if derived.panel_active_count(rec["id"]) > 0:
            fail(ERR_PANEL_HAS_ACTIVE_PLACEMENTS,
                 "Panel member still has accepted referrals")

    rec.update(updates)
    touch(rec)
    return ok_object(panel_member_json(rec))
