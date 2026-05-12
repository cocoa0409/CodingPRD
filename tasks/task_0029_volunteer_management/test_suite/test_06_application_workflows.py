"""Application approval, withdrawal, check-in, leave, check-out
(PRD §3.4 / §3.5).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    advance_clock,
    advance_to_recruiting,
    advance_to_running,
    apply_to_activity,
    api_client,
    approve_application,
    check_in_payload,
    check_in_via_gps,
    check_in_via_site_code,
    check_out,
    create_verified_volunteer,
    get_activity,
    make_organizer_headers,
    make_volunteer_headers,
    publish_activity,
    request_leave,
    setup_organizer,
    setup_recruiting_activity,
    setup_running_activity_with_approved_volunteer,
    validate_error,
    validate_success,
    withdraw_application,
)


class TestApplicationApproval:
    def test_approve_advances_applied_to_approved_and_increments_filled(self, api):
        """PRD §3.4: 'Successful approval advances Application.status
        from APPLIED to APPROVED and atomically increments
        Activity.filled_positions by exactly 1.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        res = api.approve_application(
            application["id"], make_organizer_headers(organizer["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "APPROVED"
        # Verify filled_positions incremented.
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 1


class TestApplicationRejection:
    def test_reject_advances_applied_to_rejected_terminal(self, api):
        """PRD §3.4: 'Rejection by the same Organizer advances an
        APPLIED application to REJECTED (terminal).'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        res = api.reject_application(
            application["id"], make_organizer_headers(organizer["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REJECTED"


class TestApplicationWithdrawal:
    def test_withdraw_applied_unconditional(self, api):
        """PRD §3.4: 'Withdrawal by the volunteer who owns the
        application has two valid forms: an APPLIED application
        withdraws to WITHDRAWN unconditionally.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        res = api.withdraw_application(
            application["id"], make_volunteer_headers(v["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_approved_during_recruiting_decrements_filled(self, api):
        """PRD §3.4: 'an APPROVED application may be withdrawn by the
        volunteer only while the parent activity is still RECRUITING,
        and the withdrawal additionally decrements
        Activity.filled_positions by exactly 1 to free the slot.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        app = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=app, organizer=organizer)
        # filled_positions == 1 now
        res = api.withdraw_application(app["id"], make_volunteer_headers(v["id"]))
        data = validate_success(res, expected_status=200)
        assert data["status"] == "WITHDRAWN"
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 0

    def test_withdraw_approved_after_recruiting_rejected(self, api):
        """PRD §3.4: 'A withdraw attempt on an APPROVED application
        after the parent activity has progressed past RECRUITING is
        rejected with ERR_INVALID_STATE.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        app = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=app, organizer=organizer)
        advance_to_running(activity)  # past RECRUITING
        res = api.withdraw_application(app["id"], make_volunteer_headers(v["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestCheckIn:
    def test_check_in_with_correct_site_code_advances_to_checked_in(self, api):
        """PRD §3.5: 'Once the parent activity reaches RUNNING, the
        volunteer who holds an APPROVED application checks in. ...
        Successful check-in advances Application.status from APPROVED
        to CHECKED_IN, stamps check_in_at to the current server time.'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        site = activity.get("site_code")
        res = api.check_in(
            application["id"],
            check_in_payload(site_code=site),
            make_volunteer_headers(volunteer["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CHECKED_IN"
        assert data.get("check_in_at") is not None

    def test_check_in_with_close_gps_advances_to_checked_in(self, api):
        """PRD §3.5: 'or the volunteer may submit check_in_lat and
        check_in_lng whose haversine distance to (location_lat,
        location_lng) is at most 0.50 kilometres (500 metres).'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        # Submit GPS exactly at the activity coordinates (distance 0 km).
        res = api.check_in(
            application["id"],
            check_in_payload(
                check_in_lat=activity["location_lat"],
                check_in_lng=activity["location_lng"],
            ),
            make_volunteer_headers(volunteer["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CHECKED_IN"

    def test_check_in_with_no_proof_rejected(self, api):
        """PRD §3.5: 'Lacking either valid proof, the attempt is
        rejected with ERR_CHECK_IN_PROOF_FAILED.'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        res = api.check_in(
            application["id"],
            check_in_payload(),  # no site_code, no GPS
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(res, "ERR_CHECK_IN_PROOF_FAILED")

    def test_late_marker_set_when_check_in_more_than_15_min_late(self, api):
        """PRD §3.5: 'if check_in_at is later than Activity.start_at
        plus 15 minutes — sets late_marker to true.'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        # Advance clock to start_at + 16 minutes.
        advance_clock(add_minutes(activity["start_at"], 16))
        site = activity.get("site_code")
        res = api.check_in(
            application["id"],
            check_in_payload(site_code=site),
            make_volunteer_headers(volunteer["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["late_marker"] is True

    def test_late_marker_not_set_when_check_in_at_15_min_exact(self, api):
        """PRD §3.5: 'if check_in_at is later than Activity.start_at plus
        15 minutes — sets late_marker to true.' Boundary: at exactly
        +15 minutes, 'later than' is false, so late_marker stays false.
        """
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        advance_clock(add_minutes(activity["start_at"], 15))
        site = activity.get("site_code")
        res = api.check_in(
            application["id"],
            check_in_payload(site_code=site),
            make_volunteer_headers(volunteer["id"]),
        )
        data = validate_success(res, expected_status=200)
        # PRD says "later than start_at + 15 minutes". At exactly
        # +15 min it is NOT later than.
        assert data["late_marker"] is False


class TestLeave:
    def test_leave_advances_checked_in_to_on_leave(self, api):
        """PRD §3.5: 'A CHECKED_IN volunteer who must temporarily leave
        during a RUNNING activity submits a leave request with a
        leave_reason of 1 to 500 characters; this advances the
        application from CHECKED_IN to ON_LEAVE.'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        res = api.request_leave(
            application["id"],
            {"leave_reason": "Family emergency requiring brief absence."},
            make_volunteer_headers(volunteer["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ON_LEAVE"


class TestCheckOut:
    def test_check_out_advances_checked_in_to_completed(self, api):
        """PRD §3.5: 'Check-out by a CHECKED_IN volunteer (the parent
        activity must still be in RUNNING) advances
        Application.status from CHECKED_IN to COMPLETED and stamps
        check_out_at to the current server time.'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Advance clock to start_at + 60 min (well within window, no early-departure).
        advance_clock(add_minutes(activity["start_at"], 60))
        # Step the clock to one second short of end_at. Advancing to exactly
        # end_at would cause the impl's clock-sweep to auto-cascade
        # RUNNING -> COMPLETED (per PRD §3.3) and complete the application
        # before our manual /check-out call could fire.
        from test_helpers import add_seconds
        advance_clock(add_seconds(activity["end_at"], -1))
        res = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "COMPLETED"
        assert data.get("check_out_at") is not None

    def test_early_departure_marker_set_when_check_out_more_than_15_min_early(
        self, api
    ):
        """PRD §3.5: 'If check_out_at is earlier than Activity.end_at
        minus 15 minutes, early_departure_marker is set to true.'"""
        scenario = setup_running_activity_with_approved_volunteer()
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Activity is 2h. end - 15min would still be 1h45m in. We
        # check out at start + 90min => 30 min before end => earlier
        # than end - 15min.
        advance_clock(add_minutes(activity["start_at"], 90))
        res = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["early_departure_marker"] is True
