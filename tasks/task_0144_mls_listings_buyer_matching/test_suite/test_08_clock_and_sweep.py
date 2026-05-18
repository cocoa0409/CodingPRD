"""Clock advance, sweep, 180-day listing expiration, offer/counter
auto-expiration, NO_SHOW.

Cites PRD §2.9, §3.5, §3.6, §3.7, §3.9.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    accept_offer,
    advance_clock,
    advance_clock_and_sweep,
    api_client,
    create_listing,
    create_listing_agent,
    days_from_now_iso,
    get_listing_state,
    get_offer_state,
    iso_at,
    iso_in_future,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    run_sweep,
    setup_listing_and_buyer,
    setup_listing_under_contract,
    setup_offer_with_open_counter,
    setup_scheduled_showing,
    submit_offer,
    validate_error,
    validate_success,
)


class TestListing180DayExpiry:
    """PRD §3.2 + PRD §3.9 180-day listing expiration."""

    def test_listing_still_active_just_before_180_days(self, api):
        """PRD §3.2: 'If a listing remains in ACTIVE status at the
        moment the logical clock advances to or past 180 days after its
        created_at, the next sweep auto-transitions it from ACTIVE to
        EXPIRED'.

        Claim: At T0 + 179d23h59m59s, the listing is still ACTIVE.

        # difficulty: resource_temporal_overlap/listing_expiry_180_day_window_aggregate_capacity
        """
        la = create_listing_agent()
        listing = create_listing(la)
        # Advance to just-under 180 days.
        from datetime import datetime, timedelta, timezone
        created = datetime.fromisoformat(
            listing["created_at"].replace("Z", "+00:00"),
        )
        target = created + timedelta(
            days=179, hours=23, minutes=59, seconds=59,
        )
        advance_clock_and_sweep(iso_at(target))
        listing_after = get_listing_state(listing["id"])
        assert listing_after["status"] == "ACTIVE", (
            "PRD §3.2 inclusive >= 180d boundary not yet entered"
        )

    def test_listing_expires_at_180_day_boundary(self, api):
        """PRD §3.2: 'If a listing remains in ACTIVE status at the
        moment the logical clock advances to or past 180 days after
        its created_at, the next sweep auto-transitions it from
        ACTIVE to EXPIRED'.

        Claim: At T0 + exactly 180 days, sweep transitions listing to
        EXPIRED.

        # difficulty: resource_temporal_overlap/listing_expiry_180_day_window_aggregate_capacity
        """
        la = create_listing_agent()
        listing = create_listing(la)
        from datetime import datetime, timedelta, timezone
        created = datetime.fromisoformat(
            listing["created_at"].replace("Z", "+00:00"),
        )
        target = created + timedelta(days=180)
        advance_clock_and_sweep(iso_at(target))
        listing_after = get_listing_state(listing["id"])
        assert listing_after["status"] == "EXPIRED", (
            f"PRD §3.2 closed-from-below boundary at 180d should EXPIRE; "
            f"got {listing_after['status']!r}"
        )


class TestOfferExpiryByClock:
    """PRD §3.6 SUBMITTED → EXPIRED by sweep."""

    def test_submitted_offer_auto_expires(self, api):
        """PRD §3.6: 'An offer that is still SUBMITTED at the moment
        the logical clock reaches its expires_at is auto-transitioned
        to EXPIRED by the sweep'.

        Claim: After clock advance past expires_at + sweep, the offer
        is EXPIRED.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        offer = submit_offer(
            listing, buyer, ba,
            expires_at=iso_in_future(60),
            offset_seconds=60,
        )
        # Advance clock past expires_at.
        advance_clock_and_sweep(iso_in_future(3600))
        offer_after = get_offer_state(listing["id"], offer["id"])
        assert offer_after["status"] == "EXPIRED"


