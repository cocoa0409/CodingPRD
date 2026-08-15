"""Attendance reporting/review/audit, the dispute-resubmit cycle, duplicate
open reports, and the transitive cascades into slots and campaigns."""
from test_helpers import (
    ApiErrorId, constants, make_auditor_headers, make_network_ops_headers,
    make_sales_manager_headers, make_theater_ops_headers, setup_played_slot,
    setup_showtime_with_reel, validate_error, validate_success,
)
from test_helpers.factories import (
    audit_attendance_payload, create_attendance_report_payload,
    create_playlog_payload, review_attendance_payload,
)
from test_helpers.fixtures import (
    AUDITOR_1, SM_CREATOR, create_showtime_with_reel, dispatch_and_deliver,
    record_playlog, reserve_slot, set_clock, setup_theater_screen_feature,
    submit_and_accept_attendance,
)
from test_helpers.fixtures import create_approved_campaign, lock_reel


class TestAttendanceDisputeCycle:
    def test_attendance_dispute_resubmit_cycle_resubmit_clears_reviewer(self, api):
        """PRD §3.5: "resubmission carries a fresh `reported_attendance`,
        returns the report `DISPUTED → SUBMITTED`, and clears
        `reviewed_by_user_id` so the review cycle begins again."

        Design: Corner/state_machines/attendance_dispute_resubmit_cycle
        """
        _, _, _, showtime, _ = setup_showtime_with_reel()
        # Recover the owning theater id through the showtime's screen.
        screen = validate_success(api.get_screen(showtime["screen_id"], make_network_ops_headers()))
        theater_id = screen["theater_id"]
        resp = api.create_attendance_report(showtime["id"],
                                            create_attendance_report_payload(reported_attendance=175),
                                            make_theater_ops_headers(theater_id))
        report = validate_success(resp, expected_status=201)
        api.review_attendance_report(report["id"], review_attendance_payload("DISPUTE"),
                                     make_network_ops_headers())
        resp = api.resubmit_attendance_report(report["id"],
                                              create_attendance_report_payload(reported_attendance=180),
                                              make_theater_ops_headers(theater_id))
        resubmitted = validate_success(resp)
        assert resubmitted["report_status"] == "SUBMITTED"
        assert resubmitted["reported_attendance"] == 180
        assert resubmitted["reviewed_by_user_id"] is None

    def test_attendance_dispute_resubmit_cycle_accept_applies_new_figure(self, api):
        """PRD §3.5: "An `ACCEPT` decision moves the report `SUBMITTED →
        ACCEPTED`, stamps `reviewed_by_user_id`, and — critically — sets the
        showtime's `actual_attendance` to the report's `reported_attendance`."

        Design: Corner/state_machines/attendance_dispute_resubmit_cycle
        """
        _, _, _, showtime, _ = setup_showtime_with_reel()
        screen = validate_success(api.get_screen(showtime["screen_id"], make_network_ops_headers()))
        theater_id = screen["theater_id"]
        resp = api.create_attendance_report(showtime["id"],
                                            create_attendance_report_payload(reported_attendance=175),
                                            make_theater_ops_headers(theater_id))
        report = validate_success(resp, expected_status=201)
        api.review_attendance_report(report["id"], review_attendance_payload("DISPUTE"),
                                     make_network_ops_headers())
        api.resubmit_attendance_report(report["id"],
                                       create_attendance_report_payload(reported_attendance=180),
                                       make_theater_ops_headers(theater_id))
        resp = api.review_attendance_report(report["id"], review_attendance_payload("ACCEPT"),
                                            make_network_ops_headers())
        assert validate_success(resp)["report_status"] == "ACCEPTED"
        resp = api.get_showtime(showtime["id"], make_network_ops_headers())
        assert validate_success(resp)["actual_attendance"] == 180


