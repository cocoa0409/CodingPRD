"""The two compliance percentages, worksheet rigor and the acceptance bar."""

from typing import Any, Dict, List, Tuple

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_CCW_RIGOR_INSUFFICIENT
from test_helpers.assertions import (
    assert_money,
    assert_percentage,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_total_count,
)
from test_helpers.constants import CLOCK_DEFAULT
from test_helpers.factories import ccw_decision_payload
from test_helpers.fixtures import (
    Scenario,
    build_fieldwork_engagement,
    build_submitted_ccw,
    conclude,
    create_roc,
    draft_ccw,
    ok,
    open_requirement,
    read_engagement,
    requirement_concluded,
    start_testing,
    submit_ccw,
)
from test_helpers.test_users import make_lead_headers, make_qa_reviewer_headers


def _read_requirement(api, requirement_id: str, lead_id: str) -> Dict[str, Any]:
    """Read one requirement so both of its dimensions can be inspected."""
    return validate_success(
        api.get_requirement_assessment(requirement_id, make_lead_headers(lead_id))
    )


def _gap_with_worksheet(
    api,
    scenario: Scenario,
    requirement_ref: str,
    requirement_family: str,
    observed_component_id: str,
    control_refs: List[str],
    monitoring_interval_days: int,
    submit: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fully test a requirement, find it wanting and argue a worksheet for it."""
    requirement = requirement_concluded(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        requirement_ref,
        requirement_family,
        observed_component_id,
        conclusion="NOT_IN_PLACE",
        conclusion_rationale="The stated control is absent on the sampled host.",
    )
    live_version = _read_requirement(api, requirement["id"], scenario["lead_id"])[
        "version"
    ]
    worksheet = draft_ccw(
        api,
        requirement["id"],
        scenario["lead_id"],
        live_version,
        control_refs=control_refs,
        monitoring_interval_days=monitoring_interval_days,
    )
    if submit:
        worksheet = submit_ccw(api, worksheet["id"], scenario["lead_id"])
    return requirement, worksheet


def _decide(api, ccw_id: str, qa_id: str, decision: str = "ACCEPT", note: str = None):
    """Hand the worksheet to the engagement's independent reviewer."""
    payload = ccw_decision_payload(
        decision=decision,
        reviewer_note=note or "The compensating controls were weighed on their merits.",
    )
    return api.decide_ccw(ccw_id, payload, make_qa_reviewer_headers(qa_id))


def _projection_engagement(api) -> Scenario:
    """Two applicable requirements reach 'in place' by two different routes.

    Requirement 1.2.1 was in place all along; requirement 6.4.1 was found wanting
    and its gap is covered by an accepted compensating control worksheet. A third
    requirement is ruled not applicable and stands outside the denominator.
    """
    scenario = build_fieldwork_engagement(api)
    lead_id = scenario["lead_id"]
    engagement_id = scenario["engagement_id"]

    in_place = requirement_concluded(
        api,
        engagement_id,
        lead_id,
        "1.2.1",
        "R1",
        scenario["component_ids"]["app-01"],
        conclusion="IN_PLACE",
    )
    covered, worksheet = _gap_with_worksheet(
        api,
        scenario,
        "6.4.1",
        "R6",
        scenario["component_ids"]["pay-01"],
        ["A-1", "A-2", "A-3", "A-4", "A-5"],
        1,
        submit=True,
    )
    accepted = ok(
        _decide(
            api,
            worksheet["id"],
            scenario["qa_id"],
            note="Five independent controls with daily monitoring clear the bar.",
        )
    )
    not_applicable = open_requirement(
        api,
        engagement_id,
        lead_id,
        requirement_ref="3.6.1",
        requirement_family="R3",
        testing_procedure_count=2,
        applicability="NOT_APPLICABLE",
    )

    scenario["in_place_requirement_id"] = in_place["id"]
    scenario["covered_requirement_id"] = covered["id"]
    scenario["not_applicable_requirement_id"] = not_applicable["id"]
    scenario["accepted_ccw"] = accepted
    return scenario


class TestComplianceProjectionBothVariants:
    """The same requirement population is projected twice and answers twice."""

    def test_report_reads_fifty_as_found_against_one_hundred_as_attested(self, api):
        """The worksheet-covered requirement lands in one numerator only.

        PRD: The `AS_FOUND` numerator counts the applicable requirements whose
        `test_status` is `IN_PLACE` *and* whose `remediation_status` is `NONE` — a
        requirement that was ever gapped is excluded from it forever, even after a
        successful retest restored it.

        Design: Difficulty/dual_variant_calc/compliance_projection_as_found_versus_as_attested
        """
        scenario = _projection_engagement(api)
        lead_id = scenario["lead_id"]
        engagement_id = scenario["engagement_id"]

        roc = create_roc(api, engagement_id, lead_id)

        assert roc["applicable_requirement_count"] == 2
        assert roc["in_place_count"] == 1
        assert roc["ccw_covered_count"] == 1
        assert roc["not_in_place_count"] == 0
        assert_percentage(roc["as_found_compliance_percentage"], 50.00)
        assert_percentage(roc["as_attested_compliance_percentage"], 100.00)
        assert roc["compliance_result"] == "COMPLIANT"
        assert roc["status"] == "DRAFTING"
        assert roc["revision_count"] == 0
        # One population, two membership tests, fifty percentage points apart.
        assert roc["as_attested_compliance_percentage"] - roc[
            "as_found_compliance_percentage"
        ] == pytest.approx(50.00, abs=0.01)

        assert_requirement_dimensions(
            _read_requirement(api, scenario["in_place_requirement_id"], lead_id),
            test_status="IN_PLACE",
            remediation_status="NONE",
        )
        assert_requirement_dimensions(
            _read_requirement(api, scenario["covered_requirement_id"], lead_id),
            test_status="IN_PLACE_WITH_CCW",
            remediation_status="GAP_ACCEPTED_CCW",
        )

        engagement = read_engagement(api, engagement_id, lead_id)
        assert_percentage(engagement["as_found_compliance_percentage"], 50.00)
        assert_percentage(engagement["as_attested_compliance_percentage"], 100.00)
        assert engagement["accepted_ccw_count"] == 1
        assert engagement["open_gap_count"] == 0
        assert engagement["status"] == "REPORTING"
        assert engagement["posture"] == "FROZEN"
        assert engagement["estimated_hours"] == 246
        assert_money(engagement["assessment_fee_total"], 64427.40)

    def test_a_not_applicable_requirement_never_enters_the_denominator(self, api):
        """Three requirement rows exist and only two are ever divided by.

        PRD: The denominator for both is `applicable_requirement_count`, the number
        of requirement assessments on the engagement whose `applicability` is
        `APPLICABLE`; rows created `NOT_APPLICABLE` never enter it.

        Design: Difficulty/dual_variant_calc/compliance_projection_as_found_versus_as_attested
        """
        scenario = build_fieldwork_engagement(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]

        requirement_concluded(
            api,
            engagement_id,
            lead_id,
            "1.2.1",
            "R1",
            scenario["component_ids"]["app-01"],
            conclusion="IN_PLACE",
        )
        # A procedure the assessor could not execute records no gap at all.
        not_tested = open_requirement(
            api, engagement_id, lead_id, requirement_ref="11.3.1", requirement_family="R11"
        )
        start_testing(api, not_tested["id"], lead_id)
        conclude(
            api,
            not_tested["id"],
            lead_id,
            conclusion="NOT_TESTED",
            conclusion_rationale="The client withheld access to the scanning console.",
        )
        ruled_out = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="3.6.1",
            requirement_family="R3",
            testing_procedure_count=2,
            applicability="NOT_APPLICABLE",
        )

        roc = create_roc(api, engagement_id, lead_id)

        assert roc["applicable_requirement_count"] == 2
        assert roc["in_place_count"] == 1
        assert roc["ccw_covered_count"] == 0
        assert roc["not_in_place_count"] == 1
        assert_percentage(roc["as_found_compliance_percentage"], 50.00)
        assert_percentage(roc["as_attested_compliance_percentage"], 50.00)
        assert roc["compliance_result"] == "NON_COMPLIANT"

        assert_total_count(
            api.list_requirement_assessments(
                lead_headers, {"engagement_id": engagement_id}
            ),
            3,
        )
        assert (
            _read_requirement(api, ruled_out["id"], lead_id)["test_status"]
            == "NOT_APPLICABLE"
        )

    def test_both_variants_collapse_while_a_gap_still_stands(self, api):
        """Nothing has been remediated or covered, so the two answers agree.

        PRD: The `AS_ATTESTED` numerator counts the applicable requirements whose
        `test_status` is either `IN_PLACE` or `IN_PLACE_WITH_CCW`, so both
        remediated requirements and compensating-control-covered requirements count
        toward it.

        Design: Difficulty/dual_variant_calc/compliance_projection_as_found_versus_as_attested
        """
        scenario = build_fieldwork_engagement(api)
        lead_id = scenario["lead_id"]
        engagement_id = scenario["engagement_id"]

        for requirement_ref, family, observed in (
            ("1.2.1", "R1", "app-01"),
            ("2.1.1", "R2", "pay-02"),
        ):
            requirement_concluded(
                api,
                engagement_id,
                lead_id,
                requirement_ref,
                family,
                scenario["component_ids"][observed],
                conclusion="IN_PLACE",
            )
        gapped = requirement_concluded(
            api,
            engagement_id,
            lead_id,
            "6.4.1",
            "R6",
            scenario["component_ids"]["pay-01"],
            conclusion="NOT_IN_PLACE",
            conclusion_rationale="Separate deployment credentials are not enforced.",
        )
        not_tested = open_requirement(
            api, engagement_id, lead_id, requirement_ref="11.3.1", requirement_family="R11"
        )
        start_testing(api, not_tested["id"], lead_id)
        conclude(
            api,
            not_tested["id"],
            lead_id,
            conclusion="NOT_TESTED",
            conclusion_rationale="The client withheld access to the scanning console.",
        )

        engagement = read_engagement(api, engagement_id, lead_id)

        assert engagement["applicable_requirement_count"] == 4
        assert_percentage(engagement["as_found_compliance_percentage"], 50.00)
        assert_percentage(engagement["as_attested_compliance_percentage"], 50.00)
        assert (
            engagement["as_found_compliance_percentage"]
            == engagement["as_attested_compliance_percentage"]
        )
        assert_requirement_dimensions(
            _read_requirement(api, gapped["id"], lead_id),
            test_status="NOT_IN_PLACE",
            remediation_status="GAP_OPEN",
        )
        assert_requirement_dimensions(
            _read_requirement(api, not_tested["id"], lead_id),
            test_status="NOT_TESTED",
            remediation_status="NONE",
        )


