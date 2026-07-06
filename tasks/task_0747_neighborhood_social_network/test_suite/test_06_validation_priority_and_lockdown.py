"""Validation priority conflicts and EMERGENCY-lockdown gating."""
import pytest

from test_helpers import (
    get_success_data, validate_error,
    make_resident_headers, make_business_owner_headers, make_agency_officer_headers,
    setup_neighborhood_with_moderator,
    setup_business_owner_scaffold, setup_neighborhood_with_verified_residents,
    drive_neighborhood_to_emergency,
    create_verified_business, create_resident,
    create_neighborhood, set_clock, api_client, ADMIN,
    AGENCY_OFFICER_USER_ID,
)


class TestNotVerifiedBeatsEmergencyLockdownOnMarketplaceCreate:
    """Difficulty rule 5 pair 1 — priority conflict:
    ERR_NOT_VERIFIED_IN_NEIGHBORHOOD fires before ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN."""

    def test_unverified_resident_in_emergency_neighborhood_returns_not_verified(self, api):
        """PRD §2.6: "Next, on `POST /neighborhood/posts`, `POST
        /neighborhood/marketplace-listings`, `POST /neighborhood/incidents`,
        `POST /neighborhood/flag-reports`, `POST /neighborhood/businesses`,
        `POST /neighborhood/groups`, and `POST /neighborhood/events`, the
        acting resident must own a `ResidentMembership` row for the target
        neighborhood whose `status` equals `VERIFIED`; otherwise the request
        is rejected with `ERR_NOT_VERIFIED_IN_NEIGHBORHOOD` (HTTP 403)."
        PRD §2.6: "Next, when the target neighborhood's `safety_posture`
        equals `EMERGENCY`, the endpoint that starts a local ad targeting
        that neighborhood and the endpoint that creates a marketplace
        listing in that neighborhood are both rejected with
        `ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN` (HTTP 409); creating safety-
        category posts in that neighborhood remains allowed."

        Design: Difficulty/priority_pair_validation_conflict/not_verified_in_neighborhood_beats_emergency_lockdown_on_marketplace_create
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        reporter = residents[0]
        drive_neighborhood_to_emergency(n["id"], reporter["id"])
        # Register a new resident R6 who is PENDING (not yet verified).
        r6 = create_resident(n["id"], email="r6@x.com", display_name="R6",
                             home_address_line="30 A St")
        # Attempt POST /marketplace-listings as R6 -> two violations, but
        # ERR_NOT_VERIFIED_IN_NEIGHBORHOOD MUST fire first.
        from test_helpers import create_marketplace_listing_payload
        resp = api_client.create_marketplace_listing(
            create_marketplace_listing_payload(r6["id"], n["id"],
                                              title="chair", price_cents=1000,
                                              kind="FOR_SALE"),
            make_resident_headers(r6["id"]),
        )
        validate_error(resp, "ERR_NOT_VERIFIED_IN_NEIGHBORHOOD")

    def test_error_is_not_emergency_lockdown_despite_emergency_posture(self, api):
        """PRD §2.6: "Next, when the target neighborhood's `safety_posture`
        equals `EMERGENCY`, the endpoint that starts a local ad targeting
        that neighborhood and the endpoint that creates a marketplace
        listing in that neighborhood are both rejected with
        `ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN` (HTTP 409); creating safety-
        category posts in that neighborhood remains allowed."

        The two-rule precedence in PRD §2.6 places the VERIFIED-membership
        check strictly before the EMERGENCY-lockdown check.

        Design: Difficulty/priority_pair_validation_conflict/not_verified_in_neighborhood_beats_emergency_lockdown_on_marketplace_create
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        reporter = residents[0]
        drive_neighborhood_to_emergency(n["id"], reporter["id"])
        r6 = create_resident(n["id"], email="r7@x.com", display_name="R7",
                             home_address_line="31 A St")
        from test_helpers import create_marketplace_listing_payload
        resp = api_client.create_marketplace_listing(
            create_marketplace_listing_payload(r6["id"], n["id"]),
            make_resident_headers(r6["id"]),
        )
        # Not the lockdown error — the earlier check masks it.
        assert resp.status_code == 403, \
            f"Expected 403 for not-verified, got {resp.status_code}"
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_NOT_VERIFIED_IN_NEIGHBORHOOD", \
            f"Expected precedence-earlier error, got {body['data']['error_id']}"


