"""Compensating invariants: cash invariant under create/refund; estimate
invariant under PO create/cancel."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, create_vendor, create_purchase_order,
    make_agency_ops_headers, make_agency_finance_headers,
    assert_da_funding_invariants,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / advance_create_refund_cash_invariant
# ---------------------------------------------------------------------------

def _setup_sent_da_102500():
    """DA SENT_TO_PRINCIPAL with two SUNDRY lines 60000 + 40000 (total 102500,
    advance_required 82000)."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 60000, description="a")
    add_manual_line(da["id"], 40000, description="b")
    da = get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    return pc, da


def test_advance_create_then_refund_restores_cash_baseline(api):
    """PRD §3.8: "`advances_received_cents` as the sum of `amount_cents` over
    advances in `RECEIVED` or `APPLIED` ... and `funding_available_cents` as
    received minus applied minus refunded"; "the refund always returns the
    full unapplied remainder — `refunded_cents` becomes the `amount_cents`
    minus `applied_cents` — the advance becomes `REFUNDED`."

    Design: Difficulty/compensating_invariant/advance_create_refund_cash_invariant
    """
    pc, da = _setup_sent_da_102500()
    assert da["funding_available_cents"] == 0
    adv = get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 50000}, make_agency_finance_headers()))
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_finance_headers()))
    assert da["advances_received_cents"] == 50000
    assert da["funding_available_cents"] == 50000
    adv = validate_success(api_client.refund_funding_advance(adv["id"], make_agency_finance_headers()))
    assert adv["status"] == "REFUNDED"
    assert adv["refunded_cents"] == 50000
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_finance_headers()))
    assert da["advances_received_cents"] == 50000
    assert da["advances_refunded_cents"] == 50000
    assert da["advances_applied_cents"] == 0
    assert da["funding_available_cents"] == 0, "baseline restored by the compensate pair"
    assert_da_funding_invariants(da)


def test_advance_refund_below_requirement_never_funded(api):
    """PRD §3.8: "whenever net funding — received minus refunded — reaches
    `advance_required_cents` after an advance creation or a refund, an account
    in `SENT_TO_PRINCIPAL` moves to `FUNDED` on its own" (so an account that
    never reaches the requirement stays `SENT_TO_PRINCIPAL`).

    Design: Difficulty/compensating_invariant/advance_create_refund_cash_invariant
    """
    pc, da = _setup_sent_da_102500()
    adv = get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 50000}, make_agency_finance_headers()))
    validate_success(api_client.refund_funding_advance(adv["id"], make_agency_finance_headers()))
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_finance_headers()))
    assert da["status"] == "SENT_TO_PRINCIPAL", (
        "50000 < 82000: FUNDED never fired, so nothing to revert")


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / po_create_cancel_estimate_invariant
# ---------------------------------------------------------------------------

def test_po_create_then_cancel_restores_estimate_baseline(api):
    """PRD §3.4: "Whenever the call has a disbursement account in `PRO_FORMA`,
    `SENT_TO_PRINCIPAL`, or `FUNDED`, creation also appends a mirror line to
    the account carrying the order's estimate"; "either way the mirror line is
    reversed (its estimate driven to zero) and the account totals are
    recomputed while editable."

    Design: Difficulty/compensating_invariant/po_create_cancel_estimate_invariant
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 5000, description="base")
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da["total_estimated_cents"] == 5125, "5000 + fee 125"
    assert da["advance_required_cents"] == 4100
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="sales@chandler.example")
    po = create_purchase_order(pc["id"], vendor["id"], estimated_cents=20000)
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da["total_estimated_cents"] == 25625, "lines 5000 + 20000, fee 125 + 500"
    assert da["advance_required_cents"] == 20500
    validate_success(api_client.cancel_purchase_order(po["id"], make_agency_ops_headers()))
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da["total_estimated_cents"] == 5125, "exact baseline restored, zero drift"
    assert da["advance_required_cents"] == 4100


def test_po_cancel_reverses_mirror_line_but_retains_row(api):
    """PRD §3.3: "each service-order and purchase-order cancellation reverses
    its mirrored account line, driving the line's `estimated_cents` to zero
    while the line stays `ESTIMATED` and retains its `source_ref`."

    Design: Difficulty/compensating_invariant/po_create_cancel_estimate_invariant
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 5000, description="base")
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="sales@chandler.example")
    po = create_purchase_order(pc["id"], vendor["id"], estimated_cents=20000)
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    mirror = [l for l in lines if l.get("source_ref") == f"PurchaseOrder:{po['id']}"][0]
    po = validate_success(api_client.cancel_purchase_order(po["id"], make_agency_ops_headers()))
    assert po["status"] == "CANCELLED"
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    mirror_now = [l for l in lines if l["id"] == mirror["id"]][0]
    assert mirror_now["estimated_cents"] == 0
    assert mirror_now["status"] == "ESTIMATED"
    assert mirror_now.get("source_ref") == f"PurchaseOrder:{po['id']}", "row retained for audit"
