"""Depth-2 cascade from site closure: facilities retire, pending requests
withdraw (PRD §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error_is_one_of,
    make_renter_headers,
    make_booking_env, make_draft_request, submit_request,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _site_with_pending_request(api):
    """Site + facility + policy + renter + one SUBMITTED request. No ISSUED/ACTIVE
    permits, so the close precondition holds. The renter carries the default
    VALID certificate: submission passes the §3.3 insurance hard gate
    (headcount 200 -> tier 2 floors 200000000/400000000, covered through
    2026-12-05)."""
    env = make_booking_env()
    req = make_draft_request(env, event_title="Winter Fair", headcount_estimate=200,
                             starts_at="2026-12-05T17:00:00Z",
                             ends_at="2026-12-05T21:00:00Z")
    submit_request(env, req["id"])
    return env, req


class TestSiteCloseCascade:
    def test_site_close_retires_facilities_and_withdraws_requests(self, api):
        """PRD §3.1: "Closing a site is a one-way, terminal decision (`ACTIVE` →
        `CLOSED`): it is refused while any permit on any facility of the site
        remains `ISSUED` or `ACTIVE`, and when it succeeds the system withdraws
        every not-yet-decided rental request — any request in `DRAFT`, `SUBMITTED`,
        `UNDER_REVIEW`, `REVISION_REQUESTED`, `RESUBMITTED`, or `WAITLISTED` — that
        targets a facility of the site, and retires every facility of the site."

        Design: Difficulty/transitive_cascade/site_close_to_facility_retire_to_request_withdrawal_depth2
        """
        env, req = _site_with_pending_request(api)
        site = validate_success(api.close_site(env["site"]["id"], {}, ADMIN))
        assert site["site_status"] == "CLOSED"

        # Hop 1: the facility retires (caused by the site-close cascade).
        facility = validate_success(api.get_facility(env["facility"]["id"], ADMIN))
        assert facility["facility_status"] == "RETIRED"
        # Hop 2: the pending request withdraws (caused by the facility/site
        # cascade, not by a direct call on the request).
        request = validate_success(api.get_request(req["id"], ADMIN))
        assert request["request_status"] == "WITHDRAWN"

    def test_closed_site_rejects_new_request_against_retired_facility(self, api):
        """PRD §3.1: "Request creation, begin-review, and approval against a
        facility that is `MAINTENANCE_HOLD` or `RETIRED` are rejected with
        `ERR_FACILITY_NOT_AVAILABLE`."
        PRD §3.1: "From then on, a `CLOSED` site rejects new requests, new
        calendar events, and new facilities with `ERR_SITE_CLOSED`."

        Design: Difficulty/transitive_cascade/site_close_to_facility_retire_to_request_withdrawal_depth2
        """
        env, req = _site_with_pending_request(api)
        validate_success(api.close_site(env["site"]["id"], {}, ADMIN))

        org_id = env["org"]["id"]
        res = api.create_request(
            org_id,
            {"facility_id": env["facility"]["id"], "event_title": "Too Late",
             "headcount_estimate": 50, "starts_at": "2026-12-12T01:00:00Z",
             "ends_at": "2026-12-12T03:00:00Z"},
            make_renter_headers(org_id))
        # The facility is RETIRED and its site is CLOSED; the availability tier
        # rejects the create under either site-level or facility-level wording.
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_FACILITY_NOT_AVAILABLE, ApiErrorId.ERR_SITE_CLOSED])
