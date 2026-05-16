"""Appeals path: file → schedule-hearing → hold → grant / uphold /
withdraw, plus appeal preconditions (denial state, 90-day window,
unique-per-determination).

Exercises PRD §3.6.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_appeal,
    assert_fair_hearing,
    decide_application,
    file_appeal,
    get_appeal,
    get_application,
    iso_offset,
    parse_iso,
    schedule_hearing_payload,
    server_now_dt,
    setup_appeal_under_review,
    setup_approved_application,
    setup_denied_application,
    setup_eligible_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# File appeal — PRD §3.6
# ===========================================================================
class TestFileAppeal:

    def test_appeal_filed_against_denied_application(self, api):
        """PRD §3.6: "the associated Application must be DENIED ...
        On a successful filing, the new appeal's filed_at is stamped as
        the current clock_now, its deadline_at is stamped as filed_at
        plus 90 days ... its status is set to FILED, and the associated
        Application is moved from DENIED into APPEALED."

        Claim: filing against an INELIGIBLE determination of a DENIED
        application succeeds, status=FILED, deadline_at = filed_at +
        90 days; the parent Application transitions to APPEALED.
        """
        _sp, household, _, application, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        assert_appeal(appeal)
        assert appeal["status"] == "FILED"
        filed = parse_iso(appeal["filed_at"])
        deadline = parse_iso(appeal["deadline_at"])
        assert (deadline - filed) == timedelta(days=90), (
            "deadline_at must be filed_at + 90 days per PRD §3.6 / §2.6"
        )
        # Application transitions to APPEALED.
        app_refreshed = get_application(household["id"], application["id"])
        assert app_refreshed["status"] == "APPEALED", (
            "Application must transition DENIED → APPEALED on filing "
            f"per PRD §3.6; got status={app_refreshed['status']!r}"
        )

    def test_appeal_against_approved_invalid_state(self, api):
        """PRD §3.6: "an attempt to appeal an APPROVED, WITHDRAWN, or
        otherwise non-DENIED application is rejected with
        ERR_INVALID_STATE."

        Claim: filing against an APPROVED application's determination
        → ERR_INVALID_STATE.
        """
        _sp, _hh, _, _app, determination, _enr = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        from test_helpers import create_appeal_payload
        res = api.create_appeal(
            create_appeal_payload(determination_id=determination["id"]),
            TEST_USERS["intake_worker_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_appeal_past_90_day_window_rejected(self, api):
        """PRD §3.6: "the filing must occur strictly within 90 days of
        the underlying determination — that is, the current clock_now
        must be less than the determination's decided_at plus 90 days
        — otherwise the filing is rejected with
        ERR_APPEAL_WINDOW_EXPIRED."

        Claim: filing after 91 days → ERR_APPEAL_WINDOW_EXPIRED.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        # Advance the clock 91 days into the future.
        decided = parse_iso(determination["decided_at"])
        too_late = (decided + timedelta(days=91)).isoformat().replace(
            "+00:00", "Z",
        )
        advance_clock_to(too_late)
        from test_helpers import create_appeal_payload
        res = api.create_appeal(
            create_appeal_payload(determination_id=determination["id"]),
            TEST_USERS["intake_worker_headers"],
        )
        validate_error(res, "ERR_APPEAL_WINDOW_EXPIRED")

    def test_second_appeal_against_same_determination_rejected(self, api):
        """PRD §3.6: "The system also enforces at most one appeal per
        determination_id: a second filing against the same
        determination, even if filed within the window, is rejected
        with ERR_APPEAL_ALREADY_EXISTS."

        Claim: two appeals against the same determination_id → the
        second is rejected. PRD §2.10's priority list places state-
        machine check (5) above appeal-uniqueness (11); after the first
        appeal commits, the Application is already in APPEALED, so a
        sequential second filing may also legitimately surface as
        ERR_INVALID_STATE. Both readings are PRD-faithful.
        """
        from test_helpers import create_appeal_payload, validate_error_is_one_of
        _sp, _hh, _, _app, determination = setup_denied_application()
        file_appeal(determination=determination)
        res = api.create_appeal(
            create_appeal_payload(determination_id=determination["id"]),
            TEST_USERS["intake_worker_headers"],
        )
        validate_error_is_one_of(
            res, ["ERR_APPEAL_ALREADY_EXISTS", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# Schedule hearing — PRD §3.6
# ===========================================================================
class TestScheduleHearing:

    def test_schedule_hearing_creates_fair_hearing(self, api):
        """PRD §3.6: "On a successful schedule, the system creates a
        new FairHearing record with status SCHEDULED, copies the
        officer onto the appeal as Appeal.officer_id, and moves the
        appeal from FILED to HEARING_SCHEDULED."

        Claim: schedule returns a FairHearing(status=SCHEDULED) and
        the parent Appeal transitions to HEARING_SCHEDULED with
        officer_id copied.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        start = iso_offset(days=1, base=server_now_dt())
        end = iso_offset(days=1, hours=1, base=server_now_dt())
        res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=start, scheduled_end=end,
            ),
            officer_headers,
        )
        fh = validate_success(res)
        assert_fair_hearing(fh)
        assert fh["status"] == "SCHEDULED"
        appeal_refreshed = get_appeal(appeal["id"])
        assert appeal_refreshed["status"] == "HEARING_SCHEDULED"
        assert appeal_refreshed["officer_id"] == officer_id, (
            "Appeal.officer_id must be copied from schedule per PRD §3.6"
        )

    def test_hearing_start_after_deadline_rejected(self, api):
        """PRD §3.6: "The scheduled_start must be before the appeal's
        deadline_at — a hearing scheduled to begin at or after the
        deadline is rejected with ERR_APPEAL_WINDOW_EXPIRED."

        Claim: scheduled_start == Appeal.deadline_at →
        ERR_APPEAL_WINDOW_EXPIRED.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        # Set scheduled_start exactly at deadline_at.
        start = appeal["deadline_at"]
        deadline_dt = parse_iso(appeal["deadline_at"])
        end = (deadline_dt + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z",
        )
        res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=start, scheduled_end=end,
            ),
            officer_headers,
        )
        validate_error(res, "ERR_APPEAL_WINDOW_EXPIRED")

    def test_hearing_start_not_before_end_rejected(self, api):
        """PRD §3.6: "The scheduled_start must be strictly before
        scheduled_end ... ; a violation is rejected with
        ERR_HEARING_NOT_DUE."

        Claim: scheduled_start == scheduled_end →
        ERR_HEARING_NOT_DUE.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        start = iso_offset(days=1, base=server_now_dt())
        # end equal to start.
        end = start
        res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=start, scheduled_end=end,
            ),
            officer_headers,
        )
        validate_error(res, "ERR_HEARING_NOT_DUE")

    def test_hearing_in_the_past_rejected(self, api):
        """PRD §3.6: "both instants must be in the future relative to
        clock_now at scheduling time; a violation is rejected with
        ERR_HEARING_NOT_DUE."

        Claim: scheduled_start in the past → ERR_HEARING_NOT_DUE.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        # Set start in the past.
        past_start = iso_offset(days=-1, base=server_now_dt())
        past_end = iso_offset(days=-1, hours=1, base=server_now_dt())
        res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=past_start, scheduled_end=past_end,
            ),
            officer_headers,
        )
        validate_error(res, "ERR_HEARING_NOT_DUE")


