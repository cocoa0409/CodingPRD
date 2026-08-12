"""Listing publish gates, suppress/reinstate cycle, listing OCC (PRD §3.2)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_standard_payload, create_provider_payload, create_location_payload,
    create_listing_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, get_listing, setup_listed_network,
)

NM = TEST_USERS["network_manager_headers"]


def _setup_suspended_derm_listing_without_standard():
    """Provider SUSPENDED; DRAFT DERMATOLOGY listing; NO DERMATOLOGY standard exists."""
    set_clock("2026-05-01T00:00:00Z")
    region = create_region(county_fips="06021", name="Kings")
    provider = create_provider(legal_name="Derm Thirteen", specialty="DERMATOLOGY")
    location = create_location(provider["id"], region["id"], address_line="17 Fig St",
                               avg_travel_minutes=20, avg_travel_miles=10)
    listing = create_listing(provider["id"], location["id"], specialty="DERMATOLOGY",
                             display_name="Derm 13", phone="555-0113")
    validate_success(api_client.patch_provider(provider["id"], {"to_status": "SUSPENDED"}, NM))
    return {"region": region, "provider": provider, "location": location, "listing": listing}


class TestPublishPriorityStateBeatsReferential:
    def test_publish_blocked_by_provider_state_even_when_standard_missing(self, api):
        """PRD §3.2: "First, the provider must be `EFFECTIVE`
        (`ERR_PROVIDER_NOT_EFFECTIVE`) — this check runs before the referential checks
        so a not-yet-effective provider surfaces its own error rather than being masked
        by a location mismatch."

        Design: Difficulty/priority_pair_validation_conflict/publish_state_error_beats_referential_error
        """
        ctx = _setup_suspended_derm_listing_without_standard()
        resp = api.publish_listing(ctx["listing"]["id"], NM)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_EFFECTIVE)
        assert resp.status_code == 409, (
            "state error (409) must beat the referential standard-miss (422)")

    def test_publish_blocked_by_provider_state_even_when_standard_present(self, api):
        """PRD §3.2: "First, the provider must be `EFFECTIVE`
        (`ERR_PROVIDER_NOT_EFFECTIVE`) — this check runs before the referential checks
        so a not-yet-effective provider surfaces its own error rather than being masked
        by a location mismatch."

        Design: Difficulty/priority_pair_validation_conflict/publish_state_error_beats_referential_error
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06022", name="Kings B")
        create_standard(specialty="DERMATOLOGY", geo_class="URBAN",
                        max_members_per_provider=15000, max_travel_minutes=45,
                        max_travel_miles=30, max_wait_days_routine=20,
                        max_wait_days_urgent=3)
        provider = create_provider(legal_name="Derm Thirteen B", specialty="DERMATOLOGY")
        location = create_location(provider["id"], region["id"], address_line="18 Fig St")
        listing = create_listing(provider["id"], location["id"], specialty="DERMATOLOGY",
                                 display_name="Derm 13B", phone="555-0114")
        validate_success(api.patch_provider(provider["id"], {"to_status": "SUSPENDED"}, NM))
        resp = api.publish_listing(listing["id"], NM)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_EFFECTIVE)


class TestPublishRequiresProviderEffective:
    def _setup_pending_provider_listing(self):
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06033", name="Mendocino")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        provider = create_provider(legal_name="Heart 25", contract_effective_date="2026-06-01")
        location = create_location(provider["id"], region["id"], address_line="25 Main St")
        listing = create_listing(provider["id"], location["id"], display_name="Heart 25",
                                 phone="555-0125")
        return {"region": region, "provider": provider, "location": location,
                "listing": listing}

    def test_pending_load_provider_blocks_publish(self, api):
        """PRD §3.1: "otherwise the provider is held at `PENDING_LOAD` until a future
        clock advance sweeps it forward."
        PRD §3.2: "First, the provider must be `EFFECTIVE`
        (`ERR_PROVIDER_NOT_EFFECTIVE`) — this check runs before the referential checks
        so a not-yet-effective provider surfaces its own error rather than being masked
        by a location mismatch."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_provider_effective
        """
        ctx = self._setup_pending_provider_listing()
        assert ctx["provider"]["status"] == "PENDING_LOAD"
        resp = api.publish_listing(ctx["listing"]["id"], NM)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_EFFECTIVE)

    def test_clock_sweep_effectuates_provider_and_publish_succeeds(self, api):
        """PRD §3.1: "The sweep runs as a side effect of the administrative clock-set
        capability: any provider in `PENDING_LOAD` whose `contract_effective_date` is at
        or before the new clock date transitions to `EFFECTIVE`, and each effectuated
        provider's `version` increments by 1."
        PRD §3.2: "On success the listing's `listed_at` is stamped with the current
        clock and `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_provider_effective
        """
        ctx = self._setup_pending_provider_listing()
        sweep = validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, NM))
        assert ctx["provider"]["id"] in sweep["effectuated_provider_ids"]
        published = validate_success(api.publish_listing(ctx["listing"]["id"], NM))
        assert published["status"] == "LISTED"
        assert published["listed_at"] is not None
        assert published["version"] == ctx["listing"]["version"] + 1


