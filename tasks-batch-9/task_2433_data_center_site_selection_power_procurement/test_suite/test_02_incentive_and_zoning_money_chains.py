"""Ordered money chains: incentive present value and zoning mitigation escrow."""

from test_helpers import (
    EXPECTED_CONDITIONS_ESCROW_USD,
    EXPECTED_MITIGATION_COST_USD,
    add_objection,
    assert_money,
    assert_pct,
    assert_status,
    decide_zoning,
    file_company_round,
    file_zoning,
    open_negotiation,
    read_site,
    setup_draft_site,
)


def _docket_with_five_objections(offered_tier):
    """A 55 dBA ordinance against 62 dBA of modelled noise, with three noise and two
    water objections recorded against the docket."""
    env = setup_draft_site()
    docket = file_zoning(env["site"]["id"], visual_mitigation_tier=offered_tier)
    for reference in ("CMT-001", "CMT-002", "CMT-003"):
        add_objection(docket["id"], objection_type="NOISE", commenter_reference=reference)
    for reference in ("CMT-004", "CMT-005"):
        add_objection(docket["id"], objection_type="WATER", commenter_reference=reference)
    return env, docket


def test_company_round_prices_the_tiered_sales_tax_benefit_from_the_capital_commitment():
    """A 3.2 billion dollar capital commitment sits above the 1.5 billion threshold, so
    the sales-tax rate falls to the lowest 4.75 percent band; on a fully exempted
    equipment share the benefit is 94240000.00. The round also drives the negotiation
    out of `DRAFT` into `AUTHORITY_COUNTER_PENDING` with one round recorded and the
    company named as the party that acted.

    PRD §3.7: "First, the sales-tax benefit is tiered on the capital commitment, and the tiers move *downward* as the investment grows: the applicable rate is 6.25 percent, expressed as 0.0625, when the capital commitment is strictly below 500 million dollars; 5.50 percent, expressed as 0.0550, when it is strictly below 1.5 billion dollars; and 4.75 percent, expressed as 0.0475, at 1.5 billion dollars or above."
    PRD §3.7: "The `sales_tax_benefit_usd` is then the capital commitment multiplied by an equipment share of 0.62 — the fraction of the capital spend that is taxable equipment — multiplied by that rate, multiplied by the negotiated exemption fraction, and rounded to 2 decimal places."
    PRD §3.7: "The opening company round drives the negotiation from `DRAFT` to `AUTHORITY_COUNTER_PENDING`, and that first round additionally requires the referenced site to be in `DRAFT` or `SCREENED` status."

    Design: Difficulty/combinatorial_formula/incentive_npv_tiered_sales_tax_with_per_year_rounding
    """
    env = setup_draft_site()
    negotiation = open_negotiation(env["site"]["id"], "STATE")
    assert_status(negotiation, "DRAFT", "new negotiation")
    assert negotiation["round_count"] == 0
    assert negotiation["last_party"] is None

    after_round = file_company_round(negotiation["id"])

    assert_money(
        after_round["sales_tax_benefit_usd"], 94240000.00, "sales_tax_benefit_usd"
    )
    assert_status(after_round, "AUTHORITY_COUNTER_PENDING", "negotiation")
    assert after_round["round_count"] == 1
    assert after_round["last_party"] == "COMPANY"


def test_abatement_present_value_rounds_each_year_to_cents_before_summing():
    """The ten-year abatement stream on the same terms discounts to 343874552.25 only
    because each annual figure is rounded to cents before the years are added;
    summing at full precision and rounding once at the end lands a cent lower. The
    total incentive is the sales-tax benefit plus that present value, and with a jobs
    commitment of 150 the clawback takes the gentler 0.40 share of it.

    PRD §3.7: "Third, the `abatement_npv_usd` discounts that base across the abatement term at a discount rate of 0.07 per year: for each whole year from the first through the last year of the term, the annual base is divided by one plus the discount rate raised to that year's power, **that year's figure is rounded to cents**, and only then are the per-year figures summed."
    PRD §3.7: "Fourth, `npv_incentive_usd` is the sales-tax benefit plus the abatement present value, rounded to 2 decimal places, and `clawback_exposure_usd` is that total multiplied by a clawback share, rounded to 2 decimal places — where the share is the gentler 0.40 when the company has committed to at least 100 permanent jobs and the harsher 0.60 when it has committed to fewer."
    PRD §2.7: "Conversely, a property-tax abatement's present value rounds **each** annual figure to cents before the years are summed; summing unrounded annual figures and rounding once at the end is incorrect and can differ by cents."

    Design: Difficulty/combinatorial_formula/incentive_npv_tiered_sales_tax_with_per_year_rounding
    """
    env = setup_draft_site()
    negotiation = open_negotiation(env["site"]["id"], "STATE")

    after_round = file_company_round(negotiation["id"])

    assert_money(after_round["abatement_npv_usd"], 343874552.25, "abatement_npv_usd")
    assert_money(after_round["npv_incentive_usd"], 438114552.25, "npv_incentive_usd")
    assert_money(
        after_round["clawback_exposure_usd"], 175245820.90, "clawback_exposure_usd"
    )


