"""Transitive cascades: port-call cancel depth-3 chain; PO over-variance
invoice cascade flipping a FINAL account to DISPUTED."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, create_vendor, create_service_order, create_purchase_order,
    create_crew_change, create_notification, create_berth_window,
    drive_call_to_alongside, send_da_and_fund, sail_call,
    make_agency_ops_headers, make_agency_finance_headers,
    make_port_authority_headers, make_vendor_rep_headers, make_crewing_agent_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / port_call_cancel_depth3_cascade
# ---------------------------------------------------------------------------

def _setup_cancel_cascade_scenario():
    """NOMINATED call with DA (mirrored lines from a 20000 TUG order and a
    10000 PO), one REQUESTED berth window, one DRAFT notification, one
    REQUESTED crew change."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-10T10:00:00Z", etd="2026-06-12T10:00:00Z")
    da = create_da_for_call(pc)
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS", "STORES"],
                           contact_email="sales@chandler.example")
    so = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-7",
        window_start="2026-06-10T12:00:00Z", window_end="2026-06-10T13:00:00Z",
        estimated_cents=20000)
    po = create_purchase_order(pc["id"], vendor["id"], estimated_cents=10000,
                               needed_by="2026-06-10T09:00:00Z")
    bw = create_berth_window(pc["id"], berth_code="B3",
                             start_at="2026-06-10T08:00:00Z", end_at="2026-06-12T20:00:00Z")
    n = create_notification(pc["id"], "CUSTOMS", payload_summary="cus pkg")
    cc = create_crew_change(pc["id"], full_name="J. Cook", nationality="PH",
                            passport_no="P123", requires_visa=False)
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    by_ref = {l.get("source_ref"): l for l in lines}
    return {
        "pc": pc, "da": da, "vendor": vendor, "so": so, "po": po, "bw": bw,
        "n": n, "cc": cc,
        "so_line": by_ref[f"ServiceOrder:{so['id']}"],
        "po_line": by_ref[f"PurchaseOrder:{po['id']}"],
    }


def test_port_call_cancel_cascades_children(api):
    """PRD §3.3: "Link one: every berth window of the call in `REQUESTED` or
    `CONFIRMED` moves to `CANCELLED`; every authority notification in `DRAFT`,
    `SUBMITTED`, or `REJECTED` moves to `WITHDRAWN`; every crew change in
    `REQUESTED`, `DOCS_VERIFIED`, `VISA_PENDING`, `VISA_GRANTED`,
    `SHORE_PASS_ISSUED`, or `PASS_EXPIRED` moves to `CANCELLED`; every
    purchase order in `DRAFT`, `SENT`, or `ACKNOWLEDGED` moves to `CANCELLED`;
    and every service order in `ORDERED` or `CONFIRMED` moves to `CANCELLED`
    with `cancellation_fee_cents` of zero — a port-call cancellation never
    incurs late fees."

    Design: Difficulty/transitive_cascade/port_call_cancel_depth3_cascade
    """
    s = _setup_cancel_cascade_scenario()
    pc = validate_success(api_client.cancel_port_call(s["pc"]["id"], make_agency_ops_headers()))
    assert pc["ops_status"] == "CANCELLED"
    bw = validate_success(api_client.get_berth_window(s["bw"]["id"], make_agency_ops_headers()))
    assert bw["status"] == "CANCELLED"
    n = validate_success(api_client.get_authority_notification(s["n"]["id"], make_agency_ops_headers()))
    assert n["status"] == "WITHDRAWN"
    cc = validate_success(api_client.get_crew_change(s["cc"]["id"], make_crewing_agent_headers()))
    assert cc["status"] == "CANCELLED"
    so = validate_success(api_client.get_service_order(s["so"]["id"], make_agency_ops_headers()))
    assert so["status"] == "CANCELLED"
    assert so["cancellation_fee_cents"] == 0, "cascade cancellation never charges late fees"
    po = validate_success(api_client.get_purchase_order(s["po"]["id"], make_agency_ops_headers()))
    assert po["status"] == "CANCELLED"


