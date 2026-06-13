"""Overdue-fine, replacement-charge, and account-summary calculations.

Queue A: dual_variant_calc, combinatorial_formula, boundary_precision_check
(grace edge). Queue B: fine_free short-circuit, account-summary input filtering.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_patron_headers, TEST_USERS,
    setup_active_loan, setup_branch_patron_title_copy, create_loan,
    list_unpaid_fines, get_only_unpaid_fine, set_clock,
    create_branch, create_patron, create_title, create_copy,
)

LIBRARIAN = TEST_USERS["librarian_headers"]


# =========================================================================
# Queue A — dual_variant_calc
# =========================================================================
def test_overdue_estimate_differs_from_final_on_same_loan(api):
    """PRD §3.3: "Because it projects rather than measures, the estimate and the
    eventual final fine diverge for the same loan whenever the projected date
    differs from the actual return."
    PRD §3.3: "`estimate_cents` is `chargeable_days` multiplied by the branch's
    `daily_fine_cents`, capped at `max_fine_cents`, and forced to zero entirely
    when the branch is fine-free."
    PRD §3.4: "the raw fine is `chargeable_days` multiplied by `daily_fine_cents`,
    and the assessed fine is the smaller of that raw amount and `max_fine_cents`."

    Design: Difficulty/dual_variant_calc/overdue_fine_estimate_vs_final_diverge_on_loan
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"fine_free": False, "daily_fine_cents": 25,
                          "max_fine_cents": 1000, "grace_days": 1, "loan_period_days": 7,
                          "block_threshold_cents": 1000},
        isbn="9780000000001", clock="2026-06-01T00:00:00Z")
    # due_date = 2026-06-08. Estimate projected to 2026-06-13 = 5 days overdue,
    # chargeable 4, 4*25 = 100.
    est = validate_success(api.fine_estimate(
        loan["id"], LIBRARIAN, params={"projected_return": "2026-06-13T00:00:00Z"}), 200)
    assert est["estimate_cents"] == 100, f"expected 100, got {est['estimate_cents']}"

    # Final at actual return 2026-06-15 = 7 days overdue, chargeable 6, 6*25 = 150.
    set_clock("2026-06-15T00:00:00Z")
    final = validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    assert final["accrued_fine_cents"] == 150, f"expected 150, got {final['accrued_fine_cents']}"
    assert est["estimate_cents"] != final["accrued_fine_cents"]


def test_replacement_charge_depreciated_vs_default_diverge(api):
    """PRD §3.5: "The depreciated item value in cents is the title's
    `default_replacement_cents` multiplied by one minus that depreciation
    fraction, multiplied by the copy's `condition_factor`, with that product
    rounded half up to whole cents."
    PRD §3.5: "When `flat_replacement` is true, the default variant is used:
    depreciation and `condition_factor` are ignored entirely, the item-value
    component is simply the title's `default_replacement_cents`, the processing
    fee is computed exactly as above and rounded on its own, and the two are then
    summed."

    Design: Difficulty/dual_variant_calc/replacement_charge_depreciated_vs_default_diverge_on_copy
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Pat Two")
    title = create_title(branch["id"], "9780000000002", title_text="Lost Book",
                         default_replacement_cents=3000)
    # age 365 days -> 1.0yr -> 10% depreciation, condition_factor 1.0.
    copy_dep = create_copy(title["id"], branch["id"], "BC-D",
                           acquired_on="2025-06-01T00:00:00Z", condition_factor=1.0)
    copy_flat = create_copy(title["id"], branch["id"], "BC-F",
                            acquired_on="2025-06-01T00:00:00Z", condition_factor=1.0)
    loan_dep = create_loan(copy_dep["id"], patron["id"])
    loan_flat = create_loan(copy_flat["id"], patron["id"])

    api.declare_lost(loan_dep["id"], LIBRARIAN, {})
    api.declare_lost(loan_flat["id"], LIBRARIAN, {"flat_replacement": True})

    fines = {f["loan_id"]: f for f in list_unpaid_fines(patron["id"])}
    # depreciated: round(3000*0.90*1.0)=2700 + round(300)=300 -> 3000
    assert fines[loan_dep["id"]]["amount_cents"] == 3000
    # default flat: 3000 + 300 -> 3300
    assert fines[loan_flat["id"]]["amount_cents"] == 3300
    assert fines[loan_dep["id"]]["amount_cents"] != fines[loan_flat["id"]]["amount_cents"]


# =========================================================================
# Queue A — combinatorial_formula
# =========================================================================
def test_overdue_fine_capped_at_max_fine(api):
    """PRD §3.4: "the raw fine is `chargeable_days` multiplied by `daily_fine_cents`,
    and the assessed fine is the smaller of that raw amount and `max_fine_cents`."
    PRD §3.4: "`chargeable_days` is `overdue_days` minus the branch's `grace_days`
    (never below zero, so any day index up to and including `grace_days` is free
    and only day indices beyond it are charged)".

    Design: Difficulty/combinatorial_formula/overdue_fine_nested_min_max_with_grace_and_cap
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"daily_fine_cents": 25, "max_fine_cents": 1000,
                          "grace_days": 1, "loan_period_days": 7},
        isbn="9780000000003", clock="2026-06-01T00:00:00Z")
    # due 2026-06-08; return 2026-09-16 = 100 overdue days, chargeable 99,
    # 99*25 = 2475 capped to 1000.
    set_clock("2026-09-16T00:00:00Z")
    final = validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    assert final["accrued_fine_cents"] == 1000, f"expected cap 1000, got {final['accrued_fine_cents']}"


