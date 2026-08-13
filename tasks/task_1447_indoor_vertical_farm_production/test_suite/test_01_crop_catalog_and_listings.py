"""Crop catalog creation, listing, pagination, and code uniqueness (PRD §2.2-2.5, §3.1-3.2, §3.8)."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    create_crop_payload, create_water_loop_payload, create_rack_payload,
    create_energy_reading_payload,
)

FM = TEST_USERS["farm_manager_headers"]
KALE = dict(crop_code="KALE-01", display_name="Kale", category="LEAFY_GREEN",
            margin_cents_per_lb=300, floor_price_cents_per_lb=100)
BASIL = dict(crop_code="BASIL-01", display_name="Basil", category="HERB",
             margin_cents_per_lb=500, floor_price_cents_per_lb=200)


class TestCropCreation:
    def test_create_crop_applies_system_defaults(self, api):
        """PRD §3.1: "A crop is born with `crop_status` `ACTIVE` and remains sellable
        until retired". PRD §2.5: "A unique, server-minted identifier formatted as a
        UUID, with no type prefix".

        Design: Corner/entities/create_crop_applies_defaults_and_system_fields
        """
        resp = api.create_crop(create_crop_payload(**KALE), FM)
        data = validate_success(resp, expected_status=201)
        assert data["crop_status"] == "ACTIVE", "new crop must be born ACTIVE"
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"]), "created_at must be present"
        assert isinstance(data["version"], int), "version must be a system-managed integer"

    def test_create_crop_missing_required_field_rejected(self, api):
        """PRD §2.10: "any request whose body is malformed, missing a required field,
        carrying an invalid enum value, a negative quantity, or an unknown field is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_crop_missing_required_field_rejected
        """
        payload = create_crop_payload(**KALE)
        del payload["margin_cents_per_lb"]
        resp = api.create_crop(payload, FM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_crops(FM))
        assert meta["total_count"] == 0, "rejected create must not persist a crop"

    def test_create_crop_invalid_enum_rejected(self, api):
        """PRD §3.1: "a `category` of `LEAFY_GREEN`, `HERB`, or `FRUITING`". PRD §2.10:
        "any request whose body is malformed, missing a required field, carrying an
        invalid enum value, a negative quantity, or an unknown field is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_crop_invalid_enum_rejected
        """
        resp = api.create_crop(create_crop_payload(crop_code="OAK-01", display_name="Oak",
                                                   category="TREE"), FM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_crop_duplicate_code_rejected(self, api):
        """PRD §3.1: "reusing an existing `crop_code` is rejected with
        `ERR_DUPLICATE_CODE`."

        Design: Corner/entities/create_crop_duplicate_code_rejected
        """
        validate_success(api.create_crop(create_crop_payload(**KALE), FM), expected_status=201)
        resp = api.create_crop(create_crop_payload(crop_code="KALE-01", display_name="Kale Again",
                                                   category="HERB"), FM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)

    def test_get_crop_not_found_returns_404(self, api):
        """PRD §2.10: "Path identifiers exist, validated left to right, and body
        foreign-key references exist (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_crop_not_found_returns_404
        """
        resp = api.get_crop("00000000-0000-4000-8000-000000000000", FM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRackTowerCreation:
    def test_rack_creation_autocreates_towers_with_indices(self, api):
        """PRD §3.2: "the server immediately creates that many **Tower** rows beneath the
        rack, each stamped with the owning rack's `rack_id` and numbered by `tower_index`
        from 1 through `tower_count`."

        Design: Corner/entities/rack_creation_autocreates_towers_with_indices
        """
        loop = validate_success(api.create_water_loop(create_water_loop_payload(loop_code="WL-A"), FM),
                                expected_status=201)
        rack = validate_success(
            api.create_rack(create_rack_payload(loop["id"], rack_code="R-01", tower_count=3), FM),
            expected_status=201,
        )
        towers, meta = validate_paginated(api.list_rack_towers(rack["id"], FM))
        assert len(towers) == 3 and meta["total_count"] == 3
        by_index = sorted(t["tower_index"] for t in towers)
        assert by_index == [1, 2, 3], "towers must be numbered 1..tower_count"
        for t in towers:
            assert t["rack_id"] == rack["id"], "each tower must reference the owning rack"
            assert t["tower_status"] == "IDLE", "a fresh tower has no active allocation"


class TestEnergyReadingShape:
    def test_energy_reading_has_no_version_or_updated_at(self, api):
        """PRD §2.5: "Because a meter reading is an append-only fact that is never
        modified after posting, an `EnergyMeterReading` carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from it."

        Design: Corner/entities/energy_reading_immutable_entity_has_no_version
        """
        resp = api.create_energy_reading(create_energy_reading_payload(), FM)
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert "version" not in data, "append-only reading must not carry version"
        assert "updated_at" not in data, "append-only reading must not carry updated_at"


class TestCropListing:
    def test_crop_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/crop_list_pagination_envelope
        """
        validate_success(api.create_crop(create_crop_payload(**KALE), FM), expected_status=201)
        validate_success(api.create_crop(create_crop_payload(**BASIL), FM), expected_status=201)

        page1, meta1 = validate_paginated(api.list_crops(FM, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2 and meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_crops(FM, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "pages must partition the list"

    def test_crop_filter_by_enum_listing(self, api):
        """PRD §3.1: "A successful retirement flips `crop_status` to `RETIRED`".
        PRD §4: GET /farm/crops accepts a `crop_status` filter.

        Design: Corner/entities/crop_filter_by_enum_listing
        """
        kale = validate_success(api.create_crop(create_crop_payload(**KALE), FM), expected_status=201)
        validate_success(api.create_crop(create_crop_payload(**BASIL), FM), expected_status=201)
        validate_success(api.retire_crop(kale["id"], FM))

        data, meta = validate_paginated(api.list_crops(FM, params={"crop_status": "RETIRED"}))
        assert meta["total_count"] == 1 and len(data) == 1
        assert data[0]["crop_code"] == "KALE-01"


class TestCodeUniqueness:
    def test_duplicate_rack_and_loop_codes_rejected(self, api):
        """PRD §3.2: "each created by a `FarmManager` with a unique `loop_code`
        (duplicates fail with `ERR_DUPLICATE_CODE`)" and racks carry "a unique
        `rack_code`". PRD §2.10 tier 10: "Commitment pools, dock quotas, headcount,
        weekly hours, stress caps, selector pools, code uniqueness, and queue
        singletons".

        Design: Corner/errors/duplicate_rack_and_loop_codes_rejected
        """
        loop = validate_success(api.create_water_loop(create_water_loop_payload(loop_code="WL-A"), FM),
                                expected_status=201)
        validate_success(
            api.create_rack(create_rack_payload(loop["id"], rack_code="R-01", tower_count=1), FM),
            expected_status=201,
        )
        resp_loop = api.create_water_loop(create_water_loop_payload(loop_code="WL-A"), FM)
        validate_error(resp_loop, ApiErrorId.ERR_DUPLICATE_CODE)
        resp_rack = api.create_rack(
            create_rack_payload(loop["id"], rack_code="R-01", zone="Z2", tower_count=1), FM,
        )
        validate_error(resp_rack, ApiErrorId.ERR_DUPLICATE_CODE)
