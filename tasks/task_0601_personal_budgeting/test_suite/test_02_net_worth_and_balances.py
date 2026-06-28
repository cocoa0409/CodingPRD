"""Net-worth rollup: cleared vs pending-aware, signed multi-account, archived exclusion,
and balance reconciliation after post.

Translates Difficulty queue (A) dual_variant_calc / combinatorial_formula (net_worth)
and Corner queue (B) net-worth claims.
"""
from test_helpers import (
    validate_success, get_success_data, admin_headers,
    create_household, create_account, ingest_transaction, ingest_and_post,
    post_transaction,
)


def test_net_worth_cleared_vs_pending_aware_diverge(api):
    """PRD §2.10: "The household's net_worth_cents is the sum, across all accounts whose
    status is LINKED, of each account's signed cleared_balance_cents; the household's
    projected_net_worth_cents is the same sum but using each account's signed
    available_balance_cents."
    PRD §3.3: "Ingesting a pending transaction recomputes the owning account's
    available_balance_cents and the household's projected_net_worth_cents — pending money
    moves the forward view but not the settled one."

    Design: Difficulty/dual_variant_calc/net_worth_cleared_vs_pending_aware
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                         opening_balance_cents=10000)
    ingest_transaction(acc["id"], amount_cents=-5000, merchant_name="Store")

    data = validate_success(api.get_household(hh["id"], owner_headers))
    assert data["net_worth_cents"] == 10000, \
        f"cleared excludes PENDING, expected 10000, got {data['net_worth_cents']}"
    assert data["projected_net_worth_cents"] == 5000, \
        f"pending-aware includes PENDING, expected 5000, got {data['projected_net_worth_cents']}"


def test_net_worth_cleared_converges_after_pending_posts(api):
    """PRD §2.10: "The cleared figure is the settled view and excludes pending transactions
    entirely; the projected figure is the forward-looking view and diverges from the cleared
    figure precisely when some linked account has open pending transactions."
    PRD §3.3: "The post triggers a cascade. ... Then the household's net_worth_cents and
    projected_net_worth_cents are recomputed."

    Design: Difficulty/dual_variant_calc/net_worth_cleared_vs_pending_aware
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                         opening_balance_cents=10000)
    # While PENDING: cleared 10000, projected 5000 (diverge).
    txn = ingest_transaction(acc["id"], amount_cents=-5000, merchant_name="Store")
    diverged = validate_success(api.get_household(hh["id"], owner_headers))
    assert diverged["net_worth_cents"] == 10000
    assert diverged["projected_net_worth_cents"] == 5000

    # After post: both views settle to 5000 (no open pending -> no divergence).
    validate_success(api.post_transaction(acc["id"], txn["id"], admin_headers()))
    converged = validate_success(api.get_household(hh["id"], owner_headers))
    assert converged["net_worth_cents"] == 5000, \
        f"after post cleared == 5000, got {converged['net_worth_cents']}"
    assert converged["projected_net_worth_cents"] == 5000, \
        f"after post projected == 5000, got {converged['projected_net_worth_cents']}"


def test_net_worth_signed_multi_account(api):
    """PRD §2.10: "An account's contribution to net worth carries a sign determined by
    its account_type: a DEPOSITORY or INVESTMENT account is an asset and contributes with
    a positive sign, while a CREDIT or LOAN account is a liability and contributes with a
    negated sign."

    Design: Difficulty/combinatorial_formula/net_worth_signed_multi_account_nonlinear
    """
    hh, owner_headers = create_household()
    create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                   opening_balance_cents=20000, institution_name="Bank")
    create_account(hh["id"], owner_headers, account_type="INVESTMENT",
                   opening_balance_cents=30000, institution_name="Broker")
    create_account(hh["id"], owner_headers, account_type="CREDIT",
                   opening_balance_cents=8000, institution_name="Card")

    data = validate_success(api.get_household(hh["id"], owner_headers))
    assert data["net_worth_cents"] == 42000, \
        f"20000 + 30000 - 8000 = 42000, got {data['net_worth_cents']}"


def test_projected_net_worth_signed_multi_account_with_pending(api):
    """PRD §2.10: "the household's projected_net_worth_cents is the same sum but using each
    account's signed available_balance_cents."
    PRD §2.10: "a DEPOSITORY or INVESTMENT account is an asset and contributes with a
    positive sign, while a CREDIT or LOAN account is a liability and contributes with a
    negated sign."

    Design: Difficulty/combinatorial_formula/net_worth_signed_multi_account_nonlinear
    """
    hh, owner_headers = create_household()
    dep = create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                         opening_balance_cents=20000, institution_name="Bank")
    create_account(hh["id"], owner_headers, account_type="INVESTMENT",
                   opening_balance_cents=30000, institution_name="Broker")
    create_account(hh["id"], owner_headers, account_type="LOAN",
                   opening_balance_cents=5000, institution_name="Lender")
    # A pending outflow on the depository account lowers only the projected figure.
    ingest_transaction(dep["id"], amount_cents=-1000, merchant_name="Store")

    data = validate_success(api.get_household(hh["id"], owner_headers))
    # cleared: 20000 + 30000 - 5000 = 45000 (LOAN negated, no posted txns)
    assert data["net_worth_cents"] == 45000, \
        f"20000 + 30000 - 5000 = 45000, got {data['net_worth_cents']}"
    # projected: (20000 - 1000) + 30000 - 5000 = 44000
    assert data["projected_net_worth_cents"] == 44000, \
        f"19000 + 30000 - 5000 = 44000, got {data['projected_net_worth_cents']}"


def test_net_worth_excludes_archived_account(api):
    """PRD §3.2: "On archival the account drops out of the net-worth rollup, and both
    net_worth_cents and projected_net_worth_cents are recomputed."
    PRD §2.10: "Archived accounts (status of ARCHIVED) are excluded from both rollups
    and from aggregation sync."

    Design: Corner/calculations/net_worth_excludes_archived_account
    """
    hh, owner_headers = create_household()
    create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                   opening_balance_cents=6000, institution_name="A")
    acc_b = create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                           opening_balance_cents=4000, institution_name="B")

    validate_success(api.archive_account(hh["id"], acc_b["id"], owner_headers))
    data = validate_success(api.get_household(hh["id"], owner_headers))
    assert data["net_worth_cents"] == 6000, \
        f"archived 4000 account excluded, expected 6000, got {data['net_worth_cents']}"


def test_account_cleared_balance_reconciles_after_post(api):
    """PRD §2.10: "The cleared_balance_cents is the account's opening_balance_cents plus
    the sum of the signed amount_cents of that account's POSTED (and not REMOVED)
    transactions."
    PRD §3.3: "Next the parent account's cleared_balance_cents and available_balance_cents
    are recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_account_balance_reconciles_after_post
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, account_type="DEPOSITORY",
                         opening_balance_cents=10000)
    posted = ingest_and_post(acc["id"], amount_cents=-2500, merchant_name="Store")
    assert posted["status"] == "POSTED"

    data = validate_success(api.get_account(acc["id"], owner_headers))
    assert data["cleared_balance_cents"] == 7500, \
        f"10000 - 2500 = 7500, got {data['cleared_balance_cents']}"
    assert data["available_balance_cents"] == 7500, \
        f"10000 - 2500 = 7500, got {data['available_balance_cents']}"
