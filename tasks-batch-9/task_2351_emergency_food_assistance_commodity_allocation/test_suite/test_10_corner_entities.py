"""Entity shapes: echoed inputs, computed money, declared defaults, keys and not-founds."""

from test_helpers import (
    AgreementStatus,
    ApiErrorId,
    EligibilityPosture,
    LotStatus,
    MonitorFlag,
    MonitorPolicy,
    NON_EXISTENT_UUID,
    StorageClass,
    TrainingStatus,
    UrbanRural,
    assert_commodity,
    assert_fields_absent,
    assert_instant,
    assert_inventory_lot,
    assert_pounds,
    assert_service_area,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_agency_coordinator_headers,
    make_warehouse_operator_headers,
    validate_error,
    validate_success,
)


def test_01_creating_a_commodity_echoes_every_declared_input(api):
    """PRD §3.1: "It is registered with a `code` in uppercase snake case, unique
    program-wide, a display `name`, a `storage_class` of `DRY`, `COLD`, or `FROZEN` that
    decides which warehouse pool and which agency ceiling the commodity consumes, a
    `net_weight_lbs_per_case` greater than zero carried to three decimal places, a
    `cases_per_pallet` count greater than zero used as the per-line pallet divisor, an
    `entitlement_value_cents_per_case` greater than zero charged to the state per case, a
    nominal `shelf_life_days` greater than zero kept for reporting (the actual shelf
    arithmetic uses each lot's own pack and best-by dates instead), and an
    `excess_case_ceiling` greater than zero — the cases-on-hand level above which a lot is
    flagged as excess before any staleness scoring is even considered." PRD §4:
    "Operations that bring a new, independently addressable resource into existence — a
    service area, an agency, a commodity, a warehouse, an inventory lot, an allocation
    cycle, an order, an order line, a delivery appointment, an inventory transfer, a
    recall, a recall action created by expansion, a household distribution, and the
    agreement-renewal and civil-rights-training records that write onto an agency — return
    `201 Created`." PRD §2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."

    Design: Corner/entities/create_commodity_with_all_declared_inputs_returns_201_and_echoes_every_field
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.create_commodity(f.bulk_rice_payload(), headers=fx.ADMIN)

    commodity = validate_success(response, 201)
    assert_commodity(commodity)
    assert commodity["code"] == "BULK_RICE", (
        f"code expected BULK_RICE but got {commodity['code']}"
    )
    assert commodity["name"] == "Bulk Rice", (
        f"name expected Bulk Rice but got {commodity['name']}"
    )
    assert commodity["storage_class"] == StorageClass.DRY, (
        f"storage_class expected DRY but got {commodity['storage_class']}"
    )
    assert commodity["net_weight_lbs_per_case"] == 20.0, (
        f"net_weight_lbs_per_case expected 20.0 but got {commodity['net_weight_lbs_per_case']}"
    )
    assert commodity["cases_per_pallet"] == 50, (
        f"cases_per_pallet expected 50 but got {commodity['cases_per_pallet']}"
    )
    assert commodity["entitlement_value_cents_per_case"] == 1200, (
        "entitlement_value_cents_per_case expected 1200 but got "
        f"{commodity['entitlement_value_cents_per_case']}"
    )
    assert commodity["shelf_life_days"] == 900, (
        f"shelf_life_days expected 900 but got {commodity['shelf_life_days']}"
    )
    assert commodity["excess_case_ceiling"] == 500, (
        f"excess_case_ceiling expected 500 but got {commodity['excess_case_ceiling']}"
    )
    meta = response.json()["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_ but got {meta['api_request_id']}"
    )


def test_02_a_received_lot_reads_back_with_its_computed_entitlement_value(api):
    """PRD §3.3: "At creation the lot's `entitlement_value_cents` is written as
    `cases_received` multiplied by the commodity's `entitlement_value_cents_per_case` —
    the total federal value charged to the state for this receipt." PRD §3.3: "The lot
    lands in `status` `RECEIVED` with `cases_on_hand` at 0, `cases_committed` at 0,
    `cases_shipped_to_date` at 0, `monitor_flag` at `NONE`, and `slow_moving_index` at
    0.0; `posted_at`, `last_monitored_at`, and `hold_recall_id` are all null."

    Design: Corner/entities/get_inventory_lot_returns_the_stored_row_with_its_computed_entitlement_value
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    created = fx.create_inventory_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )

    lot = get_success_data(api.get_inventory_lot(created["id"], headers=fx.REVIEWER))

    assert_inventory_lot(lot)
    assert lot["entitlement_value_cents"] == 120000, (
        f"entitlement_value_cents expected 120000 but got {lot['entitlement_value_cents']}"
    )
    assert lot["cases_received"] == 100, (
        f"cases_received expected 100 but got {lot['cases_received']}"
    )
    assert lot["cases_on_hand"] == 0, (
        f"an unposted lot must not pre-credit inventory but cases_on_hand is {lot['cases_on_hand']}"
    )
    assert lot["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {lot['cases_committed']}"
    )
    assert lot["cases_shipped_to_date"] == 0, (
        f"cases_shipped_to_date expected 0 but got {lot['cases_shipped_to_date']}"
    )
    assert lot["status"] == LotStatus.RECEIVED, (
        f"status expected RECEIVED but got {lot['status']}"
    )
    assert lot["monitor_flag"] == MonitorFlag.NONE, (
        f"monitor_flag expected NONE but got {lot['monitor_flag']}"
    )
    assert lot["slow_moving_index"] == 0.0, (
        f"slow_moving_index expected 0.0 but got {lot['slow_moving_index']}"
    )
    assert lot["posted_at"] is None, (
        f"posted_at expected null but got {lot['posted_at']}"
    )
    assert lot["last_monitored_at"] is None, (
        f"last_monitored_at expected null but got {lot['last_monitored_at']}"
    )
    assert lot["hold_recall_id"] is None, (
        f"hold_recall_id expected null but got {lot['hold_recall_id']}"
    )


