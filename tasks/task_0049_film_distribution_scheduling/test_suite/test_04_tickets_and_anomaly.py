"""Ticket purchase: presale gating, ON_SALE auto-transition, seat
capacity, per-buyer cap, and pre-sale anomaly detection.

Covers PRD §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CUMULATIVE_THRESHOLD,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_PRESALE_OPENS_AT,
    DEFAULT_RELEASE_DATE,
    PER_BUYER_HARD_CAP,
    ROLLING_WINDOW_THRESHOLD,
    advance_clock,
    api_client,
    assert_ticket,
    assert_anomaly_alert,
    create_ticket_payload,
    fetch_showtime,
    list_anomaly_alerts_for,
    purchase_ticket,
    setup_showtime_on_sale,
    validate_error,
    validate_success,
)


# =========================================================================
# Presale gating
# =========================================================================
class TestPresaleGating:

    def test_purchase_before_presale_opens(self, api, ticketing_headers):
        """PRD §3.5: 'A purchase attempt arriving before
        presale_opens_at is rejected with ERR_PRESALE_NOT_OPEN.'

        Claim: ticket purchase before presale_opens_at ->
        ERR_PRESALE_NOT_OPEN.
        """
        base = setup_showtime_on_sale(
            presale_opens_at="2099-01-01T00:00:00.000Z",
            sweep_to_on_sale=False,
        )
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(buyer_external_id="b1"),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRESALE_NOT_OPEN.value)

    def test_purchase_when_film_not_released(self, api, ticketing_headers):
        """PRD §3.5: 'If the film is not yet RELEASED when the clock
        crosses presale_opens_at, the transition is suppressed and any
        ticket purchase attempt fails with ERR_FILM_NOT_RELEASED.'

        Claim: ticket purchase while parent Film.status == PLANNED ->
        ERR_FILM_NOT_RELEASED.
        """
        # Build org with PLANNED film, advance clock past presale_opens.
        from test_helpers import (
            create_cinema, create_distributor, create_film, create_screen,
            create_showtime,
        )
        distributor = create_distributor()
        cinema = create_cinema()
        screen = create_screen(
            cinema, supported_formats=["2D"],
            operating_start_minute=0, operating_end_minute=1440,
            seat_capacity=10,
        )
        film = create_film(
            distributor,
            release_date="2099-01-01T00:00:00.000Z",  # planned far future
        )
        showtime = create_showtime(
            screen, cinema, film,
            start_minute=720, business_date=DEFAULT_BUSINESS_DATE,
            ticket_price_cents=1500,
            presale_opens_at=DEFAULT_PRESALE_OPENS_AT,
        )
        # Advance the clock past presale_opens_at so PRESALE_NOT_OPEN doesn't fire.
        advance_clock(DEFAULT_PRESALE_OPENS_AT)
        res = api.purchase_ticket(
            showtime["id"],
            create_ticket_payload(buyer_external_id="b1"),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_FILM_NOT_RELEASED.value)


# =========================================================================
# Seat capacity (PRD §3.5)
# =========================================================================
class TestSeatCapacity:
    """PRD §3.5: 'the total count of VALID tickets on the showtime must
    not equal the screen's seat_capacity at the moment of insert --
    strictly inclusive on the boundary so the (seat_capacity)-th sale
    succeeds and the (seat_capacity + 1)-th sale is rejected with
    ERR_SEAT_CAPACITY_EXCEEDED.'"""

    def test_seat_capacity_boundary(self, api, ticketing_headers):
        """Claim: seat_capacity=2 -> first 2 purchases succeed, 3rd
        rejected with ERR_SEAT_CAPACITY_EXCEEDED.
        """
        base = setup_showtime_on_sale(
            seat_capacity=2, format="2D",
            supported_formats=["2D"],
        )
        # First two succeed.
        for i in range(2):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id=f"buyer-{i}",
                    paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
        # Third rejected.
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="buyer-3", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value)


# =========================================================================
# Per-buyer hard cap (PRD §3.5)
# =========================================================================
class TestPerBuyerHardCap:
    """PRD §3.5: 'the count of VALID tickets for the same showtime_id
    and same buyer_external_id must remain strictly less than the
    per-buyer hard cap of 20 tickets -- the 20th sale to a single buyer
    is admitted, the 21st is rejected with ERR_PER_BUYER_LIMIT_EXCEEDED.'

    The cap of 20 is high; the anomaly safety check at priority 8 fires
    first on counts >= 10 in 60 minutes. To exercise the fiscal cap
    alone, we space purchases >60 minutes apart so rolling-window <10
    AND cumulative <30."""

    def test_per_buyer_limit_at_21st(self, api, ticketing_headers):
        """Claim: 21st purchase by the same buyer rejected with
        ERR_PER_BUYER_LIMIT_EXCEEDED when no anomaly rule has tripped.

        We space purchases far apart so neither anomaly rule fires
        (rolling_window<10 at any moment; cumulative<30).
        """
        base = setup_showtime_on_sale(
            seat_capacity=100,
            format="2D", supported_formats=["2D"],
            presale_opens_at=DEFAULT_PRESALE_OPENS_AT,
        )
        # Sell 20 tickets spaced 70 minutes apart so rolling-window count
        # stays at 1; cumulative stays at 1..20. We do this by stepping
        # the clock forward each purchase.
        from datetime import datetime, timedelta, timezone
        t = datetime.fromisoformat(
            DEFAULT_PRESALE_OPENS_AT.replace("Z", "+00:00"),
        )
        for i in range(PER_BUYER_HARD_CAP):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id="buyer-X",
                    paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
            t = t + timedelta(minutes=70)
            advance_clock(
                t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            )
        # 21st should be rejected.
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="buyer-X", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_PER_BUYER_LIMIT_EXCEEDED.value)


