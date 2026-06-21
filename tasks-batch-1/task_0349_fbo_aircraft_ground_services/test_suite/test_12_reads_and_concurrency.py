"""List reads (reverse-reachability), optimistic-concurrency stale-version rejection,
derived-balance reconciliation, and immediate-consistency of the depart invoice
(PRD §2.3, §2.7, §3.1, §3.6, §3.7).

Corner queue (B) instances:
  - endpoints / list_fuel_orders_by_visit_reverse_reachability
  - endpoints / list_into_plane_tickets_by_order_reverse_reachability
  - cross_cutting_complexity_layers / occ_invoice_pay_stale_version_rejected
  - cross_cutting_complexity_layers / derived_balance_reconciled_after_payment
  - consistency_model / depart_response_reflects_invoice_immediately
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    validate_paginated,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_departed_visit_with_invoice,
    create_requested_fuel_order,
    create_fueled_fuel_order,
    post_into_plane_ticket,
    get_invoice_for_visit,
    pay_invoice_payload,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_list_fuel_orders_by_visit():
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    GET /fuel-orders?service_visit_id=X returns the visit's single REQUESTED order as a
    paginated array with total_count 1.

    Design: Corner/endpoints/list_fuel_orders_by_visit_reverse_reachability
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        {"operator_id": operator["id"], "aircraft_id": aircraft["id"],
         "arrival_utc": "2026-06-14T08:00:00.000Z", "departure_utc": "2026-06-15T08:00:00.000Z"}, OPS))
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=False)
    data, meta = validate_paginated(api.list_fuel_orders(FUEL, params={"service_visit_id": visit["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == order["id"]


def test_list_into_plane_tickets_by_fuel_order():
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    GET /into-plane-tickets?fuel_order_id=X surfaces the cascade-created ticket as a
    length-1 array with total_count 1.

    Design: Corner/endpoints/list_into_plane_tickets_by_order_reverse_reachability
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    ticket = post_into_plane_ticket(order["id"], 6000)
    data, meta = validate_paginated(
        api.list_into_plane_tickets(FUEL, params={"fuel_order_id": order["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == ticket["id"]


def test_invoice_pay_stale_version_rejected():
    """PRD §2.7: "Applying a payment to an invoice must carry `expected_invoice_version`,
    and it must equal the target invoice's current `version`. If another writer has
    advanced the invoice's version since the client last read it — a prior payment that
    already moved `paid_cents`, or an adjust-billing re-price that recomputed
    `total_cents` — the supplied value no longer matches and the payment is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"

    After a first partial payment of 100,000 bumps the invoice version, a second payment
    carrying the pre-first-payment version → ERR_STALE_VERSION (412); paid_cents stays at
    100,000.

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_pay_stale_version_rejected
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    stale_version = invoice["version"]
    # First partial payment advances the invoice version.
    get_success_data(api.pay_invoice(invoice["id"], pay_invoice_payload(100_000, stale_version), BILLING))
    # Second payment carrying the now-stale version is rejected.
    res = api.pay_invoice(invoice["id"], pay_invoice_payload(80_000, stale_version), BILLING)
    validate_error(res, "ERR_STALE_VERSION")
    after = get_success_data(api.get_invoice(invoice["id"], BILLING))
    assert after["paid_cents"] == 100_000


def test_operator_open_balance_reconciles_to_zero_after_full_payment():
    """PRD §3.7: "A valid payment adds `payment_cents` to `paid_cents` and recomputes the
    operator's `open_invoice_balance_cents`. When the running `paid_cents` reaches
    `total_cents`, the invoice moves to `PAID`"
    PRD §3.1: "its `open_invoice_balance_cents` is the sum, across that operator's
    invoices in `ISSUED` or `PAST_DUE` status, of each invoice's `total_cents` minus its
    `paid_cents`, recomputed on every invoice change."

    Fully paying an ISSUED invoice (total 180,000) moves it to PAID and reconciles the
    operator's open balance from 180,000 to 0.

    Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciled_after_payment
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    assert operator["open_invoice_balance_cents"] == 180_000
    paid = get_success_data(api.pay_invoice(
        invoice["id"], pay_invoice_payload(180_000, invoice["version"]), BILLING))
    assert paid["status"] == "PAID"
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["open_invoice_balance_cents"] == 0


def test_depart_invoice_total_available_immediately():
    """PRD §3.7: "On a clean departure the visit moves `READY_FOR_DEPARTURE → DEPARTED`,
    the system creates exactly one **Invoice** for the visit in `ISSUED` status, computes
    that invoice's `total_cents`, recomputes the operator's `open_invoice_balance_cents`"

    Immediately after depart, GET /invoices?service_visit_id=X returns the ISSUED invoice
    with total_cents already computed (180,000 from a single tankered order) — no lag.

    Design: Corner/consistency_model/depart_response_reflects_invoice_immediately
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    fetched = get_invoice_for_visit(visit["id"])
    assert fetched["status"] == "ISSUED"
    assert fetched["total_cents"] == 180_000
