"""Common area components and the three-milestone dispatcher."""
from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("components", __name__)


@bp.post("/hoa/components")
def create_component():
    auth.require_roles(constants.ROLE_DECLARANT)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    name = v.get_str(body, "name", min_len=1, max_len=80)
    category = v.get_enum(body, "category", constants.COMPONENT_CATEGORIES)
    replacement_cost = v.get_int(body, "replacement_cost_cents", minimum=0)
    useful_life = v.get_int(body, "useful_life_years", minimum=1)
    effective_age = v.get_int(body, "effective_age_years", minimum=0)
    promised, _ = v.get_datetime(body, "promised_completion_date")
    build_status = v.get_enum(
        body,
        "build_status",
        constants.COMPONENT_CREATE_BUILD_STATUSES,
        required=False,
        default="UNBUILT",
    )

    component = new_record({
        "association_id": association["id"],
        "name": name,
        "category": category,
        "replacement_cost_cents": replacement_cost,
        "useful_life_years": useful_life,
        "effective_age_years": effective_age,
        "promised_completion_date": promised,
        "build_status": build_status,
        "substantial_completion_date": None,
        "conveyance_status": "NOT_CONVEYED",
        "conveyed_at": None,
    })
    db.components[component["id"]] = component
    return response.object_response(serialize(component), 201)


@bp.post("/hoa/components/<component_id>/milestones")
def record_milestone(component_id):
    auth.require_roles(constants.ROLE_DECLARANT, constants.ROLE_TRANSITION_COMMITTEE)
    body = v.body()
    auth.require_discriminator_role(body.get("milestone"), constants.MILESTONE_ROLES)

    component = common.component_or_404(component_id, scoped=True)
    milestone = v.get_enum(body, "milestone", constants.COMPONENT_MILESTONES)
    effective_date = None
    if milestone == "BUILD_COMPLETE":
        effective_date, _ = v.get_datetime(body, "effective_date")

    if milestone == "CONVEYANCE_ACCEPTED":
        cascades.require_not_settled_locked(component["association_id"])

    association = db.associations.get(component["association_id"])

    if milestone == "BUILD_COMPLETE":
        if component["build_status"] not in ("UNBUILT", "IN_PROGRESS"):
            raise ApiError("ERR_COMPONENT_MILESTONE_INVALID")
        component["build_status"] = "COMPLETE"
        component["substantial_completion_date"] = effective_date
        touch(component)
        # cascade: recompute every claim's repose deadline, oldest first
        if association is not None:
            for claim in calc.claims_of_component(component["id"]):
                deadline = calc.repose_deadline(component, association)
                if claim["repose_deadline"] != deadline:
                    claim["repose_deadline"] = deadline
                    touch(claim)

    elif milestone == "DEED_TENDERED":
        if component["conveyance_status"] != "NOT_CONVEYED":
            raise ApiError("ERR_COMPONENT_MILESTONE_INVALID")
        if component["build_status"] != "COMPLETE":
            raise ApiError("ERR_COMPONENT_MILESTONE_INVALID")
        component["conveyance_status"] = "DEED_TENDERED"
        touch(component)

    else:  # CONVEYANCE_ACCEPTED
        if component["conveyance_status"] != "DEED_TENDERED":
            raise ApiError("ERR_COMPONENT_MILESTONE_INVALID")
        component["conveyance_status"] = "CONVEYED"
        component["conveyed_at"] = util.fmt_dt(clock.now())
        touch(component)
        # cascade: every DRAFT reserve study must be re-evaluated
        for study in calc.studies_of(component["association_id"]):
            if study["status"] != "DRAFT":
                continue
            study["evaluated_method"] = None
            study["adequacy_verdict"] = "UNDETERMINED"
            study["recommended_annual_contribution_cents"] = 0
            touch(study)

    return response.object_response(serialize(component))
