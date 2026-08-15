"""Billing statement endpoints: list, read, payments."""

from flask import Blueprint, request
import db
from db import now_iso
from middleware import get_auth, require_role
from response import success_object, success_list
from utils import parse_pagination
from errors import (
    not_found, invalid_request, invalid_state, ApiError,
    ERR_PAYMENT_NOT_POSITIVE, ERR_OVERPAYMENT,
)

bp = Blueprint("billing_statements", __name__)


@bp.route("/api/v1/billing-statements", methods=["GET"])
def list_billing_statements():
    user_id, role = get_auth()
    require_role(role, ["BursarOffice", "ProgramCoordinator"])

    limit, offset = parse_pagination(request.args)
    application_id = request.args.get("application_id")
    status = request.args.get("status")

    items = list(db.billing_statements.values())
    if application_id is not None:
        items = [s for s in items if s["application_id"] == application_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]

    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(s) for s in page], limit, offset, total)


@bp.route("/api/v1/billing-statements/<id>", methods=["GET"])
def get_billing_statement(id):
    user_id, role = get_auth()
    require_role(role, ["BursarOffice", "ProgramCoordinator"])

    rec = db.billing_statements.get(id)
    if not rec:
        raise not_found("BillingStatement not found")
    return success_object(dict(rec), 200)


@bp.route("/api/v1/billing-statements/<id>/payments", methods=["POST"])
def record_payment(id):
    user_id, role = get_auth()
    require_role(role, ["BursarOffice"])

    rec = db.billing_statements.get(id)
    if not rec:
        raise not_found("BillingStatement not found")

    body = request.get_json(silent=True) or {}
    amount_cents = body.get("amount_cents")
    if amount_cents is None or isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise invalid_request("amount_cents must be an integer")

    # state gate
    if rec["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise invalid_state("BillingStatement is not in ISSUED or PARTIALLY_PAID status")

    # money checks (tier 11)
    if amount_cents <= 0:
        raise ApiError(ERR_PAYMENT_NOT_POSITIVE, "amount_cents must be > 0", 422)
    if amount_cents > rec["outstanding_cents"]:
        raise ApiError(ERR_OVERPAYMENT, "amount_cents exceeds outstanding_cents", 422)

    rec["amount_paid_cents"] += amount_cents
    if amount_cents == rec["outstanding_cents"]:
        rec["outstanding_cents"] = 0
        rec["status"] = "PAID"
    else:
        rec["outstanding_cents"] = rec["charge_cents"] - rec["amount_paid_cents"]
        rec["status"] = "PARTIALLY_PAID"

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)