class TestInvalidTimeWindowBeatsNoticeOverlap:
    """Difficulty rule 5 pair 2 — priority conflict on POST /civic-notices."""

    def test_invalid_window_beats_overlap_on_civic_notice_create(self, api):
        """PRD §2.6: "Temporal window checks follow. On `POST
        /neighborhood/civic-notices`, the server first checks that
        `effective_until` is strictly greater than `effective_from`
        (rejecting with `ERR_INVALID_TIME_WINDOW`, HTTP 422) and then that
        `effective_from` is at least the current logical clock (rejecting
        with `ERR_EFFECTIVE_FROM_IN_PAST`, HTTP 422)."
        PRD §2.6: "Constraint checks come next. On civic notice creation,
        the proposed half-open interval `[effective_from, effective_until)`
        must not overlap any `ACTIVE` or `SCHEDULED` `CivicNotice` on the
        same combination of `neighborhood_id` and `notice_kind`; a touching
        endpoint (where one notice's `effective_until` equals another's
        `effective_from`) does not count as overlap. A true overlap is
        rejected with `ERR_NOTICE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_time_window_beats_notice_overlap_on_civic_notice_create
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        # Pre-existing SCHEDULED POLICE notice spanning 2026-06-05..2026-06-10.
        from test_helpers import (
            create_civic_notice_payload,
        )
        get_success_data(api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-05T00:00:00Z",
                effective_until="2026-06-10T00:00:00Z", notice_kind="POLICE"),
            make_agency_officer_headers(AGENCY_OFFICER_USER_ID),
        ))
        set_clock("2026-06-06T00:00:00Z")
        # Propose a notice with effective_until == effective_from (invalid
        # window) AND overlapping the existing notice (overlap conflict).
        resp = api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-08T00:00:00Z",
                effective_until="2026-06-08T00:00:00Z", notice_kind="POLICE"),
            make_agency_officer_headers(AGENCY_OFFICER_USER_ID),
        )
        validate_error(resp, "ERR_INVALID_TIME_WINDOW")

    def test_error_is_not_overlap_when_window_ordering_is_invalid(self, api):
        """PRD §2.6: "the server first checks that `effective_until` is
        strictly greater than `effective_from` (rejecting with
        `ERR_INVALID_TIME_WINDOW`, HTTP 422) and then that `effective_from`
        is at least the current logical clock"

        Design: Difficulty/priority_pair_validation_conflict/invalid_time_window_beats_notice_overlap_on_civic_notice_create
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        from test_helpers import create_civic_notice_payload
        get_success_data(api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-05T00:00:00Z",
                effective_until="2026-06-10T00:00:00Z", notice_kind="POLICE"),
            make_agency_officer_headers(AGENCY_OFFICER_USER_ID),
        ))
        set_clock("2026-06-06T00:00:00Z")
        resp = api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-08T00:00:00Z",
                effective_until="2026-06-08T00:00:00Z", notice_kind="POLICE"),
            make_agency_officer_headers(AGENCY_OFFICER_USER_ID),
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INVALID_TIME_WINDOW"


