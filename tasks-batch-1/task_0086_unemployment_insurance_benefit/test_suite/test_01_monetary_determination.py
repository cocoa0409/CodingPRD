"""Monetary determination: base-period selection (STANDARD vs ALTERNATE),
weekly/maximum benefit derivation, denial, and disputed-wage exclusion."""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_eligible_claim, make_denied_determination,
    create_employer, create_claimant, add_wage_record,
    create_draft_claim, submit_claim, issue_monetary_determination,
    assert_claim, assert_determination,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]


def _build_and_determine(wages, filed_date="2026-04-05"):
    """Register employer+claimant, file wages, submit, issue MONETARY determination.
    Returns (claim_after, determination)."""
    employer = create_employer()
    claimant = create_claimant()
    for quarter, cents in wages:
        add_wage_record(claimant["id"], employer["id"], quarter, cents)
    claim = create_draft_claim(claimant["id"], filed_date)
    submit_claim(claim["id"], claimant["id"])
    det = issue_monetary_determination(claim["id"])
    claim_after = get_success_data(api_client.get_claim(claim["id"], ADJ))
    return claim_after, det


# ── Difficulty: dual_variant_calc / base_period_standard_vs_alternate_diverge ──

def test_alternate_base_period_selected_when_standard_fails(api):
    """PRD §3.2: "the system tries the standard base period first, and if it
    qualifies, that method is selected and the alternate is never evaluated for
    selection; only if the standard set fails is the alternate set tested; if the
    alternate qualifies, it is selected."
    PRD §3.2: "The standard base period is the first four of those five — that is,
    the five most recent completed quarters with the single most recent one
    dropped. The alternate base period is the four most recent completed quarters
    — the same window of five with its oldest dropped."

    Design: Difficulty/dual_variant_calc/base_period_standard_vs_alternate_diverge
    """
    # Quarters 2025-Q1..2026-Q1 completed before 2026-Q2 (filed 2026-04-05).
    # STANDARD (drop most recent 2026-Q1): 10000+50000+60000+130000 = 250000 (< 260000 -> fails).
    # ALTERNATE (drop oldest 2025-Q1): 50000+60000+130000+300000 = 540000, hq 300000 -> qualifies.
    wages = [("2025-Q1", 10000), ("2025-Q2", 50000), ("2025-Q3", 60000),
             ("2025-Q4", 130000), ("2026-Q1", 300000)]
    claim, det = _build_and_determine(wages)
    assert_claim(claim)
    assert_determination(det)
    assert claim["base_period_method"] == "ALTERNATE", \
        f"expected ALTERNATE, got {claim['base_period_method']}"
    assert claim["status"] == "MONETARILY_ELIGIBLE"
    assert claim["weekly_benefit_amount_cents"] == 11500
    assert claim["maximum_benefit_amount_cents"] == 270000
    assert det["base_period_total_wages_cents"] == 540000
    assert det["high_quarter_wages_cents"] == 300000
    assert det["outcome"] == "ALLOWED"


def test_alternate_determination_records_high_quarter_and_total(api):
    """PRD §3.2: "It also computes an appeal_deadline_date and sets is_appealable
    to true while the outcome is ALLOWED or DENIED and the determination has not
    been reversed."
    PRD §3.2: "computes base_period_total_wages_cents and high_quarter_wages_cents
    (both 0 for a NONMONETARY determination)."

    Design: Difficulty/dual_variant_calc/base_period_standard_vs_alternate_diverge
    """
    wages = [("2025-Q1", 10000), ("2025-Q2", 50000), ("2025-Q3", 60000),
             ("2025-Q4", 130000), ("2026-Q1", 300000)]
    claim, det = _build_and_determine(wages)
    assert det["base_period_total_wages_cents"] == 540000
    assert det["high_quarter_wages_cents"] == 300000
    assert det["outcome"] == "ALLOWED"
    assert det["is_appealable"] is True
    assert claim["base_period_method"] == "ALTERNATE"