class TestListingSuppressReinstateCycle:
    def _setup(self):
        return setup_listed_network(county_fips="06015", enrolled_member_count=100,
                                    listing_overrides={"display_name": "Heart Nine",
                                                       "phone": "555-0109"})

    def test_manual_suppress_stamps_reason_and_suppressed_at(self, api):
        """PRD §3.2: "From `LISTED`, a listing may be manually suppressed (transition
        to `SUPPRESSED` with `suppress_reason` = `MANUAL`) or may transition to
        `UNDER_REVIEW` automatically when the ghost-strike rule fires (see §3.5)."

        Design: Difficulty/non_linear_state_machine/listing_suppress_reinstate_cycle
        """
        ctx = self._setup()
        listing = ctx["listing"]
        suppressed = validate_success(api.patch_listing(
            listing["id"],
            {"expected_listing_version": listing["version"], "to_status": "SUPPRESSED",
             "suppress_reason": "MANUAL"}, NM))
        assert suppressed["status"] == "SUPPRESSED"
        assert suppressed["suppress_reason"] == "MANUAL"
        assert suppressed["suppressed_at"] is not None

    def test_reinstate_restores_listed_and_clears_reason(self, api):
        """PRD §3.2: "A listing suppressed for `MANUAL` reasons may be reinstated
        directly."
        PRD §3.2: "Every successful reinstate clears `suppress_reason` back to `NONE`."

        Design: Difficulty/non_linear_state_machine/listing_suppress_reinstate_cycle
        """
        ctx = self._setup()
        listing = ctx["listing"]
        suppressed = validate_success(api.patch_listing(
            listing["id"],
            {"expected_listing_version": listing["version"], "to_status": "SUPPRESSED",
             "suppress_reason": "MANUAL"}, NM))
        reinstated = validate_success(api.patch_listing(
            listing["id"],
            {"expected_listing_version": suppressed["version"], "to_status": "LISTED"}, NM))
        assert reinstated["status"] == "LISTED"
        assert reinstated["suppress_reason"] == "NONE"
        assert reinstated["ghost_strike_count"] == 0
        data, _meta = validate_paginated(api.list_listings(
            NM, params={"provider_id": ctx["provider"]["id"], "status": "LISTED"}))
        assert len(data) == 1, "reinstated listing must reappear in the LISTED filter"
        assert data[0]["id"] == listing["id"]


class TestPublishGuards:
    def test_publish_on_already_listed_listing_rejected(self, api):
        """PRD §3.2: "Publishing a listing (transitioning `DRAFT` → `LISTED`) enforces
        four checks in order."
        PRD §2.7: "After all referents exist, state-machine preconditions evaluate (the
        various `ERR_*_INVALID_*`, `ERR_*_NOT_*` 409 codes)."

        Design: Corner/state_machines/publish_on_already_listed_listing_rejected
        """
        ctx = setup_listed_network(county_fips="06055", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L43",
                                                      "phone": "555-0143"})
        resp = api.publish_listing(ctx["listing"]["id"], NM)
        validate_error(resp, ApiErrorId.ERR_LISTING_INVALID_TRANSITION)

    def test_publish_duplicate_listed_listing_same_location_specialty_rejected(self, api):
        """PRD §3.2: "Fourth, no other listing may already be `LISTED` for the same
        `(location_id, specialty)` (`ERR_LISTING_ALREADY_LISTED`)."

        Design: Corner/validations/publish_duplicate_listed_listing_same_location_specialty_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06079", name="Colusa2")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        provider = create_provider(legal_name="P67")
        location = create_location(provider["id"], region["id"], address_line="67 A St")
        l1 = create_listing(provider["id"], location["id"], display_name="First",
                            phone="555-0167")
        l2 = create_listing(provider["id"], location["id"], display_name="Second",
                            phone="555-0168")
        publish_listing(l1["id"])
        resp = api.publish_listing(l2["id"], NM)
        validate_error(resp, ApiErrorId.ERR_LISTING_ALREADY_LISTED)

    def test_publish_without_applicable_standard_rejected(self, api):
        """PRD §3.2: "Third, a `NetworkStandard` must exist for `(listing.specialty,
        location.region.geo_class)` (`ERR_SPECIALTY_STANDARD_MISSING`) — without a
        standard there is no adequacy ceiling to measure this listing against."

        Design: Corner/validations/publish_without_applicable_standard_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06085", name="Inyo")
        provider = create_provider(legal_name="P73", specialty="DERMATOLOGY")
        location = create_location(provider["id"], region["id"], address_line="73 A St")
        listing = create_listing(provider["id"], location["id"], specialty="DERMATOLOGY",
                                 display_name="D73", phone="555-0173")
        resp = api.publish_listing(listing["id"], NM)
        validate_error(resp, ApiErrorId.ERR_SPECIALTY_STANDARD_MISSING)

    def test_occ_stale_listing_version_rejected(self, api):
        """PRD §2.6: "A request to patch a `DirectoryListing` (any `to_status`
        transition) must carry `expected_listing_version`; mismatch yields
        `ERR_STALE_LISTING_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_listing_version_rejected
        """
        ctx = setup_listed_network(county_fips="06121", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L95",
                                                      "phone": "555-0195"})
        listing = ctx["listing"]
        stale_version = listing["version"] - 1  # version captured before publish bumped it
        stale = api.patch_listing(
            listing["id"],
            {"expected_listing_version": stale_version, "to_status": "SUPPRESSED",
             "suppress_reason": "MANUAL"}, NM)
        validate_error(stale, ApiErrorId.ERR_STALE_LISTING_VERSION)
        fresh = get_listing(listing["id"])
        ok = validate_success(api.patch_listing(
            listing["id"],
            {"expected_listing_version": fresh["version"], "to_status": "SUPPRESSED",
             "suppress_reason": "MANUAL"}, NM))
        assert ok["status"] == "SUPPRESSED"
