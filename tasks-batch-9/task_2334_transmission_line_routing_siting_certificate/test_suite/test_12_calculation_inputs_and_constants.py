"""Which rows a formula is allowed to read, and the constants it applies.

Route scores that stop at their own corridor, a selector pool that ignores a
screened-out portfolio, a deduction rounded to two places, and the slack
threshold read strictly.
"""

from test_helpers import (
    ApiErrorId,  # noqa: F401  (registers the error/status map on import)
    assert_ratio,
    assert_score,
    assert_timestamp_equals,
    get_success_data,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestRouteScoreInputSet:
    """A mapping run reads only the segments of the route it was run on."""

    def test_mapping_the_alternate_leaves_the_proposed_corridor_untouched(self, api):
        """PRD §3.2: "Then walk the route's segments in ascending `sequence_index`
        order — every segment on the route participates, with no filter on state, so
        segments added while the route was still a draft count in full."

        Design: Corner/calculations/route_score_input_set_excludes_other_routes_segments
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.build_route_a(api, ctx)
        fx.create_route(api, ctx, key="routeB", label="Route B - ridge line",
                        kind="ALTERNATE")
        for index, spec in enumerate(fx.ROUTE_B_SEGMENTS, start=1):
            fx.add_segment(api, ctx, "routeB", f"segB{index}", **dict(spec))

        route_b = validate_success(
            api.run_constraint_mapping(
                ctx["routeB"],
                f.constraint_mapping_payload(
                    mapping_note="Alternate fully field verified"
                ),
                fx.ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(route_b["constraint_score_certified"], 17.48, "routeB certified score")
        assert_score(route_b["total_miles"], 12.0, "routeB total_miles")
        assert_score(
            route_b["constraint_density_certified"], 1.46, "routeB certified density"
        )
        route_a = fx.read_route(api, ctx["routeA"])
        assert_score(route_a["constraint_score_certified"], 69.58, "routeA certified score")
        assert_score(
            route_a["constraint_score_preliminary"], 67.28, "routeA preliminary score"
        )
        assert_score(
            route_a["constraint_density_certified"], 3.48, "routeA certified density"
        )
        assert_score(route_a["total_miles"], 20.0, "routeA total_miles")


class TestDeductionPrecision:
    """The deduction and both indices carry exactly two decimal places."""

    def test_minor_finding_on_a_weight_two_condition_deducts_four_point_eight(self, api):
        """PRD §3.9: "Start from the severity's base points — 4 for `MINOR`, 12 for
        `MAJOR`, 30 for `SEVERE` — then scale it by a weighting factor built from the
        condition's `severity_weight`: subtract 1 from that weight, multiply the
        remainder by 0.2, add 1, and multiply the base points by the result."

        Design: Corner/calculations/minor_finding_deduction_rounds_to_two_decimals
        """
        ctx = fx.setup_issued_certificate(api)

        finding = validate_success(
            api.create_nonconformance(
                f.nonconformance_payload(
                    ctx["cert"], ctx["cond2"], severity="MINOR",
                    observation="Cultural monitor absent for one shift",
                ),
                fx.COMPLIANCE_MONITOR_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(finding["deduction_points"], 4.80, "deduction_points")
        assert finding["status"] == "OPEN", (
            f"A new finding opens at OPEN, got {finding['status']}"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 95.20, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 95.20,
            "compliance_index_cumulative",
        )
        assert certificate["posture"] == "ACTIVE", (
            f"95.20 is above both floors, got {certificate['posture']}"
        )
        assert fx.read_condition(api, ctx["cond2"])["status"] == "VIOLATED", (
            "The referenced condition moves ACTIVE -> VIOLATED"
        )
        assert fx.read_condition(api, ctx["cond1"])["status"] == "ACTIVE", (
            "An unrelated condition is untouched by the finding"
        )


class TestNonWiresSelectorPool:
    """The selector pool is filtered on kind and screening status together."""

    def test_a_screened_out_portfolio_never_enters_the_selector_pool(self, api):
        """PRD §3.1: "eligible candidates are the alternatives on this study whose
        `kind` is `NON_TRANSMISSION` or `HYBRID` **and** whose `screening_status` is
        `SCREENED_IN`; alternatives of `kind` `TRANSMISSION`, and any alternative
        still `SUBMITTED` or already `SCREENED_OUT`, are excluded from the pool even
        though screened-in transmission alternatives still count toward the
        two-alternative gate."

        Design: Corner/calculations/need_margin_selector_excludes_screened_out_alternative
        """
        ctx = fx.build_need_case(api)
        fx.screen_in_both_alternatives(api, ctx)
        cheap = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="NON_TRANSMISSION",
                    description=(
                        "Unsited merchant storage with no interconnection queue "
                        "position"
                    ),
                    capex_cents=10_000_000_000, deliverable_mw=200,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        screened_out = get_success_data(
            api.screen_alternative(
                cheap["id"],
                f.screening_payload(
                    decision="SCREEN_OUT",
                    screen_reason="No interconnection queue position",
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        study = validate_success(
            api.certify_study_sufficiency(
                ctx["study"], f.sufficiency_certification_payload(),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(
            cheap["levelized_cost_cents_per_mw"], 50000000.00,
            "levelized_cost_cents_per_mw",
        )
        assert screened_out["screening_status"] == "SCREENED_OUT", (
            f"The cheap portfolio was screened out, got "
            f"{screened_out['screening_status']}"
        )
        assert study["alternatives_screened_in_count"] == 2, (
            f"A screen-out does not add to the screened-in count, got "
            f"{study['alternatives_screened_in_count']}"
        )
        assert study["selected_nta_alternative_id"] == ctx["alt2"], (
            "The screened-in non-wires candidate wins the pool, not the cheaper "
            f"screened-out one, got {study['selected_nta_alternative_id']!r}"
        )
        assert_ratio(study["need_margin_ratio"], 1.1500, "need_margin_ratio")
        assert study["status"] == "CERTIFIED_SUFFICIENT", (
            f"The margin still clears the threshold, got {study['status']}"
        )


class TestSchedulePostureThreshold:
    """Slack of exactly 180 days is not "fewer than 180"."""

    def test_slack_of_exactly_one_hundred_eighty_days_stays_on_track(self, api):
        """PRD §3.5: "Negative slack — a deadline that falls after the contractual
        in-service date — makes the posture `CRITICAL`; slack of fewer than 180 days
        makes it `AT_RISK`; anything else leaves it `ON_TRACK`."

        Design: Corner/calculations/schedule_posture_at_exactly_180_days_slack_stays_on_track
        """
        ctx = fx.setup_nominated_routes(api)
        fx.set_clock(api, "2026-10-04T00:00:00Z")

        application = validate_success(
            api.create_application(
                f.application_payload(ctx["proj"], ctx["study"], ctx["routeA"]),
                fx.DEVELOPER_FILER_HEADERS,
            ),
            expected_status=201,
        )

        assert_timestamp_equals(application["filed_at"], "2026-10-04T00:00:00Z", "filed_at")
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-10-04T00:00:00Z",
            "decision_deadline_at",
        )
        project = fx.read_project(api, ctx)
        assert project["schedule_posture"] == "ON_TRACK", (
            "Exactly 180 days of slack is not fewer than 180, got "
            f"{project['schedule_posture']}"
        )
        assert project["right_of_way_hold"] is False, (
            f"An ON_TRACK project carries no hold, got {project['right_of_way_hold']}"
        )
        assert project["stage"] == "APPLICATION_FILED", (
            f"The filing carries the project ROUTING -> APPLICATION_FILED, got "
            f"{project['stage']}"
        )
