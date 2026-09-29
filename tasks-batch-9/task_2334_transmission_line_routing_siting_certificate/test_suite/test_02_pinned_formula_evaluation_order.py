"""Formulas whose steps must fire in the order the contract pins them.

A per-segment cap applied before mileage and the voltage multiplier, two
separate roundings on a negotiated offer, and an escrow tier chosen from the
mitigation base alone.
"""

import pytest

from test_helpers import assert_score
from test_helpers import fixtures as fx

#: A 5.0-mile segment rated 5/5/5/5, whose raw base rating of 5.00 is above the
#: 4.50 per-segment cap, followed by a 2.0-mile segment rated 0/0/0/0.
RIDGE_SEGMENTS = (
    dict(
        sequence_index=1, miles=5.0, land_use_rating=5, environmental_rating=5,
        cultural_rating=5, engineering_rating=5, county="Harlan", crew_capacity=12,
        survey_status="FIELD_VERIFIED", habitat_blackout=False, federal_crossing_kind="NONE",
    ),
    dict(
        sequence_index=2, miles=2.0, land_use_rating=0, environmental_rating=0,
        cultural_rating=0, engineering_rating=0, county="Boone", crew_capacity=12,
        survey_status="FIELD_VERIFIED", habitat_blackout=False, federal_crossing_kind="NONE",
    ),
)


def _map_ridge_corridor(api, voltage_class):
    """Draw and map the ridge corridor on a project of the given voltage class."""
    ctx = {}
    fx.create_project(
        api, ctx,
        name=f"Ridge crossing {voltage_class}",
        voltage_class=voltage_class,
    )
    fx.create_route(api, ctx, key="routeC", label="Route C - steep ridge", kind="PROPOSED")
    for index, spec in enumerate(RIDGE_SEGMENTS, start=1):
        fx.add_segment(api, ctx, "routeC", f"segC{index}", **dict(spec))
    route = fx.run_mapping(api, ctx, "routeC", note="Steep ridge corridor mapped")
    return ctx, route


class TestConstraintScoreCapOrder:
    """Where the 4.50 cap sits relative to mileage and the voltage multiplier."""

    def test_per_segment_cap_bites_before_mileage_and_the_multiplier(self, api):
        """PRD §3.2: "Cap that base rating at 4.50 per segment — the cap is
        applied to the base before mileage enters, never afterwards."

        Design: Difficulty/combinatorial_formula/route_score_cap_and_voltage_multiplier_nonlinear_mode_a
        """
        _, route = _map_ridge_corridor(api, "KV_500")

        assert_score(route["constraint_score_certified"], 29.25, "constraint_score_certified")
        assert_score(route["constraint_score_preliminary"], 29.25, "constraint_score_preliminary")
        assert float(route["constraint_score_certified"]) != pytest.approx(32.50, abs=0.005), (
            "Capping the mileage-scaled, voltage-adjusted product instead of the base "
            f"rating would give 32.50; got {route['constraint_score_certified']}"
        )
        assert_score(route["total_miles"], 7.0, "total_miles")
        assert_score(route["constraint_density_certified"], 4.18, "constraint_density_certified")

    @pytest.mark.parametrize(
        "voltage_class, expected_score, expected_density",
        [
            ("KV_138", 22.50, 3.21),
            ("KV_345", 25.88, 3.70),
            ("KV_500", 29.25, 4.18),
        ],
    )
    def test_voltage_multiplier_scales_the_already_capped_base(
        self, api, voltage_class, expected_score, expected_density
    ):
        """PRD §3.2: "Start from the project's voltage multiplier: 1.00 for
        `KV_138`, 1.15 for `KV_345`, and 1.30 for `KV_500`."

        Design: Difficulty/combinatorial_formula/route_score_cap_and_voltage_multiplier_nonlinear_mode_a
        """
        _, route = _map_ridge_corridor(api, voltage_class)

        assert_score(
            route["constraint_score_certified"],
            expected_score,
            f"constraint_score_certified on a {voltage_class} project",
        )
        assert_score(
            route["constraint_density_certified"],
            expected_density,
            f"constraint_density_certified on a {voltage_class} project",
        )
        assert_score(route["total_miles"], 7.0, "total_miles")


