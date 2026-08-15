"""Rental contract endpoints (PRD 3.7): billing with pause/resume and
conversion to ownership at the payer's rental_months_to_own threshold."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_RENTAL_PERIOD_NOT_DUE,
    ERR_RENTAL_NOT_BILLING,
    ERR_RENTAL_ALREADY_CONVERTED,
)
from middleware import authorized, ROLE_BILLING
from response import success_object
from routes.helpers import get_one, list_response
from services.core import public, touch, rental_period_due_date
from util import today
from validate import require_path_resource

bp = Blueprint("rental_contracts", __name__, url_prefix="/sleep-therapy")


@bp.get("/rental-contracts")
def list_rental_contracts():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "device_enrollment_id": request.args.get("device_enrollment_id"),
        "payer_policy_id": request.args.get("payer_policy_id"),
        "billing_status": request.args.get("billing_status"),
        "equipment_status": request.args.get("equipment_status"),
    }
    return list_response("rental_contracts", filters)


@bp.get("/rental-contracts/<rid>")
def get_rental_contract(rid):
    return get_one("rental_contracts", rid)


@bp.post("/rental-contracts/<rid>/bill-rental-month")
def bill_rental_month(rid):
    authorized([ROLE_BILLING])
    contract = require_path_resource("rental_contracts", rid)
    # Fixed check order (PRD 3.7): anniversary due -> billing status -> not converted.
    if today() < rental_period_due_date(contract):
        raise_error(ERR_RENTAL_PERIOD_NOT_DUE,
                    "the next monthly rental anniversary has not arrived")
    if contract["billing_status"] != "BILLING":
        raise_error(ERR_RENTAL_NOT_BILLING,
                    "contract must be in BILLING status to bill a rental month")
    payer = db["payer_policies"].get(contract["payer_policy_id"])
    months_to_own = int(payer["rental_months_to_own"]) if payer else 0
    if contract["rental_months_billed"] >= months_to_own:
        raise_error(ERR_RENTAL_ALREADY_CONVERTED,
                    "contract has already accrued all rental months")

    contract["rental_months_billed"] = int(contract["rental_months_billed"]) + 1
    if contract["rental_months_billed"] >= months_to_own:
        # Conversion to ownership in the same request.
        contract["billing_status"] = "CONVERTED_TO_OWNERSHIP"
        contract["equipment_status"] = "OWNERSHIP_TRANSFERRED"
    touch(contract)
    return success_object(public(contract))
