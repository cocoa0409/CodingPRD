"""Lease / brand / order / stall / equipment lifecycles, cascades, and invalid transitions.

Difficulty (A): non_linear_state_machine (lease suspend/reinstate revert cycle; order
fork route vs reject), cross_entity_state_dependency (lease activate cascades brand ACTIVE),
transitive_cascade (deactivate brand terminates ACTIVE leases depth 2).
Corner (B): invalid/idempotent transitions, terminal lockdown, parallel availability axis,
guarded deactivation, equipment retire (blocked + count decrement), order initial fork.
"""
from test_helpers import validate_success, validate_error, get_success_data
from test_helpers import fixtures as fx
from test_helpers import (
    create_order_payload,
    make_stall_operator_headers,
    make_brand_owner_headers,
)

OPS = fx.OPS
GATEWAY = fx.GATEWAY


# ── Non-linear lease machine: suspend -> reinstate revert cycle ───────────────

def test_lease_suspend_then_reinstate_returns_to_active(api):
    """PRD §3.3: "`PlatformOps` may reinstate a `SUSPENDED` lease back to `ACTIVE`, but
    reinstatement re-checks priority uniqueness: it is allowed only when the lease is
    `SUSPENDED` and no other `ACTIVE` lease at the same stall holds this lease's
    `priority_rank`"

    create(v1) -> activate(v2) -> suspend(v3) -> reinstate(v4); ends ACTIVE at version 4.

    Design: Difficulty/non_linear_state_machine/lease_suspend_reinstate_revert_cycle
    """
    stall = fx.create_stall(name="S5")
    brand = fx.create_brand(name="B5", commission_rate_bps=1000)
    lease = fx.create_lease(stall["id"], brand["id"], priority_rank=1)
    fx.activate_lease(stall["id"], lease["id"])
    get_success_data(api.suspend_lease(lease["id"], OPS))
    reinstated = validate_success(api.reinstate_lease(lease["id"], OPS), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == 4


def test_suspended_lease_excluded_then_reinstated_for_routing(api):
    """PRD §3.3: "`PlatformOps` may suspend an `ACTIVE` lease, moving it to `SUSPENDED`
    (which excludes it from routing candidate sets) and bumping its `version`"
    PRD §3.3: "Because a suspended lease can return to active, the lease lifecycle is
    non-linear."

    A SUSPENDED lease leaves no eligible stall (ERR_NO_ELIGIBLE_STALL); reinstating it
    makes the stall routable again.

    Design: Difficulty/non_linear_state_machine/lease_suspend_reinstate_revert_cycle
    """
    s = fx.setup_routable_scenario(
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "grams_received": 1000},
    )
    get_success_data(api.suspend_lease(s["lease"]["id"], OPS))
    blocked = api.route_order(s["order"]["id"], OPS)
    validate_error(blocked, "ERR_NO_ELIGIBLE_STALL", expected_status=409)
    get_success_data(api.reinstate_lease(s["lease"]["id"], OPS))
    routed = validate_success(api.route_order(s["order"]["id"], OPS), 200)
    assert routed["status"] == "ROUTED"


# ── Order fork: route vs reject divergent side effects ────────────────────────

def test_reject_order_reserves_nothing(api):
    """PRD §3.5: "A `PlatformOps` operator may reject it outright, moving
    `INGESTED → REJECTED`; rejection reserves no equipment and consumes no inventory, so
    there is nothing to compensate later, and it simply bumps the order's `version`."

    Reject leaves booking_id null and the chicken lot untouched at 1000g.

    Design: Difficulty/non_linear_state_machine/order_branch_fork_route_vs_reject_divergent_effects
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=1000)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-6"), GATEWAY))
    rejected = validate_success(api.reject_order(order["id"], OPS), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["booking_id"] is None
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 1000, "reject consumes no inventory"


def test_route_branch_reserves_booking_and_consumes(api):
    """PRD §3.5: "the platform reserves a single contiguous half-open window on one
    `AVAILABLE` unit of that type at the chosen stall" ... "Second, the platform deducts
    ingredient inventory FIFO (see §3.6)"

    Contrast branch to reject: routing creates a booking_id and draws down the lot.

    Design: Difficulty/non_linear_state_machine/order_branch_fork_route_vs_reject_divergent_effects
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=1000)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-6B"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["status"] == "ROUTED"
    assert routed["booking_id"] is not None
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 900


# ── Cross-entity: lease activation cascades brand ONBOARDING -> ACTIVE ─────────

