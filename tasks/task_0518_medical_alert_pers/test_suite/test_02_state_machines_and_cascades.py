"""State-machine transitions and cascading side effects: the suspend/reinstate cycle,
the alarm ESCALATING self-loop, the finalize-cancellation depth-3 cascade, the damaged-
inspect cross-aggregate fee, and assorted invalid-transition / initial-state corners.

Covers difficulty Rules 3, 4 and corner state_machines + cascading_side_effects.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_subscriber_headers, make_agent_headers, TEST_USERS,
    create_plan_payload,
    setup_active_contract_with_device, setup_active_contract_with_two_devices,
    setup_received_equipment_return, setup_finalized_contract_with_return,
    setup_escalating_alarm_two_contacts, setup_contacting_subscriber_alarm,
    setup_registered_device, setup_assigned_alarm,
    set_clock, request_cancellation_active, finalize_after_effective,
    cancel_via_suspended_and_finalize,
    get_first_equipment_return, dispatch, drive_contract_to_suspended,
    create_shift, raise_alarm, assign_alarm,
)

ADMIN = TEST_USERS["admin_headers"]
PREMIUM_PLAN = dict(tier="PREMIUM", monthly_fee_cents=6000, fall_detection_addon_cents=2000,
                    included_test_interval_days=30, response_sla_seconds=30,
                    early_termination_fee_cents=30000, min_commitment_months=12)


# ===========================================================================
# Rule 3 — non-linear state machines
# ===========================================================================
def test_escalating_self_loop_advances_rank(api):
    """PRD 3.10: "When that contact does not answer (`outcome` `NO_ANSWER`) and they have a
    non-null `escalates_to_contact_id` pointing to an active contact, the alarm remains
    `ESCALATING` and `current_escalation_rank` advances to the `priority_rank` of the contact
    referenced by that fallback pointer — a self-loop that walks the tree one contact per
    unanswered call."

    Design: Difficulty/non_linear_state_machine/alarm_escalating_self_loop_walks_contact_tree
    """
    sub, contract, device, alarm, c1, c2 = setup_escalating_alarm_two_contacts(agent_user_id="agent-esc")
    assert alarm["status"] == "ESCALATING"
    assert alarm["current_escalation_rank"] == 1
    # rank-1 contact NO_ANSWER -> self-loop ESCALATING at rank 2.
    res = api.create_dispatch_action(
        alarm["id"],
        {"action_type": "CALL_CONTACT", "outcome": "NO_ANSWER", "target_contact_id": c1["id"]},
        make_agent_headers("agent-esc"))
    validate_success(res, 201)
    updated = get_success_data(api.get_alarm(alarm["id"], ADMIN))
    assert updated["status"] == "ESCALATING"
    assert updated["current_escalation_rank"] == 2, (
        f"rank must advance to 2 along escalates_to, got {updated['current_escalation_rank']}"
    )


def test_escalating_enters_at_lowest_rank(api):
    """PRD 3.10: "Entering escalation sets `current_escalation_rank` to the `priority_rank` of
    the lowest-ranked active contact for the subscriber."

    Design: Difficulty/non_linear_state_machine/alarm_escalating_self_loop_walks_contact_tree
    """
    sub, contract, device, alarm, c1, c2 = setup_escalating_alarm_two_contacts(agent_user_id="agent-esc2")
    assert alarm["status"] == "ESCALATING"
    assert alarm["current_escalation_rank"] == 1, (
        f"escalation must enter at lowest rank 1, got {alarm['current_escalation_rank']}"
    )


def test_contract_active_suspended_reinstate_cycle(api):
    """PRD 3.4: "Reinstating sets `service_status` back to `ACTIVE`, cascades every
    `SUSPENDED` device under the contract back to `ACTIVE`, and increments `version`."

    Design: Difficulty/non_linear_state_machine/contract_active_suspended_reinstate_cycle
    """
    plan, sub, contract, device = setup_active_contract_with_device(
        device_overrides={"device_type": "HOME_BASE"}, clock="2026-06-01T00:00:00Z")
    contract = drive_contract_to_suspended(contract["id"])
    assert contract["service_status"] == "SUSPENDED"
    # record-payment clears billing to CURRENT, then reinstate.
    get_success_data(api.record_payment(contract["id"], ADMIN))
    res = api.reinstate_contract(contract["id"], ADMIN)
    data = validate_success(res, 200)
    assert data["service_status"] == "ACTIVE"
    assert data["billing_status"] == "CURRENT"
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["status"] == "ACTIVE", "device must cascade back to ACTIVE on reinstate"


def test_reinstate_billing_dimension_independent(api):
    """PRD 3.3: "Note that recording payment does not by itself restore monitoring — restoring
    a suspended contract to service is the separate reinstatement action in Section 3.4."

    Design: Difficulty/non_linear_state_machine/contract_active_suspended_reinstate_cycle
    """
    plan, sub, contract, device = setup_active_contract_with_device(
        device_overrides={"device_type": "HOME_BASE"}, clock="2026-06-01T00:00:00Z")
    contract = drive_contract_to_suspended(contract["id"])
    paid = get_success_data(api.record_payment(contract["id"], ADMIN))
    # Billing cleared but service still SUSPENDED until reinstate.
    assert paid["billing_status"] == "CURRENT"
    assert paid["service_status"] == "SUSPENDED", "record-payment must NOT restore service"


# ===========================================================================
# Rule 4 — transitive cascade chains
# ===========================================================================
def test_finalize_cancellation_depth3_cascade(api):
    """PRD 3.7: "finalization sets `service_status` to `CANCELLED`, cascades every
    not-yet-`DEACTIVATED` device under the contract to `DEACTIVATED`, opens one
    **EquipmentReturn** per deactivated device (each starting `INITIATED` with a `due_back_at`
    set to 14 days after the current instant), and increments the contract `version`."

    Design: Difficulty/transitive_cascade/finalize_cancellation_depth3_contract_device_return
    """
    plan, sub, contract, device = setup_active_contract_with_device(
        device_overrides={"device_type": "WRISTBAND"}, clock="2026-06-01T00:00:00Z")
    # PRD 3.7 blocks finalization while a device is ACTIVE/NEEDS_TEST; reach a finalizable
    # cancellation through SUSPENDED (the only PRD path that vacates ACTIVE without finalizing).
    contract = cancel_via_suspended_and_finalize(contract["id"])
    assert contract["service_status"] == "CANCELLED"
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["status"] == "DEACTIVATED", "device must cascade to DEACTIVATED"
    ret = get_first_equipment_return(contract["id"])
    assert ret["status"] == "INITIATED", "an EquipmentReturn must be opened INITIATED"


def test_finalize_cancellation_sets_due_back_14_days(api):
    """PRD 3.7: "opens one **EquipmentReturn** per deactivated device (each starting
    `INITIATED` with a `due_back_at` set to 14 days after the current instant)".

    Design: Difficulty/transitive_cascade/finalize_cancellation_depth3_contract_device_return
    """
    # finalize at 2026-07-02 -> due_back_at must be 2026-07-16 (14 days later).
    plan, sub, contract, device = setup_active_contract_with_device(
        device_overrides={"device_type": "WRISTBAND"}, clock="2026-06-01T00:00:00Z")
    # PRD 3.7 blocks finalization while a device is ACTIVE/NEEDS_TEST; reach a finalizable
    # cancellation through SUSPENDED. Suspend/finalize both happen at 2026-07-02, so
    # due_back_at = 2026-07-16 (finalize instant + 14 days).
    contract = cancel_via_suspended_and_finalize(contract["id"], suspend_clock="2026-07-02T00:00:00Z")
    ret = get_first_equipment_return(contract["id"])
    assert ret["due_back_at"].startswith("2026-07-16"), (
        f"due_back_at must be 14 days after finalize (2026-07-16), got {ret['due_back_at']}"
    )


def test_damaged_inspect_adds_fee_to_contract_balance(api):
    """PRD 3.11: "In either damaged outcome the computed `damage_fee_cents` is added to the
    owning contract's `outstanding_balance_cents` — a cross-aggregate effect that reaches
    across from the return back to its contract."

    Design: Difficulty/transitive_cascade/damaged_inspect_depth2_return_fee_to_contract_balance
    """
    # BASIC PENDANT (ETF 0 -> balance starts 0); grade C fee 4000.
    contract, device, ret = setup_received_equipment_return(device_type="PENDANT")
    res = api.inspect_return(ret["id"], {"condition_grade": "C"}, ADMIN)
    data = validate_success(res, 200)
    assert data["damage_fee_cents"] == 4000, f"PENDANT grade-C fee must be 4000, got {data['damage_fee_cents']}"
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    assert contract["outstanding_balance_cents"] == 4000, (
        f"fee must add to outstanding_balance_cents, got {contract['outstanding_balance_cents']}"
    )


def test_damaged_inspect_transitions_return_to_damaged(api):
    """PRD 3.11: "A grade of `C` moves the return to `DAMAGED` and computes a damage fee."

    Design: Difficulty/transitive_cascade/damaged_inspect_depth2_return_fee_to_contract_balance
    """
    # First hop of the depth-2 cascade: RECEIVED -> DAMAGED on grade C.
    contract, device, ret = setup_received_equipment_return(device_type="PENDANT")
    res = api.inspect_return(ret["id"], {"condition_grade": "C"}, ADMIN)
    data = validate_success(res, 200)
    assert data["status"] == "DAMAGED", f"grade-C inspect must move return to DAMAGED, got {data['status']}"


# ===========================================================================
# Corner — cascading_side_effects
# ===========================================================================
def test_suspend_cascades_two_devices(api):
    """PRD 3.4: "Suspending sets `service_status` to `SUSPENDED`, cascades every `ACTIVE`
    device under the contract to `SUSPENDED`, and increments the contract `version`."

    Design: Corner/cross_cutting_complexity_layers/suspend_cascades_devices_to_suspended
    """
    plan, sub, contract, dev_a, dev_b = setup_active_contract_with_two_devices(clock="2026-06-01T00:00:00Z")
    contract = drive_contract_to_suspended(contract["id"])
    dev_a = get_success_data(api.get_device(dev_a["id"], ADMIN))
    dev_b = get_success_data(api.get_device(dev_b["id"], ADMIN))
    assert dev_a["status"] == "SUSPENDED"
    assert dev_b["status"] == "SUSPENDED"


# ===========================================================================
# Corner — state_machines
# ===========================================================================
def test_activate_already_active_returns_invalid_state(api):
    """PRD 3.2: "A `PlatformAdmin` activates a contract, which is permitted only when the
    contract's `service_status` is `PENDING_ACTIVATION`, the plan referenced by `plan_id` is
    not archived, at least one device under the contract is in `ENROLLED` status, and the
    owning subscriber's `status` is `ACTIVE`; failing the state precondition yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_contract_returns_invalid_state
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    res = api.activate_contract(contract["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_suspend_active_current_billing_returns_invalid_state(api):
    """PRD 3.4: "Suspension is permitted only when `service_status` is `ACTIVE` and
    `billing_status` is `PAST_DUE`; from any other combination the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/suspend_active_but_current_billing_returns_invalid_state
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    # billing is still CURRENT; suspend must be rejected.
    res = api.suspend_contract(contract["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_already_cancelled_shift_returns_invalid_state(api):
    """PRD 3.9: "A `PlatformAdmin` may cancel a `SCHEDULED` shift, which moves it to
    `CANCELLED`, frees its interval for new shifts, and increments its `version`; a cancelled
    shift no longer provides assignment coverage."
    PRD 2.9: "Only after these gates does the system evaluate state-machine legality
    (`ERR_INVALID_STATE`) and the remaining domain rules."

    Design: Corner/state_machines/cancel_shift_already_cancelled_returns_invalid_state
    """
    shift = create_shift("agent-z", "2026-06-01T00:00:00Z", "2026-06-01T08:00:00Z")
    get_success_data(api.cancel_shift(shift["id"], ADMIN))
    res = api.cancel_shift(shift["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_enroll_moves_registered_device_to_enrolled(api):
    """PRD 3.5: "A successful enroll moves the device to `ENROLLED` and increments its
    `version`."

    Design: Corner/state_machines/enroll_device_initial_state_registered
    """
    plan, sub, contract, device = setup_registered_device(set_clock_to="2026-06-01T00:00:00Z")
    assert device["status"] == "REGISTERED", "newly created device starts REGISTERED"
    from test_helpers import submit_test
    submit_test(device["id"], sub["id"], reported_battery_pct=90, signal_ok=True)
    res = api.enroll_device(device["id"], make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["status"] == "ENROLLED"


def test_device_needs_test_auto_transition_then_back_to_active(api):
    """PRD 3.5: "whenever the clock reaches or passes `next_test_due_at`, the next alarm-create
    or test-submit against that device first auto-transitions it from `ACTIVE` to `NEEDS_TEST`
    and increments its `version`."
    PRD 3.5: "A `NEEDS_TEST` device is returned to `ACTIVE` by submitting a test whose `result`
    is `PASS`; that transition sets `last_test_at` to the current instant, recomputes
    `next_test_due_at` as `last_test_at` plus the plan's `included_test_interval_days`, and
    increments `version`."

    Design: Corner/state_machines/device_needs_test_auto_transition_on_overdue_test
    """
    # interval 30d -> next_test_due 2026-07-01; advance to 2026-07-05; PASS test returns ACTIVE.
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z")
    from test_helpers import submit_test
    submit_test(device["id"], sub["id"], reported_battery_pct=88, signal_ok=True)
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["status"] == "ACTIVE", "PASS test on overdue device returns it to ACTIVE"


def test_false_alarm_branch_distinct_side_effects(api):
    """PRD 3.10: "A `MARK_FALSE_ALARM` step with `outcome` `CONFIRMED_FALSE` records an
    accidental press and moves the alarm to terminal `FALSE_ALARM`. The false-alarm branch
    fires no 911 dispatch and no contact escalation — it is a distinct outcome from
    `RESOLVED_OK` and shares only the terminal bookkeeping (set `resolved_at`, decrement
    `open_alarm_count`)."

    Design: Corner/state_machines/false_alarm_branch_distinct_side_effects
    """
    sub, contract, device, alarm = setup_contacting_subscriber_alarm(agent_user_id="agent-fa")
    res = api.create_dispatch_action(
        alarm["id"], {"action_type": "MARK_FALSE_ALARM", "outcome": "CONFIRMED_FALSE"},
        make_agent_headers("agent-fa"))
    validate_success(res, 201)
    updated = get_success_data(api.get_alarm(alarm["id"], ADMIN))
    assert updated["status"] == "FALSE_ALARM"
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["open_alarm_count"] == 0, "false-alarm terminal must decrement open_alarm_count"


def test_dispatch_911_critical_direct_from_contacting(api):
    """PRD 3.10: "When the alarm's `priority` is `CRITICAL`, the agent may bypass the contact
    tree entirely and record a `DISPATCH_911` step with `outcome` `DISPATCHED` directly from
    `CONTACTING_SUBSCRIBER`, moving the alarm to terminal `DISPATCHED_911`."

    Design: Corner/state_machines/dispatch_911_critical_direct_from_contacting
    """
    # FALL_DETECTED on fall-enabled device -> 60+30 = 90 >= 80 -> CRITICAL.
    sub, contract, device, alarm = setup_contacting_subscriber_alarm(
        agent_user_id="agent-911", signal_type="FALL_DETECTED",
        device_overrides={"fall_detection_enabled": True}, plan_overrides=PREMIUM_PLAN)
    assert alarm["priority"] == "CRITICAL"
    res = api.create_dispatch_action(
        alarm["id"], {"action_type": "DISPATCH_911", "outcome": "DISPATCHED"},
        make_agent_headers("agent-911"))
    validate_success(res, 201)
    updated = get_success_data(api.get_alarm(alarm["id"], ADMIN))
    assert updated["status"] == "DISPATCHED_911"
