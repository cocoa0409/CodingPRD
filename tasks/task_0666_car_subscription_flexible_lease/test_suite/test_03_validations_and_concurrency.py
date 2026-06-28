"""Validation precedence, cross-entity state guards, temporal-overlap geometry,
optimistic concurrency, and scheduled-clock thresholds — depth instances plus
their corner siblings.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    make_headers,
    fixtures as fx,
)


# =========================================================================== #
# priority_pair_validation_conflict                                           #
# =========================================================================== #
def test_invalid_state_precedes_eligibility_on_assign(api):
    """PRD §2.10: "Next, that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Only after those generic gates do the
    domain rules run, themselves ordered: plan-tier match on assignment
    (`ERR_PLAN_MISMATCH`), then applicant eligibility (`ERR_NOT_ELIGIBLE`)".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_not_eligible_on_assign
    """
    # A subscription already PENDING_DELIVERY (wrong state for assign); applicant is APPROVED
    # in this build but the state gate must fire regardless of any later business rule.
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)  # now PENDING_DELIVERY

    resp = api.assign_vehicle(
        sub["id"], {"vehicle_id": v2["id"], "expected_vehicle_version": v2["version"]},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_billing_past_due_precedes_min_term_on_early_cancel(api):
    """PRD §2.10: "then the past-due block on return and cancellation
    (`ERR_BILLING_PAST_DUE`), then the minimum-term check on early cancellation
    (`ERR_MIN_TERM_ELAPSED`)".

    Design: Difficulty/priority_pair_validation_conflict/billing_past_due_beats_min_term_elapsed_on_early_cancel
    """
    ctx = fx.setup_active_subscription()  # ACTIVE since 2026-04-01, min_term 6
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    get_success_data(api.mark_past_due(sub_id, TEST_USERS["billing_admin_headers"]))
    sub_v = fx.get_subscription_version(sub_id, make_member_headers(appl_id))
    fx.set_clock("2026-11-01T00:00:00Z")  # past min-term too

    resp = api.early_cancel(
        sub_id, {"expected_subscription_version": sub_v}, make_member_headers(appl_id))
    validate_error(resp, ApiErrorId.ERR_BILLING_PAST_DUE.value)


# =========================================================================== #
# cross_entity_state_dependency                                               #
# =========================================================================== #
def test_assign_blocked_when_applicant_declined(api):
    """PRD §3.4: "that the referenced applicant's `eligibility_status` is either
    `APPROVED` or `CONDITIONAL` (otherwise `ERR_NOT_ELIGIBLE`)".

    Design: Difficulty/cross_entity_state_dependency/assign_requires_applicant_eligibility_approved_or_conditional
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    veh = fx.create_vehicle(fleet["id"], plan["id"])
    # credit_score 409, income 480000, CLEAN -> score 0.5991 < 0.60 -> DECLINED
    appl = fx.create_applicant(credit_score=409, monthly_income_cents=480000, history_flag="CLEAN")
    decided = validate_success(api.decide_eligibility(
        appl["id"], {"plan_id": plan["id"]}, TEST_USERS["billing_admin_headers"]))
    assert decided["eligibility_status"] == "DECLINED", f"got {decided['eligibility_status']}"
    sub = fx.create_subscription(appl["id"], plan["id"])

    resp = api.assign_vehicle(
        sub["id"], {"vehicle_id": veh["id"], "expected_vehicle_version": veh["version"]},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE.value)

    veh_after = validate_success(api.get_vehicle(veh["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh_after["status"] == "AVAILABLE", "vehicle must stay AVAILABLE after rejection"


def test_activate_blocked_without_scheduled_delivery_slot(api):
    """PRD §3.5: "It requires that the subscription's `lifecycle_status` is
    `PENDING_DELIVERY`, that the active vehicle's `status` is `RESERVED`, and that a
    delivery slot for this subscription with `kind` of `DELIVERY` exists in the
    `SCHEDULED` state. Failing the state precondition yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_delivery_slot_scheduled
    """
    # PENDING_DELIVERY but NO delivery slot scheduled
    ctx = fx.setup_pending_delivery()
    sub_id = ctx["subscription"]["id"]
    resp = api.activate_subscription(sub_id, TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    sub_after = validate_success(api.get_subscription(
        sub_id, make_member_headers(ctx["applicant"]["id"])))
    assert sub_after["lifecycle_status"] == "PENDING_DELIVERY", "lifecycle must stay PENDING_DELIVERY"


# =========================================================================== #
# resource_temporal_overlap                                                   #
# =========================================================================== #
def test_vehicle_slot_adjacency_allowed_overlap_rejected(api):
    """PRD §3.10: "a new `DELIVERY` or `RETURN` slot must not overlap an existing
    non-cancelled slot bound to the same vehicle's active reservation window, treated as
    a half-open interval from start up to but not including end — so two slots that
    merely touch end-to-start (one ending exactly when the next begins) are allowed,
    but any true overlap is rejected with `ERR_VEHICLE_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/vehicle_reservation_halfopen_adjacency_allowed_overlap_rejected
    """
    ctx = fx.setup_pending_delivery()
    sub_id = ctx["subscription"]["id"]
    # Distinct couriers per slot so the courier closed-interval rule never fires and
    # only the same-vehicle half-open geometry is under test.
    c1 = fx.create_courier(ctx["fleet"]["id"], buffer_minutes=0)
    c2 = fx.create_courier(ctx["fleet"]["id"], buffer_minutes=0)
    c3 = fx.create_courier(ctx["fleet"]["id"], buffer_minutes=0)
    # base slot [09:00,10:00) on the subscription's vehicle
    fx.create_delivery_slot(c1["id"], sub_id,
                            window_start_iso="2026-04-01T09:00:00Z",
                            window_end_iso="2026-04-01T10:00:00Z")
    # back-to-back [10:00,11:00) accepted (adjacency end==start under half-open)
    adj = validate_success(api.create_delivery_slot(
        {"courier_id": c2["id"], "subscription_id": sub_id, "kind": "DELIVERY",
         "window_start_iso": "2026-04-01T10:00:00Z", "window_end_iso": "2026-04-01T11:00:00Z"},
        TEST_USERS["fleet_operator_headers"]), expected_status=201)
    assert adj["status"] == "SCHEDULED"
    # overlapping [10:30,11:30) rejected on the vehicle window
    resp = api.create_delivery_slot(
        {"courier_id": c3["id"], "subscription_id": sub_id, "kind": "DELIVERY",
         "window_start_iso": "2026-04-01T10:30:00Z", "window_end_iso": "2026-04-01T11:30:00Z"},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_VEHICLE_SLOT_OVERLAP.value)


def test_courier_buffer_conflict_within_padded_interval_rejected(api):
    """PRD §3.10: "a new slot must keep at least the courier's `buffer_minutes` of clear
    gap from every other non-cancelled slot of the same courier, with each slot treated
    as a closed interval padded by the buffer on both sides; if two padded closed
    intervals so much as touch, the new slot is rejected with `ERR_COURIER_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/courier_closed_interval_plus_buffer_adjacency_rejected
    """
    # Two different subscriptions' vehicles served by one courier with buffer 30
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    ap1 = fx.create_applicant_eligible(plan["id"])
    ap2 = fx.create_applicant_eligible(plan["id"])
    sub1 = fx.create_subscription(ap1["id"], plan["id"])
    fx.assign_vehicle(sub1["id"], v1)
    sub2 = fx.create_subscription(ap2["id"], plan["id"])
    fx.assign_vehicle(sub2["id"], v2)
    courier = fx.create_courier(fleet["id"], buffer_minutes=30)
    # existing slot [09:00,10:00] for sub1
    fx.create_delivery_slot(courier["id"], sub1["id"],
                            window_start_iso="2026-04-01T09:00:00Z",
                            window_end_iso="2026-04-01T10:00:00Z")
    # new slot [10:15,11:00] for sub2 within the 30-min buffer -> rejected
    resp = api.create_delivery_slot(
        {"courier_id": courier["id"], "subscription_id": sub2["id"], "kind": "DELIVERY",
         "window_start_iso": "2026-04-01T10:15:00Z", "window_end_iso": "2026-04-01T11:00:00Z"},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_COURIER_BUFFER_CONFLICT.value)


# =========================================================================== #
# Corner: validations                                                         #
# =========================================================================== #
def test_duplicate_vin_rejected(api):
    """PRD §3.2: "its `vin` (which must be unique across all vehicles — a duplicate is
    rejected with `ERR_DUPLICATE_VALUE`)".

    Design: Corner/validations/duplicate_vin_returns_duplicate_value
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    fx.create_vehicle(fleet["id"], plan["id"], vin="DUP-1")
    resp = api.create_vehicle(
        {"fleet_id": fleet["id"], "plan_id": plan["id"], "vin": "DUP-1",
         "model_label": "XC60", "odometer_miles": 0},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE.value)


def test_odometer_regression_on_close_rejected(api):
    """PRD §3.6: "The reported reading must be at least the cycle's `odometer_start_miles`;
    a regression where the end reading is below the start reading is rejected with
    `ERR_ODOMETER_REGRESSION`."

    Design: Corner/validations/odometer_regression_on_close_rejected
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    cycle_id = fx.open_billing_cycle_id(ctx["subscription"]["id"])
    resp = api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 4000}, TEST_USERS["billing_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_ODOMETER_REGRESSION.value)
    cyc = validate_success(api.get_billing_cycle(cycle_id, TEST_USERS["billing_admin_headers"]))
    assert cyc["status"] == "OPEN", "cycle must stay OPEN after regression rejection"


def test_plan_mismatch_on_assign_rejected(api):
    """PRD §3.4: "and that the target vehicle's `plan_id` equals the subscription's
    `plan_id` (otherwise `ERR_PLAN_MISMATCH`; note that this tier match is enforced only
    on initial assignment, never on a later swap)".

    Design: Corner/validations/plan_mismatch_on_assign_rejected
    """
    fx.set_clock()
    plus = fx.create_plan()
    prem = fx.create_premium_plan()
    fleet = fx.create_fleet()
    veh = fx.create_vehicle(fleet["id"], prem["id"])  # PREMIUM vehicle
    appl = fx.create_applicant_eligible(plus["id"])
    sub = fx.create_subscription(appl["id"], plus["id"])  # PLUS subscription
    resp = api.assign_vehicle(
        sub["id"], {"vehicle_id": veh["id"], "expected_vehicle_version": veh["version"]},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_MISMATCH.value)


def test_invalid_pagination_limit_rejected(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected
    with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/invalid_pagination_limit_rejected
    """
    fx.set_clock()
    resp = api.list_plans(TEST_USERS["platform_admin_headers"], params={"limit": 500, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


# =========================================================================== #
# Corner: errors                                                              #
# =========================================================================== #
# SKIPPED — Corner/errors/no_vehicle_available_when_pool_empty:
#   The instance triggers assign-vehicle with an empty body (no vehicle_id, no
#   expected_vehicle_version). PRD §2.7 declares expected_vehicle_version a
#   "non-optional field", and PRD §2.10's fixed ordering places ERR_INVALID_REQUEST
#   (missing required body field) strictly before any business check. A faithful
#   PRD-only implementer therefore returns ERR_INVALID_REQUEST for the empty body,
#   not ERR_NO_VEHICLE_AVAILABLE — the asserted outcome is not uniquely derivable
#   from the PRD, so the instance is skipped (PRD gap, not a test bug).


# =========================================================================== #
# Corner: rbac                                                                #
# =========================================================================== #
def test_member_cannot_close_billing_cycle(api):
    """PRD §2.1: "When a recognized but unauthorized role attempts an operation it is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/member_cannot_close_billing_cycle
    """
    ctx = fx.setup_active_subscription()
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    cycle_id = fx.open_billing_cycle_id(sub_id)
    resp = api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 100}, make_member_headers(appl_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_member_cannot_early_cancel_other_members_subscription(api):
    """PRD §2.1: "a `Member` acting on a `Subscription` must own it, meaning the
    supplied `X-User-ID` must equal that subscription's `applicant_id`; if it does not,
    the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/member_cannot_early_cancel_other_members_subscription
    """
    ctx = fx.setup_active_subscription()
    sub_id = ctx["subscription"]["id"]
    # A second applicant B exists but does not own the subscription
    apB = fx.create_applicant(email="other-owner@example.com")
    sub_v = fx.get_subscription_version(sub_id, TEST_USERS["billing_admin_headers"])
    resp = api.early_cancel(
        sub_id, {"expected_subscription_version": sub_v}, make_member_headers(apB["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    fx.set_clock()
    resp = api.list_plans(make_headers("ghost-id", "Ghost"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =========================================================================== #
# Corner: cross_cutting_complexity_layers                                     #
# =========================================================================== #
def test_occ_stale_vehicle_version_on_assign_rejected(api):
    """PRD §2.7: "If another operator has advanced that vehicle's `version` since the
    client last read it — for instance by reserving the same `AVAILABLE` vehicle for a
    different subscription, a legitimate supersede — the assignment is rejected with
    `ERR_STALE_VEHICLE_VERSION` (HTTP 412)".

    PRD §2.10 fixes the precedence: the generic state gate ("the target resource is in a
    state from which the requested transition is defined", `ERR_INVALID_STATE`) runs
    BEFORE the domain-level vehicle-version concurrency check (`ERR_STALE_VEHICLE_VERSION`).
    Here sub1's supersede fully completes, leaving v1 in `RESERVED`; per §3.4 the assign
    transition requires the target vehicle's status to be `AVAILABLE`, so a §2.10-faithful
    implementation surfaces `ERR_INVALID_STATE` before reaching the version check, while a
    reader of §2.7 alone would surface `ERR_STALE_VEHICLE_VERSION`. PRD admits both, so the
    assertion accepts either.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vehicle_version_on_assign_rejected_412
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])  # version 1
    stale_version = v1["version"]
    apA = fx.create_applicant_eligible(plan["id"])
    apB = fx.create_applicant_eligible(plan["id"])
    sub1 = fx.create_subscription(apA["id"], plan["id"])
    sub2 = fx.create_subscription(apB["id"], plan["id"])
    # sub1 reserves v1, bumping its version to 2
    fx.assign_vehicle(sub1["id"], v1)
    # sub2 attempts with the stale version captured before sub1's assign
    resp = api.assign_vehicle(
        sub2["id"], {"vehicle_id": v1["id"], "expected_vehicle_version": stale_version},
        TEST_USERS["fleet_operator_headers"])
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_STALE_VEHICLE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value])


def test_occ_correct_vehicle_version_increments_on_success(api):
    """PRD §2.4: "The `version` field is a system-managed integer that begins at its
    initial value and increments by one on each mutation".
    PRD §3.4: "The target vehicle moves `AVAILABLE → RESERVED`, its
    `active_subscription_id` is set to this subscription, and its `version` increments
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_vehicle_version_increments_on_success
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])  # version 1
    assert v1["version"] == 1, f"new vehicle must start at version 1, got {v1['version']}"
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)
    veh = validate_success(api.get_vehicle(v1["id"], TEST_USERS["fleet_operator_headers"]))
    assert veh["version"] == 2, f"version must increment to 2 on assign, got {veh['version']}"
    assert veh["status"] == "RESERVED"
    assert veh["active_subscription_id"] == sub["id"]


def test_clock_advance_drives_min_term_elapsed_rejection(api):
    """PRD §3.12: "that the minimum term has not yet elapsed (the logical clock's
    current instant is before the `term_start_iso` plus the plan's `min_term_months`
    whole months; reaching or passing that instant is rejected with
    `ERR_MIN_TERM_ELAPSED`)".

    Design: Corner/cross_cutting_complexity_layers/clock_set_drives_min_term_elapsed_threshold
    """
    ctx = fx.setup_active_subscription()  # ACTIVE since 2026-04-01, min_term 6, CURRENT
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    sub_v = fx.get_subscription_version(sub_id, make_member_headers(appl_id))
    fx.set_clock("2026-11-01T00:00:00Z")  # > 6 months past term_start
    resp = api.early_cancel(
        sub_id, {"expected_subscription_version": sub_v}, make_member_headers(appl_id))
    validate_error(resp, ApiErrorId.ERR_MIN_TERM_ELAPSED.value)


def test_fleet_total_vehicles_recomputed_on_add(api):
    """PRD §2.6: "A fleet's `total_vehicles` is the count of all vehicles whose
    `fleet_id` is that fleet, regardless of state".
    PRD §3.2: "Adding a vehicle recomputes the owning fleet's `total_vehicles` and
    `utilization_pct`."

    Design: Corner/cross_cutting_complexity_layers/derived_fleet_total_vehicles_recomputed_on_add
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    data = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert data["total_vehicles"] == 2, f"expected 2, got {data['total_vehicles']}"
    assert data["utilization_pct"] == 0.0, f"both AVAILABLE -> 0.0, got {data['utilization_pct']}"


# =========================================================================== #
# Corner: consistency_model                                                   #
# =========================================================================== #
def test_assign_visible_immediately_in_same_response(api):
    """PRD §3.4: "The subscription's `active_vehicle_id` is set to the reserved vehicle,
    and its `deposit_held_cents` is set to the applicant's `required_deposit_cents`
    captured at this moment."

    Design: Corner/consistency_model/immediate_assign_visible_in_same_response
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    veh = fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])  # required_deposit 80000 (APPROVED 1x)
    sub = fx.create_subscription(appl["id"], plan["id"])
    data = validate_success(api.assign_vehicle(
        sub["id"], {"vehicle_id": veh["id"], "expected_vehicle_version": veh["version"]},
        TEST_USERS["fleet_operator_headers"]))
    assert data["lifecycle_status"] == "PENDING_DELIVERY"
    assert data["active_vehicle_id"] == veh["id"]
    assert data["deposit_held_cents"] == 80000, f"expected 80000, got {data['deposit_held_cents']}"


# =========================================================================== #
# Difficulty — second assertions (each instance needs >=2 tests)              #
# =========================================================================== #
def test_assign_on_pending_delivery_leaves_subscription_state_unchanged(api):
    """PRD §3.4: "Reservation is a `FleetOperator` action that advances the subscription
    from `DRAFT` to `PENDING_DELIVERY`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_not_eligible_on_assign
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    appl = fx.create_applicant_eligible(plan["id"])
    sub = fx.create_subscription(appl["id"], plan["id"])
    fx.assign_vehicle(sub["id"], v1)  # PENDING_DELIVERY
    resp = api.assign_vehicle(
        sub["id"], {"vehicle_id": v2["id"], "expected_vehicle_version": v2["version"]},
        TEST_USERS["fleet_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    # the second vehicle must remain untouched (still AVAILABLE)
    v2_after = validate_success(api.get_vehicle(v2["id"], TEST_USERS["fleet_operator_headers"]))
    assert v2_after["status"] == "AVAILABLE", f"v2 must stay AVAILABLE, got {v2_after['status']}"


def test_early_cancel_blocked_while_past_due_regardless_of_term(api):
    """PRD §3.13: "it is precisely the `PAST_DUE` standing that blocks both initiating a
    return and early cancellation with `ERR_BILLING_PAST_DUE`."

    Design: Difficulty/priority_pair_validation_conflict/billing_past_due_beats_min_term_elapsed_on_early_cancel
    """
    ctx = fx.setup_active_subscription()
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]
    get_success_data(api.mark_past_due(sub_id, TEST_USERS["billing_admin_headers"]))
    sub_v = fx.get_subscription_version(sub_id, make_member_headers(appl_id))
    fx.set_clock("2026-11-01T00:00:00Z")
    resp = api.early_cancel(
        sub_id, {"expected_subscription_version": sub_v}, make_member_headers(appl_id))
    validate_error(resp, ApiErrorId.ERR_BILLING_PAST_DUE.value)
    # subscription remains ACTIVE (early-cancel never ran)
    sub = validate_success(api.get_subscription(sub_id, make_member_headers(appl_id)))
    assert sub["lifecycle_status"] == "ACTIVE", f"expected ACTIVE, got {sub['lifecycle_status']}"


def test_conditional_applicant_may_be_assigned_a_vehicle(api):
    """PRD §3.4: "that the referenced applicant's `eligibility_status` is either
    `APPROVED` or `CONDITIONAL` (otherwise `ERR_NOT_ELIGIBLE`)".

    Design: Difficulty/cross_entity_state_dependency/assign_requires_applicant_eligibility_approved_or_conditional
    """
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    veh = fx.create_vehicle(fleet["id"], plan["id"])
    # credit_score 410, income 480000, CLEAN -> score 0.60 -> CONDITIONAL
    appl = fx.create_applicant(credit_score=410, monthly_income_cents=480000, history_flag="CLEAN")
    decided = validate_success(api.decide_eligibility(
        appl["id"], {"plan_id": plan["id"]}, TEST_USERS["billing_admin_headers"]))
    assert decided["eligibility_status"] == "CONDITIONAL", f"got {decided['eligibility_status']}"
    sub = fx.create_subscription(appl["id"], plan["id"])
    data = validate_success(api.assign_vehicle(
        sub["id"], {"vehicle_id": veh["id"], "expected_vehicle_version": veh["version"]},
        TEST_USERS["fleet_operator_headers"]))
    assert data["lifecycle_status"] == "PENDING_DELIVERY", (
        f"CONDITIONAL applicant must be assignable, got {data['lifecycle_status']}"
    )


def test_activate_succeeds_with_scheduled_delivery_slot(api):
    """PRD §3.5: "It requires that the subscription's `lifecycle_status` is
    `PENDING_DELIVERY`, that the active vehicle's `status` is `RESERVED`, and that a
    delivery slot for this subscription with `kind` of `DELIVERY` exists in the
    `SCHEDULED` state."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_delivery_slot_scheduled
    """
    ctx = fx.setup_pending_delivery()
    sub_id = ctx["subscription"]["id"]
    # Now schedule a DELIVERY slot, then activation should succeed.
    fx.create_delivery_slot(ctx["courier"]["id"], sub_id)
    data = validate_success(api.activate_subscription(sub_id, TEST_USERS["fleet_operator_headers"]))
    assert data["lifecycle_status"] == "ACTIVE", (
        f"activation with a SCHEDULED DELIVERY slot must reach ACTIVE, got {data['lifecycle_status']}"
    )


def test_vehicle_slot_back_to_back_adjacency_accepted(api):
    """PRD §3.10: "so two slots that merely touch end-to-start (one ending exactly when
    the next begins) are allowed, but any true overlap is rejected with
    `ERR_VEHICLE_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/vehicle_reservation_halfopen_adjacency_allowed_overlap_rejected
    """
    ctx = fx.setup_pending_delivery()
    sub_id = ctx["subscription"]["id"]
    # Distinct couriers so only the vehicle half-open adjacency rule is under test.
    c1 = fx.create_courier(ctx["fleet"]["id"], buffer_minutes=0)
    c2 = fx.create_courier(ctx["fleet"]["id"], buffer_minutes=0)
    fx.create_delivery_slot(c1["id"], sub_id,
                            window_start_iso="2026-04-01T09:00:00Z",
                            window_end_iso="2026-04-01T10:00:00Z")
    # back-to-back [10:00,11:00) must be accepted (adjacency end==start)
    adj = validate_success(api.create_delivery_slot(
        {"courier_id": c2["id"], "subscription_id": sub_id, "kind": "DELIVERY",
         "window_start_iso": "2026-04-01T10:00:00Z", "window_end_iso": "2026-04-01T11:00:00Z"},
        TEST_USERS["fleet_operator_headers"]), expected_status=201)
    assert adj["status"] == "SCHEDULED", f"adjacency slot must be SCHEDULED, got {adj['status']}"


def test_courier_far_separated_slot_accepted(api):
    """PRD §3.10: "a new slot must keep at least the courier's `buffer_minutes` of clear
    gap from every other non-cancelled slot of the same courier, with each slot treated
    as a closed interval padded by the buffer on both sides".

    Design: Difficulty/resource_temporal_overlap/courier_closed_interval_plus_buffer_adjacency_rejected
    """
    # A second slot a full day later is comfortably outside the buffer under any
    # faithful reading of the padded-interval rule, so it must be accepted.
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    ap1 = fx.create_applicant_eligible(plan["id"])
    ap2 = fx.create_applicant_eligible(plan["id"])
    sub1 = fx.create_subscription(ap1["id"], plan["id"])
    fx.assign_vehicle(sub1["id"], v1)
    sub2 = fx.create_subscription(ap2["id"], plan["id"])
    fx.assign_vehicle(sub2["id"], v2)
    courier = fx.create_courier(fleet["id"], buffer_minutes=30)
    fx.create_delivery_slot(courier["id"], sub1["id"],
                            window_start_iso="2026-04-01T09:00:00Z",
                            window_end_iso="2026-04-01T10:00:00Z")
    # new slot a full day later -> far beyond the 30-min buffer -> accepted
    ok = validate_success(api.create_delivery_slot(
        {"courier_id": courier["id"], "subscription_id": sub2["id"], "kind": "DELIVERY",
         "window_start_iso": "2026-04-02T09:00:00Z", "window_end_iso": "2026-04-02T10:00:00Z"},
        TEST_USERS["fleet_operator_headers"]), expected_status=201)
    assert ok["status"] == "SCHEDULED", f"far-separated slot must be accepted, got {ok['status']}"