def test_port_call_cancel_reverses_lines_and_recomputes_totals(api):
    """PRD §3.3: "Link two: each service-order and purchase-order cancellation
    reverses its mirrored account line, driving the line's `estimated_cents`
    to zero while the line stays `ESTIMATED` and retains its `source_ref`.
    Link three: the account's totals are recomputed after all line reversals;
    an account in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED` remains open."

    Design: Difficulty/transitive_cascade/port_call_cancel_depth3_cascade
    """
    s = _setup_cancel_cascade_scenario()
    validate_success(api_client.cancel_port_call(s["pc"]["id"], make_agency_ops_headers()))
    lines, _ = validate_paginated(api_client.list_da_lines(s["da"]["id"], make_agency_ops_headers()))
    by_id = {l["id"]: l for l in lines}
    so_line = by_id[s["so_line"]["id"]]
    po_line = by_id[s["po_line"]["id"]]
    assert so_line["estimated_cents"] == 0 and so_line["status"] == "ESTIMATED"
    assert po_line["estimated_cents"] == 0 and po_line["status"] == "ESTIMATED"
    assert so_line.get("source_ref") == f"ServiceOrder:{s['so']['id']}"
    da = validate_success(api_client.get_disbursement_account(s["da"]["id"], make_agency_ops_headers()))
    assert da["total_estimated_cents"] == 0, "totals recomputed after all reversals"
    assert da["advance_required_cents"] == 0
    assert da["status"] == "PRO_FORMA", "account remains open"


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / po_invoice_over_variance_cascade_to_da
# ---------------------------------------------------------------------------

def _setup_final_da_with_delivered_po():
    """Call fully sailed; DA FINAL (one PO mirror line estimated at 10000);
    8200 advance fully applied; PO DELIVERED awaiting invoice."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"],
                           contact_email="sales@chandler.example")
    vh = make_vendor_rep_headers(vendor["id"])
    po = create_purchase_order(pc["id"], vendor["id"], estimated_cents=10000,
                               needed_by="2026-06-10T09:00:00Z")
    pc, bw = drive_call_to_alongside(pc, berth_code="B2")
    get_success_data(api_client.send_purchase_order(po["id"], make_agency_ops_headers()))
    get_success_data(api_client.acknowledge_purchase_order(po["id"], vh))
    get_success_data(api_client.deliver_purchase_order(po["id"], vh))
    da, adv = send_da_and_fund(da["id"], 8200)
    pc = sail_call(pc, bw)
    da = validate_success(api_client.finalize_disbursement_account(
        da["id"], make_agency_finance_headers("fin-1")))
    assert da["status"] == "FINAL"
    get_success_data(api_client.apply_funding_advance(
        adv["id"], {"amount_cents": 8200}, make_agency_finance_headers()))
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    po_line = [l for l in lines if l.get("source_ref") == f"PurchaseOrder:{po['id']}"][0]
    return {"pc": pc, "bw": bw, "da": da, "adv": adv, "po": po, "po_line": po_line,
            "vendor": vendor, "vh": vh}


def test_po_over_variance_invoice_flips_final_da_to_disputed(api):
    """PRD §3.4: "An absolute variance strictly greater than 10.0 percent
    routes the order to `DISPUTED` instead, and that branch cascades through
    three links: the order itself becomes `DISPUTED`; the mirror line moves to
    `DISPUTED` with the invoiced actual still recorded on it; and the account
    totals are recomputed, with an account in `FINAL` flipping to `DISPUTED`."

    Design: Difficulty/transitive_cascade/po_invoice_over_variance_cascade_to_da
    """
    s = _setup_final_da_with_delivered_po()
    po = validate_success(api_client.invoice_purchase_order(
        s["po"]["id"], {"invoiced_cents": 12000}, s["vh"]))
    assert po["status"] == "DISPUTED"
    assert po["variance_pct"] == 20.0
    line = validate_success(api_client.get_disbursement_account(s["da"]["id"], make_agency_ops_headers()))
    lines, _ = validate_paginated(api_client.list_da_lines(s["da"]["id"], make_agency_ops_headers()))
    po_line = [l for l in lines if l["id"] == s["po_line"]["id"]][0]
    assert po_line["status"] == "DISPUTED"
    assert po_line["actual_cents"] == 12000
    da = validate_success(api_client.get_disbursement_account(s["da"]["id"], make_agency_ops_headers()))
    assert da["status"] == "DISPUTED", "FINAL account flips to DISPUTED on the fork"


def test_po_over_variance_invoice_recomputes_final_totals(api):
    """PRD §3.9: "`total_final_cents` as the sum of every line's
    `actual_cents` plus `agency_fee_final_cents` ... and `balance_due_cents`
    as `total_final_cents` minus `advances_applied_cents`."

    Design: Difficulty/transitive_cascade/po_invoice_over_variance_cascade_to_da
    """
    s = _setup_final_da_with_delivered_po()
    validate_success(api_client.invoice_purchase_order(
        s["po"]["id"], {"invoiced_cents": 12000}, s["vh"]))
    da = validate_success(api_client.get_disbursement_account(s["da"]["id"], make_agency_ops_headers()))
    # line actual 12000; per-line fee round_half_up(300) = 300; total 12300
    assert da["total_final_cents"] == 12300, f"12000 + fee 300; got {da['total_final_cents']}"
    assert da["balance_due_cents"] == 4100, f"12300 - 8200 applied; got {da['balance_due_cents']}"
