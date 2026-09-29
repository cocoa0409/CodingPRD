"""Entity shapes: declared fields, derived defaults, envelopes and reference resolution."""

from test_helpers import (
    ApiErrorId,
    assert_acres,
    assert_bps,
    assert_money,
    assert_pagination_meta,
    assert_stand_partition,
    assert_timestamp_format,
    assert_tons,
    assert_tons_per_acre,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    CANONICAL_CRUISE_PLOTS,
    carbon_dedication_payload,
    fund_payload,
    harvest_block_payload,
    property_payload,
    stand_payload,
)
from test_helpers.fixtures import (
    close_cruise,
    create_carbon_project,
    create_fund,
    create_property,
    create_stand,
    cruised_stand,
    dedicate,
    open_cruise_stand,
    owned_tract,
    read_carbon_project,
    read_stand,
    record_cruise_plot,
    reserve_block,
    stand_version,
)
from test_helpers.test_users import (
    make_analyst_headers,
    make_carbon_developer_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
)

MISSING_CORE_ID = "11111111-1111-4111-8111-111111111111"
MISSING_SECONDARY_ID = "22222222-2222-4222-8222-222222222222"
SUBMITTED_PROPERTY_ID = "33333333-3333-4333-8333-333333333333"
MISSING_PROPERTY_ID = "44444444-4444-4444-8444-444444444444"
MISSING_PROJECT_ID = "00000000-0000-4000-8000-0000000000cd"

RECREATIONAL_TRACT = {
    "hbu_acres": 40.00,
    "hbu_price_per_acre_usd": 3000.00,
    "annual_rec_income_usd": 18000.00,
}


