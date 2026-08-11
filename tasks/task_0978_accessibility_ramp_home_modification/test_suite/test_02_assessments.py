"""Assessment lifecycle, clinical scoring, and case intake guards."""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_assessment,
    create_case, create_assessment_payload, complete_assessment_payload,
    create_case_with_scheduled_assessment, create_assessed_case,
    set_clock, get_case,
)

IC = TEST_USERS["intake_coordinator_headers"]
AS = TEST_USERS["assessor_headers"]
PM = TEST_USERS["project_manager_headers"]


def test_assessment_starts_in_scheduled_state(api):
    """PRD §3.1: "The assessment is created in `SCHEDULED` status, and creating it
    moves the case from `INTAKE` to `ASSESSMENT_SCHEDULED`."

    Design: Corner/state_machines/assessment_starts_in_scheduled_state
    """
    set_clock()
    case = create_case(client_name="Lou Mays", client_address="13 Initial St",
                       client_phone="555-0215")
    asmt = validate_success(api.create_assessment(
        case["id"], create_assessment_payload(
            assessor_id="ot-4", assessor_role="BOTH", mobility_score=60, hazard_count=2),
        IC), 201)
    assert_assessment(asmt)
    assert asmt["status"] == "SCHEDULED"
    assert get_case(case["id"])["status"] == "ASSESSMENT_SCHEDULED"


def test_assessment_create_invalid_enum_role_returns_400(api):
    """PRD §2.6: "A request that is malformed, missing required fields, or
    carrying invalid values is rejected as `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "an `assessor_role` of `OT`, `CAPS`, or `BOTH`".

    Design: Corner/entities/assessment_create_invalid_enum_role_returns_400
    """
    set_clock()
    case = create_case(client_name="Hal Iles", client_address="9 Enum St",
                       client_phone="555-0211")
    res = api.create_assessment(
        case["id"],
        create_assessment_payload(assessor_id="x-1", assessor_role="BOGUS"),
        IC)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    assert get_case(case["id"])["status"] == "INTAKE", "rejected create must not fire side effects"


def test_assessment_under_unknown_case_returns_not_found(api):
    """PRD §2.7: "Path parameters are validated strictly left to right: the
    `{caseId}` segment is checked first, then the next nested identifier, then the
    next. The first segment that does not resolve produces the 404 for that
    resource type and evaluation stops."

    Design: Corner/entities/assessment_under_unknown_case_returns_not_found
    """
    set_clock()
    res = api.create_assessment(
        NON_EXISTENT_UUID,
        create_assessment_payload(assessor_id="ot-x"),
        IC)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_FOUND, expected_status=404)


def test_assessment_complete_from_scheduled_rejected(api):
    """PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."
    PRD §3.1: "the assigned `Assessor` starts the assessment, moving it from
    `SCHEDULED` to `IN_PROGRESS`". "On completion the assessment moves to
    `COMPLETED`".

    Design: Corner/state_machines/assessment_complete_from_scheduled_rejected
    """
    set_clock()
    case, asmt = create_case_with_scheduled_assessment(mobility_score=60, hazard_count=2)
    res = api.complete_assessment(
        case["id"], asmt["id"],
        complete_assessment_payload(mobility_score=60, hazard_count=2), AS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    got = validate_success(api.get_assessment(case["id"], asmt["id"], IC), 200)
    assert got["status"] == "SCHEDULED"


def test_assessment_cancelled_terminal_lockdown(api):
    """PRD §3.1: "When the scheduled day arrives — the `scheduled_date` must have
    been reached — the assigned `Assessor` starts the assessment, moving it from
    `SCHEDULED` to `IN_PROGRESS`; attempting to start an assessment that is not in
    `SCHEDULED` fails with `ERR_ASSESSMENT_NOT_SCHEDULED`."
    PRD §3.1: "An assessment that will not happen can be cancelled by an
    `IntakeCoordinator` from either `SCHEDULED` or `IN_PROGRESS`, moving it to
    `CANCELLED`."

    Design: Corner/state_machines/assessment_cancelled_terminal_lockdown
    """
    set_clock()
    case, asmt = create_case_with_scheduled_assessment(mobility_score=60, hazard_count=2)
    validate_success(api.cancel_assessment(case["id"], asmt["id"], IC), 200)
    res = api.start_assessment(case["id"], asmt["id"], AS)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_SCHEDULED, expected_status=409)
    got = validate_success(api.get_assessment(case["id"], asmt["id"], IC), 200)
    assert got["status"] == "CANCELLED"


