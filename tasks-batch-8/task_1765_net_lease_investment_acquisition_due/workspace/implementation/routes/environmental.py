"""Environmental assessment routes (PRD §3.7)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, opt_bool, opt_enum, opt_int, req_bool, req_enum
from services import domain

bp = Blueprint("environmental", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "PlatformAdmin")
PHASES = {"PHASE_I", "PHASE_II"}


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments", methods=["POST"])
def create_ea(deal_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    data = body()
    ea = db.make_record({
        "deal_id": deal["id"],
        "phase": req_enum(data, "phase", PHASES),
        "recognized_environmental_condition": req_bool(data, "recognized_environmental_condition"),
        "remediation_cost_cents": opt_int(data, "remediation_cost_cents", 0),
        "reliance_letter_received": opt_bool(data, "reliance_letter_received", False),
        "status": "ORDERED",
    })
    db.stores["eas"][ea["id"]] = ea
    return created(db.pub(ea))


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments", methods=["GET"])
def list_eas(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.eas_of(deal["id"])
    for param in ("status", "phase"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if str(e.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments/<ea_id>", methods=["GET"])
def get_ea(deal_id, ea_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_ea_scoped(deal, ea_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments/<ea_id>/receive", methods=["POST"])
def receive_ea(deal_id, ea_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    ea = domain.get_ea_scoped(deal, ea_id)
    if ea["status"] != "ORDERED":
        raise ApiError("ERR_EA_INVALID_STATE",
                       "receive requires status ORDERED", 409)
    if not ea["reliance_letter_received"]:
        raise ApiError("ERR_RELIANCE_LETTER_REQUIRED",
                       "Reliance letter is required before the report can be received", 422)
    ea["status"] = "RECEIVED"
    bump(ea)
    return ok(db.pub(ea))


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments/<ea_id>/clear", methods=["POST"])
def clear_ea(deal_id, ea_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    ea = domain.get_ea_scoped(deal, ea_id)
    if ea["status"] != "RECEIVED":
        raise ApiError("ERR_EA_INVALID_STATE",
                       "clear requires status RECEIVED", 409)
    if ea["recognized_environmental_condition"]:
        raise ApiError("ERR_REC_PRESENT",
                       "A recognized environmental condition blocks a plain clear", 422)
    ea["status"] = "CLEARED"
    bump(ea)
    domain.satisfy_milestone(deal, "ENVIRONMENTAL")
    domain.recompute_posture(deal)
    return ok(db.pub(ea))


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments/<ea_id>/mark-conditional", methods=["POST"])
def mark_conditional_ea(deal_id, ea_id):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    ea = domain.get_ea_scoped(deal, ea_id)
    if ea["status"] != "RECEIVED":
        raise ApiError("ERR_EA_INVALID_STATE",
                       "mark-conditional requires status RECEIVED", 409)
    if not ea["recognized_environmental_condition"] or ea["remediation_cost_cents"] <= 0:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "mark-conditional requires a recognized environmental condition "
                       "with a costed remediation plan (remediation_cost_cents > 0)", 400)
    ea["status"] = "CONDITIONAL"
    bump(ea)
    # Conditional counts as satisfied for the ENVIRONMENTAL milestone.
    domain.satisfy_milestone(deal, "ENVIRONMENTAL")
    domain.recompute_posture(deal)
    return ok(db.pub(ea))


@bp.route("/acquisition-deals/deals/<deal_id>/environmental-assessments/<ea_id>/fail", methods=["POST"])
def fail_ea(deal_id, ea_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    ea = domain.get_ea_scoped(deal, ea_id)
    if ea["status"] != "RECEIVED":
        raise ApiError("ERR_EA_INVALID_STATE",
                       "fail requires status RECEIVED", 409)
    if not ea["recognized_environmental_condition"]:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "fail requires a recognized environmental condition", 400)
    ea["status"] = "FAILED"
    bump(ea)
    domain.recompute_posture(deal)  # FAILED -> DD_BLOCKED
    return ok(db.pub(ea))
