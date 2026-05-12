"""Resource temporal-overlap conflicts and cross-entity state checks
(PRD §3.4, §3.5). Covers difficulty-design rule 8 instances 1 and 2 and
rule 7 instance 1.
"""
from __future__ import annotations

from test_helpers import (
    add_hours,
    add_minutes,
    add_seconds,
    advance_clock,
    advance_to_recruiting,
    advance_to_running,
    api_client,
    apply_to_activity,
    apply_to_activity_payload,
    approve_application,
    check_in_payload,
    check_in_via_site_code,
    check_out,
    create_verified_volunteer,
    get_activity,
    make_activity_times,
    make_organizer_headers,
    make_volunteer_headers,
    publish_activity,
    setup_organizer,
    setup_recruiting_activity,
    setup_running_activity_with_approved_volunteer,
    validate_error,
    validate_success,
)


class TestVolunteerTimeWindowClosedClosed:
    """difficulty: resource_temporal_overlap/application_volunteer_time_window_closed_closed_overlap"""

    def test_touching_endpoint_at_approve(self, api):
        """PRD §3.4: 'overlap is evaluated as closed-closed intervals,
        so an activity that starts at exactly the moment another ends
        still counts as a conflict and is rejected with
        ERR_TIME_CONFLICT.'

        PRD §3.4: 'the same time-conflict check that applied at apply
        time is re-evaluated at approve time against the volunteer's
        other non-terminal applications, with the same ERR_TIME_CONFLICT
        outcome.'

        Strategy: get Volunteer APPROVED on Activity A first (A is in
        RECRUITING). Then apply to Activity B [start_at == A.end_at] and
        try to approve. PRD includes APPROVED in the non-terminal set
        for the time-conflict check.

        # difficulty: resource_temporal_overlap/application_volunteer_time_window_closed_closed_overlap
        """
        organizer = setup_organizer()

        # Activity A and B times — both publishable into RECRUITING
        # under one shared baseline.
        a_times = {
            "recruit_open_at": "2030-04-01T08:00:00.000Z",
            "recruit_close_at": "2030-04-01T09:30:00.000Z",
            "start_at": "2030-04-01T10:00:00.000Z",
            "end_at": "2030-04-01T12:00:00.000Z",
        }
        b_times = {
            "recruit_open_at": "2030-04-01T08:00:00.000Z",
            "recruit_close_at": "2030-04-01T09:30:00.000Z",
            "start_at": "2030-04-01T12:00:00.000Z",  # touches A.end
            "end_at": "2030-04-01T14:00:00.000Z",
        }

        # Publish both before any clock advance.
        organizer, activity_a, _ = setup_recruiting_activity(
            organizer=organizer, position_quota=5, times=a_times,
        )
        # Activity B share organizer and is published using same baseline.
        from test_helpers import publish_activity, advance_to_recruiting
        activity_b, _ = publish_activity(
            organizer=organizer, position_quota=5, times=b_times,
        )
        activity_b = advance_to_recruiting(activity_b)

        # Volunteer applies to A and is approved.
        v = create_verified_volunteer()
        app_a = apply_to_activity(volunteer=v, activity=activity_a)
        approve_application(application=app_a, organizer=organizer)

        # Now apply to B; PRD §3.4 may reject at apply OR at approve.
        # We want the approve-time test, so apply succeeds when no
        # other APPROVED Application overlaps. Volunteer ALREADY has
        # APPROVED on A, so apply itself may already error — but the
        # difficulty-recipe explicitly tests the APPROVE-time path.
        # Apply MAY succeed or fail; if it succeeds, then approve must
        # fail with ERR_TIME_CONFLICT.
        app_b_res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity_b["id"]),
            make_volunteer_headers(v["id"]),
        )
        if app_b_res.status_code == 201:
            app_b = app_b_res.json()["data"]
            res = api.approve_application(
                app_b["id"], make_organizer_headers(organizer["id"])
            )
            validate_error(res, "ERR_TIME_CONFLICT")
        else:
            # Apply itself rejected with ERR_TIME_CONFLICT — also satisfies
            # the closed-closed touching-endpoint claim.
            validate_error(app_b_res, "ERR_TIME_CONFLICT")


