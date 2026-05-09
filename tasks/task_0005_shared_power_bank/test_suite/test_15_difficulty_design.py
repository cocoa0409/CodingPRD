"""
Difficulty-design tests (priority queue from SCAFFOLD_DIFFICULTY_DESIGN.yaml).

Every instance gets at least TWO dedicated tests. Each test cites the PRD
sentence(s) for its underlying rule (PRD-First) and tags its docstring with
``# difficulty: <rule_id>/<instance.name>``.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    OPERATOR_HEADERS,
    advance_clock_to,
    api_client,
    approve_and_invoice,
    assert_money_equal,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    create_pricing_plan,
    create_settlement_for,
    deposit,
    heartbeat,
    iso_add_hours,
    make_user_headers,
    return_for,
    setup_borrow_environment,
    setup_funded_user,
    setup_pricing_plans,
    setup_settlement_universe,
    topup_wallet,
    trigger_anomaly_cascade,
    validate_error,
    validate_success,
)


# =============================================================================
# Rule 1 — Dual-variant calculations
# =============================================================================


# difficulty: dual_variant_calc/rental_billing_provisional_vs_final_with_cross_city
def test_dvc_rental_billing_provisional_no_surcharge(api):
    """PRD §3.5: "The provisional read on a non-terminal rental never adds
    the cross-city surcharge because the return cabinet is not yet known."

    # difficulty: dual_variant_calc/rental_billing_provisional_vs_final_with_cross_city
    """
    setup_pricing_plans(["BJ", "SH"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    create_device(c1["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, c1["id"])
    advance_clock_to("2026-01-01T11:30:00Z")  # 90 min
    heartbeat(c1["id"], "2026-01-01T11:30:00Z")
    heartbeat(c2["id"], "2026-01-01T11:30:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # 90 - 5 free = 85 → ceil(85/60) = 2 → 2 * 3.00 = 6.00, capped at 30 → 6.00
    assert_money_equal(fetched["charged_amount"], 6.00)
    assert fetched["rental_status"] == "ACTIVE"


# difficulty: dual_variant_calc/rental_billing_provisional_vs_final_with_cross_city
def test_dvc_rental_billing_final_with_cross_city_surcharge(api):
    """PRD §3.5: "the start cabinet's plan's cross_city_surcharge is added
    to the rental fee" on cross-city final return.

    # difficulty: dual_variant_calc/rental_billing_provisional_vs_final_with_cross_city
    """
    setup_pricing_plans(["BJ", "SH"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    create_device(c1["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, c1["id"])
    advance_clock_to("2026-01-01T12:30:00Z")  # 150 min
    heartbeat(c1["id"], "2026-01-01T12:30:00Z")
    heartbeat(c2["id"], "2026-01-01T12:30:00Z")
    final = return_for(user, rental["id"], c2["id"])
    # 150 - 5 = 145 → ceil(145/60)=3 → 3*3.00=9.00; +10 surcharge=19.00
    assert_money_equal(final["charged_amount"], 19.00)


# difficulty: dual_variant_calc/revenue_share_provisional_vs_settled_with_refund_attribution
def test_dvc_revenue_share_provisional_zero_refund_adjustment(api):
    """PRD §3.9: "The refund_adjustment on a provisional settlement is 0.00."

    # difficulty: dual_variant_calc/revenue_share_provisional_vs_settled_with_refund_attribution
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_money_equal(s["partner_amount"], 3.03)
    assert_money_equal(s["refund_adjustment"], 0.00)
    assert s["status"] == "DRAFT"


