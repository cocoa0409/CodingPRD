"""Optimistic concurrency on approval and seasonal renewal, the approval
fan-out, and immediate read-after-write consistency (PRD §2.2, §2.5, §2.8,
§3.4, §3.5, §3.6, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    invoice_of_kind,
    make_renter_headers,
    make_booking_env,
    make_draft_request, submit_request, begin_review, approve,
    make_under_review_request, make_approved_permit_in_env,
    get_single_work_order,
    create_seasonal_permit_payload,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

EVENT_START = "2026-12-01T01:00:00Z"
EVENT_END = "2026-12-01T03:00:00Z"


class TestOccOnApprove:
    def test_occ_stale_version_on_approve(self, api):
        """PRD §2.8: "**Approving a rental request** — the
        `POST /district/requests/{request_id}/approve` endpoint — requires the
        request body to carry `expected_request_version`, the approver's last
        observed `version` of the RentalRequest. If the request's current
        `version` has advanced since the approver last read it — for example
        because the renter resubmitted revised details, which legitimately
        replaces the terms under review and leaves the approver's view of the
        request stale — the approval is rejected with `ERR_STALE_VERSION` (HTTP
        412), preventing the approver from approving terms they have not
        observed. A successful approval itself increments the request's `version`
        by one."
        PRD §2.5: "`version` (integer): a system-managed integer that increments
        with every modification to the resource, including system-initiated
        transitions and recomputation of derived fields."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_approve
        """
        env = make_booking_env()
        req = make_draft_request(env, event_title="Auction", headcount_estimate=100,
                                 starts_at=EVENT_START, ends_at=EVENT_END)
        submit_request(env, req["id"])
        v_stale = begin_review(req["id"])["version"]

        # A revision loop intervenes: request_revision, resubmit, and
        # begin_review each modify the request, so each bumps its version.
        validate_success(api.request_revision(
            req["id"], {"revision_note": "Adjust headcount"}, COORDINATOR))
        validate_success(api.resubmit_request(
            env["org"]["id"], req["id"], {"headcount_estimate": 90},
            make_renter_headers(env["org"]["id"])))
        v_fresh = begin_review(req["id"])["version"]
        assert v_fresh == v_stale + 3

        stale = api.approve_request(
            req["id"], {"expected_request_version": v_stale}, DIRECTOR)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        permits = validate_success(api.list_request_permits(req["id"], DIRECTOR))
        assert permits == [], "no Permit created by the stale approval"

        permit = approve(req["id"], v_fresh)
        assert permit["lifecycle_status"] == "ISSUED"
        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["version"] == v_fresh + 1, (
            "the successful approval itself increments the request version")
        assert after["request_status"] == "APPROVED"


class TestOccOnSeasonalRenewal:
    def test_occ_seasonal_renewal_stale_series(self, api):
        """PRD §2.8: "**Creating a renewal seasonal series** — that is, a call to
        the `POST /district/seasonal_permits` endpoint whose `renewed_from_id` is
        set — requires the request body to carry `expected_series_version`, the
        client's last observed `version` of the prior SeasonalPermit series. If
        the prior series' current `version` has advanced since the client last
        read it — for example because another writer has just renewed the same
        series, and renewals legitimately supersede one another under the
        seniority rule — the creation is rejected with `ERR_STALE_VERSION` (HTTP
        412)."
        PRD §3.9: "Seniority is hereditary: the new series' `seniority_key` is
        inherited from the renewed-from series' own `seniority_key`, so the
        earlier chain root wins conflicts; a series that renews nothing takes its
        own `created_at` as its `seniority_key`."
        PRD §3.9: "Renewal carries the optimistic-concurrency field
        `expected_series_version` per §2.8, and a successful renewal increments
        the renewed-from series' `version` by one."

        Design: Corner/cross_cutting_layers/occ_seasonal_renewal_stale_series
        """
        env = make_booking_env(org_name="Soccer League",
                               insurance_overrides={
                                   "effective_to": "2027-06-01T00:00:00Z"})
        org_id = env["org"]["id"]
        series = validate_success(api.create_seasonal_permit(
            create_seasonal_permit_payload(org_id, env["facility"]["id"],
                                           series_name="Fall Saturdays"),
            make_renter_headers(org_id)), 201)
        series = validate_success(api.get_seasonal_permit(series["id"], DIRECTOR))
        observed_version = series["version"]

        # First renewal against the observed version succeeds and inherits the
        # root series' seniority.
        renewal1 = validate_success(api.create_seasonal_permit(
            create_seasonal_permit_payload(
                org_id, env["facility"]["id"], series_name="Winter Saturdays",
                season_start="2026-11-07T00:00:00Z",
                season_end="2026-12-05T00:00:00Z",
                renewed_from_id=series["id"],
                expected_series_version=observed_version),
            make_renter_headers(org_id)), 201)
        assert renewal1["seniority_key"] == series["seniority_key"]
        bumped = validate_success(api.get_seasonal_permit(series["id"], DIRECTOR))
        assert bumped["version"] == observed_version + 1, (
            "a successful renewal increments the renewed-from series' version")

        # A second renewal carrying the pre-first-renewal version is stale.
        stale = api.create_seasonal_permit(
            create_seasonal_permit_payload(
                org_id, env["facility"]["id"], series_name="Spring Saturdays",
                season_start="2027-01-02T00:00:00Z",
                season_end="2027-01-30T00:00:00Z",
                renewed_from_id=series["id"],
                expected_series_version=observed_version),
            make_renter_headers(org_id))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestApprovalFanout:
    def test_cascading_side_effects_approve_fanout(self, api):
        """PRD §3.4: "A successful approval increments the request's `version` by
        one and triggers a chain of creations detailed in §3.5: a Permit in
        `ISSUED` with `DEPOSIT_PENDING`, a `PROVISIONAL` invoice, and — when the
        facility's `requires_custodian` is set — a `SCHEDULED` custodial work
        order."
        PRD §3.6: "Its `scheduled_start` is the permit's `blocked_start` — the
        custodian arrives at setup — and its `scheduled_end` is the
        `blocked_end`, departing only after teardown; `estimated_hours` is that
        full scheduled span expressed in hours to two decimal places, which means
        the buffers are billable custodial time."

        Design: Corner/cross_cutting_layers/cascading_side_effects_approve_fanout
        """
        env = make_booking_env()
        req = make_under_review_request(
            env, event_title="Auction", headcount_estimate=100,
            starts_at=EVENT_START, ends_at=EVENT_END)
        permit = approve(req["id"], req["version"])

        # Request side of the fan-out.
        request = validate_success(api.get_request(req["id"], DIRECTOR))
        assert request["request_status"] == "APPROVED"
        assert request["version"] == req["version"] + 1

        # Permit: ISSUED + DEPOSIT_PENDING; occupancy is the requested window,
        # the blocked span adds the 30/30 buffers.
        assert permit["lifecycle_status"] == "ISSUED"
        assert permit["financial_status"] == "DEPOSIT_PENDING"
        assert permit["occupancy_start"].startswith("2026-12-01T01:00:00")
        assert permit["occupancy_end"].startswith("2026-12-01T03:00:00")
        assert permit["blocked_start"].startswith("2026-12-01T00:30:00")
        assert permit["blocked_end"].startswith("2026-12-01T03:30:00")

        # Provisional invoice: rental 2.0h x 5000 = 10000; staffing 3.0h blocked
        # span x 4000 = 12000; Monday 16:30-19:30 site-local -> after-hours flag
        # only, uplift 0.50 -> 6000; subtotal 28000 < 50000 -> no discount.
        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        assert prov["invoice_status"] == "ISSUED"
        assert prov["rental_fee_cents"] == 10000
        assert prov["staffing_charge_cents"] == 12000
        assert prov["after_hours_charge_cents"] == 6000
        assert prov["discount_cents"] == 0
        assert prov["total_cents"] == 28000

        order = get_single_work_order(permit["id"])
        assert order["wo_status"] == "SCHEDULED"
        assert order["estimated_hours"] == pytest.approx(3.0)
        assert order["after_hours_flag"] is True
        assert order["weekend_flag"] is False
        assert order["scheduled_start"].startswith("2026-12-01T00:30:00")
        assert order["scheduled_end"].startswith("2026-12-01T03:30:00")


class TestImmediateConsistency:
    def test_immediate_consistency_mutation_visible_in_same_read(self, api):
        """PRD §2.2: "The `data` field contains the resource object or an array
        of resource objects. For 2xx responses with no data, it contains an empty
        object. Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.5: "When one operation mutates several resources — a site closure
        withdrawing requests and retiring facilities, an approval spawning a
        permit, an invoice, and a work order — every affected resource is mutated
        atomically within the same request, and each mutated resource's
        `updated_at` is refreshed and `version` incremented independently."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_read
        """
        env = make_booking_env()
        req = make_under_review_request(
            env, event_title="Auction", headcount_estimate=100,
            starts_at=EVENT_START, ends_at=EVENT_END)
        permit = approve(req["id"], req["version"])
        # The approval response itself carries the minted Permit — no async
        # provisioning lag.
        assert permit["lifecycle_status"] == "ISSUED"
        assert permit["rental_request_id"] == req["id"]

        # A separate read at the same logical instant sees the same state.
        reread = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert reread["lifecycle_status"] == "ISSUED"
        assert reread["financial_status"] == "DEPOSIT_PENDING"
        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        assert invoice_of_kind(invoices, "PROVISIONAL")["invoice_status"] == "ISSUED"
        assert get_single_work_order(permit["id"])["wo_status"] == "SCHEDULED"
