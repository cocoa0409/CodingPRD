"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build preconditions from scratch using
only PRD-declared endpoints. Setup calls use the lenient get_success_data()
validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_contractor_headers,
    make_homeowner_headers,
    make_inspector_headers,
    make_installer_headers,
    make_surveyor_headers,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
OWNER = TEST_USERS["homeowner_headers"]


# ---------------------------------------------------------------------------
# Tier 0: leaf resources
# ---------------------------------------------------------------------------

def create_property(**overrides):
    """Create a property. Returns the property dict."""
    return get_success_data(api_client.create_property(factories.create_property_payload(**overrides), COORD))


def create_technician(name="Tech", certification="CET_AND_QEI", region="north"):
    return get_success_data(api_client.create_technician(
        factories.create_technician_payload(full_name=name, certification=certification, home_region=region),
        ADMIN,
    ))


def create_contractor(**overrides):
    return get_success_data(api_client.create_contractor(factories.create_contractor_payload(**overrides), ADMIN))


def create_product_model(**overrides):
    return get_success_data(api_client.create_product_model(factories.create_product_model_payload(**overrides), ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_grant_program(**overrides):
    return get_success_data(api_client.create_grant_program(factories.create_grant_program_payload(**overrides), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: survey and project progression
# ---------------------------------------------------------------------------

def create_completed_survey(prop_id=None, surveyor=None, models=None, prop_overrides=None,
                            **complete_overrides):
    """Property + ACTIVE surveyor + catalog models + COMPLETED survey.

    Returns (prop, surveyor, survey). When models is None the default HYD-100
    catalog model (12/96 pit/overhead minimums) is created so the verdict is
    computable; pass models=[] explicitly to create no catalog model.
    prop_overrides, when given, is forwarded to create_property.
    """
    prop = prop_id and {"id": prop_id} or create_property(**(prop_overrides or {}))
    surveyor = surveyor or create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
    if models is None:
        create_product_model()
    elif models:
        for m in models:
            create_product_model(**m)
    survey = get_success_data(api_client.create_survey(
        factories.create_survey_payload(prop["id"], surveyor["id"]), COORD))
    completed = get_success_data(api_client.complete_survey(
        survey["id"],
        factories.complete_survey_payload(**complete_overrides),
        make_surveyor_headers(surveyor["id"]),
    ))
    return prop, surveyor, completed


def create_project_draft(prop=None, survey=None, project_type="NEW_INSTALLATION",
                         modernize_unit_id=None, models=None, prop_overrides=None,
                         **complete_overrides):
    """Property + completed survey + project in DRAFT.

    Returns dict with keys: prop, surveyor, survey, project, installer,
    (contractor when created). prop_overrides, when given, is forwarded to
    create_property via create_completed_survey.
    """
    installer = create_technician(name="Ivy Installer", certification="CET")
    if survey is None:
        prop, surveyor, survey = create_completed_survey(
            models=models, prop_overrides=prop_overrides, **complete_overrides)
    else:
        surveyor = create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
        prop = prop or {"id": survey["property_id"]}
    payload = factories.create_project_payload(
        prop["id"], survey["id"], project_type=project_type)
    if modernize_unit_id is not None:
        payload["modernize_unit_id"] = modernize_unit_id
    project = get_success_data(api_client.create_project(payload, COORD))
    return {
        "prop": prop, "surveyor": surveyor, "survey": survey,
        "project": project, "installer": installer,
    }


def create_quoted_project(model_overrides=None, contractor=False, survey_overrides=None,
                          prop_overrides=None, project_type="NEW_INSTALLATION",
                          modernize_unit_id=None, create_model=True):
    """Project advanced to QUOTED via a valid product selection.

    Returns dict with prop, surveyor, survey, installer, project (post-PATCH),
    model, and contractor when requested.
    """
    prop = create_property(**(prop_overrides or {}))
    surveyor = create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
    installer = create_technician(name="Ivy Installer", certification="CET")
    model = create_product_model(**(model_overrides or {})) if create_model else None
    survey = get_success_data(api_client.create_survey(
        factories.create_survey_payload(prop["id"], surveyor["id"]), COORD))
    survey = get_success_data(api_client.complete_survey(
        survey["id"], factories.complete_survey_payload(**(survey_overrides or {})),
        make_surveyor_headers(surveyor["id"])))
    payload = factories.create_project_payload(prop["id"], survey["id"], project_type=project_type)
    if modernize_unit_id is not None:
        payload["modernize_unit_id"] = modernize_unit_id
    project = get_success_data(api_client.create_project(payload, COORD))
    gc = create_contractor() if contractor else None
    patch = factories.select_product_payload(model["id"], installer["id"], project["version"])
    if gc is not None:
        patch["contractor_id"] = gc["id"]
    project = get_success_data(api_client.update_project(project["id"], patch, COORD))
    return {
        "prop": prop, "surveyor": surveyor, "survey": survey, "installer": installer,
        "model": model, "project": project, "contractor": gc,
    }


# ---------------------------------------------------------------------------
# Tier 2: permit and work-order progression
# ---------------------------------------------------------------------------

def approve_permit_for(ctx):
    """File a permit on ctx's QUOTED project and approve it.

    Returns (project, permit) after approval. A no-structural project
    auto-advances to READY_FOR_INSTALL; a structural one stops at
    PERMIT_APPROVED.
    """
    permit = get_success_data(api_client.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    permit = get_success_data(api_client.approve_permit(permit["id"], REGULATOR))
    project = get_success_data(api_client.get_project(ctx["project"]["id"], COORD))
    ctx["project"] = project
    ctx["permit"] = permit
    return ctx


def create_permit_approved_project(**kwargs):
    """Quoted project + approved permit. Returns the context dict."""
    ctx = create_quoted_project(**kwargs)
    return approve_permit_for(ctx)


def create_ready_for_install_project(**kwargs):
    """Project at READY_FOR_INSTALL.

    Without structural need the permit approval auto-advances; with structural
    need a work order is released, completed (actual == estimate), and verified.
    """
    ctx = create_permit_approved_project(**kwargs)
    if ctx["project"]["status"] == "PERMIT_APPROVED" and ctx["project"].get("requires_structural"):
        complete_structural_branch(ctx)
        ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], COORD))
    return ctx


def complete_structural_branch(ctx, actual_cost=None):
    """Create + release + complete-work + verify the structural work order.

    ctx must have project in PERMIT_APPROVED with requires_structural true and
    a contractor recorded. Mutates and returns ctx with work_order filled in.
    """
    wo = get_success_data(api_client.create_work_order(
        factories.create_work_order_payload(ctx["project"]["id"], ctx["contractor"]["id"]), COORD))
    wo = get_success_data(api_client.release_work_order(wo["id"], COORD))
    cost = ctx["project"]["structural_estimate"] if actual_cost is None else actual_cost
    wo = get_success_data(api_client.complete_work_order(
        wo["id"], {"actual_cost": cost}, make_contractor_headers(ctx["contractor"]["id"])))
    wo = get_success_data(api_client.verify_work_order(wo["id"], COORD))
    ctx["work_order"] = wo
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle (unit exists / registered / in service)
# ---------------------------------------------------------------------------

def create_install_complete_project(serial_number=None, **kwargs):
    """Project driven to INSTALL_COMPLETE; the ElevatorUnit exists.

    Returns ctx with project, unit, and all upstream entities.
    """
    ctx = create_ready_for_install_project(**kwargs)
    get_success_data(api_client.schedule_installation(
        ctx["project"]["id"], factories.schedule_installation_payload(), COORD))
    set_clock("2026-08-12T09:00:00Z")
    payload = factories.complete_installation_payload()
    if serial_number is not None:
        payload["serial_number"] = serial_number
    project = get_success_data(api_client.complete_installation(
        ctx["project"]["id"], payload, make_installer_headers(ctx["installer"]["id"])))
    units, _meta = _list_units_for_project(project["id"])
    ctx["project"] = project
    ctx["unit"] = units[0]
    return ctx


def _list_units_for_project(project_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_units(COORD, params={"project_id": project_id}))


def create_acceptance_passed_project(inspection_type="ACCEPTANCE", **kwargs):
    """INSTALL_COMPLETE project whose acceptance inspection has PASSED.

    Returns ctx with inspection recorded; project is AWAITING_REGISTRATION.
    """
    ctx = create_install_complete_project(**kwargs)
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    insp = get_success_data(api_client.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], inspector["id"],
            inspection_type=inspection_type, project_id=ctx["project"]["id"]),
        COORD))
    set_clock("2026-08-12T10:05:00Z")
    insp = get_success_data(api_client.record_inspection_result(
        insp["id"], {"result": "PASSED"}, make_inspector_headers(inspector["id"])))
    ctx["inspector"] = inspector
    ctx["inspection"] = insp
    ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], COORD))
    return ctx


