"""Clinician-preference exceptions to the DSO formulary (PRD 3.7)."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support
from errors import ApiError
from services import calc, uow

bp = Blueprint("supply", __name__)


@bp.post("/supply-preference-exceptions")
@support.transactional
def create_exception():
    middleware.authorize([config.ROLE_DENTIST], clinician_identity=True)
    data = payload.body()
    employment = support.load_fk(data, "doctor_employment_id", "doctor_employments")
    payload.string(data, "doctor_employment_id")
    vendor_category = payload.enum(data, "vendor_category", config.VENDOR_CATEGORIES)
    item_code = payload.string(data, "item_code")
    annual_qty = payload.integer(data, "annual_qty", minimum=1)
    formulary_unit_cents = payload.integer(data, "formulary_unit_cents", minimum=0)
    preferred_unit_cents = payload.integer(data, "preferred_unit_cents", minimum=0)
    clinical_rationale = payload.string(data, "clinical_rationale")
    if employment["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_EMPLOYMENT_STATE",
            "Only an ACTIVE employment may request a preference exception.",
        )
    row = db.insert(
        "supply_preference_exceptions",
        {
            "doctor_employment_id": employment["id"],
            "vendor_category": vendor_category,
            "item_code": item_code,
            "annual_qty": annual_qty,
            "formulary_unit_cents": formulary_unit_cents,
            "preferred_unit_cents": preferred_unit_cents,
            "clinical_rationale": clinical_rationale,
            "status": "REQUESTED",
            "incremental_cost_cents": None,
            "decided_by_doctor_id": None,
        },
    )
    return "supply_preference_exceptions", row, 201


@bp.get("/supply-preference-exceptions/<supply_preference_exception_id>")
def get_exception(supply_preference_exception_id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_FINANCE_CONTROLLER,
            config.ROLE_CLINICAL_DIRECTOR,
            config.ROLE_DENTIST,
        ]
    )
    row = support.load(
        "supply_preference_exceptions", supply_preference_exception_id
    )
    return support.read_one("supply_preference_exceptions", row)


@bp.post("/supply-preference-exceptions/<supply_preference_exception_id>/decide")
@support.transactional
def decide_exception(supply_preference_exception_id):
    user_id, _ = middleware.authorize(
        [config.ROLE_CLINICAL_DIRECTOR], clinician_identity=True
    )
    exception = support.load(
        "supply_preference_exceptions", supply_preference_exception_id
    )
    data = payload.body()
    decision = payload.enum(data, "decision", config.DECISIONS)
    payload.string(data, "decision_note", required=False)
    employment = db.get("doctor_employments", exception["doctor_employment_id"])
    if employment["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_EMPLOYMENT_STATE",
            "The referenced employment is no longer ACTIVE.",
        )
    if exception["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_WORKFLOW_STATE",
            "Only a requested exception can be decided.",
        )
    if decision == "APPROVE":
        exception["status"] = "APPROVED"
        exception["incremental_cost_cents"] = calc.exception_incremental_cost(
            exception["preferred_unit_cents"],
            exception["formulary_unit_cents"],
            exception["annual_qty"],
        )
    else:
        exception["status"] = "DENIED"
    exception["decided_by_doctor_id"] = user_id
    uow.touch(exception)
    return "supply_preference_exceptions", exception, 200
