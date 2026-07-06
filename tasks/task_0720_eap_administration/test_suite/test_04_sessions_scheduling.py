"""Counseling session scheduling: temporal collisions and ledger invariants."""
import pytest
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_authorized_case, schedule_session,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


def _two_authorized_cases_one_provider(per_issue=3):
    """Helper: one contract + provider + two AUTHORIZED cases for two employees."""
    contract, plan = None, None
    contract = fx.create_contract(sessions_per_issue=per_issue, annual_session_cap=10)
    plan = fx.create_published_plan(contract["id"])
    e1 = fx.create_employee(contract["id"], plan["id"], full_name="O1", external_ref="EO1")
    e2 = fx.create_employee(contract["id"], plan["id"], full_name="O2", external_ref="EO2")
    provider = fx.create_provider(full_name="Dr O", specialties=["STRESS"])
    case1 = fx.create_case(contract["id"], e1["id"])
    case1 = validate_success(fx.api_client.authorize_case(
        case1["id"], {"expected_contract_version": contract["version"]}, COORD))
    c_now = validate_success(fx.api_client.get_contract(contract["id"], ADMIN))
    case2 = fx.create_case(contract["id"], e2["id"])
    case2 = validate_success(fx.api_client.authorize_case(
        case2["id"], {"expected_contract_version": c_now["version"]}, COORD))
    fx.set_clock("2026-03-02T09:00:00Z")
    return contract, provider, case1, case2


# ===========================================================================
# Resource temporal overlap: provider minute-level double booking  (Difficulty)
# ===========================================================================
def test_provider_double_booked_minute_overlap(api):
    """PRD §3.5: "A provider's sessions may not overlap in time: if the chosen
    provider already holds a `SCHEDULED` session whose interval — from its start
    through its start plus its planned duration — overlaps the newly requested
    interval, the request is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/provider_double_booked_minute_overlap
    """
    contract, provider, case1, case2 = _two_authorized_cases_one_provider()
    schedule_session(case1["id"], provider["id"], "2026-03-02T10:00:00Z", duration_minutes=50)
    # case2 session at 10:30 overlaps 10:00-10:50 for the same provider
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-02T10:30:00Z",
               "duration_minutes": 50}
    validate_error(api.create_session(case2["id"], payload, COORD),
                   ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED.value)


def test_provider_non_overlapping_back_to_back_allowed(api):
    """PRD §3.5: "A provider's sessions may not overlap in time: if the chosen
    provider already holds a `SCHEDULED` session whose interval — from its start
    through its start plus its planned duration — overlaps the newly requested
    interval, the request is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/provider_double_booked_minute_overlap
    """
    # Different days so the case same-day rule is not triggered, and the provider
    # intervals do not overlap -> the second schedule succeeds.
    contract, provider, case1, case2 = _two_authorized_cases_one_provider()
    schedule_session(case1["id"], provider["id"], "2026-03-02T10:00:00Z", duration_minutes=50)
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-03T12:00:00Z",
               "duration_minutes": 50}
    created = validate_success(api.create_session(case2["id"], payload, COORD), 201)
    assert created["status"] == "SCHEDULED"


# ===========================================================================
# Resource temporal overlap: case same-day bucket  (Difficulty)
# ===========================================================================
def test_case_same_day_session_daybucket(api):
    """PRD §3.5: "a single case may not hold two `SCHEDULED` sessions that fall on
    the same UTC calendar day; this same-day collision, distinct from the
    provider's minute-level overlap, is rejected with `ERR_CASE_SAME_DAY_SESSION`."

    Design: Difficulty/resource_temporal_overlap/case_same_day_session_daybucket
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z", duration_minutes=50)
    # same case, same UTC day, no time overlap (14:00) -> still rejected
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-02T14:00:00Z",
               "duration_minutes": 50}
    validate_error(api.create_session(case["id"], payload, COORD),
                   ApiErrorId.ERR_CASE_SAME_DAY_SESSION.value)


def test_case_different_day_session_allowed(api):
    """PRD §3.5: "a single case may not hold two `SCHEDULED` sessions that fall on
    the same UTC calendar day; this same-day collision, distinct from the
    provider's minute-level overlap, is rejected with `ERR_CASE_SAME_DAY_SESSION`."

    Design: Difficulty/resource_temporal_overlap/case_same_day_session_daybucket
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z", duration_minutes=50)
    # next calendar day -> allowed
    payload = {"provider_id": provider["id"], "scheduled_for": "2026-03-03T10:00:00Z",
               "duration_minutes": 50}
    created = validate_success(api.create_session(case["id"], payload, COORD), 201)
    assert created["status"] == "SCHEDULED"


# ===========================================================================
# Compensating invariant: schedule then cancel preserves committed  (Difficulty)
# ===========================================================================
def test_schedule_then_cancel_session_preserves_committed(api):
    """PRD §3.1: "The `sessions_committed` count is the number of counseling
    sessions in `SCHEDULED` or `COMPLETED` status across every case of the
    contract — this is what the annual cap is measured against."
    PRD §3.5: "Cancelling a session frees the allotment slot it held, which in
    turn lowers the case's `sessions_used` and the contract's `sessions_committed`
    for any session that had been counted."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_session_preserves_committed
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    # pre-cancel: committed went to 1
    assert validate_success(api.get_contract(contract["id"], ADMIN))["sessions_committed"] == 1
    cancelled = validate_success(api.set_session_status(
        s1["id"], {"to_status": "CANCELLED"}, COORD))
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_contract(contract["id"], ADMIN))["sessions_committed"] == 0
    assert validate_success(api.get_case(case["id"], ADMIN))["sessions_used"] == 0


def test_cancel_session_lowers_case_sessions_used(api):
    """PRD §3.5: "Cancelling a session frees the allotment slot it held, which in
    turn lowers the case's `sessions_used` and the contract's `sessions_committed`
    for any session that had been counted."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_session_preserves_committed
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 3, "annual_session_cap": 10},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    assert validate_success(api.get_case(case["id"], ADMIN))["sessions_used"] == 1
    validate_success(api.set_session_status(s1["id"], {"to_status": "CANCELLED"}, COORD))
    after = validate_success(api.get_case(case["id"], ADMIN))
    assert after["sessions_used"] == 0


# ===========================================================================
# FK reverse listing
# ===========================================================================
def test_fk_reverse_list_sessions_by_case(api):
    """PRD §2.3: "Unless an endpoint states otherwise, all list responses are
    sorted by each resource's creation timestamp in ascending order."

    Design: Corner/endpoints/fk_reverse_list_sessions_by_case
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    data, meta = validate_paginated(api.list_sessions(COORD, params={"case_id": case["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == s1["id"]
