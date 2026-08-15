"""Queue B validations & errors: auth context, uniqueness gates, window gates,
program gates, fiscal gates (PRD §2.7, §3.2–§3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_completed_survey,
    create_grant_application_payload,
    create_grant_program,
    create_grant_program_payload,
    create_install_complete_project,
    create_project_draft,
    create_project_payload,
    create_quoted_project,
    create_registered_project,
    create_technician,
    create_unit_with_contract,
    create_service_call,
    factories,
    get_success_data,
    make_homeowner_headers,
    make_installer_headers,
    validate_error,
    validate_paginated,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]


# ===========================================================================
# Queue B — Corner/validations/request_with_unknown_role_unauthenticated
# ===========================================================================

def test_request_with_unknown_role_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system does
    not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/request_with_unknown_role_unauthenticated
    """
    resp = api.create_property(
        factories.create_property_payload(),
        build_user_headers("u-own-1", "SuperUser"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# ===========================================================================
# Queue B — Corner/validations/duplicate_serial_number_rejected
# ===========================================================================

def test_duplicate_serial_number_rejected(api):
    """PRD §3.5: "the supplied `serial_number` must be unique across every elevator unit
    in the system (`ERR_SERIAL_NUMBER_TAKEN`)."

    Design: Corner/validations/duplicate_serial_number_rejected
    """
    ctx1 = create_install_complete_project(serial_number="SN-100",
                                           prop_overrides={"address_line": "1 Pine St"})
    # Second project INSTALL_SCHEDULED with the clock inside its window.
    ctx2 = create_quoted_project(prop_overrides={"address_line": "2 Oak Ave"})
    permit2 = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx2["project"]["id"]), COORD))
    get_success_data(api.approve_permit(permit2["id"], REGULATOR))
    get_success_data(api.schedule_installation(
        ctx2["project"]["id"],
        {"install_start_date": "2026-08-12T08:00:00Z",
         "install_end_date": "2026-08-20T17:00:00Z"}, COORD))
    # Clock already 2026-08-12T09:00 from the first project's completion.
    resp = api.complete_installation(
        ctx2["project"]["id"], {"serial_number": "SN-100"},
        make_installer_headers(ctx2["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SERIAL_NUMBER_TAKEN)
    project2 = get_success_data(api.get_project(ctx2["project"]["id"], COORD))
    assert project2["status"] == "INSTALL_SCHEDULED"
    units, _meta = validate_paginated(api.list_units(COORD, params={"project_id": project2["id"]}))
    assert units == []


# ===========================================================================
# Queue B — Corner/validations/second_open_permit_rejected
# ===========================================================================

def test_second_open_permit_rejected(api):
    """PRD §3.3: "the project must not already carry a non-terminal permit application
    (`ERR_OPEN_PERMIT_EXISTS`)."
    PRD §3.3: "Filing is allowed while the project is in `QUOTED`, `PERMIT_APPROVED`,
    or `READY_FOR_INSTALL`" — so the uniqueness gate (§2.7 item 9) is reached only
    when the project sits in one of those states with an APPROVED (non-terminal)
    permit still on file; filing again then trips `ERR_OPEN_PERMIT_EXISTS`.

    Design: Corner/validations/second_open_permit_rejected
    """
    ctx = create_quoted_project()
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    # Approve the first permit: the no-structural project lands in READY_FOR_INSTALL,
    # a filing-admissible state, while the APPROVED permit remains non-terminal.
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    resp = api.create_permit(factories.create_permit_payload(ctx["project"]["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_OPEN_PERMIT_EXISTS)
    permits, _meta = validate_paginated(
        api.list_permits(COORD, params={"project_id": ctx["project"]["id"]}))
    assert len(permits) == 1


# ===========================================================================
# Queue B — Corner/validations/second_live_contract_rejected
# ===========================================================================

def test_second_live_contract_rejected(api):
    """PRD §3.7: "Activation requires the unit's `equipment_status` to be `IN_SERVICE`
    (`ERR_UNIT_NOT_IN_SERVICE`) and no other `ACTIVE` or `SUSPENDED` contract on the
    same unit (`ERR_CONTRACT_ALREADY_EXISTS`)".

    Design: Corner/validations/second_live_contract_rejected
    """
    ctx = create_unit_with_contract(tier="STANDARD")  # first contract ACTIVE
    second = get_success_data(api.create_service_contract(
        factories.create_service_contract_payload(ctx["unit"]["id"], tier="PREMIUM"), COORD))
    resp = api.activate_service_contract(second["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_ALREADY_EXISTS)
    second = get_success_data(api.get_service_contract(second["id"], COORD))
    assert second["status"] == "DRAFT"


# ===========================================================================
# Queue B — Corner/validations/duplicate_grant_application_rejected
# ===========================================================================

def test_duplicate_grant_application_rejected(api):
    """PRD §3.8: "no existing `SUBMITTED` or `APPROVED` application for the same project
    and program pair (`ERR_DUPLICATE_APPLICATION`)".

    Design: Corner/validations/duplicate_grant_application_rejected
    """
    ctx = create_quoted_project()
    program = create_grant_program()
    owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
    get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]), owner))
    resp = api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]), owner)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)


