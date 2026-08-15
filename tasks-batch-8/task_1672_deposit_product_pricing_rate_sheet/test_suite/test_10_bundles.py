"""Relationship bundles: combined balance, bonus stacking under the cap, and
enrollment lifecycle reconciliation (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_bundle,
    create_effective_sheet,
    create_enrollment,
    create_product,
    open_account,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BANKER = TEST_USERS["banker_headers"]
ADMIN = TEST_USERS["admin_headers"]

# Tier rates respect the product's 180 bp cap (PRD §3.1: every tier rate must
# be at most the cap) while blending, at a 7,500,000-cent balance, to the same
# 163 bp: (2,500,000*150 + 5,000,000*170) / 7,500,000 = 163.33... -> 163.
STACK_TIERS = [tier(0, 0, 2_500_000, 150), tier(1, 2_500_000, 10_000_000, 170),
               tier(2, 10_000_000, -1, 175)]


def _stack_scenario(api):
    """Customer C9 holds 7,500,000 in a MONEY_MARKET product (MARGINAL, cap
    180) and 5,000,000 in a SAVINGS product (single-tier 100 bp); bundle
    PREMIER pays 25 bp on MONEY_MARKET for a combined 10,000,000+ across both
    classes."""
    p_mma = create_product(product_code="MMA9", product_class="MONEY_MARKET",
                           term_months=0, tier_application="MARGINAL", rate_cap_bp=180)
    create_effective_sheet(product_id=p_mma["id"], effective_date="2026-08-15",
                           tiers=STACK_TIERS)
    p_sav = create_product(product_code="SAV3", product_class="SAVINGS", term_months=0,
                           tier_application="WHOLE_BALANCE", rate_cap_bp=500)
    create_effective_sheet(product_id=p_sav["id"], effective_date="2026-09-01",
                           tiers=single_tier(100))
    a_mma = open_account(p_mma["id"], opening_balance_cents=7_500_000, customer_ref="C9")
    a_sav = open_account(p_sav["id"], opening_balance_cents=5_000_000, customer_ref="C9")
    bundle = create_bundle(bundle_code="PREMIER", bonus_bp=25,
                           min_combined_balance_cents=10_000_000,
                           required_product_classes=["MONEY_MARKET", "SAVINGS"],
                           eligible_product_classes=["MONEY_MARKET"])
    enrollment = create_enrollment(bundle["id"], "C9")
    return a_mma, a_sav, bundle, enrollment


def test_bundle_bonus_stacks_and_cap_clamps(api, banker_headers):
    """PRD §3.7: "The combined relationship balance for a customer and bundle
    is the sum of `balance_cents` over that customer's accounts whose
    lifecycle is `OPEN` and whose product class is among the bundle's
    `required_product_classes` — a customer holding no open balances in the
    required classes simply sums to zero."
    PRD §3.5: "Third, the cap: `current_rate_bp` is the lesser of the
    product's `rate_cap_bp` and the base plus bonus."

    Design: Difficulty/combinatorial_formula/effective_rate_stacks_bundle_bonus_under_cap
    """
    a_mma, _, _, enrollment = _stack_scenario(api)
    assert enrollment["qualifying_balance_cents"] == 12_500_000

    quote = validate_success(api.get_rate_quote(a_mma["id"], banker_headers))
    assert quote["base_rate_bp"] == 163       # MARGINAL blend at 7,500,000
    assert quote["bundle_bonus_bp"] == 25     # enrolled and qualified
    assert quote["current_rate_bp"] == 180    # min(cap 180, 163 + 25)
    assert quote["cap_applied"] is True


def test_bundle_bonus_skips_ineligible_product_class(api, banker_headers):
    """PRD §3.5: "Second, the bundle bonus: `bonus_bp` applies only when
    `rate_source` is `SHEET` and a qualifying `ENROLLED` enrollment exists for
    the customer (§3.7) — the bonus never stacks on `PROMO` or `EXCEPTION`
    rates, and is otherwise zero."
    PRD §3.7: "the `eligible_product_classes` the bonus actually applies to."

    Design: Difficulty/combinatorial_formula/effective_rate_stacks_bundle_bonus_under_cap
    """
    _, a_sav, _, _ = _stack_scenario(api)
    quote = validate_success(api.get_rate_quote(a_sav["id"], banker_headers))
    # SAVINGS is a required (balance-counting) class but not an eligible
    # (bonus-receiving) one.
    assert quote["bundle_bonus_bp"] == 0
    assert quote["base_rate_bp"] == 100
    assert quote["current_rate_bp"] == 100


def _accrual_threshold_scenario(api):
    """Customer C7's MONEY_MARKET account holds exactly 9,999,999 cents and
    has accrued 31 days of unposted interest by 2026-09-15 — enough milli-
    cents that counting them would cross the bundle's 10,000,000 threshold."""
    product = create_product(product_code="MMA7", product_class="MONEY_MARKET",
                             term_months=0, tier_application="MARGINAL", rate_cap_bp=500)
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(400))
    account = open_account(product["id"], opening_balance_cents=9_999_999,
                           customer_ref="C7")
    set_clock("2026-09-15")
    bundle = create_bundle(bundle_code="B2", bonus_bp=25,
                           min_combined_balance_cents=10_000_000,
                           required_product_classes=["MONEY_MARKET"],
                           eligible_product_classes=["MONEY_MARKET"])
    return account, bundle


