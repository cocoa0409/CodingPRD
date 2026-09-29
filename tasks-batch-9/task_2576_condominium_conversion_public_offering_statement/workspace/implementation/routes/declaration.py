"""The declaration, bylaws and plat package, its units and the interest sweep."""

from flask import Blueprint

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import cascades, interests, projects as project_service

bp = Blueprint("declaration", __name__)

CREATE_ROLES = ["ConverterSponsor"]
READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
              "PlatformAdmin"]
UNIT_CREATE_ROLES = ["ConverterSponsor", "LicensedEngineer"]
UNIT_LIST_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
                   "LicensedEngineer", "PlatformAdmin"]
CERTIFY_ROLES = ["ConverterSponsor", "LicensedEngineer"]
RECORD_ROLES = ["ConverterSponsor", "StateRegulator"]

BOUNDARY_CONVENTIONS = ["PAINT_TO_PAINT", "STUD_TO_STUD", "CENTERLINE"]
TOTAL_BP = 10000
CRITICAL_RUL_YEARS = 5


def life_safety_screen(project):
    """No component of the project's ACCEPTED report may be VERIFIED, flagged
    life-safety and carrying strictly fewer than five remaining years."""
    for report in store.project_reports(project["id"]):
        if report["status"] != "ACCEPTED":
            continue
        for component in store.report_components(report["id"]):
            if (component["verification_status"] == "VERIFIED"
                    and component["is_life_safety"]
                    and component["remaining_useful_life_years"]
                    < CRITICAL_RUL_YEARS):
                raise ApiError("ERR_LIFE_SAFETY_COMPONENT_EXPIRED")


def require_balanced(package):
    if interests.allocated_total(package) != TOTAL_BP:
        raise ApiError("ERR_PERCENTAGE_INTEREST_NOT_BALANCED")


@bp.post("/conversion-projects/<project_id>/declaration-packages")
def create_package(project_id):
    v.authorize(CREATE_ROLES)
    project = v.get_project(project_id)
    body = v.parse([
        v.field("declaration_text_ref", "string", max_len=200),
        v.field("bylaws_text_ref", "string", max_len=200),
        v.field("boundary_convention", "enum", values=BOUNDARY_CONVENTIONS),
    ])
    if store.project_package(project["id"]) is not None:
        # At most one DeclarationPackage per conversion_project_id.
        raise ApiError("ERR_DUPLICATE_KEY")
    v.gate_not_frozen(project)
    package = store.new_record(store.declaration_packages, {
        "_type": "DeclarationPackage",
        "conversion_project_id": project["id"],
        "declaration_text_ref": body["declaration_text_ref"],
        "bylaws_text_ref": body["bylaws_text_ref"],
        "plat_revision": 0,
        "boundary_convention": body["boundary_convention"],
        "status": "DRAFT",
        "recorded_at": None,
        "allocated_bp_total": 0,
    })
    return envelope.object_response(serializers.dump(package), 201)


