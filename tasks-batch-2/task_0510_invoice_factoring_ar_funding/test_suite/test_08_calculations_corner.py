"""Calculation breadth: provisional fee floored at zero days, aging dpd==30
inclusive lower boundary.

Corner queue B: calculations.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_funded_invoice, advance_clock,
    TEST_USERS,
)

FO = TEST_USERS["funding_headers"]


def test_provisional_fee_zero_on_funding_day(api):
    """PRD §3.6: "It equals the face amount multiplied by `fee_rate_per_day`
    multiplied by the number of whole days elapsed since funding — that
    elapsed-day count being the floor of the difference between the current
    clock and `funded_at` divided by a 24-hour day (86,400 seconds), and never
    less than zero."

    On the funding day (clock == funded_at, 0 days elapsed) accrued_fee_cents
    == 0; status FUNDED; aging_bucket CURRENT.

    Design: Corner/calculations/calc_provisional_fee_zero_before_funding_day_elapses
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005,
                               invoice_overrides={"invoice_number": "INV-PF"})
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FO), 200)
    assert invoice["accrued_fee_cents"] == 0, (
        f"0 days elapsed -> floored 0, got {invoice['accrued_fee_cents']}")
    assert invoice["status"] == "FUNDED"
    assert invoice["aging_bucket"] == "CURRENT"


def test_aging_bucket_dpd_30_stays_dpd_1_30(api):
    """PRD §2.10: "`DPD_1_30` when days past due is at least 1 and at most 30 ...
    The upper edge of each band is inclusive: 30 days past due is `DPD_1_30`".

    due_date 2026-05-31, clock 2026-06-30 (dpd 30) -> aging_bucket DPD_1_30,
    status OUTSTANDING.

    Design: Corner/calculations/calc_aging_dpd30_boundary_stays_dpd_1_30
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               invoice_overrides={"invoice_number": "INV-AG30"})
    advance_clock("2026-06-30T00:00:00Z")  # dpd 30
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FO), 200)
    assert invoice["aging_bucket"] == "DPD_1_30", (
        f"dpd 30 inclusive -> DPD_1_30, got {invoice['aging_bucket']}")
    assert invoice["status"] == "OUTSTANDING"
