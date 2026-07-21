"""Subrogation recovery allocation (INDEMNITY_FIRST vs PRO_RATA) and its cascade onto the
claim recovery buckets and the account recovered roll-up.

Translates dual_variant_calc (allocation) and transitive_cascade (recovery -> claim ->
account) difficulty instances plus the pro-rata corner instance.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_claim_with_paid_indemnity, setup_claim_paid_indemnity_and_expense,
    setup_subrogation_at_negotiating, record_recovery, get_claim,
)

CM = TEST_USERS["claims_manager_headers"]


def test_indemnity_first_allocates_to_indemnity_bucket(api):
    """PRD §3.7: "Under `INDEMNITY_FIRST`: the indemnity share is the lesser of the recovery
    amount and `paid_indemnity_cents`, and the expense share is whatever remains."

    Design: Difficulty/dual_variant_calc/subrogation_recovery_prorata_vs_indemnity_first
    """
    env = setup_claim_paid_indemnity_and_expense(api, paid_indemnity=600000, paid_expense=400000,
                                                 account_overrides={"account_code": "DV2"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    sub = setup_subrogation_at_negotiating(api, claim_id, adj, demand_cents=800000)
    recovered = record_recovery(api, claim_id, sub["id"], adj, 500000, "INDEMNITY_FIRST")
    assert recovered["recovered_cents"] == 500000
    assert recovered["allocation_method"] == "INDEMNITY_FIRST"
    claim = get_claim(api, claim_id, adj)
    assert claim["recovered_indemnity_cents"] == 500000
    assert claim["recovered_expense_cents"] == 0


def test_indemnity_first_updates_claim_recovery_and_net(api):
    """PRD §3.7: "The computed indemnity share is added to the claim's
    `recovered_indemnity_cents`, the expense share to `recovered_expense_cents`, and the full
    recovery amount to `recovered_cents`. The claim's `net_incurred_cents` is then recomputed
    and the account roll-up refreshed."

    Design: Difficulty/dual_variant_calc/subrogation_recovery_prorata_vs_indemnity_first
    """
    env = setup_claim_paid_indemnity_and_expense(api, paid_indemnity=600000, paid_expense=400000,
                                                 account_overrides={"account_code": "DV2b"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    sub = setup_subrogation_at_negotiating(api, claim_id, adj, demand_cents=800000)
    record_recovery(api, claim_id, sub["id"], adj, 500000, "INDEMNITY_FIRST")
    claim = get_claim(api, claim_id, adj)
    assert claim["recovered_cents"] == 500000
    # gross = paid_indemnity 600000 + paid_expense 400000 (reserves 0) = 1000000; net = gross - 500000.
    assert claim["net_incurred_cents"] == 500000


def test_pro_rata_splits_recovery_by_paid_ratio(api):
    """PRD §3.7: "otherwise the indemnity share is the recovery amount multiplied by
    `paid_indemnity_cents` divided by the base, rounded half up, and the expense share is the
    remainder (the recovery amount less the indemnity share)."

    Design: Corner/calculations/subrogation_recovered_pro_rata_allocation
    """
    env = setup_claim_paid_indemnity_and_expense(api, paid_indemnity=600000, paid_expense=400000,
                                                 account_overrides={"account_code": "C-PR"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    sub = setup_subrogation_at_negotiating(api, claim_id, adj, demand_cents=800000)
    record_recovery(api, claim_id, sub["id"], adj, 500000, "PRO_RATA")
    claim = get_claim(api, claim_id, adj)
    # 500000 * 600000 / 1000000 = 300000 to indemnity; remainder 200000 to expense.
    assert claim["recovered_indemnity_cents"] == 300000
    assert claim["recovered_expense_cents"] == 200000
    assert claim["recovered_cents"] == 500000


def test_recovery_updates_claim_recovered_and_net(api):
    """PRD §3.7: "The computed indemnity share is added to the claim's
    `recovered_indemnity_cents`, the expense share to `recovered_expense_cents`, and the full
    recovery amount to `recovered_cents`. The claim's `net_incurred_cents` is then recomputed
    and the account roll-up refreshed."

    Design: Difficulty/transitive_cascade/subrogation_recovered_updates_claim_and_account
    """
    env = setup_claim_with_paid_indemnity(api, amount_cents=600000,
                                          account_overrides={"account_code": "TC2"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    sub = setup_subrogation_at_negotiating(api, claim_id, adj, demand_cents=500000)
    record_recovery(api, claim_id, sub["id"], adj, 200000, "INDEMNITY_FIRST")
    claim = get_claim(api, claim_id, adj)
    assert claim["recovered_cents"] == 200000
    # gross = 600000; net = 600000 - 200000 = 400000.
    assert claim["net_incurred_cents"] == 400000


def test_recovery_updates_account_recovered_rollup(api):
    """PRD §3.9: "`gross_incurred_total_cents` is the sum of `gross_incurred_cents` over the
    account's claims whose status is not `CANCELLED`. `recovered_total_cents` is the sum of
    `recovered_cents` over the account's claims whose status is not `CANCELLED`."

    Design: Difficulty/transitive_cascade/subrogation_recovered_updates_claim_and_account
    """
    env = setup_claim_with_paid_indemnity(api, amount_cents=600000,
                                          account_overrides={"account_code": "TC2b"})
    claim_id, adj, account_id = env["claim"]["id"], env["adj_headers"], env["account"]["id"]
    sub = setup_subrogation_at_negotiating(api, claim_id, adj, demand_cents=500000)
    record_recovery(api, claim_id, sub["id"], adj, 200000, "INDEMNITY_FIRST")
    account = validate_success(api.get_client_account(account_id, CM), 200)
    assert account["recovered_total_cents"] == 200000
    assert account["gross_incurred_total_cents"] == 600000
