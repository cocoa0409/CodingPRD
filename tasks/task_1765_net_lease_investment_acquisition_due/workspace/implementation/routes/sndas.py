"""SNDA routes (PRD §3.8)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, req_bool, req_str
from routes.estoppels import _check_lease_in_deal
from services import domain

bp = Blueprint("sndas", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "PlatformAdmin")


@bp.route("/acquisition-deals/deals/<deal_id>/sndas", methods=["POST"])
def create_snda(deal_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    data = body()
    lease_id = req_str(data, "lease_id")
    _check_lease_in_deal(deal, lease_id)
    lender_name = req_str(data, "lender_name")
    non_disturbance = req_bool(data, "non_disturbance_confirmed")
    snda = db.make_record({
        "deal_id": deal["id"],
        "lease_id": lease_id,
        "lender_name": lender_name,
        "non_disturbance_confirmed": non_disturbance,
        "status": "REQUESTED",
    })
    db.stores["sndas"][snda["id"]] = snda
    return created(db.pub(snda))


@bp.route("/acquisition-deals/deals/<deal_id>/sndas", methods=["GET"])
def list_sndas(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.sndas_of(deal["id"])
    for param in ("status", "lease_id"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if str(s.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/sndas/<snda_id>", methods=["GET"])
def get_snda(deal_id, snda_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_snda_scoped(deal, snda_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/sndas/<snda_id>/receive", methods=["POST"])
def receive_snda(deal_id, snda_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    snda = domain.get_snda_scoped(deal, snda_id)
    if snda["status"] != "REQUESTED":
        raise ApiError("ERR_SNDA_INVALID_STATE",
                       "receive requires status REQUESTED", 409)
    snda["status"] = "RECEIVED"
    bump(snda)
    return ok(db.pub(snda))


@bp.route("/acquisition-deals/deals/<deal_id>/sndas/<snda_id>/certify", methods=["POST"])
def certify_snda(deal_id, snda_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    snda = domain.get_snda_scoped(deal, snda_id)
    if snda["status"] != "RECEIVED":
        raise ApiError("ERR_SNDA_INVALID_STATE",
                       "certify requires status RECEIVED", 409)
    if not snda["non_disturbance_confirmed"]:
        raise ApiError("ERR_SNDA_NON_DISTURBANCE_MISSING",
                       "SNDA certification requires non_disturbance_confirmed", 422)
    snda["status"] = "CERTIFIED"
    bump(snda)
    domain.recheck_snda_collection(deal)
    domain.recompute_posture(deal)
    return ok(db.pub(snda))


@bp.route("/acquisition-deals/deals/<deal_id>/sndas/<snda_id>/reject", methods=["POST"])
def reject_snda(deal_id, snda_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    snda = domain.get_snda_scoped(deal, snda_id)
    if snda["status"] != "RECEIVED":
        raise ApiError("ERR_SNDA_INVALID_STATE",
                       "reject requires status RECEIVED", 409)
    snda["status"] = "REJECTED"
    bump(snda)
    return ok(db.pub(snda))