class TestLocalAdStartRequiresNonEmergencyPosture:
    """Difficulty rule 7 — LocalAd start blocked when target posture=EMERGENCY."""

    def test_start_local_ad_in_emergency_neighborhood_returns_lockdown(self, api):
        """PRD §3.8: "Additionally, the start is refused when the
        `safety_posture` of any of the ad's `target_neighborhood_ids` equals
        `EMERGENCY`, blocking new ad activity in a neighborhood that is in
        the middle of a serious safety event"
        PRD §2.6: "Next, when the target neighborhood's `safety_posture`
        equals `EMERGENCY`, the endpoint that starts a local ad targeting
        that neighborhood and the endpoint that creates a marketplace
        listing in that neighborhood are both rejected with
        `ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN` (HTTP 409); creating safety-
        category posts in that neighborhood remains allowed."

        Design: Difficulty/cross_entity_state_dependency/local_ad_start_requires_neighborhood_not_emergency
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        # Create a DRAFT LocalAd (not started yet).
        from test_helpers import create_local_ad_payload
        ad = get_success_data(api_client.create_local_ad(
            create_local_ad_payload(biz["id"], [n["id"]]),
            make_business_owner_headers(biz["id"]),
        ))
        # Drive N1 to EMERGENCY.
        drive_neighborhood_to_emergency(n["id"], r["id"])
        # Attempt /start -> 409 ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN.
        resp = api_client.start_local_ad(ad["id"],
                                          make_business_owner_headers(biz["id"]))
        validate_error(resp, "ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN")

    def test_ad_state_remains_draft_after_lockdown_reject(self, api):
        """PRD §3.8: "The owner starts the ad, advancing it from `DRAFT` to
        `RUNNING`, on three conditions"

        A rejected start must leave the ad in DRAFT.

        Design: Difficulty/cross_entity_state_dependency/local_ad_start_requires_neighborhood_not_emergency
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        from test_helpers import create_local_ad_payload
        ad = get_success_data(api_client.create_local_ad(
            create_local_ad_payload(biz["id"], [n["id"]]),
            make_business_owner_headers(biz["id"]),
        ))
        drive_neighborhood_to_emergency(n["id"], r["id"])
        api_client.start_local_ad(ad["id"], make_business_owner_headers(biz["id"]))
        ad_final = get_success_data(api_client.get_local_ad(ad["id"],
                                                             make_business_owner_headers(biz["id"])))
        assert ad_final["state"] == "DRAFT", \
            f"Ad state must remain DRAFT after rejected start, got {ad_final['state']}"


class TestLocalAdBudgetBelowMinimum:
    """Corner: budget_cents < 1000 -> ERR_INVALID_BUDGET."""

    def test_budget_below_1000_returns_invalid_budget(self, api):
        """PRD §2.6: "Local-ad creation requires that `budget_cents` be at
        least 1000 and `bid_cents_per_impression` be at least 1, otherwise
        `ERR_INVALID_BUDGET` (HTTP 422)."

        Design: Corner/validations/local_ad_budget_below_minimum_returns_invalid_budget
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        from test_helpers import create_local_ad_payload
        payload = create_local_ad_payload(biz["id"], [n["id"]],
                                          budget_cents=500,
                                          bid_cents_per_impression=100)
        resp = api_client.create_local_ad(payload,
                                           make_business_owner_headers(biz["id"]))
        validate_error(resp, "ERR_INVALID_BUDGET")


class TestReserveOwnMarketplaceListing:
    """Corner: seller reserving their own listing -> ERR_CANNOT_RESERVE_OWN."""

    def test_seller_reserving_own_listing_returns_cannot_reserve_own(self, api):
        """PRD §3.3: "The reservation records the acting resident's id in
        `reserved_for_resident_id` and sets `reserved_until` to the current
        logical clock plus 48 hours; a self-reservation (a seller reserving
        their own listing) is refused with `ERR_CANNOT_RESERVE_OWN`."
        PRD §2.6: "reserving a marketplace listing rejects a self-reservation
        (`reserved_for_resident_id` equal to `seller_resident_id`) with
        `ERR_CANNOT_RESERVE_OWN` (HTTP 409)."

        Design: Corner/validations/reserve_own_marketplace_listing_returns_cannot_reserve_own
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        r1 = residents[0]
        from test_helpers import create_marketplace_listing_payload
        listing = get_success_data(api_client.create_marketplace_listing(
            create_marketplace_listing_payload(r1["id"], n["id"]),
            make_resident_headers(r1["id"]),
        ))
        # Seller tries to reserve their own listing.
        resp = api_client.reserve_listing(listing["id"], make_resident_headers(r1["id"]))
        validate_error(resp, "ERR_CANNOT_RESERVE_OWN")