# ── Difficulty: combinatorial_formula / maximum_benefit_amount_rounding_order_pinned ──

def test_mba_wage_capped_below_duration_cap(api):
    """PRD §3.4: "The wage-percentage cap is fifty percent of the base-period total
    wages, floored down to a whole dollar (a whole multiple of 100 cents). The base
    maximum benefit amount is the smaller of those two caps".
    PRD §3.4: "The duration cap is the weekly benefit amount multiplied by 26".

    Design: Difficulty/combinatorial_formula/maximum_benefit_amount_rounding_order_pinned
    """
    # ALTERNATE: base_total 540000, WBA 11500. duration cap = 11500*26 = 299000.
    # wage cap = floor(0.5*540000)=270000 < 299000, so MBA = 270000.
    wages = [("2025-Q1", 10000), ("2025-Q2", 50000), ("2025-Q3", 60000),
             ("2025-Q4", 130000), ("2026-Q1", 300000)]
    claim, det = _build_and_determine(wages)
    assert claim["maximum_benefit_amount_cents"] == 270000
    assert claim["weekly_benefit_amount_cents"] == 11500
    assert claim["remaining_balance_cents"] == 270000


def test_mba_duration_capped_below_wage_cap(api):
    """PRD §3.4: "when 26 weeks of the weekly benefit amount is at most half the
    base-period total wages, the duration cap binds and the claimant has a full 26
    weeks of entitlement".
    PRD §3.2: "sets remaining_balance_cents equal to the maximum benefit amount".

    Design: Difficulty/combinatorial_formula/maximum_benefit_amount_rounding_order_pinned
    """
    # STANDARD: hq 780000 -> WBA 30000; base_total 1800000.
    # duration cap = 30000*26 = 780000 ; wage cap = floor(0.5*1800000) = 900000.
    # min -> 780000 (duration cap binds).
    claim, det = _build_and_determine(
        [("2025-Q4", 780000), ("2025-Q3", 360000),
         ("2025-Q2", 360000), ("2025-Q1", 300000)])
    assert claim["base_period_method"] == "STANDARD"
    assert claim["weekly_benefit_amount_cents"] == 30000
    assert claim["maximum_benefit_amount_cents"] == 780000
    assert claim["remaining_balance_cents"] == 780000


# ── Corner: state_machines / monetary_ineligible_terminal_for_pay_path ──

def test_denied_when_both_base_periods_fail(api):
    """PRD §3.2: "When neither method qualifies — the standard set fails and the
    alternate set also fails all three sub-tests — the determination's outcome is
    DENIED, the claim transitions MONETARY_PENDING → MONETARILY_INELIGIBLE,
    base_period_method is set to NONE, the weekly and maximum benefit amounts
    remain 0".

    Design: Corner/state_machines/monetary_ineligible_terminal_for_pay_path
    """
    claim, det = _build_and_determine([("2025-Q4", 5000)])
    assert_claim(claim)
    assert claim["status"] == "MONETARILY_INELIGIBLE"
    assert claim["base_period_method"] == "NONE"
    assert claim["weekly_benefit_amount_cents"] == 0
    assert det["outcome"] == "DENIED"


# ── Corner: calculations / standard_duration_capped_mba_correct ──

def test_standard_duration_capped_mba(api):
    """PRD §3.3: "Take high_quarter_wages_cents and divide it by 26. Round that raw
    figure to the nearest whole dollar using round-half-up".
    PRD §3.4: "The base maximum benefit amount is the smaller of those two caps".

    Design: Corner/calculations/standard_duration_capped_mba_correct
    """
    claim, det = _build_and_determine(
        [("2025-Q4", 780000), ("2025-Q3", 360000),
         ("2025-Q2", 360000), ("2025-Q1", 300000)])
    assert claim["base_period_method"] == "STANDARD"
    assert claim["weekly_benefit_amount_cents"] == 30000
    assert claim["maximum_benefit_amount_cents"] == 780000
    assert det["high_quarter_wages_cents"] == 780000


