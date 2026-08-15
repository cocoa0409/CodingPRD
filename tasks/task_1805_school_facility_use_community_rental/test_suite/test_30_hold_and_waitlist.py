"""Maintenance holds demote overlapping pending requests to WAITLISTED, and the
waitlist promotion sweep runs when a blocking permit's interval frees
(PRD §3.1, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_renter_headers,
    make_booking_env, add_renter_with_insurance,
    make_draft_request, submit_request, begin_review,
    make_under_review_request, approve,
    create_request_payload,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestMaintenanceHold:
    def test_maintenance_hold_waitlists_overlapping_requests(self, api):
        """PRD §3.1: "Placing a facility on hold (`AVAILABLE` →
        `MAINTENANCE_HOLD`), with a `hold_reason` recorded, immediately demotes
        every pending request for that facility — those in `SUBMITTED`,
        `UNDER_REVIEW`, `REVISION_REQUESTED`, or `RESUBMITTED` — whose window
        overlaps the hold window to `WAITLISTED`, recorded with a hold reason of
        `MAINTENANCE`. Releasing the hold returns the facility to `AVAILABLE`;
        the waitlisted requests become eligible for re-review at the next
        conflict sweep but are not auto-approved."
        PRD §3.1: "Request creation, begin-review, and approval against a
        facility that is `MAINTENANCE_HOLD` or `RETIRED` are rejected with
        `ERR_FACILITY_NOT_AVAILABLE`."

        Design: Corner/endpoints/maintenance_hold_waitlists_overlapping_requests
        """
        env = make_booking_env()
        req = make_under_review_request(
            env, event_title="Auction", headcount_estimate=100,
            starts_at="2026-12-01T01:00:00Z", ends_at="2026-12-01T03:00:00Z")
        # A DRAFT request predating the hold (DRAFT is outside the demotion set).
        draft = make_draft_request(env, event_title="Later Event",
                                   headcount_estimate=50,
                                   starts_at="2026-12-02T01:00:00Z",
                                   ends_at="2026-12-02T03:00:00Z")

        held = validate_success(api.hold_facility(
            env["facility"]["id"], {"hold_reason": "Floor refinish"}, ADMIN))
        assert held["facility_status"] == "MAINTENANCE_HOLD"

        demoted = validate_success(api.get_request(req["id"], DIRECTOR))
        assert demoted["request_status"] == "WAITLISTED", (
            "the hold demotes the overlapping UNDER_REVIEW request")

        # While held: new requests and submissions are rejected at the
        # availability tier.
        create_res = api.create_request(
            env["org"]["id"],
            create_request_payload(env["facility"]["id"], event_title="Too Late",
                                   headcount_estimate=50,
                                   starts_at="2026-12-03T01:00:00Z",
                                   ends_at="2026-12-03T03:00:00Z"),
            make_renter_headers(env["org"]["id"]))
        validate_error(create_res, ApiErrorId.ERR_FACILITY_NOT_AVAILABLE)
        submit_res = api.submit_request(env["org"]["id"], draft["id"],
                                        make_renter_headers(env["org"]["id"]))
        validate_error(submit_res, ApiErrorId.ERR_FACILITY_NOT_AVAILABLE)

        released = validate_success(api.release_facility_hold(
            env["facility"]["id"], ADMIN))
        assert released["facility_status"] == "AVAILABLE"
        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["request_status"] == "WAITLISTED", (
            "hold release does not auto-approve: the request stays parked")


class TestWaitlistPromotion:
    def test_waitlist_promotion_on_permit_cancel(self, api):
        """PRD §3.4: "When a blocking permit is cancelled or superseded — or when
        a blocking calendar event is cancelled — a promotion sweep examines the
        freed interval. A `WAITLISTED` request is eligible for promotion only
        while no remaining `ISSUED` or `ACTIVE` permit blocks its window, its
        renter is in `GOOD_STANDING`, its headcount fits the facility's capacity,
        and the facility is `AVAILABLE`; the eligible candidate is promoted back
        to `UNDER_REVIEW`."
        PRD §3.4: "Approval also arbitrates the queue: any other request in
        `SUBMITTED`, `UNDER_REVIEW`, `RESUBMITTED`, or `WAITLISTED` whose window
        overlaps the new permit's blocked interval on the same facility and whose
        priority is lower is demoted (or kept) at `WAITLISTED`."

        Design: Corner/endpoints/waitlist_promotion_on_permit_cancel
        """
        env = make_booking_env(org_name="Renter One")
        org2, _ = add_renter_with_insurance("Renter Two")
        env2 = {**env, "org": org2}

        # Both requests are pending before any permit exists (a request whose
        # span collides with an issued permit's blocked interval cannot be
        # created or submitted — the parking lot fills via approval-time
        # arbitration, not after the fact).
        req1 = make_under_review_request(
            env, event_title="Blocker", headcount_estimate=100,
            starts_at="2026-12-01T01:00:00Z", ends_at="2026-12-01T03:00:00Z")
        req2 = make_under_review_request(
            env2, event_title="Hopeful", headcount_estimate=50,
            starts_at="2026-12-01T02:00:00Z", ends_at="2026-12-01T04:00:00Z")

        # Approving the earlier-submitted request issues its permit and demotes
        # the overlapping lower-priority one to WAITLISTED.
        permit1 = approve(req1["id"], req1["version"])
        parked = validate_success(api.get_request(req2["id"], DIRECTOR))
        assert parked["request_status"] == "WAITLISTED"

        cancelled = validate_success(api.cancel_permit(
            permit1["id"], {"cancellation_reason": "blocker withdrew"}, DIRECTOR))
        assert cancelled["lifecycle_status"] == "CANCELLED"

        promoted = validate_success(api.get_request(req2["id"], DIRECTOR))
        assert promoted["request_status"] == "UNDER_REVIEW", (
            "the promotion sweep restores the single eligible candidate")
