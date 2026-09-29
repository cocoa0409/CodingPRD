"""State machines: declared initial states and operations repeated from a settled state."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]


def test_four_machines_seeded_in_one_chain_land_on_their_declared_initial_states(api):
    """The first disconnection is the one initial state that immediately moves its parent.

    "It opens in `status` `ACTIVE` at `version` 1 with `active_work_order_count` 0."

    "The work order opens in `status` `ISSUED` at `version` 1 with
    `failed_inspection_count` 0, `required_utility_types` copied as the four values
    `WATER`, `ELECTRIC`, `GAS` and `SEWER`, `confirmed_utility_types` an empty
    array."

    "The disconnection opens in `status` `PENDING` at `version` 1 with
    `failed_attempt_count` 0 and `confirmation_reference` and `resolved_at` null.
    Creating the **first** child moves the parent work order from `ISSUED` to
    `UTILITY_HOLD` and advances the parent's `version` by 1."

    "The case opens in `status` `OPENED` at `version` 1 with `appeal_count` 0,
    `denial_reason` and `appeal_basis` null, `rental_assistance_end_date` null, and
    every computed benefit field at 0."

    Design: Corner/state_machines/newly_created_lifecycle_rows_start_in_their_declared_initial_states
    """
    api.set_clock("2026-08-01T00:00:00Z")

    project = fixtures.create_draft_project(api, grant_program="FMA")
    parcel = fixtures.create_parcel(
        api, project, apn="APN-SM-INIT", site_address="2101 River Rd"
    )

    contractor = fixtures.create_contractor(
        api, name="Riverbend Wrecking", license_no="DEM-1",
        asbestos_certified=True, max_concurrent_work_orders=2,
    )
    assert contractor["status"] == "ACTIVE"
    assert contractor["version"] == 1
    assert contractor["active_work_order_count"] == 0

    work_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"],
        asbestos_survey_status="CLEARED",
        scheduled_start="2026-09-01T08:00:00Z",
        scheduled_end="2026-09-03T17:00:00Z",
    )
    assert work_order["status"] == "ISSUED"
    assert work_order["required_utility_types"] == ["WATER", "ELECTRIC", "GAS", "SEWER"]
    assert work_order["confirmed_utility_types"] == []
    assert work_order["failed_inspection_count"] == 0

    disconnection = validate_success(
        api.create_utility_disconnection(
            work_order["id"],
            factories.create_utility_disconnection_payload(
                work_order["id"], "WATER", provider_name="Riverbend Water Authority"
            ),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        201,
    )
    assert disconnection["status"] == "PENDING"
    assert disconnection["failed_attempt_count"] == 0
    assert disconnection["resolved_at"] is None

    case = fixtures.open_relocation_case(
        api, parcel["id"], household_reference="HH-SM-INIT",
        comparable_dwelling_price_cents=20_600_000,
    )
    assert case["status"] == "OPENED"
    assert case["appeal_count"] == 0
    assert case["total_relocation_benefit_cents"] == 0
    assert case["rental_assistance_end_date"] is None

    parent = validate_success(api.get_demolition_work_order(work_order["id"], ADMIN))
    assert parent["status"] == "UTILITY_HOLD"

    refreshed = validate_success(
        api.get_demolition_contractor(contractor["id"], ADMIN)
    )
    assert refreshed["active_work_order_count"] == 1


def _approve(api, project_id):
    return api.approve_mitigation_project(
        project_id,
        factories.approve_project_payload(project_id, "APPROVE"),
        TEST_USERS["project_approver_headers"],
    )


def test_the_draft_project_refuses_approval_return_and_a_ledger_posting_alike(api):
    """Three unrelated writes against one DRAFT project share a single error id.

    "A `ProgramAdministrator` renders a `decision` of `APPROVE` or `DENY` on a
    project in `SUBMITTED`, optionally with a `decision_note`."

    "A `ProgramAdministrator` may return a submitted project for revision with a
    `return_reason`, moving `SUBMITTED` back to `DRAFT` and advancing the project's
    `version` by 1."

    "The project's `status` must be `APPROVED`, `CLOSEOUT_PENDING` or `CLOSED_OUT`,
    otherwise `ERR_INVALID_PROJECT_STATE`; a `DRAFT`, `SUBMITTED` or `DENIED`
    project has no ledger."

    Design: Corner/state_machines/project_transitions_from_the_wrong_status_return_invalid_project_state
    """
    api.set_clock("2026-08-01T00:00:00Z")
    project = fixtures.create_draft_project(api, grant_program="FMA")
    assert project["status"] == "DRAFT"

    validate_error(
        _approve(api, project["id"]),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    validate_error(
        api.return_mitigation_project(
            project["id"],
            {"project_id": project["id"], "return_reason": "premature"},
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    validate_error(
        api.create_program_income_entry(
            project["id"],
            factories.create_program_income_entry_payload(
                project["id"], project["version"],
                entry_type="LEASE_REVENUE", amount_cents=100_000,
                posted_on="2026-08-01",
            ),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    still_draft = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["program_income_balance_cents"] == 0


def test_a_second_submit_and_a_premature_closeout_are_refused_from_submitted(api):
    """The same identifier answers a repeat of the transition that produced the state.

    "Submission requires the project to be in `DRAFT`, to carry at least one
    `BenefitCostAnalysis` in `status` `SUBMITTED`, and to carry at least one
    `Parcel`; a project that fails any of these three conditions is not in a
    submittable posture and the request is refused with
    `ERR_INVALID_PROJECT_STATE`."

    "`INITIATE` requires the project's `status` to be `APPROVED`, otherwise
    `ERR_INVALID_PROJECT_STATE`."

    Design: Corner/state_machines/project_transitions_from_the_wrong_status_return_invalid_project_state
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_submitted_project(api, project_overrides={"grant_program": "FMA"})
    assert state["project"]["status"] == "SUBMITTED"

    validate_error(
        api.submit_mitigation_project(
            state["project"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    validate_error(
        api.closeout_mitigation_project(
            state["project"]["id"],
            factories.closeout_payload(state["project"]["id"], "INITIATE"),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["status"] == "SUBMITTED"


def test_the_child_creation_gate_closes_the_moment_the_project_is_approved(api):
    """A parcel create that was legal one call earlier is refused after approval.

    "A `SubrecipientCoordinator` registers each candidate property as a `Parcel`
    while the project is in `DRAFT` or `SUBMITTED`; in any other project state this
    is `ERR_INVALID_PROJECT_STATE`."

    "On approval the project moves to `APPROVED`, the whole neighborhood-viability
    family (`participating_parcel_count`, `holdout_parcel_count`,
    `contiguous_open_space_parcel_count`, `largest_component_parcel_ids`,
    `neighborhood_viability_ratio`, `viability_status`) is recomputed, and the
    project's `version` advances by 1."

    Design: Corner/state_machines/project_transitions_from_the_wrong_status_return_invalid_project_state
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_validated_project(api, project_overrides={"grant_program": "FMA"})

    project = validate_success(_approve(api, state["project"]["id"]))
    assert project["status"] == "APPROVED"
    assert float(project["validated_bcr"]) == 2.667

    validate_error(
        api.create_parcel(
            project["id"],
            factories.create_parcel_payload(
                project["id"], apn="APN-SM-PROJ-2", site_address="2202 River Rd",
                acreage=0.41, occupancy_type="VACANT", structure_type="NONE",
            ),
            make_subrecipient_coordinator_headers(project["id"]),
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
        409,
    )

    parcels, meta = validate_paginated(
        api.list_parcels(ADMIN, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 1
    assert len(parcels) == 1


def test_validating_an_already_validated_analysis_reports_the_bca_state(api):
    """The second VALIDATE finds the analysis in a terminal state, not the project.

    "A `ProgramAdministrator` renders a `decision` of `VALIDATE` or `REJECT` on a
    specific analysis, optionally with a `review_note`. The analysis must be in
    `SUBMITTED`, otherwise `ERR_INVALID_BCA_STATE`, and the project must be in
    `SUBMITTED`, otherwise `ERR_INVALID_PROJECT_STATE`."

    "An analysis's `status` runs `SUBMITTED` to either `VALIDATED` or `REJECTED`,
    both of which are terminal."

    Design: Corner/state_machines/bca_validation_and_appraisal_decisions_repeated_from_a_settled_state_are_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_validated_project(api, project_overrides={"grant_program": "FMA"})
    assert state["bca"]["status"] == "VALIDATED"
    assert state["project"]["status"] == "SUBMITTED"

    validate_error(
        api.validate_benefit_cost_analysis(
            state["bca"]["id"],
            factories.validate_bca_payload(state["bca"]["id"], "VALIDATE"),
            TEST_USERS["bca_validator_headers"],
        ),
        ApiErrorId.ERR_INVALID_BCA_STATE.value,
        409,
    )

    bca = validate_success(
        api.get_benefit_cost_analysis(state["bca"]["id"], ADMIN)
    )
    assert bca["status"] == "VALIDATED"
    assert float(bca["bcr"]) == 2.667


def test_resubmitting_and_re_accepting_one_appraisal_both_report_the_appraisal_state(api):
    """Two different operations, each repeated once, land on the same error id.

    "Submission is admitted from `DRAFT` and from `RETURNED_FOR_REVISION`; from any
    other state it is `ERR_INVALID_APPRAISAL_STATE`."

    "`ACCEPT` is admitted only from `SUBMITTED`; an accept attempted against an
    appraisal in `RETURNED_FOR_REVISION` is `ERR_INVALID_APPRAISAL_STATE`."

    "Accepting an `INITIAL` appraisal moves nothing but the appraisal itself to
    `ACCEPTED` with `version` advanced by 1."

    Design: Corner/state_machines/bca_validation_and_appraisal_decisions_repeated_from_a_settled_state_are_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(api, project_overrides={"grant_program": "FMA"})

    appraisal = validate_success(
        api.create_appraisal(
            state["parcel"]["id"],
            factories.create_appraisal_payload(
                state["parcel"]["id"], appraiser_license_no="LIC-SA-1",
                effective_date="2026-07-01", indicated_value_cents=20_000_000,
            ),
            TEST_USERS["staff_appraiser_headers"],
        ),
        201,
    )

    submitted = validate_success(
        api.submit_appraisal(appraisal["id"], TEST_USERS["staff_appraiser_headers"])
    )
    assert submitted["status"] == "SUBMITTED"

    validate_error(
        api.submit_appraisal(appraisal["id"], TEST_USERS["staff_appraiser_headers"]),
        ApiErrorId.ERR_INVALID_APPRAISAL_STATE.value,
        409,
    )
    unmoved = validate_success(api.get_appraisal(appraisal["id"], ADMIN))
    assert unmoved["status"] == "SUBMITTED"

    accepted = validate_success(
        api.review_appraisal(
            appraisal["id"],
            factories.review_decision_payload(appraisal["id"], "ACCEPT"),
            TEST_USERS["review_appraiser_headers"],
        )
    )
    assert accepted["status"] == "ACCEPTED"

    validate_error(
        api.review_appraisal(
            appraisal["id"],
            factories.review_decision_payload(appraisal["id"], "ACCEPT"),
            TEST_USERS["review_appraiser_headers"],
        ),
        ApiErrorId.ERR_INVALID_APPRAISAL_STATE.value,
        409,
    )

    final = validate_success(api.get_appraisal(appraisal["id"], ADMIN))
    assert final["status"] == "ACCEPTED"
    assert final["revision_count"] == 0