def test_03_agency_pages_partition_the_roster_in_creation_order(api):
    """PRD §2.3: "The `limit` parameter caps the number of rows returned; it defaults to
    10 when omitted, and the accepted range is a minimum of 1 and a maximum of 100." PRD
    §2.3: "Unless a specific endpoint says otherwise, every list endpoint returns its rows
    sorted by `created_at` in ascending order." PRD §2.3: "List responses carry `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where
    `total_count` is the number of rows matching the filters before pagination and
    `has_more` indicates whether rows remain beyond the current page."

    Design: Corner/entities/list_agencies_paginates_with_total_count_has_more_and_created_at_order
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    alpha = fx.create_agency(
        api, area["id"], name="Agency Alpha", cold_storage_pallet_capacity=10
    )
    bravo = fx.create_agency(
        api, area["id"], name="Agency Bravo", cold_storage_pallet_capacity=10
    )
    charlie = fx.create_agency(
        api, area["id"], name="Agency Charlie", cold_storage_pallet_capacity=0
    )

    page_one, meta_one = fx.list_rows_and_meta(
        api.list_agencies(headers=fx.ADMIN, params={"limit": 2, "offset": 0})
    )
    page_two, meta_two = fx.list_rows_and_meta(
        api.list_agencies(headers=fx.ADMIN, params={"limit": 2, "offset": 2})
    )

    assert meta_one["total_count"] == 3, (
        f"total_count expected 3 but got {meta_one['total_count']}"
    )
    assert meta_one["has_more"] is True, (
        f"has_more expected True on page one but got {meta_one['has_more']}"
    )
    assert meta_one["limit"] == 2, f"limit expected 2 but got {meta_one['limit']}"
    assert meta_one["offset"] == 0, f"offset expected 0 but got {meta_one['offset']}"
    assert [row["id"] for row in page_one] == [alpha["id"], bravo["id"]], (
        "page one must hold Alpha then Bravo in created_at ascending order but got "
        f"{[row['name'] for row in page_one]}"
    )
    assert meta_two["total_count"] == 3, (
        f"total_count expected 3 on page two but got {meta_two['total_count']}"
    )
    assert meta_two["has_more"] is False, (
        f"has_more expected False on page two but got {meta_two['has_more']}"
    )
    assert [row["id"] for row in page_two] == [charlie["id"]], (
        f"page two must hold Charlie alone but got {[row['name'] for row in page_two]}"
    )

    _filtered, filtered_meta = fx.list_rows_and_meta(
        api.list_agencies(
            headers=fx.ADMIN,
            params={
                "service_area_id": area["id"],
                "eligibility_posture": EligibilityPosture.INELIGIBLE,
            },
        )
    )
    assert filtered_meta["total_count"] == 3, (
        "all three fresh agencies are INELIGIBLE so total_count expected 3 but got "
        f"{filtered_meta['total_count']}"
    )

    validate_error(
        api.list_agencies(headers=fx.ADMIN, params={"limit": 101}),
        ApiErrorId.ERR_INVALID_REQUEST,
        422,
    )


def test_04_an_unknown_agency_id_is_a_not_found(api):
    """PRD §2.6: "For a path such as `/efap/agencies/{agency_id}/agreement-renewals`, the
    agency is resolved before the request body is inspected at all; an unknown `agency_id`
    yields `ERR_AGENCY_NOT_FOUND` (HTTP 404) regardless of whatever else is wrong with the
    payload." PRD §2.10: "3. Every identifier in the request path resolves, left to right —
    the matching not-found code."

    Design: Corner/entities/get_agency_with_unknown_id_returns_agency_not_found
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.get_agency(NON_EXISTENT_UUID, headers=fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_AGENCY_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error", (
        f"response_type expected error but got {body['response_type']}"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        "the error envelope must carry a non-empty human-readable message"
    )


