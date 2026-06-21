"""State-machine and cascade tests: the cyclic change-request negotiation, the two parallel
order dimensions, the depth-3 order-cancel cascade to legs and route posture, the confirm-time
deposit/staffing cascade, plus the corner state-machine transitions and side effects.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CAPTAIN = TEST_USERS["captain_headers"]


# =====================================================================
# Queue A — Rule 3: non-linear state machine
# =====================================================================
def test_change_request_cycles_proposed_countered_proposed(api):
    """PRD §3.10: "In response, the `Client` may revise a `COUNTERED` request — permitted only
    when the request is `COUNTERED` — by supplying a new `requested_headcount`; this moves the
    request from `COUNTERED` back to `PROPOSED`, clears the `counter_headcount` to null, and
    bumps the request `version`."

    Design: Difficulty/non_linear_state_machine/change_request_proposed_countered_proposed_cycle
    """
    ctx = fx.setup_order_with_open_change(requested_headcount=90, clock="2026-06-01T00:00:00Z")
    cr = ctx["change_request"]
    fx.counter_change_request(cr["id"], counter_headcount=85)

    revised = validate_success(
        api.revise_change_request(cr["id"], {"requested_headcount": 95}, ctx["client_headers"])
    )
    assert revised["status"] == "PROPOSED"
    assert revised["requested_headcount"] == 95
    assert revised["counter_headcount"] is None


def test_order_parallel_dimensions_evolve_independently(api):
    """PRD §2.10: "confirming an order advances `lifecycle_status` from `DRAFT` to `CONFIRMED`
    and, as a side effect of that same operation, advances `settlement_status` from `UNBILLED`
    to `DEPOSIT_HELD`."
    PRD §3.7: "Invoicing computes `final_total_cents` ... advances `settlement_status` from
    `DEPOSIT_HELD` to `INVOICED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_lifecycle_and_settlement_dimensions
    """
    ctx = fx.setup_guaranteed_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z")
    order = ctx["order"]
    invoiced = validate_success(
        api.invoice_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    assert invoiced["lifecycle_status"] == "GUARANTEED"
    assert invoiced["settlement_status"] == "INVOICED"


def test_change_request_counter_moves_proposed_to_countered(api):
    """PRD §3.10: "A `SalesCoordinator` may counter a `PROPOSED` request ... by supplying a
    `counter_headcount`; this moves the request from `PROPOSED` to `COUNTERED`, records the
    `counter_headcount`, and bumps the request `version`."

    Design: Difficulty/non_linear_state_machine/change_request_proposed_countered_proposed_cycle
    """
    ctx = fx.setup_order_with_open_change(requested_headcount=90, clock="2026-06-01T00:00:00Z")
    cr = ctx["change_request"]
    countered = validate_success(
        api.counter_change_request(cr["id"], {"counter_headcount": 85}, COORD)
    )
    assert countered["status"] == "COUNTERED"
    assert countered["counter_headcount"] == 85


def test_confirm_advances_both_dimensions_in_one_request(api):
    """PRD §2.10: "confirming an order advances `lifecycle_status` from `DRAFT` to `CONFIRMED` and,
    as a side effect of that same operation, advances `settlement_status` from `UNBILLED` to
    `DEPOSIT_HELD`. The settlement transition `UNBILLED → DEPOSIT_HELD` never fires on its own".

    Design: Difficulty/non_linear_state_machine/order_parallel_lifecycle_and_settlement_dimensions
    """
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    order = ctx["order"]
    assert order["lifecycle_status"] == "CONFIRMED"
    assert order["settlement_status"] == "DEPOSIT_HELD"


# =====================================================================
# Queue A — Rule 4: transitive cascade
# =====================================================================
def test_cancel_cascades_legs_to_failed_and_route_to_blocked(api):
    """PRD §2.5: "When an order is cancelled, every still-planned delivery leg attached to it is
    driven to `FAILED`, and each of those leg transitions in turn recomputes its route's posture".
    PRD §3.11: "if any leg is `FAILED`, the posture is `BLOCKED`".

    Design: Difficulty/transitive_cascade/cancel_order_cascades_to_legs_then_route_posture
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    route = fx.create_route(vehicle_capacity_legs=3)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = fx.confirm_order(ctx["order"])
    leg = fx.create_leg(order["id"], route["id"],
                        "2026-09-01T15:00:00Z", "2026-09-01T16:00:00Z")

    # Leg creation set order.route_id (a mutation that bumped order.version); refetch
    # the live version before the version-checked cancel.
    order = validate_success(api.get_order(order["id"], COORD))
    cancelled = validate_success(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]},
                         ctx["client_headers"])
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"

    leg_after = validate_success(api.get_delivery_leg(leg["id"], CAPTAIN))
    assert leg_after["stop_status"] == "FAILED"

    route_after = validate_success(api.get_route(route["id"], CAPTAIN))
    assert route_after["posture"] == "BLOCKED"


def test_confirm_cascades_deposit_hold_and_staffing_reservation(api):
    """PRD §3.5: "It advances `settlement_status` from `UNBILLED` to `DEPOSIT_HELD` and appends
    a `DEPOSIT_HOLD` ledger entry whose `amount_cents` equals the positive deposit due. It
    creates a `StaffingReservation` in status `HELD` whose `reserved_staff` equals the sum of
    the effective quantities of the order's `STAFFING` add-on lines at confirmation".

    Design: Difficulty/transitive_cascade/confirm_order_cascades_deposit_ledger_and_staffing_reservation
    """
    ctx = fx.setup_confirmed_order(
        clock="2026-06-01T00:00:00Z", booked_headcount=80, staffing_qty=3, staff_pool=10,
    )
    order = ctx["order"]
    assert order["settlement_status"] == "DEPOSIT_HELD"

    entries, _ = validate_paginated(api.list_order_ledger(order["id"], COORD))
    holds = [e for e in entries if e["entry_type"] == "DEPOSIT_HOLD"]
    assert len(holds) == 1
    assert int(holds[0]["amount_cents"]) == order["deposit_due_cents"]

    reservations, _ = validate_paginated(api.list_order_staffing_reservation(order["id"], COORD))
    assert len(reservations) == 1
    assert reservations[0]["status"] == "HELD"
    assert reservations[0]["reserved_staff"] == 3


def test_cancel_releases_staffing_reservation_in_cascade(api):
    """PRD §3.9: "In every confirmed-or-later cancellation, the `StaffingReservation` is released
    (`HELD → RELEASED`, crediting `reserved_staff` back to the pool), and every still-`PLANNED`
    delivery leg on the order is cascaded to `FAILED`".

    Design: Difficulty/transitive_cascade/cancel_order_cascades_to_legs_then_route_posture
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fx.set_staff_pool(10)
    route = fx.create_route(vehicle_capacity_legs=3)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    fx.add_staffing(order["id"], ctx["client_headers"], quantity=3)
    order = fx.confirm_order(order)
    leg = fx.create_leg(order["id"], route["id"],
                        "2026-09-01T15:00:00Z", "2026-09-01T16:00:00Z")
    # Leg creation bumped order.version (set route_id); refetch before version-checked cancel.
    order = validate_success(api.get_order(order["id"], COORD))
    validate_success(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]},
                         ctx["client_headers"])
    )
    # Cascade leg → FAILED → route BLOCKED, AND reservation released.
    leg_after = validate_success(api.get_delivery_leg(leg["id"], CAPTAIN))
    assert leg_after["stop_status"] == "FAILED"
    reservations, _ = validate_paginated(api.list_order_staffing_reservation(order["id"], COORD))
    assert reservations[0]["status"] == "RELEASED"


def test_confirm_deposit_hold_amount_equals_deposit_due(api):
    """PRD §3.5: "It advances `settlement_status` from `UNBILLED` to `DEPOSIT_HELD` and appends a
    `DEPOSIT_HOLD` ledger entry whose `amount_cents` equals the positive deposit due."

    Design: Difficulty/transitive_cascade/confirm_order_cascades_deposit_ledger_and_staffing_reservation
    """
    # No staffing add-on here: provisional grand 587000, non-rush deposit 25% = 146750,
    # and the DEPOSIT_HOLD ledger amount must equal that deposit exactly.
    ctx = fx.setup_confirmed_order(
        clock="2026-06-01T00:00:00Z", booked_headcount=80,
    )
    order = ctx["order"]
    assert order["deposit_due_cents"] == 146750
    entries, _ = validate_paginated(api.list_order_ledger(order["id"], COORD))
    holds = [e for e in entries if e["entry_type"] == "DEPOSIT_HOLD"]
    assert len(holds) == 1
    assert int(holds[0]["amount_cents"]) == order["deposit_due_cents"] == 146750


# =====================================================================
# Queue B — state machines
# =====================================================================
def test_confirm_already_confirmed_order_rejected(api):
    """PRD §3.5: "It is permitted only when the order is in `DRAFT`; otherwise it is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_already_confirmed_returns_invalid_state
    """
    from test_helpers import validate_error, ApiErrorId
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    order = ctx["order"]
    validate_error(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, COORD),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "CONFIRMED"


def test_new_order_starts_draft_and_unbilled(api):
    """PRD §2.10: "The `lifecycle_status` is the provisioning dimension and takes the values
    `DRAFT`, `CONFIRMED`, `GUARANTEED`, `FULFILLED`, and `CANCELLED`, beginning at `DRAFT`...
    The `settlement_status` is the money dimension ... beginning at `UNBILLED`".

    Design: Corner/state_machines/new_order_starts_in_draft_and_unbilled
    """
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    assert order["lifecycle_status"] == "DRAFT"
    assert order["settlement_status"] == "UNBILLED"


def test_cancel_already_cancelled_order_rejected(api):
    """PRD §2.10: "`FULFILLED` and `CANCELLED` are terminal."
    PRD §3.12: "then the target's state-validity for the attempted transition across whichever
    dimension applies (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    from test_helpers import validate_error, ApiErrorId
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    cancelled = fx.cancel_order(order, ctx["client_headers"])
    validate_error(
        api.cancel_order(order["id"], {"expected_order_version": cancelled["version"]},
                         ctx["client_headers"]),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "CANCELLED"


def test_deliver_only_leg_closes_route(api):
    """PRD §3.11: "Delivering a `DISPATCHED` leg — carrying `expected_route_version` — moves it
    from `DISPATCHED` to `DELIVERED`, recomputes the route posture (which becomes `CLOSED` once
    every leg is delivered)".
    PRD §3.11: "The route's `dispatched_leg_count` is maintained separately as the count of legs
    in `DISPATCHED` or `DELIVERED` status."

    Design: Corner/state_machines/deliver_leg_marks_route_closed_when_all_delivered
    """
    ctx = fx.setup_guaranteed_order_with_route_and_leg(guaranteed_headcount=80)
    leg, route = ctx["leg"], ctx["route"]
    fx.dispatch_leg(leg["id"], route["id"])
    delivered = validate_success(
        api.deliver_delivery_leg(leg["id"], {"expected_route_version": fx.route_version(route["id"])},
                                 CAPTAIN)
    )
    assert delivered["stop_status"] == "DELIVERED"
    route_after = validate_success(api.get_route(route["id"], CAPTAIN))
    assert route_after["posture"] == "CLOSED"
    assert route_after["dispatched_leg_count"] == 1


def test_dispatch_already_dispatched_leg_rejected(api):
    """PRD §3.11: "a dispatch from a non-`PLANNED` leg is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispatch_second_call_idempotency_rejected
    """
    from test_helpers import validate_error, ApiErrorId
    ctx = fx.setup_guaranteed_order_with_route_and_leg(guaranteed_headcount=80)
    leg, route = ctx["leg"], ctx["route"]
    fx.dispatch_leg(leg["id"], route["id"])
    validate_error(
        api.dispatch_delivery_leg(leg["id"], {"expected_route_version": fx.route_version(route["id"])},
                                  CAPTAIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    route_after = validate_success(api.get_route(route["id"], CAPTAIN))
    assert route_after["dispatched_leg_count"] == 1


def test_change_accept_reverts_guaranteed_order_to_confirmed(api):
    """PRD §3.10: "if the order was `GUARANTEED`, the headcount change invalidates the guarantee,
    so the order reverts from `GUARANTEED` to `CONFIRMED` and its `guaranteed_headcount` is
    cleared to null."

    Design: Corner/state_machines/change_accept_reverts_guaranteed_order_to_confirmed
    """
    ctx = fx.setup_guaranteed_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z",
                                    booked_headcount=80)
    order = ctx["order"]
    cr = fx.open_change_request(order["id"], ctx["client_headers"], requested_headcount=90)
    accepted = validate_success(
        api.accept_change_request(cr["id"], {"expected_order_version": order["version"]}, COORD)
    )
    assert accepted["status"] == "ACCEPTED"
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "CONFIRMED"
    assert after["guaranteed_headcount"] is None
    assert after["booked_headcount"] == 90


def test_reject_change_request_leaves_order_unchanged(api):
    """PRD §3.10: "Either way the request moves to `REJECTED`, the request `version` bumps, and
    the order is left entirely unchanged — it keeps its current headcount and totals."

    Design: Corner/state_machines/reject_change_request_leaves_order_unchanged
    """
    ctx = fx.setup_order_with_open_change(requested_headcount=90, clock="2026-06-01T00:00:00Z",
                                          booked_headcount=80)
    cr = ctx["change_request"]
    rejected = validate_success(api.reject_change_request(cr["id"], {}, COORD))
    assert rejected["status"] == "REJECTED"
    after = validate_success(api.get_order(ctx["order"]["id"], COORD))
    assert after["booked_headcount"] == 80


def test_guarantee_from_draft_rejected(api):
    """PRD §3.6: "Once an order is `CONFIRMED`, a `SalesCoordinator` locks the guaranteed guest
    count ... The guarantee is permitted only when the order is `CONFIRMED` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/guarantee_from_draft_returns_invalid_state
    """
    from test_helpers import validate_error, ApiErrorId
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    validate_error(
        api.guarantee_order(order["id"],
                            {"expected_order_version": order["version"], "guaranteed_headcount": 80},
                            COORD),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = validate_success(api.get_order(order["id"], COORD))
    assert after["lifecycle_status"] == "DRAFT"
