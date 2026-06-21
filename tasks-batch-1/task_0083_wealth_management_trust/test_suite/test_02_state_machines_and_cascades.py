"""Trust/TaxFiling state cycles and the pay/file cascade chains.

Covers Difficulty queue rules non_linear_state_machine and transitive_cascade, plus the
state-machine, errors, consistency, and cross-cutting corner instances that ride the same
lifecycles.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_active_trust, setup_closed_account_with_draft_filing, setup_filed_account,
    create_paid_distribution, create_approved_distribution,
    make_grantor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["trust_admin_headers"]


# ─────────────────────────────────────────────────────────────
# Rule non_linear_state_machine — Trust amendment cycle
# ─────────────────────────────────────────────────────────────

def test_amendment_opens_then_returns_to_active(api):
    """PRD §3.9: "Opening an amendment moves the trust from ACTIVE to AMENDMENT_PENDING and
    stages an election change". "Committing the amendment moves the trust from
    AMENDMENT_PENDING back to ACTIVE, applies the staged capital_gains_to_income and
    is_grantor_trust changes to the trust".

    Design: Difficulty/non_linear_state_machine/trust_amendment_cycle_active_loop
    """
    ctx = setup_active_trust(trust_type="REVOCABLE", contribution_cents=1_000_000,
                             capital_gains_to_income=False)
    g_hdr = make_grantor_headers(ctx["grantor"]["id"])
    trust_id = ctx["trust"]["id"]
    pending = validate_success(
        api.open_amendment(trust_id, {"set_capital_gains_to_income": True}, g_hdr), 200)
    assert pending["status"] == "AMENDMENT_PENDING"
    committed = validate_success(api.commit_amendment(trust_id, g_hdr), 200)
    assert committed["status"] == "ACTIVE"


def test_amendment_commit_applies_staged_election(api):
    """PRD §3.9: "Committing the amendment moves the trust from AMENDMENT_PENDING back to
    ACTIVE, applies the staged capital_gains_to_income and is_grantor_trust changes to the
    trust, recomputes ledger sides and distributable net income for affected periods".

    Design: Difficulty/non_linear_state_machine/trust_amendment_cycle_active_loop
    """
    ctx = setup_active_trust(trust_type="REVOCABLE", contribution_cents=1_000_000,
                             capital_gains_to_income=False)
    g_hdr = make_grantor_headers(ctx["grantor"]["id"])
    trust_id = ctx["trust"]["id"]
    validate_success(
        api.open_amendment(trust_id, {"set_capital_gains_to_income": True}, g_hdr), 200)
    committed = validate_success(api.commit_amendment(trust_id, g_hdr), 200)
    assert committed["capital_gains_to_income"] is True


# ─────────────────────────────────────────────────────────────
# Rule non_linear_state_machine — TaxFiling supersede cycle
# ─────────────────────────────────────────────────────────────

def _setup_supersede_pair(api):
    """Account CLOSED with taxable_income=2000000; original filing F1 left DRAFT, amended
    filing F2 references F1 via supersedes_filing_id and is the one driven to FILED.

    Both filings are created while the period is still CLOSED (F1 DRAFT, so no FILED filing
    exists yet to block F2's creation). F2 is then filed — permitted because the period is
    CLOSED and no existing filing for the period is FILED-and-not-superseded (F1 is DRAFT).
    Filing F2 advances the period CLOSED->FILED. The amend/refile cycle in the tests then
    runs on F2 (FILED->AMENDED->FILED), and refiling F2 marks the named prior filing F1 as
    SUPERSEDED per PRD §3.7. Filing F1 instead would freeze the period to FILED and make F2
    uncreatable, so F2 is the filing that must reach FILED here."""
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=False)
    acct_id = ctx["account"]["id"]
    f1 = ctx["filing"]
    f2 = get_success_data(api.create_filing(acct_id, {"supersedes_filing_id": f1["id"]}, ADMIN))
    f2 = validate_success(api.file_filing(f2["id"], ADMIN), 200)
    return f1, f2


def test_filing_amend_refile_cycle(api):
    """PRD §3.7: "Amending moves a filing from FILED to AMENDED and increments its version.
    Refiling then moves it from AMENDED back to FILED".

    Design: Difficulty/non_linear_state_machine/tax_filing_supersede_cycle
    """
    f1, f2 = _setup_supersede_pair(api)
    amended = validate_success(api.amend_filing(f2["id"], ADMIN), 200)
    assert amended["status"] == "AMENDED"
    refiled = validate_success(api.refile_filing(f2["id"], ADMIN), 200)
    assert refiled["status"] == "FILED"


def test_refile_marks_prior_filing_superseded(api):
    """PRD §3.7: "Refiling then moves it from AMENDED back to FILED: it marks the prior
    original filing named by supersedes_filing_id as SUPERSEDED".

    Design: Difficulty/non_linear_state_machine/tax_filing_supersede_cycle
    """
    f1, f2 = _setup_supersede_pair(api)
    validate_success(api.amend_filing(f2["id"], ADMIN), 200)
    validate_success(api.refile_filing(f2["id"], ADMIN), 200)
    f1_after = validate_success(api.get_filing(f1["id"], ADMIN), 200)
    assert f1_after["status"] == "SUPERSEDED"


# ─────────────────────────────────────────────────────────────
# Rule transitive_cascade — pay → balance → DNI → K-1 (depth 3)
# ─────────────────────────────────────────────────────────────

def _setup_single_paid_distribution(api):
    """ACTIVE non-grantor trust, DNI=100000, principal 5000000; one MANDATORY 50000 to
    non-skip Ben A, paid."""
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(100000, "INTEREST")],
        num_trustees=2, capital_gains_to_income=False)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    paid = create_paid_distribution(ctx["account"]["id"], ben_a["id"], 50000,
                                    t_prop, t_appr, "MANDATORY")
    return ctx, ben_a, paid


def test_pay_cascade_sets_distribution_and_account_carryout(api):
    """PRD §3.5: "That balance change cascades into a recomputation of the owning period's
    dni_carried_out_cents and a re-run of the carry-out allocation across every PAID
    distribution on the period (described in §3.6), which in turn cascades into
    recomputation of every affected beneficiary's K-1 character lines."

    Design: Difficulty/transitive_cascade/pay_distribution_balance_dni_k1_chain_depth3
    """
    ctx, ben_a, paid = _setup_single_paid_distribution(api)
    assert paid["dni_carried_amount_cents"] == 50000
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    assert acct["dni_carried_out_cents"] == 50000


def test_pay_cascade_recomputes_beneficiary_k1_total(api):
    """PRD §3.6: "Each beneficiary receiving carried-out income gets an annual K-1 statement
    scoped to a period (its account_id) and a beneficiary_id, breaking the carried-out
    income into character lines: ordinary_income_cents, qualified_dividend_cents,
    capital_gain_cents, and a total_carried_cents that is their sum."

    Design: Difficulty/transitive_cascade/pay_distribution_balance_dni_k1_chain_depth3
    """
    ctx, ben_a, paid = _setup_single_paid_distribution(api)
    data, _ = validate_paginated(
        api.list_account_k1s(ctx["account"]["id"], ADMIN,
                             params={"beneficiary_id": ben_a["id"]}))
    assert len(data) == 1
    assert data[0]["total_carried_cents"] == 50000


# ─────────────────────────────────────────────────────────────
# Rule transitive_cascade — file → account FILED → tax disbursement (depth 2)
# ─────────────────────────────────────────────────────────────

def test_file_cascades_account_to_filed(api):
    """PRD §3.7: "It then cascades: the owning period advances from CLOSED to FILED".

    Design: Difficulty/transitive_cascade/file_tax_account_filed_tax_disbursement_depth2
    """
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=5_000_000, is_grantor_trust=False)
    filed = validate_success(api.file_filing(ctx["filing"]["id"], ADMIN), 200)
    assert filed["tax_due_cents"] == 543550
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    assert acct["status"] == "FILED"


def test_file_spawns_system_tax_payment_disbursement(api):
    """PRD §3.7: "when tax_due_cents is greater than zero, the platform spawns a system
    disbursement on the period — expense_kind TAX_PAYMENT, is_system_generated true,
    ledger_side PRINCIPAL, amount_cents equal to tax_due_cents — which debits the trust's
    principal_balance_cents."

    Design: Difficulty/transitive_cascade/file_tax_account_filed_tax_disbursement_depth2
    """
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=5_000_000, is_grantor_trust=False)
    validate_success(api.file_filing(ctx["filing"]["id"], ADMIN), 200)
    data, _ = validate_paginated(api.list_disbursements(ctx["account"]["id"], ADMIN))
    tax_disbs = [d for d in data if d["is_system_generated"]]
    assert len(tax_disbs) == 1, f"expected one system disbursement, got {len(tax_disbs)}"
    d = tax_disbs[0]
    assert d["expense_kind"] == "TAX_PAYMENT"
    assert d["amount_cents"] == 543550
    assert d["ledger_side"] == "PRINCIPAL"


# ─────────────────────────────────────────────────────────────
# Corner / consistency_model — pay cascade visible in same response
# ─────────────────────────────────────────────────────────────

def test_pay_response_carries_cascaded_carryout(api):
    """PRD §1 (Introduction): "the platform recomputes every derived figure — balances,
    distributable net income, carry-out, K-1 character lines, inclusion ratios — atomically
    within the request that triggers the change, so that a response never reflects a
    half-applied mutation."

    Design: Corner/consistency_model/pay_cascade_visible_in_same_response
    """
    ctx, ben_a, paid = _setup_single_paid_distribution(api)
    assert paid["status"] == "PAID"
    assert paid["dni_carried_amount_cents"] == 50000


# ─────────────────────────────────────────────────────────────
# Corner / errors — release after consumption
# ─────────────────────────────────────────────────────────────

def test_release_consumed_allocation_rejected(api):
    """PRD §3.8: "it is permitted only while the allocation is ALLOCATED and only when no
    GST event on the trust has already consumed this exemption (otherwise the release is
    rejected with ERR_ALLOCATION_CONSUMED)."

    Design: Corner/errors/error_allocation_consumed_on_release
    """
    from test_helpers import allocate_gst_exemption
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(1_500_000, "INTEREST")],
        num_trustees=2, grantor_gen=0)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    skip = get_success_data(api.create_beneficiary(
        {"full_name": "Grandchild", "grantor_id": g_id, "generation_level": 2}, ADMIN))
    alloc = allocate_gst_exemption(trust_id, g_id, 2_000_000, ctx["trust"]["version"])
    create_paid_distribution(ctx["account"]["id"], skip["id"], 1_000_000,
                             t_prop, t_appr, "MANDATORY")
    res = api.release_gst_exemption_allocation(trust_id, alloc["id"], ADMIN)
    validate_error(res, "ERR_ALLOCATION_CONSUMED")
