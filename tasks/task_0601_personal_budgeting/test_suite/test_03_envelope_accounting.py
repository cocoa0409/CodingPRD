"""Envelope accounting: allocated vs available, allocate recompute, cascade to posture,
goal-abandon conservation, immediate consistency.

Translates Difficulty queue (A) dual_variant_calc (envelope), transitive_cascade,
compensating_invariant (envelope) and Corner queue (B) envelope/consistency claims.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_household, create_account, ingest_transaction, post_transaction,
    ingest_and_post, setup_household_period_category, setup_posted_categorized_txn,
    setup_goal_with_funding, contribute,
)


def test_envelope_allocated_vs_available_diverge(api):
    """PRD §2.11: "The envelope's available_cents is its allocated_cents plus its
    rollover_in_cents, minus its spent_cents, minus the total of active goal contributions
    drawn from it".
    PRD §2.11: "Its spent_cents is the absolute magnitude of outflow spending charged to
    it: the sum of -amount_cents over every transaction whose budget_category_id is this
    category, whose posted_period_id is this category's budget_period_id, whose status is
    POSTED, and whose amount_cents is negative (outflows only)."

    Design: Difficulty/dual_variant_calc/envelope_allocated_vs_available
    """
    ctx = setup_posted_categorized_txn(allocated_cents=10000, amount_cents=-3000)
    cat = ctx["category"]
    data = validate_success(api.get_category(cat["id"], ctx["owner_headers"]))
    assert data["allocated_cents"] == 10000, \
        f"allocated stays 10000, got {data['allocated_cents']}"
    assert data["available_cents"] == 7000, \
        f"10000 - 3000 = 7000, got {data['available_cents']}"
    assert data["spent_cents"] == 3000, \
        f"|-3000| = 3000, got {data['spent_cents']}"


def test_envelope_allocate_then_spend_available_tracks_spent(api):
    """PRD §2.11: "These figures are recomputed whenever a categorized transaction posts,
    on recategorize, on remove, on a goal contribution, on a contribution reversal, and on
    allocation."
    PRD §3.5: "Allocation recomputes that envelope's available_cents and envelope_state,
    the period's total_allocated_cents, and the household posture."

    Design: Difficulty/dual_variant_calc/envelope_allocated_vs_available
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=8000, cat_name="Food", allocated_cents=0)
    # Allocate 8000, then spend 5000; allocated stays 8000, available becomes 3000.
    validate_success(api.allocate_category(
        hh["id"], cat["id"], {"allocated_cents": 8000}, owner_headers))
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    ingest_and_post(acc["id"], amount_cents=-5000, merchant_name="Mart",
                    budget_category_id=cat["id"])

    data = validate_success(api.get_category(cat["id"], owner_headers))
    assert data["allocated_cents"] == 8000, \
        f"allocated unchanged at 8000, got {data['allocated_cents']}"
    assert data["available_cents"] == 3000, \
        f"8000 - 5000 = 3000, got {data['available_cents']}"


def test_allocate_recomputes_available_and_state(api):
    """PRD §3.5: "an owner or member allocates funds to an envelope by setting its
    allocated_cents ... Allocation recomputes that envelope's available_cents and
    envelope_state".
    PRD §2.11: "otherwise it is FUNDED."

    Design: Corner/endpoints/allocate_recomputes_available
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=8000, cat_name="Food", allocated_cents=0)
    resp = api.allocate_category(
        hh["id"], cat["id"], {"allocated_cents": 8000}, owner_headers)
    data = validate_success(resp)
    assert data["allocated_cents"] == 8000
    assert data["available_cents"] == 8000, \
        f"8000 - 0 = 8000, got {data['available_cents']}"
    assert data["envelope_state"] == "FUNDED", \
        f"no activity -> FUNDED, got {data['envelope_state']}"


def test_post_drives_envelope_over_and_posture_overspent(api):
    """PRD §3.3: "Finally the household's posture is recomputed — if the post drives the
    envelope to OVER, the household cascades to OVERSPENT."
    PRD §2.11: "The envelope's envelope_state is OVER when available_cents is below zero".

    Design: Difficulty/transitive_cascade/post_to_envelope_to_posture_depth3
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=10000, cat_name="Food", allocated_cents=10000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    ingest_and_post(acc["id"], amount_cents=-12000, merchant_name="Mart",
                    budget_category_id=cat["id"])

    cat_data = validate_success(api.get_category(cat["id"], owner_headers))
    assert cat_data["available_cents"] == -2000, \
        f"10000 - 12000 = -2000, got {cat_data['available_cents']}"
    assert cat_data["envelope_state"] == "OVER", \
        f"available < 0 -> OVER, got {cat_data['envelope_state']}"
    hh_data = validate_success(api.get_household(hh["id"], owner_headers))
    assert hh_data["posture"] == "OVERSPENT", \
        f"category OVER -> OVERSPENT, got {hh_data['posture']}"


