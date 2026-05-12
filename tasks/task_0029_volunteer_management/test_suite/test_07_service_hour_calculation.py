"""Service-hour calculation under the three hour_rule_type branches and
penalty rules (PRD §3.6). Also covers difficulty-design rule 1
(dual-variant-calc on Application) and rule 4 instance 1
(check-out cascade depth-4) — both via Application.adjusted_hours.
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
    create_skill,
    create_verified_volunteer,
    declare_and_approve_skill,
    define_activity_role,
    equip_volunteer_with_skills,
    get_application,
    get_volunteer,
    make_organizer_headers,
    make_volunteer_headers,
    publish_activity,
    request_leave,
    setup_completed_application,
    setup_organizer,
    setup_recruiting_activity,
    setup_running_activity_with_approved_volunteer,
    validate_success,
)


class TestActualDurationBranch:
    """difficulty: dual_variant_calc/service_hour_calc_actual_vs_fixed_on_application"""

    def test_actual_duration_30_min_credits_half_hour(self, api):
        """PRD §3.6: 'When hour_rule_type is ACTUAL_DURATION, raw hours
        equal the elapsed time from check_in_at to check_out_at
        expressed in hours (the difference in seconds divided by
        3600).'

        Claim: 30 minutes ACTUAL_DURATION + EASY + no role -> credited 0.50h.

        Activity is sized so the 30-minute check-out lands at exactly
        Activity.end_at minus 15 minutes; PRD §3.5 sets the
        early_departure_marker only when check_out_at is STRICTLY EARLIER
        than end_at - 15 min, so this checkout does NOT trigger the
        early-departure penalty and the raw-hour computation is exposed
        cleanly.

        # difficulty: dual_variant_calc/service_hour_calc_actual_vs_fixed_on_application
        """
        from test_helpers import make_activity_times
        # 45-minute window: end_at - 15 min == start_at + 30 min.
        times = make_activity_times(duration_hours=0.75)
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="EASY",
            hour_rule_type="ACTUAL_DURATION",
            times=times,
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Check out 30 minutes after start_at == end_at - 15 min (not early).
        advance_clock(add_minutes(activity["start_at"], 30))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        assert application["status"] == "COMPLETED"
        assert application["credited_hours"] == pytest.approx(0.50, abs=0.005)
        assert application["adjusted_hours"] == pytest.approx(0.50, abs=0.005)


class TestFixedValueBranch:
    """difficulty: dual_variant_calc/service_hour_calc_actual_vs_fixed_on_application"""

    def test_fixed_value_30_min_attendance_credits_full_fixed_value(self, api):
        """PRD §3.6: 'When hour_rule_type is FIXED_VALUE, raw hours
        equal the parent activity's fixed_hour_value verbatim
        regardless of how long the volunteer was actually present — a
        30-minute attendance still credits the full fixed value.'

        Claim: 30 min attendance under FIXED_VALUE=3.50 -> credited 3.50h.

        Activity is sized so the 30-minute check-out lands at exactly
        Activity.end_at minus 15 minutes; PRD §3.5 sets the
        early_departure_marker only when check_out_at is STRICTLY EARLIER
        than end_at - 15 min, so this checkout does NOT trigger the
        early-departure penalty and the raw FIXED_VALUE is exposed
        cleanly without the 0.75 multiplier confounding the assertion.

        # difficulty: dual_variant_calc/service_hour_calc_actual_vs_fixed_on_application
        """
        from test_helpers import make_activity_times
        # 45-minute window so 30-min check_out == end_at - 15 min (not early).
        times = make_activity_times(duration_hours=0.75)
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="EASY",
            hour_rule_type="FIXED_VALUE",
            fixed_hour_value=3.50,
            times=times,
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        advance_clock(add_minutes(activity["start_at"], 30))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        assert application["credited_hours"] == pytest.approx(3.50, abs=0.005)
        assert application["adjusted_hours"] == pytest.approx(3.50, abs=0.005)


class TestRoleCoefficientBranch:
    def test_role_coefficient_doubles_actual_duration_at_2x(self, api):
        """PRD §3.6: 'When hour_rule_type is ROLE_COEFFICIENT, raw
        hours equal the elapsed hours from check_in_at to check_out_at
        multiplied by the assigned ActivityRole.coefficient, so the
        same elapsed time produces different hours for a
        higher-coefficient role than for a lower-coefficient one.'

        Activity is sized so the 60-minute check-out lands at exactly
        Activity.end_at minus 15 minutes; PRD §3.5 sets the
        early_departure_marker only when check_out_at is STRICTLY EARLIER
        than end_at - 15 min, so this checkout does NOT trigger the
        early-departure penalty and the raw role-coefficient hours are
        exposed cleanly.
        """
        from test_helpers import make_activity_times
        # 75-min window: end_at - 15 min == start_at + 60 min.
        times = make_activity_times(duration_hours=1.25)
        organizer, activity, roles = setup_recruiting_activity(
            difficulty="EASY",
            hour_rule_type="ROLE_COEFFICIENT",
            role_labels=["LEAD"],
            role_coefficients={"LEAD": 2.00},
            times=times,
        )
        v = create_verified_volunteer()
        app = apply_to_activity(
            volunteer=v, activity=activity, activity_role_id=roles[0]["id"]
        )
        approve_application(application=app, organizer=organizer)
        advance_to_running(activity)
        app = check_in_via_site_code(application=app, volunteer=v, activity=activity)
        # Actual: 60 minutes. Coefficient 2.00 => raw = 1.00 * 2 = 2.00 hours.
        advance_clock(add_minutes(activity["start_at"], 60))
        app = api.check_out(app["id"], make_volunteer_headers(v["id"])).json()["data"]
        assert app["credited_hours"] == pytest.approx(2.00, abs=0.005)


class TestPenalties:
    def test_leave_penalty_halves_credited_hours(self, api):
        """PRD §3.6: 'if Application.leave_reason is non-null at any
        point in the application's history (that is, the application
        reached ON_LEAVE at some point), raw hours are multiplied by
        0.50.'"""
        from test_helpers import add_seconds
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="EASY", hour_rule_type="ACTUAL_DURATION",
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Reach ON_LEAVE then check out 1 second before end_at; the 1-second
        # nudge keeps the volunteer-initiated /check-out path open (advancing
        # to exactly end_at would auto-cascade RUNNING -> COMPLETED inside the
        # impl's clock sweep). The 1-second offset rounds to 0.00h at the
        # PRD §2.5 two-decimal precision so credited hours stay at 2.00 raw.
        request_leave(application=application, volunteer=volunteer)
        advance_clock(add_seconds(activity["end_at"], -1))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        # raw = 2.00 hours; with leave penalty 0.50 -> 1.00.
        assert application["credited_hours"] == pytest.approx(1.00, abs=0.005)

    def test_early_departure_penalty_multiplies_by_0_75(self, api):
        """PRD §3.6: 'if Application.early_departure_marker is true and
        the leave penalty did not already fire (i.e., leave_reason is
        null), the result is multiplied by 0.75 instead.'"""
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="EASY", hour_rule_type="ACTUAL_DURATION",
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Check out 90 min in (more than 15 min before end -> early-departure).
        advance_clock(add_minutes(activity["start_at"], 90))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        assert application["early_departure_marker"] is True
        # raw = 1.50 hours; * 0.75 = 1.125 -> rounded half-up to 1.13.
        assert application["credited_hours"] == pytest.approx(1.13, abs=0.005)

    def test_leave_penalty_dominates_early_departure(self, api):
        """PRD §3.6: 'A leave penalty already paid means the
        early-departure penalty does not additionally apply — the two
        are mutually exclusive in this order.'"""
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="EASY", hour_rule_type="ACTUAL_DURATION",
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        request_leave(application=application, volunteer=volunteer)
        # Check out 90 min in (early-departure flag would also fire).
        advance_clock(add_minutes(activity["start_at"], 90))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        # raw = 1.50; leave penalty 0.50 -> 0.75. NOT 1.50 * 0.75 * 0.50 = 0.5625.
        assert application["credited_hours"] == pytest.approx(0.75, abs=0.005)


