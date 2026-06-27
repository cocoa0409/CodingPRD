"""Branching state machine (invoice fork to SETTLED vs SHORT_PAID->BOUGHT_BACK),
the relationship notice cycle, and compensating-invariant conservation.

Difficulty queue A: non_linear_state_machine, compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_funded_invoice, setup_short_paid_invoice, create_relationship,
    create_approved_client, create_approved_debtor,
    post_collection, advance_clock, buyback_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def test_invoice_short_pay_branch_terminates_bought_back_not_settled(api):
    """PRD §3.7: "On a permitted buyback the invoice moves to `BOUGHT_BACK`."
    PRD §3.6: "a collections officer may close out collection, moving
    `OUTSTANDING → SHORT_PAID`."

    The SHORT_PAID branch reaches the BOUGHT_BACK terminal, not SETTLED.

    Design: Difficulty/non_linear_state_machine/nlsm_invoice_branch_settled_vs_shortpaid_buyback
    """
    ctx = setup_short_paid_invoice(partial_amount_cents=80000,
                                   received_at="2026-06-10T00:00:00Z",
                                   clock_to="2026-06-10T00:00:00Z",
                                   face_amount_cents=100000, advance_rate_pct=0.85,
                                   fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                                   tier3_multiplier=2.0,
                                   invoice_overrides={"invoice_number": "INV-BR"})
    inv_id = ctx["invoice"]["id"]
    assert ctx["invoice"]["status"] == "SHORT_PAID"
    bought = validate_success(
        api.buyback_invoice(inv_id, buyback_payload("CLIENT_REQUEST"), CO), 200)
    assert bought["status"] == "BOUGHT_BACK", (
        f"SHORT_PAID branch terminal is BOUGHT_BACK, got {bought['status']}")


def test_buyback_amount_advance_outstanding_plus_uncovered_fee(api):
    """PRD §3.7: "The `buyback_amount_cents` the client must remit to make the
    factor whole is the invoice's `advance_outstanding_cents` plus that
    uncovered fee".

    advance_outstanding 5000 + uncovered FINAL fee 2250 (40 days, fee_already
    covered 0) = 7250.

    Design: Difficulty/non_linear_state_machine/nlsm_invoice_branch_settled_vs_shortpaid_buyback
    """
    ctx = setup_short_paid_invoice(partial_amount_cents=80000,
                                   received_at="2026-06-10T00:00:00Z",
                                   clock_to="2026-06-10T00:00:00Z",
                                   face_amount_cents=100000, advance_rate_pct=0.85,
                                   fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                                   tier3_multiplier=2.0,
                                   invoice_overrides={"invoice_number": "INV-BR"})
    inv_id = ctx["invoice"]["id"]
    validate_success(api.buyback_invoice(inv_id, buyback_payload("CLIENT_REQUEST"), CO), 200)
    data, _ = validate_paginated(api.list_buybacks(FO, params={"invoice_id": inv_id}))
    assert len(data) == 1, f"expected exactly one Buyback, got {len(data)}"
    assert data[0]["buyback_amount_cents"] == 7250, (
        f"5000 + 2250 = 7250, got {data[0]['buyback_amount_cents']}")
    # Branch side-effects are disjoint: no Settlement on the buyback branch.
    settlements, _ = validate_paginated(
        api.list_settlements(FO, params={"invoice_id": inv_id}))
    assert len(settlements) == 0, (
        f"buyback branch produces no Settlement, got {len(settlements)}")


def test_relationship_notice_suspend_resume_revisits_noticed(api):
    """PRD §3.3: "The relationship's notice posture thus cycles `NOTICED →
    SUSPENDED → NOTICED`; each of these transitions increments `version`."

    The same relationship row revisits NOTICED after suspend then resume.

    Design: Difficulty/non_linear_state_machine/nlsm_relationship_notice_suspend_resume_cycle
    """
    program = get_success_data(api.create_program({"name": "F-CYC"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"])
    rel = create_relationship(client["id"], debtor["id"], noticed=True)
    validate_success(api.suspend_relationship(rel["id"], FO), 200)
    resumed = validate_success(api.resume_relationship(rel["id"], FO), 200)
    assert resumed["notice_status"] == "NOTICED", (
        f"after suspend+resume notice_status revisits NOTICED, "
        f"got {resumed['notice_status']}")


def test_relationship_cycle_version_increments_each_transition(api):
    """PRD §3.3: "The relationship's notice posture thus cycles `NOTICED →
    SUSPENDED → NOTICED`; each of these transitions increments `version`."
    PRD §3.3: "On success the posture moves `PENDING → NOTICED` and the
    relationship `version` increments."

    create=v1, send-notice=v2, suspend=v3, resume=v4.

    Design: Difficulty/non_linear_state_machine/nlsm_relationship_notice_suspend_resume_cycle
    """
    program = get_success_data(api.create_program({"name": "F-CYC2"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"])
    rel = create_relationship(client["id"], debtor["id"], noticed=True)  # v2
    validate_success(api.suspend_relationship(rel["id"], FO), 200)        # v3
    resumed = validate_success(api.resume_relationship(rel["id"], FO), 200)  # v4
    assert resumed["version"] == 4, (
        f"create=1, send-notice=2, suspend=3, resume=4, got {resumed['version']}")


def test_reserve_conservation_fund_then_settle(api):
    """PRD §3.5: "The client's `reserve_balance_cents` increases by the held
    reserve". PRD §3.6: "its `reserve_balance_cents` decreases by the invoice's
    `reserve_held_cents`".

    Conserved quantity Client.reserve_balance_cents: funding holds +15000, the
    compensating settlement releases -15000 back to the pre-funding value 0.

    Design: Difficulty/compensating_invariant/ci_reserve_conservation_fund_then_settle
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-CI1"})
    inv_id = ctx["invoice"]["id"]
    client_id = ctx["client"]["id"]
    after_fund = validate_success(api.get_client(client_id, FO), 200)
    assert after_fund["reserve_balance_cents"] == 15000, (
        f"RESERVE_HELD +15000, got {after_fund['reserve_balance_cents']}")
    post_collection(inv_id, client_id, 100000, "2026-06-15T00:00:00Z")
    after_settle = validate_success(api.get_client(client_id, FO), 200)
    assert after_settle["reserve_balance_cents"] == 0, (
        f"RESERVE_RELEASED compensates back to 0, "
        f"got {after_settle['reserve_balance_cents']}")


def test_funded_advance_outstanding_conserved_fund_then_settle(api):
    """PRD §3.5: "The client's `reserve_balance_cents` increases by the held
    reserve and its `funded_advance_outstanding_cents` increases by the advance,
    the debtor's `outstanding_face_cents` increases by the face amount". PRD
    §3.6: "its `reserve_balance_cents` decreases by the invoice's
    `reserve_held_cents` and its `funded_advance_outstanding_cents` decreases by
    the `advance_amount_cents`".

    The companion conserved quantity funded_advance_outstanding_cents goes
    +85000 at funding and -85000 at settlement, returning to 0.

    Design: Difficulty/compensating_invariant/ci_reserve_conservation_fund_then_settle
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0,
                               invoice_overrides={"invoice_number": "INV-CI1"})
    inv_id = ctx["invoice"]["id"]
    client_id = ctx["client"]["id"]
    after_fund = validate_success(api.get_client(client_id, FO), 200)
    assert after_fund["funded_advance_outstanding_cents"] == 85000
    post_collection(inv_id, client_id, 100000, "2026-06-15T00:00:00Z")
    after_settle = validate_success(api.get_client(client_id, FO), 200)
    assert after_settle["funded_advance_outstanding_cents"] == 0, (
        f"outstanding advance restored to 0, "
        f"got {after_settle['funded_advance_outstanding_cents']}")


def test_debtor_face_conservation_fund_then_buyback(api):
    """PRD §3.5: "the debtor's `outstanding_face_cents` increases by the face
    amount". PRD §3.7: "the debtor's `outstanding_face_cents` decreases by the
    `face_amount_cents`."

    Conserved quantity Debtor.outstanding_face_cents: funding adds +100000, the
    compensating buyback subtracts -100000 back to 0.

    Design: Difficulty/compensating_invariant/ci_debtor_face_conservation_fund_then_buyback
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                               tier3_multiplier=2.0, recourse_grace_days=90,
                               recourse_type="RECOURSE",
                               invoice_overrides={"invoice_number": "INV-CI2"})
    inv_id = ctx["invoice"]["id"]
    debtor_id = ctx["debtor"]["id"]
    client_id = ctx["client"]["id"]
    after_fund = validate_success(api.get_debtor(debtor_id, FO), 200)
    assert after_fund["outstanding_face_cents"] == 100000, (
        f"+face 100000, got {after_fund['outstanding_face_cents']}")
    # Clock past due+grace (2026-05-31 + 90 = 2026-08-29); 2026-08-30 is later.
    advance_clock("2026-08-30T00:00:00Z")
    bought = validate_success(
        api.buyback_invoice(inv_id, buyback_payload("RECOURSE_OVERDUE"), CO), 200)
    assert bought["status"] == "BOUGHT_BACK"
    after_buyback = validate_success(api.get_debtor(debtor_id, FO), 200)
    assert after_buyback["outstanding_face_cents"] == 0, (
        f"compensated back to 0, got {after_buyback['outstanding_face_cents']}")
    client_after = validate_success(api.get_client(client_id, FO), 200)
    assert client_after["reserve_balance_cents"] == 0, (
        f"reserve also released to 0, got {client_after['reserve_balance_cents']}")


def test_debtor_face_added_at_funding_before_buyback(api):
    """PRD §3.5: "the debtor's `outstanding_face_cents` increases by the face
    amount".

    The conserved Debtor.outstanding_face_cents starts at the +face value
    100000 immediately after funding (the quantity that buyback later restores).

    Design: Difficulty/compensating_invariant/ci_debtor_face_conservation_fund_then_buyback
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               recourse_grace_days=90, recourse_type="RECOURSE",
                               invoice_overrides={"invoice_number": "INV-CI2"})
    debtor = validate_success(api.get_debtor(ctx["debtor"]["id"], FO), 200)
    assert debtor["outstanding_face_cents"] == 100000, (
        f"funding adds +face 100000 to debtor, "
        f"got {debtor['outstanding_face_cents']}")