def test_post_envelope_posture_cascade_via_drawn_then_over(api):
    """PRD §2.11: "otherwise it is DRAWN when available_cents is at least zero and there
    has been activity (either spent_cents is greater than zero or contributions against the
    envelope are greater than zero)".
    PRD §2.8: "otherwise it is OVERSPENT if any BudgetCategory in the household's current
    period has an envelope_state of OVER; otherwise it is HEALTHY."

    Design: Difficulty/transitive_cascade/post_to_envelope_to_posture_depth3
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=10000, cat_name="Food", allocated_cents=10000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    # First a -3000 outflow: DRAWN, posture HEALTHY.
    ingest_and_post(acc["id"], amount_cents=-3000, merchant_name="A",
                    budget_category_id=cat["id"])
    drawn = validate_success(api.get_category(cat["id"], owner_headers))
    assert drawn["envelope_state"] == "DRAWN", \
        f"spent>0, available>=0 -> DRAWN, got {drawn['envelope_state']}"
    assert validate_success(api.get_household(hh["id"], owner_headers))["posture"] == "HEALTHY"
    # A further -9000 outflow pushes available negative: OVER -> posture OVERSPENT.
    ingest_and_post(acc["id"], amount_cents=-9000, merchant_name="B",
                    budget_category_id=cat["id"])
    over = validate_success(api.get_category(cat["id"], owner_headers))
    assert over["available_cents"] == -2000, \
        f"10000 - 3000 - 9000 = -2000, got {over['available_cents']}"
    assert over["envelope_state"] == "OVER"
    assert validate_success(api.get_household(hh["id"], owner_headers))["posture"] == "OVERSPENT"


def test_remove_clears_envelope_over_and_posture_healthy(api):
    """PRD §3.3: "Removing a POSTED transaction does more: if it was categorized, its
    outflow is subtracted from the owning envelope's spent_cents and that envelope's
    available_cents and envelope_state are recomputed ... then household posture is
    recomputed, which may carry an envelope out of OVER and the household back to HEALTHY."

    Design: Difficulty/transitive_cascade/remove_to_envelope_to_posture_depth2
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=10000, cat_name="Food", allocated_cents=10000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-12000, merchant_name="Mart",
                             budget_category_id=cat["id"])
    post_transaction(acc["id"], txn["id"])
    # Sanity: now OVER / OVERSPENT.
    assert validate_success(api.get_household(hh["id"], owner_headers))["posture"] == "OVERSPENT"

    from test_helpers import admin_headers
    validate_success(api.remove_transaction(acc["id"], txn["id"], admin_headers()))

    cat_data = validate_success(api.get_category(cat["id"], owner_headers))
    assert cat_data["available_cents"] == 10000, \
        f"outflow removed -> available back to 10000, got {cat_data['available_cents']}"
    assert cat_data["envelope_state"] == "FUNDED", \
        f"no spend -> FUNDED, got {cat_data['envelope_state']}"
    hh_data = validate_success(api.get_household(hh["id"], owner_headers))
    assert hh_data["posture"] == "HEALTHY", \
        f"no OVER category -> HEALTHY, got {hh_data['posture']}"