# ===========================================================================
# Queue B — Corner/validations/application_outside_window_rejected
# ===========================================================================

def test_application_outside_window_rejected(api):
    """PRD §3.8: "Submission requires the clock to fall within the program's inclusive
    application window (`ERR_APPLICATION_WINDOW_CLOSED`)".

    Design: Corner/validations/application_outside_window_rejected
    """
    ctx = create_quoted_project()
    program = create_grant_program(program_name="FallGrant",
                                   application_open_date="2026-09-01T00:00:00Z")
    # Default logical clock 2026-08-01 precedes the open date.
    resp = api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]),
        make_homeowner_headers(ctx["prop"]["owner_user_id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED)


# ===========================================================================
# Queue B — Corner/validations/paused_program_blocks_submission
# ===========================================================================

def test_paused_program_blocks_submission(api):
    """PRD §3.8: "Submission requires ... the program to be `OPEN`
    (`ERR_PROGRAM_NOT_OPEN`)".
    PRD §3.8: "An administrator may pause and resume a program".

    Design: Corner/validations/paused_program_blocks_submission
    """
    ctx = create_quoted_project()
    program = create_grant_program()
    get_success_data(api.pause_grant_program(program["id"], ADMIN))
    owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
    resp = api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]), owner)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)
    get_success_data(api.resume_grant_program(program["id"], ADMIN))
    app = get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]), owner))
    assert app["status"] == "SUBMITTED"


# ===========================================================================
# Queue B — Corner/validations/ineligible_project_type_rejected
# ===========================================================================

def test_ineligible_project_type_rejected(api):
    """PRD §3.8: "Submission requires the clock to fall within the program's inclusive
    application window (`ERR_APPLICATION_WINDOW_CLOSED`), the program to be `OPEN`
    (`ERR_PROGRAM_NOT_OPEN`), the project's `project_type` to appear in the program's
    `eligible_project_types` (`ERR_PROJECT_TYPE_INELIGIBLE`)".

    Design: Corner/validations/ineligible_project_type_rejected
    """
    ctx = create_quoted_project()  # NEW_INSTALLATION project
    program = create_grant_program(program_name="ModOnly",
                                   eligible_project_types=["MODERNIZATION"])
    resp = api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]),
        make_homeowner_headers(ctx["prop"]["owner_user_id"]))
    validate_error(resp, ApiErrorId.ERR_PROJECT_TYPE_INELIGIBLE)


# ===========================================================================
# Queue B — Corner/validations/verified_income_over_cap_rejected
# ===========================================================================

def test_verified_income_over_cap_rejected(api):
    """PRD §3.8: "the verified income must not exceed the `income_cap`
    (`ERR_VERIFIED_INCOME_INELIGIBLE`)".

    Design: Corner/validations/verified_income_over_cap_rejected
    """
    ctx = create_quoted_project()
    program = create_grant_program()
    app = get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]),
        make_homeowner_headers(ctx["prop"]["owner_user_id"])))
    resp = api.approve_grant_application(app["id"], {"verified_income": 61000.00}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_VERIFIED_INCOME_INELIGIBLE)
    app = get_success_data(api.get_grant_application(app["id"], OFFICER))
    assert app["status"] == "SUBMITTED"
    program = get_success_data(api.get_grant_program(program["id"], OFFICER))
    assert program["remaining_pool"] == 50000.00


# ===========================================================================
# Queue B — Corner/validations/survey_not_completed_blocks_project
# ===========================================================================

def test_survey_not_completed_blocks_project(api):
    """PRD §3.2: "The survey must be `COMPLETED`, or creation fails with
    `ERR_SURVEY_NOT_COMPLETED`".

    Design: Corner/validations/survey_not_completed_blocks_project
    """
    prop = get_success_data(api.create_property(factories.create_property_payload(), COORD))
    surveyor = create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
    survey = get_success_data(api.create_survey(
        factories.create_survey_payload(prop["id"], surveyor["id"]), COORD))
    assert survey["status"] == "SCHEDULED"
    resp = api.create_project(create_project_payload(prop["id"], survey["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_COMPLETED)


# ===========================================================================
# Queue B — Corner/validations/discontinued_model_blocks_selection
# ===========================================================================

def test_discontinued_model_blocks_selection(api):
    """PRD §3.2: "The referenced model must still be `ACTIVE`
    (`ERR_MODEL_DISCONTINUED`)."

    Design: Corner/validations/discontinued_model_blocks_selection
    """
    ctx = create_project_draft()
    model = get_success_data(api.create_product_model(
        factories.create_product_model_payload(model_code="HYD-100"), ADMIN))
    get_success_data(api.discontinue_product_model(model["id"], ADMIN))
    resp = api.update_project(ctx["project"]["id"],
        factories.select_product_payload(model["id"], ctx["installer"]["id"],
                                         ctx["project"]["version"]), COORD)
    validate_error(resp, ApiErrorId.ERR_MODEL_DISCONTINUED)
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["status"] == "DRAFT"
