"""The same underlying fact measured twice, on three different entities.

A desk-study constraint score alongside a filing-grade one, a negotiated offer
alongside a condemnation award, and a recoverable rolling compliance index
alongside a permanent cumulative one.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assert_score
from test_helpers import fixtures as fx
from test_helpers.test_users import DEVELOPER_HEADERS, ROUTE_ANALYST_HEADERS


class TestRouteScoreVariants:
    """The preliminary and certified constraint scores on one corridor."""

    def test_desktop_segments_drive_the_two_score_variants_apart(self, api):
        """PRD §3.2: "for any segment whose `survey_status` is `DESKTOP`, the
        environmental and cultural ratings are replaced by the worst-case value
        5, while the land-use and engineering ratings are still taken verbatim".

        Design: Difficulty/dual_variant_calc/route_score_variants_diverge_on_desktop_segments
        """
        ctx = fx.build_certified_study(api)
        fx.build_route_a(api, ctx, seg1_survey="DESKTOP", map_it=False)
        route = validate_success(
            api.run_constraint_mapping(
                ctx["routeA"],
                {"mapping_note": "Desk study plus one field-verified segment"},
                ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(
            route["constraint_score_preliminary"],
            67.28,
            "constraint_score_preliminary on the desk-study view",
        )
        assert_score(
            route["constraint_score_certified"],
            82.23,
            "constraint_score_certified on the filing-grade view",
        )
        assert_score(route["total_miles"], 20.0, "total_miles")
        assert_score(route["constraint_density_certified"], 4.11, "constraint_density_certified")
        assert route["unsurveyed_segment_count"] == 2, (
            "Two of the three segments are still desk studies, so "
            f"unsurveyed_segment_count should be 2, got {route['unsurveyed_segment_count']}"
        )
        assert route["status"] == "CONSTRAINT_MAPPED", (
            f"Mapping should land the route at CONSTRAINT_MAPPED, got {route['status']}"
        )

    def test_fully_field_verified_corridor_collapses_the_two_variants(self, api):
        """PRD §3.2: "The two variants therefore coincide only when every segment
        on the route has been field-verified."

        Design: Difficulty/dual_variant_calc/route_score_variants_diverge_on_desktop_segments
        """
        ctx = fx.build_certified_study(api)
        fx.create_route(api, ctx, "routeA", "Route A - river crossing", "PROPOSED")
        for index, spec in enumerate(fx.ROUTE_A_SEGMENTS, start=1):
            spec = dict(spec)
            spec["survey_status"] = "FIELD_VERIFIED"
            fx.add_segment(api, ctx, "routeA", f"seg{index}", **spec)
        route = validate_success(
            api.run_constraint_mapping(
                ctx["routeA"],
                {"mapping_note": "Every segment field verified"},
                ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(route["constraint_score_preliminary"], 67.28, "constraint_score_preliminary")
        assert_score(route["constraint_score_certified"], 67.28, "constraint_score_certified")
        assert route["constraint_score_preliminary"] == route["constraint_score_certified"], (
            "With no desk-study segment left the two variants must coincide, got "
            f"{route['constraint_score_preliminary']} and {route['constraint_score_certified']}"
        )
        assert_score(route["constraint_density_certified"], 3.36, "constraint_density_certified")
        assert route["unsurveyed_segment_count"] == 0, (
            f"No segment is a desk study, got unsurveyed_segment_count "
            f"{route['unsurveyed_segment_count']}"
        )


class TestEasementValueVariants:
    """The negotiated offer and the condemnation award on one tract."""

    def test_condemnation_award_diverges_from_the_standing_offer(self, api):
        """PRD §3.8: "on identical tract data the award and the last offer will
        diverge — that divergence is the point, not a defect."

        Design: Difficulty/dual_variant_calc/easement_value_variants_diverge_offer_vs_award
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_rejected_tract(api, ctx, rounds=2)
        fx.file_condemnation(api, ctx)

        tract = validate_success(
            api.record_award(
                ctx["tract1"],
                {"award_note": "Commissioners' award entered"},
                fx.COMMISSION_STAFF_HEADERS,
            ),
            expected_status=201,
        )

        assert tract["offered_compensation_cents"] == 4371576, (
            "The second negotiated offer values only the easement interest, so it "
            f"should stand at 4371576 cents, got {tract['offered_compensation_cents']}"
        )
        assert tract["award_cents"] == 8200000, (
            "The award is diminution 7500000 plus severance 400000 plus deposit "
            f"interest 300000 = 8200000 cents, got {tract['award_cents']}"
        )
        assert tract["committed_cents"] == 8200000, (
            f"Recording the award sets committed_cents to the award, got "
            f"{tract['committed_cents']}"
        )
        assert tract["acquisition_status"] == "AWARDED", (
            f"The award moves the tract to AWARDED, got {tract['acquisition_status']}"
        )
        assert tract["payment_status"] == "UNPAID", (
            f"The award disburses nothing, so payment_status stays UNPAID, got "
            f"{tract['payment_status']}"
        )
        project = fx.read_project(api, ctx)
        assert project["easement_committed_cents"] == 8200000, (
            "The awarded tract rolls up into the project's committed exposure, got "
            f"{project['easement_committed_cents']}"
        )

    def test_award_ignores_the_negotiated_valuation_inputs_entirely(self, api):
        """PRD §3.8: "The condemnation measure ignores `acres`,
        `per_acre_value_cents`, `easement_factor`, `structure_damages_cents` and
        `offer_round` entirely".

        Design: Difficulty/dual_variant_calc/easement_value_variants_diverge_offer_vs_award
        """
        ctx = fx.setup_issued_certificate(api)
        fx.create_landowner(
            api, ctx, "lo_thin", name="Dell Rowan", email="dell@example.com",
            mailing_address="7 Fork Rd, Harlan KY",
        )
        fx.setup_rejected_tract(
            api, ctx, key="thin", landowner_key="lo_thin", rounds=2,
            parcel_number="H-104-31", acres=1.00, per_acre_value_cents=100_000,
            easement_factor=0.10, structure_damages_cents=0,
            before_value_cents=90_000_000, after_value_cents=82_500_000,
            severance_damages_cents=400_000,
        )
        fx.file_condemnation(api, ctx, key="thin", court_docket_number="CC-2027-78")

        tract = validate_success(
            api.record_award(
                ctx["thin"],
                {"award_note": "Commissioners' award entered"},
                fx.COMMISSION_STAFF_HEADERS,
            ),
            expected_status=201,
        )

        assert tract["offered_compensation_cents"] == 10500, (
            "The negotiated offer on this thin tract escalates 10000 to 10500 cents, "
            f"got {tract['offered_compensation_cents']}"
        )
        assert tract["award_cents"] == 8200000, (
            "The award reads only the whole-property figures, so it is unchanged at "
            f"8200000 cents, got {tract['award_cents']}"
        )
        assert tract["committed_cents"] == 8200000, (
            f"committed_cents follows the award, got {tract['committed_cents']}"
        )


