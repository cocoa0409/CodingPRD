"""Business interruption quantification on an accepted proof of loss.

These tests drive PRD §3.8: the two revenue baselines, the seven numbered
quantification steps, and the rule that every component is rounded to cents
before it is combined with the others.
"""
from test_helpers import ADJUSTER_2_HEADERS, ADJUSTER_HEADERS
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, data_of


CLOCK = "2026-09-10T00:00:00Z"
OUTAGE_START = "2026-09-05T00:00:00Z"
OUTAGE_END = "2026-09-08T00:00:00Z"


def _aurora_policy(api):
    """Bound Aurora Health policy on the five-section tower, retention 250,000."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        coverage_sections=list(C.STANDARD_TOWER),
        bi_baseline_method="TRAILING_12M",
        findings=[],
    )
    X.set_clock(api, CLOCK)
    return chain


def _proof_on_new_claim(api, policy_id, **proof_overrides):
    """A fresh RANSOMWARE claim with a 72-hour outage carrying one UNDER_REVIEW proof."""
    claim = X.confirmed_claim(
        api,
        policy_id,
        incident_type="RANSOMWARE",
        incident_discovered_at=OUTAGE_START,
        outage_start_at=OUTAGE_START,
        outage_end_at=OUTAGE_END,
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
    )
    proof = X.file_proof(api, claim["id"], **proof_overrides)
    return claim, proof


# ==========================================================================
# The two revenue baselines on identical inputs
# ==========================================================================
def test_trailing_twelve_month_baseline_assesses_two_hundred_twelve_thousand_five_hundred(api):
    """TRAILING_12M divides the annual revenue by 8,760 and lands on 212500.00.

    PRD §3.8: "Under `TRAILING_12M` it is `trailing_12m_revenue_usd` divided by
    8,760 — the hours in a 365-day year — which is a flat annual average that
    smooths seasonality and usually produces the lower indemnity." With 60.00
    compensable hours at 5,000.00 per hour and a 0.62 margin the component is
    186000.00, the mitigation credit is 20000.00 and the extra expense is capped
    at 46500.00.

    Design: Difficulty/dual_variant_calc/bi_indemnity_trailing_versus_prior_year_diverge_on_proof_of_loss
    """
    chain = _aurora_policy(api)
    _claim, proof = _proof_on_new_claim(
        api,
        chain["policy"]["id"],
        claimed_bi_loss_usd=250000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=60000,
        mitigation_savings_usd=20000,
    )

    accepted = data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))

    assert accepted["baseline_method_applied"] == "TRAILING_12M", accepted
    assert_money(accepted["outage_hours"], 72.00, "outage_hours")
    assert_money(accepted["compensable_hours"], 60.00, "compensable_hours")
    assert_money(accepted["bi_component_usd"], 186000.00, "bi_component_usd")
    assert_money(accepted["mitigation_component_usd"], 20000.00, "mitigation_component_usd")
    assert_money(accepted["extra_expense_component_usd"], 46500.00, "extra_expense_component_usd")
    assert_money(accepted["assessed_indemnity_usd"], 212500.00, "assessed_indemnity_usd")


def test_prior_year_override_raises_every_component_by_the_seasonal_peak(api):
    """SAME_PERIOD_PRIOR_YEAR uses 6,000.00 per hour and adds exactly 46500.00.

    PRD §3.8: "The adjuster may supply a `baseline_method_override`;
    `baseline_method_applied` records the variant actually used, which is the
    override when one is supplied and the policy's `bi_baseline_method` otherwise."
    The prior-year window of 1,200,000 over 200 hours raises the component to
    223200.00 and the 25 percent extra-expense cap to 55800.00, so the assessed
    indemnity moves from 212500.00 to 259000.00 on identical submitted figures.

    Design: Difficulty/dual_variant_calc/bi_indemnity_trailing_versus_prior_year_diverge_on_proof_of_loss
    """
    chain = _aurora_policy(api)
    policy_id = chain["policy"]["id"]
    financials = {
        "claimed_bi_loss_usd": 250000,
        "trailing_12m_revenue_usd": 43800000,
        "prior_year_same_period_revenue_usd": 1200000,
        "prior_year_same_period_hours": 200,
        "gross_profit_margin_pct": 0.62,
        "extra_expense_usd": 60000,
        "mitigation_savings_usd": 20000,
    }

    _claim_one, proof_one = _proof_on_new_claim(api, policy_id, **financials)
    first = data_of(api.accept_proof_of_loss(proof_one["id"], ADJUSTER_2_HEADERS))

    _claim_two, proof_two = _proof_on_new_claim(api, policy_id, **financials)
    second = data_of(
        api.accept_proof_of_loss(
            proof_two["id"],
            ADJUSTER_2_HEADERS,
            payload={"baseline_method_override": "SAME_PERIOD_PRIOR_YEAR"},
        )
    )

    assert second["baseline_method_applied"] == "SAME_PERIOD_PRIOR_YEAR", second
    assert_money(second["bi_component_usd"], 223200.00, "bi_component_usd")
    assert_money(second["extra_expense_component_usd"], 55800.00, "extra_expense_component_usd")
    assert_money(second["assessed_indemnity_usd"], 259000.00, "assessed_indemnity_usd")

    delta = round(
        float(second["assessed_indemnity_usd"]) - float(first["assessed_indemnity_usd"]), 2
    )
    assert delta == 46500.00, delta


# ==========================================================================
# Round-then-sum ordering
# ==========================================================================
def _mode_b_proof(api):
    chain = _aurora_policy(api)
    _claim, proof = _proof_on_new_claim(
        api,
        chain["policy"]["id"],
        claimed_bi_loss_usd=300000,
        trailing_12m_revenue_usd=43800043.80,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=100000,
        mitigation_savings_usd=0,
    )
    return data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))


def test_extra_expense_cap_is_taken_from_the_already_rounded_bi_component(api):
    """A 5000.005 hourly baseline rounds the component to 186000.19 before the cap applies.

    PRD §3.8: "The cap is computed from the **already rounded** `bi_component_usd`,
    not from the raw product behind it." Twenty-five percent of 186000.19 is
    46500.0475, which rounds to 46500.05, so the 100,000 claimed extra expense is
    capped there.

    Design: Difficulty/combinatorial_formula/bi_component_round_then_sum_order_pinned_mode_b
    """
    accepted = _mode_b_proof(api)

    assert_money(accepted["bi_component_usd"], 186000.19, "bi_component_usd")
    assert_money(accepted["extra_expense_component_usd"], 46500.05, "extra_expense_component_usd")
    assert_money(accepted["mitigation_component_usd"], 0.00, "mitigation_component_usd")


def test_assessed_indemnity_sums_rounded_components_not_raw_products(api):
    """The pinned order yields 232500.24; summing raw products first yields 232500.23.

    PRD §3.8: "Each component is rounded to cents before it is combined with the
    others. Summing raw components and rounding once at the end is explicitly wrong
    and will produce a different indemnity."

    Design: Difficulty/combinatorial_formula/bi_component_round_then_sum_order_pinned_mode_b
    """
    accepted = _mode_b_proof(api)

    assert_money(accepted["assessed_indemnity_usd"], 232500.24, "assessed_indemnity_usd")
    assert round(float(accepted["assessed_indemnity_usd"]), 2) != 232500.23


def test_retention_absorbs_the_whole_indemnity_before_any_section_is_touched(api):
    """A 212500.00 indemnity under a 250,000 retention posts no payment row at all.

    PRD §3.8: "Retention comes first, once per claim, off the top, before any
    section is touched." Nothing remains to allocate, so the claim settles with
    `paid_total_usd` at 0.00 and the policy aggregate untouched.

    Design: Difficulty/dual_variant_calc/bi_indemnity_trailing_versus_prior_year_diverge_on_proof_of_loss
    """
    chain = _aurora_policy(api)
    claim, proof = _proof_on_new_claim(
        api,
        chain["policy"]["id"],
        claimed_bi_loss_usd=250000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=60000,
        mitigation_savings_usd=20000,
    )

    data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))

    settled = X.read_claim(api, claim["id"], ADJUSTER_HEADERS)
    assert settled["status"] == "SETTLED", settled["status"]
    assert_money(settled["retention_absorbed_usd"], 212500.00, "retention_absorbed_usd")
    assert_money(settled["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(settled["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")
    assert X.list_payments_for_claim(api, claim["id"]) == []

    policy = X.read_policy(api, chain["policy"]["id"])
    assert_money(policy["aggregate_limit_remaining_usd"], 5000000.00, "aggregate_limit_remaining_usd")
    assert policy["limit_status"] == "INTACT", policy["limit_status"]
