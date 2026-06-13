"""Money-flow and conservation tests: deposit refund/forfeit conservation, staff-pool
reserve/release conservation, payment-then-settle, OCC staleness on change-accept, version
increments, and immediate consistency of derived fields on confirm.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CAPTAIN = TEST_USERS["captain_headers"]


# =====================================================================
# Queue A — Rule 9: compensating invariant
# =====================================================================
def test_cancel_conserves_deposit_refund_plus_forfeit(api):
    """PRD §3.9: "otherwise if hours-out is at least 72, the fraction is 0.50".
    PRD §3.9: "the forfeited amount is `deposit_due_cents` minus the refunded amount (computed
    by subtraction so that refunded plus forfeited always conserves exactly to the deposit, with
    no independent rounding on the forfeit)."

    Design: Difficulty/compensating_invariant/cancel_conserves_deposit_money_refund_plus_forfeit
    """
    # Clock 2026-08-20T17:00 vs event 2026-09-01T17:00 → ~288h... ensure half tier (>=72,<168).
    # 2026-08-20T17:00 to 2026-09-01T17:00 is 12 days = 288h >= 168 → FULL refund, not half.
    # Use clock that lands strictly in [72,168): 2026-08-27T17:00 → 5 days = 120h.
    ctx = fx.setup_confirmed_order(clock="2026-08-27T17:00:00Z", booked_headcount=80)
    order = ctx["order"]
    assert order["deposit_due_cents"] == 146750
    cancelled = validate_success(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]},
                         ctx["client_headers"])
    )
    assert cancelled["settlement_status"] == "REFUNDED"

    entries, _ = validate_paginated(api.list_order_ledger(order["id"], COORD))
    refund = sum(int(e["amount_cents"]) for e in entries if e["entry_type"] == "REFUND")
    forfeit = sum(int(e["amount_cents"]) for e in entries if e["entry_type"] == "FORFEIT")
    # refund -73375, forfeit +73375; |refund| + forfeit == deposit 146750.
    assert abs(refund) == 73375
    assert forfeit == 73375
    assert abs(refund) + forfeit == 146750


def test_fulfill_conserves_staff_pool_reserve_plus_release(api):
    """PRD §2.9: "Releasing a reservation — on fulfillment or on cancellation — credits its
    `reserved_staff` back to the pool."
    PRD §3.8: "releases the order's `StaffingReservation` by moving its `status` from `HELD` to
    `RELEASED` and crediting its `reserved_staff` back to the global pool".

    Design: Difficulty/compensating_invariant/fulfill_conserves_staff_pool_reserve_plus_release
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fx.set_staff_pool(10)
    route = fx.create_route(vehicle_capacity_legs=3)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    fx.add_staffing(order["id"], ctx["client_headers"], quantity=3)
    order = fx.confirm_order(order)
    order = fx.guarantee_order(order, 80)
    order = fx.invoice_order(order)
    final = order["final_total_cents"]
    order = fx.pay_order(order, ctx["client_headers"], final)
    order = fx.settle_order(order)
    leg = fx.create_leg(order["id"], route["id"],
                        "2026-09-01T15:00:00Z", "2026-09-01T16:00:00Z")
    fx.dispatch_leg(leg["id"], route["id"])
    fx.deliver_leg(leg["id"], route["id"])

    # Leg creation bumped order.version (set route_id); refetch before version-checked fulfill.
    order = validate_success(api.get_order(order["id"], CAPTAIN))
    fulfilled = validate_success(
        api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, CAPTAIN)
    )
    assert fulfilled["lifecycle_status"] == "FULFILLED"

    reservations, _ = validate_paginated(api.list_order_staffing_reservation(order["id"], COORD))
    assert reservations[0]["status"] == "RELEASED"
    assert reservations[0]["reserved_staff"] == 3

    # Pool returned to 10: a fresh order reserving 10 staff must confirm successfully.
    ctx2 = fx.create_draft_order(
        client_overrides={"company_name": "Acme2", "billing_email": "a2@x.com"},
        booked_headcount=80,
    )
    order2 = ctx2["order"]
    fx.add_staffing(order2["id"], ctx2["client_headers"], quantity=10)
    confirmed2 = validate_success(
        api.confirm_order(order2["id"], {"expected_order_version": order2["version"]}, COORD)
    )
    assert confirmed2["lifecycle_status"] == "CONFIRMED", "pool fully credited back to 10"


