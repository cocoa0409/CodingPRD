"""Conserved-quantity invariants under pay/reverse and allocate/release, plus GST
exemption optimistic-concurrency and derived-balance reconciliation.

Covers Difficulty queue rule compensating_invariant and the cross-cutting corner instances
on OCC and derived-field reconciliation.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_active_trust, allocate_gst_exemption, make_trustee_headers,
    create_paid_distribution,
    TEST_USERS,
)
from test_helpers.constants import DEFAULT_GST_EXEMPTION_TOTAL_CENTS

ADMIN = TEST_USERS["trust_admin_headers"]


# ─────────────────────────────────────────────────────────────
# Rule compensating_invariant — pay/reverse preserves liquid corpus
# ─────────────────────────────────────────────────────────────

def test_reverse_restores_principal_and_income(api):
    """PRD §3.5: "Reversal is the exact inverse of payment: it credits the trust's
    income_balance_cents by funded_from_income_cents and its principal_balance_cents by
    funded_from_principal_cents".

    Design: Difficulty/compensating_invariant/distribution_pay_reverse_preserves_liquid_corpus
    """
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(1_500_000, "INTEREST")],
        num_trustees=2, capital_gains_to_income=False)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    paid = create_paid_distribution(ctx["account"]["id"], ben_a["id"], 50000,
                                    t_prop, t_appr, "MANDATORY")
    validate_success(api.reverse_distribution(paid["id"], ADMIN), 200)
    trust = validate_success(api.get_trust(ctx["trust"]["id"], ADMIN), 200)
    assert trust["principal_balance_cents"] == 5_000_000
    assert trust["income_balance_cents"] == 1_500_000


def test_reverse_preserves_total_liquid_corpus(api):
    """PRD §3.5: "A paid distribution may be reversed by the back office while the owning
    period is still OPEN, moving it from PAID to the terminal REVERSED state. Reversal is
    the exact inverse of payment".

    Design: Difficulty/compensating_invariant/distribution_pay_reverse_preserves_liquid_corpus
    """
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(1_500_000, "INTEREST")],
        num_trustees=2, capital_gains_to_income=False)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    paid = create_paid_distribution(ctx["account"]["id"], ben_a["id"], 50000,
                                    t_prop, t_appr, "MANDATORY")
    validate_success(api.reverse_distribution(paid["id"], ADMIN), 200)
    trust = validate_success(api.get_trust(ctx["trust"]["id"], ADMIN), 200)
    assert trust["principal_balance_cents"] + trust["income_balance_cents"] == 6_500_000


# ─────────────────────────────────────────────────────────────
# Rule compensating_invariant — allocate/release preserves pool
# ─────────────────────────────────────────────────────────────

def test_release_restores_grantor_remaining_and_trust_allocated(api):
    """PRD §3.8: "Release moves the allocation to the terminal RELEASED state, decrements
    the trust's gst_exemption_allocated_cents by the released amount_cents, recomputes the
    trust's inclusion_ratio and the grantor's gst_exemption_remaining_cents".

    Design: Difficulty/compensating_invariant/gst_exemption_allocate_release_preserves_pool
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    alloc = allocate_gst_exemption(trust_id, g_id, 2_000_000, ctx["trust"]["version"])
    validate_success(api.release_gst_exemption_allocation(trust_id, alloc["id"], ADMIN), 200)
    grantor = validate_success(api.get_grantor(g_id, ADMIN), 200)
    trust = validate_success(api.get_trust(trust_id, ADMIN), 200)
    assert grantor["gst_exemption_remaining_cents"] == DEFAULT_GST_EXEMPTION_TOTAL_CENTS
    assert trust["gst_exemption_allocated_cents"] == 0


