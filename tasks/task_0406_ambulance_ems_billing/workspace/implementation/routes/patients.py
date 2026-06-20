"""Patient endpoints (PRD §3.1)."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_REQUEST, err
from middleware import authenticate, optional_authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    require_fields,
    resolve_fk,
)
from services.serialize import serialize

bp = Blueprint("patients", __name__)


@bp.route("/patients", methods=["POST"])
def create_patient():
    optional_authenticate()
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth"])

    coverages = body.get("coverages")
    normalized_coverages = []
    if coverages is not None:
        if not isinstance(coverages, list):
            raise err(ERR_INVALID_REQUEST, "coverages must be an array")
        for entry in coverages:
            if not isinstance(entry, dict):
                raise err(ERR_INVALID_REQUEST, "coverage entry must be an object")
            plan_id = entry.get("payer_plan_id")
            policy_rank = entry.get("policy_rank")
            if plan_id is None or policy_rank is None:
                raise err(ERR_INVALID_REQUEST, "coverage entry requires payer_plan_id and policy_rank")
            # priority 4: each payer_plan_id resolves to a PayerPlan.
            resolve_fk(store.payer_plans, plan_id)
            normalized_coverages.append(
                {"payer_plan_id": plan_id, "policy_rank": policy_rank}
            )

    rec = {
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "household_size": (
            body["household_size"] if body.get("household_size") is not None else 1
        ),
        "annual_household_income_cents": body.get("annual_household_income_cents"),
        "coverages": normalized_coverages,
    }
    init_common(rec)
    store.patients[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher", "Coder", "Biller", "ComplianceOfficer"])
    rec = get_or_404(store.patients, patient_id)
    return success(serialize(rec), 200)
