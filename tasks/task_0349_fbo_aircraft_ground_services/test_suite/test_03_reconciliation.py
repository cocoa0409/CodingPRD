"""Into-plane reconciliation: tolerance boundary, flagged-above-tolerance, parallel
state axes, and the ledger-sync cumulative advance (PRD §3.6).

Difficulty queue (A) instances:
  - non_linear_state_machine / fuel_order_parallel_axes_independent
  - boundary_precision_check / reconciliation_tolerance_exactly_two_pct
Corner queue (B) instances:
  - calculations / reconciliation_flagged_above_tolerance
  - calculations / ledger_sync_advances_jeta_cumulative
"""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    create_fueled_fuel_order,
    create_dispatched_fuel_order,
    post_into_plane_ticket,
    TEST_USERS,
)

FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_reconciliation_tolerance_exactly_two_pct_reconciles():
    """PRD §3.6: "The ticket's `outcome` is `RECONCILED` when the absolute value of
    `variance_pct` is at most 2.00 — exactly 2.00 still reconciles — and `FLAGGED`
    otherwise."
    PRD §3.6: "Posting a ticket whose outcome is `RECONCILED` is allowed only while the
    order is `FUELED` and its `reconciliation_status` is `NOT_STARTED`, and it advances
    the reconciliation axis `NOT_STARTED → RECONCILED`."

    6120 delivered vs 6000 ordered = +120 gal = +2.00% exactly → RECONCILED.

    Design: Difficulty/boundary_precision_check/reconciliation_tolerance_exactly_two_pct
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    ticket = post_into_plane_ticket(order["id"], 6120)
    assert ticket["variance_pct"] == pytest.approx(2.0, abs=1e-9), (
        f"variance_pct for +120/6000 should be 2.00, got {ticket['variance_pct']}"
    )
    assert ticket["outcome"] == "RECONCILED"
    order_after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert order_after["reconciliation_status"] == "RECONCILED"


def test_reconciliation_flagged_above_tolerance():
    """PRD §3.6: "The ticket's `outcome` is `RECONCILED` when the absolute value of
    `variance_pct` is at most 2.00 — exactly 2.00 still reconciles — and `FLAGGED`
    otherwise."
    PRD §3.6: "Posting a ticket whose outcome is `FLAGGED` under the same preconditions
    instead advances the axis `NOT_STARTED → IN_REVIEW`, creating the ticket with
    `outcome` of `FLAGGED`."

    6121 delivered vs 6000 ordered = +2.02% (> 2.00) → FLAGGED, reconciliation IN_REVIEW.

    Design: Corner/calculations/reconciliation_flagged_above_tolerance
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    ticket = post_into_plane_ticket(order["id"], 6121)
    assert ticket["variance_pct"] == pytest.approx(2.02, abs=1e-9), (
        f"variance_pct for +121/6000 should be 2.02, got {ticket['variance_pct']}"
    )
    assert ticket["outcome"] == "FLAGGED"
    order_after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert order_after["reconciliation_status"] == "IN_REVIEW"


def test_logistics_and_reconciliation_axes_evolve_independently():
    """PRD §3.6: "A **FuelOrder** carries two independent state stories on the same row,
    and they evolve separately."
    PRD §3.6: "Posting a ticket whose outcome is `RECONCILED` is allowed only while the
    order is `FUELED` and its `reconciliation_status` is `NOT_STARTED`, and it advances
    the reconciliation axis `NOT_STARTED → RECONCILED`."

    A FUELED order (logistics axis) reconciles (reconciliation axis NOT_STARTED →
    RECONCILED via a +1% ticket) without disturbing the logistics axis: it stays FUELED.

    Design: Difficulty/non_linear_state_machine/fuel_order_parallel_axes_independent
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    assert order["logistics_status"] == "FUELED"
    assert order["reconciliation_status"] == "NOT_STARTED"
    # 6060 delivered = +1.00% → RECONCILED.
    post_into_plane_ticket(order["id"], 6060)
    order_after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert order_after["logistics_status"] == "FUELED", "logistics axis must remain FUELED"
    assert order_after["reconciliation_status"] == "RECONCILED", "reconciliation axis advanced independently"


def test_complete_fueling_advances_jeta_cumulative_ledger():
    """PRD §3.6: "**Completing fueling** (also `FuelTech`-only) moves the order
    `DISPATCHED → FUELED`; this is the ledger-sync point — for a non-tankering Jet-A
    order, the order's `ordered_gallons` are added to the operator's
    `jeta_month_cumulative_gallons`, advancing the operator's volume tier for subsequent
    orders."

    Completing fueling on a non-tankering JET_A 6000-gal order advances the operator's
    cumulative from 0 to 6000.

    Design: Corner/calculations/ledger_sync_advances_jeta_cumulative
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_dispatched_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                         ordered_gallons=6000, tankering=False)
    fueled = get_success_data(api.complete_fueling_fuel_order(order["id"], FUEL))
    assert fueled["logistics_status"] == "FUELED"
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["jeta_month_cumulative_gallons"] == 6000, (
        f"cumulative should advance to 6000 after fueling, got "
        f"{operator_after['jeta_month_cumulative_gallons']}"
    )