def create_registered_project(**kwargs):
    """Project driven to REGISTERED: unit IN_SERVICE/REGISTERED, cert ACTIVE.

    Returns ctx with certificate included.
    """
    ctx = create_acceptance_passed_project(**kwargs)
    cert = get_success_data(api_client.create_certificate(
        factories.create_certificate_payload(ctx["unit"]["id"]), COORD))
    cert = get_success_data(api_client.issue_certificate(cert["id"], REGULATOR))
    ctx["certificate"] = cert
    ctx["unit"] = get_success_data(api_client.get_unit(ctx["unit"]["id"], COORD))
    ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], COORD))
    return ctx


def create_closed_project(**kwargs):
    """Project driven to CLOSED. Returns ctx."""
    ctx = create_registered_project(**kwargs)
    project = get_success_data(api_client.close_project(ctx["project"]["id"], COORD))
    ctx["project"] = project
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: service domain (contracts and calls on an in-service unit)
# ---------------------------------------------------------------------------

def create_unit_with_contract(tier="STANDARD", activate=True, **kwargs):
    """Registered unit + a service contract (ACTIVE by default). Returns ctx."""
    ctx = create_registered_project(**kwargs)
    contract = get_success_data(api_client.create_service_contract(
        factories.create_service_contract_payload(ctx["unit"]["id"], tier=tier), COORD))
    if activate:
        contract = get_success_data(api_client.activate_service_contract(contract["id"], COORD))
    ctx["contract"] = contract
    return ctx


