"""The standards book: editions, standards and publication."""

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("standards", __name__)


@bp.get("/accreditation/standards-sets/<set_id>")
def get_set(set_id):
    authenticate(("CampDirector", "AccreditationOfficer"))
    return response.ok(helpers.public(helpers.set_or_404(set_id)))


@bp.get("/accreditation/standards-sets")
def list_sets():
    authenticate(("CampDirector", "AccreditationOfficer"))
    return helpers.collection_response(db.standards_sets, helpers.SET_FILTERS)


@bp.get("/accreditation/standards/<standard_id>")
def get_standard(standard_id):
    authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    return response.ok(helpers.public(helpers.standard_or_404(standard_id)))


@bp.get("/accreditation/standards")
def list_standards():
    authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    return helpers.collection_response(db.standards, helpers.STANDARD_FILTERS)


@bp.post("/accreditation/standards-sets")
def create_set():
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    edition_code = validators.req_str(data, "edition_code", 1, 40)
    effective_year = validators.req_int(data, "effective_year", 2000, 2100)

    for existing in db.standards_sets.values():
        if existing["edition_code"] == edition_code:
            raise api_error(
                "ERR_INVALID_REQUEST", "That edition_code is already in use."
            )

    row = db.common_fields()
    row.update(
        {
            "edition_code": edition_code,
            "effective_year": effective_year,
            "status": "DRAFT",
            "published_at": None,
            "standard_count": 0,
            "mandatory_count": 0,
        }
    )
    db.standards_sets[row["id"]] = row
    return response.created(helpers.public(row))


@bp.post("/accreditation/standards")
def create_standard():
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    validators.require(data, "standards_set_id")
    set_id = data["standards_set_id"]
    if not isinstance(set_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Field 'standards_set_id' must be a string.")
    code = validators.req_str(data, "code", 1, 16)
    title = validators.req_str(data, "title", 1, 200)
    standard_domain = validators.req_enum(data, "domain", domain.DOMAINS)
    mandatory = validators.opt_bool(data, "mandatory", default=False)
    weight = validators.opt_int(data, "scoring_weight", 1, 5, default=1)
    plan_type = validators.opt_enum(
        data, "written_plan_type_required", domain.PLAN_TYPES, default=None
    )
    camp_types = validators.req_enum_array(
        data, "applies_to_camp_types", domain.CAMP_TYPES, default=[]
    )
    program_any = validators.req_enum_array(
        data, "requires_program_elements_any", domain.PROGRAM_ELEMENTS, default=[]
    )
    populations = validators.req_enum_array(
        data, "applies_to_populations", domain.POPULATIONS, default=[]
    )
    requires_licensed = validators.opt_bool(
        data, "requires_state_licensed", default=False
    )

    standards_set = helpers.set_or_404(set_id)
    if standards_set["status"] != "DRAFT":
        raise api_error(
            "ERR_STANDARDS_SET_ALREADY_PUBLISHED",
            "Standards may only be added while the edition is DRAFT.",
        )
    for existing in db.standards.values():
        if existing["standards_set_id"] == set_id and existing["code"] == code:
            raise api_error(
                "ERR_INVALID_REQUEST", "That code already exists in this edition."
            )

    row = db.common_fields()
    row.update(
        {
            "standards_set_id": set_id,
            "code": code,
            "title": title,
            "domain": standard_domain,
            "mandatory": mandatory,
            "scoring_weight": weight,
            "written_plan_type_required": plan_type,
            "applies_to_camp_types": camp_types,
            "requires_program_elements_any": program_any,
            "applies_to_populations": populations,
            "requires_state_licensed": requires_licensed,
        }
    )
    db.standards[row["id"]] = row
    domain.recompute_set_counts(standards_set)
    return response.created(helpers.public(row))


@bp.post("/accreditation/standards-sets/<set_id>/publish")
def publish_set(set_id):
    authenticate(("AccreditationOfficer",))
    standards_set = helpers.set_or_404(set_id)
    if standards_set["status"] != "DRAFT":
        raise api_error(
            "ERR_STANDARDS_SET_ALREADY_PUBLISHED",
            "Only a DRAFT edition may be published.",
        )
    standards_set["status"] = "PUBLISHED"
    standards_set["published_at"] = clock.now_iso()
    db.touch(standards_set)
    return response.ok(helpers.public(standards_set))