def test_05_an_agency_without_a_cold_storage_ceiling_is_refused(api):
    """PRD §3.2: "A `StateAdmin` registers an **agency** — an eligible recipient
    organization such as a food bank or pantry — with a `name` of 1 to 120 characters, the
    `service_area_id` of the county whose poverty population feeds its entitlement, a
    `cold_storage_pallet_capacity` of zero or more frozen-pallet positions the agency can
    hold at one time, and optionally the two prior-period baselines the allocation formula
    reads: `prior_period_pounds_distributed`, a non-negative figure carried to two decimals
    and defaulting to 0.0, and `prior_period_allocated_cases`, a non-negative integer
    defaulting to 0." PRD §2.10: "4. Payload well-formedness: every required field present,
    types as specified, enum values inside their permitted list, and every numeric range
    honoured — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_agency_without_cold_storage_capacity_returns_invalid_request
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )

    response = api.create_agency(
        {"name": "Agency Alpha", "service_area_id": area["id"]}, headers=fx.ADMIN
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)
    _rows, meta = fx.list_rows_and_meta(api.list_agencies(headers=fx.ADMIN))
    assert meta["total_count"] == 0, (
        f"no agency may have been created but total_count is {meta['total_count']}"
    )


def test_06_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """PRD §3.1: "It is registered with a display `name` of 1 to 120 characters, a
    `county_code` of 2 to 8 uppercase characters that must be unique across every service
    area (a repeat answers `ERR_DUPLICATE_CODE`), a `poverty_population` — the count of
    persons below 130% of the federal poverty guideline living in that county, which may be
    zero but never negative — and an optional `urban_rural` classification of `URBAN`,
    `RURAL`, or `MIXED`, defaulting to `MIXED` when omitted." PRD §3.1: "The warehouse also
    carries a `monitor_policy` feature flag of `TURNOVER_BASED` or `SHELF_LIFE_BASED`,
    defaulting to `TURNOVER_BASED` when omitted, which selects which staleness-scoring
    variant the monitor run applies to that warehouse's lots." PRD §3.2: "A freshly
    registered agency starts with `agreement_status` `PENDING`, `training_status`
    `REQUIRED`, and `eligibility_posture` `INELIGIBLE`, and it does not move its service
    area's `eligible_agency_count`, because a pending agency is not eligible."

    Design: Corner/entities/omitting_optional_inputs_applies_the_declared_defaults
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api, area["id"], name="Agency Alpha", cold_storage_pallet_capacity=10
    )
    warehouse = fx.create_warehouse(api, name="WH North")

    assert area["urban_rural"] == UrbanRural.MIXED, (
        f"urban_rural expected MIXED by default but got {area['urban_rural']}"
    )
    assert area["eligible_agency_count"] == 0, (
        f"eligible_agency_count expected 0 but got {area['eligible_agency_count']}"
    )
    assert_pounds(
        agency["prior_period_pounds_distributed"], 0.0, "prior_period_pounds_distributed"
    )
    assert agency["prior_period_allocated_cases"] == 0, (
        "prior_period_allocated_cases expected 0 by default but got "
        f"{agency['prior_period_allocated_cases']}"
    )
    assert agency["agreement_status"] == AgreementStatus.PENDING, (
        f"agreement_status expected PENDING but got {agency['agreement_status']}"
    )
    assert agency["training_status"] == TrainingStatus.REQUIRED, (
        f"training_status expected REQUIRED but got {agency['training_status']}"
    )
    assert agency["eligibility_posture"] == EligibilityPosture.INELIGIBLE, (
        f"eligibility_posture expected INELIGIBLE but got {agency['eligibility_posture']}"
    )
    assert warehouse["monitor_policy"] == MonitorPolicy.TURNOVER_BASED, (
        f"monitor_policy expected TURNOVER_BASED but got {warehouse['monitor_policy']}"
    )
    reread = fx.read_service_area(api, area["id"])
    assert reread["eligible_agency_count"] == 0, (
        "registering a pending agency must not move eligible_agency_count but it is "
        f"{reread['eligible_agency_count']}"
    )


