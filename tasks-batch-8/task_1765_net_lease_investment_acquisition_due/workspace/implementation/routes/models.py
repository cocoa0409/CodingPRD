"""Underwriting model routes (PRD §3.3, §2.11 version pinning)."""

from flask import Blueprint, g, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, opt_enum
from services import domain

bp = Blueprint("models", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "PlatformAdmin")
OPEX_VARIANTS = {"CONSERVATIVE", "MARKET"}


@bp.route("/acquisition-deals/deals/<deal_id>/underwriting-models", methods=["POST"])
def create_model(deal_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    data = body()
    variant = opt_enum(data, "opex_allowance_variant", OPEX_VARIANTS, "CONSERVATIVE")
    existing = domain.models_of(deal["id"])
    model = db.make_record({
        "deal_id": deal["id"],
        "model_version": (max((m["model_version"] for m in existing), default=0) + 1),
        "noi_cents": 0,
        "cap_rate_bps": None,
        "cash_on_cash_bps": None,
        "opex_allowance_variant": variant,
        "walt_months": 0,
        "status": "DRAFT",
        "_submitted_by": None,
    })
    domain.recompute_model(model)
    db.stores["models"][model["id"]] = model
    return created(db.pub(model))


@bp.route("/acquisition-deals/deals/<deal_id>/underwriting-models", methods=["GET"])
def list_models(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.models_of(deal["id"])
    v = request.args.get("status")
    if v is not None:
        items = [m for m in items if m["status"] == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/underwriting-models/<model_id>", methods=["GET"])
def get_model(deal_id, model_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_model_scoped(deal, model_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/underwriting-models/<model_id>/submit", methods=["POST"])
def submit_model(deal_id, model_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    model = domain.get_model_scoped(deal, model_id)
    if model["status"] != "DRAFT":
        raise ApiError("ERR_MODEL_INVALID_STATE",
                       "submit requires model status DRAFT", 409)
    # Figures are recomputed on submission before the gates are evaluated.
    domain.recompute_model(model)
    if model["noi_cents"] <= 0:
        raise ApiError("ERR_NOI_NON_POSITIVE",
                       "noi_cents must be positive at model submission", 422)
    if (model["cap_rate_bps"] is None
            or model["cap_rate_bps"] < domain.MIN_CAP_RATE_BPS
            or model["cap_rate_bps"] > domain.MAX_CAP_RATE_BPS):
        raise ApiError("ERR_CAP_RATE_OUT_OF_BAND",
                       "cap_rate_bps must be within [300, 1200]", 422)
    # A newer draft submission supersedes every other live DRAFT on the deal.
    for other in domain.models_of(deal["id"]):
        if other["id"] != model["id"] and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            bump(other)
    model["status"] = "SUBMITTED"
    model["_submitted_by"] = g.user_id
    bump(model)
    return ok(db.pub(model))


def _committee_decision(deal_id, model_id, outcome):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    model = domain.get_model_scoped(deal, model_id)
    if model["status"] != "SUBMITTED":
        raise ApiError("ERR_MODEL_INVALID_STATE",
                       f"{outcome.lower()} requires model status SUBMITTED", 409)
    # Segregation of duties: approver/rejector identity != submitter identity.
    if model.get("_submitted_by") is not None and g.user_id == model["_submitted_by"]:
        raise ApiError("ERR_SOD_VIOLATION",
                       "Segregation of duties: committee actor must differ from the submitter", 403)
    return deal, model


@bp.route("/acquisition-deals/deals/<deal_id>/underwriting-models/<model_id>/approve", methods=["POST"])
def approve_model(deal_id, model_id):
    deal, model = _committee_decision(deal_id, model_id, "APPROVE")
    domain.recompute_model(model)
    model["status"] = "APPROVED"
    bump(model)
    for other in domain.models_of(deal["id"]):
        if other["id"] != model["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            bump(other)
    # Pin refreshes freely only before PSA execution (PRD §2.11).
    if deal["status"] in ("SOURCING", "PSA_PENDING"):
        if deal.get("pinned_underwriting_model_id") != model["id"]:
            deal["pinned_underwriting_model_id"] = model["id"]
            bump(deal)
    return ok(db.pub(model))


@bp.route("/acquisition-deals/deals/<deal_id>/underwriting-models/<model_id>/reject", methods=["POST"])
def reject_model(deal_id, model_id):
    deal, model = _committee_decision(deal_id, model_id, "REJECT")
    model["status"] = "REJECTED"
    bump(model)
    return ok(db.pub(model))