class TestWorksheetRigorScore:
    """Depth, monitoring and family risk are weighed, then the ceiling applies."""

    def test_five_controls_verified_weekly_score_the_weighted_sum(self, api):
        """Depth 100, monitoring 80 and a risk offset of 40 weigh out at 78.00.

        PRD: The three are then combined into a raw score weighting
        `control_depth_points` at forty hundredths, `monitoring_factor` at
        thirty-five hundredths and `risk_offset_points` at twenty-five hundredths.

        Design: Difficulty/combinatorial_formula/ccw_rigor_weighted_score_with_thin_control_cap
        """
        scenario = build_fieldwork_engagement(api)
        requirement, worksheet = _gap_with_worksheet(
            api,
            scenario,
            "6.4.1",
            "R6",
            scenario["component_ids"]["pay-01"],
            ["A-1", "A-2", "A-3", "A-4", "A-5"],
            7,
        )

        assert requirement["risk_points"] == 4
        assert worksheet["control_depth_points"] == pytest.approx(100.00, abs=0.01)
        assert worksheet["monitoring_factor"] == pytest.approx(80.00, abs=0.01)
        assert worksheet["risk_offset_points"] == pytest.approx(40.00, abs=0.01)
        assert worksheet["rigor_score"] == pytest.approx(78.00, abs=0.01)
        assert worksheet["thin_control_capped"] is False
        assert worksheet["status"] == "DRAFT"
        assert worksheet["reviewer_note"] is None
        assert worksheet["decided_at"] is None
        assert worksheet["engagement_id"] == scenario["engagement_id"]

        # Arguing a worksheet decides nothing: the requirement is still wanting.
        assert_requirement_dimensions(
            _read_requirement(api, requirement["id"], scenario["lead_id"]),
            test_status="NOT_IN_PLACE",
            remediation_status="GAP_OPEN",
        )

    def test_one_control_verified_daily_is_clamped_to_the_thin_ceiling(self, api):
        """The raw weighted sum is computed and then overridden by the ceiling.

        PRD: A single control verified daily on an `R12` requirement produces a raw
        score of 64.25, but because only one distinct control was named the
        published `rigor_score` is 40.00.

        Design: Difficulty/combinatorial_formula/ccw_rigor_weighted_score_with_thin_control_cap
        """
        scenario = build_fieldwork_engagement(api)
        requirement, worksheet = _gap_with_worksheet(
            api,
            scenario,
            "12.1.1",
            "R12",
            scenario["component_ids"]["app-01"],
            ["B-1"],
            1,
        )

        assert requirement["risk_points"] == 1
        assert worksheet["control_depth_points"] == pytest.approx(20.00, abs=0.01)
        assert worksheet["monitoring_factor"] == pytest.approx(100.00, abs=0.01)
        assert worksheet["risk_offset_points"] == pytest.approx(85.00, abs=0.01)
        assert worksheet["thin_control_capped"] is True
        assert worksheet["rigor_score"] == pytest.approx(40.00, abs=0.01)
        # The raw sum of 64.25 is never the published score on a thin worksheet.
        assert worksheet["rigor_score"] != pytest.approx(64.25, abs=0.01)
        assert worksheet["status"] == "DRAFT"

    def test_duplicate_control_refs_collapse_before_the_depth_award(self, api):
        """Four listed controls that name two controls buy two controls' depth.

        PRD: `control_depth_points` awards 20 points for each *distinct* entry in
        `control_refs`, capped at 100 — duplicate entries collapse before counting,
        so listing the same control twice buys no depth.

        Design: Difficulty/combinatorial_formula/ccw_rigor_weighted_score_with_thin_control_cap
        """
        scenario = build_fieldwork_engagement(api)
        requirement, worksheet = _gap_with_worksheet(
            api,
            scenario,
            "6.4.1",
            "R6",
            scenario["component_ids"]["pay-01"],
            ["A-1", "A-2", "A-1", "A-2"],
            7,
        )

        assert worksheet["control_depth_points"] == pytest.approx(40.00, abs=0.01)
        assert worksheet["monitoring_factor"] == pytest.approx(80.00, abs=0.01)
        assert worksheet["risk_offset_points"] == pytest.approx(40.00, abs=0.01)
        assert worksheet["rigor_score"] == pytest.approx(54.00, abs=0.01)
        # Counting the four listed entries would have published 78.00 instead.
        assert worksheet["rigor_score"] != pytest.approx(78.00, abs=0.01)
        # Two distinct controls clear the thin-control test even so.
        assert worksheet["thin_control_capped"] is False


