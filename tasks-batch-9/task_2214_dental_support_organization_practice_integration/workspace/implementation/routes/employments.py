"""Doctor employments: four independent state dimensions on one row (PRD 3.4)."""

from flask import Blueprint, g

import clock
import config
import db
import middleware
import payload
import support
from errors import ApiError, invalid
from services import calc, cascade, derive, uow

bp = Blueprint("employments", __name__)


def _require_employment_state(condition, message):
    if not condition:
        raise ApiError("ERR_INVALID_EMPLOYMENT_STATE", message)


@bp.post("/doctor-employments")
@support.transactional
def create_employment():
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    practice = support.load_fk(data, "practice_id", "practices")
    doctor = support.load_fk(data, "doctor_id", "doctors")
    payload.string(data, "practice_id")
    payload.string(data, "doctor_id")
    base_salary_monthly_cents = payload.integer(
        data, "base_salary_monthly_cents", minimum=0
    )
    collections_pct_bps = payload.integer(
        data, "collections_pct_bps", minimum=0, maximum=5000
    )
    comp_model = payload.enum(
        data,
        "comp_model",
        config.COMP_MODELS,
        required=False,
        default="MONTHLY_MIN_GUARANTEE",
    )
    legacy_annual_comp_cents = payload.integer(
        data, "legacy_annual_comp_cents", minimum=0
    )
    non_compete_months = payload.integer(
        data, "non_compete_months", minimum=0, maximum=config.MAX_NON_COMPETE_MONTHS
    )
    non_compete_radius_miles = payload.integer(
        data,
        "non_compete_radius_miles",
        minimum=0,
        maximum=config.MAX_NON_COMPETE_RADIUS_MILES,
    )
    affiliation = derive.affiliation_of_practice(practice)
    post_close_term_months = payload.integer(
        data,
        "post_close_term_months",
        required=False,
        default=affiliation["post_close_doctor_term_months"],
        minimum=0,
    )
    if doctor["license_state"] != practice["state_code"]:
        raise ApiError(
            "ERR_LICENSE_STATE_MISMATCH",
            "The doctor's licensure state must match the practice's state.",
        )
    row = db.insert(
        "doctor_employments",
        {
            "practice_id": practice["id"],
            "doctor_id": doctor["id"],
            "employment_status": "OFFERED",
            "credentialing_status": "PENDING",
            "records_custody_state": "HELD_BY_PRACTICE",
            "non_compete_enforcement_state": "NOT_APPLICABLE",
            "base_salary_monthly_cents": base_salary_monthly_cents,
            "collections_pct_bps": collections_pct_bps,
            "comp_model": comp_model,
            "legacy_annual_comp_cents": legacy_annual_comp_cents,
            "harmonized_annual_comp_cents": None,
            "harmonization_delta_cents": None,
            "is_harmonized": False,
            "post_close_term_months": post_close_term_months,
            "non_compete_months": non_compete_months,
            "non_compete_radius_miles": non_compete_radius_miles,
            "non_compete_end_date": None,
            "offer_accepted": False,
            "comp_effective_date": None,
            "separation_date": None,
            "separation_reason": None,
        },
    )
    return "doctor_employments", row, 201


@bp.get("/doctor-employments/<doctor_employment_id>")
def get_employment(doctor_employment_id):
    middleware.authorize(config.ALL_ROLES)
    row = support.load("doctor_employments", doctor_employment_id)
    return support.read_one("doctor_employments", row)


@bp.get("/doctor-employments")
def list_employments():
    middleware.authorize(
        [
            config.ROLE_DEAL_COUNSEL,
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_FINANCE_CONTROLLER,
            config.ROLE_CLINICAL_DIRECTOR,
        ]
    )
    rows = db.all_rows("doctor_employments")
    rows = support.filter_rows(rows, "practice_id", payload.filter_value("practice_id"))
    rows = support.filter_rows(rows, "doctor_id", payload.filter_value("doctor_id"))
    rows = support.filter_rows(
        rows, "employment_status", payload.filter_value("employment_status")
    )
    return support.read_many("doctor_employments", rows)


@bp.post("/doctor-employments/<doctor_employment_id>/accept-offer")
@support.transactional
def accept_offer(doctor_employment_id):
    middleware.authorize([config.ROLE_DENTIST], clinician_identity=True)
    employment = support.load("doctor_employments", doctor_employment_id)
    payload.body()
    _require_employment_state(
        employment["employment_status"] == "OFFERED"
        and not employment["offer_accepted"],
        "Only an unaccepted OFFERED employment can be accepted.",
    )
    practice = derive.practice_of_employment(employment)
    affiliation = derive.affiliation_of_practice(practice)
    if affiliation["status"] == "CLOSED":
        # Post-close acceptance activates immediately and can release a freeze.
        cascade.activate_employment(employment, practice)
    else:
        # Pre-close acceptance only records consent; the row stays OFFERED.
        employment["offer_accepted"] = True
        uow.touch(employment)
    return "doctor_employments", employment, 200


