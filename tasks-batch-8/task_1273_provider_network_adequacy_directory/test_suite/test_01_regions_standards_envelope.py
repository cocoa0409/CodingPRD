"""Entity creation, defaults, 404s, pagination envelope, uniqueness, standard/location OCC."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    assert_region, assert_standard, assert_location, assert_provider, assert_listing,
    create_region_payload, create_standard_payload, create_provider_payload,
    create_location_payload, create_listing_payload, create_member_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing,
)

NM = TEST_USERS["network_manager_headers"]


class TestEntityCreation:
    def test_region_creation_persists_all_fields(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §4: "New-resource creation returns HTTP 201; modifications, transitions,
        and reads return HTTP 200."
        PRD §3.1: "Each region carries a unique `county_fips`, a display `name`, a
        `geo_class` of `URBAN`, `SUBURBAN`, or `RURAL` (which selects which
        `NetworkStandard` row applies to listings in this region), and an
        `enrolled_member_count` snapshot that is the numerator source for the
        adequacy ratio."

        Design: Corner/entities/region_creation_persists_all_fields
        """
        set_clock("2026-05-01T00:00:00Z")
        payload = create_region_payload(county_fips="06045", name="Orange",
                                        geo_class="SUBURBAN", enrolled_member_count=777)
        resp = api.create_region(payload, NM)
        data = validate_success(resp, expected_status=201)
        assert_region(data)
        assert data["county_fips"] == "06045"
        assert data["name"] == "Orange"
        assert data["geo_class"] == "SUBURBAN"
        assert data["enrolled_member_count"] == 777
        fetched = validate_success(api.get_region(data["id"], NM))
        for field in ("county_fips", "name", "geo_class", "enrolled_member_count", "version"):
            assert fetched[field] == data[field], f"GET echo mismatch on {field}"

    def test_location_panel_status_defaults_to_open(self, api):
        """PRD §3.1: "Creating one requires `provider_id`, `region_id`, `address_line`,
        `avg_travel_minutes`, and `avg_travel_miles`; `panel_status` defaults to `OPEN`
        but may be set to `CLOSED` at create time."

        Design: Corner/entities/location_panel_status_defaults_to_open
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06047", name="Placer")
        provider = create_provider(legal_name="P31", specialty="PRIMARY_CARE")
        resp = api.create_location(
            create_location_payload(provider["id"], region["id"],
                                    address_line="31 First St",
                                    avg_travel_minutes=8, avg_travel_miles=4),
            NM,
        )
        data = validate_success(resp, expected_status=201)
        assert_location(data)
        assert data["panel_status"] == "OPEN", "omitted panel_status must default to OPEN"

    def test_provider_future_effective_date_starts_pending_load(self, api):
        """PRD §3.1: "If the current logical clock date is at or past
        `contract_effective_date`, the new provider's `status` is immediately
        `EFFECTIVE`; otherwise the provider is held at `PENDING_LOAD` until a future
        clock advance sweeps it forward."

        Design: Corner/entities/provider_future_effective_date_starts_pending_load
        """
        set_clock("2026-05-01T00:00:00Z")
        future = validate_success(api.create_provider(
            create_provider_payload(legal_name="Future P", specialty="PRIMARY_CARE",
                                    contract_effective_date="2026-09-01"), NM),
            expected_status=201)
        now = validate_success(api.create_provider(
            create_provider_payload(legal_name="Now P", specialty="PRIMARY_CARE",
                                    contract_effective_date="2026-05-01"), NM),
            expected_status=201)
        assert_provider(future)
        assert_provider(now)
        assert future["status"] == "PENDING_LOAD"
        assert now["status"] == "EFFECTIVE", "clock date == contract date is the inclusive boundary"

    def test_listing_computed_fields_initialized_on_create(self, api):
        """PRD §3.2: "Creating one requires `provider_id`, `location_id`, `specialty`,
        `display_name`, `phone`, and `accepts_new_patients`; `office_hours_note` is
        optional. The listing is born in `DRAFT`."
        PRD §3.5: "The recomputation replays this listing's `RECORDED` probes in
        chronological order by `recorded_at` ascending (ties broken by `created_at`
        ascending), walking a running count that resets to 0 on every `PASS` and
        increments by 1 on every `FAIL`; the value after the newest probe is the new
        `ghost_strike_count`."
        PRD §3.2: "Every successful reinstate clears `suppress_reason` back to `NONE`."

        Design: Corner/entities/listing_computed_fields_initialized_on_create
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06049", name="Plumas")
        provider = create_provider(legal_name="P35")
        location = create_location(provider["id"], region["id"], address_line="35 Second St")
        resp = api.create_listing(
            create_listing_payload(provider["id"], location["id"], display_name="L35",
                                   phone="555-0135"),
            NM,
        )
        data = validate_success(resp, expected_status=201)
        assert_listing(data)
        assert data["status"] == "DRAFT"
        assert data["ghost_strike_count"] == 0
        assert data["suppress_reason"] == "NONE"
        assert data["has_confirmed_data_error"] is False