def test_remove_pending_does_not_affect_envelope_or_posture(api):
    """PRD §3.3: "Removing a PENDING transaction recomputes only the parent account's
    available_balance_cents and the household's projected_net_worth_cents, since a pending
    transaction was only ever in the available figure."

    Design: Difficulty/transitive_cascade/remove_to_envelope_to_posture_depth2
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=10000, cat_name="Food", allocated_cents=10000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-12000, merchant_name="Mart",
                             budget_category_id=cat["id"])
    from test_helpers import admin_headers
    validate_success(api.remove_transaction(acc["id"], txn["id"], admin_headers()))

    cat_data = validate_success(api.get_category(cat["id"], owner_headers))
    assert cat_data["spent_cents"] == 0, \
        f"PENDING never posted -> spent 0, got {cat_data['spent_cents']}"
    assert cat_data["available_cents"] == 10000, \
        f"envelope untouched -> 10000, got {cat_data['available_cents']}"
    hh_data = validate_success(api.get_household(hh["id"], owner_headers))
    assert hh_data["posture"] == "HEALTHY"


def test_goal_abandon_conserves_envelope_available(api):
    """PRD §3.6: "Abandonment reverses every one of the goal's non-reversed contributions:
    each reversal marks that contribution's reversed flag true and credits its amount_cents
    back to the funding envelope's available balance (so the reversed contributions drop out
    of both funded_cents and the envelope's contribution total, conserving the household's
    allocated funds)."

    Design: Difficulty/compensating_invariant/goal_abandon_conserves_envelope_available
    """
    ctx = setup_goal_with_funding(allocated_cents=10000, target_cents=20000,
                                  contribution_cents=4000)
    hh, owner_headers, cat, goal = (
        ctx["household"], ctx["owner_headers"], ctx["category"], ctx["goal"])
    # Forward action lowered available to 6000.
    drawn = validate_success(api.get_category(cat["id"], owner_headers))
    assert drawn["available_cents"] == 6000, \
        f"10000 - 4000 = 6000, got {drawn['available_cents']}"

    abandoned = validate_success(api.abandon_goal(hh["id"], goal["id"], owner_headers))
    assert abandoned["status"] == "ABANDONED"
    assert abandoned["funded_cents"] == 0, \
        f"all contributions reversed -> funded 0, got {abandoned['funded_cents']}"
    restored = validate_success(api.get_category(cat["id"], owner_headers))
    assert restored["available_cents"] == 10000, \
        f"reversal restores available to 10000, got {restored['available_cents']}"


def test_goal_abandon_restores_envelope_state_to_funded(api):
    """PRD §3.6: "The funding category's available_cents and envelope_state are then
    recomputed, and the household posture is recomputed."
    PRD §2.11: "otherwise it is FUNDED."

    Design: Difficulty/compensating_invariant/goal_abandon_conserves_envelope_available
    """
    ctx = setup_goal_with_funding(allocated_cents=10000, target_cents=20000,
                                  contribution_cents=4000)
    hh, owner_headers, cat, goal = (
        ctx["household"], ctx["owner_headers"], ctx["category"], ctx["goal"])
    # Forward action drew the envelope (contributions > 0) -> DRAWN.
    drawn = validate_success(api.get_category(cat["id"], owner_headers))
    assert drawn["envelope_state"] == "DRAWN"

    validate_success(api.abandon_goal(hh["id"], goal["id"], owner_headers))
    restored = validate_success(api.get_category(cat["id"], owner_headers))
    # No spend and no active contributions -> back to FUNDED with full available.
    assert restored["available_cents"] == 10000, \
        f"reversal restores available to 10000, got {restored['available_cents']}"
    assert restored["envelope_state"] == "FUNDED", \
        f"no activity after reversal -> FUNDED, got {restored['envelope_state']}"


def test_txn_post_then_remove_conserves_cleared_balance(api):
    """PRD §2.10: "The cleared_balance_cents is the account's opening_balance_cents plus
    the sum of the signed amount_cents of that account's POSTED (and not REMOVED)
    transactions."
    PRD §3.3: "a transaction may be removed from either PENDING or POSTED, landing in the
    terminal REMOVED state."

    Design: Difficulty/compensating_invariant/txn_post_then_remove_conserves_account_cleared_balance
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    txn = ingest_transaction(acc["id"], amount_cents=-3000, merchant_name="Store")
    post_transaction(acc["id"], txn["id"])
    # Forward action dropped cleared to 7000.
    assert validate_success(api.get_account(acc["id"], owner_headers))["cleared_balance_cents"] == 7000

    from test_helpers import admin_headers
    removed = validate_success(api.remove_transaction(acc["id"], txn["id"], admin_headers()))
    assert removed["status"] == "REMOVED"
    acc_data = validate_success(api.get_account(acc["id"], owner_headers))
    assert acc_data["cleared_balance_cents"] == 10000, \
        f"removed txn excluded -> cleared back to 10000, got {acc_data['cleared_balance_cents']}"


def test_txn_post_then_remove_conserves_net_worth(api):
    """PRD §2.10: "The household's net_worth_cents is the sum, across all accounts whose
    status is LINKED, of each account's signed cleared_balance_cents".
    PRD §3.3: "then the household's net_worth_cents and projected_net_worth_cents are
    recomputed".

    Design: Difficulty/compensating_invariant/txn_post_then_remove_conserves_account_cleared_balance
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    txn = ingest_transaction(acc["id"], amount_cents=-3000, merchant_name="Store")
    post_transaction(acc["id"], txn["id"])
    # Forward action dropped net worth to 7000.
    assert validate_success(api.get_household(hh["id"], owner_headers))["net_worth_cents"] == 7000

    from test_helpers import admin_headers
    validate_success(api.remove_transaction(acc["id"], txn["id"], admin_headers()))
    hh_data = validate_success(api.get_household(hh["id"], owner_headers))
    assert hh_data["net_worth_cents"] == 10000, \
        f"removed txn excluded -> net worth back to 10000, got {hh_data['net_worth_cents']}"


def test_posture_overspent_visible_immediately_after_post(api):
    """PRD §2.5: "derived state is never stale relative to the primary records it
    summarizes."
    PRD §3.3: "Finally the household's posture is recomputed — if the post drives the
    envelope to OVER, the household cascades to OVERSPENT."

    Design: Corner/consistency_model/immediate_visibility_of_posture_after_post
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=1000, cat_name="Food", allocated_cents=1000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    ingest_and_post(acc["id"], amount_cents=-3000, merchant_name="Mart",
                    budget_category_id=cat["id"])
    hh_data = validate_success(api.get_household(hh["id"], owner_headers))
    assert hh_data["posture"] == "OVERSPENT", \
        f"posture flips immediately, got {hh_data['posture']}"
    cat_data = validate_success(api.get_category(cat["id"], owner_headers))
    assert cat_data["envelope_state"] == "OVER"
