"""The five-part emergency-vehicle access standard and the cascade a newly
deficient segment sets off."""
import pytest

from test_helpers import (
    assert_required_turnouts,
    expected_required_turnouts,
    read_association,
    read_bid,
    read_project,
    read_proposal,
    read_segment,
    record_access_inspection,
    set_clock,
    setup_annual_assessment,
    setup_association,
    setup_proposal,
    setup_project,
    setup_road_segment,
    submit_bid,
)
from test_helpers import award_project as award

THREE_GRADES = {
    "name": "Three Grades Road Association",
    "reserve_target_cents": 1_000_000,
}

PINE_HOLLOW = {
    "name": "Pine Hollow Road Association",
    "reserve_target_cents": 1_000_000,
    "default_voting_basis": "PER_PARCEL",
    "delinquency_interest_basis": "STATUTORY",
    "quorum_bps": 5000,
}
PINE_HOLLOW_SEGMENT = {
    "name": "Pine Hollow Road",
    "length_feet": 2400,
    "width_feet": 22,
    "max_grade_pct": 9,
    "surface_type": "GRAVEL",
    "turnout_count": 2,
    "culvert_count": 3,
    "turnaround_present": True,
    "bridge_present": False,
}
SINGLE_PARCEL = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]

# The four measurements that sit exactly on their passing boundaries for a
# 2400 ft segment, which needs two turnouts.
ON_THE_BOUNDARY = {
    "measured_width_feet": 20,
    "measured_max_grade_pct": 12,
    "measured_turnout_count": 2,
    "turnaround_present": True,
}


def _segment_2400():
    association = setup_association(**THREE_GRADES)
    return setup_road_segment(
        association["id"],
        name="Segment A 2400",
        length_feet=2400,
        width_feet=22,
        max_grade_pct=9,
        turnout_count=2,
        culvert_count=3,
        turnaround_present=True,
        bridge_present=False,
    )


