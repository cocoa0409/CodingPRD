"""Weekly box lifecycle: lock/charge parallel dimensions, lock preconditions, charge/ship
state guards, the lifetime-box-count side effect, and immediate provisional-charge visibility.

Translates queue A (Difficulty) non_linear_state_machine(parallel), boundary_precision_check
(empty box), cross_entity_state_dependency(lock requires active), and queue B (Corner) box
state-machine + derived_field + consistency instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_plan, create_zone, register_member, create_subscription,
    create_box, add_recipes_to_box, lock_box, charge_box, create_recipes,
    setup_lockable_box, setup_locked_box, setup_charged_box,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ─── Difficulty: non_linear_state_machine / weekly_box_parallel... ──────────

def test_box_parallel_dimensions_locked_and_charged(api):
    """PRD §2.11: "A weekly box carries two state dimensions that evolve independently: a selection dimension (`selection_status`, one of `OPEN`, `LOCKED`, `SKIPPED`) and a fulfillment dimension (`fulfillment_status`, one of `PENDING`, `CHARGED`, `SHIPPED`, `REFUNDED`)."
    PRD §3.5: "On a successful charge, the box's `final_charge_cents` is computed under the final variant of the weekly-box charge (see §3.6) from the live selection and the live `credit_balance_cents` at the charge instant, the `fulfillment_status` becomes `CHARGED"

    Design: Difficulty/non_linear_state_machine/weekly_box_parallel_selection_x_fulfillment
    """
    ctx = setup_charged_box(servings_per_meal=2, meals_per_week=2, zone_code="ZONE_A",
                            cold_pack_surcharge_cents=0,
                            delivery_date="2026-07-15T00:00:00.000Z",
                            advance_clock="2026-07-11T00:00:00.000Z")
    box = ctx["box"]
    assert box["selection_status"] == "LOCKED"
    assert box["fulfillment_status"] == "CHARGED"


def test_box_lock_advances_only_selection_dimension(api):
    """PRD §3.5: "A member locks an `OPEN` box, advancing its `selection_status` from `OPEN` to `LOCKED`."
    PRD §3.5: "Charging advances the fulfillment dimension from `PENDING` to `CHARGED`."

    Design: Difficulty/non_linear_state_machine/weekly_box_parallel_selection_x_fulfillment
    """
    ctx = setup_locked_box(servings_per_meal=2, meals_per_week=2,
                           delivery_date="2026-07-15T00:00:00.000Z")
    box = ctx["box"]
    assert box["selection_status"] == "LOCKED"
    assert box["fulfillment_status"] == "PENDING"


# ─── Difficulty: cross_entity_state_dependency / box_lock_requires_subscription_active ──

def test_lock_blocked_when_owning_subscription_paused(api):
    """PRD §3.5: "Locking requires four conditions: the box's `selection_status` is `OPEN` (else `ERR_SELECTION_NOT_OPEN`); the owning subscription's `status` is `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`); the number of recipe slots on the box is exactly the plan's `meals_per_week` (else `ERR_SELECTION_INCOMPLETE`); and the current clock is strictly before `cutoff_at` (else `ERR_CUTOFF_PASSED`)."

    Design: Difficulty/cross_entity_state_dependency/box_lock_requires_subscription_active
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    recipes = create_recipes(2, prefix="LK")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    # delivery far in the future so the in-window pause cascade does not skip the box
    box = create_box(member, sub, "2026-07-29T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    # pause to a date before the box's delivery so the box stays OPEN (not skipped)
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-07-20T00:00:00.000Z"}, hdr), 200)
    res = api.lock_selection(box["id"], hdr)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, expected_status=409)


def test_lock_succeeds_when_subscription_active(api):
    """PRD §3.5: "the owning subscription's `status` is `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`)"
    PRD §3.5: "On a successful lock, the box's `provisional_charge_cents` is computed under the provisional variant of the weekly-box charge described in §3.6"

    Design: Difficulty/cross_entity_state_dependency/box_lock_requires_subscription_active
    """
    ctx = setup_locked_box(servings_per_meal=2, meals_per_week=2)
    assert ctx["box"]["selection_status"] == "LOCKED"


# ─── Difficulty: boundary_precision_check / empty_box_lock_rejected_zero_recipes ──

def test_lock_empty_box_rejected_incomplete_selection(api):
    """PRD §3.5: "the number of recipe slots on the box is exactly the plan's `meals_per_week` (else `ERR_SELECTION_INCOMPLETE`)"

    Design: Difficulty/boundary_precision_check/empty_box_lock_rejected_zero_recipes
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")  # zero recipes
    res = api.lock_selection(box["id"], make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_SELECTION_INCOMPLETE.value, expected_status=409)


def test_lock_with_too_few_recipes_rejected_incomplete(api):
    """PRD §3.5: "the number of recipe slots on the box is exactly the plan's `meals_per_week` (else `ERR_SELECTION_INCOMPLETE`)"

    Design: Difficulty/boundary_precision_check/empty_box_lock_rejected_zero_recipes
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=3)
    zone = create_zone()
    recipes = create_recipes(1, prefix="FEW")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)  # only 1 of 3 required
    res = api.lock_selection(box["id"], make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_SELECTION_INCOMPLETE.value, expected_status=409)


