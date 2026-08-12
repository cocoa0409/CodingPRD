"""State machine basics — initial states, invalid transitions, terminal lockdown, idempotent close."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_education_course_payload,
    create_household_payload,
    create_income_certification_payload,
    get_success_data,
    setup_household,
    setup_program,
    setup_under_contract_resale,
    validate_error,
)


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_household_initial_state_is_pending():
    """PRD §3.2: "The household is created under the target program — its
    `program_id` field records the owning program's id — with
    `eligibility_status` set to `PENDING`."

    Design: Corner/state_machines/household_initial_state_is_pending
    """
    prog = setup_program(name="P-INIT")
    hh = get_success_data(
        api_client.create_household(
            prog["id"], create_household_payload(legal_name="New"), _is()
        )
    )
    assert hh["eligibility_status"] == "PENDING"


def test_income_cert_approve_from_submitted_returns_invalid_state():
    """PRD §3.2: "A certification is created in `SUBMITTED` status; a
    `ComplianceOfficer` moves it `SUBMITTED` → `UNDER_REVIEW`, then
    `UNDER_REVIEW` → `APPROVED` or `UNDER_REVIEW` → `REJECTED`."
    PRD §2.10 step 4: "**State** — the target resource must be in a state that
    permits the requested transition; otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/income_cert_approve_from_submitted_returns_invalid_state
    """
    prog = setup_program(name="P-SM1")
    hh = setup_household(prog["id"])
    cert = get_success_data(
        api_client.create_income_certification(
            prog["id"],
            hh["id"],
            create_income_certification_payload(),
            _is(),
        )
    )
    # Approve without start-review.
    resp = api_client.approve_income_certification(
        prog["id"], hh["id"], cert["id"], _co()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    cert_after = get_success_data(
        api_client.get_income_certification(prog["id"], hh["id"], cert["id"], _co())
    )
    assert cert_after["status"] == "SUBMITTED"


def test_education_course_retired_lockdown():
    """PRD §3.2: "Courses start in `OFFERED` status and may be retired
    (`OFFERED` → `RETIRED`)..."

    Once RETIRED, no further state transition is available; a second retire
    attempt is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/education_course_terminal_state_retired_lockdown
    """
    prog = setup_program(name="P-SM2")
    course = get_success_data(
        api_client.create_education_course(
            prog["id"], create_education_course_payload(), _pga()
        )
    )
    retired = get_success_data(
        api_client.retire_education_course(prog["id"], course["id"], _pga())
    )
    assert retired["status"] == "RETIRED"

    resp = api_client.retire_education_course(prog["id"], course["id"], _pga())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_resale_listing_idempotent_close():
    """PRD §3.5: "From `UNDER_CONTRACT`, the sale closes by a `LeaseManager`
    operation carrying `expected_listing_version` and a boolean
    `confirmed_funds`. ... On a successful close, the listing's `version`
    increments by 1 and its status becomes `CLOSED`..."
    PRD §2.10 step 4: "**State** — the target resource must be in a state that
    permits the requested transition; otherwise `ERR_INVALID_STATE`."

    A second close against a CLOSED listing is a state violation.

    Design: Corner/state_machines/resale_listing_idempotent_close
    """
    prog = setup_program(name="P-SM3")
    _, unit, _, _, listing, _, _ = setup_under_contract_resale(prog["id"])

    # First close succeeds.
    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    closed = get_success_data(
        api_client.close_resale_listing(
            prog["id"],
            unit["id"],
            listing["id"],
            {
                "expected_listing_version": listing_now["version"],
                "confirmed_funds": True,
            },
            _lm(),
        )
    )
    assert closed["status"] == "CLOSED"

    # Second close fails with ERR_INVALID_STATE.
    closed_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    resp = api_client.close_resale_listing(
        prog["id"],
        unit["id"],
        listing["id"],
        {
            "expected_listing_version": closed_now["version"],
            "confirmed_funds": True,
        },
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