class TestNotFound:
    def test_listing_get_nonexistent_id_returns_not_found(self, api):
        """PRD §2.7: "Next, path and body-referenced identifiers are resolved
        left-to-right (`ERR_REGION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`,
        `ERR_PROVIDER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ATTESTATION_RECORD_NOT_FOUND`,
        `ERR_PROBE_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`,
        `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_CORRECTION_NOT_FOUND`)."

        Design: Corner/entities/listing_get_nonexistent_id_returns_not_found
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_listing("00000000-0000-4000-8000-000000000000", NM)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND)

    def test_region_get_nonexistent_id_returns_not_found(self, api):
        """PRD §2.7: "Next, path and body-referenced identifiers are resolved
        left-to-right (`ERR_REGION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`,
        `ERR_PROVIDER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ATTESTATION_RECORD_NOT_FOUND`,
        `ERR_PROBE_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`,
        `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_CORRECTION_NOT_FOUND`)."

        Design: Corner/entities/region_get_nonexistent_id_returns_not_found
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_region("00000000-0000-4000-8000-000000000001", NM)
        validate_error(resp, ApiErrorId.ERR_REGION_NOT_FOUND)

    def test_deficiency_get_nonexistent_id_returns_not_found(self, api):
        """PRD §2.7: "Next, path and body-referenced identifiers are resolved
        left-to-right (`ERR_REGION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`,
        `ERR_PROVIDER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ATTESTATION_RECORD_NOT_FOUND`,
        `ERR_PROBE_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`,
        `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_CORRECTION_NOT_FOUND`)."

        Design: Corner/entities/deficiency_get_nonexistent_id_returns_not_found
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_deficiency("00000000-0000-4000-8000-000000000002", NM)
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOT_FOUND)

    def test_correction_get_nonexistent_id_returns_not_found(self, api):
        """PRD §2.7: "Next, path and body-referenced identifiers are resolved
        left-to-right (`ERR_REGION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`,
        `ERR_PROVIDER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ATTESTATION_RECORD_NOT_FOUND`,
        `ERR_PROBE_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`,
        `ERR_ACCESS_PLAN_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_CORRECTION_NOT_FOUND`)."

        Design: Corner/entities/correction_get_nonexistent_id_returns_not_found
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_correction("00000000-0000-4000-8000-000000000003", NM)
        validate_error(resp, ApiErrorId.ERR_CORRECTION_NOT_FOUND)


