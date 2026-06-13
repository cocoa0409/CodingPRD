"""Service-visit and garment lifecycle: the cyclic weekly rotation, the garment's
two independent state dimensions, invalid transitions, terminal lockdown, the
ramp-down/reinstate revert, and the deliver-while-soiled guard.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_provisional_finalized_visit,
    make_account,
    make_garment_type,
    make_wash_station,
    make_wearer,
    make_garment,
    make_assignment,
    setup_route_stop_for_account,
    make_service_visit,
    wash_garment,
    get_garment,
    pickup_payload,
    reconcile_payload,
    start_wash_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
TECH = TEST_USERS["cleanroom_tech_headers"]


# ─── Queue A: non_linear_state_machine ────────────────────────────────────

def test_service_visit_cycles_fresh_each_week(api):
    """PRD §3.8: "The rotation is realized as a `ServiceVisit`, a cyclic weekly record
    scheduled against a route stop by an administrator or a driver. A visit is created
    with a `week_index`, a monotonic week counter that must be a non-negative integer and
    that uniquely identifies the visit within its stop."
    PRD §3.8: "On pickup the system snapshots `expected_soil_count` as the count of the
    account's garments that are currently `ASSIGNED` and `AT_CUSTOMER` — the garments that
    ought to be coming back."

    Design: Difficulty/non_linear_state_machine/service_visit_cyclic_weekly_rotation
    """
    # Week 0: take the garment through the full cycle back to AT_CUSTOMER.
    acct = make_account(shortage_grace_units=0)
    gt = make_garment_type(weekly_rate_cents=1000)
    ws = make_wash_station(capacity=5)
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    make_assignment(g["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])

    v0 = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(v0["id"], pickup_payload(1), DRIVER))
    wash_garment(g["id"], ws["id"])
    get_success_data(api.deliver_visit(v0["id"], DRIVER))

    # Week 1: a brand-new visit on the same stop re-runs the cycle from SCHEDULED.
    v1 = make_service_visit(stop["id"], week_index=1)
    picked = get_success_data(api.pickup_visit(v1["id"], pickup_payload(1), DRIVER))
    assert picked["status"] == "PICKED_UP", f"week-1 visit should advance to PICKED_UP, got {picked['status']}"
    assert picked["expected_soil_count"] == 1, (
        f"the garment delivered back AT_CUSTOMER should be expected in soil again, got "
        f"{picked['expected_soil_count']}"
    )
    garment = get_garment(g["id"])
    assert garment["wash_location"] == "IN_SOIL", (
        f"the garment should re-enter IN_SOIL on the second week's pickup, got "
        f"{garment['wash_location']}"
    )


def test_service_visit_runs_full_state_sequence_in_one_week(api):
    """PRD §3.8: "A visit's `status` cycles through `SCHEDULED`, `PICKED_UP`, `DELIVERED`,
    and `RECONCILED`, beginning at `SCHEDULED`, with `RECONCILED` terminal."

    Design: Difficulty/non_linear_state_machine/service_visit_cyclic_weekly_rotation
    """
    ctx = setup_provisional_finalized_visit(grace=5, weekly_rate_cents=1000,
                                            num_garments=1, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    assert visit["status"] == "DELIVERED", (
        f"the visit should be DELIVERED after pickup+deliver, got {visit['status']}"
    )
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    assert reconciled["status"] == "RECONCILED", (
        f"one weekly cycle must terminate in RECONCILED, got {reconciled['status']}"
    )


def test_garment_lifecycle_unchanged_while_wash_dimension_advances(api):
    """PRD §3.5: "The wash dimension turns independently of the lifecycle dimension — a
    garment stays `ASSIGNED` throughout the week while its `wash_location` cycles
    `AT_CUSTOMER → IN_SOIL → IN_WASH → AT_PLANT → AT_CUSTOMER`."
    PRD §3.5: "Finishing a wash is permitted only while `wash_location` is `IN_WASH`; it
    advances the garment `IN_WASH → AT_PLANT`, clears `wash_station_id`, `slot_start_min`,
    and `slot_end_min` back to null, sets `cycled_through_wash_this_visit` to true, and
    increments `version`."

    Design: Difficulty/non_linear_state_machine/garment_parallel_lifecycle_x_wash_dimensions
    """
    acct = make_account(shortage_grace_units=5)
    gt = make_garment_type(category="PANT", weekly_rate_cents=1000)
    ws = make_wash_station(capacity=5)
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    make_assignment(g["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(1), DRIVER))
    get_success_data(api.start_wash(g["id"], start_wash_payload(ws["id"], 600, 660), TECH))
    finished = validate_success(api.finish_wash(g["id"], TECH), 200)
    # lifecycle dimension never moved off ASSIGNED while wash dimension reached AT_PLANT.
    assert finished["lifecycle_status"] == "ASSIGNED", (
        f"lifecycle must remain ASSIGNED through the wash cycle, got {finished['lifecycle_status']}"
    )
    assert finished["wash_location"] == "AT_PLANT", (
        f"finish-wash must land the garment AT_PLANT, got {finished['wash_location']}"
    )


def test_start_wash_advances_only_wash_dimension(api):
    """PRD §3.5: "The garment's `wash_location` advances `IN_SOIL → IN_WASH`, its
    `wash_station_id` and slot window are recorded from the body, and its `version`
    increments."

    Design: Difficulty/non_linear_state_machine/garment_parallel_lifecycle_x_wash_dimensions
    """
    acct = make_account(shortage_grace_units=5)
    gt = make_garment_type(category="PANT", weekly_rate_cents=1000)
    ws = make_wash_station(capacity=5)
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    make_assignment(g["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(1), DRIVER))
    started = validate_success(api.start_wash(g["id"], start_wash_payload(ws["id"], 600, 660), TECH), 200)
    # The lifecycle dimension is untouched; only wash_location moved to IN_WASH.
    assert started["lifecycle_status"] == "ASSIGNED", (
        f"start-wash must not touch lifecycle_status, got {started['lifecycle_status']}"
    )
    assert started["wash_location"] == "IN_WASH", (
        f"start-wash must advance wash_location to IN_WASH, got {started['wash_location']}"
    )


# ─── Queue B: state_machines section ──────────────────────────────────────

def test_pickup_on_delivered_visit_invalid_state(api):
    """PRD §3.8: "Pickup is the driver's first field action and is permitted only while
    the visit is `SCHEDULED`, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pickup_from_delivered_returns_invalid_state
    """
    ctx = setup_provisional_finalized_visit(grace=5, weekly_rate_cents=1000,
                                            num_garments=1, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]  # already DELIVERED
    res = api.pickup_visit(visit["id"], pickup_payload(1), DRIVER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_second_reconcile_on_reconciled_visit_invalid_state(api):
    """PRD §3.10: "Reconciliation is the administrator's closing act on a visit, advancing
    it `DELIVERED → RECONCILED`, and it is permitted only while the visit is `DELIVERED`
    (else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/reconciled_visit_terminal_lockdown
    """
    ctx = setup_provisional_finalized_visit(grace=5, weekly_rate_cents=1000,
                                            num_garments=1, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    # A second reconcile on the now-RECONCILED (terminal) visit is an invalid transition.
    res = api.reconcile_visit(visit["id"], reconcile_payload(reconciled["version"]), ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_new_visit_starts_scheduled_version_one(api):
    """PRD §3.8: "A visit's `status` cycles through `SCHEDULED`, `PICKED_UP`,
    `DELIVERED`, and `RECONCILED`, beginning at `SCHEDULED`, with `RECONCILED` terminal."
    PRD §2.4: "an integer `version` that begins at its initial value on creation and
    increments by exactly one on every mutation."

    Design: Corner/state_machines/new_visit_starts_scheduled
    """
    acct = make_account()
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = validate_success(api.create_service_visit(stop["id"], {"week_index": 0}, ADMIN), 201)
    assert visit["status"] == "SCHEDULED", f"new visit must start SCHEDULED, got {visit['status']}"
    assert visit["version"] == 1, f"new visit version must begin at 1, got {visit['version']}"


def test_wearer_reinstate_reverts_to_active_with_two_mutations(api):
    """PRD §3.2: "Reinstating a ramped-down wearer is the revert edge, moving
    `roster_status` from `RAMP_DOWN` back to `ACTIVE`."
    PRD §2.4: "an integer `version` that begins at its initial value on creation and
    increments by exactly one on every mutation."

    Design: Corner/state_machines/wearer_ramp_down_then_reinstate_revert
    """
    acct = make_account()
    wearer = make_wearer(acct["id"])  # version 1, ACTIVE
    validate_success(api.ramp_down_wearer(wearer["id"], MANAGER), 200)  # version 2
    reinstated = validate_success(api.reinstate_wearer(wearer["id"], MANAGER), 200)  # version 3
    assert reinstated["roster_status"] == "ACTIVE", (
        f"reinstate must return roster_status to ACTIVE, got {reinstated['roster_status']}"
    )
    assert reinstated["version"] == 3, (
        f"two mutations after creation must yield version 3, got {reinstated['version']}"
    )


def test_deliver_blocked_while_garment_still_in_soil(api):
    """PRD §3.9: "Delivery additionally requires that the plant work be finished: every
    garment for this account must have completed its journey out of soil and wash, meaning
    no garment for the account may remain `IN_SOIL` or `IN_WASH`. If any garment is still
    soiled or still washing, delivery is rejected with `ERR_VISIT_GARMENTS_NOT_CLEAN`."

    Design: Corner/validations/deliver_blocked_while_garment_still_in_soil
    """
    acct = make_account(shortage_grace_units=5)
    gt = make_garment_type(weekly_rate_cents=1000)
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    make_assignment(g["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    # Pickup moves the garment into IN_SOIL; it is never washed.
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(1), DRIVER))
    res = api.deliver_visit(visit["id"], DRIVER)
    validate_error(res, "ERR_VISIT_GARMENTS_NOT_CLEAN", expected_status=409)