def test_combined_balance_uses_posted_balance_only(api, admin_headers):
    """PRD §3.7: "The sum reads posted balances only: `unposted_accrual_milli`
    and `posted_interest_cents` never feed it, which keeps the evaluation
    order acyclic even though rates, bonuses, balances, and accruals all
    interrelate."
    PRD §3.7: "Enrolling a customer — the `OperationsAdmin` supplies
    `bundle_id` and `customer_ref` — creates a CustomerBundleEnrollment in
    `ENROLLED` status and computes `qualifying_balance_cents` from the
    combined relationship balance at that moment."

    Design: Difficulty/combinatorial_formula/combined_balance_excludes_unposted_accrual
    """
    account, bundle = _accrual_threshold_scenario(api)
    # 31 days at floor(9,999,999 * 400 / 3,650) = 1,095,890 milli-cents.
    enriched = validate_success(api.get_deposit_account(account["id"], BANKER))
    assert enriched["unposted_accrual_milli"] == 33_972_590

    enrollment = create_enrollment(bundle["id"], "C7")
    # Only the posted 9,999,999 counts: the accrual (about 33,972 cents) would
    # have carried the total over 10,000,000.
    assert enrollment["qualifying_balance_cents"] == 9_999_999


def test_combined_balance_below_threshold_keeps_bonus_zero(api, banker_headers):
    """PRD §3.7: "When the qualifying balance reaches the bundle's
    `min_combined_balance_cents`, the bonus is applied to the customer's
    eligible accounts: every `OPEN` account of that customer whose product
    class is in `eligible_product_classes` takes `bundle_bonus_bp`, recomputes
    its `current_rate_bp`, and bumps its version. When the balance falls
    short, the bonus stays zero."

    Design: Difficulty/combinatorial_formula/combined_balance_excludes_unposted_accrual
    """
    account, bundle = _accrual_threshold_scenario(api)
    create_enrollment(bundle["id"], "C7")
    quote = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote["bundle_bonus_bp"] == 0     # 9,999,999 < 10,000,000
    assert quote["base_rate_bp"] == 400
    assert quote["current_rate_bp"] == 400


def test_enrollment_suspend_reinstate_reconciles_bonus(api, banker_headers):
    """PRD §3.7: "`SUSPEND` moves `ENROLLED → SUSPENDED` and strips the bonus:
    all eligible `OPEN` accounts of the customer have `bundle_bonus_bp`
    zeroed, rates recomputed, and versions bumped. `REINSTATE` moves
    `SUSPENDED → ENROLLED`, recomputes `qualifying_balance_cents`, and
    re-applies the bonus to eligible `OPEN` accounts only when the refreshed
    balance reaches the minimum — otherwise the bonus remains zero."

    Design: Corner/complexity_layers/enrollment_suspend_reinstate_reconciles_bonus
    """
    product = create_product(product_code="BR", product_class="MONEY_MARKET",
                             term_months=0, tier_application="MARGINAL", rate_cap_bp=500)
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(400))
    account = open_account(product["id"], opening_balance_cents=2_000_000,
                           customer_ref="CBR")
    bundle = create_bundle(bundle_code="BBR", bonus_bp=25,
                           min_combined_balance_cents=1_000_000,
                           required_product_classes=["MONEY_MARKET"],
                           eligible_product_classes=["MONEY_MARKET"])
    enrollment = create_enrollment(bundle["id"], "CBR")

    quote0 = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote0["bundle_bonus_bp"] == 25
    assert quote0["current_rate_bp"] == 425

    suspended = validate_success(api.transition_bundle_enrollment(
        enrollment["id"], {"action": "SUSPEND"}, ADMIN))
    assert suspended["status"] == "SUSPENDED"
    quote1 = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote1["bundle_bonus_bp"] == 0
    assert quote1["current_rate_bp"] == 400

    reinstated = validate_success(api.transition_bundle_enrollment(
        enrollment["id"], {"action": "REINSTATE"}, ADMIN))
    assert reinstated["status"] == "ENROLLED"
    quote2 = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote2["bundle_bonus_bp"] == 25
    assert quote2["current_rate_bp"] == 425


def test_enrollment_suspend_from_exited_returns_invalid_state(api, admin_headers):
    """PRD §3.7: "A transition attempted from an incompatible state —
    suspending an `EXITED` enrollment, say — is rejected with
    `ERR_ENROLLMENT_INVALID_STATE`."
    PRD §3.7: "`EXIT` moves either `ENROLLED` or `SUSPENDED` to the terminal
    `EXITED`: from `ENROLLED` the bonus is removed from eligible `OPEN`
    accounts with recomputation and version bumps; from `SUSPENDED` there is
    no bonus left to remove, so nothing else changes."

    Design: Corner/state_machines/enrollment_suspend_from_exited_returns_invalid_state
    """
    bundle = create_bundle(bundle_code="BIV", bonus_bp=25,
                           min_combined_balance_cents=0,
                           required_product_classes=["SAVINGS"],
                           eligible_product_classes=["SAVINGS"])
    enrollment = create_enrollment(bundle["id"], "CNO")
    exited = validate_success(api.transition_bundle_enrollment(
        enrollment["id"], {"action": "EXIT"}, admin_headers))
    assert exited["status"] == "EXITED"

    resp = api.transition_bundle_enrollment(enrollment["id"], {"action": "SUSPEND"},
                                            admin_headers)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE, 409)
