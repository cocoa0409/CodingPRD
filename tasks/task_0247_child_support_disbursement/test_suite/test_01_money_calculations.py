"""Dual-variant and combinatorial money calculations.

Translates difficulty queue (A) instances under rules dual_variant_calc and
combinatorial_formula, plus the corner calculation breadth instances.
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    setup_allocation_for_order,
    setup_three_order_obligor,
    create_and_allocate_remittance,
    list_allocations,
    create_disbursement,
    create_remittance,
    create_noncustodial_party,
    create_employer,
)

CW = TEST_USERS["case_worker_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / distribution_split_family_first_vs_state_first
# ---------------------------------------------------------------------------
def test_distribution_split_family_first_pays_all_arrears_to_family(api):
    """PRD §3.7: "Under `FAMILY_FIRST` the state retains nothing — `state_retained_cents`
    is zero — and the `family_amount_cents` is the current collected plus the entire
    arrears collected."

    Design: Difficulty/dual_variant_calc/distribution_split_family_first_vs_state_first
    """
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=20000, gross_remitted_cents=30000,
        assistance_status="NEVER_ASSISTED", with_principal=True)
    # Allocation slice on a FAMILY_FIRST order: cs=20000, interest=0, principal=10000.
    assert allocation["current_support_applied_cents"] == 20000
    assert allocation["principal_applied_cents"] == 10000
    assert allocation["interest_applied_cents"] == 0

    disb = validate_success(api.create_disbursement(
        {"support_order_id": order["id"], "custodial_party_id": cp["id"],
         "allocation_id": allocation["id"]}, FO), 201)
    assert disb["family_amount_cents"] == 30000, (
        f"FAMILY_FIRST family should be current+arrears=30000, got {disb['family_amount_cents']}")
    assert disb["state_retained_cents"] == 0


def test_distribution_split_state_first_retains_assigned_arrears(api):
    """PRD §3.7: "Under `STATE_FIRST` the `state_retained_cents` is the smaller of the
    arrears collected and the order's `assigned_arrears_cents`, and the `family_amount_cents`
    is the current collected plus whatever arrears collection remains after that retention
    (the arrears collected minus the state-retained amount)."

    Design: Difficulty/dual_variant_calc/distribution_split_family_first_vs_state_first
    """
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=20000, gross_remitted_cents=30000,
        assistance_status="CURRENTLY_ASSISTED", with_principal=True,
        assigned_arrears_cents=8000)
    # Same allocation slice as the FAMILY_FIRST case: cs=20000, interest=0, principal=10000.
    assert allocation["current_support_applied_cents"] == 20000
    assert allocation["principal_applied_cents"] == 10000

    disb = validate_success(api.create_disbursement(
        {"support_order_id": order["id"], "custodial_party_id": cp["id"],
         "allocation_id": allocation["id"]}, FO), 201)
    # arrears collected = 10000; state retains min(10000, 8000) = 8000; family = 20000 + 2000.
    assert disb["state_retained_cents"] == 8000, (
        f"STATE_FIRST should retain min(arrears,assigned)=8000, got {disb['state_retained_cents']}")
    assert disb["family_amount_cents"] == 22000, (
        f"STATE_FIRST family should be 20000+(10000-8000)=22000, got {disb['family_amount_cents']}")


# ---------------------------------------------------------------------------
# dual_variant_calc / multi_order_allocation_shortfall_vs_surplus
# ---------------------------------------------------------------------------
def test_multi_order_allocation_shortfall_prorates_current_support_only(api):
    """PRD §3.5: "If the `distributable_cents` is less than or equal to that total, nothing
    reaches arrears: each order's current-support slice is the `distributable_cents` multiplied
    by that order's `current_support_cents` divided by the total, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/multi_order_allocation_shortfall_vs_surplus
    """
    cp, ncp, emp, orders = setup_three_order_obligor(cs_amounts=(50000, 30000, 10000))
    # distributable 50000 <= total current support 90000 -> pure proration.
    create_and_allocate_remittance(emp["id"], ncp["id"],
                                   disposable_earnings_cents=200000,
                                   gross_remitted_cents=50000)
    alloc_a = list_allocations(support_order_id=orders[0]["id"])[0]
    assert alloc_a["current_support_applied_cents"] == 27777
    assert alloc_a["principal_applied_cents"] == 0, "shortfall branch leaves arrears untouched"
    assert alloc_a["interest_applied_cents"] == 0


def test_multi_order_allocation_surplus_cascades_into_principal(api):
    """PRD §3.5: "If instead the `distributable_cents` exceeds the total current support,
    current support is satisfied first on every order and the surplus cascades into arrears."

    Design: Difficulty/dual_variant_calc/multi_order_allocation_shortfall_vs_surplus
    """
    # Single-order obligor cs=50000 with arrears principal 50000 (rolled), no interest.
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=50000, gross_remitted_cents=130000,
        with_principal=True)
    # distributable 130000 > current support 50000 -> cs 50000 then principal 50000.
    assert allocation["current_support_applied_cents"] == 50000
    assert allocation["principal_applied_cents"] == 50000


# ---------------------------------------------------------------------------
# combinatorial_formula / allocation_rounding_remainder_order_pinned
# ---------------------------------------------------------------------------
def test_allocation_rounding_remainder_lands_on_greatest_current_support(api):
    """PRD §3.5: "the leftover remainder (the `distributable_cents` minus the sum of the
    rounded slices) is assigned in full to the order with the greatest `current_support_cents`,
    breaking ties toward the earliest `created_at`."

    Design: Difficulty/combinatorial_formula/allocation_rounding_remainder_order_pinned
    """
    cp, ncp, emp, orders = setup_three_order_obligor(cs_amounts=(50000, 30000, 10000))
    create_and_allocate_remittance(emp["id"], ncp["id"],
                                   disposable_earnings_cents=200000,
                                   gross_remitted_cents=50000)
    a = list_allocations(support_order_id=orders[0]["id"])[0]
    b = list_allocations(support_order_id=orders[1]["id"])[0]
    c = list_allocations(support_order_id=orders[2]["id"])[0]
    # raw HALF_UP slices 27778/16667/5556 sum to 50001 (overshoot 1); -1 lands on A.
    assert a["current_support_applied_cents"] == 27777
    assert b["current_support_applied_cents"] == 16667
    assert c["current_support_applied_cents"] == 5556


def test_allocation_rounded_slices_sum_to_distributable(api):
    """PRD §3.5: "Because per-order rounding can leave the slices summing to a cent or two
    more or less than the distributable amount, the leftover remainder (the `distributable_cents`
    minus the sum of the rounded slices) is assigned in full to the order with the greatest
    `current_support_cents`, breaking ties toward the earliest `created_at`."

    Design: Difficulty/combinatorial_formula/allocation_rounding_remainder_order_pinned
    """
    cp, ncp, emp, orders = setup_three_order_obligor(cs_amounts=(50000, 30000, 10000))
    create_and_allocate_remittance(emp["id"], ncp["id"],
                                   disposable_earnings_cents=200000,
                                   gross_remitted_cents=50000)
    total = sum(
        list_allocations(support_order_id=o["id"])[0]["current_support_applied_cents"]
        for o in orders)
    assert total == 50000, f"per-order slices must sum to distributable 50000, got {total}"


# ---------------------------------------------------------------------------
# Corner: calculations breadth
# ---------------------------------------------------------------------------
def test_ccpa_cap_non_binding_distributable_equals_gross(api):
    """PRD §3.4: "when the gross is at most the cap, the cap is non-binding and
    `distributable_cents` equals `gross_remitted_cents`."

    Design: Corner/calculations/ccpa_cap_non_binding_distributable_equals_gross
    """
    ncp = create_noncustodial_party(ssn_last4="1012")
    emp = create_employer()
    # No second family, no arrears (weeks=0 -> 0.60 tier); cap = 200000*0.60 = 120000.
    rem = validate_success(api.create_remittance(
        {"employer_id": emp["id"], "noncustodial_party_id": ncp["id"],
         "disposable_earnings_cents": 200000, "gross_remitted_cents": 50000}, FO), 201)
    assert rem["ccpa_cap_cents"] == 120000
    assert rem["distributable_cents"] == 50000


def test_interest_accrual_31_days_posts_expected_amount(api):
    """PRD §3.6: "The accrued amount is the `arrears_principal_cents` multiplied by the
    annual rate (the `interest_rate_bps` divided by ten thousand), multiplied by the day
    count, divided by 365, then rounded half-up to whole cents."

    Design: Corner/calculations/interest_accrual_31_days_posts_expected
    """
    api_client.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"}, FO)
    cp, ncp, emp, order = _principal_order(api, current_support_cents=50000)
    api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, FO)  # 31 days
    updated = validate_success(api.accrue_interest(order["id"], FO))
    # round(50000 * 0.10 * 31 / 365) = 425.
    assert updated["interest_balance_cents"] == 425


def test_within_order_waterfall_clears_within_current_support(api):
    """PRD §3.5: "when the amount does not exceed `current_support_due_cents`, interest and
    principal are left untouched."

    Design: Corner/calculations/within_order_waterfall_clears_within_current_support
    """
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=20000, gross_remitted_cents=20000, with_principal=False)
    # distributable 20000 <= current_support_due 20000 -> all to current support.
    assert allocation["current_support_applied_cents"] == 20000
    assert allocation["interest_applied_cents"] == 0
    assert allocation["principal_applied_cents"] == 0


# ---------------------------------------------------------------------------
# helpers local to this file
# ---------------------------------------------------------------------------
def _principal_order(api, current_support_cents):
    """ACTIVE order rolled so arrears_principal_cents == current_support_cents."""
    cp = validate_success(api.create_custodial_party(
        {"full_name": "CP", "state_code": "CA"}, CW), 201)
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP", "ssn_last4": "1013"}, CW), 201)
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": current_support_cents}, CW), 201)
    validate_success(api.activate_support_order(order["id"], CW))
    validate_success(api.post_charge(order["id"], CW))
    order = validate_success(api.get_support_order(order["id"], CW))
    return cp, ncp, None, order