def test_weighted_objections_and_noise_excess_select_the_required_mitigation_tier():
    """Three noise objections at 1.5 and two water objections at 2.0 weigh 8.50, and
    62 dBA against a 55 dBA ordinance leaves a 7.0 dBA excess. Neither driver reaches
    the full-enclosure rungs of 10 dBA or a score of 12, but both clear the
    berm-and-screening rungs, so the ladder stops at `BERM_AND_SCREENING` and the
    applicant offering exactly that tier is approved with conditions.

    PRD §3.6: "Each objection increments `objection_count` by one and feeds the `weighted_opposition_score`, which is the sum of a per-type weight over all objections recorded against that docket, rounded to 2 decimal places."
    PRD §3.6: "Water objections carry the heaviest weight at 2.0, noise objections 1.5, visual objections 1.2, and traffic objections the lightest at 1.0."
    PRD §3.6: "Step three selects the `required_mitigation_tier` on a first-match-wins ladder in which either driver can escalate the tier on its own: the tier is `FULL_ENCLOSURE` when the noise excess is at least 10 dBA **or** the weighted opposition score is at least 12; failing that it is `BERM_AND_SCREENING` when the noise excess is at least 5 dBA **or** the score is at least 6; failing that it is `BERM` when the noise excess is strictly greater than 0 **or** the score is at least 3; and otherwise it is `NONE`."

    Design: Difficulty/combinatorial_formula/zoning_mitigation_tier_then_escrow_pct_chain
    """
    _env, docket = _docket_with_five_objections("BERM_AND_SCREENING")

    decided = decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved subject to acoustic enclosure and screening conditions.",
    )

    assert decided["objection_count"] == 5
    assert_pct(decided["weighted_opposition_score"], 8.50, "weighted_opposition_score")
    assert decided["noise_excess_dba"] == 7.0
    assert decided["required_mitigation_tier"] == "BERM_AND_SCREENING"
    assert_status(decided, "APPROVED_WITH_CONDITIONS", "zoning docket")


def test_escrow_percentage_is_tiered_on_the_mitigation_cost_it_follows():
    """The berm-and-screening base of 2,100,000 plus 125,000 per decibel of the 7.0 dBA
    excess prices mitigation at 2975000.00, and that cost — not the tier that produced
    it — selects the 0.15 escrow band for a 446250.00 hold. Approval finalizes both
    figures in order and re-aggregates the site's capital commitment, which is exactly
    their sum on a site with no application and no options.

    PRD §3.6: "Step four prices that tier as `mitigation_cost_usd`: a tier base of 0 for `NONE`, 750,000 dollars for `BERM`, 2,100,000 dollars for `BERM_AND_SCREENING` and 5,400,000 dollars for `FULL_ENCLOSURE`, plus a per-decibel adder of 125,000 dollars applied to the **acoustic excess only** and never to the raw noise figures, with the total rounded to 2 decimal places."
    PRD §3.6: "Step five sets the escrow the board will hold, and the crucial subtlety is that the escrow percentage is tiered on the **cost computed in step four**, not on the tier chosen in step three: the percentage is 0.00 when the cost is exactly zero, one tenth at 0.10 when the cost is strictly below 1,000,000 dollars, fifteen hundredths at 0.15 when the cost is strictly below 4,000,000 dollars, and one fifth at 0.20 otherwise."
    PRD §3.6: "On approval the `mitigation_cost_usd` and then the `conditions_escrow_usd` are finalized in that order, and the owning site's `site_capital_commitment_usd` is recomputed because both figures feed it."

    Design: Difficulty/combinatorial_formula/zoning_mitigation_tier_then_escrow_pct_chain
    """
    env, docket = _docket_with_five_objections("BERM_AND_SCREENING")

    decided = decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved subject to acoustic enclosure and screening conditions.",
    )

    assert_money(
        decided["mitigation_cost_usd"], EXPECTED_MITIGATION_COST_USD, "mitigation_cost_usd"
    )
    assert_money(
        decided["conditions_escrow_usd"],
        EXPECTED_CONDITIONS_ESCROW_USD,
        "conditions_escrow_usd",
    )

    site = read_site(env["site"]["id"])
    assert_money(
        site["site_capital_commitment_usd"], 3421250.00, "site_capital_commitment_usd"
    )


