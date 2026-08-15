"""Convention creation defaults, OCC config updates, and floor inventory."""
from test_helpers import (
    ApiErrorId,
    assert_category_quota,
    assert_dock_door,
    assert_exhibitor,
    assert_exhibitor_standing_consistent,
    assert_renewal_priority_score,
    assert_space_unit,
    create_convention,
    create_space_unit,
    register_exhibitor,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestConventionCreation:
    def test_convention_creation_applies_defaults_and_cascades(self, api, director_headers):
        """PRD §3.1: "Creating the convention cascade-creates one CategoryQuota
        per `category_quotas` entry and one DockDoor per `dock_doors` entry, and
        each door's `door_code` must be unique within the convention."
        PRD §3.1: "The optional `deposit_window_days` sets how many days an
        accepted exhibitor has to accept its offer and defaults to 14 when
        omitted. A new convention's `phase` opens at `SETUP`, with an
        `ops_run_count` of zero."

        Design: Corner/entities/convention_creation_applies_defaults_and_cascades
        """
        conv = create_convention()  # deposit_window_days omitted
        assert conv["phase"] == "SETUP"
        assert conv["deposit_window_days"] == 14
        assert conv["ops_run_count"] == 0
        assert conv["version"] >= 1

        quotas, q_meta = validate_paginated(
            api.list_category_quotas(
                director_headers, params={"convention_id": conv["id"]}
            )
        )
        assert q_meta["total_count"] == 2
        for quota in quotas:
            assert_category_quota(quota)
            assert quota["accepted_count"] == 0
            assert quota["waitlisted_count"] == 0
        assert {q["category"] for q in quotas} == {"ARTIST_ALLEY", "DEALER"}

        doors, d_meta = validate_paginated(
            api.list_dock_doors(director_headers, params={"convention_id": conv["id"]})
        )
        assert d_meta["total_count"] == 2
        for door in doors:
            assert_dock_door(door)
        # PRD §3.1 covers the cascade content (one DockDoor per entry), not the
        # list order among doors sharing an identical created_at — both cascade
        # rows are stamped by the same frozen logical clock, and §2.3's
        # "sorted by creation timestamp ascending" is tie-break-silent.
        assert {d["door_code"] for d in doors} == {"D1", "D2"}


class TestConventionOcc:
    def test_occ_stale_convention_version_rejected(self, api, director_headers):
        """PRD §2.7: "Updating a convention's configuration likewise requires
        `expected_convention_version`; a mismatch with the convention's current
        `version` is rejected with `ERR_STALE_CONVENTION_VERSION` (HTTP 412),
        preventing the request from silently overwriting configuration the
        client never saw."

        Design: Corner/cross_cutting_layers/occ_stale_convention_version_rejected
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        observed_version = conv["version"]

        first = api.update_convention(
            conv["id"],
            {"expected_convention_version": observed_version, "sales_tax_rate_bp": 900},
            director_headers,
        )
        updated = validate_success(first)
        assert updated["version"] == observed_version + 1
        assert updated["sales_tax_rate_bp"] == 900

        replay = api.update_convention(
            conv["id"],
            {"expected_convention_version": observed_version, "sales_tax_rate_bp": 950},
            director_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_CONVENTION_VERSION)

        current = validate_success(api.get_convention(conv["id"], director_headers))
        assert current["sales_tax_rate_bp"] == 900


class TestSpaceUnits:
    def test_space_unit_creation_and_retrieval(self, api, director_headers):
        """PRD §3.1: "New units start `AVAILABLE`."
        PRD §4: "Operations that create a new resource return a `201 Created`
        status code."

        Design: Corner/entities/space_unit_creation_and_retrieval
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        created = create_space_unit(conv["id"], space_code="A-101")
        assert_space_unit(created)
        assert created["status"] == "AVAILABLE"

        fetched = validate_success(api.get_space_unit(created["id"], director_headers))
        assert_space_unit(fetched)
        assert fetched["space_code"] == "A-101"
        assert fetched["version"] == created["version"]

    def test_space_unit_invalid_kind_enum_rejected(self, api, director_headers):
        """PRD §2.8: "Independent of this ordering, a body that is malformed — a
        missing required field, a wrong-typed value, an unknown enum value, or an
        integer outside its declared range, such as a `requested_space_count` or
        `pallet_count` below one, or a jury criterion outside zero to one hundred
        — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/space_unit_invalid_kind_enum_rejected
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        resp = api.create_space_unit(
            {
                "convention_id": conv["id"],
                "space_code": "X-1",
                "block": "X",
                "unit_number": 1,
                "hall": "MAIN",
                "kind": "MEGA_BOOTH",
                "base_price_cents": 100000,
            },
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_space_unit_create_system_fields_input_ignored(self, api, director_headers):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."
        PRD §3.1: "New units start `AVAILABLE`."

        Design: Corner/entities/space_unit_create_system_fields_input_ignored
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        supplied_id = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        resp = api.create_space_unit(
            {
                "convention_id": conv["id"],
                "space_code": "A-101",
                "block": "A",
                "unit_number": 101,
                "hall": "MAIN",
                "kind": "BOOTH_10X10",
                "base_price_cents": 100000,
                "id": supplied_id,
                "status": "RESERVED",
            },
            director_headers,
        )
        data = validate_success(resp, 201)
        assert data["id"] != supplied_id, "server must mint its own id"
        assert data["status"] == "AVAILABLE"

    def test_space_unit_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets how many items to skip and defaults to 0."

        Design: Corner/entities/space_unit_list_pagination_defaults
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        create_space_unit(conv["id"], space_code="A-101", unit_number=101)
        create_space_unit(conv["id"], space_code="A-102", unit_number=102)

        # Space-unit listing is public convention data (PRD §2.1); the
        # zero-UUID exhibitor exercises the role without any ownership scope.
        resp = api.list_space_units(
            TEST_USERS["exhibitor_headers"], params={"convention_id": conv["id"]}
        )
        units, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(units) == 2

    def test_duplicate_space_code_rejected(self, api, director_headers):
        """PRD §3.1: "Each SpaceUnit is created with its `convention_id`, a
        human-readable `space_code` unique within the convention (a duplicate
        code is rejected with `ERR_DUPLICATE_SPACE_CODE`), a `block` letter, a
        numeric `unit_number` giving its position within the block, a `hall`
        (`MAIN`, `ARTIST_ALLEY_HALL`, or `SMALL_PRESS`), a physical `kind`
        (`BOOTH_10X10`, `BOOTH_10X20`, `CORNER_BOOTH`, `ENDCAP`,
        `FEATURED_ISLAND`, `ARTIST_TABLE`, or `NONPROFIT_TABLE`), and its
        tier-one `base_price_cents`."

        Design: Corner/validations/duplicate_space_code_rejected
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        create_space_unit(conv["id"], space_code="A-101")
        resp = api.create_space_unit(
            {
                "convention_id": conv["id"],
                "space_code": "A-101",
                "block": "B",
                "unit_number": 7,
                "hall": "SMALL_PRESS",
                "kind": "NONPROFIT_TABLE",
                "base_price_cents": 15000,
            },
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SPACE_CODE)

    def test_immediate_visibility_after_mutation(self, api, director_headers):
        """PRD §2.9: "The system is immediately consistent: every mutation
        commits atomically within its request, and every derived number is
        recomputed synchronously rather than by a background job."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        created = create_space_unit(conv["id"], space_code="A-101")
        units, meta = validate_paginated(
            api.list_space_units(
                director_headers,
                params={"convention_id": conv["id"], "status": "AVAILABLE"},
            )
        )
        assert meta["total_count"] == 1
        assert [u["id"] for u in units] == [created["id"]]


class TestLoadSlots:
    def test_load_slot_invalid_time_window_rejected(self, api, director_headers):
        """PRD §3.8: "The director creates each load slot with its
        `convention_id`, a `direction` of `INBOUND` or `OUTBOUND`, a `starts_at`
        opening the window inclusively, an `ends_at` closing it exclusively —
        the end must be strictly after the start (`ERR_INVALID_TIME_WINDOW`) —
        and a `pallet_capacity` bounding the aggregate pallets the window can
        absorb."

        Design: Corner/validations/load_slot_invalid_time_window_rejected
        """
        conv = create_convention(category_quotas=[], dock_doors=[])
        resp = api.create_load_slot(
            {
                "convention_id": conv["id"],
                "direction": "INBOUND",
                "starts_at": "2026-10-14T08:00:00Z",
                "ends_at": "2026-10-14T08:00:00Z",
                "pallet_capacity": 10,
            },
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)


class TestExhibitorRegistration:
    def test_exhibitor_registration_initializes_system_fields(self, api, director_headers):
        """PRD §3.2: "The new exhibitor starts with `strike_points` at zero and
        `standing` at `GOOD`, and its `renewal_priority_score` is computed
        immediately."
        PRD §3.2: "The `renewal_priority_score` rewards tenure and reliability:
        ten points for each completed prior year, plus three points for each
        prior on-time payment, minus eight points for each strike point, with
        the result floored at zero when the arithmetic would go negative."

        Design: Corner/entities/exhibitor_registration_initializes_system_fields
        """
        exhibitor = register_exhibitor(
            legal_name="Dealer One LLC",
            category="DEALER",
            prior_years_completed=2,
            prior_on_time_payments=3,
        )
        assert_exhibitor(exhibitor)
        assert exhibitor["standing"] == "GOOD"
        assert exhibitor["strike_points"] == 0
        assert exhibitor["renewal_priority_score"] == 29  # 10*2 + 3*3 - 8*0

        fetched = validate_success(
            api.get_exhibitor(exhibitor["id"], director_headers)
        )
        assert_exhibitor_standing_consistent(fetched)
        assert_renewal_priority_score(fetched)
