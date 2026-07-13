"""Application state machine, info-request revision cycle, and income documents
(PRD §3.2, §3.3, §3.4)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    new_funding_pool, new_household, new_draft_application, submit_app,
    make_applicant_headers, TEST_USERS,
    create_income_document_payload,
)

CW = TEST_USERS["caseworker_headers"]


class TestInfoRequestedRevisionCycle:
    def test_request_info_moves_submitted_to_info_requested(self, api):
        """PRD §3.3: "Between submission and a decision, a caseworker may send an
        application back for more information, moving it from `SUBMITTED` to
        `INFO_REQUESTED`; this action requires the application be in `SUBMITTED` status."

        Design: Difficulty/non_linear_state_machine/application_info_requested_revision_cycle
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Eve Fenn", household_size=4,
                           annual_income_cents=2_000_000, heating_source="ELECTRICITY")
        app = new_draft_application(api, hh["id"])
        submit_app(api, app["id"], hh["id"])
        data = validate_success(api.request_info_application(app["id"], CW))
        assert data["status"] == "INFO_REQUESTED"

    def test_resubmit_from_info_requested_returns_to_submitted(self, api):
        """PRD §3.3: "From `INFO_REQUESTED` the applicant resubmits (as described in
        §3.2), returning the application to `SUBMITTED` — the revision cycle that lets
        an applicant correct or supplement a filing without starting over."

        Design: Difficulty/non_linear_state_machine/application_info_requested_revision_cycle
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Eve Fenn", household_size=4,
                           annual_income_cents=2_000_000, heating_source="ELECTRICITY")
        app = new_draft_application(api, hh["id"])
        submit_app(api, app["id"], hh["id"])
        api.request_info_application(app["id"], CW)
        data = validate_success(api.submit_application(app["id"], make_applicant_headers(hh["id"])))
        assert data["status"] == "SUBMITTED"


def test_approve_draft_application_rejected(api):
    """PRD §3.4: "Approval is a caseworker action that requires the application be in
    `SUBMITTED` status; from any other state it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_from_draft_returns_invalid_state
    """
    hh = new_household(api, primary_applicant_name="Ed Frey", household_size=2,
                       annual_income_cents=1_200_000, heating_source="ELECTRICITY")
    app = new_draft_application(api, hh["id"])
    resp = api.approve_application(app["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_application(app["id"], CW))
    assert after["status"] == "DRAFT"


def test_verify_income_document_rejected_moves_to_rejected(api):
    """PRD §3.3: "When the outcome is `REJECTED`, the document moves from `PENDING` to
    `REJECTED` and does not count toward approval."

    Design: Corner/state_machines/income_document_reject_transition
    """
    hh = new_household(api, primary_applicant_name="Hy Ives", household_size=2,
                       annual_income_cents=1_200_000, heating_source="ELECTRICITY")
    app = new_draft_application(api, hh["id"])
    doc = validate_success(api.create_income_document(
        create_income_document_payload(app["id"], doc_type="SELF_ATTESTATION",
                                        reported_income_cents=1_200_000), CW), expected_status=201)
    data = validate_success(api.verify_income_document(doc["id"], {"outcome": "REJECTED"}, CW))
    assert data["status"] == "REJECTED"


def test_duplicate_active_application_submit_rejected(api):
    """PRD §3.2: "Second, no other application for the same `household_id`,
    `season_year`, and `program_component` may already be in `SUBMITTED`,
    `INFO_REQUESTED`, or `APPROVED` status; a collision is rejected with
    `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/duplicate_application_returns_error
    """
    new_funding_pool(api, program_component="HEATING")
    hh = new_household(api, primary_applicant_name="Ny Ober", household_size=3,
                       annual_income_cents=1_700_000, heating_source="NATURAL_GAS")
    app1 = new_draft_application(api, hh["id"])
    submit_app(api, app1["id"], hh["id"])
    app2 = new_draft_application(api, hh["id"])
    resp = api.submit_application(app2["id"], make_applicant_headers(hh["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION.value)
    after = validate_success(api.get_application(app2["id"], CW))
    assert after["status"] == "DRAFT"


def test_approve_without_verified_income_rejected(api):
    """PRD §3.4: "At least one income document for the application must be in `VERIFIED`
    status, or approval is rejected with `ERR_INCOME_NOT_VERIFIED`."

    Design: Corner/validations/approve_without_verified_income_returns_error
    """
    new_funding_pool(api, program_component="HEATING")
    hh = new_household(api, primary_applicant_name="Op Rand", household_size=3,
                       annual_income_cents=1_700_000, heating_source="NATURAL_GAS")
    app = new_draft_application(api, hh["id"])
    submit_app(api, app["id"], hh["id"])
    api.create_income_document(create_income_document_payload(app["id"]), CW)  # PENDING only
    resp = api.approve_application(app["id"], CW)
    validate_error(resp, ApiErrorId.ERR_INCOME_NOT_VERIFIED.value)
    after = validate_success(api.get_application(app["id"], CW))
    assert after["status"] == "SUBMITTED"