class TestCreationDefaults:
    """A creation response must already carry every derived and defaulted figure."""

    def test_a_new_fund_reports_its_seeded_treasury_and_zeroed_counters(self, api):
        """Opening cash seeds the treasury and every accumulator starts at zero.

        PRD: "At creation `cash_balance_usd` is set equal to `opening_cash_usd`, `net_operating_cash_usd` is 0.00, `cash_yield_bps` is 0, `nav_usd` equals `cash_balance_usd`, and `replan_property_count` and `valuation_basis_stale_count` are both 0."

        Design: Corner/entities/fund_creation_returns_declared_and_defaulted_fields
        """
        response = api.create_fund(
            fund_payload(target_cash_yield_bps=450), make_fund_admin_headers()
        )
        fund = validate_success(response, 201)

        assert_money(fund["cash_balance_usd"], 400000.00, "cash_balance_usd")
        assert_money(fund["nav_usd"], 400000.00, "nav_usd")
        assert_money(fund["net_operating_cash_usd"], 0.00, "net_operating_cash_usd")
        assert_bps(fund["cash_yield_bps"], 0, "cash_yield_bps")
        assert fund["harvest_acceleration_required"] is True, (
            "a target of 450 bps against a yield of 0 bps demands acceleration"
        )
        assert fund["replan_property_count"] == 0
        assert fund["valuation_basis_stale_count"] == 0
        assert fund["version"] == 1
        assert_timestamp_format(fund["created_at"])
        assert_timestamp_format(fund["updated_at"])

    def test_a_registered_tract_derives_its_market_access_from_haul_distance(self, api):
        """Sixty-two haul miles land the tract in the second tier at a 4.5 percent haircut.

        PRD: "`market_access_tier` reads `TIER_A` when `haul_distance_miles` is at most 40, `TIER_B` from 41 through 80 inclusive, `TIER_C` from 81 through 140 inclusive, and `TIER_D` at 141 or more."

        Design: Corner/entities/property_retrieval_returns_stored_and_derived_fields
        """
        fund = create_fund(api)

        tract = create_property(api, fund["id"], **RECREATIONAL_TRACT)

        assert tract["market_access_tier"] == "TIER_B"
        assert_money(
            tract["market_access_discount_pct"], 4.5, "market_access_discount_pct"
        )
        assert tract["status"] == "PROSPECT"
        assert tract["appraisal_status"] == "NONE"
        assert tract["certification_posture"] == "CERTIFIED"
        assert tract["harvest_plan_status"] == "ALIGNED"
        assert_acres(tract["total_acres"], 1200.00, "total_acres")
        assert_acres(tract["hbu_acres"], 40.00, "hbu_acres")
        assert_money(tract["annual_rec_income_usd"], 18000.00, "annual_rec_income_usd")
        assert tract["appraised_value_usd"] is None
        assert tract["acquisition_price_usd"] is None
        assert tract["composite_risk_score"] is None
        assert tract["version"] == 1

    def test_a_new_harvest_block_is_reserved_with_only_its_provisional_pricing(self, api):
        """Reservation prices the block provisionally and leaves every realised figure unset.

        PRD: "On acceptance the block is created in `RESERVED`, its `planned_tons` is added to the stand's `reserved_tons` and subtracted from `available_tons`, and the stand's `version` is incremented."

        Design: Corner/entities/harvest_block_creation_defaults_status_and_null_actuals
        """
        ctx = cruised_stand(api)

        response = api.create_harvest_block(
            harvest_block_payload(ctx.stand_id, stand_version(api, ctx.stand_id)),
            make_forest_manager_headers(),
        )
        block = validate_success(response, 201)

        assert block["status"] == "RESERVED"
        assert_money(
            block["provisional_net_revenue_usd"], 22889.55, "provisional_net_revenue_usd"
        )
        assert_money(block["severance_tax_usd"], 1248.45, "severance_tax_usd")
        assert block["actual_tons"] is None
        assert block["realized_price_index_factor"] is None
        assert block["final_net_revenue_usd"] is None
        assert block["voided_reason"] is None
        assert block["version"] == 1

    def test_a_cruise_plot_is_immutable_and_carries_no_version(self, api):
        """A plot records its own defect-netted yield and no mutable bookkeeping at all.

        PRD: "Cruise plots are the single exception: a cruise plot is immutable once recorded, so it carries only `id` and `created_at`."

        Design: Corner/entities/cruise_plot_is_immutable_and_carries_no_version
        """
        ctx = open_cruise_stand(api)

        plot = record_cruise_plot(api, ctx.stand_id, **CANONICAL_CRUISE_PLOTS[0])

        assert_tons_per_acre(plot["net_tons_per_acre"], 38.681, "net_tons_per_acre")
        assert "version" not in plot, "a cruise plot carries no version field"
        assert "updated_at" not in plot, "a cruise plot carries no updated_at field"
        assert_timestamp_format(plot["created_at"])

        plots, meta = validate_paginated(
            api.list_stand_cruise_plots(ctx.stand_id, make_forest_manager_headers())
        )
        assert len(plots) == 1
        assert_pagination_meta(meta, total_count=1, has_more=False)

        stand = read_stand(api, ctx.stand_id)
        assert stand["plot_count"] == 1
        assert stand["status"] == "CRUISE_OPEN"


