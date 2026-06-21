"""Transitive cascades (visit-cancel depth-3, adjust-billing depth-3) and the
compensating invoice/balance invariants (PRD §3.3, §3.6, §3.7).

Difficulty queue (A) instances:
  - transitive_cascade / visit_cancel_cascade_depth3
  - transitive_cascade / adjust_billing_cascade_depth3
  - compensating_invariant / adjust_billing_conserves_invoice_total_equals_lines
  - compensating_invariant / void_conserves_operator_open_balance
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_departed_visit_with_invoice,
    get_invoice_for_visit,
    create_parking_assignment_payload,
    occupy_payload,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
LINE = TEST_USERS["line_manager_headers"]


def test_visit_cancel_releases_assignment_and_frees_spot_window():
    """PRD §3.3: "Cancelling an `ON_GROUND` visit is permitted only when no fuel order on
    the visit has reached `FUELED`; it moves the visit `ON_GROUND → CANCELLED` and runs a
    deeper cascade: every non-terminal parking assignment is released to `RELEASED` and
    each released assignment frees its spot's occupation window so it no longer blocks
    overlap checks; every non-terminal ramp service is cancelled to `CANCELLED`; and
    every ramp slot in `REQUESTED` or `APPROVED` status is revoked to `REVOKED`."
    PRD §3.4: "For a `TIE_DOWN` or `RAMP` spot, the system uses plain half-open overlap
    with no buffer — two intervals conflict only if they actually overlap, so one window
    ending exactly when the next begins is allowed — and a true overlap against an
    `OCCUPIED` assignment on the same spot is rejected with `ERR_SPOT_WINDOW_CONFLICT`
    (HTTP 409)."

    Depth-3: cancel ON_GROUND visit → OCCUPIED assignment RELEASED → spot window freed,
    so a second HELD assignment overlapping the same TIE_DOWN window can now occupy.

    Design: Difficulty/transitive_cascade/visit_cancel_cascade_depth3
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    spot = get_success_data(api.create_parking_spot(
        {"label": "TD-7", "spot_type": "TIE_DOWN", "max_weight_class": "HEAVY"}, OPS))

    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    pa1 = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(v1["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T10:00:00.000Z",
                                          occupy_end_utc="2026-06-14T11:00:00.000Z"), OPS))
    get_success_data(api.occupy_parking_assignment(pa1["id"], occupy_payload(pa1["version"]), OPS))

    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-14T09:00:00.000Z",
                                                "departure_utc": "2026-06-15T09:00:00.000Z"})
    pa2 = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(v2["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T10:30:00.000Z",
                                          occupy_end_utc="2026-06-14T10:45:00.000Z"), OPS))

    cancelled = get_success_data(api.cancel_service_visit(v1["id"], OPS))
    assert cancelled["status"] == "CANCELLED"
    pa1_after = get_success_data(api.get_parking_assignment(pa1["id"], OPS))
    assert pa1_after["status"] == "RELEASED", "cancel must release the OCCUPIED assignment"

    occupied2 = get_success_data(api.occupy_parking_assignment(pa2["id"], occupy_payload(pa2["version"]), OPS))
    assert occupied2["status"] == "OCCUPIED", (
        "freed spot window should let the overlapping second assignment occupy"
    )


def test_adjust_billing_repricing_cascades_to_invoice_and_balance():
    """PRD §3.6: "The system re-runs the fuel-pricing engine using the ticket's
    `delivered_gallons` in place of the ordered figure and overwrites the order's
    `priced_amount_cents`; then, if the order's parent visit already has an `ISSUED`
    invoice, that invoice's `total_cents` is recomputed; then the owning operator's
    `open_invoice_balance_cents` is recomputed."

    A departed visit's flagged order (3,115,000 ordered-priced) over-delivered 6240 gal
    re-prices to 3,238,600; the cascade rewrites Invoice.total_cents and operator balance
    to 3,238,600.

    Design: Difficulty/transitive_cascade/adjust_billing_cascade_depth3
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": False},
        ticket_delivered=6240,
    )
    assert order["reconciliation_status"] == "IN_REVIEW"
    adjusted = get_success_data(api.adjust_billing_fuel_order(order["id"], BILLING))
    assert adjusted["priced_amount_cents"] == 3_238_600
    assert adjusted["reconciliation_status"] == "ADJUSTED"

    invoice_after = get_invoice_for_visit(visit["id"])
    assert invoice_after["total_cents"] == 3_238_600, (
        f"invoice total should follow the re-price to 3238600, got {invoice_after['total_cents']}"
    )
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["open_invoice_balance_cents"] == 3_238_600, (
        f"operator balance should follow the re-price to 3238600, got "
        f"{operator_after['open_invoice_balance_cents']}"
    )


def test_adjust_billing_conserves_invoice_total_equals_lines():
    """PRD §3.6: "This three-step cascade conserves the invariant that an invoice always
    equals the sum of its current billable lines."
    PRD §3.7: "every fuel order on the visit whose `logistics_status` is not `CANCELLED`
    contributes its `priced_amount_cents`"

    After adjusting the sole fuel line from 3,115,000 to 3,238,600, the invoice total
    equals exactly that single live billable line — no drift.

    Design: Difficulty/compensating_invariant/adjust_billing_conserves_invoice_total_equals_lines
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": False},
        ticket_delivered=6240,
    )
    get_success_data(api.adjust_billing_fuel_order(order["id"], BILLING))
    order_after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    invoice_after = get_invoice_for_visit(visit["id"])
    assert invoice_after["total_cents"] == 3_238_600
    assert invoice_after["total_cents"] == order_after["priced_amount_cents"], (
        "invoice total must equal the sum of its live billable lines (the single fuel line)"
    )


def test_void_drops_invoice_from_operator_open_balance():
    """PRD §3.7: "A `LineManager` may **void** an `ISSUED` invoice, moving it
    `ISSUED → VOID` and recomputing the operator's `open_invoice_balance_cents` so the
    voided invoice drops out of the balance."
    PRD §3.1: "its `open_invoice_balance_cents` is the sum, across that operator's
    invoices in `ISSUED` or `PAST_DUE` status, of each invoice's `total_cents` minus its
    `paid_cents`, recomputed on every invoice change."

    Voiding the sole ISSUED invoice (180,000 from a tankered order) drops it from the
    balance, leaving the operator's open balance at exactly 0.

    Design: Difficulty/compensating_invariant/void_conserves_operator_open_balance
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    assert operator["open_invoice_balance_cents"] == 180_000
    voided = get_success_data(api.void_invoice(invoice["id"], LINE))
    assert voided["status"] == "VOID"
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["open_invoice_balance_cents"] == 0, (
        f"voided invoice should drop the balance to 0, got "
        f"{operator_after['open_invoice_balance_cents']}"
    )
