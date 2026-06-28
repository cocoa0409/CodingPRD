"""Premium-rate, dual-variant claim payout, and surrender/loan calculations.

Translates the dual_variant_calc and combinatorial_formula difficulty rules
(queue A) plus the calculations corner section (queue B).
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    issue_active_policy,
    issue_active_policy_only,
    issue_vested_policy,
    issue_vested_policy_with_loan,
    create_plan,
    create_applicant,
    create_draft_application_with_questionnaire,
    set_clock,
    submit_application,
    issue_policy,
    post_premium,
    claim_under_review,
    file_claim,
    attach_certificate,
    disburse_loan,
)
from test_helpers.api_client import api_client

PA = TEST_USERS["policy_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]


# ===========================================================================
# Difficulty / combinatorial_formula / premium_rate_tiered_age_face_class_mode_a
# ===========================================================================
def test_premium_tobacco_mid_tier_band_a_rounds_once(api):
    """PRD §3.4: "The raw figure is the base monthly rate per $1000 multiplied
    by the number of face units multiplied by the age factor. The loaded figure
    is the raw figure multiplied by one plus the tier load. The final premium is
    the loaded figure multiplied by the class multiplier, rounded half up to
    whole cents."
    PRD §3.3: "rating_class is TOBACCO when the applicant's tobacco_use is true
    and STANDARD otherwise"

    Design: Difficulty/combinatorial_formula/premium_rate_tiered_age_face_class_mode_a
    """
    plan = create_plan()
    # Age 55 on 2026-02-01 (DOB 1970-06-15), tobacco, face 1500000 -> MID tier.
    applicant = create_applicant(full_name="Reba Stone", date_of_birth="1970-06-15", gender="FEMALE", tobacco_use=True)
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1500000)
    set_clock("2026-02-01T00:00:00Z")
    submitted = validate_success(api.submit_application(app["id"], UW))

    assert submitted["rating_class"] == "TOBACCO", submitted
    assert submitted["quoted_monthly_premium_cents"] == 9900, (
        f"Expected 9900 (raw 6000 -> *1.10 MID load -> *1.50 TOBACCO), got "
        f"{submitted['quoted_monthly_premium_cents']}"
    )
    assert submitted["status"] == "APPROVED"


def test_premium_standard_small_tier_band_b_no_load(api):
    """PRD §3.4: "The class multiplier is 1.00 for a STANDARD rating class, 1.50
    for TOBACCO, and 2.00 for SUBSTANDARD. The raw figure is the base monthly
    rate per $1000 multiplied by the number of face units multiplied by the age
    factor."

    Design: Difficulty/combinatorial_formula/premium_rate_tiered_age_face_class_mode_a
    """
    plan = create_plan()
    # Age 65 on 2026-02-01 (DOB 1960-06-15) -> band B (1.5). Face 1000000 SMALL (load 0). STANDARD.
    applicant = create_applicant(full_name="Mabel Crane", date_of_birth="1960-06-15", tobacco_use=False)
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    set_clock("2026-02-01T00:00:00Z")
    submitted = validate_success(api.submit_application(app["id"], UW))

    assert submitted["rating_class"] == "STANDARD", submitted
    # raw = 400 * 10 units * 1.5 band = 6000; *1.0 load *1.0 class = 6000.
    assert submitted["quoted_monthly_premium_cents"] == 6000, submitted["quoted_monthly_premium_cents"]


# ===========================================================================
# Difficulty / dual_variant_calc / claim_payout_graded_vs_full_face_on_claim
# ===========================================================================
def test_graded_natural_death_pays_graded_refund_variant(api):
    """PRD §3.12: "When the death is within the graded variant, payout_basis is
    GRADED_REFUND and the benefit is a refund of premiums paid plus simple
    interest - not the full face."
    PRD §3.12: "the per-payment interest is that payment's amount_cents
    multiplied by the plan's graded_refund_apr multiplied by the day count
    divided by 365, rounded half up to whole cents; and the running refund
    accumulates that payment's amount_cents plus its rounded interest."

    Design: Difficulty/dual_variant_calc/claim_payout_graded_vs_full_face_on_claim
    """
    policy = issue_active_policy_only(face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_mabel")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    set_clock("2026-05-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-05-01T00:00:00Z", manner_of_death="NATURAL")

    assert reviewed["payout_basis"] == "GRADED_REFUND", reviewed
    # 6000 + round(6000*0.10*89/365) = 6000 + round(146.3) = 6000 + 146 = 6146.
    assert reviewed["gross_benefit_cents"] == 6146, reviewed["gross_benefit_cents"]


def test_accidental_death_pays_full_face_variant(api):
    """PRD §3.12: "An accidental death always pays full face regardless of the
    graded window."
    PRD §3.12: "When the death is not within the graded variant, payout_basis is
    FULL_FACE and gross_benefit_cents is the policy's full face_amount_cents -
    the guaranteed full-face variant."

    Design: Difficulty/dual_variant_calc/claim_payout_graded_vs_full_face_on_claim
    """
    policy = issue_active_policy_only(face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_mabel2")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    set_clock("2026-05-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-05-01T00:00:00Z", manner_of_death="ACCIDENTAL", certified_cause="ACCIDENT")

    assert reviewed["payout_basis"] == "FULL_FACE", reviewed
    assert reviewed["gross_benefit_cents"] == 1000000, reviewed["gross_benefit_cents"]


# ===========================================================================
# Difficulty / combinatorial_formula / graded_refund_per_payment_round_then_sum_mode_b
# ===========================================================================
def test_graded_refund_rounds_interest_per_payment_before_summing(api):
    """PRD §3.12: "The rounding order here is pinned and differs from a naive
    sum: interest is computed per payment and rounded before summing, never
    summed then rounded."
    PRD §3.12: "the per-payment interest is that payment's amount_cents
    multiplied by the plan's graded_refund_apr multiplied by the day count
    divided by 365, rounded half up to whole cents; and the running refund
    accumulates that payment's amount_cents plus its rounded interest."

    Design: Difficulty/combinatorial_formula/graded_refund_per_payment_round_then_sum_mode_b
    """
    policy = issue_active_policy_only(face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_cyrus")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    post_premium(policy["id"], 6000, "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z")
    post_premium(policy["id"], 6000, "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z")
    set_clock("2026-08-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-08-01T00:00:00Z", manner_of_death="NATURAL", certificate_number="DC-2")

    assert reviewed["payout_basis"] == "GRADED_REFUND", reviewed
    # 3*6000 + (298+252+201) = 18000 + 751 = 18751.
    assert reviewed["gross_benefit_cents"] == 18751, reviewed["gross_benefit_cents"]


def test_graded_refund_single_payment_interest_rounded(api):
    """PRD §3.12: "the day count is the whole days from that payment's
    posted_date to the claim's date_of_death, floored at zero; the per-payment
    interest is that payment's amount_cents multiplied by the plan's
    graded_refund_apr multiplied by the day count divided by 365, rounded half
    up to whole cents"

    Design: Difficulty/combinatorial_formula/graded_refund_per_payment_round_then_sum_mode_b
    """
    policy = issue_active_policy_only(face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_cyrus2")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    set_clock("2026-05-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-05-01T00:00:00Z", manner_of_death="NATURAL", certificate_number="DC-S")

    # 89 days from 2026-02-01 to 2026-05-01: 6000 + round(6000*0.10*89/365)=6000+146=6146.
    assert reviewed["payout_basis"] == "GRADED_REFUND", reviewed
    assert reviewed["gross_benefit_cents"] == 6146, reviewed["gross_benefit_cents"]


# ===========================================================================
# Difficulty / dual_variant_calc / surrender_gross_vs_net_cash_value_on_policy
# Difficulty / combinatorial_formula / net_surrender_charge_keyed_on_gross_mode_c
# ===========================================================================
def test_surrender_gross_cash_value_distinct_from_net_proceeds(api):
    """PRD §3.10: "The displayed gross_cash_value_cents on the policy is the
    step-one figure and ignores both the surrender charge and the loan balance;
    the surrender proceeds subtract both."
    PRD §3.9: "it is the plan's cash_value_factor_per_1000_cents multiplied by
    the number of $1000 face units (face amount in cents divided by 100000)
    multiplied by the vested years, where vested years is the larger of zero and
    the whole policy-years in force minus cash_value_vesting_years."

    Design: Difficulty/dual_variant_calc/surrender_gross_vs_net_cash_value_on_policy
    """
    # face 1000000 (10 units), 5 whole years, vested years 2 -> gross = 1500*10*2 = 30000.
    policy = issue_vested_policy(face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_otis")
    assert policy["gross_cash_value_cents"] == 30000, policy["gross_cash_value_cents"]

    surrendered = validate_success(api.surrender_policy(policy["id"], PA))
    assert surrendered["coverage_status"] == "SURRENDERED", surrendered


def test_surrender_net_proceeds_subtract_charge_from_gross(api):
    """PRD §3.10: "The displayed gross_cash_value_cents on the policy is the
    step-one figure and ignores both the surrender charge and the loan balance;
    the surrender proceeds subtract both."
    PRD §3.10: "the charge in cents is the gross cash value multiplied by that
    percentage rounded half up to whole cents, and the after-charge figure is
    the gross cash value minus the charge."

    Design: Difficulty/dual_variant_calc/surrender_gross_vs_net_cash_value_on_policy
    """
    policy = issue_vested_policy(simple=False, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_otis2")
    assert policy["gross_cash_value_cents"] == 30000, policy["gross_cash_value_cents"]

    validate_success(api.surrender_policy(policy["id"], PA))
    # Net proceeds (27000) are distinct from the displayed gross (30000).
    entries = validate_success(api.list_ledger_entries(PA, params={"policy_id": policy["id"], "entry_type": "BENEFIT_PAID"}))
    benefit_entries = [e for e in entries if e["entry_type"] == "BENEFIT_PAID"]
    assert benefit_entries, "a BENEFIT_PAID ledger entry must be appended on surrender"
    assert any(abs(e["amount_cents"]) == 27000 for e in benefit_entries), (
        f"net proceeds 27000 must differ from gross 30000, got {[e['amount_cents'] for e in benefit_entries]}"
    )


def test_surrender_charge_keyed_on_gross_then_applied(api):
    """PRD §3.10: "the applicable charge percentage is the charge_pct of the
    surrender-charge tier whose inclusive min_gross_cents-to-max_gross_cents
    range contains the gross cash value, the charge in cents is the gross cash
    value multiplied by that percentage rounded half up to whole cents, and the
    after-charge figure is the gross cash value minus the charge."
    PRD §2.5: "Each entry records a signed amount_cents (credits positive, debits
    negative), the balance_after_cents net cash value immediately after the
    event"

    Design: Difficulty/combinatorial_formula/net_surrender_charge_keyed_on_gross_mode_c
    """
    # gross 30000 -> tier [200001..99999999] charge 0.0... but the canonical plan's
    # surrender tiers are [0..50000 0.10]; 30000 selects 10% -> charge 3000 -> 27000.
    policy = issue_vested_policy(simple=False, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_pearl")
    assert policy["gross_cash_value_cents"] == 30000, policy["gross_cash_value_cents"]

    surrendered = validate_success(api.surrender_policy(policy["id"], PA))
    assert surrendered["coverage_status"] == "SURRENDERED", surrendered
    # The BENEFIT_PAID ledger entry records the net surrender proceeds (27000).
    entries = validate_success(api.list_ledger_entries(PA, params={"policy_id": policy["id"], "entry_type": "BENEFIT_PAID"}))
    benefit_entries = [e for e in entries if e["entry_type"] == "BENEFIT_PAID"]
    assert benefit_entries, "a BENEFIT_PAID ledger entry must be appended on surrender"
    assert any(abs(e["amount_cents"]) == 27000 for e in benefit_entries), (
        f"net surrender proceeds 27000 (gross 30000 - 10% gross-keyed charge 3000), got "
        f"{[e['amount_cents'] for e in benefit_entries]}"
    )


def test_surrender_gross_unaffected_by_charge_order_pinned(api):
    """PRD §3.10: "The order is pinned: resolve the gross value first, select the
    tier by that gross value, then apply the charge - never select the tier from
    a post-charge figure."
    PRD §3.10: "The displayed gross_cash_value_cents on the policy is the
    step-one figure and ignores both the surrender charge and the loan balance"

    Design: Difficulty/combinatorial_formula/net_surrender_charge_keyed_on_gross_mode_c
    """
    policy = issue_vested_policy(simple=False, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_pearl2")
    # The displayed gross is the order-pinned step-one figure (30000), not a
    # post-charge value; the 10% tier is selected from this gross.
    assert policy["gross_cash_value_cents"] == 30000, policy["gross_cash_value_cents"]

    validate_success(api.surrender_policy(policy["id"], PA))
    entries = validate_success(api.list_ledger_entries(PA, params={"policy_id": policy["id"], "entry_type": "BENEFIT_PAID"}))
    benefit_entries = [e for e in entries if e["entry_type"] == "BENEFIT_PAID"]
    assert benefit_entries, "a BENEFIT_PAID ledger entry must be appended on surrender"
    # 30000 selects the 10% tier (gross-keyed); charge 3000; proceeds 27000.
    assert any(abs(e["amount_cents"]) == 27000 for e in benefit_entries), (
        f"order-pinned proceeds 27000 expected, got {[e['amount_cents'] for e in benefit_entries]}"
    )


# ===========================================================================
# Corner / calculations / loan_interest_simple_accrual_correct
# ===========================================================================
def test_loan_interest_simple_accrual(api):
    """PRD §3.9: "The accrued_interest_cents is the outstanding principal
    multiplied by loan_apr multiplied by the day count divided by 365, rounded
    half up to whole cents."

    Design: Corner/calculations/loan_interest_simple_accrual_correct
    """
    policy = issue_vested_policy(simple=True, face_cents=1000000, vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_lo")
    loan = disburse_loan(policy["id"], principal_cents=20000)
    set_clock("2031-05-02T00:00:00Z")  # 90 days later
    fresh = validate_success(api.get_policy_loan(loan["id"], PA))

    # round(20000 * 0.08 * 90 / 365) = round(394.5) = 395.
    assert fresh["accrued_interest_cents"] == 395, fresh["accrued_interest_cents"]


# ===========================================================================
# Corner / calculations / death_benefit_split_funeral_home_off_the_top
# ===========================================================================
def test_death_benefit_funeral_home_off_the_top_then_split(api):
    """PRD §3.14: "The amount paid to funeral homes is the lesser of the pool and
    the sum of assigned_benefit_cents across all ACTIVE funeral-home assignments,
    and the residual is the pool minus that funeral-home payment."
    PRD §3.14: "Each beneficiary's share is the residual multiplied by that
    beneficiary's share_pct divided by 100, rounded down to whole cents."

    Design: Corner/calculations/death_benefit_split_funeral_home_off_the_top
    """
    policy = issue_active_policy_only(simple=True, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_sp")
    api_client.create_funeral_home_assignment(policy["id"], {"funeral_home_name": "Restful Pines", "assigned_benefit_cents": 300000}, PA)
    api_client.create_beneficiary(policy["id"], {"full_name": "Heir One", "relationship": "CHILD", "share_pct": 50}, PA)
    api_client.create_beneficiary(policy["id"], {"full_name": "Heir Two", "relationship": "CHILD", "share_pct": 50}, PA)
    set_clock("2031-03-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2031-03-01T00:00:00Z", manner_of_death="ACCIDENTAL", certified_cause="ACCIDENT", certificate_number="DC-SP")
    assert reviewed["payout_basis"] == "FULL_FACE", reviewed

    approved = validate_success(api.approve_claim(reviewed["id"], CE))
    # No loan -> net payout == full face 1000000.
    assert approved["payout_basis"] == "FULL_FACE", approved
    assert approved["net_payout_cents"] == 1000000, approved["net_payout_cents"]