def test_assessment_scheduled_in_past_rejected(api):
    """PRD §3.1: "A `scheduled_date` in the past is rejected with
    `ERR_INVALID_SCHEDULE_DATE`."
    PRD §2.9: "Every date comparison in this document — "in the past", "reached",
    "passes" — is evaluated against this logical clock."

    Design: Corner/validations/assessment_scheduled_in_past_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    case = create_case(client_name="Quo Tam", client_address="43 Past Ln",
                       client_phone="555-0402")
    res = api.create_assessment(
        case["id"],
        create_assessment_payload(assessor_id="ot-30", scheduled_date="2026-05-01T00:00:00Z"),
        IC)
    validate_error(res, ApiErrorId.ERR_INVALID_SCHEDULE_DATE, expected_status=422)
    assert get_case(case["id"])["status"] == "INTAKE", "no assessment may be persisted"


def test_safety_risk_index_computed_from_inputs(api):
    """PRD §3.1: "The safety risk of the household is captured as
    `safety_risk_index` on the case: each identified hazard contributes half a
    point (the `hazard_count` multiplied by 0.5), and the shortfall of the
    `mobility_score` below 100 contributes five hundredths of a point per point of
    shortfall (multiplied by 0.05); the sum is clamped so it never falls below 0.0
    and never exceeds 10.0, then rounded to one decimal place."
    PRD §3.1: "When every `INITIAL` assessment on the case has reached `COMPLETED`,
    the case advances from `ASSESSMENT_SCHEDULED` to `ASSESSED`".

    Design: Corner/calculations/safety_risk_index_computed_from_inputs
    """
    set_clock()
    # risk = 4 * 0.5 + (100 - 60) * 0.05 = 2.0 + 2.0 = 4.0
    case, _ = create_assessed_case(mobility_score=60, hazard_count=4,
                                   client_name="Hal Kern", client_address="34 Risk Rd",
                                   client_phone="555-0301")
    assert case["safety_risk_index"] == pytest.approx(4.0, abs=1e-9)
    assert case["status"] == "ASSESSED"


def test_safety_risk_index_clamped_to_max_10(api):
    """PRD §3.1: "the sum is clamped so it never falls below 0.0 and never exceeds
    10.0, then rounded to one decimal place."

    Design: Corner/calculations/safety_risk_index_clamped_to_max_10
    """
    set_clock()
    # raw risk = 30 * 0.5 + (100 - 0) * 0.05 = 15 + 5 = 20 -> clamped to 10.0
    case, _ = create_assessed_case(mobility_score=0, hazard_count=30,
                                   client_name="Ida Lusk", client_address="35 Clamp Ct",
                                   client_phone="555-0302")
    assert case["safety_risk_index"] == pytest.approx(10.0, abs=1e-9)


def test_assessment_start_twice_returns_409(api):
    """PRD §3.1: "When the scheduled day arrives — the `scheduled_date` must have
    been reached — the assigned `Assessor` starts the assessment, moving it from
    `SCHEDULED` to `IN_PROGRESS`; attempting to start an assessment that is not in
    `SCHEDULED` fails with `ERR_ASSESSMENT_NOT_SCHEDULED`."

    Design: Corner/errors/assessment_start_twice_returns_409
    """
    set_clock()
    case, asmt = create_case_with_scheduled_assessment()
    validate_success(api.start_assessment(case["id"], asmt["id"], AS), 200)
    res = api.start_assessment(case["id"], asmt["id"], AS)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_SCHEDULED, expected_status=409)
    got = validate_success(api.get_assessment(case["id"], asmt["id"], IC), 200)
    assert got["status"] == "IN_PROGRESS"


def test_child_op_on_cancelled_case_returns_not_active(api):
    """PRD §3.8: "Attempts to keep operating a case that has already reached
    `CLOSED` or `CANCELLED` are rejected with `ERR_CASE_ALREADY_CLOSED`, and any
    child operation against a case in a terminal state is rejected with
    `ERR_CASE_NOT_ACTIVE`."

    Design: Corner/errors/child_op_on_cancelled_case_returns_not_active
    """
    set_clock()
    case = create_case(client_name="State NotActive", client_address="61 Guard Rd",
                       client_phone="555-0611")
    validate_success(api.cancel_case(case["id"], PM), 200)
    res = api.create_assessment(
        case["id"], create_assessment_payload(assessor_id="ot-50"), IC)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_ACTIVE, expected_status=409)


def test_assessment_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/assessment_not_found_returns_404
    """
    case = create_case(client_name="NF Asmt", client_address="51 NF Rd",
                       client_phone="555-0601")
    res = api.get_assessment(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND, expected_status=404)
