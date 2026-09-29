"""The national-office visitor roster."""

from flask import Blueprint

import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("visitors", __name__)


@bp.get("/accreditation/visitors/<visitor_id>")
def get_visitor(visitor_id):
    authenticate(("AccreditationOfficer", "Visitor"))
    return response.ok(helpers.public(helpers.visitor_or_404(visitor_id)))


@bp.get("/accreditation/visitors")
def list_visitors():
    authenticate(("AccreditationOfficer", "Visitor"))
    return helpers.collection_response(db.visitors, helpers.VISITOR_FILTERS)


@bp.post("/accreditation/visitors")
def add_visitor():
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    full_name = validators.req_str(data, "full_name", 1, 120)
    home_state_code = validators.req_state_code(data, "home_state_code")
    trained_through_year = validators.req_int(data, "trained_through_year", 2000, 2100)
    certifications = validators.req_enum_array(
        data, "certifications", domain.CERTIFICATIONS, default=[]
    )
    employer_camp_id = data.get("employer_camp_id")
    if employer_camp_id is not None and not isinstance(employer_camp_id, str):
        raise api_error(
            "ERR_INVALID_REQUEST", "Field 'employer_camp_id' must be a string."
        )
    if employer_camp_id is not None:
        helpers.camp_or_404(employer_camp_id)

    visitor = db.common_fields()
    visitor.update(
        {
            "full_name": full_name,
            "home_state_code": home_state_code,
            "trained_through_year": trained_through_year,
            "certifications": certifications,
            "employer_camp_id": employer_camp_id,
            "status": "ACTIVE",
            "committed_travel_days": 0,
            "deactivated_reason": None,
        }
    )
    db.visitors[visitor["id"]] = visitor
    return response.created(helpers.public(visitor))


@bp.post("/accreditation/visitors/<visitor_id>/deactivate")
def deactivate_visitor(visitor_id):
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    reason = validators.opt_str(data, "deactivated_reason", 0, 500)

    visitor = helpers.visitor_or_404(visitor_id)
    if visitor["status"] != "ACTIVE":
        raise api_error("ERR_VISITOR_INACTIVE", "The visitor is already INACTIVE.")

    visitor["status"] = "INACTIVE"
    if reason is not None:
        visitor["deactivated_reason"] = reason
    db.touch(visitor)

    touched_visits = []
    for seat in domain.visitor_assignments(visitor["id"]):
        if seat["status"] != "ASSIGNED":
            continue
        visit = db.visits.get(seat["visit_id"])
        domain.withdraw_seat(seat)
        if visit is not None and visit not in touched_visits:
            touched_visits.append(visit)
    for visit in touched_visits:
        domain.revert_visit_if_incomplete(visit)

    return response.ok(helpers.public(visitor))
