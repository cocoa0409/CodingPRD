"""Wrap proof customer transitions (approve / request-changes / reject)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role
from models import serialize, touch
from response import success
from services import common

bp = Blueprint("wrap_proofs", __name__)


def _customer_owns_proof(role, user_id, proof):
    if role == "Customer":
        wo = db.work_orders.get(proof["work_order_id"])
        quote = db.quotes.get(wo["quote_id"]) if wo else None
        vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"]) if quote else None
        common.check_customer_owns_vehicle(role, user_id, vehicle)


@bp.route("/wrap-proofs/<rid>/approve", methods=["POST"])
def approve(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    proof = common.get_or_404(db.wrap_proofs, rid)
    _customer_owns_proof(role, user_id, proof)
    if proof["status"] != "PROOF_SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WrapProof is not PROOF_SUBMITTED.")
    proof["status"] = "APPROVED"
    touch(proof)
    return success(serialize(proof), 200)


@bp.route("/wrap-proofs/<rid>/request-changes", methods=["POST"])
def request_changes(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    proof = common.get_or_404(db.wrap_proofs, rid)
    _customer_owns_proof(role, user_id, proof)
    if proof["status"] != "PROOF_SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WrapProof is not PROOF_SUBMITTED.")
    proof["status"] = "CHANGES_REQUESTED"
    touch(proof)
    return success(serialize(proof), 200)


@bp.route("/wrap-proofs/<rid>/reject", methods=["POST"])
def reject(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    proof = common.get_or_404(db.wrap_proofs, rid)
    _customer_owns_proof(role, user_id, proof)
    if proof["status"] != "PROOF_SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "WrapProof is not PROOF_SUBMITTED.")
    proof["status"] = "REJECTED"
    touch(proof)
    return success(serialize(proof), 200)
