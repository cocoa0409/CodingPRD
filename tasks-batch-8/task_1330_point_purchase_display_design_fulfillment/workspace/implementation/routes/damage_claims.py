"""DamageClaim endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, require_int, touch, paginate,
    sort_by_created, serialize,
)

bp = Blueprint("damage_claims", __name__)

GET_CLAIM_ROLES = ("PlatformAdmin", "ProgramManager", "ClaimsAdjuster", "WarehouseOperator")


def _get_claim_or_404(claim_id):
    c = db.damage_claims.get(claim_id)
    if not c:
        raise errors.err_not_found("Damage claim not found")
    return c


@bp.route("/pop/damage-claims", methods=["POST"])
@require_roles("ClaimsAdjuster", "WarehouseOperator")
def create_claim():
    body = request.get_json(silent=True) or {}
    kit_id = require_string(body, "kit_id")
    reported_by = require_string(body, "reported_by")
    replacement_quantity = require_int(body, "replacement_quantity", minimum=1)

    kit = db.kits.get(kit_id)
    if not kit:
        raise errors.err_not_found("Kit not found")
    if kit["status"] not in ("SHIPPED", "DELIVERED"):
        raise errors.err_referential("Kit is not in SHIPPED or DELIVERED")

    claim = new_common_fields()
    claim.update({
        "kit_id": kit_id,
        "reported_by": reported_by,
        "replacement_quantity": replacement_quantity,
        "replacement_cost_cents": None,
        "status": "REPORTED",
    })
    db.damage_claims[claim["id"]] = claim
    return response.success_object(serialize(claim), 201)


@bp.route("/pop/damage-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    _, role = get_auth()
    if role not in GET_CLAIM_ROLES:
        raise errors.err_unauthorized()
    claim = _get_claim_or_404(claim_id)
    return response.success_object(serialize(claim), 200)


@bp.route("/pop/kits/<kit_id>/damage-claims", methods=["GET"])
def list_kit_claims(kit_id):
    _, role = get_auth()
    if role not in GET_CLAIM_ROLES:
        raise errors.err_unauthorized()
    if not db.kits.get(kit_id):
        raise errors.err_not_found("Kit not found")
    items = sort_by_created([c for c in db.damage_claims.values() if c["kit_id"] == kit_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(c) for c in page], limit, offset, total)


@bp.route("/pop/damage-claims/<claim_id>/approve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def approve_claim(claim_id):
    claim = _get_claim_or_404(claim_id)
    if claim["status"] != "REPORTED":
        raise errors.err_invalid_state("Claim is not in REPORTED")
    kit = db.kits.get(claim["kit_id"])
    if not kit or kit["status"] not in ("SHIPPED", "DELIVERED"):
        raise errors.err_invalid_state("Parent kit is not in SHIPPED or DELIVERED")
    run = db.production_runs.get(kit["production_run_id"])
    unit_cost = run.get("unit_cost_cents") if run else None
    claim["replacement_cost_cents"] = claim["replacement_quantity"] * (unit_cost or 0)
    if kit["status"] == "SHIPPED":
        kit["status"] = "DAMAGED"
        touch(kit)
    claim["status"] = "APPROVED"
    touch(claim)
    return response.success_object(serialize(claim), 200)


@bp.route("/pop/damage-claims/<claim_id>/reject", methods=["POST"])
@require_roles("ClaimsAdjuster")
def reject_claim(claim_id):
    claim = _get_claim_or_404(claim_id)
    if claim["status"] != "REPORTED":
        raise errors.err_invalid_state("Claim is not in REPORTED")
    claim["status"] = "REJECTED"
    touch(claim)
    return response.success_object(serialize(claim), 200)


@bp.route("/pop/damage-claims/<claim_id>/fulfill", methods=["POST"])
@require_roles("WarehouseOperator")
def fulfill_claim(claim_id):
    claim = _get_claim_or_404(claim_id)
    if claim["status"] != "APPROVED":
        raise errors.err_invalid_state("Claim is not in APPROVED")
    claim["status"] = "FULFILLED"
    touch(claim)
    return response.success_object(serialize(claim), 200)