# ── Corner: calculations / disputed_wage_record_excluded_from_base_period ──

def test_disputed_wage_record_excluded(api):
    """PRD §3.1: "The is_disputed flag defaults to false; a disputed wage record is
    excluded from every base-period calculation."
    PRD §3.2: "a wage record is included only if its calendar_quarter falls in that
    set and its is_disputed flag is false."

    Design: Corner/calculations/disputed_wage_record_excluded_from_base_period
    """
    # STANDARD set 40000+50000+60000+70000 = 220000 (< 260000) once the 200000
    # 2025-Q4 record is excluded as disputed -> DENIED.
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q1", 40000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q2", 50000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q3", 60000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 70000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 200000, is_disputed=True)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    det = issue_monetary_determination(claim["id"])
    claim = get_success_data(api_client.get_claim(claim["id"], ADJ))
    assert claim["status"] == "MONETARILY_INELIGIBLE"
    assert det["base_period_total_wages_cents"] == 0
    assert det["outcome"] == "DENIED"


# ── Corner: calculations / wba_floor_clamp_applied ──

def test_wba_divisor_applied_before_clamp(api):
    """PRD §3.3: "Take high_quarter_wages_cents and divide it by 26 ... Then clamp
    the rounded dollar figure into the inclusive range whose floor is 4,000 cents
    and whose ceiling is 60,000 cents".

    Design: Corner/calculations/wba_floor_clamp_applied
    """
    # Single-quarter style: 2025-Q4 + 2025-Q3 each 130000.
    # STANDARD set covers Q4+Q3; total 260000, hq 130000 -> qualifies.
    # WBA = 130000/26 = 5000 (above the 4000 floor, no clamp).
    claim, det = _build_and_determine([("2025-Q4", 130000), ("2025-Q3", 130000)])
    assert claim["status"] == "MONETARILY_ELIGIBLE"
    assert claim["weekly_benefit_amount_cents"] == 5000


# ── Corner: consistency_model / immediate_visibility_of_monetary_fields ──

def test_monetary_fields_visible_immediately_after_determination(api):
    """PRD §3.2: "When a method qualifies, the determination's outcome is ALLOWED
    and the parent claim transitions MONETARY_PENDING → MONETARILY_ELIGIBLE. The
    system computes the weekly and maximum benefit amounts ... sets the claim's
    weekly_benefit_amount_cents and maximum_benefit_amount_cents".

    Design: Corner/consistency_model/immediate_visibility_of_monetary_fields_after_determination
    """
    # Two records 2025-Q4 + 2025-Q3 each 130000: STANDARD set covers both,
    # total 260000 >= 260000, hq 130000 >= 130000, 2*260000 >= 3*130000 -> qualifies.
    # WBA = 130000/26 = 5000.
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 130000)
    add_wage_record(claimant["id"], employer["id"], "2025-Q3", 130000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    issue_monetary_determination(claim["id"])
    claim = get_success_data(api_client.get_claim(claim["id"], ADJ))
    assert claim["status"] == "MONETARILY_ELIGIBLE"
    assert claim["weekly_benefit_amount_cents"] == 5000


# ── Corner: endpoints / get_claim_summary_computed_read ──

def test_get_claim_reflects_computed_balance_equals_mba(api):
    """PRD §2.8: "A claim's remaining_balance_cents always equals its
    maximum_benefit_amount_cents less the sum of the payable_amount_cents of its
    paid weeks."

    Design: Corner/endpoints/get_claim_summary_computed_read
    """
    scenario = make_eligible_claim()  # STANDARD profile: WBA 30000, MBA 780000.
    claim = get_success_data(api_client.get_claim(scenario["claim"]["id"], ADJ))
    assert claim["weekly_benefit_amount_cents"] == 30000
    assert claim["remaining_balance_cents"] == 780000
    assert claim["remaining_balance_cents"] == claim["maximum_benefit_amount_cents"]
