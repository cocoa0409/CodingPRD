"""Optimistic concurrency, version conflict, duplicate-operation
idempotency, and clock-regress.

Covers PRD §2.6, §2.9, §2.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    fetch_film,
    make_distributor_ops_headers,
    run_race,
    setup_posted_settlement,
    setup_released_film,
    setup_showtime_on_sale,
    shelve_payload,
    validate_error,
    validate_success,
    version_payload,
)


# =========================================================================
# Optimistic concurrency: version conflict
# =========================================================================
class TestVersionConflict:

    def test_release_with_stale_version_rejected(self, api):
        """PRD §2.6: 'If version is supplied and does not match the
        current version on the target row, the request is rejected with
        ERR_VERSION_CONFLICT (409)'.

        Claim: release request body with stale `version` ->
        ERR_VERSION_CONFLICT.
        """
        from test_helpers import (
            create_distributor, create_film, advance_clock,
            DEFAULT_RELEASE_DATE,
        )
        distributor = create_distributor()
        film = create_film(distributor)
        advance_clock(DEFAULT_RELEASE_DATE)
        stale_version = film["version"] + 100
        res = api.release_film(
            film["id"], version_payload(stale_version),
            make_distributor_ops_headers(distributor["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


# =========================================================================
# Duplicate-operation idempotency (PRD §2.6)
# =========================================================================
class TestDuplicateOperation:

    def test_repeated_shelve_with_stale_version_rejected(self, api):
        """PRD §2.6: 'Repeating the same action twice with the same
        version against a target whose version has already advanced past
        it (because the first call succeeded) is rejected with
        ERR_DUPLICATE_OPERATION (409)'.

        Claim: shelve, then a second shelve attempt with the same
        original `version` -> ERR_DUPLICATE_OPERATION.
        """
        base = setup_showtime_on_sale()
        original_version = base["film"]["version"]
        # First shelve succeeds.
        from test_helpers import shelve_film
        shelve_film(
            base["film"], base["distributor"], reason="first_shelve",
        )
        # Second attempt with the SAME original version.
        res = api.shelve_film(
            base["film"]["id"],
            shelve_payload(version=original_version, reason="second_attempt"),
            make_distributor_ops_headers(base["distributor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_OPERATION.value)


# =========================================================================
# Race: two purchases for the last seat (PRD §3.5)
# =========================================================================
class TestSeatRace:

    def test_two_purchases_for_last_seat(self, api, ticketing_headers):
        """PRD §3.5: 'Two simultaneous purchases racing for the last seat
        serialize first-writer-wins on the tickets_sold_count increment
        and the loser receives ERR_SEAT_CAPACITY_EXCEEDED.'

        Claim: exactly one of two concurrent purchases on a one-seat
        showtime succeeds; the other fails.
        """
        from test_helpers import create_ticket_payload
        base = setup_showtime_on_sale(
            seat_capacity=1, supported_formats=["2D"], format="2D",
        )

        def buy(idx):
            return api.purchase_ticket(
                base["showtime"]["id"],
                create_ticket_payload(
                    buyer_external_id=f"race-{idx}",
                    paid_amount_cents=1500,
                ),
                ticketing_headers,
            )

        results = run_race(lambda: buy(0), lambda: buy(1))
        assert_exactly_one_succeeds(results[0], results[1])


# =========================================================================
# Clock advance (PRD §2.10)
# =========================================================================
class TestClockAdvance:

    def test_clock_regress_rejected(self, api, admin_headers):
        """PRD §2.10: 'An attempt to set the clock to an instant at or
        before the current clock fails with ERR_CLOCK_REGRESS (422).'

        Claim: POST /_clock/advance with a timestamp at or before the
        current clock -> ERR_CLOCK_REGRESS.
        """
        from test_helpers import clock_advance_payload, advance_clock
        # First, advance to a known instant.
        anchor = "2026-06-01T00:00:00.000Z"
        advance_clock(anchor)
        # Attempt to regress to the same instant.
        res = api.advance_clock(
            clock_advance_payload(anchor), admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_CLOCK_REGRESS.value)