def test_07_a_client_supplied_entitlement_value_is_discarded(api):
    """PRD §3.3: "At creation the lot's `entitlement_value_cents` is written as
    `cases_received` multiplied by the commodity's `entitlement_value_cents_per_case` —
    the total federal value charged to the state for this receipt."

    Design: Corner/entities/inventory_lot_entitlement_value_is_computed_and_client_supplied_value_is_input_ignored
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    chicken = fx.create_frozen_chicken(api)
    warehouse = fx.create_warehouse(api, name="WH North")

    lot = validate_success(
        api.create_inventory_lot(
            f.inventory_lot_payload(
                chicken["id"],
                warehouse["id"],
                federal_lot_code="FL-2001",
                cases_received=40,
                pack_date="2026-07-15",
                best_by_date="2027-07-15",
                entitlement_value_cents=999999,
            ),
            headers=fx.ADMIN,
        ),
        201,
    )

    assert lot["entitlement_value_cents"] == 104000, (
        "entitlement_value_cents must be the computed 40 times 2600 rather than the "
        f"supplied 999999 but got {lot['entitlement_value_cents']}"
    )
    assert lot["cases_received"] == 40, (
        f"cases_received expected 40 but got {lot['cases_received']}"
    )
    assert lot["status"] == LotStatus.RECEIVED, (
        f"status expected RECEIVED but got {lot['status']}"
    )
    reread = fx.read_lot(api, lot["id"])
    assert reread["entitlement_value_cents"] == 104000, (
        f"the stored row expected 104000 but got {reread['entitlement_value_cents']}"
    )


def test_08_identity_and_timestamps_are_minted_by_the_server(api):
    """PRD §2.5: "Every stored resource carries a server-minted `id`, formatted as a UUID
    with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant
    with three fractional digits (for example `2026-08-01T00:00:00.000Z`)." PRD §2.5: "Most
    resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three
    fractional digits refreshed on every mutation, and `version`, an integer that increments
    by one on every mutation." PRD §2.4: "The clock starts at the fixed instant
    `2026-08-01T00:00:00Z` and must never fall back to wall-clock time, even before any
    client has moved it."

    Design: Corner/entities/service_area_identity_and_timestamps_are_server_generated_and_client_values_input_ignored
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    area = validate_success(
        api.create_service_area(
            f.service_area_payload(
                name="Area North",
                county_code="C001",
                poverty_population=40000,
                id="sa-client-chosen",
                created_at="1999-01-01T00:00:00Z",
                version=77,
            ),
            headers=fx.ADMIN,
        ),
        201,
    )

    assert_service_area(area)
    assert area["id"] != "sa-client-chosen", (
        "the id must be server-minted but the client value was echoed back"
    )
    assert_instant(area["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant(area["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
    assert area["version"] != 77, (
        f"the client-supplied version must be ignored but got {area['version']}"
    )
    validate_error(
        api.get_service_area("sa-client-chosen", headers=fx.ADMIN),
        ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND,
        404,
    )


def test_09_enum_and_range_violations_all_answer_invalid_request(api):
    """PRD §2.10: "4. Payload well-formedness: every required field present, types as
    specified, enum values inside their permitted list, and every numeric range honoured —
    `ERR_INVALID_REQUEST`. This covers `cases_requested` greater than zero, `cases` greater
    than zero, `cases_distributed` greater than zero, `household_size` at least 1 and at
    most 20, `declared_monthly_income_cents` at least zero, `allocatable_cases` greater than
    zero, `admin_funds_pool_cents` not negative, `dock_number` at least 1 and at most the
    warehouse's `dock_count`, `window_end` strictly after `window_start`,
    `order_window_close_at` strictly after `order_window_open_at`, `agreement_end_date`
    strictly after `agreement_start_date`, `completed_at` at or before the current instant,
    `attendee_count` at least 1, `cases_accounted` at or below the action's `exposed_cases`,
    `reason` between 1 and 400 characters, pagination bounds, and each `line_adjustments`
    entry naming an `OrderLine` of the addressed order with a `cases_approved` value between
    1 and that line's `cases_requested` inclusive." PRD §2.6: "Body-level foreign-key
    resolution happens *after* payload well-formedness is checked, which is why a request
    that both omits a required field and names a nonexistent agency answers
    `ERR_INVALID_REQUEST` rather than `ERR_AGENCY_NOT_FOUND`."

    Design: Corner/entities/enum_and_range_constraints_are_enforced_with_invalid_request
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    bad_enum = api.create_commodity(
        f.commodity_payload(
            code="CHILLED_MILK",
            name="Chilled Milk",
            storage_class="CHILLED",
            net_weight_lbs_per_case=40.0,
            cases_per_pallet=30,
            entitlement_value_cents_per_case=900,
            shelf_life_days=20,
            excess_case_ceiling=100,
        ),
        headers=fx.ADMIN,
    )
    bad_window = api.create_allocation_cycle(
        f.allocation_cycle_payload(
            cycle_code="FY27BAD",
            allocatable_cases=100,
            admin_funds_pool_cents=100000,
            order_window_open_at="2026-08-05T00:00:00Z",
            order_window_close_at="2026-08-05T00:00:00Z",
        ),
        headers=fx.ADMIN,
    )
    bad_size = api.create_household_distribution(
        f.household_distribution_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            household_size=21,
            declared_monthly_income_cents=100000,
            cases_distributed=1,
            distribution_date="2026-08-01",
        ),
        headers=make_agency_coordinator_headers(NON_EXISTENT_UUID),
    )

    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 422)
    validate_error(bad_window, ApiErrorId.ERR_INVALID_REQUEST, 422)
    validate_error(bad_size, ApiErrorId.ERR_INVALID_REQUEST, 422)
    for response, label in (
        (api.list_commodities(headers=fx.ADMIN), "commodity"),
        (api.list_allocation_cycles(headers=fx.ADMIN), "allocation cycle"),
        (api.list_household_distributions(headers=fx.ADMIN), "household distribution"),
    ):
        _rows, meta = fx.list_rows_and_meta(response)
        assert meta["total_count"] == 0, (
            f"no {label} row may exist but total_count is {meta['total_count']}"
        )


def test_10_a_commodity_carries_no_version_and_no_updated_at(api):
    """PRD §2.5: "A commodity is immutable configuration once created, so it carries only
    `id` and `created_at`: both `updated_at` and `version` are absent from a commodity
    representation entirely."

    Design: Corner/entities/commodity_is_immutable_with_no_update_endpoint_and_no_version_field
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    created = fx.create_bulk_rice(api)

    commodity = get_success_data(
        api.get_commodity(
            created["id"], headers=make_warehouse_operator_headers(NON_EXISTENT_UUID)
        )
    )

    assert_fields_absent(commodity, ["version", "updated_at"], "Commodity")
    assert commodity["entitlement_value_cents_per_case"] == 1200, (
        "entitlement_value_cents_per_case expected 1200 but got "
        f"{commodity['entitlement_value_cents_per_case']}"
    )
    assert_commodity(commodity)


def test_11_lot_codes_are_unique_per_warehouse_and_warehouse_names_globally(api):
    """PRD §2.10: "24. Uniqueness: `code` on `Commodity`, `name` on `Warehouse`,
    `county_code` on `ServiceArea`, and `cycle_code` on `AllocationCycle` are each unique
    program-wide, and `federal_lot_code` is unique within a warehouse — all answering
    `ERR_DUPLICATE_CODE`; at most one open recall exists per source lot —
    `ERR_RECALL_ALREADY_OPEN`; at most one recall action exists per recall-and-agency pair —
    `ERR_DUPLICATE_RECALL_ACTION`." PRD §3.3: "When a federal truck arrives, a `StateAdmin`
    records an **inventory lot**: the `commodity_id` received, the `warehouse_id` that
    received it, the `federal_lot_code` from the bill of lading (1 to 40 characters, unique
    within that warehouse, a repeat answering `ERR_DUPLICATE_CODE`), a `cases_received`
    count greater than zero, and the two shelf dates `pack_date` and `best_by_date`, the
    latter of which must be strictly after the former."

    Design: Corner/entities/duplicate_code_creations_are_refused_across_all_five_unique_keys
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    rice = fx.create_bulk_rice(api)
    north = fx.create_warehouse(api, name="WH North")
    south = fx.create_warehouse(
        api,
        name="WH South",
        dock_count=1,
        dry_pallet_capacity=50,
        cold_pallet_capacity=0,
        frozen_pallet_capacity=0,
    )
    fx.create_inventory_lot(
        api,
        rice["id"],
        north["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )

    def _second_lot(warehouse_id):
        return api.create_inventory_lot(
            f.inventory_lot_payload(
                rice["id"],
                warehouse_id,
                federal_lot_code="FL-1001",
                cases_received=20,
                pack_date="2026-07-02",
                best_by_date="2028-01-02",
            ),
            headers=fx.ADMIN,
        )

    validate_error(_second_lot(north["id"]), ApiErrorId.ERR_DUPLICATE_CODE, 409)
    twin = validate_success(_second_lot(south["id"]), 201)
    assert twin["warehouse_id"] == south["id"], (
        f"the twin lot must live at WH South but got {twin['warehouse_id']}"
    )
    validate_error(
        api.create_warehouse(
            f.warehouse_payload(
                name="WH North",
                dock_count=3,
                dry_pallet_capacity=10,
                cold_pallet_capacity=0,
                frozen_pallet_capacity=0,
            ),
            headers=fx.ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE,
        409,
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_inventory_lots(headers=fx.ADMIN, params={"warehouse_id": north["id"]})
    )
    assert meta["total_count"] == 1, (
        f"WH North must still hold exactly one lot but total_count is {meta['total_count']}"
    )


def test_12_an_unknown_service_area_in_the_body_is_a_not_found(api):
    """PRD §2.6: "Foreign keys supplied in a body — `service_area_id`, `agency_id`,
    `cycle_id`, `commodity_id`, `warehouse_id`, `from_lot_id`, `source_lot_id`,
    `to_agency_id`, `order_id` — are then resolved, again yielding the not-found code
    matching the entity that could not be found." PRD §2.10: "5. Every foreign key supplied
    in the request body resolves — the matching not-found code."

    Design: Corner/entities/create_agency_under_unknown_service_area_returns_service_area_not_found
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    response = api.create_agency(
        f.agency_payload(
            NON_EXISTENT_UUID, name="Agency Orphan", cold_storage_pallet_capacity=5
        ),
        headers=fx.ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND, 404)
    _rows, meta = fx.list_rows_and_meta(api.list_agencies(headers=fx.ADMIN))
    assert meta["total_count"] == 0, (
        f"no orphan agency may have been created but total_count is {meta['total_count']}"
    )
