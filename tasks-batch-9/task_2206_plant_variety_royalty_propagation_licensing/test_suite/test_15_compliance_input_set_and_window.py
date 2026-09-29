"""Which rows feed the compliance score, and for exactly how long."""

from test_helpers import (
    AUDITOR,
    OFFICER,
    OFFICER_TWO,
    active_agreement,
    add_line_item,
    advance_clock,
    assert_instant_equals,
    create_genetic_test_payload,
    create_variety,
    draft_report,
    licensed_quota,
    sampled_case,
    validate_success,
)


class TestASubmittedLateReportIsOutsideThePenaltySet:
    """The lateness flag is set at submission; the points land at acceptance."""

    def _submitted_late_report(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=20000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Everly Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "EV",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Everly Nursery",
            home_territory_code="US-WA",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-05T00:00:00Z",
            due_at="2026-08-10T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 100)
        advance_clock(api, "2026-08-15T00:00:00Z")
        chain["report_id"] = report["id"]
        chain["submitted"] = validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        return chain

    def test_submitting_after_the_deadline_flags_the_report_and_prices_it(self, api):
        """The submission instant is strictly later than the deadline, so the flag
        is raised, and the reported basis prices the single 100-plant line at the
        TIER_B rate of 35.0000.

        PRD 3.7: "Submission stamps `submitted_at` with the logical clock's present instant and sets `is_late` to true exactly when `submitted_at` is strictly later than `due_at` — a submission landing exactly at `due_at` is on time."

        Design: Corner/calculations/compliance_score_excludes_a_submitted_but_unaccepted_late_report
        """
        chain = self._submitted_late_report(api)
        submitted = chain["submitted"]

        assert submitted["review_status"] == "SUBMITTED"
        assert_instant_equals(submitted["submitted_at"], "2026-08-15T00:00:00Z",
                              "submitted_at")
        assert submitted["is_late"] is True
        assert submitted["provisional_total_cents"] == 3500

    def test_the_raised_flag_alone_costs_the_propagator_nothing(self, api):
        """A late report that has not been accepted is outside the penalty input
        set, so both scores are still pristine and no suspension has fired.

        PRD 2.11: "A late report that has been submitted but not yet accepted contributes nothing."

        Design: Corner/calculations/compliance_score_excludes_a_submitted_but_unaccepted_late_report
        """
        chain = self._submitted_late_report(api)

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 100
        assert propagator["lifetime_compliance_score"] == 100
        assert validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )["status"] == "ACTIVE"

    def test_the_six_points_materialize_only_when_the_report_is_accepted(self, api):
        """Acceptance brings the report into the penalty input set, and the late
        filing then costs exactly six points on both scores.

        PRD 2.11: "A royalty report that was submitted late and has been accepted contributes **6 points**, attributed to the instant the report was submitted."

        Design: Corner/calculations/compliance_score_excludes_a_submitted_but_unaccepted_late_report
        """
        chain = self._submitted_late_report(api)

        validate_success(api.accept_royalty_report(chain["report_id"], OFFICER_TWO))

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 94
        assert propagator["lifetime_compliance_score"] == 94


class TestTheRollingWindowLowerBoundIsExclusive:
    """A 30-point match stamped 2026-08-25, watched across day 119 and day 120."""

    def _confirmed_match_on_the_twenty_fifth(self, api):
        variety = create_variety(
            api, denomination="Kingfisher Bramble", species="Rubus idaeus",
            breeder_code="KF", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Kingfisher Nursery", home_territory_code="US-WA",
        )
        case = sampled_case(
            api, variety["id"], sampled_unit_count=30,
            suspected_propagator_id=chain["propagator_id"],
            market_survey_ref="MS-2026-060",
        )
        validate_success(
            api.create_genetic_test(
                case["id"], create_genetic_test_payload(0.9600), AUDITOR
            ),
            201,
        )
        advance_clock(api, "2026-08-25T00:00:00Z", AUDITOR)
        chain["concluded_case"] = validate_success(
            api.conclude_testing(case["id"], AUDITOR)
        )
        return chain

    def test_the_confirmed_match_lands_thirty_points_at_the_conclusion_instant(self, api):
        """Concluding in a confirmed match against a named suspect is the penalty
        event, and it is attributed to the instant of that conclusion.

        PRD 2.11: "A surveillance case whose testing concluded in a confirmed genetic match against a named suspect contributes **30 points**, attributed to the instant testing was concluded."

        Design: Corner/calculations/compliance_rolling_window_lower_bound_is_exclusive_at_exactly_one_hundred_twenty_days
        """
        chain = self._confirmed_match_on_the_twenty_fifth(api)

        assert chain["concluded_case"]["status"] == "MATCH_CONFIRMED"
        assert_instant_equals(chain["concluded_case"]["concluded_at"],
                              "2026-08-25T00:00:00Z", "concluded_at")

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 70
        assert propagator["lifetime_compliance_score"] == 70

    def test_one_day_short_of_the_window_the_event_still_counts(self, api):
        """At 2026-12-22 the lower bound is 2026-08-24, which is strictly before the
        event, so the event is still inside the half-open window and the rolling
        score is still depressed.

        PRD 2.11: "The rolling window is **half-open**. Take the logical clock's present instant, subtract 120 days, and call that the lower bound; an event contributes when its event instant is **strictly after** that lower bound and **at or before** the present instant."

        Design: Corner/calculations/compliance_rolling_window_lower_bound_is_exclusive_at_exactly_one_hundred_twenty_days
        """
        chain = self._confirmed_match_on_the_twenty_fifth(api)

        advance_clock(api, "2026-12-22T00:00:00Z", AUDITOR)

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 70
        assert propagator["lifetime_compliance_score"] == 70
        assert validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )["status"] == "ACTIVE"

    def test_at_exactly_one_hundred_twenty_days_the_event_has_aged_out(self, api):
        """At 2026-12-23 the lower bound equals the event instant, and because the
        bound is exclusive the rolling score recovers to 100 while the lifetime
        score, which ignores age, stays at 70.

        PRD 2.11: "An event landing exactly 120 days before now has therefore aged out, while an event landing exactly at now is in."

        Design: Corner/calculations/compliance_rolling_window_lower_bound_is_exclusive_at_exactly_one_hundred_twenty_days
        """
        chain = self._confirmed_match_on_the_twenty_fifth(api)
        advance_clock(api, "2026-12-22T00:00:00Z", AUDITOR)

        sweep = advance_clock(api, "2026-12-23T00:00:00Z", AUDITOR)
        assert sweep["compliance_recompute_count"] >= 1

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 100
        assert propagator["lifetime_compliance_score"] == 70
