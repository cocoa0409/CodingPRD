"""Charge entry endpoints: get, list, void (billing correction)."""

from flask import Blueprint, request

from db import STORE, touch, public
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import auth_context, require_role, require_ownership, ALL_ROLES
from response import ok, paginated

bp = Blueprint("charges", __name__)


def _get_charge_or_404(charge_id):
    charge = STORE.charges.get(charge_id)
    if charge is None:
        raise_err(ERR_NOT_FOUND, "charge id does not exist")
    return charge


@bp.route("/transload/charges/<cid>", methods=["GET"])
def get_charge(cid):
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    charge = _get_charge_or_404(cid)
    require_ownership(user_id, role, charge["customer_id"])
    return ok(public(charge))


@bp.route("/transload/charges", methods=["GET"])
def list_charges():
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    customer_id = request.args.get("customer_id")
    railcar_id = request.args.get("railcar_id")
    invoice_id = request.args.get("invoice_id")
    charge_type = request.args.get("charge_type")
    status = request.args.get("status")
    if role == "CustomerRep":
        if customer_id is not None and customer_id != user_id:
            require_ownership(user_id, role, customer_id)
        customer_id = user_id
    items = sorted(STORE.charges.values(), key=lambda c: (c["created_at"], c["_seq"]))
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if railcar_id is not None:
        items = [c for c in items if c["railcar_id"] == railcar_id]
    if invoice_id is not None:
        items = [c for c in items if c["invoice_id"] == invoice_id]
    if charge_type is not None:
        items = [c for c in items if c["charge_type"] == charge_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginated(items)
    return ok([public(c) for c in page], pagination=meta)


@bp.route("/transload/charges/<cid>/void", methods=["POST"])
def void_charge(cid):
    _, role = auth_context()
    require_role(role, ["BillingClerk", "FacilityAdmin"])
    charge = _get_charge_or_404(cid)
    if charge["status"] != "ACCRUED":
        raise_err(ERR_INVALID_STATE, "charge is not ACCRUED")
    charge["status"] = "VOIDED"
    touch(charge)
    return ok(public(charge))
