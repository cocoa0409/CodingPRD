"""
Queue A — §1.8 rule ``dual_variant_calc``.

Two computed reads in this API answer the same question under two different
bases, and the whole point of each instance below is that the two answers must
diverge by a pinned amount rather than collapsing onto one another.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import assert_fields, assert_ratio
from test_helpers.factories import REFERENCE_AUDITED_QUARTERS, REFERENCE_INTERNAL_2026Q1
from test_helpers.fixtures import build_house_campaign, build_institution, chain_through_assignment
from test_helpers.test_users import CREDIT_ANALYST

# Four audited 2025 quarters plus one internal 2026Q1: five rows, from which the
# two bases of PRD §3.1 select two different four-period windows.
FIVE_PERIODS = list(REFERENCE_AUDITED_QUARTERS) + [REFERENCE_INTERNAL_2026Q1]


def _summary(api, application_id, basis):
    return get_success_data(
        api.get_underwriting_summary(application_id, CREDIT_ANALYST, {"giving_basis": basis})
    )


def _valuation(api, campaign_id, basis):
    return get_success_data(
        api.get_campaign_valuation(campaign_id, CREDIT_ANALYST, {"basis": basis})
    )


def test_underwriting_summary_windows_and_bases_diverge_across_the_same_five_periods(api):
    """
    The two giving bases select different four-period windows over identical rows.

    PRD §3.1: "Which four depends on the **giving basis**: under `AUDITED_ONLY` the
    ordered candidate list is first filtered to periods whose `source` is `AUDITED`
    and the window is the first four of those; under `BLENDED` the window is simply
    the first four candidates of either provenance."

    PRD §3.1: "Under `BLENDED`, an `AUDITED` period still contributes its full
    unrestricted figure, but an `INTERNAL` period contributes only 85 percent of it
    — that is, its unrestricted figure multiplied by 1 less the 15 percent
    internal-statement haircut, floored to whole cents **per period** before
    anything is summed."

    PRD §3.5: "It accepts an optional `giving_basis` query selecting `AUDITED_ONLY`
    or `BLENDED`; when omitted it defaults to the application's snapshotted
    `giving_basis`, or, where no snapshot exists yet, to the mandated basis."

    Design: Difficulty/dual_variant_calc/giving_base_audited_only_vs_blended_diverge
    """
    chain = chain_through_assignment(api, period_specs=FIVE_PERIODS)

    audited = _summary(api, chain.loan_application_id, "AUDITED_ONLY")
    blended = _summary(api, chain.loan_application_id, "BLENDED")

    assert_fields(
        audited,
        giving_basis="AUDITED_ONLY",
        giving_base_cents=207000000,
        net_available_dollars=432001,
    )
    assert audited["window_period_labels"] == ["2025Q4", "2025Q3", "2025Q2", "2025Q1"], (
        f"AUDITED_ONLY window: got {audited['window_period_labels']}"
    )

    assert_fields(
        blended,
        giving_basis="BLENDED",
        giving_base_cents=202900000,
        net_available_dollars=361000,
    )
    assert blended["window_period_labels"] == ["2026Q1", "2025Q4", "2025Q3", "2025Q2"], (
        f"BLENDED window: got {blended['window_period_labels']}"
    )

    assert audited["giving_base_cents"] - blended["giving_base_cents"] == 4100000
    assert audited["net_available_dollars"] - blended["net_available_dollars"] == 71001


def test_underwriting_summary_reports_the_collateral_cap_under_both_bases_without_mutating(api):
    """
    Both bases are bound by the same collateral cap and neither read touches the snapshot.

    PRD §3.5: "The **collateral cap** is the sum of `lending_value_cents` over the
    collateral assets assigned to this application whose `lien_position` is 1."

    PRD §3.5: "The maximum supportable principal is the lowest of the caps in force."

    PRD §3.5: "A computed read exposes the whole underwriting picture without
    mutating the application, and is available to `PlatformAdmin`, `CreditAnalyst`,
    `CreditCommitteeMember` and the borrower's `InstitutionRepresentative`."

    Design: Difficulty/dual_variant_calc/giving_base_audited_only_vs_blended_diverge
    """
    chain = chain_through_assignment(api, period_specs=FIVE_PERIODS)
    snapshot_before = chain.read_application()

    audited = _summary(api, chain.loan_application_id, "AUDITED_ONLY")
    blended = _summary(api, chain.loan_application_id, "BLENDED")

    for summary in (audited, blended):
        assert_fields(
            summary,
            collateral_lending_value_cents=225000000,
            binding_cap="COLLATERAL",
            max_supportable_principal_cents=225000000,
            requested_amount_cents=225000000,
        )

    snapshot_after = chain.read_application()
    assert_fields(
        snapshot_after,
        giving_basis="AUDITED_ONLY",
        giving_base_cents=207000000,
        net_available_dollars=432001,
        version=snapshot_before["version"],
    )


def test_campaign_valuation_conservative_and_optimistic_bases_diverge(api):
    """
    Per-pledge discounting and single-shot sponsor discounting price the same rows apart.

    PRD §3.3: "Every pledge still in `ACTIVE` status then contributes its remaining
    balance, being its `pledged_amount_cents` less its `collected_cents`, multiplied
    by 1 less that pledge's own effective attrition rate, and floored to whole cents
    **per pledge**."

    PRD §3.3: "It aggregates first and discounts once: the remaining balances of
    every `ACTIVE` pledge are summed, that single total is multiplied by the
    campaign's `sponsor_collection_rate_bps` divided by 10000, the product is
    floored once to whole cents, and the collected cash is added."

    Design: Difficulty/dual_variant_calc/pledge_campaign_conservative_vs_optimistic_valuation_diverge
    """
    institution = build_institution(api)
    built = build_house_campaign(api, institution["id"])
    campaign_id = built["campaign"]["id"]

    conservative = _valuation(api, campaign_id, "LENDER_CONSERVATIVE")
    optimistic = _valuation(api, campaign_id, "SPONSOR_OPTIMISTIC")

    assert_fields(
        conservative, basis="LENDER_CONSERVATIVE", projected_value_cents=109560000
    )
    assert_fields(optimistic, basis="SPONSOR_OPTIMISTIC", projected_value_cents=117000000)
    assert optimistic["projected_value_cents"] - conservative["projected_value_cents"] == 7440000


def test_campaign_stores_both_valuations_with_tiered_attrition_and_gate_thresholds(api):
    """
    The stored campaign figures, the tier penalty and both gate thresholds all agree.

    PRD §3.3: "A donor who has missed two or more installments is penalised a
    further 15 percentage points, and the resulting rate is capped at 60 percent no
    matter how the components add up."

    PRD §3.3: "The base attrition rate is fixed by tier: 5 percent for a `LEAD`
    donor, 12 percent for a `MAJOR` donor and 22 percent for a `GENERAL` donor."

    PRD §3.3: "It accepts an optional `basis` selecting `LENDER_CONSERVATIVE` or
    `SPONSOR_OPTIMISTIC` and defaulting to `LENDER_CONSERVATIVE`, and answers with
    `basis` echoing the applied choice, `projected_value_cents` computed under that
    basis, and the raw material the figure was derived from:
    `collected_to_date_cents`, `active_pledged_cents`, `lapsed_pledged_cents`,
    `fulfilled_pledged_cents`, `total_pledged_cents`, `goal_cents`, `status`, plus
    the two gate thresholds as `underperform_threshold_cents` (the floor of the goal
    times 80 percent) and `maturity_threshold_cents` (the floor of the goal times 90
    percent)."

    Design: Difficulty/dual_variant_calc/pledge_campaign_conservative_vs_optimistic_valuation_diverge
    """
    institution = build_institution(api)
    built = build_house_campaign(api, institution["id"])
    campaign_id = built["campaign"]["id"]

    conservative = _valuation(api, campaign_id, "LENDER_CONSERVATIVE")
    optimistic = _valuation(api, campaign_id, "SPONSOR_OPTIMISTIC")
    for summary in (conservative, optimistic):
        assert_fields(
            summary,
            underperform_threshold_cents=96000000,
            maturity_threshold_cents=108000000,
            status="OPEN",
            total_pledged_cents=125000000,
            collected_to_date_cents=25000000,
        )

    campaign = get_success_data(api.get_pledge_campaign(campaign_id, CREDIT_ANALYST))
    assert_fields(
        campaign,
        attrition_adjusted_value_cents=109560000,
        sponsor_projected_value_cents=117000000,
        status="OPEN",
    )

    major = get_success_data(api.get_pledge(built["major"]["id"], CREDIT_ANALYST))
    lead = get_success_data(api.get_pledge(built["lead"]["id"], CREDIT_ANALYST))
    assert_ratio(major["effective_attrition_pct"], 0.2700, "major effective_attrition_pct")
    assert_ratio(lead["effective_attrition_pct"], 0.0500, "lead effective_attrition_pct")
