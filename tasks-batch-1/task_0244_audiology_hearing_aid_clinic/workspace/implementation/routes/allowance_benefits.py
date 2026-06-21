"""Allowance benefit pool endpoints."""

from flask import Blueprint, request

from db import db
import serialize
import validate
from middleware import require_auth, require_role, require_ownership, get_json_body
from response import object_response, array_response
from services.domain import get_or_404
from services.listing import list_page

bp = Blueprint("allowance_benefits", __name__)


@bp.post("/clinic/allowance-benefits")
def create_benefit():
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin"})
    body = get_json_body()
    patient_id = validate.require_str(body, "patient_id")
    plan_name = validate.require_str(body, "plan_name")
    total_allowance = validate.require_int(body, "total_allowance_cents", minimum=1)
    per_device_cap = validate.require_int(body, "per_device_cap_cents", minimum=1)
    coinsurance_pct = validate.require_fraction(body, "coinsurance_pct")
    period_end = validate.require_date(body, "period_end")

    # FK existence (body FK, validated after structural body checks).
    get_or_404(db.patients, patient_id)

    obj = {
        "patient_id": patient_id,
        "plan_name": plan_name,
        "total_allowance_cents": total_allowance,
        "per_device_cap_cents": per_device_cap,
        "coinsurance_pct": coinsurance_pct,
        "consumed_allowance_cents": 0,
        "period_end": period_end,
        "status": "ACTIVE",
    }
    db.stamp_create(obj)
    with db.lock:
        db.allowance_benefits[obj["id"]] = obj
    return object_response(serialize.allowance_benefit(obj), 201)


@bp.get("/clinic/allowance-benefits/<bid>")
def get_benefit(bid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    obj = get_or_404(db.allowance_benefits, bid)
    require_ownership(auth, obj["patient_id"])
    return object_response(serialize.allowance_benefit(obj))


@bp.get("/clinic/allowance-benefits")
def list_benefits():
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin"})
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    items = [b for b in db.allowance_benefits.values()
             if (patient_id is None or b["patient_id"] == patient_id)
             and (status is None or b["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.allowance_benefit)
    return array_response(page, limit, offset, total)
