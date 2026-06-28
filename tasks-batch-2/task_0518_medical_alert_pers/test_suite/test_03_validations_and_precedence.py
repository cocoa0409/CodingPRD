"""Validation rules, cross-entity gates, temporal-overlap conflicts, and the validation-
precedence pairs.

Covers difficulty Rules 5, 7, 8 and the corner validations section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    make_subscriber_headers, make_agent_headers, TEST_USERS,
    create_plan_payload, create_shift_payload, create_hold_payload,
    setup_active_contract_with_device, setup_suspended_contract_with_device,
    setup_registered_device, setup_escalating_alarm_two_contacts, setup_assigned_alarm,
    setup_plan_subscriber_contract,
    set_clock, request_cancellation_active, create_shift, create_contact,
    raise_alarm, assign_alarm, dispatch, drive_contract_to_suspended, create_subscriber,
    cancel_via_suspended_and_finalize,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Rule 7 — cross-entity state dependencies
# ===========================================================================
def test_alarm_on_suspended_contract_rejected(api):
    """PRD 3.8: "An alarm may only be raised on a device whose contract `service_status` is
    `ACTIVE`; a suspended or cancelled contract does not monitor, so the attempt is rejected
    with `ERR_CONTRACT_NOT_MONITORING`."

    Design: Difficulty/cross_entity_state_dependency/alarm_create_requires_contract_active
    """
    plan, sub, contract, device = setup_suspended_contract_with_device(clock="2026-06-01T00:00:00Z")
    res = api.raise_alarm(device["id"], {"signal_type": "MANUAL_BUTTON"},
                          make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_CONTRACT_NOT_MONITORING")


def test_finalize_blocked_by_open_alarm(api):
    """PRD 3.7: "finalization is blocked while any device under the contract is still `ACTIVE`
    or `NEEDS_TEST`, or while any alarm under any of the contract's devices is in a
    non-terminal status, with rejection code `ERR_LIVE_MONITORING_BLOCKS_CANCEL` — the system
    must never strand a live monitored device."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_open_alarm_contract_alarm_pair
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    # Raise an alarm (non-terminal SIGNAL_RECEIVED), then request cancellation, advance, finalize.
    raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    request_cancellation_active(contract)
    set_clock("2026-07-02T00:00:00Z")
    res = api.finalize_cancellation(contract["id"], ADMIN)
    validate_error(res, "ERR_LIVE_MONITORING_BLOCKS_CANCEL")
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["status"] == "ACTIVE", "device must remain ACTIVE when safety gate blocks finalize"