def test_release_preserves_total_exemption_pool(api):
    """PRD §3.1: "thereafter it is a computed figure equal to the total minus the sum,
    across all of that grantor's trusts, of the exemption currently allocated to each, and
    it is recomputed on every allocation and every release."

    Design: Difficulty/compensating_invariant/gst_exemption_allocate_release_preserves_pool
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    alloc = allocate_gst_exemption(trust_id, g_id, 2_000_000, ctx["trust"]["version"])
    validate_success(api.release_gst_exemption_allocation(trust_id, alloc["id"], ADMIN), 200)
    grantor = validate_success(api.get_grantor(g_id, ADMIN), 200)
    trust = validate_success(api.get_trust(trust_id, ADMIN), 200)
    assert (grantor["gst_exemption_remaining_cents"]
            + trust["gst_exemption_allocated_cents"]) == DEFAULT_GST_EXEMPTION_TOTAL_CENTS


# ─────────────────────────────────────────────────────────────
# Corner / cross_cutting — OCC stale-version
# ─────────────────────────────────────────────────────────────

def test_stale_trust_version_rejected_on_second_allocation(api):
    """PRD §2.9: "If they differ — because some other writer has advanced the trust's
    version since the client read it, for example by posting an earlier allocation that
    consumed part of the shared grantor exemption pool — the allocation is rejected with
    ERR_STALE_TRUST_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/gst_alloc_stale_trust_version_rejected
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    tv0 = ctx["trust"]["version"]
    # First allocation succeeds and advances the trust version.
    validate_success(api.create_gst_exemption_allocation(
        trust_id, {"grantor_id": g_id, "amount_cents": 1_000_000,
                   "expected_trust_version": tv0}, ADMIN), 201)
    # Second allocation still carrying the pre-allocation version is stale.
    res = api.create_gst_exemption_allocation(
        trust_id, {"grantor_id": g_id, "amount_cents": 1_000_000,
                   "expected_trust_version": tv0}, ADMIN)
    validate_error(res, "ERR_STALE_TRUST_VERSION")


def test_gst_allocation_increments_version_and_recomputes_inclusion_ratio(api):
    """PRD §3.8: "A successful allocation increases the trust's gst_exemption_allocated_cents
    by amount_cents, recomputes the trust's inclusion_ratio and the grantor's
    gst_exemption_remaining_cents, and increments the trust's version."

    Design: Corner/cross_cutting_complexity_layers/gst_alloc_version_increments_on_success
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    tv = ctx["trust"]["version"]
    validate_success(api.create_gst_exemption_allocation(
        trust_id, {"grantor_id": g_id, "amount_cents": 1_000_000,
                   "expected_trust_version": tv}, ADMIN), 201)
    trust = validate_success(api.get_trust(trust_id, ADMIN), 200)
    assert trust["version"] == tv + 1
    # principal 5000000, allocated 1000000 => 1 - 0.2 = 0.8
    assert trust["inclusion_ratio"] == pytest.approx(0.8, abs=1e-6)


# ─────────────────────────────────────────────────────────────
# Corner / cross_cutting — derived balance reconciliation
# ─────────────────────────────────────────────────────────────

def test_balances_reconcile_after_each_receipt(api):
    """PRD §2.7: "The principal balance is the sum of every principal-side receipt minus
    every principal-side disbursement minus the principal-funded portion of every paid
    distribution, taken across all of the trust's accounting periods. The income balance
    is, in parallel, the sum of every income-side receipt minus every income-side
    disbursement minus the income-funded portion of every paid distribution".

    Design: Corner/cross_cutting_complexity_layers/balances_reconciled_after_receipt
    """
    # FUNDED-or-later not required for balance reconciliation; post receipts on an OPEN
    # account of a DRAFT trust (creation does not require funding).
    g = get_success_data(api.create_grantor({"full_name": "G Rec", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "Rec Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    acct = get_success_data(api.create_account(trust["id"], {
        "tax_year": 2025, "period_start": "2025-01-01T00:00:00.000Z",
        "period_end": "2026-01-01T00:00:00.000Z"}, ADMIN))
    validate_success(api.create_receipt(
        acct["id"], {"amount_cents": 5_000_000, "receipt_kind": "CONTRIBUTION"}, ADMIN), 201)
    validate_success(api.create_receipt(
        acct["id"], {"amount_cents": 30000, "receipt_kind": "INTEREST"}, ADMIN), 201)
    trust = validate_success(api.get_trust(trust["id"], ADMIN), 200)
    assert trust["principal_balance_cents"] == 5_000_000
    assert trust["income_balance_cents"] == 30000
