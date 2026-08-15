"""List endpoints: pagination envelope, status filtering, reverse reachability
of cascade-created children, and the permit's blocked-span read-back
(PRD §2.2, §2.3, §3.4, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    invoice_of_kind,
    make_booking_env, make_draft_request, submit_request,
    make_approved_permit_in_env, capture_deposit,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _three_drafts(api):
    """Renter (with VALID insurance, so a draft can be submitted) holding three
    DRAFT requests (E1..E3) on separate days."""
    env = make_booking_env()
    for i, day in enumerate(("01", "02", "03"), start=1):
        make_draft_request(env, event_title=f"E{i}", headcount_estimate=10,
                           starts_at=f"2026-12-{day}T01:00:00Z",
                           ends_at=f"2026-12-{day}T02:00:00Z")
    return env


class TestPagination:
    def test_list_endpoints_paginate_with_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return. If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/list_endpoints_paginate_with_envelope
        """
        _three_drafts(api)
        page1 = api.list_requests(DIRECTOR, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert meta1["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in meta1

        page2 = api.list_requests(DIRECTOR, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_list_filter_by_status(self, api):
        """PRD §2.3: "Beyond pagination, individual list endpoints accept the
        filter parameters referenced throughout §3 — the identifier filters
        `site_id`, `facility_id`, `permit_id`, `invoice_id`, `renter_org_id`,
        `rental_request_id`, `seasonal_permit_id`, and `superseded_by_permit_id`,
        and the status-or-class filters `facility_status`, `facility_tier`,
        `rate_class`, `policy_status`, `org_standing`, `request_status`,
        `cert_status`, `event_status`, `lifecycle_status`, `financial_status`,
        `invoice_kind`, `invoice_status`, `txn_kind`, `wo_status`,
        `assessment_status`, and `series_status`."

        Design: Corner/endpoints/list_filter_by_status
        """
        env = _three_drafts(api)
        # Submit exactly one of the three drafts.
        requests = validate_success(api.list_requests(DIRECTOR))
        submit_request(env, requests[0]["id"])

        data, meta = validate_paginated(api.list_requests(
            DIRECTOR, params={"request_status": "DRAFT"}))
        assert meta["total_count"] == 2
        assert len(data) == 2
        assert all(row["request_status"] == "DRAFT" for row in data)


class TestReverseReachability:
    def test_fk_reverse_reachability_subresources(self, api):
        """PRD §3.5: "One approved request has exactly one non-void permit."
        PRD §3.4: "A successful approval increments the request's `version` by
        one and triggers a chain of creations detailed in §3.5: a Permit in
        `ISSUED` with `DEPOSIT_PENDING`, a `PROVISIONAL` invoice, and — when the
        facility's `requires_custodian` is set — a `SCHEDULED` custodial work
        order."

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        env = make_booking_env()
        req, permit = make_approved_permit_in_env(
            env, event_title="Auction", headcount_estimate=100,
            starts_at="2026-12-01T01:00:00Z", ends_at="2026-12-01T03:00:00Z")
        capture_deposit(env, permit["id"], 10000, "dep-fk-1")

        permits = validate_success(api.list_request_permits(req["id"], DIRECTOR))
        assert len(permits) == 1
        assert permits[0]["id"] == permit["id"]
        assert permits[0]["rental_request_id"] == req["id"]

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        assert len(invoices) == 1
        assert invoices[0]["invoice_kind"] == "PROVISIONAL"

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        assert len(payments) == 1
        assert payments[0]["txn_kind"] == "DEPOSIT_CAPTURE"
        assert payments[0]["amount_cents"] == 10000

        orders = validate_success(api.list_permit_work_orders(permit["id"], SUPERVISOR))
        assert len(orders) == 1
        assert orders[0]["wo_status"] == "SCHEDULED"
        assert orders[0]["permit_id"] == permit["id"]


class TestBlockedSpanReadback:
    def test_computed_read_facility_availability(self, api):
        """PRD §3.5: "Its confirmed event window runs from `occupancy_start`
        (inclusive) to `occupancy_end` (exclusive) — the requested window itself,
        with the setup buffer not included — while its calendar-blocked span runs
        from `blocked_start`, the occupancy start minus the facility's
        `setup_buffer_minutes`, to `blocked_end`, the occupancy end plus the
        `teardown_buffer_minutes`."

        Design: Corner/endpoints/computed_read_facility_availability
        """
        env = make_booking_env()
        req, permit = make_approved_permit_in_env(
            env, event_title="Auction", headcount_estimate=100,
            starts_at="2026-12-01T01:00:00Z", ends_at="2026-12-01T03:00:00Z")

        permits = validate_success(api.list_permits(
            DIRECTOR, params={"facility_id": env["facility"]["id"],
                              "lifecycle_status": "ISSUED"}))
        assert len(permits) == 1
        row = permits[0]
        assert row["id"] == permit["id"]
        assert row["occupancy_start"].startswith("2026-12-01T01:00:00")
        assert row["occupancy_end"].startswith("2026-12-01T03:00:00")
        # 30-minute buffers expand the blocked span on both sides.
        assert row["blocked_start"].startswith("2026-12-01T00:30:00")
        assert row["blocked_end"].startswith("2026-12-01T03:30:00")
