"""Tax forms: the 1099-SA gross-vs-taxable dual-variant aggregation over distributions,
and the 5498-SA contribution totals plus the fair-market-value snapshot.
"""
from test_helpers import (
    validate_success,
    assert_tax_form,
)
from test_helpers.fixtures import (
    ADMIN, ADMIN_A, ADMIN_B, set_clock, create_accountholder, open_account,
    attest_coverage, verify_account, create_and_post_contribution, account_version,
    request_distribution, clear_distribution, vault_receipt, generate_tax_form,
)
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


def _setup_three_cleared_distributions(api):
    """ACTIVE account funded with 200000; three distributions cleared by adminA:
    d1 50000 substantiated QUALIFIED (qualifying receipt), d2 30000 substantiated
    NONQUALIFIED (non-qualifying receipt), d3 12000 left UNSUBSTANTIATED.
    Returns (account, holder)."""
    set_clock("2026-02-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1980-04-04")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "SELF_ONLY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    create_and_post_contribution(account["id"], "INDIVIDUAL", 200000)
    rcpt_q = vault_receipt(account["id"], holder["id"], amount_cents=60000,
                           is_qualified_medical=True, merchant="Clinic",
                           service_date="2026-01-20T00:00:00Z")
    rcpt_n = vault_receipt(account["id"], holder["id"], amount_cents=40000,
                           is_qualified_medical=False, merchant="Spa",
                           service_date="2026-01-21T00:00:00Z")
    d1 = request_distribution(account["id"], holder["id"], "REIMBURSEMENT", 50000)
    d2 = request_distribution(account["id"], holder["id"], "REIMBURSEMENT", 30000)
    d3 = request_distribution(account["id"], holder["id"], "REIMBURSEMENT", 12000)
    clear_distribution(account["id"], d1["id"], ADMIN_A)
    clear_distribution(account["id"], d2["id"], ADMIN_A)
    clear_distribution(account["id"], d3["id"], ADMIN_A)
    validate_success(api.substantiate_distribution(
        account["id"], d1["id"], {"receipt_id": rcpt_q["id"]}, ADMIN_B), 200)
    validate_success(api.substantiate_distribution(
        account["id"], d2["id"], {"receipt_id": rcpt_n["id"]}, ADMIN_B), 200)
    return account, holder


# ── distribution_gross_vs_taxable_on_distribution (Difficulty/dual_variant_calc) ─

def test_form_1099_gross_box_sums_all_cleared(api):
    """PRD §3.10: "The `gross_amount_cents` is the sum of `amount_cents` over all of
    those included distributions, regardless of their substantiation."

    Three CLEARED distributions 50000 + 30000 + 12000 -> gross 92000 (GROSS_REPORTING).

    Design: Difficulty/dual_variant_calc/distribution_gross_vs_taxable_on_distribution
    """
    account, holder = _setup_three_cleared_distributions(api)
    form = generate_tax_form(account["id"], "FORM_1099_SA", 2026)
    assert form["gross_amount_cents"] == 92000


def test_form_1099_taxable_box_sums_nonqualified_and_unsubstantiated(api):
    """PRD §3.10: "The `nonqualified_amount_cents` is the sum of `amount_cents` over only
    those included distributions whose `substantiation_status` is `NONQUALIFIED`, where
    for tax-reporting purposes an `UNSUBSTANTIATED` distribution is treated as
    `NONQUALIFIED`."

    d2 (30000 NONQUALIFIED) + d3 (12000 UNSUBSTANTIATED-as-NONQUALIFIED) = 42000; the
    QUALIFIED d1 (50000) is excluded.

    Design: Difficulty/dual_variant_calc/distribution_gross_vs_taxable_on_distribution
    """
    account, holder = _setup_three_cleared_distributions(api)
    form = generate_tax_form(account["id"], "FORM_1099_SA", 2026)
    assert form["nonqualified_amount_cents"] == 42000


def test_form_1099_gross_and_taxable_diverge(api):
    """PRD §3.10: "The `gross_amount_cents` is the sum of `amount_cents` over all of
    those included distributions, regardless of their substantiation. The
    `nonqualified_amount_cents` is the sum of `amount_cents` over only those included
    distributions whose `substantiation_status` is `NONQUALIFIED`".

    On the same distribution set the gross box (92000) and the taxable box (42000)
    diverge because the QUALIFIED distribution is gross-only.

    Design: Difficulty/dual_variant_calc/distribution_gross_vs_taxable_on_distribution
    """
    account, holder = _setup_three_cleared_distributions(api)
    form = generate_tax_form(account["id"], "FORM_1099_SA", 2026)
    assert form["gross_amount_cents"] == 92000
    assert form["nonqualified_amount_cents"] == 42000
    assert form["gross_amount_cents"] != form["nonqualified_amount_cents"]


# ── form_5498_totals_sum_posted_and_fmv_snapshot (Corner/calculations) ───────
# NOTE: gross_amount_cents == 300000 (sum of POSTED contributions) is verbatim and
# uniquely derivable from PRD §3.10. The instance's literal FMV value is not asserted;
# instead FMV is checked against PRD §3.10's exact definition (live cash + invested at
# generation), which is what the PRD uniquely determines.

def test_form_5498_gross_sums_posted_contributions(api):
    """PRD §3.10: "For a `FORM_5498_SA` (the contribution form), the `gross_amount_cents`
    is the sum of `amount_cents` over all contributions in the tax year whose `status`
    is `POSTED`".

    Two POSTED contributions 200000 + 100000 -> gross 300000.

    Design: Corner/calculations/form_5498_totals_sum_posted_and_fmv_snapshot
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1979-01-01")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "FAMILY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    create_and_post_contribution(account["id"], "INDIVIDUAL", 200000)
    create_and_post_contribution(account["id"], "INDIVIDUAL", 100000)
    v = account_version(account["id"])
    validate_success(api.create_sweep(
        account["id"], {"requested_amount_cents": 50000,
                        "expected_account_version": v}, ADMIN_HDR), 201)
    form = generate_tax_form(account["id"], "FORM_5498_SA", 2026)
    assert_tax_form(form)
    assert form["gross_amount_cents"] == 300000


def test_form_5498_fmv_is_cash_plus_invested_snapshot(api):
    """PRD §3.10: "the `fair_market_value_cents` is a snapshot of the account's
    `cash_balance_cents` plus its `invested_balance_cents` taken at generation time."

    After contributions 300000 and a 50000 sweep (cash 250000, invested 50000), the FMV
    snapshot equals the live cash + invested read at generation time.

    Design: Corner/calculations/form_5498_totals_sum_posted_and_fmv_snapshot
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1979-01-01")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "FAMILY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    create_and_post_contribution(account["id"], "INDIVIDUAL", 200000)
    create_and_post_contribution(account["id"], "INDIVIDUAL", 100000)
    v = account_version(account["id"])
    validate_success(api.create_sweep(
        account["id"], {"requested_amount_cents": 50000,
                        "expected_account_version": v}, ADMIN_HDR), 201)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    expected_fmv = acct["cash_balance_cents"] + acct["invested_balance_cents"]
    form = generate_tax_form(account["id"], "FORM_5498_SA", 2026)
    assert form["fair_market_value_cents"] == expected_fmv
    assert form["nonqualified_amount_cents"] == 0
