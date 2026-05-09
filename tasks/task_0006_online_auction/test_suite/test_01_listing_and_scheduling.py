"""Listing, scheduling, and the physical-item-slot rule (PRD §3.1)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    create_seller_payload, create_lot_payload, advance_clock_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers, make_admin_headers,
    create_seller, create_bidder, create_lot_for_seller, publish_lot,
    create_and_publish_lot, advance_clock, get_lot, iso_future, unique_serial,
    iso_relative, current_clock_now,
    validate_success, validate_error,
    assert_seller, assert_lot,
)


ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestSellerRegistration:
    def test_register_seller_returns_active(self, api):
        """PRD §3.7: "Seller registration accepts `display_name`, mints a `Seller` with
        `status = ACTIVE`, and initialises `total_lots_listed`, `gross_proceeds_cents`,
        and `net_proceeds_cents` to zero."

        Claim: POST /sellers initialises status=ACTIVE and counters=0.
        """
        resp = api.create_seller(create_seller_payload(display_name="Houses-R-Us"), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_seller(data)
        assert data["status"] == "ACTIVE"
        assert data["total_lots_listed"] == 0
        assert data["gross_proceeds_cents"] == 0
        assert data["net_proceeds_cents"] == 0
        assert data["display_name"] == "Houses-R-Us"

    def test_register_seller_role_forbidden(self, api):
        """PRD §3.7: "A `PlatformAdmin` is the only role permitted to register sellers
        and bidders, and is the sole writer for wallet credit."

        Claim: non-admin role on POST /sellers → ERR_ROLE_FORBIDDEN.
        """
        resp = api.create_seller(
            create_seller_payload(),
            TEST_USERS["bidder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_get_seller_not_found(self, api):
        """PRD §2.5: "The leftmost unresolved id triggers the family-specific not-found
        error: `ERR_SELLER_NOT_FOUND`..."

        Claim: GET /sellers/{nonexistent} → ERR_SELLER_NOT_FOUND.
        """
        resp = api.get_seller(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SELLER_NOT_FOUND.value)


class TestLotCreation:
    def test_create_lot_in_draft(self, api):
        """PRD §3.1: "The lot is born in `DRAFT` status with `effective_end_at` left null
        and `current_price_cents` initialised to `starting_bid_cents` minus one (a
        placeholder so the first qualifying bid simply has to clear `starting_bid_cents`);
        `extension_count` starts at 0 and `bid_count` at 0."

        Claim: New lot has status=DRAFT, current_price=starting-1, counters at 0.
        """
        seller = create_seller()
        payload = create_lot_payload(
            seller_id=seller["id"],
            starting_bid_cents=50_000,
            reserve_price_cents=100_000,
        )
        resp = api.create_lot(payload, make_seller_headers(seller["id"]))
        data = validate_success(resp, expected_status=201)
        assert_lot(data)
        assert data["status"] == "DRAFT"
        assert data["current_price_cents"] == 50_000 - 1
        assert data["extension_count"] == 0
        assert data["bid_count"] == 0

    def test_create_lot_seller_id_must_match_x_user_id(self, api):
        """PRD §3.1: "The body's `seller_id` must equal the `Seller`'s own `X-User-ID`;
        otherwise the request is rejected with `ERR_IDENTITY_MISMATCH`."

        Claim: seller_id != X-User-ID → ERR_IDENTITY_MISMATCH.
        """
        seller_a = create_seller("Seller A")
        seller_b = create_seller("Seller B")
        payload = create_lot_payload(seller_id=seller_b["id"])  # body says B
        resp = api.create_lot(payload, make_seller_headers(seller_a["id"]))  # but caller is A
        validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH.value)

    def test_create_lot_role_forbidden_for_bidder(self, api):
        """PRD §4 endpoint table: "POST /lots ... Authorized: Seller".

        Claim: Bidder attempting POST /lots → ERR_ROLE_FORBIDDEN (priority 2).
        """
        seller = create_seller()
        bidder = create_bidder()
        payload = create_lot_payload(seller_id=seller["id"])
        resp = api.create_lot(payload, make_bidder_headers(bidder["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)


class TestPublishValidation:
    def test_publish_duration_too_short(self, api):
        """PRD §3.1: "The interval between `scheduled_start_at` and `scheduled_end_at`
        must be at least one hour, expressed in seconds as a difference of at least 3600;
        a shorter interval produces `ERR_LOT_DURATION_TOO_SHORT`."

        Claim: Lot with end - start < 3600 → ERR_LOT_DURATION_TOO_SHORT on publish.
        """
        seller = create_seller()
        # 30-minute window, anchored 1 day in the future
        lot = create_lot_for_seller(
            seller,
            scheduled_start_at=iso_relative(86400),
            scheduled_end_at=iso_relative(86400 + 1800),
        )
        resp = api.publish_lot(lot["id"], make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_DURATION_TOO_SHORT.value)

    def test_publish_start_in_past(self, api):
        """PRD §3.1: "The `scheduled_start_at` must be strictly after the current logical
        clock at the moment of publish; a start time at or before `now()` produces
        `ERR_LOT_START_IN_PAST`."

        Claim: scheduled_start_at <= now() → ERR_LOT_START_IN_PAST.
        """
        seller = create_seller()
        # Create with future schedule, then advance clock past start
        lot = create_lot_for_seller(
            seller,
            scheduled_start_at=iso_relative(86400),
            scheduled_end_at=iso_relative(86400 + 7200),
        )
        # advance well past scheduled_start_at
        advance_clock(86400 + 3600)
        resp = api.publish_lot(lot["id"], make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_START_IN_PAST.value)

    def test_publish_moves_draft_to_scheduled(self, api):
        """PRD §3.1: "Publishing — the act that moves a lot from `DRAFT` to `SCHEDULED`
        — is the lifecycle gate that runs the schedule and slot-uniqueness checks. ...
        On a successful publish, `effective_end_at` is initialised to `scheduled_end_at`."

        Claim: Successful publish → status=SCHEDULED and effective_end_at == scheduled_end_at.
        """
        seller = create_seller()
        lot = create_and_publish_lot(seller)
        assert lot["status"] == "SCHEDULED"
        assert lot["effective_end_at"] == lot["scheduled_end_at"]

    def test_publish_non_owner_identity_mismatch(self, api):
        """PRD §2.1: "When `X-User-Role` is `Seller`, the `X-User-ID` value is the `id` of
        the acting `Seller`; ownership checks on a lot compare `Lot.seller_id` to
        `X-User-ID`."
        PRD §2.1: "When the role passes the role-permission check (priority 2) but the
        acting principal is not the resource's owner under the rules above, the request
        is rejected with `ERR_IDENTITY_MISMATCH` and HTTP status 403."

        Claim: Seller A publishing Seller B's lot → ERR_IDENTITY_MISMATCH.
        """
        seller_a = create_seller("Seller A")
        seller_b = create_seller("Seller B")
        lot = create_lot_for_seller(seller_b)
        resp = api.publish_lot(lot["id"], make_seller_headers(seller_a["id"]))
        validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH.value)


class TestPhysicalItemSlot:
    def test_overlap_blocks_publish(self, api):
        """PRD §3.1: "no other lot may already hold the same `physical_item_serial`
        over an overlapping time window. ... A violation produces
        `ERR_PHYSICAL_ITEM_TIME_OVERLAP`."

        Claim: Overlapping intervals on same physical_item_serial → ERR_PHYSICAL_ITEM_TIME_OVERLAP.
        """
        seller = create_seller()
        serial = unique_serial()
        # Anchor relative to current clock so this works no matter how far the
        # session clock has advanced.
        T = 86400
        H = 3600
        # First lot: [T, T+2h)
        create_and_publish_lot(
            seller,
            physical_item_serial=serial,
            scheduled_start_at=iso_relative(T),
            scheduled_end_at=iso_relative(T + 2 * H),
        )
        # Overlapping second lot: [T+1h, T+3h)
        lot_b = create_lot_for_seller(
            seller,
            physical_item_serial=serial,
            scheduled_start_at=iso_relative(T + H),
            scheduled_end_at=iso_relative(T + 3 * H),
        )
        resp = api.publish_lot(lot_b["id"], make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_PHYSICAL_ITEM_TIME_OVERLAP.value)

    def test_adjacent_intervals_allowed(self, api):
        """PRD §3.1: "The intervals are half-open: lot A's `[scheduled_start_at,
        effective_end_at)` overlaps lot B's `[scheduled_start_at, scheduled_end_at)` if
        and only if A's interval starts strictly before B's ends and A's interval ends
        strictly after B's starts. Adjacency — A ending exactly at B's start — is
        therefore permitted."

        Claim: A.end == B.start with same physical_item_serial does NOT overlap.

        # difficulty: resource_temporal_overlap/physical_item_serial_half_open_overlap
        """
        seller = create_seller()
        serial = unique_serial()
        T = 86400
        H = 3600
        # First: [T, T+2h)
        create_and_publish_lot(
            seller,
            physical_item_serial=serial,
            scheduled_start_at=iso_relative(T),
            scheduled_end_at=iso_relative(T + 2 * H),
        )
        # Adjacent: [T+2h, T+4h)
        lot_b = create_lot_for_seller(
            seller,
            physical_item_serial=serial,
            scheduled_start_at=iso_relative(T + 2 * H),
            scheduled_end_at=iso_relative(T + 4 * H),
        )
        resp = api.publish_lot(lot_b["id"], make_seller_headers(seller["id"]))
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"

    def test_overlap_is_409_with_exact_error(self, api):
        """PRD §3.1: "A violation produces `ERR_PHYSICAL_ITEM_TIME_OVERLAP`."
        PRD §5: ERR_PHYSICAL_ITEM_TIME_OVERLAP is HTTP 409.

        Claim: Strictly-overlapping window → exact ERR_PHYSICAL_ITEM_TIME_OVERLAP at HTTP 409.

        # difficulty: resource_temporal_overlap/physical_item_serial_half_open_overlap
        """
        seller = create_seller()
        serial = unique_serial()
        T = 86400
        H = 3600
        # First: [T, T+3h)
        create_and_publish_lot(
            seller,
            physical_item_serial=serial,
            scheduled_start_at=iso_relative(T),
            scheduled_end_at=iso_relative(T + 3 * H),
        )
        # Strictly inside first: [T+1h, T+2h)
        lot_b = create_lot_for_seller(
            seller,
            physical_item_serial=serial,
            scheduled_start_at=iso_relative(T + H),
            scheduled_end_at=iso_relative(T + 2 * H),
        )
        resp = api.publish_lot(lot_b["id"], make_seller_headers(seller["id"]))
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_PHYSICAL_ITEM_TIME_OVERLAP"


class TestCancellation:
    def test_cancel_in_draft(self, api):
        """PRD §3.1: "A still-unstarted lot — one in `DRAFT` or `SCHEDULED` — may be
        cancelled by its owning `Seller`, which terminates the lot in `CANCELLED` with
        no further side-effects."

        Claim: Cancel from DRAFT → status=CANCELLED.
        """
        seller = create_seller()
        lot = create_lot_for_seller(seller)
        resp = api.cancel_lot(lot["id"], make_seller_headers(seller["id"]))
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_in_scheduled(self, api):
        """PRD §3.1: "A still-unstarted lot — one in `DRAFT` or `SCHEDULED` — may be
        cancelled by its owning `Seller`, which terminates the lot in `CANCELLED`..."

        Claim: Cancel from SCHEDULED → status=CANCELLED.
        """
        seller = create_seller()
        lot = create_and_publish_lot(seller)
        resp = api.cancel_lot(lot["id"], make_seller_headers(seller["id"]))
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_outside_draft_or_scheduled(self, api):
        """PRD §3.1: "Cancellation outside `DRAFT` and `SCHEDULED` is rejected with
        `ERR_LOT_INVALID_STATE`."

        Claim: cancel on LIVE lot → ERR_LOT_INVALID_STATE.
        """
        from test_helpers import setup_live_lot
        seller, lot = setup_live_lot()
        resp = api.cancel_lot(lot["id"], make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value)


class TestScheduledToLive:
    def test_clock_advance_drives_scheduled_to_live(self, api):
        """PRD §3.1: "When the logical clock crosses `scheduled_start_at`, the lot moves
        from `SCHEDULED` to `LIVE` automatically — the system does not require any actor
        to perform this transition."

        Claim: After clock advances past scheduled_start_at, lot.status is LIVE.
        """
        from test_helpers import setup_live_lot
        seller, lot = setup_live_lot()
        assert lot["status"] == "LIVE"


class TestAnonymousAccess:
    def test_anonymous_can_read_lots(self, api):
        """PRD §3.7: "`Anonymous` callers may read public lot data (the lot detail, the lot
        list with its `status`, `category`, and `seller_id` filters and `limit`/`offset`
        pagination, the per-lot bid list, and the seller record)."

        Claim: Anonymous GET /lots/{id} succeeds.
        """
        seller = create_seller()
        lot = create_lot_for_seller(seller)
        resp = api.get_lot(lot["id"], ANON)
        validate_success(resp)

    def test_anonymous_blocked_from_mutation(self, api):
        """PRD §3.7: "They may not invoke any mutation, and any mutation attempt resolves
        to `ERR_ROLE_FORBIDDEN`."

        Claim: Anonymous on POST /lots → ERR_ROLE_FORBIDDEN.
        """
        resp = api.create_lot(create_lot_payload(seller_id=NON_EXISTENT_UUID), ANON)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)


class TestUserContextHeader:
    def test_missing_x_user_id_header(self, api):
        """PRD §2.1: "Every request must include two headers: `X-User-ID` (the acting
        principal's identifier) and `X-User-Role` (one of the five role names enumerated
        below). A request missing either header, or carrying an empty value, or naming
        a role outside the recognised set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP status 400."

        Claim: missing X-User-ID → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api.create_seller(
            create_seller_payload(),
            {"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_invalid_role_value(self, api):
        """PRD §2.1: "...or naming a role outside the recognised set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`..."

        Claim: unknown role → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api.create_seller(
            create_seller_payload(),
            {"X-User-ID": "alice", "X-User-Role": "Wizard", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_empty_headers(self, api):
        """PRD §2.1: "...or carrying an empty value..."

        Claim: empty X-User-ID → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        resp = api.create_seller(
            create_seller_payload(),
            {"X-User-ID": "", "X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
