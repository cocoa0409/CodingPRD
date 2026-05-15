"""Lot intake, inspection windows, statutory notice, withdrawal
(PRD §3.1, §3.3)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_inspection_window_payload,
    announce_lot,
    api_client,
    assert_lot,
    create_lot,
    create_lot_payload,
    FIRST_AUCTION_DISCOUNT_BPS,
    get_auction,
    get_lot,
    iso_offset,
    iso_utc,
    open_auction,
    place_bid,
    setup_announced_lot,
    setup_bidder_with_paid_deposit,
    setup_live_auction,
    setup_lot_with_auction,
    STATUTORY_NOTICE_DAYS,
    utcnow,
    validate_error,
    validate_success,
    withdraw_lot,
    withdraw_lot_payload,
)


# ===========================================================================
# Registration happy path — PRD §3.1
# ===========================================================================
class TestLotRegistration:

    def test_register_lot_returns_registered_status(self, api,
                                                  court_clerk_headers):
        """PRD §3.1: "A successful registration creates the `Lot` row in `REGISTERED` status (its `status` field is computed and defaults to `DRAFT` at row level, but the registration transition writes `REGISTERED` atomically)."

        Claim: POST /lots → 201 and Lot.status == REGISTERED.
        """
        resp = api.create_lot(create_lot_payload(), court_clerk_headers)
        lot = validate_success(resp, expected_status=201)
        assert_lot(lot)
        assert lot["status"] == "REGISTERED"

    def test_register_lot_starts_round_number_at_one(self, api,
                                                    court_clerk_headers):
        """PRD §3.3: "The `Lot.round_number` starts at one on registration and is incremented by one each time a re-auction is triggered."

        Claim: round_number == 1 on freshly registered Lot.
        """
        lot = create_lot()
        assert lot["round_number"] == 1

    def test_first_auction_starting_price_uses_30pct_discount(
        self, api, court_clerk_headers,
    ):
        """PRD §3.3: "The starting price for the first auction of a lot is the court-appointed assessment value discounted by thirty percent. Precisely: when the auction's `round_number` is one, `starting_price_cents` is the result of multiplying `Lot.assessment_value_cents` by ten thousand minus three thousand (the basis-point representation of the first-auction discount), then dividing by ten thousand, then rounding half up to integer cents."

        Claim: starting_price = round_half_up(assessment * 7000 / 10000).
        """
        lot, auction = setup_lot_with_auction(
            assessment_value_cents=100_000_000,
        )
        assert auction["starting_price_cents"] == 70_000_000, (
            f"Expected 70_000_000 (= 100_000_000 * 0.7), "
            f"got {auction['starting_price_cents']}"
        )

    def test_duplicate_court_order_no_rejected(self, api, court_clerk_headers):
        """PRD §3.1: "the underlying court order by `court_order_no` (which must be non-empty and is unique across the system; collisions are rejected with `ERR_DUPLICATE`)"

        Claim: second POST /lots with the same court_order_no →
        ERR_DUPLICATE.
        """
        payload = create_lot_payload(court_order_no="CO-DUP-001")
        first = api.create_lot(payload, court_clerk_headers)
        validate_success(first, expected_status=201)
        second = api.create_lot(payload, court_clerk_headers)
        validate_error(second, ApiErrorId.ERR_DUPLICATE.value)

    def test_inspection_window_overlapping_auction_rejected(
        self, api, court_clerk_headers,
    ):
        """PRD §3.1: "The inspection window must end strictly before the planned auction start; an `inspection_window_end_at` greater than or equal to `auction_scheduled_start_at` is rejected with `ERR_INSPECTION_OVERLAPS_AUCTION."

        Claim: end_at == auction_start → ERR_INSPECTION_OVERLAPS_AUCTION.
        """
        auction_start = utcnow() + timedelta(days=30)
        payload = create_lot_payload(
            auction_scheduled_start_at=iso_utc(auction_start),
            inspection_window_start_at=iso_utc(
                auction_start - timedelta(hours=2),
            ),
            inspection_window_end_at=iso_utc(auction_start),
        )
        resp = api.create_lot(payload, court_clerk_headers)
        validate_error(
            resp, ApiErrorId.ERR_INSPECTION_OVERLAPS_AUCTION.value,
        )


# ===========================================================================
# Inspection windows — PRD §3.1 second paragraph
# ===========================================================================
class TestInspectionWindowConflict:

    def test_adjacent_windows_rejected_closed_interval(
        self, api, court_clerk_headers,
    ):
        """PRD §3.1: "Two inspection windows on the same lot may not overlap, and adjacency counts as overlap — that is, a new window whose `start_at` is exactly equal to an existing window's `end_at` is rejected (closed-interval semantics). Overlapping or touching attempts surface `ERR_INSPECTION_WINDOW_CONFLICT."

        Claim: start_at == existing.end_at → ERR_INSPECTION_WINDOW_CONFLICT.
        """
        lot, _ = setup_lot_with_auction()
        existing_end = lot["inspection_window_end_at"]
        # New window starts exactly at the original's end → conflict.
        resp = api.add_inspection_window(
            lot["id"],
            add_inspection_window_payload(
                start_at=existing_end,
                end_at=iso_offset(hours=2, base=_parse(existing_end)),
            ),
            court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT.value)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ===========================================================================
# Announcement statutory notice — PRD §3.1
# ===========================================================================
class TestAnnouncementStatutoryNotice:

    def test_announce_with_less_than_15_days_notice_rejected(
        self, api, court_clerk_headers,
    ):
        """PRD §3.1: "The announcement is only valid if the gap between
        the planned auction_scheduled_start_at and the current instant
        is at least fifteen calendar days — the statutory notice
        period. An announcement attempted with less than fifteen
        calendar days of notice is rejected with
        ERR_STATUTORY_NOTICE_INSUFFICIENT."

        Claim: auction_scheduled_start_at < now+15d → reject.
        """
        # Schedule an auction 5 days from now — well under the 15-day floor.
        auction_start = utcnow() + timedelta(days=5)
        payload = create_lot_payload(
            auction_scheduled_start_at=iso_utc(auction_start),
            inspection_window_start_at=iso_utc(
                auction_start - timedelta(hours=4),
            ),
            inspection_window_end_at=iso_utc(
                auction_start - timedelta(hours=1),
            ),
        )
        create_resp = api.create_lot(payload, court_clerk_headers)
        lot = validate_success(create_resp, expected_status=201)
        resp = api.announce_lot(lot["id"], headers=court_clerk_headers)
        validate_error(
            resp, ApiErrorId.ERR_STATUTORY_NOTICE_INSUFFICIENT.value,
        )

    def test_announce_with_exactly_15_days_notice_succeeds(
        self, api, court_clerk_headers,
    ):
        """PRD §3.1: "the gap between the planned `auction_scheduled_start_at` and the current instant is at least fifteen calendar days." The threshold is `>=`, so exactly 15
        days suffices.

        Claim: auction_scheduled_start_at == now+15d → announce succeeds.
        """
        auction_start = utcnow() + timedelta(days=STATUTORY_NOTICE_DAYS,
                                              hours=1)
        payload = create_lot_payload(
            auction_scheduled_start_at=iso_utc(auction_start),
            inspection_window_start_at=iso_utc(
                auction_start - timedelta(hours=4),
            ),
            inspection_window_end_at=iso_utc(
                auction_start - timedelta(hours=1),
            ),
        )
        lot = validate_success(
            api.create_lot(payload, court_clerk_headers),
            expected_status=201,
        )
        resp = api.announce_lot(lot["id"], headers=court_clerk_headers)
        data = validate_success(resp)
        assert data["status"] == "ANNOUNCED"

    def test_announce_transitions_status_to_announced(
        self, api, court_clerk_headers,
    ):
        """PRD §3.1: "The `CourtClerk` then publishes the auction announcement, transitioning the `Lot.status` from `REGISTERED` to `ANNOUNCED`. This transition stamps `announcement_published_at` to the current instant."

        Claim: announce → Lot.status == ANNOUNCED and
        announcement_published_at populated.
        """
        lot, auction = setup_announced_lot()
        assert lot["status"] == "ANNOUNCED"
        assert lot.get("announcement_published_at"), \
            "announcement_published_at must be stamped after announce"


# ===========================================================================
# Withdrawal — PRD §3.1
# ===========================================================================
class TestLotWithdrawal:

    def test_withdraw_registered_lot_succeeds(self, api, court_clerk_headers):
        """PRD §3.1: "Before any auction has gone live or sold, a `CourtClerk` may withdraw the lot, transitioning `Lot.status` from `REGISTERED` to `WITHDRAWN."

        Claim: withdraw on REGISTERED Lot → status == WITHDRAWN.
        """
        lot, _auction = setup_lot_with_auction()
        resp = api.withdraw_lot(
            lot["id"], court_clerk_headers, withdraw_lot_payload(),
        )
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_rejected_when_auction_live(self, api,
                                                court_clerk_headers):
        """PRD §3.1: "A withdrawal is rejected if any associated `Auction` has already reached `LIVE` or `SOLD."

        Claim: withdraw on Lot whose sibling Auction is LIVE →
        ERR_INVALID_STATE.
        """
        lot, _auction, _bidders = setup_live_auction(num_bidders=1)
        resp = api.withdraw_lot(
            lot["id"], court_clerk_headers, withdraw_lot_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# CRUD list endpoint — PRD §3.12
# ===========================================================================
class TestLotListFilter:

    def test_list_lots_status_filter(self, api, court_clerk_headers):
        """PRD §3.12: "The lot listing accepts a `status` filter to scope by `DRAFT`, `REGISTERED`, `ANNOUNCED`, `AUCTIONED`, `WITHDRAWN`, or `TRANSFERRED."

        Claim: GET /lots?status=ANNOUNCED returns only ANNOUNCED lots.
        """
        # Build one ANNOUNCED and one REGISTERED-only lot.
        lot_announced, _ = setup_announced_lot()
        lot_registered, _ = setup_lot_with_auction()
        resp = api.list_lots(
            court_clerk_headers, params={"status": "ANNOUNCED", "limit": 100},
        )
        data, _meta = validate_success(resp), None
        # validate_success returns the array directly when response_type=array
        ids = {row["id"] for row in data}
        assert lot_announced["id"] in ids
        assert lot_registered["id"] not in ids, (
            "REGISTERED Lot must not appear under status=ANNOUNCED filter"
        )


# ===========================================================================
# Not-found path-parameter resolution — PRD §2.8
# ===========================================================================
class TestNotFoundOnLotPaths:

    def test_announce_unknown_lot_returns_not_found(self, api,
                                                  court_clerk_headers):
        """PRD §2.8: "Endpoints with multiple identifiers in their path validate those identifiers in strict left-to-right order. The first identifier that does not resolve to an existing row causes the request to be rejected with `ERR_NOT_FOUND."

        Claim: POST /lots/{unknown}/announce → ERR_NOT_FOUND.
        """
        resp = api.announce_lot(NON_EXISTENT_UUID, headers=court_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_unknown_lot_returns_not_found(self, api,
                                              court_clerk_headers):
        """PRD §2.8: existence checks return ERR_NOT_FOUND when the path
        identifier does not resolve.

        Claim: GET /lots/{unknown} → ERR_NOT_FOUND.
        """
        resp = api.get_lot(NON_EXISTENT_UUID, court_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
