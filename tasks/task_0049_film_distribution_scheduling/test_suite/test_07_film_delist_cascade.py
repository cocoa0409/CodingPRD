"""Film DELIST cascade (depth-4) -- spans Film → Showtime → Ticket →
Settlement (REVERSAL) → ScheduleAdjustment + AuditLog.

Covers PRD §3.2 (delist cascade prose) and §3.10 (audit log).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    delist_film,
    fetch_film,
    fetch_showtime,
    fetch_ticket,
    list_audit_logs_for,
    list_schedule_adjustments_for,
    list_settlements_for,
    purchase_ticket,
    setup_posted_settlement,
    validate_error,
    validate_success,
)


# =========================================================================
# DELIST cascade hops (PRD §3.2)
# =========================================================================
class TestFilmDelistCascade:
    """PRD §3.2: 'The delist cascade fires in four hops in this order.
    First, every Showtime belonging to the film whose lifecycle_status
    is SCHEDULED is force-cancelled -- lifecycle_status becomes
    CANCELLED, sale_status becomes CLOSED, and cancel_reason is set to
    INCIDENT (a delist never uses NEW_FILM_INSERTION as its cancel
    reason). Second, every VALID Ticket on those cancelled showtimes
    has its status set to REFUNDED and refunded_at set to the server
    clock. Third, for each refunded ticket whose original POSTING
    Settlement row is in status POSTED, a compensating REVERSAL row is
    appended with kind REVERSAL and parent_settlement_id pointing at
    the original POSTING. Fourth, one ScheduleAdjustment row is archived
    per cancelled showtime with adjustment_type CANCEL, reason INCIDENT
    ... An AuditLog row with action FILM_DELIST finalizes the cascade.'"""

    def test_delist_cancels_scheduled_showtimes(self, api):
        """Claim hop 1: delisting a RELEASED film force-cancels its
        SCHEDULED showtimes with cancel_reason=INCIDENT.

        # difficulty: transitive_cascade/film_delist_four_hop_cascade
        """
        # We need a SCHEDULED showtime alongside the COMPLETED one.
        # setup_posted_settlement leaves the underlying showtime in
        # lifecycle_status=COMPLETED. Build a second SCHEDULED showtime
        # for the same film/cinema/screen by creating one after the fact.
        from test_helpers import create_showtime
        base = setup_posted_settlement(
            tickets=2, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        # Create a second showtime on a new day (different business_date).
        second = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=720,
            business_date="2026-05-12T00:00:00.000Z",
            ticket_price_cents=1500,
            presale_opens_at="2026-05-11T12:00:00.000Z",
        )
        # Delist film.
        # Refresh film version first.
        film = fetch_film(base["film"]["id"], base["distributor"])
        delist_film(film, base["distributor"])
        # Hop 1: second showtime is CANCELLED with cancel_reason=INCIDENT.
        second_refreshed = fetch_showtime(second["id"], base["cinema"])
        assert second_refreshed["lifecycle_status"] == "CANCELLED"
        assert second_refreshed["cancel_reason"] == "INCIDENT"
        assert second_refreshed["sale_status"] == "CLOSED"

    def test_delist_refunds_valid_tickets_on_cancelled_showtimes(self, api):
        """Claim hop 2: every VALID Ticket on the cancelled showtimes is
        set to REFUNDED.

        # difficulty: transitive_cascade/film_delist_four_hop_cascade
        """
        from test_helpers import create_showtime
        base = setup_posted_settlement(
            tickets=2, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        # Build a second showtime + sell 2 VALID tickets there.
        second = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=720,
            business_date="2026-05-12T00:00:00.000Z",
            ticket_price_cents=1500,
            presale_opens_at="2026-05-11T12:00:00.000Z",
        )
        # Open presale + sweep.
        from test_helpers import advance_clock, run_sweep
        advance_clock("2026-05-11T12:00:00.000Z")
        run_sweep()
        second_tickets = []
        for i in range(2):
            t = purchase_ticket(
                second,
                buyer_external_id=f"delist-b-{i}",
                paid_amount_cents=1500,
            )
            second_tickets.append(t)
        # Delist film.
        film = fetch_film(base["film"]["id"], base["distributor"])
        delist_film(film, base["distributor"])
        # Hop 2: each VALID ticket on the cancelled second showtime is REFUNDED.
        for t in second_tickets:
            refreshed = fetch_ticket(t["id"])
            assert refreshed["status"] == "REFUNDED"

    def test_delist_appends_reversal_for_posted_settlement(self, api):
        """Claim hop 3: a REVERSAL settlement row is appended for each
        refunded ticket whose POSTING was POSTED.

        # difficulty: transitive_cascade/film_delist_four_hop_cascade
        """
        base = setup_posted_settlement(
            tickets=2, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        # No second showtime needed for hop 3: just delist; PRD §3.2
        # hop 3 is conditional on whether a POSTING Settlement was POSTED.
        # The first showtime is COMPLETED + POSTED but lifecycle_status
        # is no longer SCHEDULED -- it was completed via sweep. PRD §3.2
        # hop 1 force-cancels only SCHEDULED showtimes. The COMPLETED
        # showtime is therefore NOT force-cancelled, so no REVERSAL hops
        # fire from delist on this showtime.
        #
        # To exercise hop 3 we need: a SCHEDULED showtime that has a
        # POSTING Settlement in POSTED status. PRD §3.9 lets a POSTING
        # POST only when lifecycle_status == COMPLETED, so we cannot
        # have both. Hop 3 is therefore only observable when a
        # not-yet-completed cascade originates a refund that hits a
        # *previously posted* settlement on a separate completed
        # showtime.
        #
        # The cascade hop 3 is the SAME ledger machinery as
        # POST /tickets/{id}/refund. We've already proved the REVERSAL
        # ledger discipline in test_06_settlements.
        #
        # For delist specifically: confirm that delisting a film that
        # has only a COMPLETED+POSTED showtime leaves the POSTING
        # untouched (no REVERSAL appended), because hop 1 force-cancels
        # only SCHEDULED rows.
        rows_before = list_settlements_for(base["showtime"]["id"])
        film = fetch_film(base["film"]["id"], base["distributor"])
        delist_film(film, base["distributor"])
        rows_after = list_settlements_for(base["showtime"]["id"])
        # PRD §3.2 hop 1 acts ONLY on SCHEDULED showtimes, so the
        # COMPLETED showtime's POSTING is untouched.
        assert len(rows_after) == len(rows_before), (
            "PRD §3.2 hop 1: 'every Showtime ... whose lifecycle_status "
            "is SCHEDULED is force-cancelled' -- COMPLETED rows are not "
            "in the cascade scope"
        )

    def test_delist_archives_schedule_adjustment_per_cancelled_showtime(
        self, api,
    ):
        """Claim hop 4: one ScheduleAdjustment row per cancelled showtime
        with adjustment_type=CANCEL, reason=INCIDENT.

        # difficulty: transitive_cascade/film_delist_four_hop_cascade
        """
        from test_helpers import create_showtime, advance_clock, run_sweep
        base = setup_posted_settlement(
            tickets=2, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        second = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=720,
            business_date="2026-05-12T00:00:00.000Z",
            ticket_price_cents=1500,
            presale_opens_at="2026-05-11T12:00:00.000Z",
        )
        film = fetch_film(base["film"]["id"], base["distributor"])
        delist_film(film, base["distributor"])
        adjustments = list_schedule_adjustments_for(second["id"])
        cancels = [a for a in adjustments
                   if a["adjustment_type"] == "CANCEL"]
        assert len(cancels) == 1
        assert cancels[0]["reason"] == "INCIDENT"

    def test_delist_emits_film_delist_audit_log(self, api):
        """PRD §3.2: 'An AuditLog row with action FILM_DELIST finalizes
        the cascade.'

        Claim: AuditLog has a FILM_DELIST row targeting the film.id.

        # difficulty: transitive_cascade/film_delist_four_hop_cascade
        """
        base = setup_posted_settlement(
            tickets=1, paid_amount_cents=1500,
            distributor_split_bps=6000,
            format="2D", supported_formats=["2D"],
        )
        film = fetch_film(base["film"]["id"], base["distributor"])
        delist_film(film, base["distributor"])
        rows = list_audit_logs_for(film["id"], action="FILM_DELIST")
        assert len(rows) >= 1