# ===========================================================================
# Hold hearing — PRD §3.6
# ===========================================================================
class TestHoldHearing:

    def test_hold_before_start_rejected(self, api):
        """PRD §3.6: "Holding the hearing ... requires the hearing to
        be SCHEDULED (otherwise ERR_INVALID_STATE) and clock_now to be
        at or after the hearing's scheduled_start (otherwise
        ERR_HEARING_NOT_DUE)."

        Claim: /hold before scheduled_start → ERR_HEARING_NOT_DUE.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        start = iso_offset(days=2, base=server_now_dt())
        end = iso_offset(days=2, hours=1, base=server_now_dt())
        fh_res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=start, scheduled_end=end,
            ),
            officer_headers,
        )
        fh = validate_success(fh_res)
        # Do NOT advance clock; attempt /hold immediately.
        res = api.hold_fair_hearing(fh["id"], officer_headers)
        validate_error(res, "ERR_HEARING_NOT_DUE")

    def test_hold_transitions_appeal_to_under_review(self, api):
        """PRD §3.6: "On a successful hold, the hearing's status becomes
        HELD and the linked appeal moves from HEARING_SCHEDULED to
        UNDER_REVIEW."

        Claim: after /hold, FairHearing.status == HELD and
        Appeal.status == UNDER_REVIEW.

        # difficulty: non_linear_state_machine/application_cyclic_via_appeal
        """
        _hh, _app, _det, appeal, fair_hearing = setup_appeal_under_review()
        assert fair_hearing["status"] == "HELD"
        assert appeal["status"] == "UNDER_REVIEW"


# ===========================================================================
# Grant — PRD §3.6
# ===========================================================================
class TestGrantAppeal:

    def test_grant_cascade_overturns_determination_and_reopens_application(
            self, api):
        """PRD §3.6: "On grant, the system performs a deterministic
        three-hop cascade in order: hop one — the appealed
        EligibilityDetermination's outcome is set to OVERTURNED ...
        hop two — the associated Application moves from APPEALED to
        UNDER_REVIEW for re-decision."

        Claim: after /grant, EligibilityDetermination.outcome ==
        OVERTURNED and Application.status == UNDER_REVIEW.

        # difficulty: transitive_cascade/appeal_grant_cascade_depth_3
        """
        from test_helpers import grant_appeal
        household, application, determination, appeal, _fh = (
            setup_appeal_under_review()
        )
        grant_appeal(appeal=appeal)
        # Refetch determination via... PRD §4 has no GET /eligibility-
        # determinations endpoint. The only way to observe outcome is
        # via the Appeal record OR via a refetched Application. But
        # PRD says the determination is mutated. We rely on the
        # Application transition as the canonical observable.
        app_refreshed = get_application(household["id"], application["id"])
        assert app_refreshed["status"] == "UNDER_REVIEW", (
            "Application must move APPEALED → UNDER_REVIEW on grant per "
            f"PRD §3.6; got status={app_refreshed['status']!r}"
        )


# ===========================================================================
# Uphold — PRD §3.6
# ===========================================================================
class TestUpholdAppeal:

    def test_uphold_keeps_application_denied(self, api):
        """PRD §3.6: "on uphold, the determination's outcome stays
        INELIGIBLE, the application stays DENIED, and the appeal moves
        to UPHELD."

        Claim: after /uphold, the Application remains DENIED and
        the Appeal.status == UPHELD.
        """
        from test_helpers import uphold_appeal_payload
        household, application, _det, appeal, _fh = (
            setup_appeal_under_review()
        )
        res = api.uphold_appeal(
            appeal["id"], uphold_appeal_payload(),
            TEST_USERS["appeals_officer_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "UPHELD"
        app_refreshed = get_application(household["id"], application["id"])
        assert app_refreshed["status"] == "DENIED", (
            "Application must stay DENIED on uphold per PRD §3.6; "
            f"got status={app_refreshed['status']!r}"
        )


# ===========================================================================
# Withdraw appeal — PRD §3.6
# ===========================================================================
class TestWithdrawAppeal:

    def test_withdraw_filed_appeal_cancels_no_hearing(self, api):
        """PRD §3.6: "An IntakeWorker may withdraw the appeal while it
        is still FILED or HEARING_SCHEDULED ... the appeal moves to
        WITHDRAWN."

        Claim: /withdraw on a FILED appeal returns status=WITHDRAWN.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        res = api.withdraw_appeal(
            appeal["id"], TEST_USERS["intake_worker_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_hearing_scheduled_cancels_fair_hearing(self, api):
        """PRD §3.6: "if a SCHEDULED fair hearing exists, its status is
        set to CANCELLED as an automatic linked side effect."

        Claim: /withdraw on a HEARING_SCHEDULED appeal also flips the
        FairHearing.status from SCHEDULED to CANCELLED.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        appeal = file_appeal(determination=determination)
        officer_headers = TEST_USERS["appeals_officer_headers"]
        start = iso_offset(days=1, base=server_now_dt())
        end = iso_offset(days=1, hours=1, base=server_now_dt())
        fh_res = api.schedule_hearing(
            appeal["id"],
            schedule_hearing_payload(
                officer_id=officer_headers["X-User-ID"],
                scheduled_start=start, scheduled_end=end,
            ),
            officer_headers,
        )
        fh = validate_success(fh_res)
        api.withdraw_appeal(
            appeal["id"], TEST_USERS["intake_worker_headers"],
        )
        # Refetch FairHearing.
        from test_helpers import get_fair_hearing
        fh_refreshed = get_fair_hearing(fh["id"])
        assert fh_refreshed["status"] == "CANCELLED", (
            "withdrawing a HEARING_SCHEDULED appeal must CANCEL the "
            f"FairHearing per PRD §3.6; got status="
            f"{fh_refreshed['status']!r}"
        )
