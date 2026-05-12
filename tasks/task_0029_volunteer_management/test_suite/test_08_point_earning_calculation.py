"""Point-earning calculation order, multipliers, and floor (PRD §3.7).
Covers difficulty-design rule 1 instance 2 (point_earn_calc on Volunteer
balance) and rule 2 instance 1 (three-factor combinatorial formula with
pinned rounding order).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    advance_clock,
    advance_to_running,
    api_client,
    apply_to_activity,
    approve_application,
    assert_volunteer_totals,
    check_in_via_site_code,
    create_verified_volunteer,
    file_hour_adjustment,
    get_application,
    get_volunteer,
    make_volunteer_headers,
    setup_completed_application,
    setup_recruiting_activity,
    validate_success,
)


class TestPointMultiplierMatrix:
    @pytest.mark.parametrize(
        "difficulty, role_label, hours, expected_points",
        [
            # base = round(hours*10, 2). raw = base * diff * role. floor.
            ("EASY", None, 1.00, 10),     # 10.00 * 1.00 * 1.00 = 10.00 -> 10
            ("EASY", "REGULAR", 1.00, 9), # 10.00 * 1.00 * 0.90 = 9.00 -> 9
            ("MEDIUM", "SUPPORT", 1.00, 15),  # 10.00 * 1.50 * 1.00 = 15
            ("MEDIUM", "LEAD", 2.00, 36),     # 20.00 * 1.50 * 1.20 = 36
            ("HARD", "LEAD", 1.00, 24),       # 10.00 * 2.00 * 1.20 = 24
        ],
    )
    def test_difficulty_role_multiplier_table(
        self, api, difficulty, role_label, hours, expected_points
    ):
        """PRD §3.7: 'a difficulty multiplier is taken from the parent
        Activity.difficulty: EASY maps to 1.00, MEDIUM to 1.50, and
        HARD to 2.00. Third, a role multiplier is taken from the
        assigned ActivityRole.role_label (this is the label string, not
        the numeric coefficient): LEAD maps to 1.20, SUPPORT to 1.00,
        and REGULAR to 0.90; if no ActivityRole is assigned to the
        application, the role multiplier is 1.00.'"""
        scenario = setup_completed_application(
            difficulty=difficulty,
            hour_rule_type="ACTUAL_DURATION",
            role_label=role_label,
            duration_hours=int(hours),
        )
        application = scenario["application"]
        assert int(application["points_awarded"]) == expected_points


class TestRoundingOrder:
    """difficulty: combinatorial_formula/point_earn_calc_three_factor_with_pinned_rounding_order"""

    def test_pinned_order_round_base_then_multiply_then_floor(self, api):
        """PRD §3.7: 'IMPORTANT: rounding order — base is rounded to 2
        decimals BEFORE multiplication; final points are floored, NOT
        rounded half-up.'

        Recipe: 1.50 hours * early-departure 0.75 = 1.125 -> round_half_up
        to 1.13 (adjusted_hours). base = round(1.13 * 10, 2) = 11.30.
        raw = 11.30 * 1.50 * 1.20 = 20.34. floor = 20.

        # difficulty: combinatorial_formula/point_earn_calc_three_factor_with_pinned_rounding_order
        """
        from test_helpers import setup_running_activity_with_approved_volunteer
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="MEDIUM",
            hour_rule_type="ACTUAL_DURATION",
            role_label="LEAD",
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Activity is 2h. start_at + 90 min = 30 min before end -> early-departure.
        advance_clock(add_minutes(activity["start_at"], 90))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        assert application["early_departure_marker"] is True
        assert application["adjusted_hours"] == pytest.approx(1.13, abs=0.005)
        assert int(application["points_awarded"]) == 20
        volunteer = get_volunteer(volunteer["id"])
        assert volunteer["points_balance"] == 20


class TestAdjustmentRecomputeUsesDelta:
    """difficulty: dual_variant_calc/point_earn_calc_completion_vs_adjustment_on_volunteer_balance"""

    def test_adjustment_recompute_increments_balance_by_delta_only(self, api):
        """PRD §3.7: 'When an approved HourAdjustment later changes
        Application.adjusted_hours, the calculation re-runs with the
        updated adjusted_hours; the volunteer's points_balance is then
        incremented (or decremented) only by the delta between the new
        and old points_awarded, never by the full new amount.'

        Setup: COMPLETED Application with adjusted_hours=2.00,
        points_awarded=36, Volunteer.points_balance=36 (MEDIUM/LEAD).
        Approve HourAdjustment delta=+0.50:
          new adjusted_hours = 2.50
          new base = round(2.50 * 10, 2) = 25.00
          new raw = 25.00 * 1.50 * 1.20 = 45.00 -> floor 45
          delta = 45 - 36 = 9
          balance: 36 + 9 = 45 (NOT 36 + 45 = 81)

        # difficulty: dual_variant_calc/point_earn_calc_completion_vs_adjustment_on_volunteer_balance
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM",
            hour_rule_type="ACTUAL_DURATION",
            role_label="LEAD",
            duration_hours=2,
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        organizer = scenario["organizer"]
        # Sanity: starting state.
        assert int(application["points_awarded"]) == 36
        assert int(volunteer["points_balance"]) == 36

        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=0.50
        )
        from test_helpers import approve_hour_adjustment
        approve_hour_adjustment(adj["id"])

        # Refetch and assert.
        new_app = get_application(application["id"])
        new_v = get_volunteer(volunteer["id"])
        assert new_app["adjusted_hours"] == pytest.approx(2.50, abs=0.005)
        assert int(new_app["points_awarded"]) == 45
        assert_volunteer_totals(
            new_v,
            expected_total_service_hours=2.50,
            expected_points_balance=45,
        )