class TestNegotiatedOfferRoundingOrder:
    """Two separate roundings: the land value, then the escalated base offer."""

    def test_second_round_offer_keeps_the_two_roundings_apart(self, api):
        """PRD §3.8: "Collapsing the two roundings into a single final rounding
        changes the answer by a cent on fractional-acre tracts."

        Design: Difficulty/combinatorial_formula/easement_offer_rounding_order_pinned_mode_b
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_rejected_tract(api, ctx, rounds=1)
        tract = fx.extend_offer(api, ctx, "tract1", note="Sweetened offer")

        assert tract["offered_compensation_cents"] == 4371576, (
            "Rounding the land value to 3913406 before adding structure damages and "
            f"escalating gives 4371576 cents, got {tract['offered_compensation_cents']}"
        )
        assert tract["offered_compensation_cents"] != 4371577, (
            "4371577 is the answer produced by carrying the fractional land value "
            "through the escalation and rounding once at the end"
        )
        assert tract["offer_round"] == 2, (
            f"This is the second offer on the tract, got offer_round {tract['offer_round']}"
        )
        assert tract["acquisition_status"] == "OFFERED", (
            "A sweetened offer moves the tract REJECTED -> OFFERED, got "
            f"{tract['acquisition_status']}"
        )
        assert tract["committed_cents"] == 0, (
            "An outstanding offer commits nothing, got committed_cents "
            f"{tract['committed_cents']}"
        )

    def test_third_round_escalation_multiplies_the_rounded_base_offer(self, api):
        """PRD §3.8: "Then apply the escalation factor for the round just entered
        — 1.00 for the first offer, 1.05 for the second, 1.12 for the third —
        multiplying it by the already-rounded base offer".

        Design: Difficulty/combinatorial_formula/easement_offer_rounding_order_pinned_mode_b
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_rejected_tract(
            api, ctx, rounds=2,
            parcel_number="H-104-27", acres=12.35, per_acre_value_cents=487_500,
            easement_factor=0.65, structure_damages_cents=250_005,
        )
        tract = fx.extend_offer(api, ctx, "tract1", note="Final offer before condemnation")

        assert tract["offered_compensation_cents"] == 4663020, (
            "The base offer of 4163411 cents escalated by 1.12 rounds to 4663020, got "
            f"{tract['offered_compensation_cents']}"
        )
        assert tract["offered_compensation_cents"] != 4663021, (
            "4663021 is the answer produced by collapsing the land-value rounding into "
            "the final one"
        )
        assert tract["offer_round"] == 3, (
            f"This is the third and last permitted offer, got {tract['offer_round']}"
        )


class TestEscrowRequirementEvaluationOrder:
    """The tier from the base alone, the rate on the base alone, then the sum."""

    def test_tier_one_requirement_adds_contingency_and_surcharge_last(self, api):
        """PRD §3.7: "Applying the contingency rate to the base plus surcharge, or
        re-deriving the tier from a running total, are both wrong."

        Design: Difficulty/combinatorial_formula/escrow_requirement_evaluation_order_pinned_mode_c
        """
        ctx = fx.setup_issued_certificate(api)
        certificate = fx.read_certificate(api, ctx["cert"])

        assert certificate["escrow_tier"] == "TIER_1", (
            "A mitigation base of 480000000 cents is below the 500000000 TIER_2 floor, "
            f"got {certificate['escrow_tier']}"
        )
        assert certificate["contingency_cents"] == 48000000, (
            "0.10 of the mitigation base alone is 48000000 cents, got "
            f"{certificate['contingency_cents']}"
        )
        assert certificate["condition_surcharge_cents"] == 5000000, (
            "Two of the three conditions carry severity_weight 4 or greater, so the "
            f"surcharge is 5000000 cents, got {certificate['condition_surcharge_cents']}"
        )
        assert certificate["escrow_required_cents"] == 533000000, (
            "480000000 + 48000000 + 5000000 = 533000000 cents, got "
            f"{certificate['escrow_required_cents']}"
        )
        assert certificate["escrow_required_cents"] != 533500000, (
            "533500000 is the answer produced by applying the contingency rate to the "
            "base plus the surcharge"
        )
        assert certificate["posture"] == "ACTIVE", (
            f"A fresh certificate opens at posture ACTIVE, got {certificate['posture']}"
        )
        assert_score(
            certificate["compliance_index_rolling"], 100.00, "compliance_index_rolling"
        )

    def test_tier_two_rate_never_sees_the_condition_surcharge(self, api):
        """PRD §3.7: "take the tier's contingency rate — 0.10 for `TIER_1`, 0.14
        for `TIER_2`, 0.18 for `TIER_3` — multiply it by the mitigation base and
        only the mitigation base".

        Design: Difficulty/combinatorial_formula/escrow_requirement_evaluation_order_pinned_mode_c
        """
        ctx = fx.setup_issued_certificate(api, mitigation_base_cents=1_900_000_000)
        certificate = fx.read_certificate(api, ctx["cert"])

        assert certificate["escrow_tier"] == "TIER_2", (
            "1900000000 cents sits at or above 500000000 and below 2000000000, got "
            f"{certificate['escrow_tier']}"
        )
        assert certificate["contingency_cents"] == 266000000, (
            "0.14 of 1900000000 is 266000000 cents, got "
            f"{certificate['contingency_cents']}"
        )
        assert certificate["escrow_required_cents"] == 2171000000, (
            "1900000000 + 266000000 + 5000000 = 2171000000 cents, got "
            f"{certificate['escrow_required_cents']}"
        )
        assert certificate["escrow_required_cents"] != 2171700000, (
            "2171700000 is the answer produced by applying 0.14 to the base plus the "
            "surcharge"
        )
        assert certificate["escrow_required_cents"] != 2247000000, (
            "2247000000 is the answer produced by re-deriving the tier from the running "
            "total and applying the TIER_3 rate"
        )
