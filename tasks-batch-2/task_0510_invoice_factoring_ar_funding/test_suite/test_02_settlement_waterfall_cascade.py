"""Settlement waterfall (principal->fee->rebate) and the multi-hop cascades
that fire on settlement and on debtor insolvency.

Difficulty queue A: combinatorial_formula (waterfall), transitive_cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_funded_invoice, setup_funding_ready, post_collection, advance_clock,
    submit_and_verify_invoice, create_batch_payload, fund_batch_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def test_short_pay_advance_outstanding_zero_after_full_principal_repaid(api):
    """PRD §3.6: "This runs the partial settlement waterfall in the same pinned
    principal-then-fee-then-rebate order, sets `advance_outstanding_cents` to
    `advance_amount_cents` minus `principal_applied_cents`".

    85000 principal fully repaid by 90000 collected -> advance_outstanding 0.

    Design: Difficulty/combinatorial_formula/cf_settlement_waterfall_three_bucket_minmax
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-WF"})
    inv_id = ctx["invoice"]["id"]
    client_id = ctx["client"]["id"]
    advance_clock("2026-06-10T00:00:00Z")
    post_collection(inv_id, client_id, 50000, "2026-06-09T00:00:00Z")
    post_collection(inv_id, client_id, 40000, "2026-06-10T00:00:00Z")
    validate_success(api.close_collection(inv_id, CO), 200)
    invoice = validate_success(api.get_invoice(inv_id, FO), 200)
    assert invoice["advance_outstanding_cents"] == 0, (
        f"85000 - 85000 = 0, got {invoice['advance_outstanding_cents']}"
    )


def test_settlement_cascade_recomputes_client_reserve_to_zero(api):
    """PRD §3.6: "its `reserve_balance_cents` decreases by the invoice's
    `reserve_held_cents` and its `funded_advance_outstanding_cents` decreases by
    the `advance_amount_cents`".

    After full settlement, the single-invoice client returns reserve and
    outstanding-advance balances to 0.

    Design: Difficulty/transitive_cascade/tc_settlement_depth3_invoice_client_ledger
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-TC"})
    inv_id = ctx["invoice"]["id"]
    client_id = ctx["client"]["id"]
    before = validate_success(api.get_client(client_id, FO), 200)
    assert before["reserve_balance_cents"] == 15000
    post_collection(inv_id, client_id, 100000, "2026-06-15T00:00:00Z")
    after = validate_success(api.get_client(client_id, FO), 200)
    assert after["reserve_balance_cents"] == 0, (
        f"reserve released to 0, got {after['reserve_balance_cents']}"
    )
    assert after["funded_advance_outstanding_cents"] == 0, (
        f"outstanding advance released to 0, "
        f"got {after['funded_advance_outstanding_cents']}"
    )


def test_settlement_cascade_appends_rebate_and_reserve_release_ledger(api):
    """PRD §3.6: "Finally the system appends three ledger entries —
    `FEE_ACCRUED`, `REBATE_PAID`, and `RESERVE_RELEASED` — each carrying its
    `reserve_balance_after_cents` snapshot."

    The settlement cascade reaches the append-only ledger with REBATE_PAID and
    RESERVE_RELEASED entries; RESERVE_RELEASED snapshots reserve 0.

    Design: Difficulty/transitive_cascade/tc_settlement_depth3_invoice_client_ledger
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-TC"})
    inv_id = ctx["invoice"]["id"]
    client_id = ctx["client"]["id"]
    post_collection(inv_id, client_id, 100000, "2026-06-15T00:00:00Z")
    data, _ = validate_paginated(
        api.list_ledger_entries(FO, params={"invoice_id": inv_id}))
    types = [e["entry_type"] for e in data]
    assert "REBATE_PAID" in types, f"expected REBATE_PAID ledger entry, got {types}"
    assert "RESERVE_RELEASED" in types, (
        f"expected RESERVE_RELEASED ledger entry, got {types}")
    release = [e for e in data if e["entry_type"] == "RESERVE_RELEASED"][-1]
    assert release["reserve_balance_after_cents"] == 0, (
        f"RESERVE_RELEASED snapshot reserve 0, "
        f"got {release['reserve_balance_after_cents']}"
    )


def test_insolvency_cascade_suspends_noticed_relationships(api):
    """PRD §3.2: "every `ClientDebtorRelationship` on this debtor whose
    `notice_status` is `NOTICED` has its notice posture driven to `SUSPENDED`."

    Declaring a debtor insolvent flips every NOTICED relationship on it to
    SUSPENDED (hop2 caused by the debtor change, not the operator directly).

    Design: Difficulty/transitive_cascade/tc_insolvency_depth2_debtor_relationship
    """
    program = get_success_data(api.create_program(
        {"name": "F-INS"}, ADMIN))
    # Two clients, one shared debtor, two NOTICED relationships.
    from test_helpers import (create_approved_client, create_approved_debtor,
                              create_relationship)
    client_a = create_approved_client(program["id"])
    client_b = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"],
                                    debtor_overrides={"credit_rating": "BB"})
    rel_a = create_relationship(client_a["id"], debtor["id"], noticed=True,
                                recourse_type="NON_RECOURSE")
    rel_b = create_relationship(client_b["id"], debtor["id"], noticed=True,
                                recourse_type="NON_RECOURSE")

    declared = validate_success(api.declare_insolvent(debtor["id"], UW), 200)
    assert declared["status"] == "INSOLVENT"

    rel_a_after = validate_success(api.get_relationship(rel_a["id"], FO), 200)
    rel_b_after = validate_success(api.get_relationship(rel_b["id"], FO), 200)
    assert rel_a_after["notice_status"] == "SUSPENDED", (
        f"rel_a cascaded to SUSPENDED, got {rel_a_after['notice_status']}")
    assert rel_b_after["notice_status"] == "SUSPENDED", (
        f"rel_b cascaded to SUSPENDED, got {rel_b_after['notice_status']}")


def test_insolvency_sets_debtor_insolvent(api):
    """PRD §3.2: "An approved debtor may be declared insolvent by underwriting,
    moving `APPROVED → INSOLVENT`."

    Hop1 of the cascade: the debtor itself moves to INSOLVENT.

    Design: Difficulty/transitive_cascade/tc_insolvency_depth2_debtor_relationship
    """
    program = get_success_data(api.create_program({"name": "F-INS2"}, ADMIN))
    from test_helpers import create_approved_debtor
    debtor = create_approved_debtor(program["id"],
                                    debtor_overrides={"credit_rating": "BB"})
    declared = validate_success(api.declare_insolvent(debtor["id"], UW), 200)
    assert declared["status"] == "INSOLVENT"
