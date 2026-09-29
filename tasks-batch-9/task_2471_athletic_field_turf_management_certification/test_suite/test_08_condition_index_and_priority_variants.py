"""The two variant pairs: the condition index and the replacement priority score."""

from test_helpers import (
    ApiErrorId,
    assert_one_decimal,
    assert_two_decimals,
    factories,
    fixtures,
    validate_error,
)


def _advisory_synthetic_field(client, roster):
    """A synthetic surface past its nominal life carrying a 185.0 g-max mean."""
    field = fixtures.register_synthetic_stadium_1(client, roster)
    assessment = fixtures.record_impact_test(
        client, roster, field["id"], [185.0, 185.0, 185.0]
    )
    return fixtures.read_field(client, roster, field["id"]), assessment


class TestConditionIndexVariantDivergence:
    def test_agronomic_variant_is_an_uncapped_weighted_blend(self, client, roster):
        """The agronomic headline number is allowed to outrun its safety term.

        "The `AGRONOMIC` variant then weights the wear component at 0.50, the age
        component at 0.20 and the safety component at 0.30, sums them, and rounds
        half up to two decimal places, applying no cap — an agronomically
        excellent surface can still score well on this variant with a mediocre
        g-max reading."

        "otherwise it is the distance from the mandatory g-max limit of 200.0 down
        to the measured mean, divided by the distance from that mandatory limit
        down to an ideal value of 90.0, expressed as a percentage, clamped to lie
        between 0.00 and 100.00, and rounded half up to two decimals."

        "a mean above 165.0 g but no more than 200.0 g is an `ADVISORY`"

        Design: Difficulty/dual_variant_calc/condition_index_agronomic_vs_certification_variant_divergence
        """
        field, assessment = _advisory_synthetic_field(client, roster)
        assert_one_decimal(assessment["gmax_mean_value"], 185.0, "gmax_mean_value")
        assert assessment["result"] == "ADVISORY"
        assert_one_decimal(
            field["latest_gmax_mean_value"], 185.0, "Field.latest_gmax_mean_value"
        )

        # (200.0 - 185.0) / (200.0 - 90.0) as a percentage is 13.6363, so the
        # safety component is 13.64 and the blend is
        # 100.00 x 0.50 + 0.00 x 0.20 + 13.64 x 0.30 = 54.092.
        assert_two_decimals(
            field["condition_index_agronomic"], 54.09, "Field.condition_index_agronomic"
        )
        assert_two_decimals(field["age_years"], 10.17, "Field.age_years")
        assert_two_decimals(
            field["cumulative_wear_units"], 0.00, "Field.cumulative_wear_units"
        )
        assert field["warranty_status"] == "EXPIRED"

    def test_certification_variant_collapses_to_its_safety_component(
        self, client, roster
    ):
        """The certification cap, not the weights, produces the divergence.

        "It takes the very same three components as §3.7 — wear, age and safety,
        each rounded to two decimal places first — but weights the wear component
        at 0.20, the age component at 0.20 and the safety component at 0.60, sums
        them and rounds half up to two decimal places, and then applies a cap the
        agronomic variant does not have: the final value is the **lesser** of that
        weighted sum and the safety component alone."

        "Crucially, **both scores are recomputed from scratch at every submission**
        and never carried over from a previous one, because a resubmission is a
        fresh assertion about a world that has moved on."

        Design: Difficulty/dual_variant_calc/condition_index_agronomic_vs_certification_variant_divergence
        """
        field, assessment = _advisory_synthetic_field(client, roster)
        packet = fixtures.open_packet(
            client,
            roster,
            field["id"],
            assessment["id"],
            field["version"],
            competition_season_label="2026-FALL",
        )
        submitted = fixtures.submit_packet(client, roster, packet["id"])

        # The weighted sum would have been 100.00 x 0.20 + 0.00 x 0.20 +
        # 13.64 x 0.60 = 28.184, but the cap pulls it down to the safety
        # component itself.
        assert_two_decimals(
            submitted["condition_index_certification"],
            13.64,
            "CertificationPacket.condition_index_certification",
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            after["condition_index_agronomic"],
            54.09,
            "the agronomic variant is unchanged by the submission",
        )
        assert (
            round(float(submitted["condition_index_certification"]), 2)
            != round(float(after["condition_index_agronomic"]), 2)
        ), "the two variants read the same field data and disagree"


