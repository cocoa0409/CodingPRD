"""ConsentRecord flat actions."""
from flask import Blueprint

import db
from db import bump
from errors import ApiError, ERR_NOT_FOUND, ERR_CONSENT_NOT_ACTIVE
from middleware import auth, require_role, forbid
from response import success_object
from services import cancel_order_cascade

bp = Blueprint("consents", __name__)


@bp.route("/consents/<consent_id>/revoke", methods=["POST"])
def revoke_consent(consent_id):
    uid, role = auth()
    require_role(role, {"Candidate"})
    consent = db.consents.get(consent_id)
    if consent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Consent not found")
    order = db.orders.get(consent["order_id"])
    # entity-backed ownership (2.5)
    if order is None or uid != order["candidate_id"]:
        forbid("Candidate may only revoke their own consent")
    if consent["status"] != "CAPTURED":
        raise ApiError(ERR_CONSENT_NOT_ACTIVE, 409,
                       "Revoke requires consent CAPTURED")
    consent["status"] = "REVOKED"
    bump(consent)
    # cascade: order cancelled with the full compensation chain
    cancel_order_cascade(order)
    return success_object(consent, 200)
