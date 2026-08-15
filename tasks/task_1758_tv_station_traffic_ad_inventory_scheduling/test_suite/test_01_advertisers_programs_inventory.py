"""Entity foundations: advertiser registration, program listing and
pagination, avail-unit creation, and the append-only as-run surface."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_advertiser,
    assert_avail_unit,
    create_avail_week,
    create_program,
    validate_error,
    validate_paginated,
    validate_success,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]
BILLING = TEST_USERS["billingclerk_headers"]


class TestAdvertiserCreation:
    def test_advertiser_creation_defaults_and_echo(self, api):
        """PRD §3.1: "When the buy comes through a media agency, the `agency_name` records the agency of record; for direct business the field may be omitted and defaults to an empty string."

        Design: Corner/entities/advertiser_creation_defaults_and_stored_fields
        """
        created = validate_success(
            api.create_advertiser(
                {
                    "name": "Corner Ad",
                    "product_category": "RETAIL",
                    "credit_limit_cents": 100000,
                },
                SALESREP,
            ),
            201,
        )
        assert_advertiser(created)
        assert created["agency_name"] == "", "omitted agency_name must default to empty string"

        fetched = validate_success(api.get_advertiser(created["id"], TRAFFIC))
        assert fetched["name"] == "Corner Ad"
        assert fetched["product_category"] == "RETAIL"
        assert fetched["credit_limit_cents"] == 100000
        assert fetched["agency_name"] == ""

    def test_advertiser_invalid_product_category_rejected(self, api):
        """PRD §3.1: "The `product_category` must be one of `AUTOMOTIVE`, `RETAIL`, `RESTAURANT`, `PHARMA`, `FINANCE`, `POLITICAL`, or `OTHER`"
        PRD §2.10: "Thirteenth, field-level request sanity — required fields present, enum values valid, prices positive, weights and ratings non-negative where required, spot lengths in the allowed set — else `ERR_INVALID_REQUEST`"

        Design: Corner/entities/advertiser_invalid_enum_product_category_rejected
        """
        resp = api.create_advertiser(
            {"name": "Bad Cat", "product_category": "TOBACCO", "credit_limit_cents": 1000},
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_advertiser_missing_required_name_rejected(self, api):
        """PRD §3.1: "A `SalesRep` registers one by supplying its legal `name`, its `product_category`, and a `credit_limit_cents` ceiling on approved outstanding billing, which must not be negative."
        PRD §2.10: "Thirteenth, field-level request sanity — required fields present, enum values valid, prices positive, weights and ratings non-negative where required, spot lengths in the allowed set — else `ERR_INVALID_REQUEST`"

        Design: Corner/entities/advertiser_missing_required_field_rejected
        """
        resp = api.create_advertiser(
            {"product_category": "RETAIL", "credit_limit_cents": 1000}, SALESREP
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_advertiser_returns_404(self, api):
        """PRD §2.10: "Third, existence: path identifiers and then body references resolve left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_get_not_found_returns_404
        """
        resp = api.get_advertiser(NON_EXISTENT_UUID, SALESREP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProgramListing:
    def test_program_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/program_list_pagination_envelope
        """
        for i, (daypart, weekday) in enumerate(
            [("PRIME", 1), ("DAYTIME", 2), ("OVERNIGHT", 3)], start=1
        ):
            create_program(
                title=f"P{i}",
                daypart_code=daypart,
                airs_weekday=weekday,
                rating_estimate=float(i),
            )
        resp = api.list_programs(SALESREP, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"expected 2 items under limit=2, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestAvailUnitCreation:
    def test_booked_counters_and_reserve_default_zero(self, api):
        """PRD §3.2: "Creation initializes both booked-second counters of §2.6 to zero."
        PRD §3.2: "During a political window, the unit may also carry `reserved_political_seconds`, which defaults to 0, must never be negative, and must never exceed the unit's `total_seconds`."

        Design: Corner/entities/availunit_computed_booked_counters_start_zero
        """
        program = create_program(daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0)
        week = create_avail_week("2026-08-03")
        unit = validate_success(
            api.create_avail_unit(
                week["id"],
                {
                    "program_id": program["id"],
                    "air_date": "2026-08-08",
                    "break_position": 1,
                    "total_seconds": 120,
                },
                TRAFFIC,
            ),
            201,
        )
        assert_avail_unit(unit)
        assert unit["booked_commercial_seconds"] == 0
        assert unit["booked_political_seconds"] == 0
        assert unit["reserved_political_seconds"] == 0

    def test_air_date_outside_owning_week_rejected(self, api):
        """PRD §3.2: "The air date must fall inside the owning week and its weekday must equal the program's `airs_weekday`; a mismatch in either direction is rejected with `ERR_DATE_WINDOW`."

        Design: Corner/validations/availunit_air_date_outside_week_rejected
        """
        program = create_program(daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0)
        week = create_avail_week("2026-08-03")
        # 2026-08-10 is a Monday (weekday matches) but belongs to the next week.
        resp = api.create_avail_unit(
            week["id"],
            {
                "program_id": program["id"],
                "air_date": "2026-08-10",
                "break_position": 1,
                "total_seconds": 60,
            },
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_WINDOW)

    def test_air_date_weekday_mismatch_rejected(self, api):
        """PRD §3.2: "The air date must fall inside the owning week and its weekday must equal the program's `airs_weekday`; a mismatch in either direction is rejected with `ERR_DATE_WINDOW`."

        Design: Corner/validations/availunit_weekday_mismatch_rejected
        """
        program = create_program(daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0)
        week = create_avail_week("2026-08-03")
        # 2026-08-04 is inside the week but is a Tuesday; the program airs Monday.
        resp = api.create_avail_unit(
            week["id"],
            {
                "program_id": program["id"],
                "air_date": "2026-08-04",
                "break_position": 1,
                "total_seconds": 60,
            },
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_WINDOW)


class TestAsRunEntrySurface:
    def test_as_run_entries_are_append_only_reads(self, api):
        """PRD §2.4: "An as-run entry is an append-only reconciliation record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent. Once posted, an as-run entry is never modified."
        PRD §2.10: "Third, existence: path identifiers and then body references resolve left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/asrunentry_immutable_no_update_endpoint
        """
        resp = api.list_log_day_as_run_entries(NON_EXISTENT_UUID, BILLING)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
