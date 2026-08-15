"""Delinquency sweeps, notice lifecycle, and the half-open cure window."""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    CLERK,
    ApiErrorId,
    drive_member_delinquent,
    get_member,
    get_success_data,
    list_member_notices,
    make_local,
    make_member,
    make_classification,
    make_payment,
    run_period,
    send_notice,
    set_clock,
    setup_flat_local_with_journeyman,
    sweep_delinquency,
    validate_error,
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestDelinquencyThresholdBoundary:
    """The arrears threshold comparison is inclusive: at the threshold the
    member flips DELINQUENT; one cent below it they stay ACTIVE."""

    def test_arrears_at_threshold_flip_delinquent(self, api):
        """PRD section on delinquency: "A member is **over** when their
        `arrears_cents` is at or above `delinquency_threshold_cents` — the
        boundary is inclusive." Two 5000 charges against a 10000 threshold sit
        exactly on the boundary.

        Design: Difficulty/boundary_precision_check/delinquency_threshold_inclusive_boundary
        """
        local, cls = setup_flat_local_with_journeyman(flat=5000, local_name="Local A")
        member = make_member(local["id"], cls["id"], full_name="Edge Ed", member_number="A-001")
        drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06"))
        after = get_member(member["id"])
        assert after["arrears_cents"] == 10000, "exactly at the threshold"
        assert after["status"] == "DELINQUENT", "the >= boundary includes the threshold"

    def test_arrears_one_below_threshold_stay_active(self, api):
        """PRD section on delinquency: "A member is **over** when their
        `arrears_cents` is at or above `delinquency_threshold_cents` — the
        boundary is inclusive." Three 3333 charges total 9999, one cent below,
        so the sweep leaves the member ACTIVE.

        Design: Difficulty/boundary_precision_check/delinquency_threshold_inclusive_boundary
        """
        local, cls = setup_flat_local_with_journeyman(flat=3333, local_name="Local B")
        member = make_member(local["id"], cls["id"], full_name="Below Beth", member_number="B-001")
        drive_member_delinquent(
            local["id"], member["id"], ("2026-05", "2026-06", "2026-07")
        )
        after = get_member(member["id"])
        assert after["arrears_cents"] == 9999, "one cent below the threshold"
        assert after["status"] == "ACTIVE", "no flip below the threshold"


class TestDelinquencyCycleLoop:
    """The member lifecycle re-enters DELINQUENT after a cure: ACTIVE ->
    DELINQUENT -> ACTIVE -> DELINQUENT again on a later sweep."""

    def _setup_cycle(self, api):
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Cy Clark", member_number="M-001")
        first = drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06"))
        return local, member, first

    def test_first_leg_delinquent_then_payment_cures(self, api):
        """PRD section on delinquency: "An `ACTIVE` member who is both aged and
        over transitions to `DELINQUENT`", and "Whenever any credit posting —
        a direct payment, a reinstatement, a remittance post, an objector
        rebate — drops a `DELINQUENT` member's arrears below the threshold,
        the member auto-cures to `ACTIVE` in the same request: every `SENT`
        notice for the member moves to `CURED`, every `DRAFT` notice is
        deleted".

        Design: Difficulty/non_linear_state_machine/member_delinquency_cycle_loop
        """
        local, member, first = self._setup_cycle(api)
        assert first["status"] == "DELINQUENT" and first["arrears_cents"] == 10000
        make_payment(member["id"], 10000)
        cured = get_member(member["id"])
        assert cured["status"] == "ACTIVE" and cured["arrears_cents"] == 0
        notices = list_member_notices(member["id"])
        assert notices == [], "the auto-cure deleted the DRAFT notice"

    def test_cycle_reentry_on_later_sweep(self, api):
        """PRD section on delinquency: "An `ACTIVE` member who is both aged and
        over transitions to `DELINQUENT`, and the sweep creates a `DRAFT`
        `DelinquencyNotice` capturing an `arrears_at_notice_cents` snapshot".
        After curing and accumulating three further 5000 charges, the member
        is aged and over again at a later sweep.

        Design: Difficulty/non_linear_state_machine/member_delinquency_cycle_loop
        """
        local, member, first = self._setup_cycle(api)
        make_payment(member["id"], 10000)
        run_period(local["id"], "2026-08")
        run_period(local["id"], "2026-09")
        run_period(local["id"], "2026-10")
        set_clock("2026-12-01T00:00:00Z")
        sweep_delinquency(local["id"])
        third = get_member(member["id"])
        assert third["status"] == "DELINQUENT", "the cycle re-entered DELINQUENT"
        assert third["arrears_cents"] == 15000, "2026-08..2026-10 charges unpaid"


class TestNoticeHalfOpenWindow:
    """The cure window is half-open [sent_at, cure_deadline): a send inside
    the window is refused; a send at exactly the deadline is accepted."""

    def _setup_two_notices(self, api):
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Nina Notice", member_number="M-001")
        drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06"))
        n1 = list_member_notices(member["id"])[0]
        send_notice(member["id"], n1["id"])  # window [08-01, 08-11)
        set_clock("2026-08-02T00:00:00Z")
        resp = api.create_notice(member["id"], CLERK)
        n2 = get_success_data(resp)
        return local, member, n1, n2

    def test_send_inside_open_window_rejected(self, api):
        """PRD section on notices: "The cure window is the half-open interval
        from `sent_at` up to but not including `cure_deadline`, and sending is
        refused with `ERR_NOTICE_WINDOW_OPEN` while another `SENT` notice's
        window still contains the current clock time."

        Design: Difficulty/resource_temporal_overlap/notice_halfopen_window_boundary
        """
        _, member, _, n2 = self._setup_two_notices(api)
        set_clock("2026-08-06T00:00:00Z")
        resp = api.send_notice(member["id"], n2["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_OPEN)

    def test_send_at_exact_deadline_accepted(self, api):
        """PRD section on notices: "The cure window is the half-open interval
        from `sent_at` up to but not including `cure_deadline`", and sending
        "computes `cure_deadline` as `notice_cure_days` days after `sent_at`".
        At exactly the first window's deadline the endpoint is exclusive, so
        the second send succeeds and opens its own 10-day window.

        Design: Difficulty/resource_temporal_overlap/notice_halfopen_window_boundary
        """
        _, member, _, n2 = self._setup_two_notices(api)
        set_clock("2026-08-11T00:00:00Z")
        resp = api.send_notice(member["id"], n2["id"], CLERK)
        sent = get_success_data(resp)
        assert sent["status"] == "SENT"
        assert _parse(sent["cure_deadline"]) == _parse(sent["sent_at"]) + timedelta(days=10)
        assert _parse(sent["cure_deadline"]) == _parse("2026-08-21T00:00:00Z")


class TestNoticeSendTwice:
    def test_notice_send_twice_rejected(self, api):
        """PRD section on notices: "Sending a draft — which requires it to
        still be `DRAFT` (`ERR_NOTICE_STATE_FORBIDDEN`)". Re-sending an
        already SENT notice fails the state guard.

        Design: Corner/state_machines/notice_send_twice_rejected
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Twice Tina", member_number="M-001")
        drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06"))
        notice = list_member_notices(member["id"])[0]
        send_notice(member["id"], notice["id"])
        resp = api.send_notice(member["id"], notice["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_NOTICE_STATE_FORBIDDEN)
