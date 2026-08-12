"""Auth and RBAC validation tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_household_payload,
    create_income_certification_payload,
    get_success_data,
    make_household_headers,
    setup_active_lease,
    setup_household,
    setup_program,
    validate_error,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _insp():
    return TEST_USERS["inspector_headers"]


def test_unauthenticated_missing_role_header():
    """PRD §2.1: "Every API call is authenticated by two headers: `X-User-ID`
    (the identifier of the acting principal) and `X-User-Role` (the role the
    principal is acting in). If either header is missing or malformed, the
    request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/unauthenticated_missing_role_header
    """
    prog = setup_program(name="P-AUTH1")
    # Send a request without the X-User-Role header.
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    resp = api_client.list_households(prog["id"], headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_wrong_role_cannot_create_households():
    """PRD §2.1: "`IntakeSpecialist` — front-line staff; registers
    households, records education completions, and submits income
    certifications on behalf of households."
    PRD §2.1: "If the headers are present but the named role is not
    permitted to invoke the requested operation, the request is rejected
    with `ERR_UNAUTHORIZED`."

    Household creation is IntakeSpecialist-only; a LeaseManager is not
    permitted and is rejected with ERR_UNAUTHORIZED.

    Design: Corner/validations/wrong_role_cannot_create_households
    """
    prog = setup_program(name="P-AUTH2")
    resp = api_client.create_household(
        prog["id"], create_household_payload(legal_name="X"), _lm()
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_segregation_of_duties_same_user_approves_own_submission():
    """PRD §2.8: "When a `ComplianceOfficer` approves or rejects an
    `IncomeCertification`, the acting `X-User-ID` must differ from the
    certification's `submitted_by`. ... In both cases, if the acting
    identifier equals `submitted_by`, the request is rejected with
    `ERR_SO_DUTY_VIOLATION` (HTTP 409)."

    The submitter is an IntakeSpecialist with X-User-ID 'shared-user-1'. The
    same X-User-ID then acts as ComplianceOfficer to approve — the SoD check
    compares identifiers across roles, and fires.

    Design: Corner/validations/segregation_of_duties_same_user_approves_own_submission
    """
    prog = setup_program(name="P-SOD")
    hh = setup_household(prog["id"])

    # IntakeSpecialist submits with a particular user id.
    submitter_id = "shared-user-1"
    submitter_headers = {
        "X-User-ID": submitter_id,
        "X-User-Role": "IntakeSpecialist",
        "Content-Type": "application/json",
    }
    cert = get_success_data(
        api_client.create_income_certification(
            prog["id"],
            hh["id"],
            create_income_certification_payload(),
            submitter_headers,
        )
    )
    # ComplianceOfficer starts review (different user id).
    get_success_data(
        api_client.start_review_income_certification(
            prog["id"], hh["id"], cert["id"], _co()
        )
    )
    # Same X-User-ID attempts to approve as ComplianceOfficer — SoD fires.
    same_id_officer_headers = {
        "X-User-ID": submitter_id,
        "X-User-Role": "ComplianceOfficer",
        "Content-Type": "application/json",
    }
    resp = api_client.approve_income_certification(
        prog["id"], hh["id"], cert["id"], same_id_officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_SO_DUTY_VIOLATION.value)


def test_education_incomplete_blocks_lease_activation():
    """PRD §3.3: "Four preconditions must all hold: ... the household's
    `education_completed_at` must be non-null and every required
    `EducationCourse` must have an unexpired `EducationCompletion`
    (otherwise `ERR_EDUCATION_INCOMPLETE`)..."

    The household is ELIGIBLE (its stored status passes the §3.3 eligibility
    gate); a SECOND required course is then added, which the household has
    not completed — so the activation-time education check, which evaluates
    every required course live, fires ERR_EDUCATION_INCOMPLETE.

    Design: Corner/validations/education_incomplete_blocks_lease_activation
    """
    from test_helpers import (
        create_education_course_payload,
        create_lease_payload,
        create_unit_payload,
        setup_eligible_household,
    )

    prog = setup_program(name="P-EDU")
    hh, _, _ = setup_eligible_household(prog["id"])
    assert hh["eligibility_status"] == "ELIGIBLE"

    # A new required course appears after the household qualified.
    get_success_data(
        api_client.create_education_course(
            prog["id"],
            create_education_course_payload(code="REQ-2", is_required=True),
            _pga(),
        )
    )

    unit = get_success_data(
        api_client.create_unit(prog["id"], create_unit_payload(address="1 ED St"), _pga())
    )
    lease = get_success_data(
        api_client.create_lease(
            prog["id"], unit["id"],
            create_lease_payload(household_id=hh["id"]),
            _lm(),
        )
    )
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    resp = api_client.activate_lease(
        prog["id"],
        unit["id"],
        lease["id"],
        {"expected_unit_version": unit_now["version"]},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_EDUCATION_INCOMPLETE.value)

    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after["status"] == "DRAFT"


def test_underpayment_on_lease_fee():
    """PRD §3.3: "A `Household` may pay a fee by submitting
    `payment_amount_cents`; if the sum of the existing `paid_amount_cents`
    and the new `payment_amount_cents` is at least `amount_cents`, the fee
    transitions to `PAID` ... If the sum is less than `amount_cents`, the
    request is rejected with `ERR_UNDERPAYMENT` and the fee's status is
    unchanged."

    Design: Corner/validations/underpayment_on_lease_fee
    """
    prog = setup_program(name="P-UND")
    _, unit, hh, lease = setup_active_lease(prog["id"])
    fees = get_success_data(
        api_client.list_fees(prog["id"], unit["id"], lease["id"], _lm())
    )
    fee = fees[0]
    hh_headers = make_household_headers(hh["id"])
    # Pay less than amount_cents.
    resp = api_client.pay_fee(
        prog["id"],
        unit["id"],
        lease["id"],
        fee["id"],
        {"payment_amount_cents": 10_000},
        hh_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNDERPAYMENT.value)

    fee_after = get_success_data(
        api_client.get_fee(prog["id"], unit["id"], lease["id"], fee["id"], _lm())
    )
    assert fee_after["status"] == "PENDING"


def test_funds_not_confirmed_blocks_close():
    """PRD §3.5: "From `UNDER_CONTRACT`, the sale closes by a `LeaseManager`
    operation carrying `expected_listing_version` and a boolean
    `confirmed_funds`. If `confirmed_funds` is not true, the close is
    rejected with `ERR_FUNDS_NOT_CONFIRMED`."

    Design: Corner/validations/funds_not_confirmed_blocks_close
    """
    from test_helpers import setup_under_contract_resale

    prog = setup_program(name="P-FNC")
    _, unit, _, _, listing, _, _ = setup_under_contract_resale(prog["id"])

    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    resp = api_client.close_resale_listing(
        prog["id"],
        unit["id"],
        listing["id"],
        {
            "expected_listing_version": listing_now["version"],
            "confirmed_funds": False,
        },
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_FUNDS_NOT_CONFIRMED.value)

    listing_after = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    assert listing_after["status"] == "UNDER_CONTRACT"