def test_alarm_on_cancelled_contract_rejected(api):
    """PRD 3.8: "An alarm may only be raised on a device whose contract `service_status` is
    `ACTIVE`; a suspended or cancelled contract does not monitor, so the attempt is rejected
    with `ERR_CONTRACT_NOT_MONITORING`."

    Design: Difficulty/cross_entity_state_dependency/alarm_create_requires_contract_active
    """
    # Different non-ACTIVE service_status (CANCELLED via finalize) for the same Device->Contract
    # dependency: the device's legal alarm-create depends on its contract's state.
    # PRD 3.7 blocks finalization while a device is ACTIVE/NEEDS_TEST; reach the CANCELLED
    # state through SUSPENDED (the only PRD path that vacates ACTIVE without finalizing).
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    cancel_via_suspended_and_finalize(contract["id"])
    res = api.raise_alarm(device["id"], {"signal_type": "MANUAL_BUTTON"},
                          make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_CONTRACT_NOT_MONITORING")


def test_finalize_blocked_alarm_does_not_cancel_contract(api):
    """PRD 3.7: "finalization is blocked while any device under the contract is still `ACTIVE`
    or `NEEDS_TEST`, or while any alarm under any of the contract's devices is in a
    non-terminal status, with rejection code `ERR_LIVE_MONITORING_BLOCKS_CANCEL` — the system
    must never strand a live monitored device."

    The blocked finalize must leave the contract un-cancelled (still CANCELLATION_REQUESTED),
    confirming the non-terminal alarm aborts the transition rather than partially applying it.

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_open_alarm_contract_alarm_pair
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    request_cancellation_active(contract)
    set_clock("2026-07-02T00:00:00Z")
    res = api.finalize_cancellation(contract["id"], ADMIN)
    validate_error(res, "ERR_LIVE_MONITORING_BLOCKS_CANCEL")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    assert contract["service_status"] == "CANCELLATION_REQUESTED", (
        "blocked finalize must not advance service_status to CANCELLED"
    )


# ===========================================================================
# Rule 8 — resource temporal-overlap conflicts
# ===========================================================================
def test_agent_shift_half_open_overlap_rejected(api):
    """PRD 3.9: "A new shift whose half-open interval intersects an existing `SCHEDULED` shift
    for the same `agent_user_id` is rejected with `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agent_shift_half_open_overlap_zero_buffer
    """
    create_shift("agent-3", "2026-06-01T06:00:00Z", "2026-06-01T18:00:00Z")
    res = api.create_shift(
        create_shift_payload("agent-3", "2026-06-01T00:00:00Z", "2026-06-01T12:00:00Z"), ADMIN)
    validate_error(res, "ERR_SHIFT_OVERLAP")


def test_agent_shift_adjacent_allowed_zero_buffer(api):
    """PRD 3.9: "two `SCHEDULED` shifts for the same agent may be exactly adjacent (one shift's
    `ends_at` equal to the next's `starts_at`) but must not otherwise overlap."

    Design: Difficulty/resource_temporal_overlap/agent_shift_half_open_overlap_zero_buffer
    """
    create_shift("agent-3b", "2026-06-01T06:00:00Z", "2026-06-01T18:00:00Z")
    # New shift starting exactly at prior end is allowed.
    res = api.create_shift(
        create_shift_payload("agent-3b", "2026-06-01T18:00:00Z", "2026-06-02T06:00:00Z"), ADMIN)
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


def test_monitoring_hold_buffered_overlap_rejected(api):
    """PRD 3.12: "A new hold is rejected with `ERR_HOLD_OVERLAP` unless its start is at least 7
    days after an existing hold's `ends_at`, or its end plus 7 days is at or before that
    existing hold's `starts_at` — in other words, it is rejected whenever its window comes
    within 7 days of any existing scheduled hold on that device."

    Design: Difficulty/resource_temporal_overlap/monitoring_hold_buffered_overlap_seven_day_gap
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    get_success_data(api.create_hold(
        create_hold_payload(device["id"], "2026-06-05T00:00:00Z", "2026-06-10T00:00:00Z"),
        make_subscriber_headers(sub["id"])))
    # New hold starts 2026-06-13 (only 3 days after prior end) -> within 7-day buffer.
    res = api.create_hold(
        create_hold_payload(device["id"], "2026-06-13T00:00:00Z", "2026-06-20T00:00:00Z"),
        make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_HOLD_OVERLAP")


def test_monitoring_hold_outside_buffer_allowed(api):
    """PRD 3.12: "A new hold is rejected with `ERR_HOLD_OVERLAP` unless its start is at least 7
    days after an existing hold's `ends_at`, or its end plus 7 days is at or before that
    existing hold's `starts_at`".

    Design: Difficulty/resource_temporal_overlap/monitoring_hold_buffered_overlap_seven_day_gap
    """
    # Existing hold ends 2026-06-10; a new hold starting exactly 7 days later (2026-06-17) is
    # outside the buffer and must be accepted — the satisfied side of the 7-day rule.
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    hdrs = make_subscriber_headers(sub["id"])
    get_success_data(api.create_hold(
        create_hold_payload(device["id"], "2026-06-05T00:00:00Z", "2026-06-10T00:00:00Z"), hdrs))
    res = api.create_hold(
        create_hold_payload(device["id"], "2026-06-17T00:00:00Z", "2026-06-20T00:00:00Z"), hdrs)
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED", "hold starting >= 7 days after prior end must be allowed"


# ===========================================================================
# Rule 5 — validation-precedence pairs
# ===========================================================================
def test_second_cancellation_request_state_beats_stale_version(api):
    """PRD 2.9: "Only after these gates does the system evaluate state-machine legality
    (`ERR_INVALID_STATE`) and the remaining domain rules."
    PRD 3.7: "Cancellation may be requested from either `ACTIVE` or `SUSPENDED` service status;
    from any other state the request yields `ERR_INVALID_STATE`."

    State-machine legality (ERR_INVALID_STATE) precedes the OCC/domain rule, so a second
    request-cancellation on a CANCELLATION_REQUESTED contract — even carrying a stale version —
    surfaces ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/request_cancellation_state_beats_fiscal
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    stale_version = contract["version"]
    request_cancellation_active(contract)  # now CANCELLATION_REQUESTED, version advanced
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": stale_version},
        make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_finalize_before_effective_with_active_device(api):
    """PRD 3.7: "Finalizing a cancellation is a `PlatformAdmin` action permitted only when
    `service_status` is `CANCELLATION_REQUESTED` and the clock has reached or passed
    `cancellation_effective_at`; a premature attempt is rejected with `ERR_TEMPORAL_NOT_DUE`,
    and a wrong-state attempt yields `ERR_INVALID_STATE`."
    PRD 3.7: "finalization is blocked while any device under the contract is still `ACTIVE` or
    `NEEDS_TEST`, or while any alarm under any of the contract's devices is in a non-terminal
    status, with rejection code `ERR_LIVE_MONITORING_BLOCKS_CANCEL` — the system must never
    strand a live monitored device."

    Both 409 conditions hold simultaneously and the PRD does not commit to which is reported
    first, so either faithful ordering is accepted.

    Design: Difficulty/priority_pair_validation_conflict/finalize_safety_beats_temporal
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    request_cancellation_active(contract)  # STANDARD -> effective_at = paid_through (2026-07-01)
    set_clock("2026-06-10T00:00:00Z")  # before effective date; device still ACTIVE
    res = api.finalize_cancellation(contract["id"], ADMIN)
    assert res.status_code == 409, f"expected 409, got {res.status_code}: {res.text}"
    validate_error_is_one_of(res, ["ERR_LIVE_MONITORING_BLOCKS_CANCEL", "ERR_TEMPORAL_NOT_DUE"])


def test_second_cancellation_with_fresh_version_still_invalid_state(api):
    """PRD 2.9: "Only after these gates does the system evaluate state-machine legality
    (`ERR_INVALID_STATE`) and the remaining domain rules."
    PRD 3.7: "Cancellation may be requested from either `ACTIVE` or `SUSPENDED` service status;
    from any other state the request yields `ERR_INVALID_STATE`."

    Even with a CORRECT (freshly-read) expected_contract_version, a second request on a
    CANCELLATION_REQUESTED contract is rejected with ERR_INVALID_STATE because state legality
    is evaluated ahead of the OCC/domain check.

    Design: Difficulty/priority_pair_validation_conflict/request_cancellation_state_beats_fiscal
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    request_cancellation_active(contract)  # now CANCELLATION_REQUESTED
    fresh = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": fresh["version"]},
        make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_finalize_before_effective_leaves_contract_uncancelled(api):
    """PRD 3.7: "Finalizing a cancellation is a `PlatformAdmin` action permitted only when
    `service_status` is `CANCELLATION_REQUESTED` and the clock has reached or passed
    `cancellation_effective_at`; a premature attempt is rejected with `ERR_TEMPORAL_NOT_DUE`,
    and a wrong-state attempt yields `ERR_INVALID_STATE`."
    PRD 3.7: "finalization is blocked while any device under the contract is still `ACTIVE` or
    `NEEDS_TEST`, or while any alarm under any of the contract's devices is in a non-terminal
    status, with rejection code `ERR_LIVE_MONITORING_BLOCKS_CANCEL` — the system must never
    strand a live monitored device."

    A premature finalize with a still-ACTIVE device returns a 409 and must leave the contract
    un-cancelled regardless of which faithful ordering the implementer chose.

    Design: Difficulty/priority_pair_validation_conflict/finalize_safety_beats_temporal
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    request_cancellation_active(contract)
    set_clock("2026-06-10T00:00:00Z")  # before effective date; device still ACTIVE
    res = api.finalize_cancellation(contract["id"], ADMIN)
    assert res.status_code == 409, f"expected 409, got {res.status_code}: {res.text}"
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    assert contract["service_status"] == "CANCELLATION_REQUESTED", (
        "premature/blocked finalize must not cancel the contract"
    )


# ===========================================================================
# Corner — validations
# ===========================================================================
def test_enroll_without_passing_test_rejected(api):
    """PRD 3.5: "A missing passing test, or fall detection requested on a non-fall-capable
    device type, is rejected with `ERR_ENROLL_PRECONDITION`; attempting to enroll a device that
    is not in `REGISTERED` status yields `ERR_INVALID_STATE`."

    Design: Corner/validations/enroll_without_passing_test_returns_enroll_precondition
    """
    plan, sub, contract, device = setup_registered_device()
    res = api.enroll_device(device["id"], make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_ENROLL_PRECONDITION")


def test_enroll_fall_detection_on_home_base_rejected(api):
    """PRD 3.5: "if `fall_detection_enabled` is true — that the `device_type` is one of
    `PENDANT`, `WRISTBAND`, or `MOBILE_GPS`, since a `HOME_BASE` unit cannot perform fall
    detection. A missing passing test, or fall detection requested on a non-fall-capable
    device type, is rejected with `ERR_ENROLL_PRECONDITION`".

    Design: Corner/validations/enroll_fall_detection_on_home_base_returns_enroll_precondition
    """
    plan, sub, contract, device = setup_registered_device(
        device_overrides={"device_type": "HOME_BASE", "fall_detection_enabled": True})
    from test_helpers import submit_test
    submit_test(device["id"], sub["id"], reported_battery_pct=90, signal_ok=True)
    res = api.enroll_device(device["id"], make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_ENROLL_PRECONDITION")


def test_contact_tree_duplicate_rank_rejected(api):
    """PRD 3.6: "A duplicate rank, an escalation target owned by a different subscriber, or an
    escalation cycle is rejected with `ERR_CONTACT_TREE_INVALID`."

    Design: Corner/validations/contact_tree_duplicate_rank_returns_contact_tree_invalid
    """
    sub = create_subscriber()
    create_contact(sub["id"], 1, name="C1", phone="111", relationship="CAREGIVER")
    res = api.create_contact(
        {"subscriber_id": sub["id"], "name": "C1b", "phone": "222",
         "relationship": "FAMILY", "priority_rank": 1},
        make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_CONTACT_TREE_INVALID")


def test_escalation_out_of_order_rejected(api):
    """PRD 3.10: "A `CALL_CONTACT` step must target the active contact whose `priority_rank`
    equals the alarm's `current_escalation_rank`; a step that targets any other contact, or an
    inactive one, is rejected with `ERR_ESCALATION_ORDER`."

    Design: Corner/validations/escalation_out_of_order_returns_escalation_order
    """
    sub, contract, device, alarm, c1, c2 = setup_escalating_alarm_two_contacts(agent_user_id="agent-ord")
    assert alarm["current_escalation_rank"] == 1
    # Target rank-2 contact while current rank is 1 -> ERR_ESCALATION_ORDER.
    res = api.create_dispatch_action(
        alarm["id"],
        {"action_type": "CALL_CONTACT", "outcome": "NO_ANSWER", "target_contact_id": c2["id"]},
        make_agent_headers("agent-ord"))
    validate_error(res, "ERR_ESCALATION_ORDER")


def test_assign_without_shift_coverage_rejected(api):
    """PRD 3.9: "With no covering shift, assignment is rejected with `ERR_NO_SHIFT_COVERAGE`."

    Design: Corner/validations/assign_without_shift_coverage_returns_no_shift_coverage
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    alarm = raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    # agent-noshift has no SCHEDULED shift covering clock.now.
    res = api.assign_alarm(alarm["id"], make_agent_headers("agent-noshift"))
    validate_error(res, "ERR_NO_SHIFT_COVERAGE")


def test_911_not_authorized_non_critical_unauthorized_contact(api):
    """PRD 3.10: "A `DISPATCH_911` step is permitted only when the alarm's `priority` is
    `CRITICAL`, or when an answering contact authorized it — that is, a `CALL_CONTACT` dispatch
    action with `outcome` `ANSWERED` exists whose targeted contact has `can_authorize_911` set
    to true. A `DISPATCH_911` step that satisfies neither condition is rejected with
    `ERR_911_NOT_AUTHORIZED`."

    Design: Corner/validations/error_911_not_authorized_non_critical
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    # Single active contact, cannot authorize 911, no escalates_to.
    c1 = create_contact(sub["id"], 1, name="C1", phone="111", relationship="NEIGHBOR",
                        can_authorize_911=False)
    create_shift("agent-na", "2026-06-01T00:00:00Z", "2026-06-01T12:00:00Z")
    alarm = raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")  # ROUTINE (40)
    assign_alarm(alarm["id"], "agent-na")
    dispatch(alarm["id"], "agent-na", "CALL_SUBSCRIBER", "ANSWERED")
    dispatch(alarm["id"], "agent-na", "CALL_SUBSCRIBER", "NO_ANSWER")  # -> ESCALATING rank 1
    dispatch(alarm["id"], "agent-na", "CALL_CONTACT", "ANSWERED", target_contact_id=c1["id"])
    res = api.create_dispatch_action(
        alarm["id"], {"action_type": "DISPATCH_911", "outcome": "DISPATCHED"},
        make_agent_headers("agent-na"))
    validate_error(res, "ERR_911_NOT_AUTHORIZED")


def test_mark_past_due_before_paid_through_rejected(api):
    """PRD 3.3: "Marking a contract past-due is permitted only when `billing_status` is
    `CURRENT` and the clock has advanced strictly beyond `paid_through_at`; attempting it
    before that instant is rejected with `ERR_TEMPORAL_NOT_DUE`".

    Design: Corner/validations/mark_past_due_before_paid_through_returns_temporal_not_due
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    # paid_through is 2026-07-01; clock still 2026-06-10 -> not yet due.
    set_clock("2026-06-10T00:00:00Z")
    res = api.mark_past_due(contract["id"], ADMIN)
    validate_error(res, "ERR_TEMPORAL_NOT_DUE")


def test_shift_ends_before_starts_returns_invalid_request(api):
    """PRD 3.9: "A `PlatformAdmin` schedules on-call coverage by creating an agent shift with an
    `agent_user_id`, a `starts_at`, and an `ends_at`; `ends_at` must be strictly after
    `starts_at`."
    PRD 2.9: "interval ordering — is the lowest-priority family and surfaces as
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/shift_ends_before_starts_returns_invalid_request
    """
    res = api.create_shift(
        create_shift_payload("agent-bad", "2026-06-01T10:00:00Z", "2026-06-01T09:00:00Z"), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")
