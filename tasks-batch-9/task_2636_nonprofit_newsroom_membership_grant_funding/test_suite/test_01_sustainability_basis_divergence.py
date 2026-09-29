"""Two bases over one identical database, and the two funder risk variants.

The recognized and pipeline bases read the same stored rows and disagree; the
self-attested and audited advocacy variants score the same funder row
differently. Both divergences are observable through reads alone.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_funder,
    assert_sustainability,
    file_disclosure,
    open_fiscal_period,
    read_funder,
    read_proposal,
    read_sustainability,
    record_contribution,
    record_proposal_outcome,
    register_coverage_area,
    register_funder,
    rule_on_funder,
    setup_cleared_funder,
    setup_submitted_proposal,
    settle_contribution,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ED_HEADERS, FC_HEADERS


def _setup_one_award_one_pipeline_and_event_cash():
    """One period holding a 350000 award, a 200000 submitted proposal at 5000
    bps and 650000 of settled events cash."""
    period = open_fiscal_period(
        monthly_expense_base_cents=200000, reserve_balance_cents=500000
    )
    funder_a = setup_cleared_funder(legal_name="Cascade Foundation")
    proposal_a = setup_submitted_proposal(
        funder_a["id"],
        period["id"],
        title="General operating support",
        requested_amount_cents=350000,
        restriction_type="UNRESTRICTED",
        reporting_cadence="NONE",
        award_probability_bps=8000,
    )
    awarded = record_proposal_outcome(
        proposal_a["id"],
        "AWARDED",
        awarded_amount_cents=350000,
        award_date="2026-08-15",
    )
    funder_b = setup_cleared_funder(legal_name="Ridgeline Trust")
    proposal_b = setup_submitted_proposal(
        funder_b["id"],
        period["id"],
        title="Statehouse accountability desk",
        requested_amount_cents=200000,
        restriction_type="UNRESTRICTED",
        reporting_cadence="NONE",
        award_probability_bps=5000,
    )
    event_cash = record_contribution(
        period["id"],
        "EVENTS",
        650000,
        received_date="2026-08-10",
        source_label="Annual benefit dinner",
    )
    settle_contribution(event_cash["id"])
    return {
        "period": period,
        "funder_a": funder_a,
        "awarded": awarded,
        "funder_b": funder_b,
        "submitted": proposal_b,
    }


class TestRecognizedAndPipelineBasesDiverge:
    """The two bases of the diversification index over one database."""

    def test_recognized_basis_counts_only_the_award_and_settled_cash(self):
        """A 350000 award plus 650000 of settled events cash gives 1000000 of
        recognized revenue, a concentration of 5450 and a top source of 3500.

        PRD: "The **recognized** basis is the persisted one: its settled set is
        exactly `SETTLED`, both pipeline terms are 0, and it counts cash and
        signed awards only."

        Design: Difficulty/dual_variant_calc/dv_recognized_vs_pipeline_diverge_on_hhi_top_source_and_reserve_target
        """
        ctx = _setup_one_award_one_pipeline_and_event_cash()

        recognized = read_sustainability(ctx["period"]["id"], basis="RECOGNIZED")
        assert_sustainability(recognized)

        assert recognized["basis"] == "RECOGNIZED"
        assert recognized["recognized_revenue_cents"] == 1000000
        assert recognized["grants_share_bps"] == 3500
        assert recognized["events_share_bps"] == 6500
        assert recognized["membership_share_bps"] == 0
        assert recognized["major_gift_share_bps"] == 0
        assert recognized["syndication_share_bps"] == 0
        assert recognized["concentration_hhi"] == 5450
        assert recognized["top_source_share_bps"] == 3500
        assert recognized["reserve_months_target"] == 5
        assert recognized["operating_reserve_target_cents"] == 1000000
        assert recognized["reserve_months_ratio_bps"] == 25000
        assert recognized["sustainability_posture"] == "WATCH"
        assert recognized["restricted_release_cap_pct_bps"] == 6000

    def test_pipeline_basis_folds_in_the_submitted_proposal_and_persists_nothing(self):
        """The same rows on the pipeline basis total 1100000, drop the top source
        to 3182 and relax the reserve target to four months, while the stored
        fiscal period keeps its recognized figures.

        PRD: "The **pipeline** basis is a read-only projection that is never
        persisted: its settled set is `SETTLED` **and** `INITIATED`, and its
        grant pipeline term is the sum, over the period's proposals in status
        `SUBMITTED`, of `requested_amount_cents` multiplied by
        `award_probability_bps` divided by 10000 and rounded half up"

        Design: Difficulty/dual_variant_calc/dv_recognized_vs_pipeline_diverge_on_hhi_top_source_and_reserve_target
        """
        ctx = _setup_one_award_one_pipeline_and_event_cash()

        pipeline = read_sustainability(ctx["period"]["id"], basis="PIPELINE")
        assert_sustainability(pipeline)

        assert pipeline["basis"] == "PIPELINE"
        assert pipeline["recognized_revenue_cents"] == 1100000
        assert pipeline["grants_share_bps"] == 4091
        assert pipeline["events_share_bps"] == 5909
        assert pipeline["concentration_hhi"] == 5165
        assert pipeline["top_source_share_bps"] == 3182
        assert pipeline["reserve_months_target"] == 4
        assert pipeline["operating_reserve_target_cents"] == 800000

        stored = validate_success(
            api_client.get_fiscal_period(ctx["period"]["id"], FC_HEADERS)
        )
        assert stored["concentration_hhi"] == 5450
        assert stored["top_source_share_bps"] == 3500
        assert stored["reserve_months_target"] == 5

        still_submitted = read_proposal(ctx["submitted"]["id"])
        assert still_submitted["status"] == "SUBMITTED"
        assert still_submitted["awarded_amount_cents"] == 0

    def test_the_two_bases_split_the_reserve_target_from_one_database(self):
        """A top source of 3500 earns the fifth reserve month on the recognized
        basis while 3182 does not on the pipeline basis, so one period reports
        two different targets in the same breath.

        PRD: "Third, `reserve_months_target` starts at a base of 3 months and
        gains one month if `concentration_hhi` is at least 3000 and one further
        month if `top_source_share_bps` is at least 3500 - so the target is 3, 4
        or 5 months."

        Design: Difficulty/dual_variant_calc/dv_recognized_vs_pipeline_diverge_on_hhi_top_source_and_reserve_target
        """
        ctx = _setup_one_award_one_pipeline_and_event_cash()

        recognized = read_sustainability(ctx["period"]["id"], basis="RECOGNIZED")
        pipeline = read_sustainability(ctx["period"]["id"], basis="PIPELINE")

        assert recognized["top_source_share_bps"] >= 3500
        assert pipeline["top_source_share_bps"] < 3500
        assert recognized["reserve_months_target"] == 5
        assert pipeline["reserve_months_target"] == 4
        assert recognized["operating_reserve_target_cents"] == 1000000
        assert pipeline["operating_reserve_target_cents"] == 800000
        assert recognized["concentration_hhi"] >= 3000
        assert pipeline["concentration_hhi"] >= 3000

    def test_the_recognized_read_replays_the_persisted_values_when_basis_is_omitted(self):
        """Omitting the basis replays exactly what the period stores.

        PRD: "Omitted or `RECOGNIZED` replays the persisted values; `PIPELINE`
        returns the probability-weighted projection and persists nothing."

        Design: Difficulty/dual_variant_calc/dv_recognized_vs_pipeline_diverge_on_hhi_top_source_and_reserve_target
        """
        ctx = _setup_one_award_one_pipeline_and_event_cash()

        default_read = read_sustainability(ctx["period"]["id"])
        stored = validate_success(
            api_client.get_fiscal_period(ctx["period"]["id"], FC_HEADERS)
        )

        assert default_read["recognized_revenue_cents"] == stored["recognized_revenue_cents"]
        assert default_read["concentration_hhi"] == stored["concentration_hhi"]
        assert default_read["top_source_share_bps"] == stored["top_source_share_bps"]
        assert default_read["reserve_months_target"] == stored["reserve_months_target"]


def _setup_affiliated_self_attesting_funder():
    """A FOUNDATION affiliated to a beat and self-attesting advocacy, with an
    ACTIVE disclosure already covering the pair."""
    area = register_coverage_area(
        area_code="HOUSING",
        name="Housing and homelessness",
        editorial_lead_user_id="user-ed-9",
    )
    funder = register_funder(
        legal_name="Wexler Family Foundation",
        funder_type="FOUNDATION",
        affiliated_coverage_area_id=area["id"],
        self_attested_advocacy=True,
    )
    disclosure = file_disclosure(
        funder["id"],
        area["id"],
        funder["version"],
        disclosure_text=(
            "Wexler funds housing coverage; assignments, sourcing and "
            "publication decisions rest solely with the housing desk editor."
        ),
    )
    return {"area": area, "funder": funder, "disclosure": disclosure}


class TestFunderRiskVariantsCrossTheDisclosureFloor:
    """One unchanged funder row scores 32 self-attested and 48 audited."""

    def test_self_attested_variant_pins_the_advocacy_index_at_three(self):
        """Registration scores the funder on the self-attested basis: 10 for the
        foundation type, 10 for the affiliation and 12 for the pinned advocacy
        index of 3, which is 32 and below the disclosure floor.

        PRD: "Under the `SELF_ATTESTED` basis - the default at registration, and
        the basis in force whenever a clearance is filed declaring it - the
        advocacy index is 3 when `self_attested_advocacy` is true and 0 when it
        is false, and `audited_advocacy_index` is ignored even if a value is
        stored."

        Design: Difficulty/dual_variant_calc/dv_funder_risk_self_attested_32_vs_audited_48_crosses_disclosure_floor
        """
        ctx = _setup_affiliated_self_attesting_funder()

        funder = read_funder(ctx["funder"]["id"])
        assert_funder(funder)

        assert funder["risk_basis"] == "SELF_ATTESTED"
        assert funder["independence_risk_score"] == 32
        assert funder["status"] == "PROSPECT"
        assert funder["self_attested_advocacy"] is True
        assert funder["audited_advocacy_index"] is None
        assert funder["independence_risk_score"] < 40

    def test_audited_variant_reads_the_supplied_index_and_lands_at_48(self):
        """Clearing on the audited basis with an index of 7 re-scores the same
        row to 48, exactly 16 higher, and the self-attestation is retained but
        ignored.

        PRD: "Under the `AUDITED` basis - established by a clearance that
        declares it and supplies an `audited_advocacy_index` between 0 and 10 -
        the advocacy index is that supplied integer taken verbatim, and
        `self_attested_advocacy` is ignored."

        Design: Difficulty/dual_variant_calc/dv_funder_risk_self_attested_32_vs_audited_48_crosses_disclosure_floor
        """
        ctx = _setup_affiliated_self_attesting_funder()
        before = read_funder(ctx["funder"]["id"])

        cleared = rule_on_funder(
            ctx["funder"]["id"],
            "CLEAR",
            "AUDITED",
            audited_advocacy_index=7,
            reason="Independent audit measured sustained advocacy on the funded beat.",
        )
        assert_funder(cleared)

        assert before["independence_risk_score"] == 32
        assert cleared["independence_risk_score"] == 48
        assert cleared["risk_basis"] == "AUDITED"
        assert cleared["audited_advocacy_index"] == 7
        assert cleared["self_attested_advocacy"] is True
        assert cleared["independence_risk_score"] - before["independence_risk_score"] == 16

    def test_the_audited_clearance_is_legal_only_because_the_pair_is_disclosed(self):
        """At 48 the funder is at or above the disclosure floor, so the clearance
        succeeds only against the ACTIVE disclosure for its exact beat.

        PRD: "If the recomputed score has reached the disclosure floor of 40 or
        more, then `affiliated_coverage_area_id` must be non-null and an
        `ACTIVE` firewall disclosure must exist for that exact
        funder-and-beat pair; a missing one is `ERR_DISCLOSURE_REQUIRED`, and a
        disclosure for some *other* beat does not satisfy the requirement."

        Design: Difficulty/dual_variant_calc/dv_funder_risk_self_attested_32_vs_audited_48_crosses_disclosure_floor
        """
        ctx = _setup_affiliated_self_attesting_funder()

        cleared = rule_on_funder(
            ctx["funder"]["id"], "CLEAR", "AUDITED", audited_advocacy_index=7
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_by_user_id"] == ED_HEADERS["X-User-ID"]
        assert cleared["independence_risk_score"] >= 40

        disclosure = validate_success(
            api_client.get_firewall_disclosure(ctx["disclosure"]["id"], ED_HEADERS)
        )
        assert disclosure["status"] == "ACTIVE"
        assert disclosure["coverage_area_id"] == ctx["area"]["id"]

    def test_a_funder_with_no_disclosure_cannot_be_cleared_on_the_audited_basis(self):
        """Without the disclosure the identical audited clearance at 48 is
        refused, which is what makes the variant switch load-bearing.

        PRD: "a missing one is `ERR_DISCLOSURE_REQUIRED`, and a disclosure for
        some *other* beat does not satisfy the requirement."

        Design: Difficulty/dual_variant_calc/dv_funder_risk_self_attested_32_vs_audited_48_crosses_disclosure_floor
        """
        area = register_coverage_area(
            area_code="HOUSING",
            name="Housing and homelessness",
            editorial_lead_user_id="user-ed-9",
        )
        funder = register_funder(
            legal_name="Wexler Family Foundation",
            funder_type="FOUNDATION",
            affiliated_coverage_area_id=area["id"],
            self_attested_advocacy=True,
        )
        assert funder["independence_risk_score"] == 32

        response = api_client.funder_independence_clearance(
            funder["id"],
            {"decision": "CLEAR", "basis": "AUDITED", "audited_advocacy_index": 7},
            ED_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DISCLOSURE_REQUIRED)

        unchanged = read_funder(funder["id"])
        assert unchanged["status"] == "PROSPECT"
