"""Vendor consolidations: projected savings net of approved exception leakage (PRD 3.7)."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support
from errors import ApiError
from services import calc, derive, uow

bp = Blueprint("consolidations", __name__)


@bp.post("/vendor-consolidations")
@support.transactional
def create_consolidation():
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    practice = support.load_fk(data, "practice_id", "practices")
    payload.string(data, "practice_id")
    vendor_category = payload.enum(data, "vendor_category", config.VENDOR_CATEGORIES)
    baseline = payload.integer(data, "baseline_annual_spend_cents", minimum=0)
    formulary = payload.integer(data, "formulary_annual_spend_cents", minimum=0)
    row = db.insert(
        "vendor_consolidations",
        {
            "practice_id": practice["id"],
            "vendor_category": vendor_category,
            "baseline_annual_spend_cents": baseline,
            "formulary_annual_spend_cents": formulary,
            "status": "PLANNED",
            "gross_savings_cents": None,
            "exception_leakage_cents": None,
            "projected_savings_cents": None,
            "exception_count_applied": 0,
        },
    )
    return "vendor_consolidations", row, 201


@bp.get("/vendor-consolidations/<vendor_consolidation_id>")
def get_consolidation(vendor_consolidation_id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_FINANCE_CONTROLLER,
            config.ROLE_CLINICAL_DIRECTOR,
        ]
    )
    row = support.load("vendor_consolidations", vendor_consolidation_id)
    return support.read_one("vendor_consolidations", row)


@bp.post("/vendor-consolidations/<vendor_consolidation_id>/finalize")
@support.transactional
def finalize_consolidation(vendor_consolidation_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    consolidation = support.load("vendor_consolidations", vendor_consolidation_id)
    payload.body()
    if consolidation["status"] != "PLANNED":
        raise ApiError(
            "ERR_INVALID_WORKFLOW_STATE",
            "Only a planned consolidation can be finalized.",
        )
    practice = db.get("practices", consolidation["practice_id"])
    support.require_affiliated(practice)
    support.require_posture(practice, ("STABILIZING", "INTEGRATED"))

    gross = calc.gross_savings(
        consolidation["baseline_annual_spend_cents"],
        consolidation["formulary_annual_spend_cents"],
    )

    # Leakage: only APPROVED exceptions of this practice and vendor category,
    # taken in created_at ASC order and never rounded.
    qualifying = []
    for employment in derive.employments_of_practice(practice["id"]):
        for exception in derive.exceptions_of_employment(employment["id"]):
            if (
                exception["status"] == "APPROVED"
                and exception["vendor_category"] == consolidation["vendor_category"]
            ):
                qualifying.append(exception)
    qualifying = db.ordered(qualifying)
    leakage = sum(item["incremental_cost_cents"] for item in qualifying)

    consolidation["gross_savings_cents"] = gross
    consolidation["exception_leakage_cents"] = leakage
    consolidation["exception_count_applied"] = len(qualifying)
    consolidation["projected_savings_cents"] = max(0, gross - leakage)
    consolidation["status"] = "FINALIZED"
    uow.touch(consolidation)
    return "vendor_consolidations", consolidation, 200