class TestAccessGradeInputBoundaries:
    """Five measured inputs, four inclusive boundaries, one conditional clause."""

    def test_required_turnouts_derive_from_the_eight_hundred_foot_spacing(self, api):
        """PRD §2.7: "A segment also carries `required_turnouts`, a derived
        integer count of the emergency passing turnouts the standard demands: take
        the segment's `length_feet`, divide by the eight-hundred-foot turnout
        spacing, round the quotient up to the next whole number, subtract one, and
        treat any negative result as zero."
        PRD §3.1: "On creation, `required_turnouts` is derived from the length as
        described in §2.7, `emergency_access_grade` is set to `UNKNOWN`, and
        `last_inspection_at` is null."

        Design: Difficulty/combinatorial_formula/emergency_access_grade_five_input_boundary_interaction
        """
        association = setup_association(**THREE_GRADES)
        seg_a = setup_road_segment(
            association["id"], name="Segment A 2400", length_feet=2400, turnout_count=2
        )
        seg_b = setup_road_segment(
            association["id"],
            name="Segment B 1600 bridged",
            length_feet=1600,
            turnout_count=1,
            bridge_present=True,
            bridge_load_rating_tons=39,
            culvert_count=1,
        )
        seg_c = setup_road_segment(
            association["id"], name="Segment C 2401", length_feet=2401, turnout_count=2
        )

        assert seg_a["required_turnouts"] == 2
        assert seg_b["required_turnouts"] == 1
        assert seg_c["required_turnouts"] == 3, (
            "one extra foot raises ceil(2401 / 800) - 1 from 2 to 3"
        )
        for segment in (seg_a, seg_b, seg_c):
            assert segment["emergency_access_grade"] == "UNKNOWN"
            assert segment["last_inspection_at"] is None
            assert_required_turnouts(segment)
        assert expected_required_turnouts(2400) == 2

    def test_all_four_boundaries_are_inclusive_at_once(self, api):
        """PRD §2.7: "A segment grades as `COMPLIANT` only when all five conditions
        hold at once: its `width_feet` is at least twenty feet; its
        `max_grade_pct` is no more than twelve percent; `turnaround_present` is
        true; its `turnout_count` is at least `required_turnouts`; and either
        `bridge_present` is false, or `bridge_present` is true and
        `bridge_load_rating_tons` is both non-null and at least forty tons."
        PRD §2.7: "The bridge clause disappears entirely on a segment with no
        bridge, and both boundary comparisons are inclusive — a road exactly
        twenty feet wide on exactly a twelve percent grade passes."

        Design: Difficulty/combinatorial_formula/emergency_access_grade_five_input_boundary_interaction
        """
        segment = _segment_2400()

        graded = record_access_inspection(
            segment["id"], "2026-10-02T00:00:00Z", **ON_THE_BOUNDARY
        )

        assert graded["emergency_access_grade"] == "COMPLIANT"
        assert graded["width_feet"] == pytest.approx(20, abs=0.01)
        assert graded["max_grade_pct"] == pytest.approx(12, abs=0.01)
        assert graded["turnout_count"] == 2
        assert graded["turnaround_present"] is True
        assert graded["required_turnouts"] == 2

    @pytest.mark.parametrize(
        "changed_input,label",
        [
            ({"measured_width_feet": 19.9}, "a tenth of a foot too narrow"),
            ({"measured_max_grade_pct": 12.1}, "a tenth of a percent too steep"),
            ({"measured_turnout_count": 1}, "one turnout short of required"),
            ({"turnaround_present": False}, "no turnaround"),
        ],
    )
    def test_a_single_failing_measurement_grades_the_segment_deficient(
        self, api, changed_input, label
    ):
        """PRD §2.7: "A segment grades as `COMPLIANT` only when all five conditions
        hold at once: its `width_feet` is at least twenty feet; its
        `max_grade_pct` is no more than twelve percent; `turnaround_present` is
        true; its `turnout_count` is at least `required_turnouts`; and either
        `bridge_present` is false, or `bridge_present` is true and
        `bridge_load_rating_tons` is both non-null and at least forty tons. If any
        of those fails, the grade is `DEFICIENT`."

        Design: Difficulty/combinatorial_formula/emergency_access_grade_five_input_boundary_interaction
        """
        segment = _segment_2400()
        measurements = dict(ON_THE_BOUNDARY)
        measurements.update(changed_input)

        graded = record_access_inspection(segment["id"], "2026-10-03T00:00:00Z", **measurements)

        assert graded["emergency_access_grade"] == "DEFICIENT", (
            f"{label} must fail the standard on its own"
        )
        assert graded["required_turnouts"] == 2, "the derived count does not move"

    def test_the_bridge_clause_is_inclusive_at_forty_tons(self, api):
        """PRD §2.7: "and either `bridge_present` is false, or `bridge_present` is
        true and `bridge_load_rating_tons` is both non-null and at least forty
        tons."
        PRD §3.1: "Those measurements overwrite the segment's `width_feet`,
        `max_grade_pct`, `turnout_count`, `turnaround_present`, and
        `bridge_load_rating_tons` respectively, `last_inspection_at` is set to the
        supplied `inspected_at`, and the segment is regraded against the five-part
        standard."

        Design: Difficulty/combinatorial_formula/emergency_access_grade_five_input_boundary_interaction
        """
        association = setup_association(**THREE_GRADES)
        segment = setup_road_segment(
            association["id"],
            name="Segment B 1600 bridged",
            length_feet=1600,
            turnout_count=1,
            bridge_present=True,
            bridge_load_rating_tons=39,
            culvert_count=1,
        )
        boundary = dict(ON_THE_BOUNDARY, measured_turnout_count=1)

        under = record_access_inspection(
            segment["id"],
            "2026-10-07T00:00:00Z",
            measured_bridge_load_rating_tons=39,
            **boundary,
        )
        assert under["emergency_access_grade"] == "DEFICIENT"
        assert under["bridge_load_rating_tons"] == pytest.approx(39, abs=0.01)
        assert under["last_inspection_at"] == "2026-10-07T00:00:00Z"

        at_forty = record_access_inspection(
            segment["id"],
            "2026-10-08T00:00:00Z",
            measured_bridge_load_rating_tons=40,
            **boundary,
        )
        assert at_forty["emergency_access_grade"] == "COMPLIANT", (
            "forty tons exactly satisfies the bridge clause"
        )
        assert at_forty["bridge_load_rating_tons"] == pytest.approx(40, abs=0.01)
        assert at_forty["last_inspection_at"] == "2026-10-08T00:00:00Z"

    def test_one_extra_foot_of_length_flips_the_same_measurements(self, api):
        """PRD §2.7: "`turnaround_present` is true; its `turnout_count` is at least
        `required_turnouts`; and either `bridge_present` is false, or
        `bridge_present` is true and `bridge_load_rating_tons` is both non-null and
        at least forty tons."
        PRD §2.7: "take the segment's `length_feet`, divide by the
        eight-hundred-foot turnout spacing, round the quotient up to the next
        whole number, subtract one, and treat any negative result as zero."

        Design: Difficulty/combinatorial_formula/emergency_access_grade_five_input_boundary_interaction
        """
        association = setup_association(**THREE_GRADES)
        seg_a = setup_road_segment(
            association["id"], name="Segment A 2400", length_feet=2400, turnout_count=2
        )
        seg_c = setup_road_segment(
            association["id"], name="Segment C 2401", length_feet=2401, turnout_count=2
        )

        graded_a = record_access_inspection(
            seg_a["id"], "2026-10-02T00:00:00Z", **ON_THE_BOUNDARY
        )
        graded_c = record_access_inspection(
            seg_c["id"], "2026-10-09T00:00:00Z", **ON_THE_BOUNDARY
        )

        assert graded_a["emergency_access_grade"] == "COMPLIANT"
        assert graded_c["emergency_access_grade"] == "DEFICIENT"
        assert graded_c["required_turnouts"] == 3
        assert graded_c["turnout_count"] == 2