class TestCheckoutToVolunteerCascade:
    """difficulty: transitive_cascade/checkout_to_hour_calc_to_points_to_volunteer_balance"""

    def test_checkout_cascade_into_volunteer_totals(self, api):
        """PRD §3.5: 'As the same logical transaction,
        Volunteer.total_completed_activities is incremented by 1,
        Volunteer.total_service_hours is increased by the
        freshly-computed Application.adjusted_hours, and
        Volunteer.points_balance is increased by the freshly-computed
        Application.points_awarded.'

        # difficulty: transitive_cascade/checkout_to_hour_calc_to_points_to_volunteer_balance
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM",
            hour_rule_type="ACTUAL_DURATION",
            role_label="LEAD",
            duration_hours=2,
        )
        volunteer = scenario["volunteer"]
        application = scenario["application"]
        # 2.00 hours under ACTUAL_DURATION; MEDIUM=1.50, LEAD=1.20.
        # base = round(2.00 * 10, 2) = 20.00.
        # raw = 20.00 * 1.50 * 1.20 = 36.00. floor -> 36.
        assert application["credited_hours"] == pytest.approx(2.00, abs=0.005)
        assert application["adjusted_hours"] == pytest.approx(2.00, abs=0.005)
        assert int(application["points_awarded"]) == 36
        # Volunteer cascades.
        assert_volunteer_totals(
            volunteer,
            expected_total_service_hours=2.00,
            expected_points_balance=36,
            expected_total_completed_activities=1,
        )
