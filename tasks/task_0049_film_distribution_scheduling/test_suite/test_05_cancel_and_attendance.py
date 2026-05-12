"""Showtime cancel: state preconditions, attendance-rate boundary,
distributor weekly minimum, and cascade to tickets / settlements.

Covers PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BUSINESS_DATE,
    LOW_ATTENDANCE_THRESHOLD_BPS,
    api_client,
    assert_schedule_adjustment,
    cancel_showtime,
    cancel_showtime_payload,
    create_showtime,
    fetch_showtime,
    fetch_ticket,
    list_audit_logs_for,
    list_schedule_adjustments_for,
    make_cinema_ops_headers,
    purchase_ticket,
    setup_distributor_with_weekly_minimum,
    setup_showtime_on_sale,
    validate_error,
    validate_success,
)


# =========================================================================
# Cancel state preconditions
# =========================================================================
class TestCancelStateGate:

    def test_cancel_already_cancelled_rejected(self, api):
        """PRD §3.7: 'A cancel is only admitted when lifecycle_status is
        SCHEDULED -- cancelling an IN_PROGRESS or already-CANCELLED show
        fails with ERR_INVALID_STATE.'

        Claim: cancelling a CANCELLED showtime -> ERR_INVALID_STATE.
        """
        base = setup_showtime_on_sale()
        cancelled = cancel_showtime(
            base["showtime"], base["cinema"], cancel_reason="INCIDENT",
        )
        # Second cancel attempt on the already-CANCELLED row.
        res = api.cancel_showtime(
            cancelled["id"],
            cancel_showtime_payload(
                version=cancelled["version"], cancel_reason="INCIDENT",
            ),
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# LOW_ATTENDANCE attendance-rate boundary (PRD §3.7)
# =========================================================================
class TestLowAttendanceBoundary:
    """PRD §3.7: 'The attendance rate, expressed in basis points, is
    gross_box_office_cents multiplied by 10000 and then divided by the
    maximum possible revenue using integer (floor) division; the
    resulting attendance_rate_bps must be strictly less than 1500
    (15.00 percent) for the LOW_ATTENDANCE cancellation to be admitted.
    Boundary precision matters here: a showtime whose attendance_rate_bps
    computes to exactly 1500 does not qualify, and the cancel attempt is
    rejected with ERR_INVALID_STATE.'"""

    def test_rate_exactly_1500_rejected(self, api, ticketing_headers):
        """Claim: attendance_rate_bps == 1500 (strict '<') ->
        ERR_INVALID_STATE on cancel with LOW_ATTENDANCE.
        """
        # seat_capacity=100, ticket_price_cents=100, sell exactly 15
        # -> gross=1500, max=10000, rate_bps = 15000000//10000 = 1500.
        base = setup_showtime_on_sale(
            seat_capacity=100,
            format="2D", supported_formats=["2D"],
        )
        # Override price by re-creating? simpler: just use price=100 on
        # the create. We did setup_showtime_on_sale with default
        # ticket_price_cents=1500; override here:
        from test_helpers import (
            create_cinema, create_distributor, create_film, create_screen,
            advance_clock, run_sweep, release_film, create_showtime,
        )
        distributor = create_distributor(min_show_count_per_week=0)
        cinema = create_cinema(tier="TIER_1")
        screen = create_screen(
            cinema, supported_formats=["2D"], seat_capacity=100,
            operating_start_minute=0, operating_end_minute=1440,
        )
        film = create_film(distributor, format="2D", duration_minutes=90)
        advance_clock("2026-05-04T00:00:00.000Z")
        film = release_film(film, distributor)
        showtime = create_showtime(
            screen, cinema, film,
            start_minute=720, business_date="2026-05-05T00:00:00.000Z",
            ticket_price_cents=100,
            presale_opens_at="2026-05-04T12:00:00.000Z",
        )
        advance_clock("2026-05-04T12:00:00.000Z")
        run_sweep()
        # Sell exactly 15 tickets.
        for i in range(15):
            purchase_ticket(
                showtime,
                buyer_external_id=f"b-{i}",
                paid_amount_cents=100,
            )
        # Refresh showtime to update gross.
        showtime = fetch_showtime(showtime["id"], cinema)
        # gross=1500, max=10000, rate_bps=1500 (floor).
        # Cancel with LOW_ATTENDANCE should be ERR_INVALID_STATE.
        res = api.cancel_showtime(
            showtime["id"],
            cancel_showtime_payload(
                version=showtime["version"],
                cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(cinema["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_zero_attendance_low_attendance_allowed(
        self, api, ticketing_headers,
    ):
        """PRD §3.7: 'the resulting attendance_rate_bps must be strictly
        less than 1500 (15.00 percent) for the LOW_ATTENDANCE
        cancellation to be admitted'.

        Claim: zero tickets sold -> attendance_rate_bps=0 < 1500;
        LOW_ATTENDANCE cancel succeeds.
        """
        base = setup_showtime_on_sale(
            seat_capacity=100, supported_formats=["2D"], format="2D",
            ticket_price_cents=100,
        )
        # No tickets sold; gross=0; rate=0 < 1500. Cancel allowed.
        res = api.cancel_showtime(
            base["showtime"]["id"],
            cancel_showtime_payload(
                version=base["showtime"]["version"],
                cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["lifecycle_status"] == "CANCELLED"
        assert data["cancel_reason"] == "LOW_ATTENDANCE"


# =========================================================================
# Cancel cascade (PRD §3.7)
# =========================================================================
class TestCancelCascade:
    """PRD §3.7: 'The cascade on a successful cancel fires in this order.
    The showtime's lifecycle_status becomes CANCELLED, its sale_status
    becomes CLOSED, and its cancel_reason is stored. Every VALID Ticket
    on the showtime has its status set to REFUNDED ... and refunded_at
    set to the current clock ... One ScheduleAdjustment row is archived
    with adjustment_type CANCEL, reason matching the supplied
    cancel_reason ... An AuditLog row with action SHOWTIME_CANCEL
    finalizes the operation.'"""

    def test_cancel_refunds_valid_tickets(self, api):
        """Claim: after cancel, every VALID ticket transitions to REFUNDED.
        """
        base = setup_showtime_on_sale(seat_capacity=10)
        ticket_ids = []
        for i in range(3):
            t = purchase_ticket(
                base["showtime"],
                buyer_external_id=f"b-{i}", paid_amount_cents=1500,
            )
            ticket_ids.append(t["id"])
        cancel_showtime(
            base["showtime"], base["cinema"], cancel_reason="INCIDENT",
        )
        for tid in ticket_ids:
            t = fetch_ticket(tid)
            assert t["status"] == "REFUNDED", (
                "PRD §3.7: every VALID Ticket on the showtime has its "
                "status set to REFUNDED"
            )

    def test_cancel_archives_schedule_adjustment(self, api):
        """PRD §3.7: 'One ScheduleAdjustment row is archived with
        adjustment_type CANCEL, reason matching the supplied
        cancel_reason'.

        Claim: ScheduleAdjustment for the cancelled showtime has
        adjustment_type='CANCEL' and reason matching the request.
        """
        base = setup_showtime_on_sale(seat_capacity=10)
        cancel_showtime(
            base["showtime"], base["cinema"], cancel_reason="INCIDENT",
        )
        adjustments = list_schedule_adjustments_for(base["showtime"]["id"])
        cancels = [a for a in adjustments if a["adjustment_type"] == "CANCEL"]
        assert len(cancels) == 1
        assert_schedule_adjustment(cancels[0])
        assert cancels[0]["reason"] == "INCIDENT"

    def test_cancel_emits_audit_log(self, api):
        """PRD §3.7: 'An AuditLog row with action SHOWTIME_CANCEL
        finalizes the operation.'

        Claim: AuditLog has a SHOWTIME_CANCEL row for the cancelled
        showtime.id.
        """
        base = setup_showtime_on_sale(seat_capacity=10)
        cancel_showtime(
            base["showtime"], base["cinema"], cancel_reason="INCIDENT",
        )
        entries = list_audit_logs_for(
            base["showtime"]["id"], action="SHOWTIME_CANCEL",
        )
        assert len(entries) >= 1


# =========================================================================
# Distributor weekly minimum (PRD §3.7)
# =========================================================================
class TestMinShowCountBreach:
    """PRD §3.7: 'If that count would fall strictly below the
    distributor's min_show_count_per_week after the cancel, the cancel
    is rejected with ERR_MIN_SHOW_COUNT_BREACH -- unless cancel_reason
    is INCIDENT, which acts as a force-majeure override that bypasses
    this check.'"""

    def test_low_attendance_cancel_breaches_minimum(self, api):
        """Claim: with min_show_count_per_week=3 and exactly 3 SCHEDULED
        showtimes, a LOW_ATTENDANCE cancel that would drop the count to
        2 is rejected with ERR_MIN_SHOW_COUNT_BREACH.
        """
        # 3 showtimes spaced wide apart to avoid screen/peak conflicts.
        scenario = setup_distributor_with_weekly_minimum(
            min_show_count_per_week=3,
            showtime_count=3,
            start_minute_first=400,  # outside peak (peak starts 1080)
            start_minute_gap=200,
        )
        # No tickets sold -> attendance_rate_bps=0 so LOW_ATTENDANCE
        # would otherwise pass. The weekly-minimum check should fire.
        st = scenario["showtimes"][0]
        res = api.cancel_showtime(
            st["id"],
            cancel_showtime_payload(
                version=st["version"], cancel_reason="LOW_ATTENDANCE",
            ),
            make_cinema_ops_headers(scenario["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MIN_SHOW_COUNT_BREACH.value)

    def test_incident_bypasses_weekly_minimum(self, api):
        """PRD §3.7: 'unless cancel_reason is INCIDENT, which acts as a
        force-majeure override that bypasses this check.'

        Claim: INCIDENT cancel proceeds even when it would drop count
        below min_show_count_per_week.
        """
        scenario = setup_distributor_with_weekly_minimum(
            min_show_count_per_week=3,
            showtime_count=3,
            start_minute_first=400,
            start_minute_gap=200,
        )
        st = scenario["showtimes"][0]
        res = api.cancel_showtime(
            st["id"],
            cancel_showtime_payload(
                version=st["version"], cancel_reason="INCIDENT",
            ),
            make_cinema_ops_headers(scenario["cinema"]["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["lifecycle_status"] == "CANCELLED"
        assert data["cancel_reason"] == "INCIDENT"
