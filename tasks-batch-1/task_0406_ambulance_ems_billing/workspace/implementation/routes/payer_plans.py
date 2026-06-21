"""PayerPlan endpoints (PRD §3.1, §2.9)."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_ENUM, err
from middleware import authenticate, optional_authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    require_fields,
    touch,
)
from services.serialize import serialize

bp = Blueprint("payer_plans", __name__)

PAYER_TYPES = {"MEDICARE", "MEDICAID", "AUTO", "COMMERCIAL", "SELF_PAY"}


@bp.route("/payer-plans", methods=["POST"])
def create_payer_plan():
    optional_authenticate()
    body = get_json_body()
    require_fields(body, ["name", "payer_type"])
    if body["payer_type"] not in PAYER_TYPES:
        raise err(ERR_INVALID_ENUM, "Invalid payer_type")
    rec = {
        "name": body["name"],
        "payer_type": body["payer_type"],
        "qpa_multiplier": (
            body["qpa_multiplier"] if body.get("qpa_multiplier") is not None else 1.0
        ),
        "allows_balance_billing": bool(body.get("allows_balance_billing", True)),
        "status": "ACTIVE",
    }
    init_common(rec)
    store.payer_plans[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/payer-plans/<plan_id>", methods=["GET"])
def get_payer_plan(plan_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    rec = get_or_404(store.payer_plans, plan_id)
    return success(serialize(rec), 200)


@bp.route("/payer-plans/<plan_id>/deactivate", methods=["POST"])
def deactivate_payer_plan(plan_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin"])
    rec = get_or_404(store.payer_plans, plan_id)
    rec["status"] = "INACTIVE"
    touch(rec)
    return success(serialize(rec), 200)
