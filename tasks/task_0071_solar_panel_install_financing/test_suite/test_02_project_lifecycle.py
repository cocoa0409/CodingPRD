"""Project state machine: transitions, cycles, invalid-state guards, versioning."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assess_payload, design_payload, create_project_payload,
    make_homeowner_headers, make_installer_headers,
    register_homeowner, register_installer,
    create_requested_project, create_assessed_project, create_designed_project,
    create_active_plan, drive_to_installed, setup_operational_project,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Corner: state machine basics ---

def test_project_initial_state_is_requested(api):
    """PRD 3.2: "The project is born in REQUESTED status with an empty
    installer_id, and all of its computed economics ... start at their zero or
    null defaults until later stages fill them in."

    Design: Corner/state_machines/project_initial_state_is_requested
    """
    homeowner, project = create_requested_project()
    assert project["status"] == "REQUESTED"


def test_assess_from_designed_returns_invalid_state(api):
    """PRD 3.2: "An assessment attempted on a project not in REQUESTED is rejected
    as an invalid state."

    Design: Corner/state_machines/assess_from_designed_returns_invalid_state
    """
    homeowner, installer, project = create_designed_project()
    inst_headers = make_installer_headers(installer["id"])
    resp = api.assess_project(
        project["id"], assess_payload(shading_factor=0.20, peak_sun_hours=4.0),
        inst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_design_by_unlicensed_installer_rejected(api):
    """PRD 3.2: "the acting installer must be licensed in the homeowner's state —
    that is, the homeowner's state_code must appear in the installer's
    licensed_states, failing which the request is rejected with
    ERR_INSTALLER_NOT_LICENSED (HTTP 422)."

    Design: Corner/state_machines/design_install_not_licensed_in_state
    """
    homeowner = register_homeowner(state_code="CA")
    installer = register_installer(licensed_states=["TX"], company_name="TxOnly")
    homeowner, installer, project = create_assessed_project(
        homeowner=homeowner, installer=installer,
    )
    inst_headers = make_installer_headers(installer["id"])
    resp = api.design_project(
        project["id"],
        design_payload(installer_id=installer["id"], gross_system_cost_cents=3000000),
        inst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSTALLER_NOT_LICENSED, 422)


def test_design_infeasible_zero_sun_hours(api):
    """PRD 3.2: "If peak_sun_hours is zero, or if the shading factor is exactly
    1.0 (leaving no usable irradiance), system size is undefined and the request
    is rejected with ERR_DESIGN_INFEASIBLE (HTTP 422)."

    Design: Corner/state_machines/design_infeasible_zero_sun_hours
    """
    homeowner, installer, project = create_assessed_project(
        shading_factor=0.10, peak_sun_hours=0.0,
    )
    inst_headers = make_installer_headers(installer["id"])
    resp = api.design_project(
        project["id"],
        design_payload(installer_id=installer["id"], gross_system_cost_cents=3000000),
        inst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_INFEASIBLE, 422)


def test_submit_permit_without_active_financing_rejected(api):
    """PRD 3.6: "The SolarInstaller submits the permit package, moving the project
    from DESIGNED to PERMIT_PENDING; this requires that the project carry a
    non-null financing_plan_id whose plan is in ACTIVE status."

    Design: Corner/state_machines/submit_permit_without_active_financing_rejected
    """
    homeowner, installer, project = create_designed_project()
    # A DRAFT plan exists but is never activated.
    from test_helpers import create_draft_plan
    create_draft_plan(homeowner, project, model="LEASE")
    inst_headers = make_installer_headers(installer["id"])
    resp = api.submit_permit(project["id"], inst_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_cancel_operational_project_terminal_lockdown(api):
    """PRD 3.6: "A Homeowner who owns a project may cancel it while it remains in
    REQUESTED, ASSESSED, or DESIGNED."

    Design: Corner/state_machines/cancel_operational_project_terminal_lockdown
    """
    ctx = setup_operational_project()
    resp = api.cancel_project(ctx["project"]["id"], ctx["ho_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# --- Difficulty: non_linear_state_machine ---

def test_failed_inspection_remediation_returns_to_installed(api):
    """PRD 3.6: "From a failure the assigned installer begins remediation, moving
    FAILED_INSPECTION to REMEDIATION, and then completes the install again to
    return REMEDIATION to INSTALLED, re-entering the inspection branch."

    Design: Difficulty/non_linear_state_machine/project_failed_inspection_remediation_cycle
    """
    homeowner, installer, project, plan = create_active_plan(model="LEASE")
    inst_headers = make_installer_headers(installer["id"])
    drive_to_installed(homeowner, installer, project)
    get_success_data(api.inspect_project(project["id"], {"result": "FAIL"}, ADMIN))
    get_success_data(api.start_remediation(project["id"], inst_headers))
    resp = api.complete_install(project["id"], inst_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "INSTALLED"


def test_failed_inspection_sets_failed_inspection_state(api):
    """PRD 3.6: "A passing inspection advances the project from INSTALLED to
    PTO_PENDING; a failing inspection sends it from INSTALLED to
    FAILED_INSPECTION."

    Design: Difficulty/non_linear_state_machine/project_failed_inspection_remediation_cycle
    """
    homeowner, installer, project, plan = create_active_plan(model="LEASE")
    inst_headers = make_installer_headers(installer["id"])
    drive_to_installed(homeowner, installer, project)
    resp = api.inspect_project(project["id"], {"result": "FAIL"}, ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "FAILED_INSPECTION"


# --- Difficulty: version increments (cross_cutting OCC corner uses this too) ---

def test_version_increments_on_each_project_mutation(api):
    """PRD 2.4: "The version begins at 1 on creation and increments by exactly 1
    on every mutation, including mutations that arrive as a cascade from an
    operation on another resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_project_mutation
    """
    homeowner, installer, project = create_assessed_project()
    inst_headers = make_installer_headers(installer["id"])
    resp = api.design_project(
        project["id"],
        design_payload(installer_id=installer["id"], gross_system_cost_cents=3000000),
        inst_headers,
    )
    data = validate_success(resp, 200)
    # create -> 1, assess -> 2, design -> 3
    assert data["version"] == 3