class TestDuplicateOpenReport:
    def test_duplicate_open_attendance_report_while_submitted(self, api):
        """PRD §3.5: "is refused with `ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT`
        while any earlier report for the same showtime still sits in `SUBMITTED`
        or `ACCEPTED`."

        Design: Corner/errors/duplicate_open_attendance_report_rejected
        """
        _, _, _, showtime, _ = setup_showtime_with_reel()
        screen = validate_success(api.get_screen(showtime["screen_id"], make_network_ops_headers()))
        theater_id = screen["theater_id"]
        api.create_attendance_report(showtime["id"],
                                     create_attendance_report_payload(reported_attendance=175),
                                     make_theater_ops_headers(theater_id))
        resp = api.create_attendance_report(showtime["id"],
                                            create_attendance_report_payload(reported_attendance=180),
                                            make_theater_ops_headers(theater_id))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT)

    def test_duplicate_open_attendance_report_while_accepted(self, api):
        """PRD §3.5: "is refused with `ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT`
        while any earlier report for the same showtime still sits in `SUBMITTED`
        or `ACCEPTED`."

        Design: Corner/errors/duplicate_open_attendance_report_rejected
        """
        _, _, _, showtime, _ = setup_showtime_with_reel()
        screen = validate_success(api.get_screen(showtime["screen_id"], make_network_ops_headers()))
        theater_id = screen["theater_id"]
        resp = api.create_attendance_report(showtime["id"],
                                            create_attendance_report_payload(reported_attendance=175),
                                            make_theater_ops_headers(theater_id))
        report = validate_success(resp, expected_status=201)
        api.review_attendance_report(report["id"], review_attendance_payload("ACCEPT"),
                                     make_network_ops_headers())
        resp = api.create_attendance_report(showtime["id"],
                                            create_attendance_report_payload(reported_attendance=180),
                                            make_theater_ops_headers(theater_id))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT)


class TestAuditPreconditions:
    def test_audit_submitted_report_rejected(self, api):
        """PRD §3.5: "Audit requires the report to be in `ACCEPTED`; auditing a
        report in any other state is rejected with
        `ERR_ATTENDANCE_NOT_AUDITABLE`."

        Design: Corner/errors/audit_submitted_report_rejected
        """
        _, _, _, showtime, _ = setup_showtime_with_reel()
        screen = validate_success(api.get_screen(showtime["screen_id"], make_network_ops_headers()))
        theater_id = screen["theater_id"]
        resp = api.create_attendance_report(showtime["id"],
                                            create_attendance_report_payload(reported_attendance=175),
                                            make_theater_ops_headers(theater_id))
        report = validate_success(resp, expected_status=201)
        resp = api.audit_attendance_report(report["id"], audit_attendance_payload(audited_attendance=150),
                                           make_auditor_headers(AUDITOR_1))
        validate_error(resp, ApiErrorId.ERR_ATTENDANCE_NOT_AUDITABLE)
        resp = api.list_attendance_reports(showtime["id"], make_network_ops_headers())
        reports = validate_success(resp)
        assert reports[0]["report_status"] == "SUBMITTED"


class TestAuditRevisionCascadeDepth3:
    def test_audit_revises_showtime_and_slot(self, api):
        """PRD §3.5: "A successful audit moves the report `ACCEPTED → AUDITED`,
        stamps `audited_by_user_id`, rewrites the showtime's `actual_attendance`
        to the `audited_attendance`, and re-runs the same attribution and
        delivery cascades as an acceptance."

        Design: Difficulty/transitive_cascade/audit_revision_cascade_depth3
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED")
        resp = api.audit_attendance_report(ctx["report"]["id"],
                                           audit_attendance_payload(audited_attendance=150),
                                           make_auditor_headers(AUDITOR_1))
        audited = validate_success(resp)
        assert audited["report_status"] == "AUDITED"
        resp = api.get_showtime(ctx["showtime"]["id"], make_network_ops_headers())
        assert validate_success(resp)["actual_attendance"] == 150
        resp = api.get_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["attributed_impressions"] == 150

    def test_audit_revises_campaign_delivered(self, api):
        """PRD §3.5: "That assignment cascades immediately: every `PLAYED` slot
        on the showtime recomputes its `attributed_impressions` from the new
        figure, and every affected campaign recomputes its
        `delivered_impressions`."

        Design: Difficulty/transitive_cascade/audit_revision_cascade_depth3
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED")
        resp = api.get_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["delivered_impressions"] == 175
        api.audit_attendance_report(ctx["report"]["id"],
                                    audit_attendance_payload(audited_attendance=150),
                                    make_auditor_headers(AUDITOR_1))
        resp = api.get_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["delivered_impressions"] == 150