def test_lease_activation_cascades_brand_active(api):
    """PRD §3.3: "if the brand referenced by the lease's `brand_id` is still `ONBOARDING`
    — that brand cascades from `ONBOARDING` to `ACTIVE` as the second hop of the activation
    cascade, with the brand's own `version` bumped."
    PRD §3.2: "A brand becomes `ACTIVE` only as a side effect of its first lease activating
    (see §3.3), never by direct request."

    Activating the brand's first lease flips the brand ONBOARDING->ACTIVE; availability
    stays PAUSED.

    Design: Difficulty/cross_entity_state_dependency/lease_activate_cascades_brand_active
    """
    stall = fx.create_stall(name="S14")
    brand = fx.create_brand(name="B14", commission_rate_bps=1000)
    assert brand["status"] == "ONBOARDING"
    lease = fx.create_lease(stall["id"], brand["id"], priority_rank=1)
    activated = validate_success(
        api.activate_lease(lease["id"], make_stall_operator_headers(stall["id"])), 200)
    assert activated["status"] == "ACTIVE"
    brand_after = validate_success(api.get_brand(brand["id"], OPS), 200)
    assert brand_after["status"] == "ACTIVE"
    assert brand_after["availability"] == "PAUSED"


def test_brand_must_be_active_to_list(api):
    """PRD §3.2: "moving from `PAUSED` to `LISTED` requires both that availability currently
    be `PAUSED` and that the brand's `status` be `ACTIVE`"

    After the activation cascade flips the brand ACTIVE, its owner can list it (PAUSED ->
    LISTED), confirming the cascade really set status ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/lease_activate_cascades_brand_active
    """
    stall = fx.create_stall(name="S14b")
    brand = fx.create_brand(name="B14b", commission_rate_bps=1000)
    lease = fx.create_lease(stall["id"], brand["id"], priority_rank=1)
    fx.activate_lease(stall["id"], lease["id"])
    listed = validate_success(
        api.list_brand_availability(brand["id"], make_brand_owner_headers(brand["id"])), 200)
    assert listed["availability"] == "LISTED"
    assert listed["status"] == "ACTIVE"


# ── Transitive cascade: deactivate brand terminates ACTIVE leases (depth 2) ───

def test_deactivate_brand_terminates_active_leases(api):
    """PRD §3.2: "When deactivation does proceed, the brand's `status` becomes
    `DEACTIVATED`, its `availability` is forced to `PAUSED`, every `KitchenLease` for that
    brand that is currently `ACTIVE` cascades to `TERMINATED`, and the brand's `version` is
    bumped."

    Design: Difficulty/transitive_cascade/deactivate_brand_terminate_lease_depth2
    """
    stall = fx.create_stall(name="S8")
    brand = fx.create_brand(name="B8", commission_rate_bps=1000)
    lease = fx.create_lease(stall["id"], brand["id"], priority_rank=1)
    fx.activate_lease(stall["id"], lease["id"])
    deactivated = validate_success(
        api.deactivate_brand(brand["id"], make_brand_owner_headers(brand["id"])), 200)
    assert deactivated["status"] == "DEACTIVATED"
    assert deactivated["availability"] == "PAUSED"
    lease_after = validate_success(api.get_lease(lease["id"], OPS), 200)
    assert lease_after["status"] == "TERMINATED"


def test_deactivate_brand_forces_availability_paused(api):
    """PRD §3.2: "its `availability` is forced to `PAUSED`" ... "every `KitchenLease` for
    that brand that is currently `ACTIVE` cascades to `TERMINATED`"

    A LISTED brand, on deactivation, is forced PAUSED and its ACTIVE lease is TERMINATED.

    Design: Difficulty/transitive_cascade/deactivate_brand_terminate_lease_depth2
    """
    stall, brand, lease = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    assert brand["availability"] == "LISTED"
    deactivated = validate_success(
        api.deactivate_brand(brand["id"], make_brand_owner_headers(brand["id"])), 200)
    assert deactivated["status"] == "DEACTIVATED"
    assert deactivated["availability"] == "PAUSED"
    lease_after = validate_success(api.get_lease(lease["id"], OPS), 200)
    assert lease_after["status"] == "TERMINATED"


# ── Corner: invalid / idempotent transitions and terminal lockdown ────────────

