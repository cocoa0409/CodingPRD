"""Corner tests: response envelope, defaults, listings, RBAC, marketplace,
LocalAd auto-end, clock startup default."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    make_resident_headers, make_business_owner_headers, make_agency_officer_headers,
    setup_neighborhood_with_verified_residents,
    setup_business_owner_scaffold, create_running_local_ad,
    create_neighborhood, create_resident,
    set_clock, api_client, ADMIN,
    AGENCY_OFFICER_USER_ID,
)


class TestResponseEnvelope:
    """Corner: successful responses carry meta.api_request_id + timestamp."""

    def test_response_envelope_contains_meta_and_response_type(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO
        8601 UTC timestamp with three fractional digits."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_meta_contains_api_request_id_and_timestamp
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api_client.get_clock(ADMIN)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_"), \
            f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
        assert body["response_type"] == "object"
        # Timestamp: use is_iso8601 to check.
        from test_helpers import is_iso8601_timestamp
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestClockStartupDefault:
    """Corner: default logical clock is 2026-03-01T00:00:00Z before any set."""

    def test_clock_now_returns_default_before_any_set(self, api):
        """PRD §2.10: "The clock starts at `2026-03-01T00:00:00Z` on server
        boot before any clock advance has been issued; this default is fixed
        and does not fall back to wall-clock time."

        Design: Corner/endpoints/clock_default_startup_time_before_first_set

        The PRD names the temporal *value* (2026-03-01T00:00:00Z) but is
        silent on the clock endpoint's wire format (§2.4's three-fractional-
        digits rule is scoped to entity-common `created_at`/`updated_at`, not
        this scalar). Per PARTIAL COVERAGE HANDLING we keep the covered
        assertion — the moment-in-time equals the declared default — and parse
        both sides to normalize away the format-silence.
        """
        from datetime import datetime, timezone

        def _parse(ts: str) -> datetime:
            txt = ts.strip()
            if txt.endswith("Z"):
                txt = txt[:-1] + "+00:00"
            return datetime.fromisoformat(txt).astimezone(timezone.utc)

        # DO NOT set the clock first — this is the fresh-boot assertion.
        resp = api_client.get_clock(ADMIN)
        data = validate_success(resp, expected_status=200)
        assert _parse(data["current_utc"]) == _parse("2026-03-01T00:00:00Z"), \
            f"Expected default clock 2026-03-01T00:00:00Z, got {data['current_utc']}"


class TestNeighborhoodDefaults:
    """Corner: resident create sets trust_score=100, is_moderator=false, etc."""

    def test_new_resident_defaults(self, api):
        """PRD §3.1: "On success, the resident is stored with
        `is_moderator=false`, `trust_score=100`,
        `verification_status=PENDING`, and `is_suspended=false`"

        Design: Corner/entities/resident_create_sets_default_trust_score_100_and_is_moderator_false
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        r = create_resident(n["id"], email="r@x.com", display_name="R",
                            home_address_line="1 A St")
        assert r["trust_score"] == 100
        assert r["is_moderator"] is False
        assert r["is_suspended"] is False
        assert r["verification_status"] == "PENDING"


class TestNeighborhoodMissingRequiredField:
    """Corner: POST /neighborhoods without state_code -> ERR_INVALID_REQUEST."""

    def test_neighborhood_missing_state_code_returns_400(self, api):
        """PRD §2.6: "Finally, `ERR_INVALID_REQUEST` (HTTP 400) is the
        catch-all for any payload that fails schema conformance — missing
        required fields, wrong types, unknown fields, or out-of-enum values
        — evaluated last so that a more specific business error is preferred
        whenever both apply."

        Design: Corner/entities/neighborhood_create_missing_required_state_code_returns_invalid_request
        """
        set_clock("2026-06-01T00:00:00Z")
        # Omit state_code.
        payload = {
            "name": "N1",
            "center_lat": 37.75,
            "center_lng": -122.42,
            "radius_meters": 2000,
        }
        resp = api_client.create_neighborhood(payload, ADMIN)
        validate_error(resp, "ERR_INVALID_REQUEST")


