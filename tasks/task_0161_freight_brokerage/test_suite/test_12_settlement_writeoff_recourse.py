"""Settlement, write-off, and recourse — PRD §3.10."""
from __future__ import annotations

import pytest

from test_helpers import (
    get_invoice,
    get_load,
    get_shipper,
    make_shipper_headers,
    resolve_dispute,
    setup_factored_invoice,
    setup_invoice_in_review_dispute,
    setup_invoiced_load,
    validate_error,
    validate_success,
    write_off_invoice,
)


# ===========================================================================
# §3.10 — Write-off.
# ===========================================================================
def test_write_off_drives_balance_to_zero_and_settles(api, broker_ops_headers):
    """PRD §3.10: "The write-off increases `amount_credited_cents` by the
    current `balance_due_cents`, driving the balance to zero, and decreases
    the shipper's `outstanding_invoiced_cents` by the original frozen
    `invoice_total_cents`."

    Claim: write-off -> settlement_status == WRITTEN_OFF, balance == 0,
    shipper.outstanding == 0.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=0, accessorials=None,
    )
    original_total = invoice["invoice_total_cents"]
    write_off_invoice(brokerage["id"], invoice["id"])
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["settlement_status"] == "WRITTEN_OFF"
    assert after["balance_due_cents"] == 0
    assert after["amount_credited_cents"] == original_total

    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == 0


def test_write_off_with_zero_balance_rejected(api, broker_ops_headers):
    """PRD §3.10: "The operation requires `balance_due_cents` to be
    strictly positive (a fully-paid invoice yields
    `ERR_INVOICE_NOTHING_TO_WRITE_OFF`)."

    Claim: an invoice that has already been written off has
    balance_due_cents == 0; a second write-off -> ERR_INVOICE_NOTHING_TO_WRITE_OFF.
    """
    brokerage, _s, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=0, accessorials=None,
    )
    write_off_invoice(brokerage["id"], invoice["id"])
    res = api.write_off_invoice(brokerage["id"], invoice["id"],
                                broker_ops_headers)
    validate_error(res, "ERR_INVOICE_NOTHING_TO_WRITE_OFF")


def test_write_off_with_open_dispute_rejected(api, broker_ops_headers):
    """PRD §3.10: "requires no `DisputeClaim` on the invoice to currently
    be `OPEN`, `IN_REVIEW`, or `COUNTER_OFFERED` (otherwise
    `ERR_INVOICE_HAS_OPEN_DISPUTE`)."

    Claim: write-off while a claim is IN_REVIEW -> ERR_INVOICE_HAS_OPEN_DISPUTE.
    """
    brokerage, _s, _c, _q, _l, invoice, _claim = (
        setup_invoice_in_review_dispute(claimed_cents=1_000)
    )
    res = api.write_off_invoice(brokerage["id"], invoice["id"],
                                broker_ops_headers)
    validate_error(res, "ERR_INVOICE_HAS_OPEN_DISPUTE")


# ===========================================================================
# §3.10 — FACTORED -> RECOURSED cascade.
# ===========================================================================
# NOTE: PRD §3.10 describes the FACTORED -> RECOURSED transition as
# triggered by "a dispute claim resolves on a FACTORED invoice with a
# non-zero settled credit". However, the PRD's §3.8 factoring gate
# forbids factoring when any DisputeClaim is in OPEN, IN_REVIEW, or
# COUNTER_OFFERED; and §3.9 explicitly forbids filing a NEW claim on a
# FACTORED invoice. Through PRD-documented endpoints alone, no sequence
# can land an actively-resolvable claim on a FACTORED invoice; per
# Silence Patterns (cross-entity-cascade), the RECOURSED transition is
# documented but its trigger state is unreachable from PRD prose, and
# is therefore omitted from this suite.


def test_factored_invoice_settlement_status_stays_issued(api):
    """PRD §3.8: "the parallel settlement dimension only auto-advances
    to `PAID` when `balance_due_cents` reaches zero and `factoring_status` is
    something other than `FACTORED`; while the invoice is `FACTORED` it
    remains `ISSUED` on the settlement axis."

    Claim: a freshly-factored invoice has settlement_status == ISSUED
    despite balance_due_cents == 0.
    """
    brokerage, _s, _c, _q, _l, invoice, _adv = setup_factored_invoice()
    assert invoice["balance_due_cents"] == 0
    assert invoice["factoring_status"] == "FACTORED"
    assert invoice["settlement_status"] == "ISSUED"
