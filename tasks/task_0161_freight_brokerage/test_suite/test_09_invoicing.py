"""Invoice issuance from a DELIVERED load — PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    approve_accessorial,
    assert_invoice,
    create_accessorial,
    DEFAULT_DETENTION_FREE_MINUTES,
    DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    deny_accessorial,
    detention_cents,
    get_invoice,
    get_load,
    get_shipper,
    invoice_load,
    iso_utc,
    make_carrier_headers,
    parse_iso,
    setup_brokerage_with_shipper,
    setup_delivered_load,
    setup_invoiced_load,
    spot_linehaul_cents,
    validate_error,
    validate_success,
)


def test_invoice_creates_frozen_invoice_row(api, broker_ops_headers):
    """PRD §3.7: "The new `Invoice` row is created with `linehaul_cents`
    frozen from the load's `linehaul_cents`, `detention_cents` frozen from
    `final_detention_cents`, and `accessorial_cents` frozen from
    `accessorial_total_cents`. The invoice's `invoice_total_cents` is the
    sum of those three frozen components."

    Claim: invoice fields match the load's components and the total is
    their sum; settlement_status starts at ISSUED, factoring_status at
    NOT_FACTORED.
    """
    brokerage, shipper, carrier, _q, load, invoice = setup_invoiced_load(
        origin_zip="10000", destination_zip="10500",  # DRY_VAN linehaul = 30000+500*10 = 35000
        equipment_type="DRY_VAN",
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 30,  # 30 chargeable -> 3000
        accessorials=[("LUMPER", 5_000, True)],
    )
    assert_invoice(invoice)

    expected_linehaul = spot_linehaul_cents("DRY_VAN", "10000", "10500")
    expected_detention = detention_cents(
        DEFAULT_DETENTION_FREE_MINUTES + 30,
        DEFAULT_DETENTION_FREE_MINUTES,
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    )
    expected_accessorials = 5_000
    expected_total = (
        expected_linehaul + expected_detention + expected_accessorials
    )
    assert invoice["linehaul_cents"] == expected_linehaul
    assert invoice["detention_cents"] == expected_detention
    assert invoice["accessorial_cents"] == expected_accessorials
    assert invoice["invoice_total_cents"] == expected_total
    assert invoice["amount_paid_cents"] == 0
    assert invoice["amount_credited_cents"] == 0
    assert invoice["balance_due_cents"] == expected_total
    assert invoice["settlement_status"] == "ISSUED"
    assert invoice["factoring_status"] == "NOT_FACTORED"


def test_invoice_increases_shipper_outstanding(api, broker_ops_headers):
    """PRD §3.7: "At the same time, the owning shipper's
    `outstanding_invoiced_cents` is increased by the new invoice's full
    `invoice_total_cents`."

    Claim: after /invoice, shipper.outstanding_invoiced_cents equals
    the invoice_total_cents.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="01000",
        equipment_type="DRY_VAN", detention_minutes=0, accessorials=None,
    )
    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == (
        invoice["invoice_total_cents"]
    )


def test_invoice_only_approved_accessorials_count(api, broker_ops_headers):
    """PRD §3.7: "The `accessorial_total_cents` accumulated on the load
    is the sum of `amount_cents` over all `APPROVED` charges (denied charges
    contribute nothing)."

    Claim: one APPROVED 4_000 + one DENIED 7_000 -> invoice
    accessorial_cents == 4_000.
    """
    brokerage, shipper, carrier, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",  # spot DRY_VAN 30_000+100*10 = 31_000
        detention_minutes=0,
        accessorials=[
            ("LUMPER", 4_000, True),
            ("LAYOVER", 7_000, False),
        ],
    )
    assert invoice["accessorial_cents"] == 4_000


def test_invoice_with_pending_accessorial_rejected(api, broker_ops_headers):
    """PRD §3.7: "every `AccessorialCharge` row on the load must be
    either `APPROVED` or `DENIED` — none may remain in `REQUESTED`. A pending
    charge yields `ERR_ACCESSORIAL_PENDING`."

    Claim: leaving one charge in REQUESTED at /invoice time ->
    ERR_ACCESSORIAL_PENDING.
    """
    from test_helpers import setup_in_transit_load, deliver_load
    brokerage, shipper, carrier, _q, load = setup_in_transit_load()
    create_accessorial(brokerage["id"], shipper["id"], load["id"],
                       carrier["id"], charge_type="LUMPER",
                       amount_cents=5_000)
    # Deliver without approving/denying the accessorial.
    from test_helpers import get_brokerage
    brokerage = get_brokerage(brokerage["id"])
    arrive = parse_iso(brokerage["clock_now_iso"])
    deliver_load(brokerage["id"], shipper["id"], load["id"], carrier["id"],
                 actual_arrive_at=iso_utc(arrive),
                 actual_depart_at=iso_utc(arrive))
    res = api.invoice_load(brokerage["id"], shipper["id"], load["id"],
                           broker_ops_headers)
    validate_error(res, "ERR_ACCESSORIAL_PENDING")


def test_invoice_on_non_delivered_load_rejected(api, broker_ops_headers):
    """PRD §3.6: invoice transitions Load DELIVERED -> INVOICED; any
    other state -> ERR_LOAD_NOT_DELIVERED.

    PRD §5: ERR_LOAD_NOT_DELIVERED is enumerated.

    Claim: /invoice on a DELIVERED load -> INVOICED; /invoice on an
    IN_TRANSIT load -> ERR_LOAD_NOT_DELIVERED.
    """
    from test_helpers import setup_in_transit_load
    brokerage, shipper, _c, _q, load = setup_in_transit_load()
    res = api.invoice_load(brokerage["id"], shipper["id"], load["id"],
                           broker_ops_headers)
    validate_error(res, "ERR_LOAD_NOT_DELIVERED")