def test_cancel_conserves_deposit_balance_nets_to_negative_refund(api):
    """PRD §3.9: "The refunded amount is the order's `deposit_due_cents` multiplied by the refund
    fraction, rounded half-up to whole cents; the forfeited amount is `deposit_due_cents` minus
    the refunded amount (computed by subtraction so that refunded plus forfeited always conserves
    exactly to the deposit, with no independent rounding on the forfeit)."

    Design: Difficulty/compensating_invariant/cancel_conserves_deposit_money_refund_plus_forfeit
    """
    # Half tier (120h out): refund fraction 0.50 → refunded 73375, forfeited 73375. The two
    # entries are written with opposite signs and each is exactly half the deposit.
    ctx = fx.setup_confirmed_order(clock="2026-08-27T17:00:00Z", booked_headcount=80)
    order = ctx["order"]
    validate_success(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]},
                         ctx["client_headers"])
    )
    entries, _ = validate_paginated(api.list_order_ledger(order["id"], COORD))
    refund = [int(e["amount_cents"]) for e in entries if e["entry_type"] == "REFUND"]
    forfeit = [int(e["amount_cents"]) for e in entries if e["entry_type"] == "FORFEIT"]
    assert refund == [-73375], "REFUND entry is the negative refunded amount"
    assert forfeit == [73375], "FORFEIT entry is the positive forfeited amount"
    # Conservation: |refund| + forfeit == deposit_due_cents (146750), no drift.
    assert abs(refund[0]) + forfeit[0] == 146750


def test_confirm_debits_staff_pool_so_overflow_is_rejected(api):
    """PRD §2.9: "When an order confirms, the staff implied by its `STAFFING` add-on lines are
    reserved against this pool; if the reservation would exceed the remaining capacity,
    confirmation is rejected with `ERR_STAFF_POOL_EXHAUSTED`".

    Design: Difficulty/compensating_invariant/fulfill_conserves_staff_pool_reserve_plus_release
    """
    # Pool 10; confirm order reserving 7 (pool → 3 remaining); a second order reserving 5 then
    # fails because the forward reserve debited the pool (5 > 3 remaining).
    fx.set_clock("2026-06-01T00:00:00Z")
    fx.set_staff_pool(10)
    ctx1 = fx.create_draft_order(booked_headcount=80)
    o1 = ctx1["order"]
    fx.add_staffing(o1["id"], ctx1["client_headers"], quantity=7)
    fx.confirm_order(o1)

    ctx2 = fx.create_draft_order(
        client_overrides={"company_name": "Acme2", "billing_email": "a2@x.com"},
        booked_headcount=80,
    )
    o2 = ctx2["order"]
    fx.add_staffing(o2["id"], ctx2["client_headers"], quantity=5)
    validate_error(
        api.confirm_order(o2["id"], {"expected_order_version": o2["version"]}, COORD),
        ApiErrorId.ERR_STAFF_POOL_EXHAUSTED.value,
    )