def test_replacement_charge_rounds_each_component_then_sums(api):
    """PRD §3.5: "The replacement charge is built from two independently rounded
    components that are summed only after each is rounded — the order is pinned,
    and summing before rounding is wrong."
    PRD §3.5: "Depreciation is that age in years multiplied by the annual
    depreciation rate of ten percent, but never more than the cap of eighty
    percent."

    Design: Difficulty/combinatorial_formula/replacement_charge_round_each_component_then_sum
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Round Pat")
    title = create_title(branch["id"], "9780000000004", title_text="Round Book",
                         default_replacement_cents=5000)
    # age 730 days -> 2.0yr -> 20% depreciation, condition_factor 0.5.
    copy = create_copy(title["id"], branch["id"], "BC-R",
                       acquired_on="2024-06-01T00:00:00Z", condition_factor=0.5)
    loan = create_loan(copy["id"], patron["id"])
    validate_success(api.declare_lost(loan["id"], LIBRARIAN, {}), 200)
    fine = get_only_unpaid_fine(patron["id"])
    # item round(5000*0.80*0.5)=2000 + processing round(5000*0.10)=500 -> 2500
    assert fine["amount_cents"] == 2500, f"expected 2500, got {fine['amount_cents']}"


def test_account_summary_waiver_tier_evaluation_order(api):
    """PRD §3.1: "First, `raw_total_cents` is computed as the sum of `amount_cents`
    over the patron's fines whose `settlement_status` is `UNPAID`".
    PRD §3.1: "if `raw_total_cents` is at least 2000 cents, `waiver_cents` is set
    to a goodwill waiver of 200 cents; otherwise `waiver_cents` is zero."
    PRD §3.1: "`net_owed_cents` is the raw total minus the waiver, floored at zero
    so it is never negative."

    Design: Difficulty/combinatorial_formula/account_balance_waiver_tier_evaluation_order
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Acct Pat")
    title = create_title(branch["id"], "9780000000005", title_text="Acct Book",
                         default_replacement_cents=2500)
    copy = create_copy(title["id"], branch["id"], "BC-A1",
                       acquired_on="2026-06-01T00:00:00Z", condition_factor=1.0)
    loan = create_loan(copy["id"], patron["id"])
    api.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True})
    # LOST flat: item 2500 + processing round(2500*0.10)=250 -> 2750 raw.
    summary = validate_success(api.get_account_summary(patron["id"], LIBRARIAN), 200)
    assert summary["raw_total_cents"] == 2750, f"raw {summary['raw_total_cents']}"
    assert summary["waiver_cents"] == 200, "raw 2750 >= goodwill tier 2000"
    assert summary["net_owed_cents"] == 2550, f"net {summary['net_owed_cents']}"


