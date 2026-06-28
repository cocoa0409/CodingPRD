"""Vehicle/Subscription/Swap/Inspection lifecycles, cross-entity cascades, and
conserved-quantity invariants — depth instances plus their corner siblings.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    assert_deposit_conserved,
    fixtures as fx,
)


# =========================================================================== #
# non_linear_state_machine                                                    #
# =========================================================================== #
def test_vehicle_cyclic_returns_to_available_then_reassignable(api):
    """PRD §3.2: "A vehicle moves through a cyclic allocation lifecycle: `AVAILABLE`,
    `RESERVED`, `ASSIGNED`, `IN_INSPECTION`, and a side branch of `MAINTENANCE`."
    PRD §3.4: "The target vehicle moves `AVAILABLE → RESERVED`, its
    `active_subscription_id` is set to this subscription, and its `version`
    increments by one."

    Design: Difficulty/non_linear_state_machine/vehicle_cyclic_available_reserved_assigned_inspection_available
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 100})
    veh = ctx["vehicle"]
    sub1_id = ctx["subscription"]["id"]
    appl1_id = ctx["applicant"]["id"]
    plan = ctx["plan"]

    # Full loop back to AVAILABLE: return -> inspect -> assess -> settle
    fx.initiate_return(sub1_id, appl1_id)
    insp = fx.open_inspection(sub1_id, veh["id"], reported_odometer_miles=200)
    fx.assess_inspection(insp["id"])
    fx.settle_inspection(insp["id"])

    # Re-assign the same vehicle to a second subscription
    ap2 = fx.create_applicant_eligible(plan["id"])
    sub2 = fx.create_subscription(ap2["id"], plan["id"])
    veh_after = get_success_data(api.get_vehicle(veh["id"], TEST_USERS["fleet_operator_headers"]))
    data = fx.assign_vehicle(sub2["id"], veh_after)

    veh_final = validate_success(api.get_vehicle(veh["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh_final["status"] == "RESERVED", f"expected RESERVED after loop, got {veh_final['status']}"
    assert veh_final["active_subscription_id"] == sub2["id"]
    assert data["active_vehicle_id"] == veh["id"]


def test_subscription_billing_axis_independent_of_lifecycle_mark_past_due(api):
    """PRD §2.6: "These are orthogonal: a subscription can be `ACTIVE` and `PAST_DUE`
    at the same time. Operations that read or guard on one axis must not silently
    mutate the other."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_axes
    """
    ctx = fx.setup_active_subscription()
    sub_id = ctx["subscription"]["id"]
    data = validate_success(api.mark_past_due(sub_id, TEST_USERS["billing_admin_headers"]))
    assert data["lifecycle_status"] == "ACTIVE", "lifecycle must stay ACTIVE after mark-past-due"
    assert data["billing_status"] == "PAST_DUE", "billing must flip to PAST_DUE"


def test_subscription_record_payment_restores_current_without_touching_lifecycle(api):
    """PRD §3.13: "The administrator records recovery by moving `billing_status` from
    `PAST_DUE` to `CURRENT`, which requires that the subscription is currently `PAST_DUE`."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_axes
    """
    ctx = fx.setup_active_subscription()
    sub_id = ctx["subscription"]["id"]
    get_success_data(api.mark_past_due(sub_id, TEST_USERS["billing_admin_headers"]))
    data = validate_success(api.record_payment(sub_id, TEST_USERS["billing_admin_headers"]))
    assert data["billing_status"] == "CURRENT", "billing must return to CURRENT"
    assert data["lifecycle_status"] == "ACTIVE", "lifecycle must remain ACTIVE"


# =========================================================================== #
# transitive_cascade                                                          #
# =========================================================================== #
def test_settle_cascade_releases_vehicle_and_recomputes_fleet(api):
    """PRD §3.11: "the inspected vehicle moves `IN_INSPECTION → AVAILABLE` with its
    `active_subscription_id` cleared to null and its `version` incremented; the owning
    fleet's `in_use_count` is decremented and `utilization_pct` recomputed; the
    subscription's `active_vehicle_id` is cleared to null and, when it was
    `RETURN_PENDING`, its `lifecycle_status` advances `RETURN_PENDING → CLOSED`."

    Design: Difficulty/transitive_cascade/settle_cascade_depth3_inspection_vehicle_fleet
    """
    # Fleet of 2: v1 assigned to the returning sub, v2 AVAILABLE -> utilization 0.5 before settle
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"], odometer_miles=100)
    fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)
    courier = fx.create_courier(fleet["id"])
    fx.create_delivery_slot(courier["id"], sub["id"])
    get_success_data(api.activate_subscription(sub["id"], TEST_USERS["fleet_operator_headers"]))
    fx.initiate_return(sub["id"], appl["id"])
    insp = fx.open_inspection(sub["id"], v1["id"], reported_odometer_miles=300)
    fx.assess_inspection(insp["id"])

    settled = validate_success(api.settle_inspection(insp["id"], TEST_USERS["billing_admin_headers"]))
    assert settled["status"] == "SETTLED"

    veh = validate_success(api.get_vehicle(v1["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh["status"] == "AVAILABLE", f"vehicle must release to AVAILABLE, got {veh['status']}"
    assert veh["active_subscription_id"] is None

    flt = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert flt["in_use_count"] == 0, f"fleet in_use_count must drop to 0, got {flt['in_use_count']}"
    assert flt["utilization_pct"] == 0.0, f"utilization must recompute to 0.0, got {flt['utilization_pct']}"

    sub_final = validate_success(api.get_subscription(sub["id"], make_member_headers(appl["id"])))
    assert sub_final["lifecycle_status"] == "CLOSED"


def test_assign_cascade_reserves_vehicle_and_bumps_fleet(api):
    """PRD §3.4: "The owning fleet's `in_use_count` increases by one and its
    `utilization_pct` is recomputed."

    Design: Difficulty/transitive_cascade/assign_cascade_depth2_vehicle_fleet
    """
    # 4 AVAILABLE vehicles, util 0; assign one -> in_use 1, util 0.25 (1 of 4)
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])

    fx.assign_vehicle(sub["id"], v1)

    veh = validate_success(api.get_vehicle(v1["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh["status"] == "RESERVED", f"expected RESERVED, got {veh['status']}"
    flt = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert flt["in_use_count"] == 1, f"expected in_use_count 1, got {flt['in_use_count']}"
    assert flt["utilization_pct"] == 0.25, f"expected 0.25 (1 of 4), got {flt['utilization_pct']}"


# =========================================================================== #
# compensating_invariant                                                      #
# =========================================================================== #
def test_deposit_conservation_held_equals_applied_plus_refunded(api):
    """PRD §3.11: "The `deposit_applied_cents` is the lesser of the subscription's
    `deposit_held_cents` and that outstanding amount. The `deposit_refunded_cents` is
    the held deposit minus the applied portion."

    Design: Difficulty/compensating_invariant/deposit_conservation_held_equals_applied_plus_refunded
    """
    ctx = fx.setup_assessed_inspection(
        damage_items=[("MODERATE", 12000), ("MINOR", 4500)], reported_odometer_miles=50)
    insp_before = ctx["inspection"]
    assert insp_before["total_damage_cents"] == 16500, (
        f"expected total damage 16500, got {insp_before['total_damage_cents']}"
    )
    insp = validate_success(api.settle_inspection(
        insp_before["id"], TEST_USERS["billing_admin_headers"]))
    # deposit 80000, outstanding 16500 -> applied 16500, refunded 63500, balance 0
    assert insp["deposit_applied_cents"] == 16500, f"got {insp['deposit_applied_cents']}"
    assert insp["deposit_refunded_cents"] == 63500, f"got {insp['deposit_refunded_cents']}"
    assert insp["balance_due_cents"] == 0, f"got {insp['balance_due_cents']}"
    assert_deposit_conserved(insp, 80000)


def test_swap_approve_then_reject_conserves_fleet_in_use_count(api):
    """PRD §3.8: "rejection is a compensating action: the target vehicle moves
    `RESERVED → AVAILABLE`, its `active_subscription_id` is cleared to null, its
    `version` increments, and the target's fleet has its `in_use_count` decreased by
    one and `utilization_pct` recomputed — leaving that fleet's `in_use_count` exactly
    as it stood before the approval."

    Design: Difficulty/compensating_invariant/fleet_in_use_count_conservation_swap_approve_then_reject
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)
    courier = fx.create_courier(fleet["id"])
    fx.create_delivery_slot(courier["id"], sub["id"])
    get_success_data(api.activate_subscription(sub["id"], TEST_USERS["fleet_operator_headers"]))

    before = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert before["in_use_count"] == 1, f"expected 1 before approve, got {before['in_use_count']}"

    sw = fx.request_swap(sub["id"], appl["id"], v2["id"])
    fx.approve_swap(sw["id"], v2["id"])
    after_approve = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert after_approve["in_use_count"] == 2, f"expected 2 after approve, got {after_approve['in_use_count']}"

    rej = validate_success(api.reject_swap(sw["id"], TEST_USERS["fleet_operator_headers"]))
    assert rej["status"] == "REJECTED"
    after_reject = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert after_reject["in_use_count"] == 1, (
        f"compensation must restore in_use_count to 1, got {after_reject['in_use_count']}"
    )
    v2_final = validate_success(api.get_vehicle(v2["id"], TEST_USERS["fleet_operator_headers"]))
    assert v2_final["status"] == "AVAILABLE", f"target must revert to AVAILABLE, got {v2_final['status']}"
    assert v2_final["active_subscription_id"] is None


# =========================================================================== #
# Corner: state_machines                                                      #
# =========================================================================== #
def test_reject_completed_swap_returns_invalid_state(api):
    """PRD §3.8: "Rejecting from any state other than `REQUESTED` or `APPROVED` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_swap_from_completed_returns_invalid_state
    """
    fx.set_clock()
    plus = fx.create_plan()
    prem = fx.create_premium_plan()
    fleet = fx.create_fleet()
    vA = fx.create_vehicle(fleet["id"], plus["id"])
    vB = fx.create_vehicle(fleet["id"], prem["id"])
    appl = fx.create_applicant_eligible(plus["id"])
    sub = fx.create_subscription(appl["id"], plus["id"])
    fx.assign_vehicle(sub["id"], vA)
    courier = fx.create_courier(fleet["id"])
    fx.create_delivery_slot(courier["id"], sub["id"])
    get_success_data(api.activate_subscription(sub["id"], TEST_USERS["fleet_operator_headers"]))
    sw = fx.perform_full_swap(sub["id"], appl["id"], vB["id"])  # COMPLETED

    resp = api.reject_swap(sw["id"], TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_initiate_return_from_draft_returns_invalid_state(api):
    """PRD §3.11: "A `Member` initiates a return on their own subscription, advancing
    it `ACTIVE → RETURN_PENDING`. This requires that the subscription's
    `lifecycle_status` is `ACTIVE`."

    Design: Corner/state_machines/initiate_return_from_draft_returns_invalid_state
    """
    fx.set_clock()
    plan = fx.create_plan()
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])  # DRAFT
    resp = api.initiate_return(sub["id"], make_member_headers(appl["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_subscription_starts_draft_current(api):
    """PRD §3.4: "The new subscription starts with `lifecycle_status` of `DRAFT`,
    `billing_status` of `CURRENT`, `deposit_held_cents` of 0, and `swaps_used` of 0".

    Design: Corner/state_machines/subscription_initial_state_draft_current
    """
    fx.set_clock()
    plan = fx.create_plan()
    appl = fx.create_applicant_eligible(plan["id"])
    data = validate_success(api.create_subscription(
        {"applicant_id": appl["id"], "plan_id": plan["id"]},
        make_member_headers(appl["id"])), expected_status=201)
    assert data["lifecycle_status"] == "DRAFT"
    assert data["billing_status"] == "CURRENT"
    assert data["deposit_held_cents"] == 0
    assert data["swaps_used"] == 0


def test_maintenance_complete_returns_vehicle_to_available(api):
    """PRD §3.2: "When servicing finishes, the operator returns the vehicle from
    `MAINTENANCE` to `AVAILABLE`, which increments the vehicle's `version`."

    Design: Corner/state_machines/maintenance_complete_returns_vehicle_to_available
    """
    ctx = fx.setup_active_subscription()
    veh_id = ctx["vehicle"]["id"]
    get_success_data(api.vehicle_maintenance(veh_id, TEST_USERS["fleet_operator_headers"]))
    data = validate_success(api.vehicle_maintenance_complete(
        veh_id, TEST_USERS["fleet_operator_headers"]))
    assert data["status"] == "AVAILABLE", f"expected AVAILABLE, got {data['status']}"


# =========================================================================== #
# Difficulty — second assertions (each instance needs >=2 tests)              #
# =========================================================================== #
def test_vehicle_cyclic_loop_releases_to_available_before_reassign(api):
    """PRD §3.11: "the inspected vehicle moves `IN_INSPECTION → AVAILABLE` with its
    `active_subscription_id` cleared to null and its `version` incremented".

    Design: Difficulty/non_linear_state_machine/vehicle_cyclic_available_reserved_assigned_inspection_available
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 100})
    veh = ctx["vehicle"]
    sub1_id = ctx["subscription"]["id"]
    appl1_id = ctx["applicant"]["id"]
    fx.initiate_return(sub1_id, appl1_id)
    insp = fx.open_inspection(sub1_id, veh["id"], reported_odometer_miles=200)
    fx.assess_inspection(insp["id"])
    fx.settle_inspection(insp["id"])
    # After the full loop the vehicle is AVAILABLE again with no holding subscription.
    veh_after = validate_success(api.get_vehicle(veh["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh_after["status"] == "AVAILABLE", f"expected AVAILABLE mid-loop, got {veh_after['status']}"
    assert veh_after["active_subscription_id"] is None


def test_subscription_active_and_past_due_coexist(api):
    """PRD §3.13: "Because this axis is independent of `lifecycle_status`, a subscription
    can be `ACTIVE` and `PAST_DUE` simultaneously".

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_axes
    """
    ctx = fx.setup_active_subscription()
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    get_success_data(api.mark_past_due(sub_id, TEST_USERS["billing_admin_headers"]))
    sub = validate_success(api.get_subscription(sub_id, make_member_headers(appl_id)))
    assert sub["lifecycle_status"] == "ACTIVE" and sub["billing_status"] == "PAST_DUE", (
        f"expected ACTIVE+PAST_DUE coexistence, got "
        f"{sub['lifecycle_status']}+{sub['billing_status']}"
    )


def test_settle_closes_subscription_and_posts_settlement_invoice(api):
    """PRD §3.11: "the subscription's `active_vehicle_id` is cleared to null and, when
    it was `RETURN_PENDING`, its `lifecycle_status` advances `RETURN_PENDING → CLOSED`."

    Design: Difficulty/transitive_cascade/settle_cascade_depth3_inspection_vehicle_fleet
    """
    ctx = fx.setup_assessed_inspection(reported_odometer_miles=300)
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    fx.settle_inspection(ctx["inspection"]["id"])
    sub = validate_success(api.get_subscription(sub_id, make_member_headers(appl_id)))
    assert sub["lifecycle_status"] == "CLOSED", f"expected CLOSED, got {sub['lifecycle_status']}"
    assert sub["active_vehicle_id"] is None


def test_assign_sets_vehicle_active_subscription_and_reserves(api):
    """PRD §3.4: "The target vehicle moves `AVAILABLE → RESERVED`, its
    `active_subscription_id` is set to this subscription, and its `version` increments
    by one."

    Design: Difficulty/transitive_cascade/assign_cascade_depth2_vehicle_fleet
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)
    veh = validate_success(api.get_vehicle(v1["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh["status"] == "RESERVED"
    assert veh["active_subscription_id"] == sub["id"], (
        f"vehicle must reference the reserving subscription, got {veh['active_subscription_id']}"
    )


def test_deposit_waterfall_full_refund_when_nothing_outstanding(api):
    """PRD §3.11: "When nothing is outstanding, the applied portion is 0, the entire
    deposit is refunded, and the balance due is 0."

    Design: Difficulty/compensating_invariant/deposit_conservation_held_equals_applied_plus_refunded
    """
    # No damage items, no unpaid invoices -> outstanding 0
    ctx = fx.setup_assessed_inspection(damage_items=[], reported_odometer_miles=50)
    insp = validate_success(api.settle_inspection(
        ctx["inspection"]["id"], TEST_USERS["billing_admin_headers"]))
    assert insp["deposit_applied_cents"] == 0, f"got {insp['deposit_applied_cents']}"
    assert insp["deposit_refunded_cents"] == 80000, f"got {insp['deposit_refunded_cents']}"
    assert insp["balance_due_cents"] == 0, f"got {insp['balance_due_cents']}"
    assert_deposit_conserved(insp, 80000)


def test_swap_reject_after_approve_reverts_target_to_available(api):
    """PRD §3.8: "If the swap had already been `APPROVED`, rejection is a compensating
    action: the target vehicle moves `RESERVED → AVAILABLE`, its `active_subscription_id`
    is cleared to null, its `version` increments, and the target's fleet has its
    `in_use_count` decreased by one and `utilization_pct` recomputed".

    Design: Difficulty/compensating_invariant/fleet_in_use_count_conservation_swap_approve_then_reject
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)
    courier = fx.create_courier(fleet["id"])
    fx.create_delivery_slot(courier["id"], sub["id"])
    get_success_data(api.activate_subscription(sub["id"], TEST_USERS["fleet_operator_headers"]))
    sw = fx.request_swap(sub["id"], appl["id"], v2["id"])
    fx.approve_swap(sw["id"], v2["id"])
    rej = validate_success(api.reject_swap(sw["id"], TEST_USERS["fleet_operator_headers"]))
    assert rej["status"] == "REJECTED"
    v2_after = validate_success(api.get_vehicle(v2["id"], TEST_USERS["fleet_operator_headers"]))
    assert v2_after["status"] == "AVAILABLE", f"target must revert to AVAILABLE, got {v2_after['status']}"
    assert v2_after["active_subscription_id"] is None
