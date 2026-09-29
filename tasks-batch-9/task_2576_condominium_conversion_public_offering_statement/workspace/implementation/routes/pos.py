"""The public offering statement, its nine statutory sections and amendments."""

from flask import Blueprint

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import cascades, projects as project_service

bp = Blueprint("pos", __name__)

CREATE_ROLES = ["ConverterSponsor"]
READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
              "Purchaser", "PlatformAdmin"]

SECTION_MIN_WORDS = 150
REQUIRED_SECTION_COUNT = 9


def _recount_sections(statement):
    """`complete_section_count` is recomputed, then the statement bubbles in
    whichever direction the new count demands."""
    sections = store.statement_sections(statement["id"])
    count = len([s for s in sections if s["content_status"] == "COMPLETE"])
    if statement["complete_section_count"] != count:
        statement["complete_section_count"] = count
        store.touch(statement)
    if statement["status"] == "DRAFT" and count == REQUIRED_SECTION_COUNT:
        statement["status"] = "SECTIONS_COMPLETE"
        store.touch(statement)
    elif (statement["status"] == "SECTIONS_COMPLETE"
            and count < REQUIRED_SECTION_COUNT):
        statement["status"] = "DRAFT"
        store.touch(statement)
    return statement


@bp.post("/conversion-projects/<project_id>/public-offering-statements")
def create_statement(project_id):
    v.authorize(CREATE_ROLES)
    project = v.get_project(project_id)
    body = v.raw_body()
    package = v.body_ref(body, "declaration_package_id", v.get_package)
    study = v.body_ref(body, "reserve_study_id", v.get_study)
    budget = v.body_ref(body, "initial_budget_id", v.get_budget)
    v.require_scope(project["id"], package, study, budget)
    fields = v.parse([
        v.field("declaration_package_id", "id"),
        v.field("reserve_study_id", "id"),
        v.field("initial_budget_id", "id"),
    ])
    if store.project_statement(project["id"]) is not None:
        # At most one PublicOfferingStatement per conversion_project_id.
        raise ApiError("ERR_DUPLICATE_KEY")
    v.gate_not_frozen(project)
    statement = store.new_record(store.public_offering_statements, {
        "_type": "PublicOfferingStatement",
        "conversion_project_id": project["id"],
        "declaration_package_id": fields["declaration_package_id"],
        "reserve_study_id": fields["reserve_study_id"],
        "initial_budget_id": fields["initial_budget_id"],
        "status": "DRAFT",
        "effective_at": None,
        "amendment_count": 0,
        "last_material_amendment_at": None,
        "complete_section_count": 0,
    })
    # Nine child sections are synthesized in the same act.
    for section_code in v.SECTION_CODES:
        store.new_record(store.pos_sections, {
            "_type": "POSSection",
            "public_offering_statement_id": statement["id"],
            "section_code": section_code,
            "body_ref": None,
            "word_count": 0,
            "content_status": "DRAFTED",
            "attested_by_user_id": None,
            "last_attested_at": None,
        })
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(statement), 201)