@bp.post("/doctor-employments/<doctor_employment_id>/harmonize-compensation")
@support.transactional
def harmonize_compensation(doctor_employment_id):
    middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    employment = support.load("doctor_employments", doctor_employment_id)
    data = payload.body()
    monthly = payload.int_list(
        data, "monthly_collections_cents", length=config.COMP_MONTHS, minimum=0
    )
    _require_employment_state(
        employment["employment_status"] == "ACTIVE",
        "Only an ACTIVE employment can be harmonized.",
    )
    practice = derive.practice_of_employment(employment)
    support.require_affiliated(practice)
    support.require_posture(practice, ("STABILIZING", "INTEGRATED"))
    harmonized = calc.doctor_compensation(
        employment["comp_model"],
        monthly,
        employment["base_salary_monthly_cents"],
        employment["collections_pct_bps"],
    )
    if calc.comp_cap_exceeded(harmonized, employment["legacy_annual_comp_cents"]):
        raise ApiError(
            "ERR_COMP_HARMONIZATION_CAP_EXCEEDED",
            "The harmonized package exceeds the legacy uplift ceiling.",
        )
    employment["harmonized_annual_comp_cents"] = harmonized
    employment["harmonization_delta_cents"] = (
        harmonized - employment["legacy_annual_comp_cents"]
    )
    employment["is_harmonized"] = True
    uow.touch(employment)
    return "doctor_employments", employment, 200


@bp.post("/doctor-employments/<doctor_employment_id>/separate")
@support.transactional
def separate(doctor_employment_id):
    middleware.authorize(
        [config.ROLE_INTEGRATION_LEAD, config.ROLE_DENTIST], clinician_identity=True
    )
    employment = support.load("doctor_employments", doctor_employment_id)
    data = payload.body()
    separation_reason = payload.enum(
        data, "separation_reason", config.SEPARATION_REASONS
    )
    _require_employment_state(
        employment["employment_status"] == "ACTIVE",
        "Only an ACTIVE employment can separate.",
    )
    cascade.separate_employment(employment, separation_reason)
    return "doctor_employments", employment, 200


@bp.post("/doctor-employments/<doctor_employment_id>/records-custody-transfer")
@support.transactional
def records_custody_transfer(doctor_employment_id):
    middleware.authorize([config.ROLE_CLINICAL_DIRECTOR], clinician_identity=True)
    employment = support.load("doctor_employments", doctor_employment_id)
    data = payload.body()
    payload.string(data, "custodian_note", required=False)
    _require_employment_state(
        employment["employment_status"] == "SEPARATED"
        and employment["records_custody_state"] == "TRANSFER_PENDING",
        "Custody transfer requires a separated employment with a pending transfer.",
    )
    employment["records_custody_state"] = "TRANSFERRED"
    uow.touch(employment)
    return "doctor_employments", employment, 200


@bp.post("/doctor-employments/<doctor_employment_id>/enforce-non-compete")
@support.transactional
def enforce_non_compete(doctor_employment_id):
    middleware.authorize([config.ROLE_DEAL_COUNSEL])
    employment = support.load("doctor_employments", doctor_employment_id)
    data = payload.body()
    payload.string(data, "enforcement_note", required=False)
    _require_employment_state(
        employment["employment_status"] == "SEPARATED"
        and employment["non_compete_enforcement_state"] == "PENDING",
        "Enforcement requires a separated employment with a pending covenant.",
    )
    end_date = employment["non_compete_end_date"]
    if end_date is None or clock.now() >= end_date:
        raise ApiError(
            "ERR_NON_COMPETE_EXPIRED",
            "The restrictive covenant window has already elapsed.",
        )
    employment["non_compete_enforcement_state"] = "ENFORCED"
    uow.touch(employment)
    return "doctor_employments", employment, 200


@bp.get("/doctor-employments/<id>/supply-preference-exceptions")
def list_employment_exceptions(id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_FINANCE_CONTROLLER,
            config.ROLE_CLINICAL_DIRECTOR,
            config.ROLE_DENTIST,
        ]
    )
    employment = support.load("doctor_employments", id)
    rows = derive.exceptions_of_employment(employment["id"])
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("supply_preference_exceptions", rows)


@bp.get("/doctor-employments/<id>/clinical-quality-reviews")
def list_employment_quality_reviews(id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_CLINICAL_DIRECTOR,
            config.ROLE_DENTIST,
        ]
    )
    employment = support.load("doctor_employments", id)
    rows = derive.reviews_of_employment(employment["id"])
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("clinical_quality_reviews", rows)