def _cascade_scenario():
    """A funded association with a DRAFT grading proposal and an awarded paving
    project on a COMPLIANT segment."""
    set_clock("2026-10-01T00:00:00Z")
    scenario = setup_annual_assessment(
        parcel_specs=SINGLE_PARCEL,
        fiscal_year=2027,
        fy_start_date="2026-10-01",
        fy_end_date="2027-09-30",
        budget_requirement_cents=4_000_000,
        method_variant="FRONTAGE_WEIGHTED",
        association_overrides=PINE_HOLLOW,
        segment_overrides=PINE_HOLLOW_SEGMENT,
    )
    record_access_inspection(
        scenario["segment"]["id"],
        "2026-10-01T00:00:00Z",
        measured_width_feet=22,
        measured_max_grade_pct=9,
        measured_turnout_count=2,
        turnaround_present=True,
    )
    scenario["proposal"] = setup_proposal(
        scenario,
        project_type="GRADING",
        title="Spring regrade",
        estimated_cost_cents=1_500_000,
        cost_allocation_method="FRONTAGE_WEIGHTED",
    )
    scenario["project"] = setup_project(
        scenario["segment"]["id"],
        category="PAVING",
        window_start_date="2026-11-01",
        window_end_date="2026-11-10",
    )
    scenario["bid"] = submit_bid(
        scenario["project"], 250_000, contractor_user_id="c-1", contractor_name="Alpha Paving LLC"
    )
    return scenario