class TestPlaylogFailureCascadeDepth2:
    def _setup_two_slots_one_played(self, api):
        """Two slots of one campaign on two showtimes, both reels DELIVERED,
        both showtimes report 175 ACCEPTED, slot1 VERIFIED. Returns context."""
        theater, screen, feature = setup_theater_screen_feature()
        st1, r1 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        st2, r2 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-15T19:00:00Z")
        campaign = create_approved_campaign()
        sl1 = reserve_slot(r1["id"], campaign["id"], reel_version=r1["version"])
        sl2 = reserve_slot(r2["id"], campaign["id"], reel_version=r2["version"])
        lock_reel(r1["id"])
        lock_reel(r2["id"])
        dispatch_and_deliver(r1["id"], theater["id"])
        dispatch_and_deliver(r2["id"], theater["id"])
        set_clock(constants.AFTER_SHOW_CLOCK_DAY2)
        submit_and_accept_attendance(st1["id"], theater["id"], 175)
        submit_and_accept_attendance(st2["id"], theater["id"], 175)
        record_playlog(sl1["id"], theater["id"], outcome="VERIFIED")
        return {
            "theater": theater, "campaign": campaign,
            "st1": st1, "st2": st2, "r1": r1, "r2": r2, "sl1": sl1, "sl2": sl2,
        }

    def test_failed_playlog_moves_slot_to_missed(self, api):
        """PRD §3.4: "`FAILED` moves it `CONFIRMED → MISSED`."
        PRD §3.4: "A failed slot instead takes a `play_factor` of 0.0 and an
        `attributed_impressions` of 0."

        Design: Difficulty/transitive_cascade/playlog_failure_cascade_depth2
        """
        ctx = self._setup_two_slots_one_played(api)
        resp = api.create_playlog(ctx["sl2"]["id"], create_playlog_payload(outcome="FAILED"),
                                  make_theater_ops_headers(ctx["theater"]["id"]))
        validate_success(resp, expected_status=201)
        resp = api.get_slot(ctx["sl2"]["id"], make_sales_manager_headers(SM_CREATOR))
        slot = validate_success(resp)
        assert slot["slot_status"] == "MISSED"
        assert slot["play_factor"] == 0.0
        assert slot["attributed_impressions"] == 0

    def test_failed_playlog_recomputes_campaign_delivered(self, api):
        """PRD §3.2: "`delivered_impressions` is the sum of
        `attributed_impressions` over the campaign's `PLAYED` slots, with slots
        whose attribution is still null contributing zero; it is recomputed
        immediately whenever a playback outcome lands and whenever an attendance
        figure is accepted or revised."

        Design: Difficulty/transitive_cascade/playlog_failure_cascade_depth2
        """
        ctx = self._setup_two_slots_one_played(api)
        resp = api.get_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["delivered_impressions"] == 175
        api.create_playlog(ctx["sl2"]["id"], create_playlog_payload(outcome="FAILED"),
                           make_theater_ops_headers(ctx["theater"]["id"]))
        resp = api.get_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        # The surviving VERIFIED slot still contributes 175; the MISSED slot
        # contributes nothing.
        assert validate_success(resp)["delivered_impressions"] == 175