# ─── Corner: state_machines (box transitions) ───────────────────────────────

def test_ship_uncharged_box_rejected(api):
    """PRD §3.5: "Shipping requires the `fulfillment_status` to be `CHARGED` (else `ERR_BOX_NOT_CHARGED`) and the owning member's shipping zone to be serviceable"

    Design: Corner/state_machines/ship_uncharged_box_rejected
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")  # PENDING, never charged
    res = api.ship_box(box["id"], OPS)
    validate_error(res, ApiErrorId.ERR_BOX_NOT_CHARGED.value, expected_status=409)


def test_charge_before_cutoff_rejected(api):
    """PRD §2.7: "charging a box is only permitted once the current clock is at or after `cutoff_at`; charging before the cutoff is rejected with `ERR_CUTOFF_NOT_REACHED`."

    Design: Corner/state_machines/charge_before_cutoff_rejected
    """
    ctx = setup_locked_box(servings_per_meal=2, meals_per_week=2, zone_code="ZONE_B",
                           cold_pack_surcharge_cents=499,
                           delivery_date="2026-07-15T00:00:00.000Z",
                           clock="2026-07-01T00:00:00.000Z")
    # clock still 2026-07-01, well before cutoff 2026-07-10T23:59:59Z
    res = api.charge_box(ctx["box"]["id"], OPS)
    validate_error(res, ApiErrorId.ERR_CUTOFF_NOT_REACHED.value, expected_status=409)


def test_skip_locked_box_after_charge_rejected_cross_dimension(api):
    """PRD §3.5: "Skipping from `LOCKED` requires `selection_status` to be `LOCKED` (else `ERR_SELECTION_NOT_LOCKED`), additionally requires that the fulfillment dimension is still `PENDING` — a box already charged cannot be skipped, and an attempt is rejected with `ERR_BOX_ALREADY_CHARGED"

    Design: Corner/state_machines/skip_locked_box_after_charge_rejected_cross_dimension
    """
    ctx = setup_charged_box(servings_per_meal=2, meals_per_week=2,
                            delivery_date="2026-07-15T00:00:00.000Z",
                            advance_clock="2026-07-11T00:00:00.000Z")
    member, box = ctx["member"], ctx["box"]
    res = api.skip_box(box["id"], make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_BOX_ALREADY_CHARGED.value, expected_status=409)


# ─── Corner: derived_field_reconciliation / lifetime_box_count_derived_after_ship ──

def test_lifetime_box_count_increments_on_ship(api):
    """PRD §2.6: "A second derived field, `lifetime_box_count`, is a read-only count of the member's weekly boxes that have reached `SHIPPED`. It too is system-maintained, increments by one each time one of the member's boxes ships, and drives the member's loyalty tier."

    Design: Corner/cross_cutting_complexity_layers/lifetime_box_count_derived_after_ship
    """
    ctx = setup_charged_box(servings_per_meal=2, meals_per_week=2,
                            delivery_date="2026-07-15T00:00:00.000Z",
                            advance_clock="2026-07-11T00:00:00.000Z")
    member, box = ctx["member"], ctx["box"]
    before = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert before["lifetime_box_count"] == 0
    validate_success(api.ship_box(box["id"], OPS), 200)
    after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert after["lifetime_box_count"] == 1


# ─── Corner: consistency_model / immediate_visibility_of_provisional_charge ──

def test_provisional_charge_present_in_lock_response(api):
    """PRD §3.5: "On a successful lock, the box's `provisional_charge_cents` is computed under the provisional variant of the weekly-box charge described in §3.6, taking a snapshot of the member's credit and loyalty standing as they stand at the lock instant"

    Design: Corner/consistency_model/immediate_visibility_of_provisional_charge
    """
    # Plan 4x2 = 8 servings -> 999 tier; STANDARD; ZONE_A; loyalty 0; credit 0 -> 999*8 = 7992
    ctx = setup_lockable_box(servings_per_meal=4, meals_per_week=2, zone_code="ZONE_A",
                             cold_pack_surcharge_cents=0,
                             delivery_date="2026-07-15T00:00:00.000Z")
    locked = validate_success(api.lock_selection(
        ctx["box"]["id"], make_member_headers(ctx["member"]["id"])), 200)
    assert locked["provisional_charge_cents"] == 7992
