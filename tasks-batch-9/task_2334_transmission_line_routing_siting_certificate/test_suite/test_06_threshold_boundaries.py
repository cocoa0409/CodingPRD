"""Values sitting exactly on a declared threshold, and one step either side.

The 1.1500 need margin, the crew ceiling that binds at equality, and the escrow
tier floors that move on a single cent.
"""

import pytest

from test_helpers import (
    DEV_MILO,
    ApiErrorId,
    assert_ratio,
    assert_score,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _study_with_nonwires_capex(api, capex_cents):
    """A screened study whose only non-wires competitor carries the given capex."""
    ctx = {}
    fx.create_project(api, ctx)
    study = get_success_data(
        api.create_planning_study(f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS)
    )
    ctx["study"] = study["id"]
    alt1 = get_success_data(
        api.create_alternative(
            f.alternative_payload(
                ctx["study"], kind="TRANSMISSION",
                description="New 345kV single-circuit line",
                capex_cents=80_000_000_000, deliverable_mw=400,
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
    )
    alt2 = get_success_data(
        api.create_alternative(
            f.alternative_payload(
                ctx["study"], kind="NON_TRANSMISSION",
                description="Battery storage plus demand response portfolio",
                capex_cents=capex_cents, deliverable_mw=200,
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
    )
    ctx["alt1"], ctx["alt2"] = alt1["id"], alt2["id"]
    fx.screen_in_both_alternatives(api, ctx)
    return ctx


class TestNeedMarginThreshold:
    """A need margin of exactly 1.1500 certifies; 1.1250 does not."""

    def test_need_margin_of_exactly_the_threshold_certifies_the_study(self, api):
        """PRD §3.1: "Fifth, the threshold is applied to that rounded four-decimal
        ratio: a value of at least 1.1500 certifies the study, and anything below
        it does not."

        Design: Difficulty/boundary_precision_check/need_margin_at_exact_threshold_certifies_study
        """
        ctx = _study_with_nonwires_capex(api, 46_000_000_000)

        study = validate_success(
            api.certify_study_sufficiency(
                ctx["study"], f.sufficiency_certification_payload(),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(
            study["transmission_levelized_cents_per_mw"],
            200000000.00,
            "transmission_levelized_cents_per_mw",
        )
        assert_ratio(study["benefit_ratio"], 1.0000, "benefit_ratio")
        assert_ratio(study["need_margin_ratio"], 1.1500, "need_margin_ratio")
        assert study["status"] == "CERTIFIED_SUFFICIENT", (
            "A ratio of exactly 1.1500 clears an at-least threshold, got "
            f"{study['status']}"
        )
        assert study["selected_nta_alternative_id"] == ctx["alt2"], (
            "The only eligible non-wires candidate is the selected competitor"
        )
        assert study["certified_by_user_id"] == DEV_MILO, (
            f"The certifying developer is recorded, got {study['certified_by_user_id']!r}"
        )
        assert study["alternatives_screened_in_count"] == 2, (
            f"Both alternatives were screened in, got "
            f"{study['alternatives_screened_in_count']}"
        )

    def test_need_margin_below_the_threshold_lands_the_study_insufficient(self, api):
        """PRD §3.1: "A ratio at or above the threshold moves the study
        `ALTERNATIVES_ANALYZED → CERTIFIED_SUFFICIENT`; a ratio below it moves the
        study `ALTERNATIVES_ANALYZED → INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/need_margin_at_exact_threshold_certifies_study
        """
        ctx = _study_with_nonwires_capex(api, 45_000_000_000)

        study = validate_success(
            api.certify_study_sufficiency(
                ctx["study"], f.sufficiency_certification_payload(),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            ),
            expected_status=201,
        )

        assert_ratio(study["need_margin_ratio"], 1.1250, "need_margin_ratio")
        assert study["status"] == "INSUFFICIENT", (
            f"A ratio of 1.1250 is below the 1.1500 threshold, got {study['status']}"
        )
        assert study["selected_nta_alternative_id"] == ctx["alt2"], (
            "The selector still runs and records its winner on the failing path"
        )
        assert study["certified_by_user_id"] == DEV_MILO, (
            "The acting user is recorded in either direction, got "
            f"{study['certified_by_user_id']!r}"
        )

    def test_raw_quotient_rounding_up_to_the_threshold_still_certifies(self, api):
        """PRD §2.8: "A need margin ratio whose raw quotient is 1.149975 rounds to
        1.1500 and therefore passes a threshold of 1.1500."

        Design: Difficulty/boundary_precision_check/need_margin_at_exact_threshold_certifies_study
        """
        ctx = _study_with_nonwires_capex(api, 45_999_000_000)

        study = validate_success(
            api.certify_study_sufficiency(
                ctx["study"], f.sufficiency_certification_payload(),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            ),
            expected_status=201,
        )

        assert_ratio(study["need_margin_ratio"], 1.1500, "need_margin_ratio")
        assert study["status"] == "CERTIFIED_SUFFICIENT", (
            "The threshold is compared against the rounded four-decimal ratio, got "
            f"{study['status']}"
        )


class TestEffectiveCrewLimitBoundary:
    """The order's crew_limit of 9 binds below the segment's capacity of 12."""

    def test_aggregate_crew_exactly_at_the_effective_limit_is_accepted(self, api):
        """PRD §3.9: "form the effective limit as the smaller of the segment's
        `crew_capacity` and the lowest `crew_limit` among the `ACTIVE`
        `CREW_LIMIT` conditions on the certificate".

        Design: Difficulty/boundary_precision_check/aggregate_crew_exactly_at_effective_limit_accepted
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)

        activity = validate_success(
            api.create_construction_activity(
                f.construction_activity_payload(
                    ctx["cert"], ctx["seg1"], activity_kind="FOUNDATION", crew_count=3,
                    window_start_at="2027-08-05T00:00:00Z",
                    window_end_at="2027-08-10T00:00:00Z",
                ),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert activity["status"] == "SCHEDULED", (
            f"The accepted activity opens at SCHEDULED, got {activity['status']}"
        )
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 9, (
            f"6 plus 3 sits exactly on the effective limit of 9, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["crew_capacity"] == 12, (
            "The segment's own capacity is the looser of the two ceilings, got "
            f"{segment['crew_capacity']}"
        )

    def test_aggregate_crew_one_over_the_effective_limit_is_refused(self, api):
        """PRD §3.9: "refuse the request with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP
        422) if that total exceeds the effective limit".

        Design: Difficulty/boundary_precision_check/aggregate_crew_exactly_at_effective_limit_accepted
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)

        response = api.create_construction_activity(
            f.construction_activity_payload(
                ctx["cert"], ctx["seg1"], activity_kind="FOUNDATION", crew_count=4,
                window_start_at="2027-08-05T00:00:00Z",
                window_end_at="2027-08-10T00:00:00Z",
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.CREW_CAPACITY_EXCEEDED, expected_status=422)

        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 6, (
            "The refused activity commits no crew slots, got "
            f"{segment['committed_crew_count']}"
        )


class TestEscrowTierFloors:
    """The tier boundaries are exclusive below and inclusive at the floor."""

    def test_one_cent_below_the_tier_2_floor_stays_in_tier_1(self, api):
        """PRD §3.7: "First, select `escrow_tier` from `mitigation_base_cents`
        **alone**: a base below five million dollars, that is below 500,000,000
        cents, is `TIER_1`".

        Design: Difficulty/boundary_precision_check/escrow_tier_one_cent_below_tier_2_floor_stays_tier_1
        """
        ctx = fx.setup_issued_certificate(api, mitigation_base_cents=499_999_999)
        certificate = fx.read_certificate(api, ctx["cert"])

        assert certificate["escrow_tier"] == "TIER_1", (
            f"499999999 cents is one cent below the TIER_2 floor, got "
            f"{certificate['escrow_tier']}"
        )
        assert certificate["contingency_cents"] == 50000000, (
            "0.10 of 499999999 is 49999999.9, which rounds half up to 50000000 cents, "
            f"got {certificate['contingency_cents']}"
        )
        assert certificate["escrow_required_cents"] == 554999999, (
            "499999999 + 50000000 + 5000000 = 554999999 cents, got "
            f"{certificate['escrow_required_cents']}"
        )
        assert certificate["escrow_required_cents"] != 575000000, (
            "575000000 is the TIER_2 answer, which a one-cent-lower base must not reach"
        )

    @pytest.mark.parametrize(
        "mitigation_base_cents, expected_tier, expected_contingency, expected_required",
        [
            (500_000_000, "TIER_2", 70_000_000, 575_000_000),
            (1_999_999_999, "TIER_2", 280_000_000, 2_284_999_999),
            (2_000_000_000, "TIER_3", 360_000_000, 2_365_000_000),
        ],
    )
    def test_tier_floors_are_inclusive_at_the_floor_itself(
        self, api, mitigation_base_cents, expected_tier, expected_contingency,
        expected_required,
    ):
        """PRD §3.7: "a base below twenty million dollars, that is below
        2,000,000,000 cents, is `TIER_2`; anything at or above that is `TIER_3`."

        Design: Difficulty/boundary_precision_check/escrow_tier_one_cent_below_tier_2_floor_stays_tier_1
        """
        ctx = fx.setup_issued_certificate(api, mitigation_base_cents=mitigation_base_cents)
        certificate = fx.read_certificate(api, ctx["cert"])

        assert certificate["escrow_tier"] == expected_tier, (
            f"A mitigation base of {mitigation_base_cents} cents belongs to "
            f"{expected_tier}, got {certificate['escrow_tier']}"
        )
        assert certificate["contingency_cents"] == expected_contingency, (
            f"The tier rate applied to the base alone gives {expected_contingency} "
            f"cents, got {certificate['contingency_cents']}"
        )
        assert certificate["escrow_required_cents"] == expected_required, (
            f"base plus contingency plus the 5000000 surcharge is {expected_required} "
            f"cents, got {certificate['escrow_required_cents']}"
        )
