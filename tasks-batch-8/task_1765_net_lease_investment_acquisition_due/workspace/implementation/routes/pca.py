"""Property condition assessment routes (PRD §3.7)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, req_enum, req_int
from services import domain

bp = Blueprint("pca", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "PlatformAdmin")
CONDITION_RATINGS = {"GOOD", "FAIR", "POOR", "CRITICAL"}


@bp.route("/acquisition-deals/deals/<deal_id>/property-condition-assessments", methods=["POST"])
def create_pca(deal_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    data = body()
    pca = db.make_record({
        "deal_id": deal["id"],
        "immediate_repair_cost_cents": req_int(data, "immediate_repair_cost_cents"),
        "capital_reserve_cents_per_sqft": req_int(data, "capital_reserve_cents_per_sqft"),
        "total_reserve_cents": None,
        "condition_rating": req_enum(data, "condition_rating", CONDITION_RATINGS),
        "status": "ORDERED",
    })
    db.stores["pcas"][pca["id"]] = pca
    return created(db.pub(pca))


@bp.route("/acquisition-deals/deals/<deal_id>/property-condition-assessments", methods=["GET"])
def list_pcas(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.pcas_of(deal["id"])
    v = request.args.get("status")
    if v is not None:
        items = [p for p in items if p["status"] == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/property-condition-assessments/<pca_id>", methods=["GET"])
def get_pca(deal_id, pca_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_pca_scoped(deal, pca_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/property-condition-assessments/<pca_id>/receive", methods=["POST"])
def receive_pca(deal_id, pca_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    pca = domain.get_pca_scoped(deal, pca_id)
    if pca["status"] != "ORDERED":
        raise ApiError("ERR_PCA_INVALID_STATE",
                       "receive requires status ORDERED", 409)
    # total_reserve = per-sqft reserve * rentable sqft of the linked property.
    props = domain.properties_of(deal["id"])
    sqft = props[0]["rentable_sqft"] if props else 0
    pca["total_reserve_cents"] = pca["capital_reserve_cents_per_sqft"] * sqft
    pca["status"] = "RECEIVED"
    bump(pca)
    return ok(db.pub(pca))


@bp.route("/acquisition-deals/deals/<deal_id>/property-condition-assessments/<pca_id>/accept", methods=["POST"])
def accept_pca(deal_id, pca_id):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    pca = domain.get_pca_scoped(deal, pca_id)
    if pca["status"] != "RECEIVED":
        raise ApiError("ERR_PCA_INVALID_STATE",
                       "accept requires status RECEIVED", 409)
    if pca["condition_rating"] == "CRITICAL":
        raise ApiError("ERR_PCA_CRITICAL_CONDITION",
                       "A CRITICAL condition rating cannot be accepted", 422)
    pca["status"] = "ACCEPTED"
    bump(pca)
    domain.satisfy_milestone(deal, "PCA")
    domain.recompute_posture(deal)
    return ok(db.pub(pca))


@bp.route("/acquisition-deals/deals/<deal_id>/property-condition-assessments/<pca_id>/reject", methods=["POST"])
def reject_pca(deal_id, pca_id):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    pca = domain.get_pca_scoped(deal, pca_id)
    if pca["status"] != "RECEIVED":
        raise ApiError("ERR_PCA_INVALID_STATE",
                       "reject requires status RECEIVED", 409)
    pca["status"] = "REJECTED"
    bump(pca)
    return ok(db.pub(pca))