# =========================================================================
# Queue A — boundary_precision_check (grace edge)
# =========================================================================
@pytest.mark.parametrize("return_iso,overdue_days,expected_fine", [
    ("2026-06-09T00:00:00Z", 1, 0),    # 1 overdue day == grace_days -> free
    ("2026-06-10T00:00:00Z", 2, 25),   # 2 overdue days == grace_days+1 -> 1 charged day
])
def test_overdue_grace_boundary_day_index(api, return_iso, overdue_days, expected_fine):
    """PRD §3.4: "`chargeable_days` is `overdue_days` minus the branch's `grace_days`
    (never below zero, so any day index up to and including `grace_days` is free
    and only day indices beyond it are charged), the raw fine is `chargeable_days`
    multiplied by `daily_fine_cents`".

    Design: Difficulty/boundary_precision_check/overdue_grace_boundary_day_index
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"daily_fine_cents": 25, "grace_days": 1, "loan_period_days": 7,
                          "max_fine_cents": 1000},
        isbn="9780000000011", clock="2026-06-01T00:00:00Z")
    # due 2026-06-08.
    set_clock(return_iso)
    final = validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    assert final["accrued_fine_cents"] == expected_fine, (
        f"{overdue_days} overdue days -> expected {expected_fine}, "
        f"got {final['accrued_fine_cents']}")


# =========================================================================
# Queue B — calculations
# =========================================================================
def test_fine_free_branch_assesses_zero_overdue(api):
    """PRD §3.1: "A fine-free branch still records overdue loans as `OVERDUE` and
    still blocks on other fine types, but it assesses zero money for lateness."
    PRD §3.4: "if the branch is fine-free it is zero".

    Design: Corner/calculations/fine_free_branch_assesses_zero_overdue_fine
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"fine_free": True, "loan_period_days": 7},
        isbn="9789999999999", clock="2026-06-01T00:00:00Z")
    # due 2026-06-08; return 2026-07-08 (30 days late).
    set_clock("2026-07-08T00:00:00Z")
    final = validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    assert final["accrued_fine_cents"] == 0, "fine-free branch assesses zero"
    assert list_unpaid_fines(patron["id"]) == [], "no OVERDUE Fine created"


def test_account_summary_excludes_settled_fines(api):
    """PRD §3.1: "fines that are `PAID` or `WAIVED` are excluded entirely, so
    settling a fine can change the result and even the tier below."

    Design: Corner/calculations/account_summary_excludes_settled_fines
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Excl Pat")
    title = create_title(branch["id"], "9780000000020", title_text="Excl Book",
                         default_replacement_cents=1500)
    c1 = create_copy(title["id"], branch["id"], "BC-E1",
                     acquired_on="2026-06-01T00:00:00Z", condition_factor=1.0)
    c2 = create_copy(title["id"], branch["id"], "BC-E2",
                     acquired_on="2026-06-01T00:00:00Z", condition_factor=1.0)
    ln1 = create_loan(c1["id"], patron["id"])
    ln2 = create_loan(c2["id"], patron["id"])
    # Each LOST flat: 1500 + round(150) = 1650.
    api.declare_lost(ln1["id"], LIBRARIAN, {"flat_replacement": True})
    api.declare_lost(ln2["id"], LIBRARIAN, {"flat_replacement": True})
    fine1 = list_unpaid_fines(patron["id"])[0]
    api.pay_fine(fine1["id"], LIBRARIAN)

    summary = validate_success(api.get_account_summary(patron["id"], LIBRARIAN), 200)
    assert summary["raw_total_cents"] == 1650, "only remaining UNPAID fine counts"
    assert summary["waiver_cents"] == 0, "1650 < goodwill tier 2000"
    assert summary["net_owed_cents"] == 1650
