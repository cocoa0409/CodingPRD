"""Site closure locks out new activity, and referential-integrity failures
surface as ERR_REFERENCE_INVALID / ERR_RENEWAL_NOT_RENEWABLE
(PRD §2.9, §3.1, §3.2, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    make_renter_headers,
    make_site, make_facility, make_policy, make_renter, make_insurance,
    make_booking_env,
    create_facility_payload, create_calendar_event_payload,
    create_request_payload, create_seasonal_permit_payload,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestSiteClosedRejectsNewActivity:
    def test_site_closed_rejects_new_activity(self, api):
        """PRD §3.1: "Closing a site is a one-way, terminal decision (`ACTIVE` →
        `CLOSED`): it is refused while any permit on any facility of the site
        remains `ISSUED` or `ACTIVE`, and when it succeeds the system withdraws
        every not-yet-decided rental request — any request in `DRAFT`,
        `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `RESUBMITTED`, or
        `WAITLISTED` — that targets a facility of the site, and retires every
        facility of the site. From then on, a `CLOSED` site rejects new requests,
        new calendar events, and new facilities with `ERR_SITE_CLOSED`."

        Design: Corner/errors/site_closed_rejects_new_activity
        """
        site = make_site("RHS")
        facility = make_facility(site["id"])
        org = make_renter("Riverview PTA")

        closed = validate_success(api.close_site(site["id"], {}, ADMIN))
        assert closed["site_status"] == "CLOSED"

        new_facility = api.create_facility(
            site["id"],
            create_facility_payload(facility_code="AUD", facility_tier="PREMIUM",
                                    capacity=100),
            ADMIN)
        validate_error(new_facility, ApiErrorId.ERR_SITE_CLOSED)

        new_event = api.create_calendar_event(
            site["id"],
            create_calendar_event_payload(title="Event on closed site"),
            ADMIN)
        validate_error(new_event, ApiErrorId.ERR_SITE_CLOSED)

        new_request = api.create_request(
            org["id"],
            create_request_payload(facility["id"], event_title="Too Late",
                                   headcount_estimate=50,
                                   starts_at="2026-12-01T01:00:00Z",
                                   ends_at="2026-12-01T03:00:00Z"),
            make_renter_headers(org["id"]))
        validate_error(new_request, ApiErrorId.ERR_SITE_CLOSED)

        retired = validate_success(api.get_facility(facility["id"], ADMIN))
        assert retired["facility_status"] == "RETIRED", "close cascade retires facilities"


class TestReferentialIntegrity:
    def test_reference_invalid_on_stale_policy_and_bad_renewal(self, api):
        """PRD §2.9: "**Referential integrity.** Referenced objects must be valid
        in context — the facility belongs to an `ACTIVE` site, a pricing policy
        exists for the renter's rate class, the facility's tier, and the event
        start date, and a renewal source points to a real renewable series of the
        same renter — else `ERR_REFERENCE_INVALID` (HTTP 422). Applies to request
        creation, seasonal series creation, and approval."
        PRD §3.9: "The referenced series must belong to the same renter, must be
        a real series in `COMPLETED` or `ACTIVE` status, and must not already
        have been renewed by another series — violations are rejected with
        `ERR_RENEWAL_NOT_RENEWABLE`."

        Design: Corner/errors/reference_invalid_on_stale_policy_and_bad_renewal
        """
        # Only a NONPROFIT x STANDARD policy exists; nothing covers
        # (FOR_PROFIT, STANDARD).
        env = make_booking_env()
        org_fp = make_renter("Profit Co", rate_class="FOR_PROFIT")
        no_policy = api.create_request(
            org_fp["id"],
            create_request_payload(env["facility"]["id"],
                                   event_title="No Policy Event",
                                   headcount_estimate=50,
                                   starts_at="2026-12-01T01:00:00Z",
                                   ends_at="2026-12-01T03:00:00Z"),
            make_renter_headers(org_fp["id"]))
        validate_error(no_policy, ApiErrorId.ERR_REFERENCE_INVALID)

        # Renter A owns an active seasonal series on the gym.
        org_a = make_renter("Soccer A")
        make_insurance(org_a["id"])
        series_a = validate_success(api.create_seasonal_permit(
            create_seasonal_permit_payload(org_a["id"], env["facility"]["id"],
                                           series_name="A Series"),
            make_renter_headers(org_a["id"])), 201)
        series_a = validate_success(api.get_seasonal_permit(series_a["id"], DIRECTOR))

        # Renter B's renewal points at A's series: not the same renter. The
        # renewal-linkage rule names ERR_RENEWAL_NOT_RENEWABLE; the pipeline's
        # referential-integrity tier also claims the same-renter check under
        # ERR_REFERENCE_INVALID — both reject the cross-renter renewal at 422.
        org_b = make_renter("Soccer B")
        bad_renewal = api.create_seasonal_permit(
            create_seasonal_permit_payload(
                org_b["id"], env["facility"]["id"],
                series_name="B Renewal of A",
                season_start="2026-11-07T00:00:00Z",
                season_end="2026-12-05T00:00:00Z",
                renewed_from_id=series_a["id"],
                expected_series_version=series_a["version"]),
            DIRECTOR)
        validate_error_is_one_of(bad_renewal, [
            ApiErrorId.ERR_RENEWAL_NOT_RENEWABLE,
            ApiErrorId.ERR_REFERENCE_INVALID,
        ])
