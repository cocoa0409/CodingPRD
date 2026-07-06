"""Employer contract: creation, OCC lifecycle, revoke cascades, utilization."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, make_provider_headers,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_contract_payload,
    setup_authorized_case, schedule_session, complete_session, submit_claim,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


# ===========================================================================
# Contract creation / defaults
# ===========================================================================
def test_create_contract_returns_201_with_defaults(api):
    """PRD §3.1: "A new contract begins with `status` of `ACTIVE`,
    `sessions_committed` of zero, `utilization_rate` of zero, and `version` of 1."
    PRD §3.1: "`crisis_sla_minutes`, the maximum minutes from crisis intake to
    triage disposition before the SLA is breached (at least 1, defaulting to 15),
    and `reporting_min_cohort`, the k-anonymity floor below which aggregate report
    cells are suppressed (at least 1, defaulting to 5)."

    Design: Corner/entities/create_contract_returns_201_with_defaults
    """
    payload = {
        "employer_name": "Acme2", "sessions_per_issue": 2, "annual_session_cap": 10,
        "session_rate_cents": 12000, "annual_reimbursement_budget_cents": 100000,
    }
    data = validate_success(api.create_contract(payload, ADMIN), 201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["sessions_committed"] == 0
    assert data["crisis_sla_minutes"] == 15
    assert data["reporting_min_cohort"] == 5


def test_get_contract_not_found_returns_404(api):
    """PRD §2.5: "the system validates existence left-to-right and rejects the
    first missing reference with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_contract_not_found_returns_404
    """
    validate_error(api.get_contract(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_contract_missing_required_returns_invalid_request(api):
    """PRD §2.6: "then request well-formedness — required fields present, enum
    values valid, and numeric constraints satisfied (`ERR_INVALID_REQUEST`,
    HTTP 422)."

    Design: Corner/entities/create_contract_missing_required_returns_invalid_request
    """
    payload = {
        "employer_name": "NoRate", "sessions_per_issue": 2, "annual_session_cap": 10,
        "annual_reimbursement_budget_cents": 100000,
    }
    validate_error(api.create_contract(payload, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_contracts_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_contracts_pagination_envelope
    """
    fx.create_contract(employer_name="L1")
    fx.create_contract(employer_name="L2")
    data, meta = validate_paginated(api.list_contracts(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ===========================================================================
# Dual-variant: committed vs verified utilization  (Difficulty)
# ===========================================================================
def test_contract_utilization_committed_vs_verified_diverge(api):
    """PRD §3.1: "By default, and when a contract is fetched, this committed
    figure counts both scheduled and completed sessions (the forward-looking
    basis). The contract may also be examined on a **verified** basis, which
    counts only `COMPLETED` sessions and excludes those merely `SCHEDULED`,
    yielding a rate less than or equal to the committed rate; the basis is chosen
    by a `basis` query value of either committed (the default) or verified."
    PRD §3.1: "The `utilization_rate` is `sessions_committed` divided by the
    `annual_session_cap`, rounded to four decimal places half-up."

    Design: Difficulty/dual_variant_calc/contract_utilization_committed_vs_verified_diverge
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    schedule_session(case["id"], provider["id"], "2026-03-03T10:00:00Z")
    complete_session(s1["id"], provider)

    committed = validate_success(api.get_contract(contract["id"], ADMIN))
    assert committed["utilization_rate"] == 0.2, \
        f"committed basis expected 0.2 (2 sessions /10), got {committed['utilization_rate']}"

    verified = validate_success(api.get_contract_utilization(
        contract["id"], ADMIN, params={"basis": "verified"}))
    assert verified["utilization_rate"] == 0.1, \
        f"verified basis expected 0.1 (1 completed /10), got {verified['utilization_rate']}"


def test_utilization_committed_counts_scheduled_sessions(api):
    """PRD §3.1: "The `sessions_committed` count is the number of counseling
    sessions in `SCHEDULED` or `COMPLETED` status across every case of the
    contract — this is what the annual cap is measured against."
    PRD §3.1: "By default, and when a contract is fetched, this committed figure
    counts both scheduled and completed sessions (the forward-looking basis)."

    Design: Difficulty/dual_variant_calc/contract_utilization_committed_vs_verified_diverge
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    schedule_session(case["id"], provider["id"], "2026-03-03T10:00:00Z")
    # both merely SCHEDULED: committed basis still counts them -> 2/10 = 0.2
    committed = validate_success(api.get_contract(contract["id"], ADMIN))
    assert committed["sessions_committed"] == 2
    assert committed["utilization_rate"] == 0.2


# ===========================================================================
# Transitive cascade: terminate revoke/cancel/decrement/reject  (Difficulty)
# ===========================================================================
def test_contract_terminate_cascades_revoke_cancel_decrement_reject(api):
    """PRD §3.1: "Suspension and termination both fire the revoke cascade
    described in §3.4: every case on the contract whose `funding_status` is
    `AUTHORIZED` is driven to `REVOKED`, and each such revocation cancels that
    case's `SCHEDULED` sessions and decrements `sessions_committed` accordingly."
    PRD §3.4: "every counseling session on the case that is in `SCHEDULED` status
    is moved to `CANCELLED`; each such cancelled session decrements the funding
    contract's `sessions_committed`, keeping the annual-cap ledger in sync; and
    any claim that referenced one of those sessions and stood in `SUBMITTED` or
    `UNDER_REVIEW` status is moved to `REJECTED`."

    Design: Difficulty/transitive_cascade/contract_terminate_cascades_revoke_cancel_decrement_reject
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        plan_overrides={"copay_cents": 0},
        clock="2026-03-02T09:00:00Z")
    s_completed = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    s_scheduled = schedule_session(case["id"], provider["id"], "2026-03-04T10:00:00Z")
    complete_session(s_completed["id"], provider)
    claim = submit_claim(contract["id"], s_completed["id"], 12000, provider)

    terminated = validate_success(api.terminate_contract(
        contract["id"], {"expected_contract_version": contract["version"]}, ADMIN))
    assert terminated["status"] == "TERMINATED"
    # hop1: case revoked
    assert validate_success(api.get_case(case["id"], ADMIN))["funding_status"] == "REVOKED"
    # hop2: SCHEDULED session cancelled; the COMPLETED one is untouched
    assert validate_success(api.get_session(s_scheduled["id"], ADMIN))["status"] == "CANCELLED"
    assert validate_success(api.get_session(s_completed["id"], ADMIN))["status"] == "COMPLETED"
    # hop3: sessions_committed decremented to just the completed one
    assert terminated["sessions_committed"] == 1
    # hop3 per PRD §3.4: only claims that referenced one of the CANCELLED sessions
    # are rejected. This claim references the COMPLETED session (untouched above),
    # so it is not "one of those sessions" and remains SUBMITTED.
    assert validate_success(api.get_claim(claim["id"], ADMIN))["status"] == "SUBMITTED"


def test_contract_suspend_cascades_revoke_and_cancel(api):
    """PRD §3.1: "Suspension and termination both fire the revoke cascade
    described in §3.4: every case on the contract whose `funding_status` is
    `AUTHORIZED` is driven to `REVOKED`, and each such revocation cancels that
    case's `SCHEDULED` sessions and decrements `sessions_committed` accordingly."

    Design: Difficulty/transitive_cascade/contract_terminate_cascades_revoke_cancel_decrement_reject
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    s_scheduled = schedule_session(case["id"], provider["id"], "2026-03-04T10:00:00Z")
    suspended = validate_success(api.suspend_contract(
        contract["id"], {"expected_contract_version": contract["version"]}, ADMIN))
    assert suspended["status"] == "SUSPENDED"
    assert validate_success(api.get_case(case["id"], ADMIN))["funding_status"] == "REVOKED"
    assert validate_success(api.get_session(s_scheduled["id"], ADMIN))["status"] == "CANCELLED"
    assert suspended["sessions_committed"] == 0


# ===========================================================================
# Cross-entity state dependency: authorize requires ACTIVE contract  (Difficulty)
# ===========================================================================
def test_case_authorize_requires_contract_active(api):
    """PRD §3.3: "The funding contract's `status` must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/case_authorize_requires_contract_active
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    case = fx.create_case(contract["id"], employee["id"])
    suspended = validate_success(api.suspend_contract(
        contract["id"], {"expected_contract_version": contract["version"]}, ADMIN))
    validate_error(api.authorize_case(
        case["id"], {"expected_contract_version": suspended["version"]}, COORD),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    assert validate_success(api.get_case(case["id"], ADMIN))["funding_status"] == "PENDING"


def test_case_authorize_rejected_when_contract_terminated(api):
    """PRD §3.3: "The funding contract's `status` must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/case_authorize_requires_contract_active
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    case = fx.create_case(contract["id"], employee["id"])
    terminated = validate_success(api.terminate_contract(
        contract["id"], {"expected_contract_version": contract["version"]}, ADMIN))
    validate_error(api.authorize_case(
        case["id"], {"expected_contract_version": terminated["version"]}, COORD),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


# ===========================================================================
# Contract OCC corner cases
# ===========================================================================
def test_occ_correct_version_suspend_succeeds_and_bumps_version(api):
    """PRD §3.1: "Each of these four transitions requires the matching
    `expected_contract_version` and increments the contract's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_suspend_succeeds_and_bumps_version
    """
    contract = fx.create_contract(employer_name="OccCo")
    suspended = validate_success(api.suspend_contract(
        contract["id"], {"expected_contract_version": contract["version"]}, ADMIN))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2


def test_occ_stale_version_suspend_returns_412(api):
    """PRD §2.9: "If another writer has already reinstated or terminated the
    contract (each bumping the version) since the client's last read, the suspend
    is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) because the writer's
    view is stale."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_suspend_returns_412
    """
    contract = fx.create_contract(employer_name="StaleCo")
    v1 = contract["version"]
    suspended = validate_success(api.suspend_contract(
        contract["id"], {"expected_contract_version": v1}, ADMIN))
    v2 = suspended["version"]
    validate_success(api.reinstate_contract(
        contract["id"], {"expected_contract_version": v2}, ADMIN))
    # client still holds the v2 view, which is now stale
    validate_error(api.suspend_contract(
        contract["id"], {"expected_contract_version": v2}, ADMIN),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)


# ===========================================================================
# Reinstate does not restore revoked cases
# ===========================================================================
def test_contract_reinstate_does_not_restore_revoked_cases(api):
    """PRD §3.1: "Reinstatement bumps the version but does **not** restore
    previously revoked cases — revocation is permanent, and a reinstated contract
    starts fresh from its surviving state."

    Design: Corner/state_machines/contract_reinstate_does_not_restore_revoked_cases
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    case = fx.create_case(contract["id"], employee["id"])
    authorized = validate_success(api.authorize_case(
        case["id"], {"expected_contract_version": contract["version"]}, COORD))
    contract_now = validate_success(api.get_contract(contract["id"], ADMIN))
    suspended = validate_success(api.suspend_contract(
        contract["id"], {"expected_contract_version": contract_now["version"]}, ADMIN))
    reinstated = validate_success(api.reinstate_contract(
        contract["id"], {"expected_contract_version": suspended["version"]}, ADMIN))
    assert reinstated["status"] == "ACTIVE"
    assert validate_success(api.get_case(case["id"], ADMIN))["funding_status"] == "REVOKED"


# ===========================================================================
# Immediate consistency of the revoke cascade
# ===========================================================================
def test_revoke_cascade_visible_in_same_request_immediate(api):
    """PRD §3.4: "Driving a case to `REVOKED` performs three cascade hops in
    sequence: every counseling session on the case that is in `SCHEDULED` status
    is moved to `CANCELLED`; each such cancelled session decrements the funding
    contract's `sessions_committed`, keeping the annual-cap ledger in sync; and
    any claim that referenced one of those sessions and stood in `SUBMITTED` or
    `UNDER_REVIEW` status is moved to `REJECTED`."

    Design: Corner/consistency_model/revoke_cascade_visible_in_same_request_immediate
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    revoked = validate_success(api.revoke_case(case["id"], ADMIN))
    assert revoked["funding_status"] == "REVOKED"
    assert validate_success(api.get_session(s1["id"], COORD))["status"] == "CANCELLED"