class TestFilteredLists:
    def test_fk_reverse_listings_filtered_by_provider(self, api):
        """PRD §4: "GET /network/listings — List listings (filters: `provider_id`,
        `location_id`, `status`)".

        Design: Corner/entities/fk_reverse_listings_filtered_by_provider
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06053", name="Solano")
        p1 = create_provider(legal_name="P39")
        p2 = create_provider(legal_name="P40")
        l1 = create_location(p1["id"], region["id"], address_line="39 A St")
        l2 = create_location(p2["id"], region["id"], address_line="40 A St")
        s1 = create_listing(p1["id"], l1["id"], display_name="L39", phone="555-0139")
        s2 = create_listing(p2["id"], l2["id"], display_name="L40", phone="555-0140")
        data, meta = validate_paginated(api.list_listings(NM, params={"provider_id": p1["id"]}))
        assert len(data) == 1, f"expected exactly one listing for provider 1, got {len(data)}"
        assert data[0]["id"] == s1["id"]
        assert data[0]["id"] != s2["id"], "provider 2's listing leaked into the filter"


class TestPaginationEnvelope:
    def test_list_pagination_defaults_and_envelope_shape(self, api):
        """PRD §2.3: "List endpoints accept optional `limit` and `offset` query
        parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100.
        `offset` defaults to 0."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope_shape
        """
        set_clock("2026-05-01T00:00:00Z")
        for i in range(11):
            create_region(county_fips=f"070{i + 1:02d}", name=f"R{i + 1:02d}",
                          enrolled_member_count=1)
        resp1 = api.list_regions(NM)
        data1, meta1 = validate_paginated(resp1)
        body1 = resp1.json()
        assert body1["response_type"] == "array"
        assert isinstance(body1["meta"].get("api_request_id"), str)
        assert body1["meta"]["api_request_id"].startswith("req_")
        assert len(data1) == 10, f"default limit must be 10, got {len(data1)}"
        assert meta1["limit"] == 10
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        data2, meta2 = validate_paginated(api.list_regions(NM, params={"offset": 10}))
        assert len(data2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False


class TestUniqueness:
    def test_duplicate_standard_pair_rejected(self, api):
        """PRD §3.1: "A duplicate `(specialty, geo_class)` pair is rejected with
        `ERR_STANDARD_DUPLICATE`."

        Design: Corner/validations/duplicate_standard_pair_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        dup = api.create_standard(create_standard_payload(
            specialty="CARDIOLOGY", geo_class="URBAN", max_members_per_provider=999,
            max_travel_minutes=1, max_travel_miles=1, max_wait_days_routine=1,
            max_wait_days_urgent=1), NM)
        validate_error(dup, ApiErrorId.ERR_STANDARD_DUPLICATE)
        other = api.create_standard(create_standard_payload(
            specialty="CARDIOLOGY", geo_class="RURAL", max_members_per_provider=999,
            max_travel_minutes=60, max_travel_miles=40, max_wait_days_routine=30,
            max_wait_days_urgent=5), NM)
        data = validate_success(other, expected_status=201)
        assert_standard(data)
        assert data["geo_class"] == "RURAL", "uniqueness is over the (specialty, geo_class) pair"

    def test_duplicate_npi_rejected(self, api):
        """PRD §3.1: "A `NetworkManager` loads a new provider with `npi` (unique, else
        `ERR_NPI_DUPLICATE`), `legal_name`, `specialty`, and `contract_effective_date`."

        Design: Corner/validations/duplicate_npi_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        create_provider(npi="1000000063", legal_name="P63", specialty="PRIMARY_CARE")
        resp = api.create_provider(create_provider_payload(
            npi="1000000063", legal_name="P63 Clone", specialty="CARDIOLOGY"), NM)
        validate_error(resp, ApiErrorId.ERR_NPI_DUPLICATE)

    def test_member_ref_and_region_fips_duplicates_rejected(self, api):
        """PRD §3.1: "Each region carries a unique `county_fips`, a display `name`, a
        `geo_class` of `URBAN`, `SUBURBAN`, or `RURAL` (which selects which
        `NetworkStandard` row applies to listings in this region), and an
        `enrolled_member_count` snapshot that is the numerator source for the adequacy
        ratio. A duplicate `county_fips` is rejected with `ERR_REGION_DUPLICATE`."
        PRD §3.9: "Members are enrolled into a region by a `NetworkManager` supplying
        `region_id`, `member_ref` (unique, else `ERR_MEMBER_REF_DUPLICATE`),
        `full_name`, and `enrolled_on`."

        Design: Corner/errors/member_ref_and_region_fips_duplicates_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06105", name="Napa2")
        validate_success(api.create_member(
            create_member_payload(region["id"], member_ref="M-9105",
                                  full_name="Kay Om", enrolled_on="2026-04-15"), NM),
            expected_status=201)
        dup_region = api.create_region(create_region_payload(
            county_fips="06105", name="Napa2-dup", geo_class="RURAL",
            enrolled_member_count=5), NM)
        validate_error(dup_region, ApiErrorId.ERR_REGION_DUPLICATE)
        dup_member = api.create_member(create_member_payload(
            region["id"], member_ref="M-9105", full_name="Kay Dup",
            enrolled_on="2026-04-16"), NM)
        validate_error(dup_member, ApiErrorId.ERR_MEMBER_REF_DUPLICATE)


class TestOccGuardedWrites:
    def test_occ_stale_standard_version_rejected(self, api):
        """PRD §2.6: "A request to update a `NetworkStandard` must carry
        `expected_standard_version` equal to that standard's current `version`; a
        mismatch is rejected with `ERR_STALE_STANDARD_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_standard_version_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        standard = create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        first = validate_success(api.update_standard(
            standard["id"],
            {"expected_standard_version": standard["version"], "max_members_per_provider": 1100},
            NM))
        assert first["version"] == standard["version"] + 1
        assert first["max_members_per_provider"] == 1100
        stale = api.update_standard(
            standard["id"],
            {"expected_standard_version": standard["version"], "max_members_per_provider": 1000},
            NM)
        validate_error(stale, ApiErrorId.ERR_STALE_STANDARD_VERSION)
        current = validate_success(api.get_standard(standard["id"], NM))
        assert current["max_members_per_provider"] == 1100, "stale write must not have applied"

    def test_occ_stale_location_version_rejected(self, api):
        """PRD §2.6: "A request to patch a `PracticeLocation` must carry
        `expected_location_version`; mismatch yields `ERR_STALE_LOCATION_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_location_version_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06119", name="Sonoma2")
        provider = create_provider(legal_name="P93", specialty="PRIMARY_CARE")
        location = create_location(provider["id"], region["id"], address_line="93 A St")
        first = validate_success(api.patch_location(
            location["id"],
            {"expected_location_version": location["version"], "panel_status": "CLOSED"},
            NM))
        assert first["version"] == location["version"] + 1
        assert first["panel_status"] == "CLOSED"
        stale = api.patch_location(
            location["id"],
            {"expected_location_version": location["version"], "panel_status": "OPEN"},
            NM)
        validate_error(stale, ApiErrorId.ERR_STALE_LOCATION_VERSION)
        current = validate_success(api.get_location(location["id"], NM))
        assert current["panel_status"] == "CLOSED", "stale write must not have applied"