def test_close_already_closed_stall_invalid_state(api):
    """PRD §3.1: "attempting this while the stall is already `CLOSED` is an invalid
    transition rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_already_closed_stall_invalid_state
    """
    stall = fx.create_stall(name="SC")
    headers = make_stall_operator_headers(stall["id"])
    get_success_data(api.close_stall(stall["id"], headers))
    res = api.close_stall(stall["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activate_already_active_lease_invalid_state(api):
    """PRD §3.3: "a lease not in `PENDING` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_lease_invalid_state
    """
    stall = fx.create_stall(name="SLI")
    brand = fx.create_brand(name="BLI", commission_rate_bps=1000)
    lease = fx.create_lease(stall["id"], brand["id"], priority_rank=1)
    headers = make_stall_operator_headers(stall["id"])
    get_success_data(api.activate_lease(lease["id"], headers))
    res = api.activate_lease(lease["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_terminated_lease_rejects_further_transition(api):
    """PRD §3.3: "the owning `StallOperator` may terminate a lease from either `ACTIVE` or
    `SUSPENDED`, moving it to the terminal `TERMINATED` state" ... "suspending a lease that
    is not `ACTIVE` is rejected with `ERR_INVALID_STATE`."

    A TERMINATED lease has no outgoing transitions: suspend is ERR_INVALID_STATE.

    Design: Corner/state_machines/terminated_lease_terminal_lockdown
    """
    stall = fx.create_stall(name="SLT")
    brand = fx.create_brand(name="BLT", commission_rate_bps=1000)
    lease = fx.create_lease(stall["id"], brand["id"], priority_rank=1)
    op_headers = make_stall_operator_headers(stall["id"])
    get_success_data(api.activate_lease(lease["id"], op_headers))
    get_success_data(api.terminate_lease(lease["id"], op_headers))
    res = api.suspend_lease(lease["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ── Corner: brand availability parallel to status ─────────────────────────────

def test_brand_availability_toggle_leaves_status_active(api):
    """PRD §3.2: "these two axes evolve independently of one another." ... "moving from
    `LISTED` to `PAUSED` requires only that availability currently be `LISTED`."

    Listing then pausing leaves status ACTIVE unchanged.

    Design: Corner/state_machines/brand_availability_parallel_to_status
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    paused = validate_success(
        api.pause_brand(brand["id"], make_brand_owner_headers(brand["id"])), 200)
    assert paused["availability"] == "PAUSED"
    assert paused["status"] == "ACTIVE"


# ── Corner: list while onboarding is invalid ──────────────────────────────────

def test_list_brand_while_onboarding_invalid_state(api):
    """PRD §3.2: "moving from `PAUSED` to `LISTED` requires both that availability currently
    be `PAUSED` and that the brand's `status` be `ACTIVE`" ... "an attempt from the wrong
    starting availability is rejected with `ERR_INVALID_STATE`."

    An ONBOARDING brand (status != ACTIVE) cannot be listed.

    Design: Corner/state_machines/list_brand_while_onboarding_invalid_state
    """
    brand = fx.create_brand(name="BO", commission_rate_bps=1000)
    res = api.list_brand_availability(brand["id"], make_brand_owner_headers(brand["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ── Corner: deactivation guarded by in-flight order ───────────────────────────

def test_deactivate_blocked_by_routed_order(api):
    """PRD §3.2: "Deactivation is permitted only when the brand is `ACTIVE` and no
    `AggregatorOrder` for that brand is currently in either `ROUTED` or `PREPARING` status;
    an in-flight order blocks deactivation with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deactivate_brand_blocked_by_routed_order
    """
    s = fx.setup_routable_scenario(
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "grams_received": 1000},
    )
    fx.route_order(s["order"]["id"])
    res = api.deactivate_brand(s["brand"]["id"], make_brand_owner_headers(s["brand"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    brand_after = validate_success(api.get_brand(s["brand"]["id"], OPS), 200)
    assert brand_after["status"] == "ACTIVE"


# ── Corner: equipment retire (blocked by held booking + count decrement) ──────

def test_retire_equipment_blocked_by_held_booking(api):
    """PRD §3.1: "Retiring a unit moves it from `AVAILABLE` to `RETIRED`, but only when no
    `EquipmentBooking` for that unit is still `HELD`; a unit with a live held booking cannot
    be retired and the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retire_equipment_blocked_by_held_booking
    """
    stall, equipment, _ = fx.stall_with_held_booking(turnaround_buffer_minutes=0,
                                                     start_minute=100, end_minute=150)
    res = api.retire_equipment(equipment["id"], make_stall_operator_headers(stall["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    stall_after = validate_success(api.get_stall(stall["id"], OPS), 200)
    assert stall_after["equipment_count"] == 1


def test_retire_idle_equipment_decrements_count(api):
    """PRD §3.1: "Retirement also decrements the owning stall's `equipment_count` by one and
    bumps both the equipment's and the stall's `version`."

    Design: Corner/state_machines/retire_equipment_decrements_count
    """
    stall = fx.create_stall(name="SQ")
    equipment = fx.create_equipment(stall["id"], equipment_type="FRYER")
    retired = validate_success(
        api.retire_equipment(equipment["id"], make_stall_operator_headers(stall["id"])), 200)
    assert retired["status"] == "RETIRED"
    stall_after = validate_success(api.get_stall(stall["id"], OPS), 200)
    assert stall_after["equipment_count"] == 0