# difficulty: dual_variant_calc/revenue_share_provisional_vs_settled_with_refund_attribution
def test_dvc_revenue_share_settled_subtracts_refund(api):
    """PRD §3.9: "the partner_amount becomes the provisional-style billed sum
    ... minus this refund_adjustment."

    # difficulty: dual_variant_calc/revenue_share_provisional_vs_settled_with_refund_attribution
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    api.refund_rental(env["rentals"][0]["id"], ADMIN_HEADERS)
    invoiced = approve_and_invoice(s["id"])
    # PRD §3.9: settled partner_amount = (BILLED-share sum) − refund_adjustment.
    # After refund: 2 BILLED rentals × 1.01 = 2.02; refund_adjustment = 1.01;
    # partner_amount = 2.02 − 1.01 = 1.01.
    assert_money_equal(invoiced["partner_amount"], 1.01)
    assert_money_equal(invoiced["refund_adjustment"], 1.01)
    assert invoiced["status"] == "INVOICED"
    assert invoiced["invoice_number"] is not None


# =============================================================================
# Rule 2 — Combinatorial formulas across modes
# =============================================================================


# difficulty: combinatorial_formula/rental_billing_nested_min_ceil_with_cap_activation
def test_cf_billing_ceil_and_cap_both_fire(api):
    """PRD §3.5: "billable_hours is billable_minutes divided by 60, rounded up
    to a whole number" AND "the rental fee is the smaller of billable_hours
    multiplied by ... hourly_rate and the start cabinet's daily_cap."

    With 655 min total: 650 billable minutes → ceil(650/60) = 11 (ceil fires
    non-trivially) → min(11*3.00, 30.00) = 30.00 (cap fires non-trivially).

    # difficulty: combinatorial_formula/rental_billing_nested_min_ceil_with_cap_activation
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T20:55:00Z")  # 655 min
    heartbeat(cabinet["id"], "2026-01-01T20:55:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert_money_equal(fetched["charged_amount"], 30.00)
    assert fetched["rental_status"] == "ACTIVE"  # 655 min < 24h


# difficulty: combinatorial_formula/rental_billing_nested_min_ceil_with_cap_activation
def test_cf_billing_under_cap_uses_hourly_product(api):
    """PRD §3.5: "When billable_hours is at most 24, the rental fee is the
    smaller of billable_hours multiplied by ... hourly_rate and the
    daily_cap." When the product is below the cap, the product wins.

    # difficulty: combinatorial_formula/rental_billing_nested_min_ceil_with_cap_activation
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T11:05:00Z")  # 65 min total
    heartbeat(cabinet["id"], "2026-01-01T11:05:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # 65 - 5 = 60 → ceil(60/60)=1 → min(1*3.00, 30) = 3.00
    assert_money_equal(fetched["charged_amount"], 3.00)


# difficulty: combinatorial_formula/revenue_share_round_per_rental_then_sum_order_pin
def test_cf_revenue_share_per_rental_round_then_sum(api):
    """PRD §2.6: "For settlement aggregations, the rounding order is pinned:
    each contributing rental's partner share is rounded to two decimal
    places first and the rounded values are then summed, never the reverse."

    With 3 BILLED rentals at 3.00 each and pct=0.335:
      per-rental round: round(3.00 * 0.335, 2) = 1.01
      sum: 1.01 * 3 = 3.03  (NOT 3.02 from sum-then-round)

    # difficulty: combinatorial_formula/revenue_share_round_per_rental_then_sum_order_pin
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_money_equal(s["partner_amount"], 3.03)


# difficulty: combinatorial_formula/revenue_share_round_per_rental_then_sum_order_pin
def test_cf_revenue_share_gross_revenue_unrounded_sum(api):
    """PRD §3.9: "The gross_revenue on a provisional settlement is the sum
    of charged_amount over the same BILLED subset."

    Three rentals at 3.00 each → gross = 9.00. (No per-rental rounding step
    since charged_amount already carries 2dp precision.)

    # difficulty: combinatorial_formula/revenue_share_round_per_rental_then_sum_order_pin
    """
    env = setup_settlement_universe(
        n_users=3, revenue_share_pct=0.335, rental_hours=1.0
    )
    s = create_settlement_for(
        env["partner"]["id"],
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
    assert_money_equal(s["gross_revenue"], 9.00)


# =============================================================================
# Rule 3 — Non-linear state-machine shape
# =============================================================================


# difficulty: non_linear_state_machine/rental_parallel_status_dimensions
def test_nlsm_rental_parallel_dimensions_diverge(api):
    """PRD §3.4 / §3.5 / §3.6: rental_status and payment_status evolve on
    independent dimensions on the same Rental row.

    # difficulty: non_linear_state_machine/rental_parallel_status_dimensions
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    # ACTIVE/PENDING after borrow.
    advance_clock_to("2026-01-02T11:00:00Z")  # 25h elapsed
    heartbeat(cabinet["id"], "2026-01-02T11:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    after_overdue = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    # rental advanced; payment did not.
    assert after_overdue["rental_status"] == "OVERDUE"
    assert after_overdue["payment_status"] == "PENDING"


# difficulty: non_linear_state_machine/rental_parallel_status_dimensions
def test_nlsm_refund_advances_only_payment_dimension(api):
    """PRD §3.7: "the rental's payment_status advances from BILLED to
    REFUNDED" — rental_status (RETURNED) is unchanged.

    # difficulty: non_linear_state_machine/rental_parallel_status_dimensions
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    refunded = validate_success(api.refund_rental(final["id"], ADMIN_HEADERS), 200)
    assert refunded["rental_status"] == "RETURNED"
    assert refunded["payment_status"] == "REFUNDED"


# difficulty: non_linear_state_machine/repair_ticket_in_progress_on_hold_cycle_iterates_twice
def test_nlsm_ticket_cycle_first_iter(api):
    """PRD §3.8: "these two transitions form a cycle that may iterate any
    number of times before resolution" — first iteration.

    # difficulty: non_linear_state_machine/repair_ticket_in_progress_on_hold_cycle_iterates_twice
    """
    trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket_id = task["linked_repair_ticket_id"]
    api.assign_ticket(ticket_id, OPERATOR_HEADERS)
    api.hold_ticket(ticket_id, OPERATOR_HEADERS)
    res = api.resume_ticket(ticket_id, OPERATOR_HEADERS)
    assert validate_success(res, 200)["status"] == "IN_PROGRESS"


# difficulty: non_linear_state_machine/repair_ticket_in_progress_on_hold_cycle_iterates_twice
def test_nlsm_ticket_cycle_second_iter_then_resolve(api):
    """PRD §3.8: cycle may iterate any number of times before RESOLVED.
    Second iteration followed by resolve.

    # difficulty: non_linear_state_machine/repair_ticket_in_progress_on_hold_cycle_iterates_twice
    """
    trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket_id = task["linked_repair_ticket_id"]
    api.assign_ticket(ticket_id, OPERATOR_HEADERS)
    api.hold_ticket(ticket_id, OPERATOR_HEADERS)
    api.resume_ticket(ticket_id, OPERATOR_HEADERS)
    second_hold = validate_success(api.hold_ticket(ticket_id, OPERATOR_HEADERS), 200)
    assert second_hold["status"] == "ON_HOLD"
    api.resume_ticket(ticket_id, OPERATOR_HEADERS)
    resolved = validate_success(
        api.resolve_ticket(ticket_id, OPERATOR_HEADERS, {"cancel": False}), 200
    )
    assert resolved["status"] == "RESOLVED"


# =============================================================================
# Rule 4 — Transitive cascade chains
# =============================================================================


# difficulty: transitive_cascade/anomaly_sweep_to_operator_task_depth_4_chain
def test_tc_anomaly_chain_device_and_slot_faulty(api):
    """PRD §2.8 / §3.6: "the targeted Device transitions from AVAILABLE to
    FAULTY ... the slot housing that device transitions from OCCUPIED to
    FAULTY" caused by the previous link.

    # difficulty: transitive_cascade/anomaly_sweep_to_operator_task_depth_4_chain
    """
    env = trigger_anomaly_cascade()
    device_after = validate_success(
        api.get_device(env["device"]["id"], ADMIN_HEADERS), 200
    )
    cab_after = validate_success(
        api.get_cabinet(env["cabinet"]["id"], ADMIN_HEADERS), 200
    )
    slot0 = next(s for s in cab_after["slots"] if s["slot_index"] == 0)
    assert device_after["status"] == "FAULTY"
    assert slot0["slot_status"] == "FAULTY"


# difficulty: transitive_cascade/anomaly_sweep_to_operator_task_depth_4_chain
def test_tc_anomaly_chain_priority_score(api):
    """PRD §3.8 priority formula: low_battery_count*10 + faulty_slot_count*5
    + offline_bonus (50 when OFFLINE).

    Post-cascade: low_battery_count = 0 (device is FAULTY now, formula
    excludes non-AVAILABLE devices); faulty_slot_count = 1; offline_bonus
    = 0 (cabinet is ONLINE). Expected priority_score = 5.

    # difficulty: transitive_cascade/anomaly_sweep_to_operator_task_depth_4_chain
    """
    trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    assert task["priority_score"] == 5
    assert task["task_type"] == "REPAIR_DISPATCH"


# difficulty: transitive_cascade/ticket_resolve_repairs_slot_depth_3_chain
def test_tc_resolve_returns_device_to_available(api):
    """PRD §3.8: "On resolution, when target_type is DEVICE the device's
    status advances from FAULTY to AVAILABLE."

    # difficulty: transitive_cascade/ticket_resolve_repairs_slot_depth_3_chain
    """
    env = trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket_id = task["linked_repair_ticket_id"]
    api.assign_ticket(ticket_id, OPERATOR_HEADERS)
    api.resolve_ticket(ticket_id, OPERATOR_HEADERS, {"cancel": False})
    device_after = validate_success(
        api.get_device(env["device"]["id"], ADMIN_HEADERS), 200
    )
    assert device_after["status"] == "AVAILABLE"


# difficulty: transitive_cascade/ticket_resolve_repairs_slot_depth_3_chain
def test_tc_resolve_returns_slot_to_non_faulty(api):
    """PRD §3.8: "the slot housing the device transitions from FAULTY to
    either EMPTY or OCCUPIED depending on whether the slot's device_id is
    null."

    # difficulty: transitive_cascade/ticket_resolve_repairs_slot_depth_3_chain
    """
    env = trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket_id = task["linked_repair_ticket_id"]
    api.assign_ticket(ticket_id, OPERATOR_HEADERS)
    api.resolve_ticket(ticket_id, OPERATOR_HEADERS, {"cancel": False})
    cab = validate_success(api.get_cabinet(env["cabinet"]["id"], ADMIN_HEADERS), 200)
    slot0 = next(s for s in cab["slots"] if s["slot_index"] == 0)
    assert slot0["slot_status"] != "FAULTY"


# =============================================================================
# Rule 5 — Validation priority pair conflicts
# =============================================================================


# difficulty: priority_pair_validation_conflict/state_beats_business_referential_on_borrow
def test_pp_state_beats_business_referential(api):
    """PRD §2.7 priority order: priority 6 (state) fires before priority 13
    (business_referential).

    # difficulty: priority_pair_validation_conflict/state_beats_business_referential_on_borrow
    """
    setup_pricing_plans(["BJ"])  # SH absent
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    create_device(c1["id"], 0, battery_level=80)
    create_device(c2["id"], 0, battery_level=80)
    user = setup_funded_user()
    borrow_for(user, c1["id"])  # creates ACTIVE rental
    res = api.create_rental(
        {"cabinet_id": c2["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_DUPLICATE_RENTAL")


# difficulty: priority_pair_validation_conflict/state_beats_business_referential_on_borrow
def test_pp_state_beats_pricing_check_no_pricing_error_emitted(api):
    """Negative companion: confirm the response error_id is NOT
    ERR_PRICING_NOT_CONFIGURED.

    # difficulty: priority_pair_validation_conflict/state_beats_business_referential_on_borrow
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    create_device(c1["id"], 0, battery_level=80)
    create_device(c2["id"], 0, battery_level=80)
    user = setup_funded_user()
    borrow_for(user, c1["id"])
    res = api.create_rental(
        {"cabinet_id": c2["id"]}, make_user_headers(user["id"])
    )
    body = res.json()
    assert body["data"]["error_id"] != "ERR_PRICING_NOT_CONFIGURED"


# difficulty: priority_pair_validation_conflict/business_safety_beats_business_constraint_on_borrow
def test_pp_business_safety_beats_business_constraint(api):
    """PRD §2.7: priority 8 (business_safety) beats priority 10
    (business_constraint).

    # difficulty: priority_pair_validation_conflict/business_safety_beats_business_constraint_on_borrow
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T08:00:00Z")  # 2h stale → OFFLINE
    create_device(cabinet["id"], 0, battery_level=10)  # below MIN_BORROW_BATTERY
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_CABINET_OFFLINE")


# difficulty: priority_pair_validation_conflict/business_safety_beats_business_constraint_on_borrow
def test_pp_business_safety_no_no_available_device_emitted(api):
    """Negative companion: response must NOT carry ERR_NO_AVAILABLE_DEVICE.

    # difficulty: priority_pair_validation_conflict/business_safety_beats_business_constraint_on_borrow
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T08:00:00Z")
    create_device(cabinet["id"], 0, battery_level=10)
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    body = res.json()
    assert body["data"]["error_id"] != "ERR_NO_AVAILABLE_DEVICE"


# =============================================================================
# Rule 6 — Boundary precision
# =============================================================================


# difficulty: boundary_precision_check/free_minutes_inclusive_minute_boundary_on_get_rental
def test_bp_free_minutes_at_5_min_zero_fee(api):
    """PRD §3.5: "billable_minutes is the larger of zero and total_minutes
    minus ... free_minutes."

    # difficulty: boundary_precision_check/free_minutes_inclusive_minute_boundary_on_get_rental
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T10:05:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:05:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert_money_equal(fetched["charged_amount"], 0.00)


# difficulty: boundary_precision_check/free_minutes_inclusive_minute_boundary_on_get_rental
def test_bp_free_minutes_at_6_min_first_billable_hour(api):
    """PRD §3.5: 6 min total → 1 billable_minute → ceil(1/60)=1 → fee=3.00.

    # difficulty: boundary_precision_check/free_minutes_inclusive_minute_boundary_on_get_rental
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-01T10:06:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:06:00Z")
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert_money_equal(fetched["charged_amount"], 3.00)


# difficulty: boundary_precision_check/lost_threshold_inclusive_hour_boundary_on_sweep
def test_bp_lost_just_below_167h59_stays_overdue(api):
    """PRD §3.6: "168 is inclusive (a rental that has elapsed exactly 168
    hours becomes LOST)" — at 167h59m (= 167 floor) still OVERDUE.

    # difficulty: boundary_precision_check/lost_threshold_inclusive_hour_boundary_on_sweep
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-07T23:59:00Z")  # 167h59m elapsed
    heartbeat(cabinet["id"], "2026-01-07T23:59:00Z")
    api.run_sweep({"sweep_type": "lost"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "OVERDUE"
    assert fetched["payment_status"] == "PENDING"


# difficulty: boundary_precision_check/lost_threshold_inclusive_hour_boundary_on_sweep
def test_bp_lost_at_exactly_168h_flips_to_lost(api):
    """PRD §3.6: at 168h exactly → LOST, with charged_amount == 99.00.

    # difficulty: boundary_precision_check/lost_threshold_inclusive_hour_boundary_on_sweep
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    device = create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    advance_clock_to("2026-01-02T01:00:00Z")
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    advance_clock_to("2026-01-08T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-08T00:00:00Z")
    api.run_sweep({"sweep_type": "lost"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "LOST"
    assert fetched["payment_status"] == "DEPOSIT_DEDUCTED"
    assert_money_equal(fetched["charged_amount"], 99.00)
    user_after = validate_success(
        api.get_user(user["id"], make_user_headers(user["id"])), 200
    )
    assert_money_equal(user_after["deposit_balance"], 0.00)
    assert_money_equal(user_after["wallet_balance"], 100.00)
    device_after = validate_success(api.get_device(device["id"], ADMIN_HEADERS), 200)
    assert device_after["status"] == "LOST"


# =============================================================================
# Rule 7 — Cross-entity state dependencies
# =============================================================================


# difficulty: cross_entity_state_dependency/rental_borrow_blocked_by_cabinet_offline
def test_cesd_borrow_blocked_when_cabinet_offline(api):
    """PRD §2.5 + §2.7 priority 8: cabinet OFFLINE blocks borrow.

    # difficulty: cross_entity_state_dependency/rental_borrow_blocked_by_cabinet_offline
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T09:00:00Z")  # 1h stale > 300s → OFFLINE
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_CABINET_OFFLINE")
    cab_after = validate_success(api.get_cabinet(cabinet["id"], ADMIN_HEADERS), 200)
    assert cab_after["online_status"] == "OFFLINE"


# difficulty: cross_entity_state_dependency/rental_borrow_blocked_by_cabinet_offline
def test_cesd_fresh_heartbeat_unblocks_borrow(api):
    """PRD §3.1: "a single fresh heartbeat with a current timestamp" re-flips
    OFFLINE → ONLINE. After re-flip, borrow succeeds.

    # difficulty: cross_entity_state_dependency/rental_borrow_blocked_by_cabinet_offline
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T09:00:00Z")  # OFFLINE
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    # Refresh heartbeat → ONLINE.
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    rental = validate_success(res, 201)
    assert rental["rental_status"] == "ACTIVE"


# difficulty: cross_entity_state_dependency/operator_task_complete_blocked_by_repair_ticket_unresolved
def test_cesd_complete_repair_dispatch_blocked_by_unresolved(api):
    """PRD §2.7 priority 19: REPAIR_DISPATCH complete requires linked ticket
    in RESOLVED.

    # difficulty: cross_entity_state_dependency/operator_task_complete_blocked_by_repair_ticket_unresolved
    """
    trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    res = api.complete_task(task["id"], OPERATOR_HEADERS, {"cancel": False})
    validate_error(res, "ERR_TICKET_UNRESOLVED")


# difficulty: cross_entity_state_dependency/operator_task_complete_blocked_by_repair_ticket_unresolved
def test_cesd_complete_after_resolve_succeeds(api):
    """PRD §3.8: after the linked ticket reaches RESOLVED, complete succeeds.

    # difficulty: cross_entity_state_dependency/operator_task_complete_blocked_by_repair_ticket_unresolved
    """
    trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket_id = task["linked_repair_ticket_id"]
    api.assign_ticket(ticket_id, OPERATOR_HEADERS)
    api.resolve_ticket(ticket_id, OPERATOR_HEADERS, {"cancel": False})
    res = api.complete_task(task["id"], OPERATOR_HEADERS, {"cancel": False})
    completed = validate_success(res, 200)
    assert completed["status"] == "COMPLETED"


# =============================================================================
# Rule 8 — Resource temporal-overlap conflicts
# =============================================================================


# difficulty: resource_temporal_overlap/maintenance_window_half_open_overlap_on_cabinet
def test_rto_touching_windows_permitted(api):
    """PRD §2.5: touching windows (a.window_end == b.window_start) permitted.

    # difficulty: resource_temporal_overlap/maintenance_window_half_open_overlap_on_cabinet
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    mw1 = validate_success(
        api.create_maintenance_window(
            {
                "cabinet_id": cabinet["id"],
                "window_start": "2026-02-01T10:00:00Z",
                "window_end": "2026-02-01T12:00:00Z",
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    mw2 = validate_success(
        api.create_maintenance_window(
            {
                "cabinet_id": cabinet["id"],
                "window_start": "2026-02-01T12:00:00Z",  # touching
                "window_end": "2026-02-01T14:00:00Z",
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    assert mw1["status"] == "SCHEDULED"
    assert mw2["status"] == "SCHEDULED"


# difficulty: resource_temporal_overlap/maintenance_window_half_open_overlap_on_cabinet
def test_rto_strict_overlap_rejected(api):
    """PRD §2.5: strict overlap rejected with ERR_MAINTENANCE_WINDOW_OVERLAP.

    # difficulty: resource_temporal_overlap/maintenance_window_half_open_overlap_on_cabinet
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    api.create_maintenance_window(
        {
            "cabinet_id": cabinet["id"],
            "window_start": "2026-02-01T10:00:00Z",
            "window_end": "2026-02-01T12:00:00Z",
        },
        ADMIN_HEADERS,
    )
    res = api.create_maintenance_window(
        {
            "cabinet_id": cabinet["id"],
            "window_start": "2026-02-01T11:00:00Z",  # strict overlap
            "window_end": "2026-02-01T13:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(res, "ERR_MAINTENANCE_WINDOW_OVERLAP")


# difficulty: resource_temporal_overlap/user_active_rental_open_ended_exclusivity
def test_rto_user_open_ended_exclusivity_first_borrow(api):
    """PRD §3.4: "any second borrow attempt while the same user already has
    a rental in ACTIVE, OVERDUE, or STUCK is rejected" — first borrow
    succeeds, establishing the lock.

    # difficulty: resource_temporal_overlap/user_active_rental_open_ended_exclusivity
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    create_device(c1["id"], 0, battery_level=80)
    create_device(c2["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, c1["id"])
    assert rental["rental_status"] == "ACTIVE"


# difficulty: resource_temporal_overlap/user_active_rental_open_ended_exclusivity
def test_rto_user_second_borrow_rejected(api):
    """PRD §3.4: second borrow with ACTIVE rental → ERR_DUPLICATE_RENTAL.

    # difficulty: resource_temporal_overlap/user_active_rental_open_ended_exclusivity
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    create_device(c1["id"], 0, battery_level=80)
    create_device(c2["id"], 0, battery_level=80)
    user = setup_funded_user()
    borrow_for(user, c1["id"])
    res = api.create_rental(
        {"cabinet_id": c2["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_DUPLICATE_RENTAL")


# =============================================================================
# Rule 9 — Compensating-action invariants
# =============================================================================


# difficulty: compensating_invariant/refund_preserves_user_money_total
def test_ci_refund_invariant_post_return_wallet(api):
    """PRD §3.5 / §3.7: post-return wallet = pre-borrow wallet - charged_amount.

    # difficulty: compensating_invariant/refund_preserves_user_money_total
    """
    env = setup_borrow_environment()
    pre = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    post_return = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert_money_equal(
        post_return["wallet_balance"], pre["wallet_balance"] - final["charged_amount"]
    )


# difficulty: compensating_invariant/refund_preserves_user_money_total
def test_ci_refund_invariant_post_refund_returns_to_pre_borrow(api):
    """PRD §3.7: refund increases wallet by refund_amount; the cycle
    rent → return → refund leaves wallet at the pre-borrow value.

    # difficulty: compensating_invariant/refund_preserves_user_money_total
    """
    env = setup_borrow_environment()
    pre = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    refunded = validate_success(api.refund_rental(final["id"], ADMIN_HEADERS), 200)
    assert refunded["refund_amount"] == final["charged_amount"]
    post_refund = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert_money_equal(post_refund["wallet_balance"], pre["wallet_balance"])


# difficulty: compensating_invariant/borrow_return_preserves_global_device_count
def test_ci_device_count_preserved_through_borrow(api):
    """PRD §3.4: borrow transitions device AVAILABLE → BORROWED but creates
    no new Device records.

    # difficulty: compensating_invariant/borrow_return_preserves_global_device_count
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    d1 = create_device(c1["id"], 0, battery_level=80)
    d2 = create_device(c1["id"], 1, battery_level=70)
    d3 = create_device(c1["id"], 2, battery_level=60)
    user = setup_funded_user()
    rental = borrow_for(user, c1["id"])
    # Selector picked d1 (highest battery).
    assert rental["device_id"] == d1["id"]
    # All three devices still reachable; count preserved.
    for d in (d1, d2, d3):
        validate_success(api.get_device(d["id"], ADMIN_HEADERS), 200)
    d1_after = validate_success(api.get_device(d1["id"], ADMIN_HEADERS), 200)
    assert d1_after["status"] == "BORROWED"
    assert d1_after["current_cabinet_id"] is None


# difficulty: compensating_invariant/borrow_return_preserves_global_device_count
def test_ci_device_count_preserved_through_return(api):
    """PRD §3.5: return transitions device BORROWED → AVAILABLE. Cross-cabinet
    return moves the device but does not create or destroy any Device row.

    # difficulty: compensating_invariant/borrow_return_preserves_global_device_count
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    c1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    c2 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(c1["id"], "2026-01-01T10:00:00Z")
    heartbeat(c2["id"], "2026-01-01T10:00:00Z")
    d1 = create_device(c1["id"], 0, battery_level=80)
    d2 = create_device(c1["id"], 1, battery_level=70)
    d3 = create_device(c1["id"], 2, battery_level=60)
    user = setup_funded_user()
    rental = borrow_for(user, c1["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(c1["id"], "2026-01-01T11:00:00Z")
    heartbeat(c2["id"], "2026-01-01T11:00:00Z")
    return_for(user, rental["id"], c2["id"])
    # Devices still reachable, count preserved.
    for d in (d1, d2, d3):
        validate_success(api.get_device(d["id"], ADMIN_HEADERS), 200)
    d1_after = validate_success(api.get_device(d1["id"], ADMIN_HEADERS), 200)
    assert d1_after["status"] == "AVAILABLE"
    assert d1_after["current_cabinet_id"] == c2["id"]
    assert d1_after["current_slot_index"] == 0
