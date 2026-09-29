"""The registry writes and reads: declared defaults, stored rows, listing
pages, not-found envelopes, and the counters derived at creation."""

import pytest

from test_helpers import (
    UNKNOWN_ID,
    a2l_program_payload,
    assert_append_only_row,
    assert_component_supply,
    assert_instant_equals,
    assert_leak_test,
    assert_product_platform,
    assert_refrigerant_program,
    assert_regional_standard,
    assert_supply_conservation,
    assert_test_cell,
    compressor_supply_payload,
    create_a1_program,
    create_certification_record_payload,
    create_released_standard_a1_platform,
    create_southeast_standard,
    create_standard_a1_draft_platform,
    create_test_cell_payload,
    pressure_decay_leak_test_payload,
    read_build_order,
    read_platform,
    setup_brazed_standard_a1_lot,
    southeast_standard_payload,
    standard_a1_platform_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRefrigerantProgramRegistration:
    """A registered program opens with every lifecycle field at its default."""

    def test_new_program_is_active_with_zeroed_counter_and_clock_stamp(
        self, api, plant_admin_headers
    ):
        """A new program opens in ACTIVE status with sell_through_entered_at and
        expired_at both unset, and its affected_platform_count reports how many
        platforms name this program and currently sit in DRAFT, ENG_REVIEW,
        RELEASED, or RESTRICTED — retired platforms drop out of the count. The
        api_request_id is a server-generated unique identifier for the request
        that starts with req_.

        Design: Corner/entities/c_create_refrigerant_program_stamps_defaults_and_active_status
        """
        response = api.create_refrigerant_program(
            a2l_program_payload(), plant_admin_headers
        )
        program = validate_success(response, 201)
        body = response.json()

        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert len(body["meta"]["api_request_id"]) > len("req_")

        assert_refrigerant_program(program)
        assert program["status"] == "ACTIVE"
        assert program["affected_platform_count"] == 0
        assert program["sell_through_entered_at"] is None
        assert program["expired_at"] is None
        assert program["refrigerant_code"] == "R-454B"
        assert program["gwp"] == 466
        assert program["flammability_class"] == "A2L"
        assert program["version"] == 1
        assert_instant_equals(
            program["created_at"], "2026-08-01T00:00:00Z", "created_at"
        )

        stored = validate_success(
            api.get_refrigerant_program(program["id"], plant_admin_headers)
        )
        for field in (
            "id",
            "status",
            "version",
            "refrigerant_code",
            "gwp",
            "flammability_class",
            "affected_platform_count",
            "sell_through_entered_at",
            "expired_at",
        ):
            assert stored[field] == program[field], (
                f"the read returns the identical row, but {field} differs"
            )


class TestRegionalStandardRead:
    """The single-standard read returns the published floors unchanged."""

    def test_stored_standard_reports_its_tier_minimums_and_default_flag(
        self, api, plant_admin_headers, certification_engineer_headers
    ):
        """Three minimums are published together, one per efficiency tier:
        min_seer2_standard, min_seer2_high, and min_seer2_premium, each greater
        than zero and carried to two decimal places. A jurisdiction that bans
        mildly flammable refrigerant sets prohibits_flammable_refrigerant to
        true; when the flag is omitted it defaults to false.

        Design: Corner/entities/c_get_regional_standard_returns_stored_row
        """
        payload = southeast_standard_payload()
        assert "prohibits_flammable_refrigerant" not in payload
        created = validate_success(
            api.create_regional_standard(payload, plant_admin_headers), 201
        )

        standard = validate_success(
            api.get_regional_standard(created["id"], certification_engineer_headers)
        )

        assert_regional_standard(standard)
        assert standard["id"] == created["id"]
        assert standard["region_code"] == "SOUTHEAST"
        assert standard["status"] == "ACTIVE"
        assert float(standard["min_seer2_standard"]) == pytest.approx(14.30, abs=0.005)
        assert float(standard["min_seer2_high"]) == pytest.approx(15.20, abs=0.005)
        assert float(standard["min_seer2_premium"]) == pytest.approx(16.00, abs=0.005)
        assert standard["prohibits_flammable_refrigerant"] is False, (
            "the omitted flag took its declared default"
        )
        assert_instant_equals(
            standard["effective_from_utc"],
            "2026-01-01T00:00:00Z",
            "effective_from_utc",
        )


class TestPlatformListing:
    """Three platforms, two pages, and a filter applied before pagination."""

    def test_platform_pages_report_the_same_total_count(self, api, plant_admin_headers):
        """offset is the number of rows to skip and defaults to 0. Platforms are
        listable and can be filtered by refrigerant_program_id, by
        supersedes_platform_id, by efficiency_tier, by status, and by
        warranty_posture.

        Design: Corner/entities/c_list_platforms_paginates_and_reports_total_count
        """
        program = create_a1_program()
        first = create_standard_a1_draft_platform(program["id"])
        second = create_standard_a1_draft_platform(
            program["id"],
            model_code="LX-3000-A1",
            efficiency_tier="HIGH",
            rated_capacity_btuh=30000,
            rated_eer=12.10,
            rated_seer2=15.40,
            compressor_part_number="CMP-3T-A1",
        )
        third = create_standard_a1_draft_platform(
            program["id"],
            model_code="LX-3600-A1",
            efficiency_tier="PREMIUM",
            rated_capacity_btuh=36000,
            rated_eer=12.90,
            rated_seer2=16.80,
            compressor_part_number="CMP-5T-A1",
            control_board_part_number="CTL-9X",
        )

        page_response = api.list_product_platforms(
            plant_admin_headers, params={"limit": 2, "offset": 0}
        )
        page_one, meta_one = validate_paginated(page_response)
        assert page_response.json()["response_type"] == "array"
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert [row["id"] for row in page_one] == [first["id"], second["id"]]

        page_two, meta_two = validate_paginated(
            api.list_product_platforms(
                plant_admin_headers, params={"limit": 2, "offset": 2}
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert page_two[0]["id"] == third["id"]

        premium, premium_meta = validate_paginated(
            api.list_product_platforms(
                plant_admin_headers, params={"efficiency_tier": "PREMIUM"}
            )
        )
        assert premium_meta["total_count"] == 1, (
            "the filter is applied before pagination"
        )
        assert len(premium) == 1
        assert premium[0]["id"] == third["id"]

        for row in page_one + page_two:
            assert_product_platform(row)
            assert row["status"] == "DRAFT"
            assert row["salable_region_count"] == 0


class TestUnknownPlatformRead:
    """A well-formed identifier that names nothing is a 404, not an empty 200."""

    def test_unknown_platform_id_returns_the_not_found_envelope(
        self, api, plant_admin_headers
    ):
        """The path identifier is resolved first, and if it names nothing the
        request fails immediately with the not-found error belonging to that
        identifier's type. The error_id is a unique, machine-readable string that
        identifies the specific error. The message provides a human-readable
        explanation of what went wrong.

        Design: Corner/entities/c_get_platform_unknown_id_not_found
        """
        response = api.get_product_platform(UNKNOWN_ID, plant_admin_headers)
        validate_error(response, "ERR_PLATFORM_NOT_FOUND", 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""


class TestPlatformCreationRequiresEveryRating:
    """A required rating has no default, so its absence is a shape failure."""

    def test_platform_without_rated_seer2_is_refused_and_stores_nothing(
        self, api, design_engineer_headers, plant_admin_headers
    ):
        """A missing required field, an enum value outside its declared set, a
        numeric field that is non-numeric or negative where a positive value is
        required, or a timestamp that is not RFC 3339, all rejected with
        ERR_INVALID_REQUEST. The naming program's affected_platform_count is
        recomputed as part of the same write.

        Design: Corner/entities/c_create_platform_missing_rated_seer2_rejected
        """
        program = create_a1_program()
        payload = standard_a1_platform_payload(program["id"])
        del payload["rated_seer2"]

        response = api.create_product_platform(payload, design_engineer_headers)
        validate_error(response, "ERR_INVALID_REQUEST", 422)

        _, meta = validate_paginated(api.list_product_platforms(plant_admin_headers))
        assert meta["total_count"] == 0, "no platform row was written"

        stored_program = validate_success(
            api.get_refrigerant_program(program["id"], plant_admin_headers)
        )
        assert stored_program["affected_platform_count"] == 0


class TestTestCellDefaults:
    """An omitted cooldown is filled in server-side."""

    def test_cell_created_without_a_cooldown_takes_the_declared_default(
        self, api, plant_admin_headers
    ):
        """A PlantAdmin registers each cell with a cell_code of 1 to 32
        characters, unique across cells, and an optional cooldown_minutes between
        0 and 240 that defaults to 30 when omitted; the cell's status is set to
        ACTIVE at creation and cells are never retired in this scope.

        Design: Corner/entities/c_create_test_cell_applies_default_cooldown
        """
        payload = create_test_cell_payload("CELL-9")
        assert "cooldown_minutes" not in payload

        cell = validate_success(api.create_test_cell(payload, plant_admin_headers), 201)

        assert_test_cell(cell)
        assert cell["cooldown_minutes"] == 30
        assert cell["status"] == "ACTIVE"
        assert cell["cell_code"] == "CELL-9"
        assert cell["version"] == 1

        _, meta = validate_paginated(
            api.list_test_cell_run_tests(cell["id"], plant_admin_headers)
        )
        assert meta["total_count"] == 0, "a fresh cell has occupied no window yet"


class TestLeakTestIsAppendOnly:
    """A leak test carries no version because it is never edited."""

    def test_recorded_leak_test_exposes_neither_version_nor_updated_at(
        self, api, quality_technician_headers
    ):
        """There is no endpoint that updates either one; a corrected measurement
        is a new record, not an edit. Under PRESSURE_DECAY, the applied_limit is
        the plant's allowance of 2.00 kilopascals for every 15 minutes of hold —
        that is, 2.00 multiplied by hold_minutes divided by 15 — multiplied by the
        strictness factor and rounded to two decimal places.

        Design: Corner/entities/c_leak_test_record_is_immutable_without_version
        """
        scenario = setup_brazed_standard_a1_lot(quantity_units=8)
        lot_id = scenario["build_order"]["id"]

        record = validate_success(
            api.create_leak_test(
                pressure_decay_leak_test_payload(lot_id, decay_kpa=1.50, hold_minutes=15),
                quality_technician_headers,
            ),
            201,
        )

        assert_leak_test(record)
        assert_append_only_row(record)
        assert float(record["applied_limit"]) == pytest.approx(2.00, abs=0.005), (
            "a 15-minute hold on an A1 program allows the full 2.00 kilopascals"
        )
        assert record["verdict"] == "PASS"
        assert record["performed_by_user_id"] == "user-qt-1"
        assert_instant_equals(
            record["performed_at"], "2026-08-01T00:00:00Z", "performed_at"
        )

        records, meta = validate_paginated(
            api.list_leak_tests(
                quality_technician_headers, params={"build_order_id": lot_id}
            )
        )
        assert meta["total_count"] == 1
        assert records[0]["id"] == record["id"]
        assert read_build_order(lot_id)["status"] == "LEAK_PASSED"


class TestCertificationForeignKey:
    """The payload's foreign key is checked before the version token it carries."""

    def test_certification_naming_an_unknown_platform_is_a_not_found(
        self, api, certification_engineer_headers, plant_admin_headers
    ):
        """Unresolvable path identifiers and unresolvable payload foreign keys
        yield the appropriate not-found error from the family listed in §2.7. Only
        after the path resolves are the payload's own foreign keys checked, and
        those failures carry the same error family.

        Design: Corner/entities/c_create_certification_for_unknown_platform_not_found
        """
        create_southeast_standard()
        program = create_a1_program()
        platform = create_released_standard_a1_platform(program["id"])
        held_version = platform["version"]

        response = api.create_certification_record(
            create_certification_record_payload(
                UNKNOWN_ID,
                held_version,
                region_code="SOUTHEAST",
                rated_seer2_submitted=14.60,
            ),
            certification_engineer_headers,
        )
        validate_error(response, "ERR_PLATFORM_NOT_FOUND", 404)

        _, meta = validate_paginated(
            api.list_certification_records(plant_admin_headers)
        )
        assert meta["total_count"] == 0, "no filing was opened"
        assert read_platform(platform["id"])["version"] == held_version, (
            "the refused call bumped nothing"
        )


class TestComponentSupplyDerivedAtCreation:
    """The four pool counters are derived from the first write onwards."""

    def test_fresh_pool_reports_its_full_committed_total_as_available(
        self, api, supply_planner_headers
    ):
        """Four counters describe a pool at any instant, and all four are derived
        rather than written. A derate is never stored as a negative balance, and
        the cascade revokes reserved lines until the identity holds with
        available_units at zero or above.

        Design: Corner/entities/c_component_supply_effective_units_derived_at_creation
        """
        payload = compressor_supply_payload(
            part_number="CMP-5T-A2L",
            supplier_lot_code="LOT-CMP-77",
            supply_month="2026-11",
            total_allocatable_units=140,
        )
        assert "allocation_policy" not in payload

        pool = validate_success(
            api.create_component_supply(payload, supply_planner_headers), 201
        )

        assert_component_supply(pool)
        assert pool["status"] == "ACTIVE"
        assert pool["derate_pct"] == 0
        assert pool["total_allocatable_units"] == 140
        assert pool["effective_allocatable_units"] == 140
        assert pool["reserved_units"] == 0
        assert pool["committed_units"] == 0
        assert pool["available_units"] == 140
        assert pool["allocation_policy"] == "PRIORITY_WATERFALL", (
            "the omitted policy took its declared default"
        )
        assert_supply_conservation(pool)

        _, meta = validate_paginated(
            api.list_supply_allocation_lines(pool["id"], supply_planner_headers)
        )
        assert meta["total_count"] == 0, "nothing has been drawn from the pool"