# =====================================================================
# Queue B — endpoints
# =====================================================================
def test_payment_equal_to_final_lets_settle_succeed(api):
    """PRD §3.7: "Settlement is the final money step. A `SalesCoordinator` settles an order ...
    settlement is permitted only when `settlement_status` is `INVOICED` and the running
    deposit-ledger balance for the order exactly equals `final_total_cents`."

    Design: Corner/endpoints/payment_advances_ledger_then_settle_succeeds
    """
    ctx = fx.setup_invoiced_order(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z")
    order = ctx["order"]
    assert order["final_total_cents"] == 587000
    order = fx.pay_order(order, ctx["client_headers"], 587000)
    settled = validate_success(
        api.settle_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    assert settled["settlement_status"] == "SETTLED"


def test_patch_draft_order_updates_headcount_and_bumps_version(api):
    """PRD §3.2: "A successful edit applies the supplied fields and increments the order
    `version`."

    Design: Corner/endpoints/patch_draft_order_updates_headcount
    """
    ctx = fx.create_draft_order(booked_headcount=80)
    order = ctx["order"]
    patched = validate_success(
        api.patch_order(order["id"],
                        {"expected_order_version": order["version"], "booked_headcount": 100},
                        ctx["client_headers"])
    )
    assert patched["booked_headcount"] == 100
    assert patched["version"] == 2


def test_delivery_leg_creation_sets_order_route_id(api):
    """PRD §3.11: "Creating a leg sets its `stop_status` to `PLANNED`, sets the owning order's
    `route_id` to the route if it was still null".

    Design: Corner/endpoints/delivery_leg_creation_sets_order_route_id
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    route = fx.create_route(vehicle_capacity_legs=3)
    ctx = fx.create_draft_order(booked_headcount=80)
    order = fx.confirm_order(ctx["order"])
    leg = validate_success(
        api.create_delivery_leg(
            {"order_id": order["id"], "route_id": route["id"],
             "window_start": "2026-09-01T15:00:00Z", "window_end": "2026-09-01T16:00:00Z"},
            COORD,
        ),
        expected_status=201,
    )
    assert leg["route_id"] == route["id"]
    order_after = validate_success(api.get_order(order["id"], COORD))
    assert order_after["route_id"] == route["id"]


# SKIPPED Corner/endpoints/list_orders_filtered_by_client_id:
#   The only PRD coverage for GET /catering/orders filtering is the §4 table row
#   "List orders (filterable)" — endpoint-titular (C2 fail). PRD prose never states that
#   client_id is a supported filter or its exact semantics, so a faithful PRD-only reader
#   could omit client_id filtering entirely. Not uniquely derivable → gap stays a gap.


# =====================================================================
# Queue B — cross-cutting complexity (OCC) + consistency
# =====================================================================
def test_second_change_accept_with_stale_order_version_rejected(api):
    """PRD §2.11: "If the order's `version` has advanced since that observation — for instance
    because an earlier change request was already accepted and legitimately superseded the
    headcount and totals this acceptance was quoted against — the acceptance is rejected with
    `ERR_STALE_ORDER_VERSION`".

    Design: Corner/cross_cutting_complexity_layers/accept_second_change_with_stale_order_version
    """
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    order = ctx["order"]
    stale_v = order["version"]
    cr1 = fx.open_change_request(order["id"], ctx["client_headers"], requested_headcount=90)
    cr2 = fx.open_change_request(order["id"], ctx["client_headers"], requested_headcount=95)
    # Accept CR1 → advances Order.version past stale_v.
    validate_success(
        api.accept_change_request(cr1["id"], {"expected_order_version": stale_v}, COORD)
    )
    # Accept CR2 still carrying the pre-supersede version → stale.
    validate_error(
        api.accept_change_request(cr2["id"], {"expected_order_version": stale_v}, COORD),
        ApiErrorId.ERR_STALE_ORDER_VERSION.value,
    )
    cr2_after = validate_success(api.get_change_request(cr2["id"], COORD))
    assert cr2_after["status"] == "PROPOSED"


def test_order_version_increments_by_one_on_confirm(api):
    """PRD §2.4: "The `version` is an integer that starts at 1 and increments by exactly 1 on
    every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_order_mutation
    """
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    assert ctx["order"]["version"] == 2


def test_confirm_response_reflects_derived_fields_immediately(api):
    """PRD §2.5: "every mutation, including the derived recomputations it triggers, completes
    inside the request that caused it, with no asynchronous reconciliation."
    PRD §3.5: "It computes `provisional_total_cents` via the provisional grand-total pass and
    `deposit_due_cents` via the deposit computation."

    Design: Corner/consistency_model/confirm_response_reflects_all_derived_fields_immediately
    """
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    order = ctx["order"]
    assert order["provisional_total_cents"] == 587000
    assert order["deposit_due_cents"] == 146750
    assert order["settlement_status"] == "DEPOSIT_HELD"