def create_service_call(ctx, call_type="REPAIR", description=None, homeowner_id=None):
    payload = factories.create_service_call_payload(ctx["unit"]["id"], call_type=call_type)
    if description is not None:
        payload["description"] = description
    return get_success_data(api_client.create_service_call(
        payload, make_homeowner_headers(homeowner_id or ctx["prop"]["owner_user_id"])))


def create_dispatched_call(ctx, call_type="REPAIR", technician=None, description=None):
    """Create a service call and dispatch it. Returns the DISPATCHED call."""
    call = create_service_call(ctx, call_type=call_type, description=description)
    tech = technician or ctx["installer"]
    return get_success_data(api_client.dispatch_service_call(
        call["id"], {"technician_id": tech["id"]}, COORD))


# ---------------------------------------------------------------------------
# Tier 5: grant domain
# ---------------------------------------------------------------------------

def create_grant_application(ctx, program, household_income=42000.00, homeowner_id=None):
    return get_success_data(api_client.create_grant_application(
        factories.create_grant_application_payload(
            ctx["project"]["id"], program["id"], household_income=household_income),
        make_homeowner_headers(homeowner_id or ctx["prop"]["owner_user_id"])))


def create_approved_application(ctx, program, household_income=42000.00):
    app = create_grant_application(ctx, program, household_income=household_income)
    return get_success_data(api_client.approve_grant_application(
        app["id"], {"verified_income": household_income}, OFFICER))
