"""Practices: the integration unit whose posture gates seven operations (PRD 2.6)."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support
from errors import ApiError
from services import derive, uow

bp = Blueprint("practices", __name__)


@bp.post("/practices")
@support.transactional
def create_practice():
    middleware.authorize([config.ROLE_DEAL_COUNSEL, config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    affiliation = support.load_fk(data, "affiliation_id", "affiliations")
    vendor = support.load_fk(data, "conversion_vendor_id", "conversion_vendors")
    payload.string(data, "affiliation_id")
    payload.string(data, "conversion_vendor_id")
    name = payload.string(data, "name")
    state_code = payload.uppercase_code(data, "state_code", 2)
    charts_total_expected = payload.integer(data, "charts_total_expected", minimum=1)
    row = db.insert(
        "practices",
        {
            "affiliation_id": affiliation["id"],
            "conversion_vendor_id": vendor["id"],
            "name": name,
            "state_code": state_code,
            "charts_total_expected": charts_total_expected,
            "affiliation_status": "PENDING",
            "staffing_model_state": "LEGACY",
            "fte_hygiene_ratio_bps": None,
        },
    )
    # Attaching a practice increments the affiliation's practice_count and version.
    uow.touch(affiliation)
    return "practices", row, 201


@bp.get("/practices/<practice_id>")
def get_practice(practice_id):
    middleware.authorize(config.ALL_ROLES)
    row = support.load("practices", practice_id)
    return support.read_one("practices", row)


@bp.get("/practices")
def list_practices():
    middleware.authorize(config.DSO_ROLES)
    rows = db.all_rows("practices")
    rows = support.filter_rows(
        rows, "affiliation_id", payload.filter_value("affiliation_id")
    )
    rows = support.filter_rows(
        rows, "conversion_vendor_id", payload.filter_value("conversion_vendor_id")
    )
    rows = support.filter_posture(rows, payload.filter_value("integration_posture"))
    return support.read_many("practices", rows)


@bp.post("/practices/<practice_id>/standardize-staffing")
@support.transactional
def standardize_staffing(practice_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    practice = support.load("practices", practice_id)
    data = payload.body()
    ratio_bps = payload.integer(data, "fte_hygiene_ratio_bps")
    support.require_affiliated(practice)
    support.require_posture(practice, ("STABILIZING", "INTEGRATED"))
    if not (
        config.MIN_HYGIENE_RATIO_BPS <= ratio_bps <= config.MAX_HYGIENE_RATIO_BPS
    ):
        raise ApiError(
            "ERR_STAFFING_RATIO_OUT_OF_RANGE",
            "fte_hygiene_ratio_bps must fall between %d and %d inclusive."
            % (config.MIN_HYGIENE_RATIO_BPS, config.MAX_HYGIENE_RATIO_BPS),
        )
    practice["staffing_model_state"] = "STANDARDIZED"
    practice["fte_hygiene_ratio_bps"] = ratio_bps
    uow.touch(practice)
    return "practices", practice, 200


@bp.get("/practices/<id>/vendor-consolidations")
def list_practice_vendor_consolidations(id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_FINANCE_CONTROLLER,
            config.ROLE_CLINICAL_DIRECTOR,
        ]
    )
    practice = support.load("practices", id)
    rows = derive.consolidations_of_practice(practice["id"])
    return support.read_many("vendor_consolidations", rows)