class TestRecruitmentWindowHalfOpen:
    """difficulty: resource_temporal_overlap/activity_recruitment_window_half_open_at_application_create"""

    def test_apply_at_exact_recruit_close_at_returns_recruitment_closed(self, api):
        """PRD §3.4: 'the activity's status is not RECRUITING, or the
        current clock time is outside the half-open recruitment window
        starting at recruit_open_at and ending strictly before
        recruit_close_at (ERR_RECRUITMENT_CLOSED).'

        Setup: Activity with recruit_open_at=08:00, recruit_close_at=09:00,
        start_at=10:00. Advance clock to exactly 09:00 (== recruit_close_at).
        Apply -> ERR_RECRUITMENT_CLOSED because the half-open interval
        excludes the right endpoint.

        # difficulty: resource_temporal_overlap/activity_recruitment_window_half_open_at_application_create
        """
        organizer = setup_organizer()
        times = {
            "recruit_open_at": "2030-06-01T08:00:00.000Z",
            "recruit_close_at": "2030-06-01T09:00:00.000Z",
            "start_at": "2030-06-01T10:00:00.000Z",
            "end_at": "2030-06-01T12:00:00.000Z",
        }
        from test_helpers import publish_activity
        activity, _ = publish_activity(organizer=organizer, times=times)
        # Move clock to recruit_open so Activity reaches RECRUITING.
        advance_clock(times["recruit_open_at"])
        # Volunteer.
        v = create_verified_volunteer()
        # Now move clock to exactly recruit_close_at.
        advance_clock(times["recruit_close_at"])
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_RECRUITMENT_CLOSED")

    def test_apply_one_second_before_recruit_close_at_succeeds(self, api):
        """PRD §3.4: 'the half-open recruitment window starting at
        recruit_open_at and ending strictly before recruit_close_at.'

        Inclusive at left, exclusive at right -> at recruit_close_at -1s,
        the apply succeeds.
        """
        organizer = setup_organizer()
        times = {
            "recruit_open_at": "2030-07-01T08:00:00.000Z",
            "recruit_close_at": "2030-07-01T09:00:00.000Z",
            "start_at": "2030-07-01T10:00:00.000Z",
            "end_at": "2030-07-01T12:00:00.000Z",
        }
        from test_helpers import publish_activity
        activity, _ = publish_activity(organizer=organizer, times=times)
        advance_clock(times["recruit_open_at"])
        v = create_verified_volunteer()
        # 1 second before close.
        before_close = add_seconds(times["recruit_close_at"], -1)
        advance_clock(before_close)
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_success(res, expected_status=201)


class TestCheckInRequiresActivityRunning:
    """difficulty: cross_entity_state_dependency/application_check_in_requires_activity_running"""

    def test_check_in_when_activity_recruiting_rejected_with_invalid_state(self, api):
        """PRD §3.5: 'Once the parent activity reaches RUNNING, the
        volunteer who holds an APPROVED application checks in.'

        With Activity in RECRUITING (not RUNNING), the state-machine
        precondition 'Activity.status == RUNNING' fails -> the
        check-in is not permitted. Per PRD §2.7 priority, the
        state-machine error surfaces.

        # difficulty: cross_entity_state_dependency/application_check_in_requires_activity_running
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=application, organizer=organizer)
        # Activity is RECRUITING. Submit a valid site_code-shaped payload
        # (matching string is unknown until /approve mints it; use a
        # non-empty string to ensure check-in proof would otherwise pass
        # except for the state precondition).
        from test_helpers import get_activity as _get_activity
        a = _get_activity(activity["id"])
        # site_code may be present (PRD §3.3 mints at PUBLISHED). Use the
        # real one if available; either way the state error preempts.
        site = a.get("site_code") or "000000"
        res = api.check_in(
            application["id"], check_in_payload(site_code=site),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")
