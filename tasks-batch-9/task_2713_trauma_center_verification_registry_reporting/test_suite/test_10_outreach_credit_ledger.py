"""The outreach credit-hour ledger: quantization order, recomputation, and read freshness.

Credit hours are weighted by activity kind and then rounded to a quarter hour, and the
order of those two steps is observable in the center's running total.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ActivityKind,
    ApiClient,
    CycleType,
    DIRECTOR_1_USER_ID,
    DesignationLevel,
    VerifiedStatus,
    assert_decimal,
    assert_quarter_hour_multiple,
    assert_readiness_read,
    fixtures as fx,
    make_trauma_program_manager_headers,
)


class TestLedgerQuantizationOrder:
    """Each activity is rounded on its own before it joins the total."""

    def test_the_ledger_quantizes_every_activity_before_adding_it(
        self, api: ApiClient
    ) -> None:
        """Per-activity rounding lands the total on 3.50 rather than the pooled 3.25.

        Design: Difficulty/combinatorial_formula/outreach_ledger_quantizes_each_activity_before_summing
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Cedar Falls Trauma",
            state_code="IA",
            designation_level=DesignationLevel.LEVEL_II,
        )
        prevention = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.INJURY_PREVENTION,
            event_date="2026-06-10T17:00:00Z",
            credit_hours=1.10,
            audience_count=40,
        )
        education = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.PROFESSIONAL_EDUCATION,
            event_date="2026-06-17T17:00:00Z",
            credit_hours=1.15,
            audience_count=25,
        )
        community = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.COMMUNITY_OUTREACH,
            event_date="2026-06-24T17:00:00Z",
            credit_hours=0.75,
            audience_count=90,
        )

        fx.verify_outreach(api, prevention)
        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            1.75,
            "outreach_credit_hours_ytd",
        )
        fx.verify_outreach(api, education)
        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            3.00,
            "outreach_credit_hours_ytd",
        )
        fx.verify_outreach(api, community)
        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            3.50,
            "outreach_credit_hours_ytd",
        )

    def test_each_activity_reports_its_own_quantized_weight(self, api: ApiClient) -> None:
        """The three weights are 1.75, 1.25 and 0.50, each a quarter-hour multiple.

        Design: Difficulty/combinatorial_formula/outreach_ledger_quantizes_each_activity_before_summing
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Cedar Falls Trauma",
            state_code="IA",
            designation_level=DesignationLevel.LEVEL_II,
        )
        expected = {
            ActivityKind.INJURY_PREVENTION: 1.75,
            ActivityKind.PROFESSIONAL_EDUCATION: 1.25,
            ActivityKind.COMMUNITY_OUTREACH: 0.50,
        }
        activities = fx.verified_outreach_ledger(
            api,
            center["id"],
            [
                {
                    "activity_kind": ActivityKind.INJURY_PREVENTION,
                    "event_date": "2026-06-10T17:00:00Z",
                    "credit_hours": 1.10,
                    "audience_count": 40,
                },
                {
                    "activity_kind": ActivityKind.PROFESSIONAL_EDUCATION,
                    "event_date": "2026-06-17T17:00:00Z",
                    "credit_hours": 1.15,
                    "audience_count": 25,
                },
                {
                    "activity_kind": ActivityKind.COMMUNITY_OUTREACH,
                    "event_date": "2026-06-24T17:00:00Z",
                    "credit_hours": 0.75,
                    "audience_count": 90,
                },
            ],
        )

        for activity in activities:
            assert_quarter_hour_multiple(activity["weighted_credit_hours"])
            assert_decimal(
                activity["weighted_credit_hours"],
                expected[activity["activity_kind"]],
                "weighted_credit_hours",
            )
            assert activity["verified_status"] == VerifiedStatus.VERIFIED
            assert activity["reviewed_by_user_id"] == DIRECTOR_1_USER_ID


class TestLedgerRecomputationWithoutDrift:
    """Crossing verified and rejected repeatedly must not accumulate rounding error."""

    def test_verify_reject_verify_returns_the_ledger_to_its_exact_value(
        self, api: ApiClient
    ) -> None:
        """The total lands on 1.75, 0.00 and 1.75, and the score on 84.62, 82.00, 84.62.

        Design: Difficulty/compensating_invariant/outreach_rejection_returns_credit_ledger_without_drift
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Fairhaven Trauma",
            state_code="VT",
            designation_level=DesignationLevel.LEVEL_III,
        )
        cycle = fx.create_cycle(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-11-05T13:00:00Z",
        )
        activity = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.INJURY_PREVENTION,
            event_date="2026-06-14T00:00:00Z",
            credit_hours=1.15,
            audience_count=60,
        )

        fx.verify_outreach(api, activity)
        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            1.75,
            "outreach_credit_hours_ytd",
        )
        assert_readiness_read(
            fx.get_readiness(api, cycle["id"]),
            None,
            deficiency_penalty=0,
            outreach_penalty=15.38,
            pi_penalty=0,
            readiness_score=84.62,
            submit_eligible=True,
        )

        fx.reject_outreach(api, activity)
        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            0.00,
            "outreach_credit_hours_ytd",
        )
        assert_readiness_read(
            fx.get_readiness(api, cycle["id"]),
            None,
            deficiency_penalty=0,
            outreach_penalty=18.00,
            pi_penalty=0,
            readiness_score=82.00,
            submit_eligible=True,
        )

        fx.verify_outreach(api, activity)
        assert_decimal(
            fx.get_center(api, center["id"])["outreach_credit_hours_ytd"],
            1.75,
            "outreach_credit_hours_ytd",
        )
        assert_readiness_read(
            fx.get_readiness(api, cycle["id"]),
            None,
            deficiency_penalty=0,
            outreach_penalty=15.38,
            pi_penalty=0,
            readiness_score=84.62,
            submit_eligible=True,
        )

    def test_the_per_activity_weight_is_independent_of_the_verified_status(
        self, api: ApiClient
    ) -> None:
        """The stored weight stays 1.75 through every crossing of the ledger.

        Design: Difficulty/compensating_invariant/outreach_rejection_returns_credit_ledger_without_drift
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Fairhaven Trauma",
            state_code="VT",
            designation_level=DesignationLevel.LEVEL_III,
        )
        activity = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.INJURY_PREVENTION,
            event_date="2026-06-14T00:00:00Z",
            credit_hours=1.15,
            audience_count=60,
        )
        assert_decimal(activity["weighted_credit_hours"], 1.75, "weighted_credit_hours")

        for step, expected_status in (
            (fx.verify_outreach, VerifiedStatus.VERIFIED),
            (fx.reject_outreach, VerifiedStatus.REJECTED),
            (fx.verify_outreach, VerifiedStatus.VERIFIED),
        ):
            step(api, activity)
            current = fx.get_outreach_activity(api, center["id"], activity["id"])
            assert current["verified_status"] == expected_status
            assert_decimal(
                current["weighted_credit_hours"], 1.75, "weighted_credit_hours"
            )


class TestLedgerReadFreshness:
    """A verified activity is visible to the very next read."""

    def test_verified_hours_appear_on_the_next_read_with_no_lag(
        self, api: ApiClient
    ) -> None:
        """The center reads 0.00 while the activity is logged and 3.50 straight after verification.

        Design: Corner/consistency_model/verified_outreach_hours_are_visible_to_the_next_read_with_no_lag
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Saltmarsh Trauma",
            state_code="SC",
            designation_level=DesignationLevel.LEVEL_II,
        )
        cycle = fx.create_cycle(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-11-10T13:00:00Z",
        )
        activity = fx.log_outreach(
            api,
            center["id"],
            activity_kind=ActivityKind.PROFESSIONAL_EDUCATION,
            event_date="2026-06-18T00:00:00Z",
            credit_hours=3.600,
            audience_count=42,
        )
        assert_decimal(activity["weighted_credit_hours"], 3.50, "weighted_credit_hours")
        assert activity["verified_status"] == VerifiedStatus.LOGGED

        before = get_success_data(
            api.get_trauma_center(
                center["id"], make_trauma_program_manager_headers(center["id"])
            )
        )
        assert_decimal(
            before["outreach_credit_hours_ytd"], 0.00, "outreach_credit_hours_ytd"
        )

        verified = fx.verify_outreach(api, activity)
        assert verified["verified_status"] == VerifiedStatus.VERIFIED
        assert verified["reviewed_by_user_id"] == DIRECTOR_1_USER_ID

        after = get_success_data(
            api.get_trauma_center(
                center["id"], make_trauma_program_manager_headers(center["id"])
            )
        )
        assert_decimal(
            after["outreach_credit_hours_ytd"], 3.50, "outreach_credit_hours_ytd"
        )

        assert_readiness_read(
            fx.get_readiness(api, cycle["id"]),
            None,
            deficiency_penalty=0,
            outreach_penalty=12.75,
            pi_penalty=0,
            readiness_score=87.25,
            submit_eligible=True,
        )