# =========================================================================
# Pre-sale anomaly detection (PRD §3.5)
# =========================================================================
class TestPresaleAnomalyDetection:
    """PRD §3.5: 'The rolling-window rule counts the number of such
    tickets whose purchased_at lies within the last 60 minutes inclusive
    of the current server clock; if this count would reach 10 or more
    with the proposed ticket included, the rule trips with rule
    ROLLING_WINDOW. The cumulative rule counts the total number of such
    tickets without any time bound; if this count would reach 30 or
    more with the proposed ticket included, the rule trips with rule
    CUMULATIVE. When either rule trips, the proposed ticket is not
    persisted (no Ticket row is written, tickets_sold_count is not
    incremented, and gross_box_office_cents is unchanged), an
    AnomalyAlert is appended with the showtime_id, buyer_external_id,
    the rule that fired, and the triggering_count that breached the
    threshold, and the response is ERR_PRESALE_ANOMALY_DETECTED.'"""

    def test_rolling_window_trips_at_tenth(self, api, ticketing_headers):
        """Claim: the 10th VALID ticket within 60 minutes for the same
        buyer is rejected with ERR_PRESALE_ANOMALY_DETECTED and an
        AnomalyAlert with rule='ROLLING_WINDOW' is appended.
        """
        base = setup_showtime_on_sale(
            seat_capacity=100,
            format="2D", supported_formats=["2D"],
        )
        # Sell 9 tickets in quick succession.
        for i in range(ROLLING_WINDOW_THRESHOLD - 1):
            res = api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id="b1", paid_amount_cents=1500,
                ),
                ticketing_headers,
            )
            validate_success(res, expected_status=201)
        # 10th trips ROLLING_WINDOW.
        res = api.purchase_ticket(
            base["showtime"]["id"],
            create_ticket_payload(
                buyer_external_id="b1", paid_amount_cents=1500,
            ),
            ticketing_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRESALE_ANOMALY_DETECTED.value)
        # Showtime ticket count remains 9 (PRD §3.5: 'no Ticket row is
        # written, tickets_sold_count is not incremented').
        showtime = fetch_showtime(
            base["showtime"]["id"], base["cinema"],
        )
        assert showtime["tickets_sold_count"] == ROLLING_WINDOW_THRESHOLD - 1
        # AnomalyAlert row with rule=ROLLING_WINDOW.
        alerts = list_anomaly_alerts_for(
            base["showtime"]["id"], buyer_external_id="b1",
        )
        rolling = [a for a in alerts if a["rule"] == "ROLLING_WINDOW"]
        assert len(rolling) >= 1, (
            "PRD §3.5: AnomalyAlert with rule ROLLING_WINDOW must be appended"
        )
        assert rolling[-1]["triggering_count"] >= ROLLING_WINDOW_THRESHOLD

    # test_cumulative_trips_at_thirtieth DELETED.
    # STEP 1b unique-derivability collapse: PRD §3.5 scopes the
    # cumulative rule's input domain to "the same showtime_id and same
    # buyer_external_id"; the per-buyer hard cap of 20 (PRD §3.5)
    # rejects the 21st purchase to that buyer with
    # ERR_PER_BUYER_LIMIT_EXCEEDED. A faithful PRD implementer therefore
    # CANNOT let a single buyer reach 30 same-showtime same-buyer
    # VALID tickets, so the CUMULATIVE threshold is unreachable in the
    # only setup the test allows. Scaffold-driven over-coverage of the
    # threshold-at-thirtieth rule.


# =========================================================================
# Gross box-office aggregate (PRD §3.5)
# =========================================================================
class TestGrossBoxOfficeAggregate:

    def test_tickets_sold_count_and_gross_after_purchase(
        self, api, ticketing_headers,
    ):
        """PRD §3.5: 'tickets_sold_count is the count of tickets on this
        showtime whose status is VALID ... and gross_box_office_cents is
        the sum of paid_amount_cents over the tickets whose status is
        VALID.'

        Claim: after N successful purchases the aggregates equal N and
        Σ paid_amount_cents.
        """
        base = setup_showtime_on_sale(seat_capacity=10)
        amounts = [1200, 1500, 800]
        for i, amt in enumerate(amounts):
            purchase_ticket(
                base["showtime"],
                buyer_external_id=f"buyer-{i}",
                paid_amount_cents=amt,
            )
        showtime = fetch_showtime(
            base["showtime"]["id"], base["cinema"],
        )
        assert showtime["tickets_sold_count"] == len(amounts)
        assert showtime["gross_box_office_cents"] == sum(amounts)
