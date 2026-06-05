"""Trust income tax, capital-gain allocation, DNI, and K-1 character calculations.

Covers Difficulty queue rules dual_variant_calc and combinatorial_formula, plus the
calculations corner instances on input filtering and tier order.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_active_trust, setup_closed_account_with_draft_filing,
    propose_distribution, approve_distribution, pay_distribution,
    create_paid_distribution, post_receipt,
    TEST_USERS,
)

ADMIN = TEST_USERS["trust_admin_headers"]


# ─────────────────────────────────────────────────────────────
# Rule dual_variant_calc — grantor vs separate-taxpayer income tax
# ─────────────────────────────────────────────────────────────

def test_separate_taxpayer_trust_income_tax_compressed_brackets(api):
    """PRD §3.9: "For a non-grantor trust the tax is computed on the snapshotted taxable
    income under the compressed four-bracket schedule, applied marginally: the first
    310,000 cents of taxable income are taxed at 10 percent; taxable income above 310,000
    and up to 1,115,000 cents at 24 percent; taxable income above 1,115,000 and up to
    1,520,000 cents at 35 percent; and any taxable income above 1,520,000 cents at 37
    percent."

    Design: Difficulty/dual_variant_calc/grantor_vs_separate_taxpayer_trust_income_tax
    """
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=False)
    filed = validate_success(api.file_filing(ctx["filing"]["id"], ADMIN), 200)
    assert filed["tax_due_cents"] == 543550, \
        f"compressed-bracket tax on 2,000,000 must be 543550, got {filed['tax_due_cents']}"


def test_grantor_trust_income_tax_is_zero(api):
    """PRD §3.9: "For a grantor trust — one whose is_grantor_trust election is true — the
    tax_due_cents is 0, because the trust's income flows through to the grantor and the
    trust pays no tax at its own level."

    Design: Difficulty/dual_variant_calc/grantor_vs_separate_taxpayer_trust_income_tax
    """
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=True)
    filed = validate_success(api.file_filing(ctx["filing"]["id"], ADMIN), 200)
    assert filed["tax_due_cents"] == 0, \
        f"grantor trust must owe 0 tax, got {filed['tax_due_cents']}"


def test_identical_income_diverges_grantor_vs_separate(api):
    """PRD §3.9: "The identical taxable income therefore produces a positive tax for a
    separate-taxpayer trust and exactly zero for an otherwise-identical grantor trust."

    Design: Difficulty/dual_variant_calc/grantor_vs_separate_taxpayer_trust_income_tax
    """
    sep = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=False)
    grt = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=True)
    sep_filed = validate_success(api.file_filing(sep["filing"]["id"], ADMIN), 200)
    grt_filed = validate_success(api.file_filing(grt["filing"]["id"], ADMIN), 200)
    assert sep_filed["tax_due_cents"] == 543550
    assert grt_filed["tax_due_cents"] == 0


# ─────────────────────────────────────────────────────────────
# Rule dual_variant_calc — capital gain to principal vs income
# ─────────────────────────────────────────────────────────────

def test_capital_gain_to_principal_excluded_from_dni(api):
    """PRD §3.3: "A CAPITAL_GAIN receipt credits INCOME when the owning trust's
    capital_gains_to_income election is true and PRINCIPAL when it is false."

    Design: Difficulty/dual_variant_calc/capital_gain_to_principal_vs_income_allocation
    """
    ctx = setup_active_trust(contribution_cents=1, capital_gains_to_income=False)
    receipt = validate_success(
        api.create_receipt(ctx["account"]["id"],
                           {"amount_cents": 500000, "receipt_kind": "CAPITAL_GAIN"}, ADMIN), 201)
    assert receipt["ledger_side"] == "PRINCIPAL"
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    assert acct["dni_cents"] == 0, \
        f"capital gain in principal must be excluded from DNI, got {acct['dni_cents']}"


def test_capital_gain_to_income_included_in_dni(api):
    """PRD §3.4: "Because capital-gain receipts land in income only under the
    capital_gains_to_income election, the very same set of receipts produces a larger
    distributable net income — and a different K-1 capital-gain line — for a trust that has
    made that election than for one that has not."

    Design: Difficulty/dual_variant_calc/capital_gain_to_principal_vs_income_allocation
    """
    ctx = setup_active_trust(contribution_cents=1, capital_gains_to_income=True)
    receipt = validate_success(
        api.create_receipt(ctx["account"]["id"],
                           {"amount_cents": 500000, "receipt_kind": "CAPITAL_GAIN"}, ADMIN), 201)
    assert receipt["ledger_side"] == "INCOME"
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    assert acct["dni_cents"] == 500000, \
        f"capital gain in income must be included in DNI, got {acct['dni_cents']}"


# ─────────────────────────────────────────────────────────────
# Rule combinatorial_formula — compressed-bracket tiered tax (mode a)
# ─────────────────────────────────────────────────────────────

def test_compressed_bracket_straddles_all_four_tiers(api):
    """PRD §3.9: "For a non-grantor trust the tax is computed on the snapshotted taxable
    income under the compressed four-bracket schedule, applied marginally: the first
    310,000 cents of taxable income are taxed at 10 percent; taxable income above 310,000
    and up to 1,115,000 cents at 24 percent; taxable income above 1,115,000 and up to
    1,520,000 cents at 35 percent; and any taxable income above 1,520,000 cents at 37
    percent."

    Design: Difficulty/combinatorial_formula/compressed_bracket_tiered_tax_mode_a
    """
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=False)
    filed = validate_success(api.file_filing(ctx["filing"]["id"], ADMIN), 200)
    # 31000 + 193200 + 141750 + 177600 = 543550
    assert filed["tax_due_cents"] == 543550


def test_compressed_bracket_snapshot_matches_taxable_income(api):
    """PRD §3.7: "Filing snapshots the period's taxable income into
    taxable_income_snapshot_cents and computes tax_due_cents (described in §3.9)."

    Design: Difficulty/combinatorial_formula/compressed_bracket_tiered_tax_mode_a
    """
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=2_000_000, contribution_cents=1, is_grantor_trust=False)
    filed = validate_success(api.file_filing(ctx["filing"]["id"], ADMIN), 200)
    assert filed["taxable_income_snapshot_cents"] == 2_000_000
    assert filed["tax_due_cents"] == 543550


# ─────────────────────────────────────────────────────────────
# Rule combinatorial_formula — K-1 character residual rounding (mode b)
# ─────────────────────────────────────────────────────────────

def _setup_k1_residual_scenario(api):
    """Three non-skip beneficiaries A,B,C; income receipts INTEREST 60001 +
    DIVIDEND_ORDINARY 15000 + DIVIDEND_QUALIFIED 24999 => DNI=100000, ord_pool=75001,
    qd_pool=24999. MANDATORY distributions A=40000, B=40000, C=20000 all PAID =>
    total carried 100000, shares 0.4/0.4/0.2."""
    ctx = setup_active_trust(
        contribution_cents=5_000_000,
        income_receipts=[(60001, "INTEREST"), (15000, "DIVIDEND_ORDINARY"),
                         (24999, "DIVIDEND_QUALIFIED")],
        num_trustees=2, capital_gains_to_income=False)
    acct_id = ctx["account"]["id"]
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    ben_b = get_success_data(api.create_beneficiary(
        {"full_name": "Ben B", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    ben_c = get_success_data(api.create_beneficiary(
        {"full_name": "Ben C", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    create_paid_distribution(acct_id, ben_a["id"], 40000, t_prop, t_appr, "MANDATORY")
    create_paid_distribution(acct_id, ben_b["id"], 40000, t_prop, t_appr, "MANDATORY")
    create_paid_distribution(acct_id, ben_c["id"], 20000, t_prop, t_appr, "MANDATORY")
    return acct_id, ben_a, ben_b, ben_c


def _k1_for(api, account_id, beneficiary_id):
    data, _ = validate_paginated(
        api.list_account_k1s(account_id, ADMIN, params={"beneficiary_id": beneficiary_id}))
    assert len(data) == 1, f"expected exactly one K-1 for beneficiary, got {len(data)}"
    return data[0]


def test_k1_residual_added_to_earliest_largest_share_beneficiary(api):
    """PRD §3.6: "Rounding is performed per beneficiary line independently; any residual
    cent — the scaled character total minus the sum of the rounded per-beneficiary lines —
    is then added to the beneficiary holding the largest carried share, ties broken by
    earliest created_at."

    Design: Difficulty/combinatorial_formula/k1_character_residual_rounding_mode_b
    """
    acct_id, ben_a, ben_b, ben_c = _setup_k1_residual_scenario(api)
    k1_a = _k1_for(api, acct_id, ben_a["id"])
    assert k1_a["ordinary_income_cents"] == 30001
    assert k1_a["qualified_dividend_cents"] == 9999


def test_k1_non_residual_beneficiaries_round_to_base_lines(api):
    """PRD §3.6: "each of the beneficiary's three character lines is the corresponding
    scaled character pool times that share, rounded half up."

    Design: Difficulty/combinatorial_formula/k1_character_residual_rounding_mode_b
    """
    acct_id, ben_a, ben_b, ben_c = _setup_k1_residual_scenario(api)
    k1_b = _k1_for(api, acct_id, ben_b["id"])
    k1_c = _k1_for(api, acct_id, ben_c["id"])
    assert k1_b["ordinary_income_cents"] == 30000
    assert k1_b["qualified_dividend_cents"] == 10000
    assert k1_c["ordinary_income_cents"] == 15000
    assert k1_c["qualified_dividend_cents"] == 5000


# ─────────────────────────────────────────────────────────────
# Corner / calculations
# ─────────────────────────────────────────────────────────────

def test_dni_excludes_principal_capital_gain_receipt(api):
    """PRD §3.4: "take the sum of amount_cents over every receipt on the period whose
    computed ledger_side is INCOME, subtract the sum of amount_cents over every
    disbursement on the period whose ledger_side is INCOME, and floor the result at zero
    so it can never go negative."

    Design: Corner/calculations/dni_excludes_principal_capital_gain_receipt
    """
    ctx = setup_active_trust(
        contribution_cents=1,
        income_receipts=[(30000, "INTEREST"), (70000, "CAPITAL_GAIN")],
        capital_gains_to_income=False)
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    assert acct["dni_cents"] == 30000, \
        f"DNI must exclude the principal-side capital gain, got {acct['dni_cents']}"


def test_mandatory_carries_dni_before_discretionary(api):
    """PRD §3.6: "The distributions are ordered so that all MANDATORY distributions precede
    all DISCRETIONARY ones, and within each tier they are ordered by created_at ascending
    (never by id)."

    Design: Corner/calculations/mandatory_before_discretionary_dni_carryout_tier_order
    """
    ctx = setup_active_trust(
        contribution_cents=5_000_000, income_receipts=[(10000, "INTEREST")],
        num_trustees=2, capital_gains_to_income=False)
    acct_id = ctx["account"]["id"]
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    ben_b = get_success_data(api.create_beneficiary(
        {"full_name": "Ben B", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    # DISCRETIONARY created first, MANDATORY created second.
    disc = propose_distribution(acct_id, ben_a["id"], 8000, t_prop, "DISCRETIONARY")
    mand = propose_distribution(acct_id, ben_b["id"], 8000, t_prop, "MANDATORY")
    approve_distribution(disc["id"], t_appr)
    approve_distribution(mand["id"], t_appr)
    pay_distribution(disc["id"], t_prop)
    pay_distribution(mand["id"], t_prop)
    mand_after = validate_success(api.get_distribution(mand["id"], ADMIN), 200)
    disc_after = validate_success(api.get_distribution(disc["id"], ADMIN), 200)
    assert mand_after["dni_carried_amount_cents"] == 8000, \
        "MANDATORY tier carries first and gets full 8000"
    assert disc_after["dni_carried_amount_cents"] == 2000, \
        "DISCRETIONARY gets only the remaining 2000 of DNI"