class TestRigorAcceptanceBoundary:
    """The acceptance bar sits at 70.00 and includes it."""

    def test_a_worksheet_at_exactly_seventy_is_accepted(self, api):
        """The score lands on the bar and the reviewer may accept it.

        PRD: Four distinct controls verified weekly on an `R6` requirement give
        depth 80, monitoring 80 and a risk offset of 40, for a `rigor_score` of
        exactly 70.00 — the acceptance boundary.

        Design: Difficulty/boundary_precision_check/ccw_rigor_score_inclusive_seventy_boundary
        """
        scenario = build_submitted_ccw(
            api,
            control_refs=["A-1", "A-2", "A-3", "A-4"],
            monitoring_interval_days=7,
            requirement_ref="6.4.1",
            requirement_family="R6",
        )
        lead_id = scenario["lead_id"]
        worksheet = scenario["ccw"]

        assert worksheet["control_depth_points"] == pytest.approx(80.00, abs=0.01)
        assert worksheet["monitoring_factor"] == pytest.approx(80.00, abs=0.01)
        assert worksheet["risk_offset_points"] == pytest.approx(40.00, abs=0.01)
        assert worksheet["rigor_score"] == pytest.approx(70.00, abs=0.01)
        assert worksheet["thin_control_capped"] is False
        assert worksheet["status"] == "SUBMITTED"

        accepted = ok(
            _decide(
                api,
                scenario["ccw_id"],
                scenario["qa_id"],
                note="Four controls with weekly monitoring exactly meet the bar.",
            )
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["rigor_score"] == pytest.approx(70.00, abs=0.01)
        assert_same_instant(accepted["decided_at"], CLOCK_DEFAULT)
        assert_requirement_dimensions(
            _read_requirement(api, scenario["requirement_id"], lead_id),
            test_status="IN_PLACE_WITH_CCW",
            remediation_status="GAP_ACCEPTED_CCW",
        )
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["accepted_ccw_count"] == 1
        assert engagement["open_gap_count"] == 0
        assert engagement["posture"] == "OPEN"
        assert engagement["estimated_hours"] == 246
        assert_money(engagement["assessment_fee_total"], 64427.40)

    def test_a_worksheet_at_sixty_six_point_two_five_is_refused(self, api):
        """The same paperwork on a heavier family falls short of the bar.

        PRD: Holding everything else and moving the family to `R3` drops the risk
        offset to 25 and the score to 66.25.

        Design: Difficulty/boundary_precision_check/ccw_rigor_score_inclusive_seventy_boundary
        """
        scenario = build_submitted_ccw(
            api,
            control_refs=["C-1", "C-2", "C-3", "C-4"],
            monitoring_interval_days=7,
            requirement_ref="3.5.1",
            requirement_family="R3",
        )
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        worksheet = scenario["ccw"]

        assert worksheet["control_depth_points"] == pytest.approx(80.00, abs=0.01)
        assert worksheet["monitoring_factor"] == pytest.approx(80.00, abs=0.01)
        assert worksheet["risk_offset_points"] == pytest.approx(25.00, abs=0.01)
        assert worksheet["rigor_score"] == pytest.approx(66.25, abs=0.01)

        refused = _decide(
            api,
            scenario["ccw_id"],
            scenario["qa_id"],
            note="Attempting to accept a worksheet that sits just under the bar.",
        )
        validate_error(refused, ERR_CCW_RIGOR_INSUFFICIENT, 422)

        # The refusal is not a rejection: the worksheet never reached a decision.
        held = validate_success(api.get_ccw(scenario["ccw_id"], lead_headers))
        assert held["status"] == "SUBMITTED"
        assert held["decided_at"] is None
        assert held["reviewer_note"] is None
        assert held["version"] == worksheet["version"]
        assert_requirement_dimensions(
            _read_requirement(api, scenario["requirement_id"], lead_id),
            test_status="NOT_IN_PLACE",
            remediation_status="GAP_OPEN",
        )
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["accepted_ccw_count"] == 0
        assert engagement["open_gap_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
        assert engagement["estimated_hours"] == 226
        assert_money(engagement["assessment_fee_total"], 59189.40)

    def test_the_family_risk_offset_alone_decides_the_two_worksheets(self, api):
        """Two identically argued worksheets split either side of the bar.

        PRD: Acceptance additionally demands two things of the worksheet itself:
        `monitoring_interval_days` must not exceed 30, or the acceptance is refused
        with `ERR_CCW_MONITORING_INTERVAL_TOO_LONG`, and `rigor_score` must have
        reached 70.00 — the threshold is inclusive, so a score of exactly 70.00
        passes and 69.99 does not — or the acceptance is refused with
        `ERR_CCW_RIGOR_INSUFFICIENT`.

        Design: Difficulty/boundary_precision_check/ccw_rigor_score_inclusive_seventy_boundary
        """
        scenario = build_submitted_ccw(
            api,
            control_refs=["A-1", "A-2", "A-3", "A-4"],
            monitoring_interval_days=7,
            requirement_ref="6.4.1",
            requirement_family="R6",
        )
        lead_id = scenario["lead_id"]
        at_the_bar = scenario["ccw"]
        below_the_bar_requirement, below_the_bar = _gap_with_worksheet(
            api,
            scenario,
            "3.5.1",
            "R3",
            scenario["component_ids"]["app-01"],
            ["C-1", "C-2", "C-3", "C-4"],
            7,
            submit=True,
        )

        # The paperwork is identical; only the family's risk weight differs.
        assert at_the_bar["control_depth_points"] == pytest.approx(
            below_the_bar["control_depth_points"], abs=0.01
        )
        assert at_the_bar["monitoring_factor"] == pytest.approx(
            below_the_bar["monitoring_factor"], abs=0.01
        )
        assert at_the_bar["risk_offset_points"] == pytest.approx(40.00, abs=0.01)
        assert below_the_bar["risk_offset_points"] == pytest.approx(25.00, abs=0.01)
        assert at_the_bar["rigor_score"] - below_the_bar["rigor_score"] == pytest.approx(
            3.75, abs=0.01
        )

        accepted = ok(
            _decide(api, at_the_bar["id"], scenario["qa_id"], note="Exactly at the bar.")
        )
        assert accepted["status"] == "ACCEPTED"

        refused = _decide(
            api,
            below_the_bar["id"],
            scenario["qa_id"],
            note="Three and three quarter points short of the bar.",
        )
        validate_error(refused, ERR_CCW_RIGOR_INSUFFICIENT, 422)

        assert_requirement_dimensions(
            _read_requirement(api, scenario["requirement_id"], lead_id),
            test_status="IN_PLACE_WITH_CCW",
            remediation_status="GAP_ACCEPTED_CCW",
        )
        assert_requirement_dimensions(
            _read_requirement(api, below_the_bar_requirement["id"], lead_id),
            test_status="NOT_IN_PLACE",
            remediation_status="GAP_OPEN",
        )
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["accepted_ccw_count"] == 1
        assert engagement["open_gap_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