class TestNeighborhoodNotFound:
    """Corner: GET /neighborhoods/{unknown} -> ERR_NOT_FOUND."""

    def test_get_neighborhood_by_unknown_id_returns_404(self, api):
        """PRD §2.5: "Endpoints whose URL contains multiple path-templated
        identifiers validate each identifier in left-to-right order,
        rejecting the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to a live row."

        Design: Corner/entities/get_neighborhood_by_non_existent_id_returns_not_found
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api_client.get_neighborhood(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, "ERR_NOT_FOUND")


class TestNeighborhoodListPaginationDefaults:
    """Corner: default pagination — limit=10, offset=0, meta populated."""

    def test_neighborhoods_list_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned
        rows; it defaults to 10 when omitted, and must be at least 1 and no
        greater than 100 when provided. The `offset` parameter names the
        number of rows to skip and defaults to 0."
        PRD §2.3: "the `meta` object of the response envelope carries
        `limit`, `offset`, `total_count`, and `has_more` alongside the
        request identifiers."

        Design: Corner/entities/neighborhood_list_pagination_defaults_apply
        """
        set_clock("2026-06-01T00:00:00Z")
        create_neighborhood()
        resp = api_client.list_neighborhoods(ADMIN)
        rows, meta = validate_paginated(resp)
        assert meta.get("limit") == 10
        assert meta.get("offset") == 0
        assert meta.get("total_count", 0) >= 1
        assert meta.get("has_more") is False


class TestResidentCannotCreateCivicNotice:
    """Corner: /civic-notices is AgencyOfficer-exclusive."""

    def test_resident_civic_notice_returns_forbidden(self, api):
        """PRD §2.1: "Once authenticated, a role that is not permitted for
        the specific endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/resident_cannot_create_civic_notice_forbidden
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        r = residents[0]
        from test_helpers import create_civic_notice_payload
        resp = api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-10T00:00:00Z",
                effective_until="2026-06-15T00:00:00Z", notice_kind="POLICE"),
            make_resident_headers(r["id"]),
        )
        validate_error(resp, "ERR_FORBIDDEN")


class TestMissingXUserIdReturnsUnauthenticated:
    """Corner: missing headers -> ERR_UNAUTHENTICATED."""

    def test_missing_headers_returns_401(self, api):
        """PRD §2.1: "If either header is missing, malformed, or its value
        is not one of the six declared role names, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_x_user_id_returns_unauthenticated
        """
        # No headers at all.
        resp = api_client.create_neighborhood(
            {"name": "N1", "state_code": "CA", "center_lat": 37.75,
             "center_lng": -122.42, "radius_meters": 2000},
            {},
        )
        validate_error(resp, "ERR_UNAUTHENTICATED")


class TestLocalAdAutoEndOnClockAdvance:
    """Corner: RUNNING LocalAd auto-transitions to ENDED at end_at."""

    def test_running_ad_ends_after_end_at(self, api):
        """PRD §2.10: "a `RUNNING` or `PAUSED` `LocalAd` whose `end_at` has
        been reached transitions to `ENDED`"

        Design: Corner/state_machines/local_ad_expires_on_clock_advance_running_to_ended
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        ad = create_running_local_ad(
            biz["id"], [n["id"]],
            budget_cents=5000, bid_cents_per_impression=100,
            start_at="2026-06-01T00:00:00Z",
            end_at="2026-06-10T00:00:00Z",
        )
        assert ad["state"] == "RUNNING"
        # Advance clock past end_at.
        set_clock("2026-06-11T00:00:00Z")
        ad_final = get_success_data(
            api_client.get_local_ad(ad["id"], make_business_owner_headers(biz["id"])))
        assert ad_final["state"] == "ENDED"


class TestMarketplaceReservationExpiresBack:
    """Corner: RESERVED listing auto-transitions to ACTIVE after reserved_until."""

    def test_reservation_expiry_returns_to_active_and_clears_pointer(self, api):
        """PRD §3.3: "If the logical clock reaches `reserved_until` before
        the seller confirms the sale, the system auto-transitions the
        listing from `RESERVED` back to `ACTIVE`, clearing both
        `reserved_for_resident_id` and `reserved_until`."

        Design: Corner/state_machines/marketplace_listing_reservation_expires_reserved_to_active
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(2)
        seller = residents[0]
        buyer = residents[1]
        from test_helpers import create_marketplace_listing_payload
        listing = get_success_data(api_client.create_marketplace_listing(
            create_marketplace_listing_payload(seller["id"], n["id"]),
            make_resident_headers(seller["id"]),
        ))
        # Buyer reserves.
        reserved = get_success_data(
            api_client.reserve_listing(listing["id"], make_resident_headers(buyer["id"])))
        assert reserved["state"] == "RESERVED"
        # Advance clock past 48h.
        set_clock("2026-06-05T00:00:00Z")
        listing_after = get_success_data(
            api_client.get_marketplace_listing(listing["id"], make_resident_headers(seller["id"])))
        assert listing_after["state"] == "ACTIVE", \
            f"Expected ACTIVE after reservation expiry, got {listing_after['state']}"
        assert listing_after.get("reserved_for_resident_id") in (None, ""), \
            "reserved_for_resident_id must be cleared on auto-transition"
