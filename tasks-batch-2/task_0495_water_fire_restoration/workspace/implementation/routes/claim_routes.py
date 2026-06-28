from flask import Blueprint, request

from db import db, stamp_create
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from validate import (
    get_body, req_str, req_enum, req_int, opt_int, opt_number, pagination_params,
)

bp = Blueprint("claims", __name__)

PERILS = {"WATER", "FIRE", "MOLD"}


@bp.route("/restoration/claims", methods=["POST"])
def create_claim():
    user_id, role = auth(["Adjuster", "PlatformAdmin"])
    body = get_body()
    carrier_name = req_str(body, "carrier_name")
    policy_number = req_str(body, "policy_number")
    peril = req_enum(body, "peril", PERILS)
    coverage_limit_cents = req_int(body, "coverage_limit_cents", minimum=0)
    deductible_cents = opt_int(body, "deductible_cents", default=0, minimum=0)
    depreciation_pct = opt_number(body, "depreciation_pct", default=0, minimum=0, maximum=100)
    tax_pct = opt_number(body, "tax_pct", default=0, minimum=0, maximum=100)

    entity = {
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "adjuster_user_id": user_id,
        "peril": peril,
        "coverage_limit_cents": coverage_limit_cents,
        "deductible_cents": deductible_cents,
        "depreciation_pct": depreciation_pct,
        "tax_pct": tax_pct,
        "status": "OPEN",
        "settled_estimate_id": None,
    }
    stamp_create(entity)
    db.claims[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/restoration/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    auth(["Adjuster", "PlatformAdmin", "Dispatcher"])
    return object_response(get_or_404(db.claims, claim_id))


@bp.route("/restoration/claims", methods=["GET"])
def list_claims():
    auth(["Adjuster", "PlatformAdmin", "Dispatcher"])
    status = request.args.get("status")
    settled_estimate_id = request.args.get("settled_estimate_id")
    limit, offset = pagination_params()

    items = list(db.claims.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if settled_estimate_id is not None:
        items = [c for c in items if c["settled_estimate_id"] == settled_estimate_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
