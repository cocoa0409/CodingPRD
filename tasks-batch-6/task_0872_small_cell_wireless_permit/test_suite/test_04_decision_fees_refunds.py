"""Batch decision outcomes, final-fee recomputation, refund cascades, the
four-eyes/pending precedence, and payment validation + OCC.

Difficulty: dual_variant_calc, transitive_cascade,
priority_pair_validation_conflict, compensating_invariant.
Corner: validations, cross_cutting_complexity_layers.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    payment_payload, design_review_payload,
    register_applicant, create_structure, create_segment, set_clock,
    open_application, add_node, submit, record_completeness,
    record_design_review, decide, pay_full, fetch_invoice, fetch_node,
    setup_submitted_single, setup_denied_single_collocation,
    make_applicant_headers, build_user_headers, TEST_USERS,
)

ROW = TEST_USERS["row_reviewer_headers"]
APPROVER = TEST_USERS["approver_headers"]


# ─── Difficulty: application_fee_provisional_vs_final ──────────────────────
def _partial_grant_scenario():
    """2 COLLOCATION (design PASS) + 1 NEW_POLE (design FAIL) → PARTIALLY_GRANTED."""
    applicant = register_applicant()
    ss_col = create_structure(max_collocations=2)
    ss_np = create_structure(max_collocations=1, structure_type="NEW_POLE")
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    n1 = add_node(app["id"], applicant["id"], ss_col["id"], seg["id"], facility_type="COLLOCATION")
    n2 = add_node(app["id"], applicant["id"], ss_col["id"], seg["id"], facility_type="COLLOCATION")
    n3 = add_node(app["id"], applicant["id"], ss_np["id"], seg["id"],
                  facility_type="NEW_POLE", proposed_construction_date="2029-06-15T00:00:00Z")
    submit(app["id"], applicant["id"])
    provisional = fetch_invoice(app["id"], applicant["id"])
    record_completeness(app["id"], complete=True)
    record_design_review(n1["id"], ss_col["id"], outcome="PASS")
    record_design_review(n2["id"], ss_col["id"], outcome="PASS")
    record_design_review(n3["id"], ss_np["id"], outcome="FAIL")
    decided = decide(app["id"])
    final_invoice = fetch_invoice(app["id"], applicant["id"])
    return provisional, decided, final_invoice


def test_partial_grant_final_fee_counts_only_permitted_nodes(api):
    """PRD §3.7: "The provisional variant counts every filed node; the final variant
    counts only nodes ending in `PERMITTED`, so denied or withdrawn nodes drop out
    and can lower the total."

    Design: Difficulty/dual_variant_calc/application_fee_provisional_vs_final
    """
    _, decided, final_invoice = _partial_grant_scenario()
    assert decided["status"] == "PARTIALLY_GRANTED"
    assert final_invoice["fee_variant"] == "FINAL"
    assert final_invoice["assessed_amount_cents"] == 102908


def test_provisional_fee_differs_from_final_after_rejection(api):
    """PRD §3.7: "At submission the invoice is raised with `fee_variant` of
    `PROVISIONAL`, `status` of `OPEN`, and `assessed_amount_cents` computed over all
    filed nodes; at decision it is recomputed to `FINAL` over the surviving permitted nodes."

    Design: Difficulty/dual_variant_calc/application_fee_provisional_vs_final
    """
    provisional, _, final_invoice = _partial_grant_scenario()
    assert provisional["fee_variant"] == "PROVISIONAL"
    assert provisional["assessed_amount_cents"] == 205817
    assert final_invoice["assessed_amount_cents"] == 102908
    assert provisional["assessed_amount_cents"] != final_invoice["assessed_amount_cents"]


# ─── Difficulty: deny_decision_cascades_nodes_invoice_refund ──────────────
def test_deny_decision_cascades_to_node_and_zero_invoice(api):
    """PRD §3.5: "If every node is `REJECTED`, it moves to `DENIED`." "on a denial
    the assessed amount is zero, so any net amount collected is refunded in full and
    the invoice moves to `REFUNDED`."

    Design: Difficulty/transitive_cascade/deny_decision_cascades_nodes_invoice_refund
    """
    ctx = setup_denied_single_collocation(pay=True)
    assert fetch_node(ctx["node"]["id"])["status"] == "DENIED"
    invoice = ctx["invoice"]
    assert invoice["fee_variant"] == "FINAL"
    assert invoice["assessed_amount_cents"] == 0
    assert invoice["outstanding_amount_cents"] == 0


def test_deny_decision_creates_full_refund_payment(api):
    """PRD §3.5: "on a denial the assessed amount is zero, so any net amount collected
    is refunded in full and the invoice moves to `REFUNDED`."

    Design: Difficulty/transitive_cascade/deny_decision_cascades_nodes_invoice_refund
    """
    ctx = setup_denied_single_collocation(pay=True)
    invoice = ctx["invoice"]
    payments, _ = validate_paginated(
        api.list_payments(invoice["id"], make_applicant_headers(ctx["applicant"]["id"]))
    )
    refunds = [p for p in payments if p["payment_type"] == "REFUND"]
    assert any(p["amount_cents"] == 51454 for p in refunds)
    assert invoice["status"] == "REFUNDED"


# ─── Difficulty: decision_sod_beats_nodes_pending ─────────────────────────
def _sod_and_pending_scenario():
    """node1 reviewed by rowrev-1 (APPROVED); node2 unreviewed (IN_REVIEW);
    the acting Approver's X-User-ID equals the reviewer's."""
    applicant = register_applicant()
    ss = create_structure(max_collocations=2)
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    n1 = add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    record_completeness(app["id"], complete=True)
    record_design_review(n1["id"], ss["id"], outcome="PASS", reviewer_id="rowrev-1")
    return app


def test_decision_reports_sod_when_reviewer_and_node_pending_both_violated(api):
    """PRD §2.10: "On a batch decision, the four-eyes segregation check
    (`ERR_SEGREGATION_OF_DUTIES`) is evaluated before the check that no node is still
    under review (`ERR_NODES_PENDING_REVIEW`)."

    Design: Difficulty/priority_pair_validation_conflict/decision_sod_beats_nodes_pending
    """
    app = _sod_and_pending_scenario()
    approver_is_reviewer = build_user_headers("rowrev-1", "Approver")
    res = api.decide_application(app["id"], {}, approver_is_reviewer)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", 409)


def test_decision_sod_precedence_not_reported_as_nodes_pending(api):
    """PRD §3.5: "an approver who reviewed any node of the batch is blocked with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/decision_sod_beats_nodes_pending
    """
    app = _sod_and_pending_scenario()
    approver_is_reviewer = build_user_headers("rowrev-1", "Approver")
    res = api.decide_application(app["id"], {}, approver_is_reviewer)
    body = res.json()["data"]
    assert body["error_id"] == "ERR_SEGREGATION_OF_DUTIES"
    assert body["error_id"] != "ERR_NODES_PENDING_REVIEW"


# ─── Difficulty: fee_ledger_conservation_payment_refund ───────────────────
def _paid_then_withdrawn():
    ctx = setup_submitted_single()
    pay_full(ctx["app"]["id"], ctx["applicant"]["id"])
    api_headers = make_applicant_headers(ctx["applicant"]["id"])
    from test_helpers import api_client
    validate_success(api_client.withdraw_application(ctx["app"]["id"], api_headers), 200)
    ctx["invoice"] = fetch_invoice(ctx["app"]["id"], ctx["applicant"]["id"])
    return ctx


def test_withdraw_refunds_full_net_collected(api):
    """PRD §3.9: "if a fee invoice exists and its net collected amount (payments
    minus refunds) is positive, a refund for the full net is created and the invoice
    moves to `REFUNDED`."

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_payment_refund
    """
    ctx = _paid_then_withdrawn()
    invoice = ctx["invoice"]
    assert invoice["paid_amount_cents"] == 51454
    assert invoice["refunded_amount_cents"] == 51454
    assert invoice["outstanding_amount_cents"] == 51454
    payments, _ = validate_paginated(
        api.list_payments(invoice["id"], make_applicant_headers(ctx["applicant"]["id"]))
    )
    assert any(p["payment_type"] == "REFUND" and p["amount_cents"] == 51454 for p in payments)


def test_invoice_ledger_identity_holds_after_refund(api):
    """PRD §3.7: "a computed `outstanding_amount_cents` equal to `assessed_amount_cents`
    minus `paid_amount_cents` plus `refunded_amount_cents`."

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_payment_refund
    """
    ctx = _paid_then_withdrawn()
    invoice = ctx["invoice"]
    assert (
        invoice["outstanding_amount_cents"]
        == invoice["assessed_amount_cents"]
        - invoice["paid_amount_cents"]
        + invoice["refunded_amount_cents"]
    )
    assert invoice["assessed_amount_cents"] == 51454


# ─── Corner: payment_exceeds_outstanding_rejected ─────────────────────────
def test_payment_exceeds_outstanding_rejected(api):
    """PRD §3.7: "The amount must be a positive number of cents that does not exceed
    the current outstanding balance, otherwise `ERR_INVALID_PAYMENT_AMOUNT`;"

    Design: Corner/validations/payment_exceeds_outstanding_rejected
    """
    ctx = setup_submitted_single()
    invoice = fetch_invoice(ctx["app"]["id"], ctx["applicant"]["id"])
    res = api.create_payment(
        invoice["id"],
        payment_payload(99999999, invoice["version"]),
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(res, "ERR_INVALID_PAYMENT_AMOUNT", 422)


# ─── Corner: occ_stale_invoice_version_on_payment ─────────────────────────
def test_stale_invoice_version_on_payment_rejected(api):
    """PRD §3.7: "the version must match, otherwise `ERR_STALE_VERSION`." "Recording
    a payment advances the invoice's version."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_payment
    """
    ctx = setup_submitted_single()
    applicant_headers = make_applicant_headers(ctx["applicant"]["id"])
    invoice = fetch_invoice(ctx["app"]["id"], ctx["applicant"]["id"])
    ver_pre = invoice["version"]
    # First payment advances the invoice version.
    validate_success(
        api.create_payment(invoice["id"], payment_payload(10000, ver_pre), applicant_headers), 201
    )
    # Second payment still carries the pre-first version → stale.
    res = api.create_payment(invoice["id"], payment_payload(10000, ver_pre), applicant_headers)
    validate_error(res, "ERR_STALE_VERSION", 412)
