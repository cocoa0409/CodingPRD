"""HAPPayment endpoints."""

from flask import Blueprint

import db
import errors
from middleware import require_roles
from response import success_object
from routes.helpers import get_or_404

bp = Blueprint("hap_payments", __name__)


def serialize_payment(p):
    # HAPPayment carries only id and created_at — no updated_at, no version.
    return {
        "id": p["id"],
        "contract_id": p["contract_id"],
        "period_month": p["period_month"],
        "hap_amount_cents": p["hap_amount_cents"],
        "disbursement_status": p["disbursement_status"],
        "created_at": p["created_at"],
    }


@bp.route("/hcv/hap-payments/<pid>/disburse", methods=["POST"])
def disburse_payment(pid):
    require_roles("HousingAuthorityAdmin")
    p = get_or_404(db.hap_payments, pid, "HAPPayment")
    if p["disbursement_status"] != "SCHEDULED":
        raise errors.invalid_state("HAPPayment must be SCHEDULED to disburse")
    contract = db.hap_contracts.get(p["contract_id"])
    if contract is None:
        raise errors.not_found("Parent HAPContract not found")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Parent HAPContract must be ACTIVE")
    p["disbursement_status"] = "PAID"
    # HAPPayment has no updated_at/version
    return success_object(serialize_payment(p))