class TestReplacementPriorityVariantDivergence:
    def test_remaining_life_variant_scores_below_the_approval_floor(
        self, client, full_roster
    ):
        """A surface barely past its nominal life earns almost nothing here.

        "The `REMAINING_LIFE` variant scores how far past its nominal service life
        the surface has run. The life deficit is the field's `age_years` minus its
        `expected_life_years`, rounded half up to two decimal places and floored at
        0.00; the score is that deficit multiplied by 6.00 points per year, plus an
        accumulated-usage term equal to the field's `cumulative_wear_units` divided
        by 25.00 but capped at 20.00 points, plus the warranty penalty, all
        rounded half up to two decimal places."

        "Both variants share a warranty penalty: 8.00 points when the field's
        `warranty_status` is `EXPIRED`, and 0.00 otherwise."

        "`APPROVE` additionally requires the budget to be `OPEN`, refusing with
        `ERR_BUDGET_LOCKED`; then that `replacement_priority_score` is at least
        20.00, refusing with `ERR_PLAN_PRIORITY_BELOW_THRESHOLD`; then that
        `plan_funding_amount_cents` does not exceed the budget's
        `available_amount_cents`, refusing with `ERR_BUDGET_INSUFFICIENT`."

        Design: Difficulty/dual_variant_calc/replacement_priority_score_remaining_life_vs_condition_risk_divergence
        """
        field, _assessment = _advisory_synthetic_field(client, full_roster)
        budget = fixtures.authorize_budget(client, full_roster)

        plan = fixtures.draft_plan(
            client,
            full_roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="REMAINING_LIFE",
            planned_install_year=2028,
        )
        # A deficit of 10.17 - 10 = 0.17 years at 6.00 points is 1.02, no wear
        # term at all, plus the 8.00-point expired-warranty penalty.
        assert_two_decimals(
            plan["replacement_priority_score"], 9.02, "replacement_priority_score"
        )
        # 70000 x 65 plus 70000 x 5 disposal is 4900000, which selects 0.07.
        assert plan["plan_funding_amount_cents"] == 5243000
        assert float(plan["replacement_priority_score"]) < 20.00

        fixtures.submit_plan(client, full_roster, plan["id"])
        validate_error(
            client.decide_replacement_plan(
                plan["id"],
                factories.make_plan_decide_payload(
                    decision="APPROVE",
                    decided_by_staff_member_id=full_roster.id_of("director_two"),
                ),
                full_roster.headers_of("director_two"),
            ),
            ApiErrorId.PLAN_PRIORITY_BELOW_THRESHOLD,
            422,
        )

        after_budget = fixtures.read_budget(client, full_roster, budget["id"])
        assert after_budget["committed_amount_cents"] == 0
        assert after_budget["status"] == "OPEN"

    def test_condition_risk_variant_clears_the_approval_floor(
        self, client, full_roster
    ):
        """The same field, priced identically, passes under the other basis.

        "The `CONDITION_RISK` variant ignores nominal life entirely. It counts the
        field's remediation orders whose `severity` is `MANDATORY` and whose
        `opened_at_utc` falls at or after the current instant less a lookback of
        365 days — counted regardless of their current `status`, so orders that
        have since been closed or cancelled still weigh — and the score is 100.00
        minus the field's `condition_index_agronomic`, multiplied by 0.80 points
        per index point, plus 5.00 points per counted mandatory order, plus the
        warranty penalty, rounded half up to two decimal places."

        "The same field can clear the approval floor under one basis and fail it
        under the other, which is exactly why the basis is a recorded decision
        rather than an implementation detail."

        "Hop one is the plan itself moving `SUBMITTED → APPROVED`, with
        `decided_at_utc` and `decided_by_staff_member_id` recorded."

        Design: Difficulty/dual_variant_calc/replacement_priority_score_remaining_life_vs_condition_risk_divergence
        """
        field, _assessment = _advisory_synthetic_field(client, full_roster)
        budget = fixtures.authorize_budget(client, full_roster)

        remaining_life = fixtures.draft_plan(
            client,
            full_roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="REMAINING_LIFE",
            planned_install_year=2028,
        )
        refreshed = fixtures.read_field(client, full_roster, field["id"])
        condition_risk = fixtures.draft_plan(
            client,
            full_roster,
            field["id"],
            budget["id"],
            refreshed["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )

        # (100.00 - 54.09) x 0.80 is 36.728, no mandatory order in the lookback,
        # plus the 8.00-point expired-warranty penalty.
        assert_two_decimals(
            condition_risk["replacement_priority_score"],
            44.73,
            "CONDITION_RISK replacement_priority_score",
        )
        assert_two_decimals(
            remaining_life["replacement_priority_score"],
            9.02,
            "REMAINING_LIFE replacement_priority_score",
        )
        # Only the variant differs; the pricing is identical.
        assert (
            condition_risk["plan_funding_amount_cents"]
            == remaining_life["plan_funding_amount_cents"]
            == 5243000
        )
        assert float(condition_risk["replacement_priority_score"]) >= 20.00

        fixtures.submit_plan(client, full_roster, condition_risk["id"])
        approved = fixtures.decide_plan(
            client, full_roster, condition_risk["id"], decision="APPROVE"
        )
        assert approved["funding_status"] == "APPROVED"
        assert approved["decided_by_staff_member_id"] == full_roster.id_of(
            "director_two"
        )
