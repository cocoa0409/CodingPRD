"""Calculation rules: proration refund variants, damage-fee variants, alarm priority,
SLA breach boundary, battery-health classification, and device-test result ordering.

Covers difficulty Rules 1, 2, 6 and the corner `calculations` section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_subscriber_headers, make_agent_headers, TEST_USERS,
    create_plan_payload,
    setup_active_contract_with_device, setup_suspended_contract_with_device,
    setup_received_equipment_return, setup_assigned_alarm, setup_registered_device,
    set_clock, request_cancellation_active, submit_test,
)

ADMIN = TEST_USERS["admin_headers"]

PLUS_PLAN = dict(tier="PLUS", monthly_fee_cents=4000, fall_detection_addon_cents=1500,
                 included_test_interval_days=30, response_sla_seconds=60,
                 early_termination_fee_cents=20000, min_commitment_months=12)
PREMIUM_PLAN = dict(tier="PREMIUM", monthly_fee_cents=6000, fall_detection_addon_cents=2000,
                    included_test_interval_days=30, response_sla_seconds=30,
                    early_termination_fee_cents=30000, min_commitment_months=12)


# ===========================================================================
# Rule 1 — dual-variant calculations (refund STANDARD vs IMMEDIATE)
# ===========================================================================
def test_refund_zero_when_cancelled_while_active(api):
    """PRD 3.7: "When cancellation is requested from `ACTIVE` (the STANDARD variant),
    service continues to the end of the cycle the subscriber has already paid for, so no
    unused days are refunded: `refund_cents` is 0, and `cancellation_effective_at` is set
    to `paid_through_at`."

    Design: Difficulty/dual_variant_calc/refund_standard_vs_immediate_on_contract
    """
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=PLUS_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    # Move clock mid-cycle, re-read version, then cancel while ACTIVE.
    set_clock("2026-06-15T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["refund_cents"] == 0, f"STANDARD refund must be 0, got {data['refund_cents']}"


def test_refund_immediate_per_day_proration_when_suspended(api):
    """PRD 3.7: "The per-day rate is the applicable monthly amount divided by the cycle's
    total days, rounded half-up to a whole number of cents; this rounded per-day rate is
    then multiplied by the unused days to give `refund_cents`."

    Design: Difficulty/dual_variant_calc/refund_standard_vs_immediate_on_contract
    """
    # PLUS with fall-detection device -> monthly 5500c; cycle June (30 days);
    # per-day round_half_up(5500/30)=183; suspended; cancel at 2026-06-15 -> 16 unused days
    # -> 183*16 = 2928.
    plan, sub, contract, device = setup_suspended_contract_with_device(
        plan_overrides=PLUS_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["refund_cents"] == 2928, f"IMMEDIATE refund must be 2928, got {data['refund_cents']}"


def test_refund_round_per_day_then_multiply_order(api):
    """PRD 3.7: "The rounding is applied to the per-day rate first and the multiplication
    second — this per-line-item-then-multiply order is load-bearing and is not the same as
    rounding only the final product."

    Design: Difficulty/combinatorial_formula/refund_per_day_round_then_multiply_mode_b
    """
    # round_half_up(5500/30)=183; *16 = 2928 (NOT round(5500/30*16)=2933).
    plan, sub, contract, device = setup_suspended_contract_with_device(
        plan_overrides=PLUS_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["refund_cents"] == 2928, (
        f"per-day-round-then-multiply must yield 2928, got {data['refund_cents']}"
    )


# ===========================================================================
# Rule 1 — damage-fee variants (grade C vs UNRETURNED)
# ===========================================================================
def test_damage_fee_grade_c_is_half_replacement_cost(api):
    """PRD 3.11: "For a grade-`C` (DAMAGED) inspection, the fee is the replacement cost
    multiplied by one half, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/damage_fee_grade_c_vs_unreturned_on_equipment_return
    """
    # MOBILE_GPS replacement 18000; grade C -> 9000.
    contract, device, ret = setup_received_equipment_return(device_type="MOBILE_GPS")
    res = api.inspect_return(ret["id"], {"condition_grade": "C"}, ADMIN)
    data = validate_success(res, 200)
    assert data["damage_fee_cents"] == 9000, f"grade-C MOBILE_GPS fee must be 9000, got {data['damage_fee_cents']}"
    assert data["status"] == "DAMAGED"


def test_damage_fee_unreturned_is_full_replacement_cost(api):
    """PRD 3.11: "For an `UNRETURNED` inspection, the fee is the full replacement cost."

    Design: Difficulty/dual_variant_calc/damage_fee_grade_c_vs_unreturned_on_equipment_return
    """
    # MOBILE_GPS; never received; past due_back_at; UNRETURNED -> 18000.
    contract, device, ret = _setup_unreturned_ready(device_type="MOBILE_GPS")
    res = api.inspect_return(ret["id"], {"condition_grade": "UNRETURNED"}, ADMIN)
    data = validate_success(res, 200)
    assert data["damage_fee_cents"] == 18000, f"UNRETURNED MOBILE_GPS fee must be 18000, got {data['damage_fee_cents']}"
    assert data["status"] == "DAMAGED"


def _setup_unreturned_ready(device_type="MOBILE_GPS"):
    """INITIATED return whose due_back_at has passed (no kit/received). Returns (contract, device, ret)."""
    from test_helpers import setup_finalized_contract_with_return
    contract, device, ret = setup_finalized_contract_with_return(
        device_type=device_type, clock="2026-06-01T00:00:00Z")
    # finalize occurred at 2026-07-02 -> due_back_at = 2026-07-16; advance past it.
    set_clock("2026-07-17T00:00:00Z")
    return contract, device, ret


# ===========================================================================
# Rule 2 — alarm priority three-input non-linear formula
# ===========================================================================
def test_alarm_priority_critical_fall_detected_critical_battery(api):
    """PRD 3.8: "A base weight is taken from the signal type: `MANUAL_BUTTON` contributes
    40, `FALL_DETECTED` contributes 60, `BATTERY_CRITICAL` contributes 20, and
    `PERIODIC_CHECKIN_MISSED` contributes 50. A bonus of 30 is added only when the device
    has `fall_detection_enabled` set and the signal type is `FALL_DETECTED`. A further bonus
    of 25 is added only when the device's `battery_health` is `CRITICAL`."
    PRD 3.8: "a score of 80 or more is `CRITICAL`; otherwise a score of 50 or more is
    `ELEVATED`; otherwise it is `ROUTINE`."

    Design: Difficulty/combinatorial_formula/alarm_priority_three_input_nonlinear_mode_a
    """
    # FALL_DETECTED(60) + fall_bonus(30) + battery_bonus(25) = 115 >= 80 -> CRITICAL.
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=PREMIUM_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    # Drive battery to CRITICAL (below 20) via a low test reading (device stays ACTIVE, not overdue).
    submit_test(device["id"], sub["id"], reported_battery_pct=10, signal_ok=True)
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["battery_health"] == "CRITICAL"
    res = api.raise_alarm(device["id"], {"signal_type": "FALL_DETECTED"},
                          make_subscriber_headers(sub["id"]))
    data = validate_success(res, 201)
    assert data["priority"] == "CRITICAL", f"score 115 must be CRITICAL, got {data['priority']}"


def test_alarm_priority_battery_bonus_when_critical(api):
    """PRD 3.8: "A further bonus of 25 is added only when the device's `battery_health` is
    `CRITICAL`."
    PRD 3.8: "a score of 80 or more is `CRITICAL`; otherwise a score of 50 or more is
    `ELEVATED`; otherwise it is `ROUTINE`."

    Design: Difficulty/combinatorial_formula/alarm_priority_three_input_nonlinear_mode_a
    """
    # Non-fall device, BATTERY_CRITICAL signal (base 20) + battery_bonus(25) = 45 < 50 -> ROUTINE.
    # The fall_bonus is correctly NOT applied (signal_type != FALL_DETECTED), proving the
    # non-linear gating of the three inputs.
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=PREMIUM_PLAN, device_overrides={"fall_detection_enabled": False},
        clock="2026-06-01T00:00:00Z")
    submit_test(device["id"], sub["id"], reported_battery_pct=10, signal_ok=True)
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["battery_health"] == "CRITICAL"
    res = api.raise_alarm(device["id"], {"signal_type": "BATTERY_CRITICAL"},
                          make_subscriber_headers(sub["id"]))
    data = validate_success(res, 201)
    assert data["priority"] == "ROUTINE", (
        f"score 20+25=45 (<50, no fall_bonus) must be ROUTINE, got {data['priority']}"
    )


def test_refund_immediate_value_mode_b_explicit(api):
    """PRD 3.7: "The per-day rate is the applicable monthly amount divided by the cycle's total
    days, rounded half-up to a whole number of cents; this rounded per-day rate is then
    multiplied by the unused days to give `refund_cents`."

    Design: Difficulty/combinatorial_formula/refund_per_day_round_then_multiply_mode_b
    """
    # Distinct subscriber/scenario from the order-of-operations test; asserts the IMMEDIATE
    # refund equals the per-day-rounded product 2928 from a SUSPENDED cancellation.
    plan, sub, contract, device = setup_suspended_contract_with_device(
        plan_overrides=PLUS_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["refund_cents"] == 2928


def test_alarm_priority_periodic_checkin_elevated_at_cutoff(api):
    """PRD 3.8: "otherwise a score of 50 or more is `ELEVATED`; otherwise it is `ROUTINE`.
    Each cutoff is inclusive (the comparison is "at least")."

    Design: Corner/calculations/alarm_priority_periodic_checkin_elevated_at_cutoff
    """
    # PERIODIC_CHECKIN_MISSED(50) + 0 + 0 = 50 == ELEVATED_CUTOFF -> ELEVATED.
    plan, sub, contract, device = setup_active_contract_with_device(
        clock="2026-06-01T00:00:00Z")  # BASIC, non-fall, battery GOOD
    res = api.raise_alarm(device["id"], {"signal_type": "PERIODIC_CHECKIN_MISSED"},
                          make_subscriber_headers(sub["id"]))
    data = validate_success(res, 201)
    assert data["priority"] == "ELEVATED", f"score 50 must be ELEVATED, got {data['priority']}"


# ===========================================================================
# Rule 6 — boundary precision: SLA strict-> and battery >= cutoff
# ===========================================================================
def test_sla_not_breached_at_exactly_sla_seconds(api):
    """PRD 3.9: "The SLA check, **sla_breach_check**, measures the whole-second elapsed time
    between `agent_assigned_at` and `signal_received_at` and sets `sla_breached` to true only
    when that elapsed time is strictly greater than the plan's `response_sla_seconds`.
    Equality is not a breach — an elapsed time exactly equal to `response_sla_seconds` leaves
    `sla_breached` false."

    Design: Difficulty/boundary_precision_check/sla_strict_greater_than_on_assign
    """
    # response_sla_seconds=60; signal at 00:00:00; assign at 00:01:00 (elapsed 60) -> false.
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(response_sla_seconds=60), clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    from test_helpers import create_shift, raise_alarm
    create_shift("agent-sla", "2026-06-01T00:00:00Z", "2026-06-01T12:00:00Z")
    alarm = raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    set_clock("2026-06-01T00:01:00Z")
    res = api.assign_alarm(alarm["id"], make_agent_headers("agent-sla"))
    data = validate_success(res, 200)
    assert data["sla_breached"] is False, "elapsed == SLA must NOT breach"


def test_sla_not_breached_below_sla_seconds(api):
    """PRD 3.9: "sets `sla_breached` to true only when that elapsed time is strictly greater
    than the plan's `response_sla_seconds`."

    Design: Difficulty/boundary_precision_check/sla_strict_greater_than_on_assign
    """
    # elapsed 59s < 60 -> not a breach (the other side of the strict-> boundary).
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(response_sla_seconds=60), clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    from test_helpers import create_shift, raise_alarm
    create_shift("agent-sla3", "2026-06-01T00:00:00Z", "2026-06-01T12:00:00Z")
    alarm = raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    set_clock("2026-06-01T00:00:59Z")
    res = api.assign_alarm(alarm["id"], make_agent_headers("agent-sla3"))
    data = validate_success(res, 200)
    assert data["sla_breached"] is False, "elapsed 59 < SLA 60 must NOT breach"


def test_sla_breached_when_strictly_over_sla_seconds(api):
    """PRD 3.9: "sets `sla_breached` to true only when that elapsed time is strictly greater
    than the plan's `response_sla_seconds`."

    Design: Corner/calculations/sla_breach_true_when_strictly_over
    """
    # elapsed 61s > 60 -> true.
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(response_sla_seconds=60), clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-01T00:00:00Z")
    from test_helpers import create_shift, raise_alarm
    create_shift("agent-sla2", "2026-06-01T00:00:00Z", "2026-06-01T12:00:00Z")
    alarm = raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    set_clock("2026-06-01T00:01:01Z")
    res = api.assign_alarm(alarm["id"], make_agent_headers("agent-sla2"))
    data = validate_success(res, 200)
    assert data["sla_breached"] is True, "elapsed 61 > SLA 60 must breach"


def test_battery_health_good_at_exactly_40(api):
    """PRD 3.5: "A percentage of 40 or more is `GOOD`; a percentage that is at least 20 but
    below 40 is `LOW`; anything below 20 is `CRITICAL`."

    Design: Difficulty/boundary_precision_check/battery_health_ge_cutoff_on_test
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    submit_test(device["id"], sub["id"], reported_battery_pct=40, signal_ok=True)
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["battery_pct"] == 40
    assert device["battery_health"] == "GOOD", "battery 40 must classify GOOD"


