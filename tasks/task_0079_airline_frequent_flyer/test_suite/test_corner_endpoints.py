"""Queue B (Corner) — not-found, pagination, and FK reverse-reachability listings."""
from test_helpers import validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, create_booked_segment, create_pool,
    current_pool_version, create_companion_certificate, create_pending_gift, grant_status_match,
    inject_points,
)
from test_helpers.factories import (
    create_member_payload, create_award_booking_payload, create_upgrade_request_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


class TestNotFoundAndPagination:
    def test_get_member_not_found(self, api):
        """PRD §2.10: "Next, the existence of every path and referenced resource is
        checked, validated left to right across the path and any foreign keys
        (ERR_NOT_FOUND)."

        Design: Corner/endpoints/get_member_not_found
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        validate_error(api.get_member(NON_EXISTENT_UUID, ADMIN), "ERR_NOT_FOUND")

    def test_list_members_pagination(self, api):
        """PRD §2.3: "Alongside the page of data, the response meta carries the
        pagination bookkeeping fields limit, offset, total_count (the total number of
        records matching the query before the page window is applied), and has_more (a
        boolean that is true when records remain beyond the current window)."

        Design: Corner/endpoints/list_members_pagination
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        for _ in range(3):
            validate_success(api.create_member(create_member_payload(), ADMIN), 201)
        data, meta = validate_paginated(api.list_members(ADMIN, params={"limit": 2, "offset": 0}))
        assert meta["total_count"] == 3, meta
        assert len(data) == 2, data
        assert meta["has_more"] is True, meta

    def test_pagination_limit_out_of_bounds(self, api):
        """PRD §2.3: "The limit parameter defaults to 10 when omitted, may be no smaller
        than 1, and may be no larger than 100. The offset parameter defaults to 0 and
        represents the number of leading records to skip. A limit below 1 or above 100,
        or a negative offset, is rejected with ERR_PAGINATION_INVALID (HTTP 400)."

        Design: Corner/endpoints/pagination_limit_out_of_bounds
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        validate_error(api.list_members(ADMIN, params={"limit": 500, "offset": 0}), "ERR_PAGINATION_INVALID")


class TestFkReverseReachability:
    def test_fk_reverse_member_segments(self, api):
        """PRD §3.1: "their flying history as their FlightSegment records - both
        retrievable as owned sub-collections."

        Design: Corner/endpoints/fk_reverse_member_segments
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        m = create_member(api)
        seg = create_booked_segment(api, m["id"], scheduled_departure="2026-02-01T08:00:00.000Z")
        data, _ = validate_paginated(api.list_member_segments(m["id"], ADMIN))
        assert len(data) == 1, data
        assert data[0]["id"] == seg["id"], data

    def test_fk_reverse_pool_upgrade_requests(self, api):
        """PRD §3.8: "Upgrade requests for a pool, and a member's own upgrade requests,
        are retrievable as listed sub-collections."

        Design: Corner/endpoints/fk_reverse_pool_upgrade_requests
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA11", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=2)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m),
            ), 201,
        )
        data, _ = validate_paginated(api.list_pool_upgrade_requests(pool["id"], AGENT))
        assert len(data) == 1, data
        assert data[0]["id"] == req["id"], data

    def test_fk_reverse_award_by_certificate(self, api):
        """PRD §4: "GET /award-bookings | List award bookings, filterable by member or
        attached certificate | ProgramAdmin, Member"
        PRD §3.5: "A valid attachment moves the certificate ISSUED -> RESERVED and
        records the new award's id as the certificate's attached_award_id, so the
        certificate is held against the quote."

        Design: Corner/endpoints/fk_reverse_award_by_certificate
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(
                    m["id"], cabin="ECONOMY", pricing_mode="FIXED", companion_certificate_id=cert["id"]
                ),
                hdrs,
            ), 201,
        )
        data, _ = validate_paginated(api.list_award_bookings(hdrs, params={"companion_certificate_id": cert["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == award["id"], data

    def test_fk_reverse_gifts_by_recipient(self, api):
        """PRD §4: "GET /points-gifts | List points gifts, filterable by sender or
        recipient | ProgramAdmin, Member"
        PRD §3.6: "Creating a gift records the sender_id, the recipient_id, and the
        integer amount (at least 1), and starts the gift in state PENDING."

        Design: Corner/endpoints/fk_reverse_gifts_by_recipient
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        gift = create_pending_gift(api, sender, recipient["id"], amount=100)
        data, _ = validate_paginated(api.list_points_gifts(ADMIN, params={"recipient_id": recipient["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == gift["id"], data

    def test_fk_reverse_certificates_by_member(self, api):
        """PRD §4: "GET /companion-certificates | List companion certificates, filterable
        by member or attached award | ProgramAdmin, Member"

        Design: Corner/endpoints/fk_reverse_certificates_by_member
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        data, _ = validate_paginated(api.list_companion_certificates(ADMIN, params={"member_id": m["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == cert["id"], data

    def test_fk_reverse_status_matches_by_member(self, api):
        """PRD §4: "GET /status-matches | List status matches, filterable by member |
        ProgramAdmin, Member"

        Design: Corner/endpoints/fk_reverse_status_matches_by_member
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        sm = grant_status_match(api, m["id"], rival_tier="GOLD")
        data, _ = validate_paginated(api.list_status_matches(ADMIN, params={"member_id": m["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == sm["id"], data

    def test_fk_reverse_ledger_by_member(self, api):
        """PRD §3.1: "A member's points history is available as their PointsLedger rows."
        PRD §2.6: "Every movement of points is recorded as an append-only PointsLedger
        row. Each row records the owning member_id, a signed delta."

        Design: Corner/endpoints/fk_reverse_ledger_by_member
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 1000)
        data, _ = validate_paginated(api.list_member_ledger(m["id"], ADMIN))
        assert len(data) >= 1, data
        assert data[0]["delta"] == 1000, data

    def test_fk_reverse_awards_by_member(self, api):
        """PRD §4: "GET /award-bookings | List award bookings, filterable by member or
        attached certificate | ProgramAdmin, Member"

        Design: Corner/endpoints/fk_reverse_awards_by_member
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )
        data, _ = validate_paginated(api.list_award_bookings(hdrs, params={"member_id": m["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == award["id"], data

    def test_fk_reverse_upgrade_requests_by_member(self, api):
        """PRD §4: "GET /upgrade-requests | List upgrade requests, filterable by member
        or pool | ProgramAdmin, OperationsAgent, Member"
        PRD §3.8: "a member's own upgrade requests, are retrievable as listed
        sub-collections."

        Design: Corner/endpoints/fk_reverse_upgrade_requests_by_member
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA12", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=2)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m),
            ), 201,
        )
        data, _ = validate_paginated(api.list_upgrade_requests(ADMIN, params={"member_id": m["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == req["id"], data

    def test_fk_reverse_gifts_by_sender(self, api):
        """PRD §4: "GET /points-gifts | List points gifts, filterable by sender or
        recipient | ProgramAdmin, Member"

        Design: Corner/endpoints/fk_reverse_gifts_by_sender
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        gift = create_pending_gift(api, sender, recipient["id"], amount=100)
        data, _ = validate_paginated(api.list_points_gifts(ADMIN, params={"sender_id": sender["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == gift["id"], data
