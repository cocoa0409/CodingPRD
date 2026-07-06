"""Case parallel state dimensions, authorization caps, allotment, closure."""
import pytest
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_error_is_one_of, ApiErrorId,
    setup_authorized_case, schedule_session, complete_session,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


# ===========================================================================
# Non-linear state machine: parallel dimensions  (Difficulty)
# ===========================================================================
def test_case_parallel_dimensions_evolve_independently(api):
    """PRD §3.5: "when that count reaches the case's `session_allotment`, the
    case's `funding_status` advances from `AUTHORIZED` to `EXHAUSTED`, its
    `sessions_remaining` is set to zero, and any further scheduling attempt on
    that case is rejected with `ERR_ALLOTMENT_EXHAUSTED`."
    PRD §3.3: "Closing the clinical dimension does not force the funding dimension
    to any terminal value — `funding_status` retains whatever value it held
    (`AUTHORIZED` or `EXHAUSTED`) at the time of closure."

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_evolve_independently
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 1, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    complete_session(s1["id"], provider)
    # funding exhausted, clinical still OPEN
    mid = validate_success(api.get_case(case["id"], ADMIN))
    assert mid["funding_status"] == "EXHAUSTED"
    assert mid["clinical_status"] == "OPEN"
    closed = validate_success(api.close_case(case["id"], COORD))
    assert closed["funding_status"] == "EXHAUSTED"
    assert closed["clinical_status"] == "CLOSED"


def test_case_exhausted_blocks_further_scheduling(api):
    """PRD §3.5: "when that count reaches the case's `session_allotment`, the
    case's `funding_status` advances from `AUTHORIZED` to `EXHAUSTED`, its
    `sessions_remaining` is set to zero, and any further scheduling attempt on
    that case is rejected with `ERR_ALLOTMENT_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_evolve_independently
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 1, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    exhausted = validate_success(api.get_case(case["id"], ADMIN))
    assert exhausted["funding_status"] == "EXHAUSTED"
    assert exhausted["sessions_remaining"] == 0
    # clinical still OPEN — funding axis exhausted independently
    assert exhausted["clinical_status"] == "OPEN"
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-03T10:00:00Z"}
    validate_error(api.create_session(case["id"], payload, COORD),
                   ApiErrorId.ERR_ALLOTMENT_EXHAUSTED.value)


# NOTE: Difficulty/priority_pair_validation_conflict/authorize_invalid_state_beats_annual_cap
# is SKIPPED. Its recipe drives case2 to CLOSED by calling close on an INTAKE
# case, but PRD §3.3 states close moves clinical_status "from `OPEN` to `CLOSED`"
# only. A PRD-only reader would reject closing an INTAKE case (invalid transition),
# leaving case2 INTAKE/PENDING — a legal authorize source where the cap check, not
# a state check, fires. The setup is not uniquely derivable from PRD prose, so the
# instance fails the Core rule's unique-derivability condition and is not emitted.


# ===========================================================================
# Priority pair: SESSION_IN_PAST beats ALLOTMENT_EXHAUSTED  (Difficulty)
# ===========================================================================
def test_schedule_session_in_past_beats_allotment_exhausted(api):
    """PRD §3.5: "The `scheduled_for` instant must be at or after the logical
    clock's current value; back-dated scheduling is rejected with
    `ERR_SESSION_IN_PAST`."
    PRD §2.6: "Domain-specific business rules — crisis safety, temporal scheduling
    rules, and the fiscal caps described later — are evaluated after these
    foundational checks. Where two business rules of the same kind could both apply
    to one request, the more specific guidance in the relevant workflow subsection
    of §3 governs their relative order."

    NOTE: PRD §2.6 groups temporal scheduling rules and fiscal caps in the SAME
    after-foundational category, and §3.6 does not establish a precedence between
    ERR_SESSION_IN_PAST and ERR_ALLOTMENT_EXHAUSTED. Both are PRD-faithful outcomes
    for a request that is simultaneously back-dated and over-allotment, so we accept
    either error_id (ERROR PRECEDENCE SILENCE relaxation).

    Design: Difficulty/priority_pair_validation_conflict/schedule_session_in_past_beats_allotment_exhausted
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 1, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    # exhaust allotment
    schedule_session(case["id"], provider["id"], "2026-03-05T10:00:00Z")
    fx.set_clock("2026-03-10T09:00:00Z")
    # back-dated AND over-allotment -> either error is PRD-faithful
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-06T10:00:00Z"}
    validate_error_is_one_of(api.create_session(case["id"], payload, COORD),
                   [ApiErrorId.ERR_SESSION_IN_PAST.value,
                    ApiErrorId.ERR_ALLOTMENT_EXHAUSTED.value])


def test_schedule_session_in_past_rejected_on_authorized_case(api):
    """PRD §3.5: "The `scheduled_for` instant must be at or after the logical
    clock's current value; back-dated scheduling is rejected with
    `ERR_SESSION_IN_PAST`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_session_in_past_beats_allotment_exhausted
    """
    # Isolated SESSION_IN_PAST: authorized case with allotment available, but the
    # requested instant is strictly before the clock.
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        clock="2026-03-10T09:00:00Z")
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-02T10:00:00Z"}
    validate_error(api.create_session(case["id"], payload, COORD),
                   ApiErrorId.ERR_SESSION_IN_PAST.value)


# ===========================================================================
# Boundary: annual cap inclusive <=  (Difficulty)
# ===========================================================================
def test_annual_cap_inclusive_boundary_on_authorize(api):
    """PRD §3.3: "the contract's current `sessions_committed` plus the contract's
    `sessions_per_issue` must be less than or equal to the contract's
    `annual_session_cap`, or the request fails with `ERR_ANNUAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/annual_cap_inclusive_boundary_on_authorize
    """
    # cap=2, per_issue=2: first authorize 0+2<=2 allowed; commit 2 sessions;
    # second authorize would be 2+2=4 > 2 -> rejected.
    contract, plan, employee, provider, case1 = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 2, "annual_session_cap": 2},
        clock="2026-03-02T09:00:00Z")
    schedule_session(case1["id"], provider["id"], "2026-03-02T10:00:00Z")
    schedule_session(case1["id"], provider["id"], "2026-03-03T10:00:00Z")
    c_now = validate_success(api.get_contract(contract["id"], ADMIN))
    assert c_now["sessions_committed"] == 2
    case2 = fx.create_case(contract["id"], employee["id"], presenting_issue="GRIEF")
    validate_error(api.authorize_case(
        case2["id"], {"expected_contract_version": c_now["version"]}, COORD),
        ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED.value)


def test_annual_cap_boundary_first_authorize_allowed(api):
    """PRD §3.3: "the contract's current `sessions_committed` plus the contract's
    `sessions_per_issue` must be less than or equal to the contract's
    `annual_session_cap`, or the request fails with `ERR_ANNUAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/annual_cap_inclusive_boundary_on_authorize
    """
    # Inclusive boundary: committed(0)+sessions_per_issue(2) == cap(2) is allowed.
    contract, plan, employee = fx.setup_contract_plan_employee(
        contract_overrides={"sessions_per_issue": 2, "annual_session_cap": 2})
    case = fx.create_case(contract["id"], employee["id"])
    authorized = validate_success(api.authorize_case(
        case["id"], {"expected_contract_version": contract["version"]}, COORD))
    assert authorized["funding_status"] == "AUTHORIZED"


# ===========================================================================
# Close-case precondition: open sessions block close
# ===========================================================================
def test_case_close_with_scheduled_session_returns_open_sessions(api):
    """PRD §3.3: "A case may not be closed while it still has any session in
    `SCHEDULED` status; the attempt is rejected with `ERR_CASE_HAS_OPEN_SESSIONS`."

    Design: Corner/state_machines/case_close_with_scheduled_session_returns_open_sessions
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        clock="2026-03-02T09:00:00Z")
    schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    validate_error(api.close_case(case["id"], COORD),
                   ApiErrorId.ERR_CASE_HAS_OPEN_SESSIONS.value)
    assert validate_success(api.get_case(case["id"], ADMIN))["clinical_status"] == "OPEN"


# ===========================================================================
# Invalid enum on case create
# ===========================================================================
def test_create_case_invalid_presenting_issue_enum_returns_invalid_request(api):
    """PRD §2.6: "then request well-formedness — required fields present, enum
    values valid, and numeric constraints satisfied (`ERR_INVALID_REQUEST`,
    HTTP 422)."

    Design: Corner/entities/create_case_invalid_presenting_issue_enum_returns_invalid_request
    """
    contract, plan, employee = fx.setup_contract_plan_employee(
        employee_overrides={"external_ref": "EQ1", "full_name": "Empl Q"})
    payload = {"contract_id": contract["id"], "employee_id": employee["id"],
               "presenting_issue": "NOT_A_REAL_ISSUE"}
    validate_error(api.create_case(payload, COORD),
                   ApiErrorId.ERR_INVALID_REQUEST.value)