class TestSystemManagedInputIsIgnored:
    """Computed and server-owned fields in a request body carry no weight."""

    def test_a_stand_created_with_fabricated_volumes_still_starts_empty(self, api):
        """Submitted inventory figures are discarded and the cruise starts from nothing.

        PRD: "Computed and system-managed fields that appear in a request body are silently ignored rather than rejected."

        Design: Corner/entities/stand_create_computed_volume_input_ignored
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"])

        response = api.create_stand(
            stand_payload(
                tract["id"],
                net_merch_tons=99999.99,
                available_tons=99999.99,
                status="INVENTORIED",
            ),
            make_forest_manager_headers(),
        )
        stand = validate_success(response, 201)

        assert stand["status"] == "CRUISE_OPEN"
        assert_stand_partition(stand, net_merch_tons=0.00, available_tons=0.00)
        assert_tons(stand["gross_merch_tons"], 0.00, "gross_merch_tons")
        assert stand["plot_count"] == 0
        assert stand["cruise_confidence"] == "NONE"

    def test_a_property_created_with_a_fabricated_identifier_gets_a_server_minted_one(
        self, api
    ):
        """The server mints the identifier and starts the version count itself.

        PRD: "Each persisted resource is addressed by an `id` that the server mints as a UUID."

        Design: Corner/entities/property_create_system_field_input_ignored
        """
        fund = create_fund(api)

        response = api.create_property(
            property_payload(
                fund["id"],
                id=SUBMITTED_PROPERTY_ID,
                version=77,
                created_at="2000-01-01T00:00:00.000Z",
            ),
            make_analyst_headers(),
        )
        tract = validate_success(response, 201)

        assert tract["id"] != SUBMITTED_PROPERTY_ID, (
            "the submitted identifier must not have been honoured"
        )
        assert tract["version"] == 1
        validate_error(
            api.get_property(SUBMITTED_PROPERTY_ID, make_analyst_headers()),
            ApiErrorId.PROPERTY_NOT_FOUND.value,
            404,
        )


class TestFieldValidationOnCreation:
    """Missing required fields and out-of-set enums are rejected before anything else."""

    def test_a_stand_without_acres_is_refused_as_an_invalid_request(self, api):
        """Acreage is required, so its absence is a shape error and not a business error.

        PRD: "All required input fields present; enum values inside their declared sets; numerics inside their declared ranges and decimal precision; dates well formed."

        Design: Corner/entities/stand_create_without_acres_returns_invalid_request
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"])

        response = api.create_stand(
            stand_payload(tract["id"], acres=...), make_forest_manager_headers()
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _stands, meta = validate_paginated(
            api.list_property_stands(tract["id"], make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=0)
        unchanged = validate_success(
            api.get_property(tract["id"], make_analyst_headers()), 200
        )
        assert unchanged["version"] == 1, "the refused stand never mutated its parent"

    def test_an_unknown_product_mix_is_refused_before_the_tonnage_is_weighed(self, api):
        """A mix outside the declared set is a shape error, never an over-reservation.

        PRD: "The effective price is the block's stumpage expectation multiplied by the index factor and then by the product-mix factor — 1.00 for `SAWTIMBER`, 0.82 for `MIXED`, 0.61 for `PULPWOOD` — rounded half-up to four decimal places."

        Design: Corner/entities/harvest_block_product_mix_invalid_enum_rejected
        """
        ctx = cruised_stand(api)

        response = api.create_harvest_block(
            harvest_block_payload(
                ctx.stand_id,
                stand_version(api, ctx.stand_id),
                product_mix="FIREWOOD",
                planned_tons=9000.00,
            ),
            make_forest_manager_headers(),
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        assert_stand_partition(
            read_stand(api, ctx.stand_id), reserved_tons=0.00, available_tons=4647.12
        )
        _blocks, meta = validate_paginated(
            api.list_stand_harvest_blocks(ctx.stand_id, make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=0)


class TestReferenceResolution:
    """Every resource type answers a missing identifier with its own not-found code."""

    def test_an_absent_core_entity_identifier_returns_its_own_not_found_code(self, api):
        """Five core reads on one unknown identifier give five distinct codes.

        PRD: "Each resource type has its own 404: `ERR_FUND_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_STAND_NOT_FOUND`, `ERR_UNDERWRITING_CASE_NOT_FOUND`, `ERR_HARVEST_BLOCK_NOT_FOUND`, `ERR_CARBON_PROJECT_NOT_FOUND`, `ERR_CARBON_DEDICATION_NOT_FOUND`, `ERR_HBU_PARCEL_NOT_FOUND`, `ERR_RECREATIONAL_LEASE_NOT_FOUND`, `ERR_CERTIFICATION_AUDIT_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, and `ERR_HAZARD_EVENT_NOT_FOUND`."

        Design: Corner/entities/core_entity_path_id_absent_returns_not_found
        """
        headers = make_fund_admin_headers()
        expectations = [
            (api.get_fund(MISSING_CORE_ID, headers), ApiErrorId.FUND_NOT_FOUND),
            (api.get_property(MISSING_CORE_ID, headers), ApiErrorId.PROPERTY_NOT_FOUND),
            (api.get_stand(MISSING_CORE_ID, headers), ApiErrorId.STAND_NOT_FOUND),
            (
                api.get_underwriting_case(MISSING_CORE_ID, headers),
                ApiErrorId.UNDERWRITING_CASE_NOT_FOUND,
            ),
            (
                api.get_harvest_block(MISSING_CORE_ID, headers),
                ApiErrorId.HARVEST_BLOCK_NOT_FOUND,
            ),
        ]
        for response, error_id in expectations:
            validate_error(response, error_id.value, 404)

    def test_an_absent_secondary_entity_identifier_returns_its_own_not_found_code(
        self, api
    ):
        """The seven satellite resources each keep their own not-found code too.

        PRD: "When a URL contains a resource identifier, the server resolves it before it looks at anything in the body, and when a path nests identifiers it resolves them left to right, failing on the first one that does not exist."

        Design: Corner/entities/secondary_entity_path_id_absent_returns_not_found
        """
        headers = make_fund_admin_headers()
        expectations = [
            (
                api.get_carbon_project(MISSING_SECONDARY_ID, headers),
                ApiErrorId.CARBON_PROJECT_NOT_FOUND,
            ),
            (
                api.get_carbon_dedication(MISSING_SECONDARY_ID, headers),
                ApiErrorId.CARBON_DEDICATION_NOT_FOUND,
            ),
            (
                api.get_hbu_parcel(MISSING_SECONDARY_ID, headers),
                ApiErrorId.HBU_PARCEL_NOT_FOUND,
            ),
            (
                api.get_recreational_lease(MISSING_SECONDARY_ID, headers),
                ApiErrorId.RECREATIONAL_LEASE_NOT_FOUND,
            ),
            (
                api.get_certification_audit(MISSING_SECONDARY_ID, headers),
                ApiErrorId.CERTIFICATION_AUDIT_NOT_FOUND,
            ),
            (
                api.get_audit_finding(MISSING_SECONDARY_ID, headers),
                ApiErrorId.AUDIT_FINDING_NOT_FOUND,
            ),
            (
                api.get_hazard_event(MISSING_SECONDARY_ID, headers),
                ApiErrorId.HAZARD_EVENT_NOT_FOUND,
            ),
        ]
        for response, error_id in expectations:
            validate_error(response, error_id.value, 404)

    def test_a_stand_naming_an_unknown_property_is_refused_as_not_found(self, api):
        """The body's parent reference is resolved before the stand is persisted.

        PRD: "Every foreign key in the body resolves, left to right, else the matching not-found code for the first unresolved reference (404)."

        Design: Corner/entities/stand_create_with_unknown_property_returns_not_found
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"])

        response = api.create_stand(
            stand_payload(MISSING_PROPERTY_ID), make_forest_manager_headers()
        )
        validate_error(response, ApiErrorId.PROPERTY_NOT_FOUND.value, 404)

        _stands, meta = validate_paginated(
            api.list_property_stands(tract["id"], make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=0)


class TestListingEnvelopes:
    """List windows report the full result size independently of the page returned."""

    def test_the_stand_listing_windows_three_rows_across_two_pages(self, api):
        """A two-row window reports three in total and flags the remainder.

        PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full result set before the window is applied and `has_more` indicates whether records remain beyond the current window."

        Design: Corner/entities/property_stands_listing_paginates_with_envelope_fields
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"])
        for code in ("PC-01", "PC-02", "PC-03"):
            create_stand(api, tract["id"], stand_code=code)

        headers = make_forest_manager_headers()
        first_page, first_meta = validate_paginated(
            api.list_property_stands(tract["id"], headers, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )

        second_page, second_meta = validate_paginated(
            api.list_property_stands(tract["id"], headers, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert_pagination_meta(
            second_meta, limit=2, offset=2, total_count=3, has_more=False
        )

    def test_a_dedication_is_listable_from_its_project_and_from_its_stand(self, api):
        """Two pledges on two stands appear once each stand-side and twice project-side.

        PRD: "A new dedication is `PENDING` with `reduced_tons` 0.00, `permanence_end_date` unset and `release_reason` unset; its tonnage is added to the stand's `dedicated_tons` and subtracted from `available_tons`, the project's `dedicated_tons_total` is recomputed, and the stand's `version` is incremented."

        Design: Corner/entities/carbon_dedication_junction_is_listable_from_both_parents
        """
        ctx = owned_tract(api)
        second_stand = create_stand(api, ctx.property_id, stand_code="PC-02")
        for plot in CANONICAL_CRUISE_PLOTS:
            record_cruise_plot(api, second_stand["id"], **plot)
        close_cruise(api, second_stand["id"])
        project = create_carbon_project(api, ctx.property_id)

        first = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)
        second = dedicate(api, project["id"], second_stand["id"], dedicated_tons=300.00)

        headers = make_carbon_developer_headers()
        project_side, project_meta = validate_paginated(
            api.list_carbon_project_dedications(project["id"], headers)
        )
        assert {row["id"] for row in project_side} == {first["id"], second["id"]}
        assert_pagination_meta(project_meta, total_count=2)

        for stand_id, dedication_id, dedicated, available in (
            (ctx.stand_id, first["id"], 500.00, 4147.12),
            (second_stand["id"], second["id"], 300.00, 4347.12),
        ):
            rows, meta = validate_paginated(
                api.list_stand_carbon_dedications(stand_id, headers)
            )
            assert [row["id"] for row in rows] == [dedication_id]
            assert_pagination_meta(meta, total_count=1)
            assert rows[0]["status"] == "PENDING"
            assert_stand_partition(
                read_stand(api, stand_id),
                dedicated_tons=dedicated,
                available_tons=available,
            )

        assert_tons(
            read_carbon_project(api, project["id"])["dedicated_tons_total"],
            800.00,
            "dedicated_tons_total",
        )


class TestStandReadPathAgreement:
    """The create response, the direct read and the parent listing must agree."""

    def test_a_stand_reads_back_identically_from_every_route(self, api):
        """One stand, three routes, one set of stored and derived figures.

        PRD: "A stand also records `plot_count`, `mean_net_tons_per_acre`, `cruise_confidence` and `gross_merch_tons` from its cruise, and may reference the stand it was carved out of through `split_from_stand_id`."

        Design: Corner/endpoints/stand_create_read_and_list_round_trip
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"])
        headers = make_forest_manager_headers()

        created = validate_success(
            api.create_stand(stand_payload(tract["id"]), headers), 201
        )
        fetched = validate_success(api.get_stand(created["id"], headers), 200)
        listed, meta = validate_paginated(
            api.list_property_stands(tract["id"], headers, {"limit": 10, "offset": 0})
        )

        assert fetched["id"] == created["id"]
        assert [row["id"] for row in listed] == [created["id"]]
        assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)

        assert fetched["status"] == "CRUISE_OPEN"
        assert_tons(fetched["available_tons"], 0.00, "available_tons")
        assert fetched["version"] == 1
        assert fetched["property_id"] == tract["id"]
        assert_acres(fetched["acres"], 120.00, "acres")
        assert fetched["species_code"] == "LOBLOLLY_PINE"
        assert fetched["age_years"] == 22
        assert fetched["site_index"] == 78
        assert fetched["split_from_stand_id"] is None
        assert fetched["plot_count"] == 0

    def test_a_dedication_naming_an_unknown_project_is_refused_before_the_version_guard(
        self, api
    ):
        """The missing project is reported even though the stand and its version are good.

        PRD: "Creating a carbon dedication therefore reports a bad `carbon_project_id` as `ERR_CARBON_PROJECT_NOT_FOUND` even when `stand_id` is also unresolvable, because the project reference is declared first."

        Design: Corner/endpoints/dedication_with_an_unknown_project_id_returns_not_found
        """
        ctx = owned_tract(api)
        version = stand_version(api, ctx.stand_id)

        response = api.create_carbon_dedication(
            carbon_dedication_payload(MISSING_PROJECT_ID, ctx.stand_id, version),
            make_carbon_developer_headers(),
        )
        validate_error(response, ApiErrorId.CARBON_PROJECT_NOT_FOUND.value, 404)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=0.00,
            available_tons=4647.12,
        )
        assert stand_version(api, ctx.stand_id) == version
        _rows, meta = validate_paginated(
            api.list_stand_carbon_dedications(
                ctx.stand_id, make_carbon_developer_headers()
            )
        )
        assert_pagination_meta(meta, total_count=0)


class TestReservationLedgerAgreement:
    """A reservation must be visible in the stand's ledger the moment it is filed."""

    def test_a_filed_reservation_shows_up_in_the_stand_ledger_immediately(self, api):
        """Reserved tons rise and available tons fall in the very next read.

        PRD: "`available_tons` is the residue: `net_merch_tons` less `reserved_tons`, less `committed_tons`, less `dedicated_tons`, less `hbu_withdrawn_tons`, rounded half-up to two decimals."

        Design: Corner/endpoints/stand_create_read_and_list_round_trip
        """
        ctx = cruised_stand(api)

        reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=1000.00,
            available_tons=3647.12,
        )
