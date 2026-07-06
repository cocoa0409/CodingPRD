"""Screening gates, the result-delivery fork, and abnormal-result navigation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    fixtures,
)

PM = TEST_USERS["program_manager_headers"]
CS = TEST_USERS["clinical_staff_headers"]
NAV = TEST_USERS["patient_navigator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def _referrals_for(api, appointment_id):
    return validate_paginated(api.list_referrals(NAV, params={"appointment_id": appointment_id}))


# ---------------------------------------------------------------------------
# Corner: state_machines — screen requires credentialed staff
# ---------------------------------------------------------------------------
def test_screen_without_credentialed_staff_returns_error(api):
    """PRD §3.5: "The appointment must be `CHECKED_IN` (otherwise `ERR_INVALID_STATE`), and
    there must exist a staff member who is `ACTIVE`, whose `modality` equals the event's
    modality, and whose `role_type` is `TECHNOLOGIST` or `PHLEBOTOMIST` (otherwise
    `ERR_NO_CREDENTIALED_STAFF`) — the roster gates the screening."

    Design: Corner/state_machines/screen_without_credentialed_staff_returns_error
    """
    # Published event but NO credentialed staff registered.
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    validate_success(api.consent_appointment(appt["id"], CS))
    validate_success(api.checkin_appointment(appt["id"], CS))
    resp = api.screen_appointment(appt["id"], CS)
    validate_error(resp, ApiErrorId.ERR_NO_CREDENTIALED_STAFF.value)
    reread = validate_success(api.get_appointment(appt["id"], CS))
    assert reread["status"] == "CHECKED_IN"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — abnormal result spawns referral
# ---------------------------------------------------------------------------
def test_abnormal_result_spawns_open_referral(api):
    """PRD §3.5: "Here the workflow forks: when the result is `ABNORMAL`, a referral is
    created in `OPEN` for this appointment (its priority and deadline are set per §3.6);
    when the result is `NORMAL`, no referral is created."

    Design: Difficulty/non_linear_state_machine/appointment_branch_abnormal_spawns_referral
    """
    ctx = fixtures.create_screened_appointment(pay_type="INSURANCE", modality="MAMMOGRAPHY",
                                              insurance_member_id="INS-A")
    appt = validate_success(api.deliver_result(ctx["appointment"]["id"],
                                              {"result": "ABNORMAL", "flagged_urgent": True}, CS))
    assert appt["result"] == "ABNORMAL", f"expected ABNORMAL, got {appt['result']}"
    assert appt["status"] == "RESULT_READY", f"expected RESULT_READY, got {appt['status']}"
    refs, meta = _referrals_for(api, appt["id"])
    assert meta["total_count"] == 1, f"expected 1 referral, got {meta['total_count']}"
    assert refs[0]["status"] == "OPEN", f"expected OPEN referral, got {refs[0]['status']}"
    assert refs[0]["priority"] == "URGENT", f"expected URGENT, got {refs[0]['priority']}"


def test_normal_result_spawns_no_referral(api):
    """PRD §3.5: "when the result is `ABNORMAL`, a referral is created in `OPEN` for this
    appointment (its priority and deadline are set per §3.6); when the result is `NORMAL`,
    no referral is created."

    Design: Difficulty/non_linear_state_machine/appointment_branch_abnormal_spawns_referral
    """
    ctx = fixtures.create_screened_appointment(pay_type="INSURANCE", modality="MAMMOGRAPHY",
                                              insurance_member_id="INS-B")
    appt = validate_success(api.deliver_result(ctx["appointment"]["id"], {"result": "NORMAL"}, CS))
    assert appt["result"] == "NORMAL", f"expected NORMAL, got {appt['result']}"
    assert appt["status"] == "RESULT_READY", f"expected RESULT_READY, got {appt['status']}"
    refs, meta = _referrals_for(api, appt["id"])
    assert meta["total_count"] == 0, f"expected no referral for NORMAL, got {meta['total_count']}"


# ---------------------------------------------------------------------------
# Corner: calculations — referral urgent SLA due date
# ---------------------------------------------------------------------------
def test_referral_urgent_sla_due_date(api):
    """PRD §3.6: "Its `priority` is derived at creation from the `flagged_urgent` flag
    supplied at result delivery: when `flagged_urgent` is true the priority is `URGENT`,
    otherwise it is `ROUTINE`. The referral's `due_by_date` is the deadline for navigation
    contact, computed as the event's `event_date` plus a service-level number of calendar
    days — 7 days for an `URGENT` referral and 30 days for a `ROUTINE` referral."

    Design: Corner/calculations/referral_urgent_sla_due_date
    """
    # Event date 2026-06-10, urgent → 2026-06-10 + 7 = 2026-06-17
    ctx = fixtures.create_screened_appointment(pay_type="SELF_PAY", modality="MAMMOGRAPHY",
                                              event_date="2026-06-10")
    appt = validate_success(api.deliver_result(ctx["appointment"]["id"],
                                              {"result": "ABNORMAL", "flagged_urgent": True}, CS))
    refs, meta = _referrals_for(api, appt["id"])
    ref = refs[0]
    assert ref["priority"] == "URGENT", f"expected URGENT, got {ref['priority']}"
    assert ref["due_by_date"] == "2026-06-17", f"expected 2026-06-17, got {ref['due_by_date']}"


# ---------------------------------------------------------------------------
# Corner: state_machines — referral resolve from OPEN invalid
# ---------------------------------------------------------------------------
def test_referral_resolve_from_open_returns_invalid_state(api):
    """PRD §3.6: "resolves the referral, advancing `SCHEDULED_FOLLOWUP` to `RESOLVED`
    (must be `SCHEDULED_FOLLOWUP`, otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/referral_resolve_from_open_returns_invalid_state
    """
    ctx = fixtures.create_result_ready_appointment(result="ABNORMAL", flagged_urgent=False,
                                                 modality="MAMMOGRAPHY", pay_type="SELF_PAY")
    ref = ctx["referral"]
    resp = api.resolve_referral(ref["id"], NAV)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_referral(ref["id"], NAV))
    assert reread["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — close abnormal requires referral terminal
# ---------------------------------------------------------------------------
def test_close_abnormal_appointment_with_open_referral_rejected(api):
    """PRD §3.5: "When the appointment's `result` was `ABNORMAL`, its linked referral must
    already be in a terminal state — `RESOLVED` or `LOST_TO_FOLLOWUP` — or closure is
    rejected with `ERR_REFERRAL_UNRESOLVED`; a `NORMAL` appointment has no such gate."

    Design: Difficulty/cross_entity_state_dependency/close_abnormal_appointment_requires_referral_terminal
    """
    ctx = fixtures.create_result_ready_appointment(result="ABNORMAL", flagged_urgent=False,
                                                 modality="MAMMOGRAPHY", pay_type="SELF_PAY")
    resp = api.close_appointment(ctx["appointment"]["id"], CS)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_UNRESOLVED.value)
    reread = validate_success(api.get_appointment(ctx["appointment"]["id"], CS))
    assert reread["status"] == "RESULT_READY"


def test_close_abnormal_appointment_after_referral_resolved_succeeds(api):
    """PRD §3.5: "When the appointment's `result` was `ABNORMAL`, its linked referral must
    already be in a terminal state — `RESOLVED` or `LOST_TO_FOLLOWUP` — or closure is
    rejected with `ERR_REFERRAL_UNRESOLVED`; a `NORMAL` appointment has no such gate."

    Design: Difficulty/cross_entity_state_dependency/close_abnormal_appointment_requires_referral_terminal
    """
    ctx = fixtures.create_result_ready_appointment(result="ABNORMAL", flagged_urgent=False,
                                                 modality="MAMMOGRAPHY", pay_type="SELF_PAY")
    ref = ctx["referral"]
    validate_success(api.contact_referral(ref["id"], NAV))
    validate_success(api.schedule_followup_referral(ref["id"], NAV))
    validate_success(api.resolve_referral(ref["id"], NAV))
    data = validate_success(api.close_appointment(ctx["appointment"]["id"], CS))
    assert data["status"] == "CLOSED", f"expected CLOSED, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner: rbac — billing clerk cannot contact referral
# ---------------------------------------------------------------------------
def test_billing_clerk_cannot_contact_referral(api):
    """PRD §2.1: "A `PatientNavigator` owns abnormal-result navigation — contacting
    participants, scheduling follow-ups, and resolving or marking referrals lost."
    PRD §2.1: "When a caller holds a valid role but that role is not permitted for the
    requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/billing_clerk_cannot_contact_referral
    """
    ctx = fixtures.create_result_ready_appointment(result="ABNORMAL", flagged_urgent=False,
                                                 modality="MAMMOGRAPHY", pay_type="SELF_PAY")
    ref = ctx["referral"]
    resp = api.contact_referral(ref["id"], BC)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