class TestDeficientInspectionCascade:
    """One inspection payload, four hops, ending on a proposal nobody named."""

    def test_awarding_paving_work_lifts_the_draft_threshold(self, api):
        """PRD §3.7: "The association's `reserve_balance_cents` falls by that
        draw, `reserve_funding_ratio` and `reserve_posture` are recomputed, and
        every `DRAFT` proposal's `required_threshold_bps` follows."
        PRD §3.5: "A further five hundred are added when the association's
        `reserve_posture` is `UNDERFUNDED`, on the theory that a board with no
        reserve should need broader consent."

        Design: Difficulty/transitive_cascade/deficient_inspection_cancels_paving_reverses_reserve_and_retunes_threshold
        """
        scenario = _cascade_scenario()

        before = read_association(scenario["association"]["id"])
        assert before["reserve_balance_cents"] == 600_000
        assert before["reserve_posture"] == "ADEQUATE"
        assert scenario["proposal"]["required_threshold_bps"] == 5000

        awarded = award(scenario["project"]["id"], scenario["bid"]["id"])
        assert awarded["status"] == "AWARDED"
        assert awarded["reserve_draw_cents"] == 250_000
        assert awarded["awarded_amount_cents"] == 250_000

        after = read_association(scenario["association"]["id"])
        assert after["reserve_balance_cents"] == 350_000
        assert after["reserve_posture"] == "UNDERFUNDED"

        proposal = read_proposal(scenario["proposal"]["id"])
        assert proposal["status"] == "DRAFT"
        assert proposal["required_threshold_bps"] == 5500

    def test_deficient_regrade_cancels_the_paving_project_and_rejects_its_bid(self, api):
        """PRD §3.1: "Should the regrade land on `DEFICIENT`, a cascade follows:
        every maintenance project on that segment whose `category` is `PAVING` and
        whose `status` is `BID_SOLICITATION` or `AWARDED` is moved to `CANCELLED`;
        because those projects cancelled, their `SUBMITTED` and `AWARDED` bids are
        moved to `REJECTED` and each cancelled project's `reserve_draw_cents` is
        returned to the association's `reserve_balance_cents` and then zeroed"

        Design: Difficulty/transitive_cascade/deficient_inspection_cancels_paving_reverses_reserve_and_retunes_threshold
        """
        scenario = _cascade_scenario()
        award(scenario["project"]["id"], scenario["bid"]["id"])

        regraded = record_access_inspection(
            scenario["segment"]["id"],
            "2026-10-20T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=14,
            measured_turnout_count=2,
            turnaround_present=True,
        )
        assert regraded["emergency_access_grade"] == "DEFICIENT"
        assert regraded["max_grade_pct"] == pytest.approx(14, abs=0.01)
        assert regraded["last_inspection_at"] == "2026-10-20T00:00:00Z"

        project = read_project(scenario["project"]["id"])
        assert project["status"] == "CANCELLED"
        assert project["reserve_draw_cents"] == 0

        bid = read_bid(scenario["bid"]["id"])
        assert bid["status"] == "REJECTED"

    def test_deficient_regrade_returns_the_reserve_and_retunes_the_draft_proposal(self, api):
        """PRD §2.6: "Whenever `reserve_balance_cents` changes, the funding ratio
        and the posture are recomputed, and because the posture may have moved,
        every special assessment proposal of that association whose `status` is
        `DRAFT` has its `required_threshold_bps` recomputed as part of the same
        operation."
        PRD §2.6: "Its `reserve_balance_cents` is not a free-standing counter but a
        reconciled aggregate, recomputed from first principles on every event that
        moves reserve money: an assessment roll levy, a connection approval, a
        project award, a project cancellation, and the withdrawal of an awarded
        bid."

        Design: Difficulty/transitive_cascade/deficient_inspection_cancels_paving_reverses_reserve_and_retunes_threshold
        """
        scenario = _cascade_scenario()
        award(scenario["project"]["id"], scenario["bid"]["id"])

        record_access_inspection(
            scenario["segment"]["id"],
            "2026-10-20T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=14,
            measured_turnout_count=2,
            turnaround_present=True,
        )

        association = read_association(scenario["association"]["id"])
        assert association["reserve_balance_cents"] == 600_000, (
            "the balance returns to exactly its pre-award value, not 599999 or 600001"
        )
        assert association["reserve_funding_ratio"] == pytest.approx(0.6, abs=0.0001)
        assert association["reserve_posture"] == "ADEQUATE"

        proposal = read_proposal(scenario["proposal"]["id"])
        assert proposal["required_threshold_bps"] == 5000
        assert proposal["status"] == "DRAFT"
        assert proposal["eligible_weight_total"] == pytest.approx(0, abs=0.0001), (
            "the proposal never opened a round, so no weight was ever snapshotted"
        )

    def test_the_regrade_leaves_the_segment_geometry_and_version_updated(self, api):
        """PRD §3.1: "because the reserve balance rose, `reserve_funding_ratio` and
        `reserve_posture` are recomputed and every `DRAFT` proposal's
        `required_threshold_bps` follows. The segment's own `version` increments by
        one."
        PRD §2.7: "The grade gates three operations, and it gates them at
        different strictnesses. Awarding a `PAVING` project requires the segment to
        be `COMPLIANT`."

        Design: Difficulty/transitive_cascade/deficient_inspection_cancels_paving_reverses_reserve_and_retunes_threshold
        """
        scenario = _cascade_scenario()
        award(scenario["project"]["id"], scenario["bid"]["id"])
        before = read_segment(scenario["segment"]["id"])
        assert before["emergency_access_grade"] == "COMPLIANT"

        record_access_inspection(
            scenario["segment"]["id"],
            "2026-10-20T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=14,
            measured_turnout_count=2,
            turnaround_present=True,
        )

        after = read_segment(scenario["segment"]["id"])
        assert after["version"] == before["version"] + 1
        assert after["emergency_access_grade"] == "DEFICIENT"
        assert after["turnout_count"] == 2
        assert after["required_turnouts"] == 2