@bp.get("/conversion-projects/<project_id>/declaration-packages")
def list_packages(project_id):
    v.authorize(READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [p for p in store.children(store.declaration_packages,
                                         "conversion_project_id",
                                         project["id"])
               if v.matches(p, status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/declaration-packages/<package_id>")
def get_package(package_id):
    v.authorize(READ_ROLES)
    package = v.get_package(package_id)
    return envelope.object_response(serializers.dump(package), 200)


@bp.patch("/declaration-packages/<package_id>")
def patch_package(package_id):
    v.authorize(CREATE_ROLES)
    package = v.get_package(package_id)
    project = v.get_project(package["conversion_project_id"])
    body = v.parse([
        v.field("declaration_text_ref", "string", required=False,
                max_len=200),
        v.field("bylaws_text_ref", "string", required=False, max_len=200),
        v.field("boundary_convention", "enum", required=False,
                values=BOUNDARY_CONVENTIONS),
    ])
    v.gate_not_frozen(project)
    v.require_state(package, "status", ("DRAFT",))
    for name in ("declaration_text_ref", "bylaws_text_ref",
                 "boundary_convention"):
        if name in body:
            package[name] = body[name]
    store.touch(package)
    return envelope.object_response(serializers.dump(package), 200)


@bp.post("/declaration-packages/<package_id>/plat-certification")
def certify_plat(package_id):
    v.authorize(CERTIFY_ROLES)
    package = v.get_package(package_id)
    project = v.get_project(package["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(package, "status", ("DRAFT",))
    included = [u for u in store.package_units(package["id"])
                if u["declaration_status"] == "INCLUDED"]
    if not included:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    life_safety_screen(project)
    if project["suitability_gate"] != "PASSED":
        raise ApiError("ERR_SUITABILITY_GATE_FAILED")
    require_balanced(package)
    package["status"] = "PLAT_CERTIFIED"
    store.touch(package)
    interests.reallocate(package)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(package), 200)


@bp.post("/declaration-packages/<package_id>/record")
def record_package(package_id):
    v.authorize(RECORD_ROLES)
    package = v.get_package(package_id)
    project = v.get_project(package["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(package, "status", ("PLAT_CERTIFIED",))
    for household in store.project_households(project["id"]):
        if household["notice_status"] == "PRE_NOTICE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # ERR_RESERVE_STUDY_NOT_ADOPTED is a readiness gate (priority 27) and so
    # precedes the life-safety screen (priority 29).
    adopted = False
    for budget in store.project_budgets(project["id"]):
        if budget["status"] != "ADOPTED":
            continue
        study = store.reserve_studies.get(budget["reserve_study_id"])
        if study is not None and study["adoption_status"] == "ADOPTED":
            adopted = True
            break
    if not adopted:
        raise ApiError("ERR_RESERVE_STUDY_NOT_ADOPTED")
    life_safety_screen(project)
    require_balanced(package)
    instant = clock.now()
    package["status"] = "RECORDED"
    package["recorded_at"] = instant
    store.touch(package)
    project["declaration_recorded_at"] = instant
    project["warranty_start_at"] = instant
    if project["status"] == "DOCUMENTS_PREPARATION":
        project["status"] = "REGISTRATION"
    store.touch(project)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(package), 200)


# --- units inside the package ---------------------------------------------

UNIT_INPUTS = [
    v.field("floor_level", "integer", minimum=-3, maximum=80),
    v.field("heated_square_feet", "integer", minimum=100),
    v.field("boundary_note", "string", max_len=500),
    v.field("base_percentage_interest_bp", "integer", minimum=1,
            maximum=TOTAL_BP),
]


@bp.post("/declaration-packages/<package_id>/units")
def create_unit(package_id):
    v.authorize(UNIT_CREATE_ROLES)
    package = v.get_package(package_id)
    project = v.get_project(package["conversion_project_id"])
    body = v.parse([v.field("unit_number", "string", max_len=100)]
                   + UNIT_INPUTS)
    v.require_unique(store.package_units(package["id"]),
                     unit_number=body["unit_number"])
    v.gate_not_frozen(project)
    unit = store.new_record(store.units, {
        "_type": "Unit",
        "declaration_package_id": package["id"],
        "conversion_project_id": package["conversion_project_id"],
        "unit_number": body["unit_number"],
        "floor_level": body["floor_level"],
        "heated_square_feet": body["heated_square_feet"],
        "boundary_note": body["boundary_note"],
        "base_percentage_interest_bp": body["base_percentage_interest_bp"],
        # Seeded from the declared basis until the next sweep overwrites it.
        "percentage_interest_bp": body["base_percentage_interest_bp"],
        "unit_annual_assessment_cents": 0,
        "unit_monthly_assessment_cents": 0,
        "declaration_status": "INCLUDED",
        "sale_status": "UNSOLD",
        "withdrawal_reason": None,
    })
    # Defining a unit is a structural change to an already certified plat.
    cascades.revert_plat(package)
    project_service.sync(project)
    return envelope.object_response(serializers.dump(unit), 201)


@bp.get("/declaration-packages/<package_id>/units")
def list_package_units(package_id):
    v.authorize(UNIT_LIST_ROLES)
    package = v.get_package(package_id)
    limit, offset = v.pagination()
    records = [
        u for u in store.package_units(package["id"])
        if v.matches(u,
                     declaration_status=v.filter_value("declaration_status"),
                     sale_status=v.filter_value("sale_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/declaration-packages/<package_id>/assessment-allocation")
def assessment_allocation(package_id):
    v.authorize(READ_ROLES)
    package = v.get_package(package_id)
    included = [u for u in store.package_units(package["id"])
                if u["declaration_status"] == "INCLUDED"]
    return envelope.array_response(serializers.dump_all(included), 200)
