"""Dispatch assignment, the field lifecycle, and dispatch-time guards."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_field_officer_headers,
    set_clock, make_complaint, make_officer, make_pending_dispatch,
    accept_dispatch, clear_dispatch, setup_en_route_dispatch,
    create_dispatch_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ==========================================================================
# Difficulty: cross_entity_state_dependency / dispatch_blocked_by_officer_off_duty
# ==========================================================================
def test_dispatch_rejected_when_officer_off_duty(api):
    """PRD 3.2: "The officer must be on duty — the logical clock must fall
    within the inclusive interval from shift_start_at to shift_end_at,
    otherwise ERR_OFFICER_OFF_DUTY."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_officer_off_duty
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    complaint = make_complaint(api, reporter_name="R11", complaint_type="STRAY")
    officer = make_officer(api, name="Ofc J", badge_number="B11",
                           shift_start_at="2026-03-05T08:00:00Z", shift_end_at="2026-03-05T17:00:00Z")
    resp = api.create_dispatch(create_dispatch_payload(
        complaint["id"], officer["id"],
        scheduled_start_at="2026-03-05T09:00:00Z", scheduled_end_at="2026-03-05T10:00:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_OFFICER_OFF_DUTY)


def test_off_duty_dispatch_leaves_complaint_new(api):
    """PRD 3.2: "The complaint must be in status NEW; a dispatch against a
    complaint in any other status is rejected with ERR_COMPLAINT_NOT_DISPATCHABLE."
    PRD 3.2: "Creating it advances the linked complaint from NEW to DISPATCHED,
    incrementing that complaint's version by one, and raises the assigned
    officer's active_dispatch_count by one."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_officer_off_duty
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    complaint = make_complaint(api, reporter_name="R11", complaint_type="STRAY")
    officer = make_officer(api, name="Ofc J", badge_number="B11",
                           shift_start_at="2026-03-05T08:00:00Z", shift_end_at="2026-03-05T17:00:00Z")
    resp = api.create_dispatch(create_dispatch_payload(
        complaint["id"], officer["id"],
        scheduled_start_at="2026-03-05T09:00:00Z", scheduled_end_at="2026-03-05T10:00:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_OFFICER_OFF_DUTY)
    # The failed dispatch must not have advanced the complaint out of NEW.
    complaint_after = validate_success(api.get_complaint(complaint["id"], DISPATCHER))
    assert complaint_after["status"] == "NEW"


# ==========================================================================
# Corner: state_machines
# ==========================================================================
def test_new_dispatch_starts_pending(api):
    """PRD 3.2: "When all guards pass, the dispatch is created in status PENDING."

    Design: Corner/state_machines/dispatch_initial_state_is_pending
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    complaint = make_complaint(api, reporter_name="IS1", complaint_type="STRAY")
    officer = make_officer(api, name="IS Ofc", badge_number="ISB1")
    dispatch = validate_success(api.create_dispatch(create_dispatch_payload(
        complaint["id"], officer["id"]), DISPATCHER), expected_status=201)
    assert dispatch["status"] == "PENDING"


def test_clear_dispatch_resolves_complaint_and_frees_officer(api):
    """PRD 3.3: "it decrements the officer's active_dispatch_count by one (the
    dispatch has left the active set), and it advances the linked complaint from
    DISPATCHED to RESOLVED, incrementing the complaint's version."

    Design: Corner/state_machines/clear_dispatch_cascades_complaint_to_resolved
    """
    ctx = setup_en_route_dispatch(api)
    cleared = clear_dispatch(api, ctx["dispatch"]["id"], ctx["officer"]["id"], "RESOLVED_ON_SCENE")
    assert cleared["status"] == "CLEARED"
    complaint_after = validate_success(api.get_complaint(ctx["complaint"]["id"], DISPATCHER))
    assert complaint_after["status"] == "RESOLVED"
    officer_after = validate_success(api.get_officer(ctx["officer"]["id"], SUPERVISOR))
    assert officer_after["active_dispatch_count"] == 0


def test_accept_cleared_dispatch_is_invalid_state(api):
    """PRD 3.3: "Accepting requires the dispatch to be in PENDING; from any other
    state the transition is an invalid-state error."

    Design: Corner/state_machines/accept_cleared_dispatch_returns_invalid_state
    """
    ctx = setup_en_route_dispatch(api)
    clear_dispatch(api, ctx["dispatch"]["id"], ctx["officer"]["id"], "RESOLVED_ON_SCENE")
    resp = api.accept_dispatch(ctx["dispatch"]["id"], make_field_officer_headers(ctx["officer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Corner: validations
# ==========================================================================
def test_second_dispatch_exceeds_officer_capacity(api):
    """PRD 3.2: "Finally, the officer's active_dispatch_count must be strictly
    below max_daily_dispatches, otherwise ERR_OFFICER_CAPACITY_EXCEEDED."

    Design: Corner/validations/officer_capacity_exceeded_on_second_dispatch
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    c1 = make_complaint(api, reporter_name="CE1", complaint_type="STRAY")
    c2 = make_complaint(api, reporter_name="CE2", complaint_type="STRAY")
    officer = make_officer(api, name="Cap Ofc", badge_number="CAPB1", max_daily_dispatches=1)
    make_pending_dispatch(api, c1["id"], officer["id"],
                          scheduled_start_at="2026-03-01T09:00:00Z", scheduled_end_at="2026-03-01T10:00:00Z")
    resp = api.create_dispatch(create_dispatch_payload(
        c2["id"], officer["id"],
        scheduled_start_at="2026-03-01T12:00:00Z", scheduled_end_at="2026-03-01T13:00:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_OFFICER_CAPACITY_EXCEEDED)


# ==========================================================================
# Corner: endpoints (listing)
# ==========================================================================
def test_list_dispatches_filtered_by_officer(api):
    """PRD 3.2: "Dispatches may be listed and filtered by complaint_id, by
    officer_id, and by status." PRD 2.3: "total_count is the number of matching
    rows before pagination."

    Design: Corner/endpoints/list_dispatches_filtered_by_officer
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    c1 = make_complaint(api, reporter_name="LD1", complaint_type="STRAY")
    c2 = make_complaint(api, reporter_name="LD2", complaint_type="STRAY")
    officer = make_officer(api, name="LD Ofc", badge_number="LDB1")
    make_pending_dispatch(api, c1["id"], officer["id"],
                          scheduled_start_at="2026-03-01T09:00:00Z", scheduled_end_at="2026-03-01T10:00:00Z")
    make_pending_dispatch(api, c2["id"], officer["id"],
                          scheduled_start_at="2026-03-01T11:00:00Z", scheduled_end_at="2026-03-01T12:00:00Z")
    resp = api.list_dispatches(DISPATCHER, params={"officer_id": officer["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(d["officer_id"] == officer["id"] for d in data)


# ==========================================================================
# Corner: rbac (ownership)
# ==========================================================================
def test_unassigned_officer_cannot_accept_dispatch(api):
    """PRD 3.3: "only the officer whose id matches the dispatch's officer_id may
    do so, and an attempt by anyone else is ERR_NOT_ASSIGNED_OFFICER."

    Design: Corner/rbac/accept_dispatch_by_unassigned_officer_rejected
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    complaint = make_complaint(api, reporter_name="OW1", complaint_type="STRAY")
    officer_a = make_officer(api, name="Ofc A2", badge_number="AB2")
    officer_b = make_officer(api, name="Ofc B2", badge_number="BB2")
    dispatch = make_pending_dispatch(api, complaint["id"], officer_a["id"])
    resp = api.accept_dispatch(dispatch["id"], make_field_officer_headers(officer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_OFFICER)