class TestComplianceIndexVariants:
    """The rolling and cumulative compliance indices on one certificate."""

    def test_correcting_a_finding_restores_half_the_rolling_penalty_only(self, api):
        """PRD §3.9: "In the **rolling** index, an `OPEN` finding contributes its
        full deduction and a `CORRECTED` finding contributes half of it, so
        correcting a finding restores half its penalty."

        Design: Difficulty/dual_variant_calc/compliance_index_variants_diverge_after_correction
        """
        ctx = fx.setup_issued_certificate(api)
        fx.file_finding(api, ctx, key="ncr_sev", condition_key="cond1", severity="SEVERE")

        finding = validate_success(
            api.correct_nonconformance(
                ctx["ncr_sev"],
                {
                    "corrective_action": (
                        "Habitat restoration completed and monitor sign-off obtained"
                    )
                },
                fx.COMPLIANCE_MONITOR_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(finding["deduction_points"], 48.00, "deduction_points frozen at creation")
        assert finding["status"] == "CORRECTED", (
            f"Recording corrective action moves the finding to CORRECTED, got "
            f"{finding['status']}"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 76.00, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 52.00, "compliance_index_cumulative"
        )
        assert certificate["posture"] == "ACTIVE", (
            "A rolling index of 76.00 is above the 60.00 floor, so posture returns to "
            f"ACTIVE, got {certificate['posture']}"
        )
        condition = fx.read_condition(api, ctx["cond1"])
        assert condition["status"] == "ACTIVE", (
            "The correction was the last open finding on the condition, so it returns "
            f"to ACTIVE, got {condition['status']}"
        )

    def test_indices_are_identical_while_the_finding_is_still_open(self, api):
        """PRD §3.9: "The two figures are identical until the first correction and
        diverge permanently thereafter."

        Design: Difficulty/dual_variant_calc/compliance_index_variants_diverge_after_correction
        """
        ctx = fx.setup_issued_certificate(api)
        fx.file_finding(api, ctx, key="ncr_sev", condition_key="cond1", severity="SEVERE")

        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 52.00, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 52.00, "compliance_index_cumulative"
        )
        assert (
            certificate["compliance_index_rolling"]
            == certificate["compliance_index_cumulative"]
        ), (
            "Before any correction the two indices must agree, got rolling "
            f"{certificate['compliance_index_rolling']} and cumulative "
            f"{certificate['compliance_index_cumulative']}"
        )
        assert certificate["posture"] == "STOP_WORK", (
            "A rolling index of 52.00 is strictly below the 60.00 floor, got posture "
            f"{certificate['posture']}"
        )
        project = fx.read_project(api, ctx)
        assert project["escrow_funded_cents"] == 0, (
            "Nothing in this scenario deposits into escrow, got "
            f"{project['escrow_funded_cents']}"
        )
        assert DEVELOPER_HEADERS["X-User-Role"] == "Developer"
