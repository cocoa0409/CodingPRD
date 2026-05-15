"""priority_category classification and lottery_weight computation.

Covers PRD §3.4 decision order and the tiered base / poverty multiplier
/ choice-rank decay formula, including the integer-scaling rule from
PRD §2.7 that protects decile boundaries from float drift.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    DEFAULT_BASE_CLOCK,
    accept_application,
    advance_clock_to,
    api_client,
    assert_lottery_weight_matches_prd,
    close_program_window,
    create_application,
    create_program,
    create_school,
    create_district,
    create_student,
    draw_lottery,
    expected_lottery_weight,
    get_application,
    get_family,
    iso_utc,
    open_program_window,
    setup_accepted_application_with_anchor,
    setup_district_with_school_and_program,
    setup_family_at_threshold_exactly,
    setup_family_with_student,
    setup_two_families_threshold_pair,
    submit_application,
    validate_success,
)
from test_helpers import create_family as create_family_h
from test_helpers import make_cross_district_application_with_approved_transfer


class TestPriorityCategory:

    def test_in_district_standard_below_threshold(self, api):
        """PRD §3.4: "Otherwise, if the application does not cross
        district lines, the category is IN_DISTRICT_STANDARD."

        Claim: in-district family with poverty_index_score below the
        district threshold, no anchor, gets IN_DISTRICT_STANDARD.
        """
        district, school, program = setup_district_with_school_and_program(
            poverty_index_threshold=0.50,
        )
        family, student = setup_family_with_student(district, poverty_index_score=0.10)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=1)
        open_program_window(program)
        app = submit_application(family, app)
        assert app["priority_category"] == "IN_DISTRICT_STANDARD"

    def test_in_district_disadvantaged_above_threshold(self, api):
        """PRD §3.4: "Otherwise, if the application does not cross
        district lines and the family's poverty_index_score is at least
        the district's poverty_index_threshold, the category is
        IN_DISTRICT_DISADVANTAGED."
        """
        district, school, program = setup_district_with_school_and_program(
            poverty_index_threshold=0.50,
        )
        family, student = setup_family_with_student(district, poverty_index_score=0.85)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=1)
        open_program_window(program)
        app = submit_application(family, app)
        assert app["priority_category"] == "IN_DISTRICT_DISADVANTAGED"

    def test_sibling_in_district_with_anchor_in_same_district(self, api):
        """PRD §3.4: "if the family currently has a non-null
        head_household_application_id whose program's school sits in
        the same district as this program's school, and the new
        application does not cross district lines ... the category is
        SIBLING_IN_DISTRICT. Sibling priority strictly dominates the
        poverty multiplier in this classifier: a SIBLING_IN_DISTRICT
        application is so categorized even when the family is
        non-disadvantaged."
        """
        district, school, program_anchor, family, _student, anchor_app = (
            setup_accepted_application_with_anchor(seed="sibling-cat")
        )
        # Build a second program under the same school + district and a
        # new student in the same family.
        program2 = create_program(
            district, school,
            grade_level=5, seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=40)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=70)),
            lottery_seed="cat-seed",
        )
        sibling = create_student(family, grade_level_next_year=5)
        sibling_app = create_application(family, sibling, program2, choice_rank=1)
        open_program_window(program2)
        sibling_app = submit_application(family, sibling_app)
        assert sibling_app["priority_category"] == "SIBLING_IN_DISTRICT"

    def test_inter_district_disadvantaged_when_crossing_and_above_threshold(self, api):
        """PRD §3.4: "Otherwise, if the application crosses district
        lines and the family's poverty_index_score is at least the
        district's poverty_index_threshold, the category is
        INTER_DISTRICT_DISADVANTAGED."

        Claim: cross-district + above-threshold yields
        INTER_DISTRICT_DISADVANTAGED. The PRD's "district's
        poverty_index_threshold" is the threshold on the residency
        district per the classifier's "is_disadvantaged" branch.
        """
        # Build manually so we know the residency threshold.
        advance_clock_to(DEFAULT_BASE_CLOCK)
        home = create_district(poverty_index_threshold=0.50)
        target = create_district(
            accepts_inter_district_transfers=True, poverty_index_threshold=0.50,
        )
        target_school = create_school(target, school_type="MAGNET", grade_levels_offered=[5])
        target_program = create_program(
            target, target_school, grade_level=5, seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed="cross-disad",
        )
        family = create_family_h(home, poverty_index_score=0.85)
        student = create_student(family, grade_level_next_year=5)
        app = create_application(family, student, target_program, choice_rank=1)
        from test_helpers import (
            create_transfer_request, approve_transfer_request,
        )
        tr = create_transfer_request(family, app, target)
        approve_transfer_request(target, tr)
        open_program_window(target_program)
        app = submit_application(family, app)
        assert app["priority_category"] == "INTER_DISTRICT_DISADVANTAGED"


class TestLotteryWeightFormula:

    # DELETED: test_lottery_weight_at_threshold_no_boost
    # PRD §3.4 priority_category classifier states "at least the district's
    # poverty_index_threshold" (>=) → at threshold equality yields
    # IN_DISTRICT_DISADVANTAGED. The deleted test asserted the opposite
    # (IN_DISTRICT_STANDARD, weight=2.0) by importing the lottery_weight
    # multiplier's "strictly greater" rule into the classifier — a coupling
    # PRD does not state, so the assertion fails STEP 1b unique derivability.

    def test_lottery_weight_one_decile_above_threshold(self, api):
        """PRD §3.4: "the number of completed deciles by which the
        family exceeds the threshold is computed by integer
        floor-division of their difference by 10; the multiplier is
        then 1.0 plus 0.10 times that decile count."

        Claim: poverty_index_score 0.60 vs threshold 0.50 produces
        deciles=1, multiplier=1.1, category IN_DISTRICT_DISADVANTAGED
        with base=3.0, decay=1.0 → lottery_weight = 3.3.
        """
        bundle = setup_two_families_threshold_pair(
            threshold=0.50, below_or_equal=0.50, above=0.60,
        )
        above_app = bundle["above_app"]
        assert above_app["priority_category"] == "IN_DISTRICT_DISADVANTAGED"
        assert above_app["lottery_weight"] == pytest.approx(3.3, abs=1e-9)

    def test_lottery_weight_rounding_to_four_decimals(self, api):
        """PRD §2.7: "Application.lottery_weight is rounded to four
        decimal places."
        PRD §3.4: "the application's choice_rank minus 1 is the
        exponent applied to the constant 0.85, so a first-choice
        application receives a decay factor of 1.0, a second choice
        receives 0.85, a third 0.7225, and so on. The raw weight is the
        base weight multiplied by the poverty multiplier multiplied by
        the decay factor, and the persisted lottery_weight is that raw
        value rounded half-up to four decimal places."

        Claim: IN_DISTRICT_STANDARD (base=2.0), no boost (mult=1.0),
        choice_rank=5 (decay=0.85^4=0.52200625) →
        2.0 * 1.0 * 0.52200625 = 1.0440125, ROUND_HALF_UP to 4 dp →
        1.0440.
        """
        district, school, program = setup_district_with_school_and_program(
            poverty_index_threshold=0.50, seats_total=5,
        )
        family, student = setup_family_with_student(district, poverty_index_score=0.10)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=5)
        open_program_window(program)
        app = submit_application(family, app)
        expected = expected_lottery_weight(
            "IN_DISTRICT_STANDARD",
            poverty_index_score=0.10,
            poverty_index_threshold=0.50,
            choice_rank=5,
        )
        assert expected == pytest.approx(1.044, abs=1e-9)
        assert app["lottery_weight"] == pytest.approx(expected, abs=1e-9)
