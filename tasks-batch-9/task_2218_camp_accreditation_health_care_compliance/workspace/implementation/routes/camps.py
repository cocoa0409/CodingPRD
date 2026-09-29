"""Camp registration, the state licensing axis and the health centre."""

from flask import Blueprint

import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("camps", __name__)


@bp.get("/accreditation/camps/<camp_id>")
def get_camp(camp_id):
    ident = authenticate(
        ("CampDirector", "HealthCareStaff", "AccreditationOfficer", "StateLicensingAgent")
    )
    camp = helpers.camp_or_404(camp_id)
    helpers.scope(ident, camp["id"])
    return response.ok(helpers.public(camp))


@bp.get("/accreditation/camps")
def list_camps():
    authenticate(("AccreditationOfficer", "StateLicensingAgent"))
    return helpers.collection_response(db.camps, helpers.CAMP_FILTERS)


@bp.get("/accreditation/camps/<camp_id>/risk-index")
def camp_risk_index(camp_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "StateLicensingAgent"))
    camp = helpers.camp_or_404(camp_id)
    helpers.scope(ident, camp["id"])
    return response.ok(domain.risk_breakdown(camp))


@bp.post("/accreditation/camps")
def register_camp():
    authenticate(("AccreditationOfficer",))
    data = validators.body()

    name = validators.req_str(data, "name", 1, 160)
    camp_type = validators.req_enum(data, "camp_type", domain.CAMP_TYPES)
    state_code = validators.req_state_code(data, "state_code")
    population = validators.req_enum(data, "population_served", domain.POPULATIONS)
    elements = validators.req_enum_array(
        data, "program_elements", domain.PROGRAM_ELEMENTS, default=[]
    )
    resident_census = validators.opt_int(data, "resident_census", 0, default=0)
    distance = validators.opt_number(data, "distance_to_hospital_km", 0, default=0)
    max_daily = validators.opt_int(data, "max_daily_census", 0, default=0)
    staffing = validators.opt_enum(
        data, "health_staffing_level", domain.STAFFING_LEVELS, default="NONE"
    )
    prior_count = validators.opt_int(data, "prior_accredited_cycle_count", 0, default=0)

    camp = db.common_fields()
    camp.update(
        {
            "name": name,
            "camp_type": camp_type,
            "state_code": state_code,
            "population_served": population,
            "program_elements": elements,
            "resident_census": resident_census,
            "distance_to_hospital_km": distance,
            "max_daily_census": max_daily,
            "health_staffing_level": staffing,
            "required_health_staffing_level": "NONE",
            "prior_accredited_cycle_count": prior_count,
            "state_license_number": None,
            "state_license_status": "NONE",
            "accreditation_status": "NOT_ACCREDITED",
            "compliance_posture": "OPEN",
            "penalty_point_balance": 0,
            "health_intake_status": "OPEN",
            "controlled_intake_units": 0,
            "controlled_on_hand_units": 0,
            "risk_index": 0.0,
            "risk_index_variant": "PRE_VISIT",
            "last_accredited_year": None,
        }
    )
    # Derived state is computed before the row is published so that a freshly
    # registered camp is version 1.
    camp["required_health_staffing_level"] = domain.required_staffing_level(camp)
    camp["compliance_posture"] = domain.compute_posture(camp)
    camp["health_intake_status"] = (
        "SUSPENDED" if camp["compliance_posture"] == "FROZEN" else "OPEN"
    )
    breakdown = domain.risk_breakdown(camp)
    camp["risk_index"] = breakdown["risk_index"]
    camp["risk_index_variant"] = breakdown["risk_index_variant"]

    db.camps[camp["id"]] = camp
    return response.created(helpers.public(camp))


@bp.patch("/accreditation/camps/<camp_id>/state-license")
def move_state_license(camp_id):
    authenticate(("StateLicensingAgent",))
    data = validators.body()
    target = validators.req_enum(data, "state_license_status", domain.LICENSE_STATUSES)
    number = validators.opt_str(data, "state_license_number", 1, 80)

    camp = helpers.camp_or_404(camp_id)
    current = camp["state_license_status"]
    if (current, target) not in domain.LICENSE_TRANSITIONS:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "A state licence may not move from %s to %s." % (current, target),
        )
    if target == "ACTIVE":
        if current == "NONE":
            if number is None:
                raise api_error(
                    "ERR_INVALID_REQUEST",
                    "A licence number is required to activate a licence.",
                )
        elif number is None and camp["state_license_number"] is None:
            raise api_error(
                "ERR_INVALID_REQUEST",
                "A licence number is required to activate a licence.",
            )

    if number is not None:
        camp["state_license_number"] = number
    camp["state_license_status"] = target
    db.touch(camp)
    domain.recompute_posture(camp)
    domain.recompute_risk_index(camp)
    return response.ok(helpers.public(camp))


@bp.patch("/accreditation/camps/<camp_id>/health-center")
def update_health_center(camp_id):
    ident = authenticate(("HealthCareStaff", "CampDirector"))
    data = validators.body()
    staffing = validators.opt_enum(data, "health_staffing_level", domain.STAFFING_LEVELS)
    resident_census = validators.opt_int(data, "resident_census", 0)
    max_daily = validators.opt_int(data, "max_daily_census", 0)
    distance = validators.opt_number(data, "distance_to_hospital_km", 0)
    added = validators.opt_int(data, "controlled_intake_units_added", 0)

    camp = helpers.camp_or_404(camp_id)
    helpers.scope(ident, camp["id"])

    if staffing is not None:
        camp["health_staffing_level"] = staffing
    if resident_census is not None:
        camp["resident_census"] = resident_census
    if max_daily is not None:
        camp["max_daily_census"] = max_daily
    if distance is not None:
        camp["distance_to_hospital_km"] = distance
    if added:
        camp["controlled_intake_units"] = camp["controlled_intake_units"] + added
    db.touch(camp)

    domain.recompute_required_staffing(camp)
    domain.recompute_controlled_balance(camp)
    domain.recompute_posture(camp)
    domain.recompute_risk_index(camp)
    return response.ok(helpers.public(camp))