def test_mitigation_cost_of_exactly_one_million_lands_in_the_fifteen_percent_band():
    """A berm base of 750,000 plus 125,000 for each of exactly 2.0 dBA of excess prices
    mitigation at precisely 1000000.00. The ten percent band is a strict "below", so
    that figure falls through into the fifteen percent band and the board holds
    150000.00 rather than 100000.00.

    PRD §3.6: "Step five sets the escrow the board will hold, and the crucial subtlety is that the escrow percentage is tiered on the **cost computed in step four**, not on the tier chosen in step three: the percentage is 0.00 when the cost is exactly zero, one tenth at 0.10 when the cost is strictly below 1,000,000 dollars, fifteen hundredths at 0.15 when the cost is strictly below 4,000,000 dollars, and one fifth at 0.20 otherwise."
    PRD §3.6: "A cost of exactly 1,000,000.00 dollars therefore lands in the 0.15 band because the lowest band is a strict "below"."
    PRD §3.6: "The `conditions_escrow_usd` is the mitigation cost multiplied by that percentage, rounded to 2 decimal places."

    Design: Difficulty/boundary_precision_check/zoning_escrow_tier_at_exact_one_million_boundary
    """
    env = setup_draft_site()
    docket = file_zoning(
        env["site"]["id"],
        noise_limit_dba=55,
        projected_noise_dba=57,
        visual_mitigation_tier="BERM",
    )

    decided = decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved with berm condition.",
    )

    assert_money(decided["mitigation_cost_usd"], 1000000.00, "mitigation_cost_usd")
    assert_money(decided["conditions_escrow_usd"], 150000.00, "conditions_escrow_usd")
    assert_status(decided, "APPROVED_WITH_CONDITIONS", "zoning docket")


def test_docket_with_no_objections_carries_a_zero_weighted_opposition_score():
    """With no community engagement recorded at all the weighted opposition score is
    0.00, so the tier ladder is driven by the acoustic excess alone: 57 dBA against a
    55 dBA ordinance leaves 2.0 dBA, which clears only the strictly-greater-than-zero
    rung and demands a `BERM`.

    PRD §3.6: "Step two computes `noise_excess_dba` as the modelled noise minus the ordinance limit, floored at 0, so a campus modelled at or below the limit has no excess."
    PRD §3.6: "A freshly filed docket sits at `status` `SUBMITTED` with `continuance_count` of 0 and `objection_count` of 0, and its acoustic and mitigation figures are already computed from the noise inputs on the assumption of zero objections."

    Design: Difficulty/boundary_precision_check/zoning_escrow_tier_at_exact_one_million_boundary
    """
    env = setup_draft_site()
    docket = file_zoning(
        env["site"]["id"],
        noise_limit_dba=55,
        projected_noise_dba=57,
        visual_mitigation_tier="BERM",
    )
    assert_status(docket, "SUBMITTED", "fresh zoning docket")
    assert docket["objection_count"] == 0
    assert docket["continuance_count"] == 0

    decided = decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved with berm condition.",
    )

    assert decided["objection_count"] == 0
    assert_pct(decided["weighted_opposition_score"], 0.00, "weighted_opposition_score")
    assert decided["noise_excess_dba"] == 2.0
    assert decided["required_mitigation_tier"] == "BERM"
