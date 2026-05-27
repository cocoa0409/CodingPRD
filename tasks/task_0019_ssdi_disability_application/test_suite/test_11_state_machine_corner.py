"""State-machine corner cases: invalid transition, initial state, terminal
lockdown, hearing already scheduled."""
import pytest
from test_helpers import (
    validate_error, get_success_data, api_client, TEST_USERS,
    set_clock,
    create_claimant, create_application_for_claimant,
    setup_application_in_medical_review,
    setup_hearing_in_requested,
    submit_medical_decision,
    attach_evidence,
    medical_decision_payload, schedule_hearing_payload,
    schedule_hearing,
    make_claimant_headers,
)


# =========================================================================
# Instance: submit_application_in_qc_review_returns_invalid_state
# =========================================================================

def test_resubmit_already_submitted_application_returns_invalid_state(api):
    """PRD §3.2: "Submitting an application that is not in `DRAFT` is
    rejected with `ERR_INVALID_APPLICATION_STATE`."

    Design: Corner/state_machines/submit_application_in_qc_review_returns_invalid_state
    """
    set_clock("2026-01-15T00:00:00Z")
    claimant, app_submitted = setup_application_in_medical_review(
        claimant_overrides={
            "ssn_last4": "1001",
            "full_name": "Resub",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
        attach_evidence_after=False,
    )
    # Application is now in MEDICAL_REVIEW (auto-routed after submit).
    res = api_client.submit_application(app_submitted["id"],
                                         make_claimant_headers(claimant["id"]))
    validate_error(res, "ERR_INVALID_APPLICATION_STATE", expected_status=409)


# =========================================================================
# Instance: new_application_starts_in_draft
# =========================================================================

def test_new_application_starts_in_draft(api):
    """PRD §3.2: "The resource is created at `version` 1 with `status` of
    `DRAFT`, an `insured_status` of `PENDING`, a `medical_decision` of
    `PENDING`, and computed fields `total_qc_at_filing`,
    `recent_qc_in_lookback`, and `established_onset_date` initialised to
    a not-yet-computed state."

    Design: Corner/state_machines/new_application_starts_in_draft
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(ssn_last4="1002", full_name="Init State",
                        date_of_birth="1985-01-01T00:00:00Z", filing_state="TX")
    app = create_application_for_claimant(c["id"])
    assert app["status"] == "DRAFT"
    assert app["version"] == 1
    assert app["insured_status"] == "PENDING"
    assert app["medical_decision"] == "PENDING"


# =========================================================================
# Instance: terminal_denied_qc_no_further_transitions
# =========================================================================

def test_terminal_denied_qc_blocks_medical_decision(api):
    """PRD §3.2: "When `insured_status` resolves to `NOT_INSURED`, the
    server transitions through `QC_REVIEW` to the terminal `DENIED_QC`
    state and increments the `version`."
    PRD §3.4: "The application must be in `MEDICAL_REVIEW`, otherwise the
    request is rejected with `ERR_INVALID_APPLICATION_STATE`."

    Design: Corner/state_machines/terminal_denied_qc_no_further_transitions
    """
    set_clock("2026-01-15T00:00:00Z")
    # Young claimant with no credits → DENIED_QC.
    c = create_claimant(ssn_last4="1003", full_name="Term DQ",
                        date_of_birth="2002-06-01T00:00:00Z", filing_state="TX")
    app = create_application_for_claimant(
        c["id"],
        alleged_onset_date="2025-01-01T00:00:00Z",
        protective_filing_date="2026-01-15T00:00:00Z",
    )
    res = api_client.submit_application(app["id"], make_claimant_headers(c["id"]))
    app_after = get_success_data(res)
    assert app_after["status"] == "DENIED_QC"
    # Try to push a medical decision on a DENIED_QC application.
    attach_evidence(app["id"])  # as DDSExaminer
    payload = medical_decision_payload(
        decision_type="RFC_DISABLED",
        established_onset_date="2025-01-15T00:00:00Z",
        expected_application_version=app_after["version"],
        rfc_score=30,
    )
    res = api_client.medical_decision(app["id"], payload,
                                       TEST_USERS["dds_examiner_headers"])
    validate_error(res, "ERR_INVALID_APPLICATION_STATE", expected_status=409)


# =========================================================================
# Instance: schedule_hearing_already_scheduled_returns_invalid_state
# =========================================================================

def test_schedule_already_scheduled_hearing_returns_invalid_hearing_state(api):
    """PRD §3.5: "Two preconditions guard the call: the hearing must be in
    `REQUESTED` (otherwise `ERR_INVALID_HEARING_STATE`), and the supplied
    `scheduled_date` must be at least 75 days after the hearing's
    server-recorded `requested_date`"

    Design: Corner/state_machines/schedule_hearing_already_scheduled_returns_invalid_state
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_hearing_in_requested(
        claimant_overrides={
            "ssn_last4": "1004",
            "full_name": "Sch Twice",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
    )
    hearing = ctx["hearing"]
    # First schedule succeeds: 75+ days ahead.
    schedule_hearing(hearing["id"], "2026-08-01T00:00:00Z")
    # Second schedule on a now-SCHEDULED hearing → ERR_INVALID_HEARING_STATE.
    payload = schedule_hearing_payload("2026-09-01T00:00:00Z")
    res = api_client.schedule_hearing(hearing["id"], payload, TEST_USERS["alj_headers"])
    validate_error(res, "ERR_INVALID_HEARING_STATE", expected_status=409)