@bp.get("/conversion-projects/<project_id>/public-offering-statements")
def list_project_statements(project_id):
    v.authorize(READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [s for s in store.children(store.public_offering_statements,
                                         "conversion_project_id",
                                         project["id"])
               if v.matches(s, status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/public-offering-statements")
def list_statements():
    v.authorize(READ_ROLES)
    limit, offset = v.pagination()
    records = [
        s for s in store.ordered(store.public_offering_statements.values())
        if v.matches(
            s,
            conversion_project_id=v.filter_value("conversion_project_id"),
            declaration_package_id=v.filter_value("declaration_package_id"),
            reserve_study_id=v.filter_value("reserve_study_id"),
            initial_budget_id=v.filter_value("initial_budget_id"),
            status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/public-offering-statements/<statement_id>")
def get_statement(statement_id):
    v.authorize(READ_ROLES)
    statement = v.get_statement(statement_id)
    return envelope.object_response(serializers.dump(statement), 200)


@bp.get("/public-offering-statements/<statement_id>/sections")
def list_sections(statement_id):
    v.authorize(READ_ROLES)
    statement = v.get_statement(statement_id)
    limit, offset = v.pagination()
    records = [s for s in store.statement_sections(statement["id"])
               if v.matches(s,
                            content_status=v.filter_value("content_status"),
                            section_code=v.filter_value("section_code"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/public-offering-statements/<statement_id>/sections/<section_code>")
def get_section(statement_id, section_code):
    v.authorize(READ_ROLES)
    statement = v.get_statement(statement_id)
    section = v.get_section(statement["id"], section_code)
    return envelope.object_response(serializers.dump(section), 200)


@bp.put("/public-offering-statements/<statement_id>/sections/<section_code>")
def write_section(statement_id, section_code):
    v.authorize(CREATE_ROLES)
    statement = v.get_statement(statement_id)
    section = v.get_section(statement["id"], section_code)
    project = v.get_project(statement["conversion_project_id"])
    body = v.parse([
        v.field("body_ref", "string", max_len=200),
        v.field("word_count", "integer", minimum=0),
        v.field("attested_by_user_id", "string", required=False),
    ])
    v.gate_not_frozen(project)
    section["body_ref"] = body["body_ref"]
    section["word_count"] = body["word_count"]
    attester = body.get("attested_by_user_id")
    if attester:
        section["attested_by_user_id"] = attester
        section["last_attested_at"] = clock.now()
    else:
        section["attested_by_user_id"] = None
    section["content_status"] = (
        "COMPLETE"
        if (section["body_ref"] and body["word_count"] >= SECTION_MIN_WORDS
            and section["attested_by_user_id"])
        else "DRAFTED")
    store.touch(section)
    _recount_sections(statement)
    return envelope.object_response(serializers.dump(section), 200)


@bp.post("/public-offering-statements/<statement_id>/effectiveness")
def confer_effectiveness(statement_id):
    v.authorize(["StateRegulator"])
    statement = v.get_statement(statement_id)
    project = v.get_project(statement["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(statement, "status",
                    ("SECTIONS_COMPLETE", "AMENDMENT_FILED"))
    package = store.declaration_packages.get(
        statement["declaration_package_id"])
    if package is None or package["status"] != "RECORDED":
        raise ApiError("ERR_DECLARATION_NOT_RECORDED")
    budget = store.initial_budgets.get(statement["initial_budget_id"])
    study = (store.reserve_studies.get(budget["reserve_study_id"])
             if budget is not None else None)
    if (budget is None or budget["status"] != "ADOPTED" or study is None
            or study["adoption_status"] != "ADOPTED"):
        raise ApiError("ERR_RESERVE_STUDY_NOT_ADOPTED")
    if statement["complete_section_count"] != REQUIRED_SECTION_COUNT:
        raise ApiError("ERR_POS_SECTIONS_INCOMPLETE")
    statement["status"] = "EFFECTIVE"
    # `effective_at` records the most recent entry into EFFECTIVE.
    statement["effective_at"] = clock.now()
    store.touch(statement)
    if project["status"] == "REGISTRATION":
        project["status"] = "PRESALE"
        store.touch(project)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(statement), 200)


@bp.post("/public-offering-statements/<statement_id>/amendments")
def file_amendment(statement_id):
    v.authorize(CREATE_ROLES)
    statement = v.get_statement(statement_id)
    project = v.get_project(statement["conversion_project_id"])
    body = v.parse([
        v.field("material_change", "boolean"),
        v.field("amendment_summary", "string", max_len=500),
    ])
    v.gate_not_frozen(project)
    v.require_state(statement, "status", ("EFFECTIVE", "AMENDMENT_REQUIRED"))
    cascades.file_amendment(statement, project, body["material_change"])
    return envelope.object_response(serializers.dump(statement), 201)
