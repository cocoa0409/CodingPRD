"""Authentication / RBAC / audit logging."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_operating_room_payload,
    create_surgical_case_payload,
    create_surgical_case,
    approve_case,
    setup_scheduled_general_case,
    get_audit_entries,
)


SCHED = TEST_USERS["scheduler_headers"]
COORD = TEST_USERS["surgical_coordinator_headers"]
DEPT = TEST_USERS["department_head_headers"]


# ─── Auth / RBAC ─────────────────────────────────────────────────────────

def test_missing_user_id_header(api):
    """PRD §2.1: 'Every request must include the headers `X-User-ID` and `X-User-Role`.
    If either header is missing or empty, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP status 400.'"""
    headers = {"X-User-Role": "Scheduler"}  # no X-User-ID
    res = api.create_operating_room(create_operating_room_payload(), headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_empty_user_id_header(api):
    """PRD §2.1: 'If either header is missing or empty, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`'."""
    headers = {"X-User-ID": "", "X-User-Role": "Scheduler"}
    res = api.create_operating_room(create_operating_room_payload(), headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_missing_role_header(api):
    """PRD §2.1: 'If either header is missing or empty, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`'."""
    headers = {"X-User-ID": "user-1"}  # no X-User-Role
    res = api.create_operating_room(create_operating_room_payload(), headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


@pytest.mark.parametrize(
    "wrong_role",
    [
        "DepartmentHead",
        "BillingAdmin",
    ],
)
def test_create_operating_room_rbac_rejects_other_roles(api, wrong_role):
    """PRD §4: 'POST /operating-rooms' is restricted to Scheduler.
    PRD §2.1: 'If the role-bearing headers are present but the role is not on the
    authorized list for the requested operation, the server rejects the call with
    `ERR_INSUFFICIENT_PERMISSIONS` and HTTP status 403'."""
    headers = build_user_headers(f"u-{wrong_role}", wrong_role)
    res = api.create_operating_room(create_operating_room_payload(), headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_billing_admin_cannot_approve_case(api):
    """PRD §4: 'POST /surgical-cases/{caseId}/approve' is restricted to
    DepartmentHead. BillingAdmin must be rejected with `ERR_INSUFFICIENT_PERMISSIONS`."""
    case = create_surgical_case(pre_op_assessment_attached=True, informed_consent_verified=True)
    res = api.approve_case(case["id"], TEST_USERS["billing_admin_headers"])
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_invalid_request_body_type(api):
    """PRD §2.6 ladder #14: 'Schema and value-range checks on the request body
    (`ERR_INVALID_REQUEST`)'."""
    payload = create_surgical_case_payload()
    payload["implant_cost_estimate"] = "not-a-number"  # type mismatch
    res = api.create_surgical_case(payload, COORD)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_invalid_planned_end_lower_than_start_at_schedule(api):
    """PRD §3.3: 'an integer `planned_end_minute` (which must be strictly greater
    than `planned_start_minute`; otherwise `ERR_INVALID_TIME_PARAMETERS`)'."""
    from test_helpers import (
        create_operating_room,
        create_anesthesiologist,
        create_instrument_set,
        create_schedule_payload,
        make_staff_assignment,
    )
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    anesth = create_anesthesiologist()
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    payload = create_schedule_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=100,
        planned_end_minute=100,  # equal, not strictly greater
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_INVALID_TIME_PARAMETERS")


def test_clock_advance_must_be_positive(api):
    """PRD §2.5: 'the request body supplies a `delta_minutes` integer (which must
    be greater than 0; otherwise the request is rejected with
    `ERR_INVALID_TIME_PARAMETERS`)'."""
    res = api.advance_clock({"delta_minutes": 0}, SCHED)
    validate_error(res, "ERR_INVALID_TIME_PARAMETERS")


# ─── Audit logging ────────────────────────────────────────────────────────

def test_audit_entry_written_on_case_request(api):
    """PRD §2.8: 'a logical action label such as `'CASE_REQUESTED'`, ...'.
    PRD §3.2: 'A successful creation initialises the case's `status` to
    `REQUESTED`, ... and writes an `AuditEntry` whose `action` is `'CASE_REQUESTED'`'."""
    case = create_surgical_case()
    entries = get_audit_entries(entity_type="SurgicalCase", entity_id=case["id"], action="CASE_REQUESTED")
    assert len(entries) >= 1


def test_audit_entry_written_on_case_approved(api):
    """PRD §3.2: 'and writes an `AuditEntry` with `action` `'CASE_APPROVED'`.'"""
    case = create_surgical_case(pre_op_assessment_attached=True, informed_consent_verified=True)
    approve_case(case["id"])
    entries = get_audit_entries(entity_type="SurgicalCase", entity_id=case["id"], action="CASE_APPROVED")
    assert len(entries) >= 1


def test_audit_entry_carries_actor_metadata(api):
    """PRD §2.8: 'Each audit row carries `actor_role` (the request's `X-User-Role`),
    `actor_user_id` (the request's `X-User-ID`)'."""
    case = create_surgical_case()  # created via SurgicalCoordinator
    entries = get_audit_entries(entity_type="SurgicalCase", entity_id=case["id"])
    assert len(entries) >= 1
    e = entries[0]
    assert e["actor_role"] == "SurgicalCoordinator"
    assert e["actor_user_id"] == "test-surgical-coordinator-1"
    assert "occurred_at_minute" in e
