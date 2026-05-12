"""Activity authoring, review, time-gated lifecycle (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    SITE_CODE_LENGTH,
    advance_clock,
    advance_to_completed,
    advance_to_recruiting,
    advance_to_running,
    api_client,
    apply_to_activity,
    approve_activity,
    approve_application,
    assert_activity,
    create_draft_activity,
    create_skill,
    create_verified_volunteer,
    define_activity_role,
    equip_volunteer_with_skills,
    find_partner_sync_events,
    list_partner_sync_events,
    make_activity_times,
    make_organizer_headers,
    make_skilladmin_headers,
    publish_activity,
    reject_activity,
    setup_organizer,
    setup_recruiting_activity,
    submit_activity,
    validate_error,
    validate_success,
)


class TestActivityCreation:
    def test_create_draft_starts_in_draft(self, api):
        """PRD §3.3: 'A draft begins in status of DRAFT with
        Activity.organizer_id stamped to the acting organizer's id.'"""
        organizer = setup_organizer()
        from test_helpers import create_activity_payload, make_activity_times
        payload = create_activity_payload(**make_activity_times())
        res = api.create_activity(payload, make_organizer_headers(organizer["id"]))
        data = validate_success(res, expected_status=201)
        assert_activity(data)
        assert data["status"] == "DRAFT"
        assert data["organizer_id"] == organizer["id"]
        assert data["filled_positions"] == 0


class TestActivitySubmission:
    def test_submit_draft_advances_to_under_review(self, api):
        """PRD §3.3: 'Submission to admin review advances the activity
        from DRAFT to UNDER_REVIEW.'"""
        organizer = setup_organizer()
        activity = create_draft_activity(organizer=organizer)
        res = api.submit_activity(activity["id"], make_organizer_headers(organizer["id"]))
        data = validate_success(res, expected_status=200)
        assert data["status"] == "UNDER_REVIEW"

    def test_submit_with_recruit_open_after_close_rejected(self, api):
        """PRD §3.3: 'Submission requires ... recruit_open_at to be
        strictly less than recruit_close_at, recruit_close_at to be
        strictly less than start_at, start_at to be strictly less than
        end_at.'"""
        organizer = setup_organizer()
        # Build invalid time ordering: open == close (not strictly less).
        bad_times = make_activity_times()
        bad_times["recruit_open_at"] = bad_times["recruit_close_at"]
        activity = create_draft_activity(organizer=organizer, times=bad_times)
        res = api.submit_activity(activity["id"], make_organizer_headers(organizer["id"]))
        # PRD lists multiple ordering rules; this case violates
        # recruit_open < recruit_close. Must reject; either
        # ERR_INVALID_INPUT (field validation) is the natural outcome
        # for ordering violations per PRD §1.4 / §5.
        validate_error(res, "ERR_INVALID_INPUT")

    def test_submit_with_recruit_close_at_or_after_start_rejected(self, api):
        """PRD §3.3: 'Submission requires ... recruit_close_at to be
        strictly less than start_at.'"""
        organizer = setup_organizer()
        from test_helpers import add_hours, CLOCK_BASELINE_ISO
        # close = start (violates strict-less-than)
        start = add_hours(CLOCK_BASELINE_ISO, 24 * 21)
        end = add_hours(start, 2)
        bad_times = {
            "recruit_open_at": add_hours(CLOCK_BASELINE_ISO, 24),
            "recruit_close_at": start,
            "start_at": start,
            "end_at": end,
        }
        activity = create_draft_activity(organizer=organizer, times=bad_times)
        res = api.submit_activity(activity["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_INVALID_INPUT")


class TestActivityApprovalAndPublication:
    def test_approve_advances_to_published_and_mints_site_code(
        self, api, skilladmin_headers
    ):
        """PRD §3.3: 'Approval advances status from UNDER_REVIEW to
        PUBLISHED, mints the activity's six-digit numeric site_code
        (used for on-site check-in), and emits two PartnerSyncEvent rows
        with event_type of ACTIVITY_PUBLISHED — one on channel
        PARTNER_ORG and one on channel IM.'"""
        organizer = setup_organizer()
        activity = create_draft_activity(organizer=organizer)
        submit_activity(activity, organizer)
        res = api.approve_activity(activity["id"], skilladmin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "PUBLISHED"
        site = data.get("site_code")
        assert isinstance(site, str), f"site_code missing: {data!r}"
        assert len(site) == SITE_CODE_LENGTH, f"site_code length {len(site)} != 6"
        assert site.isdigit(), f"site_code must be 6-digit numeric, got {site!r}"

    def test_approve_emits_partner_org_and_im_sync_events(self, api):
        """PRD §3.3: '... emits two PartnerSyncEvent rows with event_type
        of ACTIVITY_PUBLISHED — one on channel PARTNER_ORG and one on
        channel IM.'"""
        organizer = setup_organizer()
        activity = create_draft_activity(organizer=organizer)
        submit_activity(activity, organizer)
        approve_activity(activity["id"])
        events = list_partner_sync_events(event_type="ACTIVITY_PUBLISHED", limit=100)
        assert len(find_partner_sync_events(events, channel="PARTNER_ORG")) >= 1
        assert len(find_partner_sync_events(events, channel="IM")) >= 1

    def test_reject_advances_to_rejected_and_revisable(self, api, skilladmin_headers):
        """PRD §3.3: 'A rejected activity is not terminal: the original
        organizer may pull the rejected activity back to DRAFT for
        revision, and the revision-resubmit-review loop may run any
        number of times.'"""
        organizer = setup_organizer()
        activity = create_draft_activity(organizer=organizer)
        submit_activity(activity, organizer)
        reject_activity(activity["id"])
        res = api.revise_activity(activity["id"], make_organizer_headers(organizer["id"]))
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DRAFT"


class TestTimeGatedTransitions:
    def test_clock_advance_published_to_recruiting(self, api):
        """PRD §3.3: 'When the clock reaches recruit_open_at, the
        activity advances from PUBLISHED to RECRUITING.'"""
        organizer = setup_organizer()
        activity, _ = publish_activity(organizer=organizer)
        assert activity["status"] == "PUBLISHED"
        advance_clock(activity["recruit_open_at"])
        from test_helpers import get_activity
        fresh = get_activity(activity["id"])
        assert fresh["status"] == "RECRUITING"

    def test_clock_advance_recruiting_to_running(self, api):
        """PRD §3.3: 'when the clock reaches start_at, it advances from
        RECRUITING to RUNNING.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        advance_clock(activity["start_at"])
        from test_helpers import get_activity
        fresh = get_activity(activity["id"])
        assert fresh["status"] == "RUNNING"

    def test_clock_advance_running_to_completed(self, api):
        """PRD §3.3: 'when the clock reaches end_at, it advances from
        RUNNING to COMPLETED.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        advance_to_running(activity)
        advance_to_completed(activity)
        from test_helpers import get_activity
        fresh = get_activity(activity["id"])
        assert fresh["status"] == "COMPLETED"

    def test_running_transition_auto_rejects_lingering_applied(self, api):
        """PRD §3.3: 'When the clock reaches start_at, it advances from
        RECRUITING to RUNNING (and as a side effect every Application
        for this activity that is still in APPLIED is auto-rejected,
        advancing those rows to REJECTED).'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        # Don't approve. Move clock forward to start_at.
        advance_to_running(activity)
        from test_helpers import get_application
        fresh = get_application(application["id"])
        assert fresh["status"] == "REJECTED"


class TestShelveActivity:
    def test_shelve_published_with_zero_filled(self, api):
        """PRD §3.3: 'An Organizer may shelve an activity that has
        reached PUBLISHED or RECRUITING if and only if the activity's
        filled_positions is exactly zero — this advances status from
        PUBLISHED (or RECRUITING) to SHELVED and is terminal.'"""
        organizer = setup_organizer()
        activity, _ = publish_activity(organizer=organizer)
        res = api.shelve_activity(activity["id"], make_organizer_headers(organizer["id"]))
        data = validate_success(res, expected_status=200)
        assert data["status"] == "SHELVED"

    def test_shelve_with_filled_positions_rejected(self, api):
        """PRD §3.3: 'A shelve attempt against an activity with one or
        more filled positions is rejected with ERR_INVALID_STATE.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        app = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=app, organizer=organizer)
        res = api.shelve_activity(activity["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_shelve_running_rejected(self, api):
        """PRD §3.3: 'An attempt to shelve a RUNNING or COMPLETED
        activity is rejected with ERR_INVALID_STATE.'"""
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        advance_to_running(activity)
        res = api.shelve_activity(activity["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_INVALID_STATE")
