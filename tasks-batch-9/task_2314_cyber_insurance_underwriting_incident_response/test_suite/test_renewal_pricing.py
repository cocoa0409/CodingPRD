"""Renewal pricing: the loss ratio and the capped control credit.

These tests drive PRD §3.9, whose evaluation order is pinned because the
control credit is capped as a share of the very premium it reduces.
"""
from test_helpers import ACTUARY_HEADERS, ADJUSTER_2_HEADERS
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, assert_ratio_4dp, data_of


REDSTONE_TOWER = [
    {
        "section_key": "FIRST_PARTY_RESPONSE",
        "sublimit_usd": 1000000,
        "waiting_period_hours": None,
        "coinsurance_pct": 0.0,
        "erosion_priority": 10,
    },
    {
        "section_key": "BUSINESS_INTERRUPTION",
        "sublimit_usd": 5000000,
        "waiting_period_hours": 12,
        "coinsurance_pct": 0.0,
        "erosion_priority": 20,
    },
]


def _redstone_policy_with_one_settled_claim(api):
    """A 50058.00 policy carrying one SETTLED claim that paid 20000.00 net."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_REDSTONE,
        attestations=C.ATTEST_87_50,
        requested_aggregate_limit_usd=10000000,
        requested_retention_usd=100000,
        coverage_sections=REDSTONE_TOWER,
        period_start="2026-08-01T00:00:00Z",
        period_end="2027-08-01T00:00:00Z",
        bi_baseline_method="TRAILING_12M",
        findings=[],
    )
    policy_id = chain["policy"]["id"]
    assert_money(chain["policy"]["premium_usd"], 50058.00, "premium_usd")

    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        policy_id,
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-06T18:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=120000,
        affected_record_count=5000,
    )
    proof = X.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=120000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.8,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))
    return chain, claim


def _conditions_met_assessment(api, policy_id):
    """Open the renewal inside the 90-day window and verify both required controls."""
    X.set_clock(api, "2027-06-01T00:00:00Z")
    keys = ["EMAIL_FILTERING", "INCIDENT_RESPONSE_PLAN"]
    assessment = X.open_renewal_assessment(
        api,
        policy_id,
        required_control_keys=keys,
        remediation_due_at="2027-07-01T00:00:00Z",
    )
    X.submit_remediation(api, assessment["id"], submitted_control_keys=keys)
    return X.verify_remediation(api, assessment["id"], verified_control_keys=keys)


def test_loss_ratio_prices_the_renewal_at_fifty_one_thousand_sixty_dollars_ninety(api):
    """A 20000.00 incurred figure over a 50058.00 earned premium gives 0.3995 and 51060.90.

    PRD §3.9: "The incurred figure is the paid figure plus the outstanding reserve,
    rounded half up to 2 decimal places, and the loss ratio is the incurred figure
    divided by the policy's `premium_usd`, rounded half up to 4 decimal places." A
    settled claim holds no reserve, so 20000.00 / 50058.00 rounds to 0.3995, which
    selects the positive 0.05 tier.

    Design: Difficulty/combinatorial_formula/renewal_control_credit_cap_evaluation_order_mode_c
    """
    chain, claim = _redstone_policy_with_one_settled_claim(api)
    policy_id = chain["policy"]["id"]
    settled = X.read_claim(api, claim["id"])
    assert settled["status"] == "SETTLED", settled["status"]
    assert_money(settled["paid_total_usd"], 20000.00, "paid_total_usd")

    assessment = _conditions_met_assessment(api, policy_id)
    assert assessment["status"] == "CONDITIONS_MET", assessment["status"]

    quoted = X.issue_renewal_quote(api, assessment["id"], policy_id, ACTUARY_HEADERS)

    assert quoted["status"] == "RENEWAL_QUOTED", quoted["status"]
    assert_ratio_4dp(quoted["loss_ratio"], 0.3995, "loss_ratio")
    assert_money(quoted["renewal_premium_usd"], 51060.90, "renewal_premium_usd")
    assert_ratio_4dp(quoted["premium_adjustment_pct"], 0.0200, "premium_adjustment_pct")


def test_control_credit_is_capped_against_the_pre_credit_premium_computed_first(api):
    """The 1500.00 raw credit sits below the 6307.31 cap taken from 52560.90.

    PRD §3.9: "The evaluation order below is pinned, because the control credit is
    capped as a share of the very premium it reduces — the pre-credit premium is
    computed first, the credit is capped against that figure, and only then is it
    subtracted." Two verified keys earn 1500.00, twelve percent of 52560.90 is
    6307.31, so 51060.90 is neither the untouched 50058.00 nor the uncredited
    52560.90.

    Design: Difficulty/combinatorial_formula/renewal_control_credit_cap_evaluation_order_mode_c
    """
    chain, _claim = _redstone_policy_with_one_settled_claim(api)
    policy_id = chain["policy"]["id"]
    assessment = _conditions_met_assessment(api, policy_id)
    assert assessment["verified_control_keys"] == ["EMAIL_FILTERING", "INCIDENT_RESPONSE_PLAN"], (
        assessment["verified_control_keys"]
    )
    assert assessment["verification_round"] == 1, assessment["verification_round"]

    quoted = X.issue_renewal_quote(api, assessment["id"], policy_id, ACTUARY_HEADERS)

    pre_credit = round(50058.00 * 1.05, 2)
    assert pre_credit == 52560.90, pre_credit
    raw_credit = 2 * C.CONTROL_CREDIT_PER_KEY_USD
    cap = round(C.CONTROL_CREDIT_CAP_PCT * pre_credit, 2)
    assert cap == 6307.31, cap
    assert raw_credit == 1500.00 and raw_credit < cap

    assert_money(quoted["renewal_premium_usd"], round(pre_credit - raw_credit, 2), "renewal_premium_usd")
    actual = round(float(quoted["renewal_premium_usd"]), 2)
    assert actual != 50058.00, actual
    assert actual != 52560.90, actual


def test_renewal_quote_reads_the_loss_summary_of_the_expiring_policy(api):
    """The computed loss summary exposes the same paid and incurred figures the pricing uses.

    PRD §3.9: "A computed read exposes these figures directly as `paid_total_usd`,
    `outstanding_reserve_usd`, `incurred_usd`, and `loss_ratio`, alongside
    `aggregate_limit_remaining_usd` and `limit_status`."

    Design: Difficulty/combinatorial_formula/renewal_control_credit_cap_evaluation_order_mode_c
    """
    chain, _claim = _redstone_policy_with_one_settled_claim(api)
    policy_id = chain["policy"]["id"]

    summary = data_of(api.get_policy_loss_summary(policy_id, ACTUARY_HEADERS))

    assert_money(summary["paid_total_usd"], 20000.00, "paid_total_usd")
    assert_money(summary["outstanding_reserve_usd"], 0.00, "outstanding_reserve_usd")
    assert_money(summary["incurred_usd"], 20000.00, "incurred_usd")
    assert_ratio_4dp(summary["loss_ratio"], 0.3995, "loss_ratio")
    assert_money(
        summary["aggregate_limit_remaining_usd"], 9980000.00, "aggregate_limit_remaining_usd"
    )
    assert summary["limit_status"] == "PARTIALLY_ERODED", summary["limit_status"]