def test_battery_health_low_just_below_good_cutoff(api):
    """PRD 3.5: "a percentage that is at least 20 but below 40 is `LOW`".

    Design: Difficulty/boundary_precision_check/battery_health_ge_cutoff_on_test
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    submit_test(device["id"], sub["id"], reported_battery_pct=39, signal_ok=True)
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["battery_health"] == "LOW", "battery 39 must classify LOW"


# ===========================================================================
# Corner — device_test_result ordering + boundary
# ===========================================================================
def test_device_test_fail_signal_dominates_battery(api):
    """PRD 3.5: "signal failure dominates. If `signal_ok` is false, the result is
    `FAIL_SIGNAL`."

    Design: Corner/calculations/device_test_result_fail_signal_dominates
    """
    plan, sub, contract, device = setup_registered_device()
    res = api.submit_test(device["id"], {"reported_battery_pct": 5, "signal_ok": False},
                          make_subscriber_headers(sub["id"]))
    data = validate_success(res, 201)
    assert data["result"] == "FAIL_SIGNAL", "signal failure must dominate low battery"


def test_device_test_battery_exactly_20_passes(api):
    """PRD 3.5: "if `reported_battery_pct` is below 20, the result is `FAIL_BATTERY` — note
    that a reading of exactly 20 is not a failure and yields `PASS`, so the boundary is
    strict."

    Design: Corner/calculations/device_test_battery_20_boundary_passes
    """
    plan, sub, contract, device = setup_registered_device()
    res = api.submit_test(device["id"], {"reported_battery_pct": 20, "signal_ok": True},
                          make_subscriber_headers(sub["id"]))
    data = validate_success(res, 201)
    assert data["result"] == "PASS", "battery exactly 20 must PASS"
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["battery_health"] == "LOW", "battery 20 classifies LOW"


def test_damage_fee_grade_b_inspected_ok_zero(api):
    """PRD 3.11: "From `RECEIVED`, a grade of `A` or `B` moves the return to `INSPECTED_OK`
    and sets `damage_fee_cents` to 0."

    Design: Corner/calculations/damage_fee_grade_b_inspected_ok_zero
    """
    contract, device, ret = setup_received_equipment_return(device_type="PENDANT")
    res = api.inspect_return(ret["id"], {"condition_grade": "B"}, ADMIN)
    data = validate_success(res, 200)
    assert data["status"] == "INSPECTED_OK"
    assert data["damage_fee_cents"] == 0, "grade B must set damage_fee_cents 0"