class TestCounterExpiryByClock:
    """PRD §3.6 OPEN Counter → EXPIRED by sweep."""

    def test_open_counter_auto_expires(self, api):
        """PRD §3.6: 'A counter that reaches its counter_expires_at
        while still OPEN is auto-transitioned to EXPIRED by the sweep.'

        Claim: After clock past counter_expires_at + sweep, the counter
        transitions to EXPIRED (verified via rebound now returning
        ERR_COUNTER_EXPIRED).
        """
        state = setup_offer_with_open_counter()
        listing = state["listing"]
        offer = state["offer"]
        counter = state["counter"]
        ba = state["buyer_agent"]
        from datetime import datetime, timedelta, timezone
        ce_dt = datetime.fromisoformat(
            counter["counter_expires_at"].replace("Z", "+00:00"),
        )
        advance_clock_and_sweep(iso_at(ce_dt + timedelta(seconds=120)))
        # Now attempt rebound — must fail with ERR_COUNTER_EXPIRED
        # (the counter was OPEN→EXPIRED via sweep).
        from test_helpers import rebound_offer_payload
        res = api.rebound_offer(
            listing["id"], offer["id"],
            rebound_offer_payload(
                offer_price_cents=50_000_000,
                earnest_money_cents=1_000_000,
                expires_at=iso_at(ce_dt + timedelta(hours=2)),
            ),
            make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_COUNTER_EXPIRED.value)


class TestContingencyExpiryByClock:
    """PRD §3.7 + §3.9 PENDING Contingency → FAILED → cascade."""

    def test_contingency_deadline_passed_triggers_fail_cascade(self, api):
        """PRD §3.7: 'a PENDING contingency whose deadline_at is in
        the past becomes FAILED (with the listing rebound cascade)'.

        Claim: After clock past contingency.deadline_at + sweep, the
        Listing reverts UNDER_CONTRACT → ACTIVE.
        """
        from test_helpers import attach_contingency
        state = setup_listing_under_contract()
        # Attach contingency with deadline in 1 hour.
        c = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
            offset_seconds=3600,
        )
        # Advance past deadline.
        advance_clock_and_sweep(iso_in_future(7200))
        listing_after = get_listing_state(state["accepted_listing"]["id"])
        assert listing_after["status"] == "ACTIVE", (
            f"PRD §3.7 cascade after sweep: listing must revert to ACTIVE, "
            f"got {listing_after['status']!r}"
        )
        assert listing_after.get("accepted_offer_id") is None


# NOTE: TestShowingNoShowByClock removed — PRD §3.5 stamps
# lockbox_access_granted_at on approval, so a SCHEDULED showing always
# has lockbox_access_granted_at != NULL, but the NO_SHOW sweep rule
# requires lockbox_access_granted_at IS NULL. The transition is
# therefore unreachable under PRD's own preconditions; the test is
# deleted under the cross-entity-cascade silence category.


class TestClockAdvanceContract:
    """PRD §3.9 admin clock-advance returns now."""

    def test_clock_advance_returns_now_field(self, api, mls_admin_headers):
        """PRD §3.9: 'The admin clock-advance capability takes a target
        instant `to` in ISO 8601 form and moves the server's logical
        clock to that instant, returning the resulting now.'

        Claim: POST /_clock/advance with a future `to` returns a body
        whose data contains `now`.
        """
        target = iso_in_future(3600)
        from test_helpers import clock_advance_payload
        resp = api.clock_advance(
            clock_advance_payload(to=target), mls_admin_headers,
        )
        body = resp.json()
        assert resp.status_code == 200, body
        data = body["data"]
        assert "now" in data, f"PRD §3.9 must return `now` field; data={data}"


class TestSweepResponseFields:
    """PRD §3.9 sweep response counts."""

    def test_sweep_response_has_five_count_fields(
        self, api, mls_admin_headers,
    ):
        """PRD §3.9: 'The sweep response surfaces the count of rows
        transitioned in each of those five categories.' (PRD §4
        endpoint description names them: expired_offers,
        expired_counters, failed_contingencies, expired_listings,
        no_show_showings.)

        Claim: POST /_sweep/run returns a data object with all five
        named count fields.
        """
        resp = api.sweep_run(mls_admin_headers)
        body = resp.json()
        assert resp.status_code == 200
        data = body["data"]
        for field in (
            "expired_offers", "expired_counters", "failed_contingencies",
            "expired_listings", "no_show_showings",
        ):
            assert field in data, (
                f"PRD §3.9 sweep response missing {field!r}; got "
                f"keys={list(data.keys())}"
            )
            assert isinstance(data[field], int), (
                f"{field} must be int, got {type(data[field]).__name__}"
            )
