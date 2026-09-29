"""Entity-surface corners: creation, read-back, listing, defaults and typing."""
import pytest

from test_helpers import (
    AM_HEADERS,
    PA_HEADERS,
    WH_HEADERS,
    NON_EXISTENT_UUID,
    add_reading,
    add_spot_hop_line,
    approve_credit,
    confirm_order,
    create_brewer,
    create_malt_product,
    create_order,
    create_strain,
    create_variety,
    create_zone,
    depart_shipment,
    get_shipment,
    is_valid_uuid,
    make_brewer_headers,
    pick_order,
    pin_clock,
    stage_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

UNUSED_LOT_ID = "00000000-0000-4000-8000-000000000404"
UNUSED_ORDER_ID = "00000000-0000-4000-8000-0000000005a1"
UNUSED_VARIETY_ID = "00000000-0000-4000-8000-0000000005b2"


def test_a_new_brewery_arrives_with_its_whole_computed_ledger_populated(
        api, credit_manager_headers, brewer_headers):
    """A 60,000 lb volume seed rates TIER_2 immediately, on an empty order set.

    PRD §3.1: "From that total, `freight_program_tier` is `TIER_3` when the
    trailing volume is at least 120,000 pounds, otherwise `TIER_2` when it is at
    least 40,000 pounds, otherwise `TIER_1`; the comparison is a plain "at least"
    on the summed poundage with no rounding."

    Design: Corner/entities/brewer_creation_echoes_input_and_seeds_the_computed_credit_ledger
    """
    pin_clock()
    created = validate_success(api.create_brewer(
        {"name": "Corner Creation Brewing", "brewery_license_no": "BR-1001",
         "credit_terms_days": 45, "credit_limit_cents": 2500000,
         "cold_chain_certified": True, "legacy_trailing_lbs": 60000},
        credit_manager_headers), expected_status=201)

    assert created["name"] == "Corner Creation Brewing", (
        f"the trade name is echoed, got {created['name']}")
    assert created["brewery_license_no"] == "BR-1001", (
        f"the licence is echoed, got {created['brewery_license_no']}")
    assert created["credit_terms_days"] == 45, (
        f"45-day terms are honoured, got {created['credit_terms_days']}")
    assert created["credit_limit_cents"] == 2500000, (
        f"the supplied limit is stored, got {created['credit_limit_cents']}")
    assert created["cold_chain_certified"] is True, (
        f"the dock is certified, got {created['cold_chain_certified']}")

    assert created["ar_balance_cents"] == 0, (
        f"the receivable starts at zero, got {created['ar_balance_cents']}")
    assert created["open_order_exposure_cents"] == 0, (
        f"there are no orders yet, got {created['open_order_exposure_cents']}")
    assert created["credit_exposure_cents"] == 0, (
        f"total exposure starts at zero, got {created['credit_exposure_cents']}")
    assert created["credit_utilization_pct"] == pytest.approx(0.00, abs=0.005), (
        f"utilisation starts at zero, got {created['credit_utilization_pct']}")
    assert created["credit_status"] == "GOOD_STANDING", (
        f"an empty ledger is in good standing, got {created['credit_status']}")

    assert created["legacy_trailing_lbs"] == 60000, (
        f"the seed is stored, got {created['legacy_trailing_lbs']}")
    assert created["trailing_12mo_volume_lbs"] == 60000, (
        "the seed counts immediately with no DELIVERED orders, got "
        f"{created['trailing_12mo_volume_lbs']}")
    assert created["freight_program_tier"] == "TIER_2", (
        "60000 lbs clears 40,000 and falls short of 120,000, so the tier is not "
        f"the TIER_1 default, got {created['freight_program_tier']}")
    assert created["version"] == 1, (
        f"version starts at 1 on creation, got {created['version']}")
    assert created["created_at"].startswith("2026-08-01T00:00:00"), (
        f"the row is stamped with the logical clock, got {created['created_at']}")
    assert is_valid_uuid(created["id"]), (
        f"the id is a server-minted UUID, got {created['id']}")


def test_a_hop_variety_reads_back_field_for_field_without_advancing_version(
        api, brewer_headers, credit_manager_headers):
    """Two-place decimals survive the round trip and a GET is not a mutation.

    PRD §2.5: "`version` as an integer that starts at 1 on creation and
    increments by exactly one on every mutation of that resource, including
    mutations that only rewrite derived fields such as a recomputed `total_cents`
    or `credit_status`"

    Design: Corner/entities/hop_variety_retrieval_returns_the_stored_row_unchanged
    """
    pin_clock()
    created = validate_success(api.create_hop_variety(
        {"variety_code": "CITRA", "name": "Citra",
         "substitution_group": "AROMA_HIGH_ALPHA", "alpha_acid_target_pct": 12.50,
         "spot_price_cents_per_lb": 51.00, "available_spot_lbs": 20000,
         "cold_storage_required": True, "pallet_quantity_lbs": 880,
         "min_order_lbs": 44}, AM_HEADERS), expected_status=201)

    read = validate_success(api.get_hop_variety(created["id"], brewer_headers))
    assert read["variety_code"] == "CITRA", (
        f"the trade code reads back, got {read['variety_code']}")
    assert read["name"] == "Citra", f"the name reads back, got {read['name']}"
    assert read["substitution_group"] == "AROMA_HIGH_ALPHA", (
        f"the family reads back, got {read['substitution_group']}")
    assert read["alpha_acid_target_pct"] == pytest.approx(12.50, abs=0.005), (
        f"12.50 keeps its scale, got {read['alpha_acid_target_pct']}")
    assert read["spot_price_cents_per_lb"] == pytest.approx(51.00, abs=0.005), (
        f"51.00 keeps its scale, got {read['spot_price_cents_per_lb']}")
    assert read["available_spot_lbs"] == 20000, (
        f"the floor inventory reads back, got {read['available_spot_lbs']}")
    assert read["cold_storage_required"] is True, (
        f"the reefer flag reads back, got {read['cold_storage_required']}")
    assert read["pallet_quantity_lbs"] == 880, (
        f"the pallet size reads back, got {read['pallet_quantity_lbs']}")
    assert read["min_order_lbs"] == 44, (
        f"the line minimum reads back, got {read['min_order_lbs']}")
    assert read["version"] == 1, (
        f"a GET is not a mutation, got version {read['version']}")

    for headers in (AM_HEADERS, credit_manager_headers, WH_HEADERS, PA_HEADERS):
        other = validate_success(api.get_hop_variety(created["id"], headers))
        assert other == read, (
            "the catalogue read is identical for every desk, got a different "
            f"body for headers {headers}")


def test_a_three_order_listing_pages_with_stable_total_count_and_has_more(
        api, credit_manager_headers):
    """limit 2 splits three orders into a full page and a remainder.

    PRD §2.3: "Both are echoed in the envelope's `meta` object alongside
    `total_count` (the number of rows matching the filter before pagination is
    applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/sales_order_listing_paginates_with_total_count_and_has_more
    """
    pin_clock()
    brewer = create_brewer(name="Pagination Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    first_order = create_order(brewer["id"],
                               requested_ship_date="2026-09-01T00:00:00Z",
                               purchase_order_ref="PO-P1")
    middle_order = create_order(brewer["id"],
                                requested_ship_date="2026-09-02T00:00:00Z",
                                purchase_order_ref="PO-P2")
    last_order = create_order(brewer["id"],
                              requested_ship_date="2026-09-03T00:00:00Z",
                              purchase_order_ref="PO-P3")

    page_one, meta_one = validate_paginated(api.list_sales_orders(
        AM_HEADERS, params={"brewer_id": brewer["id"], "limit": 2, "offset": 0}))
    assert meta_one["total_count"] == 3, (
        f"the unpaged match count is 3, got {meta_one['total_count']}")
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0, (
        f"the page parameters are echoed, got {meta_one['limit']} and "
        f"{meta_one['offset']}")
    assert meta_one["has_more"] is True, (
        f"a third row remains beyond this page, got {meta_one['has_more']}")
    assert len(page_one) == 2, f"exactly two rows are returned, got {len(page_one)}"
    assert page_one[0]["id"] == first_order["id"], (
        "rows are ordered by created_at ascending, got "
        f"{page_one[0]['purchase_order_ref']} first")
    assert page_one[1]["id"] == middle_order["id"], (
        f"the second row is PO-P2, got {page_one[1]['purchase_order_ref']}")

    page_two, meta_two = validate_paginated(api.list_sales_orders(
        AM_HEADERS, params={"brewer_id": brewer["id"], "limit": 2, "offset": 2}))
    assert meta_two["total_count"] == 3, (
        f"the total is unaffected by paging, got {meta_two['total_count']}")
    assert meta_two["offset"] == 2 and meta_two["has_more"] is False, (
        f"the last page reports no remainder, got offset {meta_two['offset']} "
        f"has_more {meta_two['has_more']}")
    assert [row["id"] for row in page_two] == [last_order["id"]], (
        f"only the third order remains, got {len(page_two)} rows")

    unpaged, meta_all = validate_paginated(api.list_sales_orders(
        AM_HEADERS, params={"brewer_id": brewer["id"]}))
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0, (
        "the declared defaults are applied, got "
        f"{meta_all['limit']} and {meta_all['offset']}")
    assert meta_all["total_count"] == 3 and meta_all["has_more"] is False, (
        f"all three fit on one default page, got {meta_all['total_count']} rows "
        f"has_more {meta_all['has_more']}")
    assert len(unpaged) == 3, f"three rows are returned, got {len(unpaged)}"
    assert all(row["brewer_id"] == brewer["id"] for row in unpaged), (
        "every row belongs to the filtered brewery")


def test_an_unused_but_well_formed_lot_id_reports_the_segment_specific_404(
        api, warehouse_operator_headers):
    """A valid UUID that names nothing is a 404 with the lot's own code.

    PRD §2.8: "`ERR_MALT_LOT_NOT_FOUND` for a lot path identifier or
    `malt_lot_id`"

    Design: Corner/entities/malt_lot_fetch_with_unknown_id_returns_not_found
    """
    pin_clock()
    error = validate_error(api.get_malt_lot(UNUSED_LOT_ID,
                                            warehouse_operator_headers),
                          "ERR_MALT_LOT_NOT_FOUND", expected_status=404)
    assert error["error_id"] == "ERR_MALT_LOT_NOT_FOUND", (
        f"the lot's own code is reported, got {error['error_id']}")
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"the message is a non-empty human-readable string, got {error['message']!r}")

    _, meta = validate_paginated(api.list_malt_lots(warehouse_operator_headers))
    assert meta["total_count"] == 0, (
        f"the failed read created nothing, got {meta['total_count']} lots")


def test_omitting_a_required_field_fails_at_the_request_shape_band(
        api, credit_manager_headers):
    """No licence means ERR_INVALID_REQUEST, and an optional omission does not.

    PRD §2.8: "**Request shape** (priority 4): every required body field
    present, every field of the declared type, every enum field carrying a
    declared member, every quantity, poundage, pallet count and money amount
    non-negative, no decimal exceeding its declared scale, and every version
    field an integer. Violations are reported as `ERR_INVALID_REQUEST` (HTTP
    400)."

    Design: Corner/entities/brewer_create_missing_licence_returns_invalid_request
    """
    pin_clock()
    validate_error(api.create_brewer(
        {"name": "No Licence Brewing", "credit_terms_days": 30},
        credit_manager_headers), "ERR_INVALID_REQUEST", expected_status=400)
    validate_error(api.create_brewer(
        {"brewery_license_no": "BR-1002B", "credit_terms_days": 30},
        credit_manager_headers), "ERR_INVALID_REQUEST", expected_status=400)
    validate_error(api.get_brewer(NON_EXISTENT_UUID, credit_manager_headers),
                   "ERR_BREWER_NOT_FOUND", expected_status=404)

    accepted = validate_success(api.create_brewer(
        {"name": "Optional Omission Brewing",
         "brewery_license_no": "BR-1002C"},
        credit_manager_headers), expected_status=201)
    assert accepted["credit_limit_cents"] == 500000, (
        "omitting an optional field is accepted and defaulted, got "
        f"{accepted['credit_limit_cents']}")


def test_every_declared_brewery_default_materialises_from_a_two_field_payload(
        api, credit_manager_headers):
    """Name and licence alone produce 30-day terms, a 500000 limit and TIER_1.

    PRD §3.1: "`credit_terms_days`, the net payment terms granted, which must be
    one of `0`, `15`, `30` or `45` and defaults to 30; `credit_limit_cents`, the
    ceiling on credit exposure, which must be at least 1 and defaults to 500000;
    `cold_chain_certified`, true when the brewery's dock is certified to receive
    refrigerated freight, defaulting to false; and `legacy_trailing_lbs`, a
    migrated pre-platform shipped poundage that must be zero or greater and
    defaults to 0."

    Design: Corner/entities/brewer_defaults_applied_when_optional_inputs_are_omitted
    """
    pin_clock()
    created = validate_success(api.create_brewer(
        {"name": "Default Values Brewing", "brewery_license_no": "BR-1003"},
        credit_manager_headers), expected_status=201)

    assert created["credit_terms_days"] == 30, (
        f"terms default to 30 days, got {created['credit_terms_days']}")
    assert created["credit_limit_cents"] == 500000, (
        f"the limit defaults to 500000, got {created['credit_limit_cents']}")
    assert created["cold_chain_certified"] is False, (
        f"certification defaults to false, got {created['cold_chain_certified']}")
    assert created["legacy_trailing_lbs"] == 0, (
        f"the volume seed defaults to 0, got {created['legacy_trailing_lbs']}")
    assert created["trailing_12mo_volume_lbs"] == 0, (
        f"there is no trailing volume, got {created['trailing_12mo_volume_lbs']}")
    assert created["freight_program_tier"] == "TIER_1", (
        f"zero volume rates TIER_1, got {created['freight_program_tier']}")
    assert created["credit_status"] == "GOOD_STANDING", (
        f"an empty ledger is in good standing, got {created['credit_status']}")
    assert created["credit_utilization_pct"] == pytest.approx(0.00, abs=0.005), (
        f"utilisation is 0.00, got {created['credit_utilization_pct']}")


def test_smuggled_system_fields_are_discarded_while_declared_inputs_are_kept(
        api, credit_manager_headers):
    """An id, a version and two statuses in the body are ignored, not honoured.

    PRD §2.5: "Every resource carries a server-minted `id`: a UUID string with no
    type prefix, generated by the server and never accepted from the client."

    Design: Corner/entities/order_system_fields_are_server_minted_and_client_values_are_ignored_input
    """
    pin_clock()
    brewer = create_brewer(name="System Field Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    created = validate_success(api.create_sales_order(
        {"brewer_id": brewer["id"],
         "requested_ship_date": "2026-09-15T00:00:00Z",
         "purchase_order_ref": "PO-SF",
         "id": "11111111-1111-4111-8111-111111111111",
         "version": 99, "fulfillment_status": "DELIVERED",
         "credit_status": "APPROVED", "total_cents": 123456},
        make_brewer_headers(brewer["id"])), expected_status=201)

    assert created["id"] != "11111111-1111-4111-8111-111111111111", (
        f"the client id must not be honoured, got {created['id']}")
    assert is_valid_uuid(created["id"]), (
        f"a fresh server UUID is minted instead, got {created['id']}")
    assert created["version"] == 1, (
        f"version starts at 1, not the smuggled 99, got {created['version']}")
    assert created["fulfillment_status"] == "DRAFT", (
        f"the smuggled fulfillment status is ignored, got "
        f"{created['fulfillment_status']}")
    assert created["credit_status"] == "PENDING_REVIEW", (
        f"the smuggled credit status is ignored, got {created['credit_status']}")
    assert created["total_cents"] == 0 and created["subtotal_cents"] == 0, (
        "the smuggled money is ignored, got total "
        f"{created['total_cents']} subtotal {created['subtotal_cents']}")
    assert created["line_count"] == 0, (
        f"a fresh order has no lines, got {created['line_count']}")
    assert created["fee_variant"] is None, (
        f"no fee variant is assessed yet, got {created['fee_variant']}")
    assert created["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at is the logical clock, got {created['created_at']}")
    assert created["updated_at"].startswith("2026-08-01T00:00:00"), (
        f"updated_at is the logical clock, got {created['updated_at']}")
    assert created["purchase_order_ref"] == "PO-SF", (
        "a declared input field IS honoured, proving the rejection is "
        f"selective, got {created['purchase_order_ref']}")


def test_an_undeclared_fermentation_type_is_refused_rather_than_defaulted(
        api, warehouse_operator_headers):
    """WILD is not a declared member, and neither is a three-place price.

    PRD §3.7: "a `fermentation_type` of either `ALE` or `LAGER`, the whole-day
    `propagation_lead_time_days` of bench time required (at least 1), and a spot
    `list_price_cents_per_l` in cents per litre of slurry, greater than zero at
    two decimal places"

    Design: Corner/entities/yeast_strain_invalid_enum_fermentation_type_rejected
    """
    pin_clock()
    wild = {"strain_code": "WLP650", "name": "Brettanomyces Bruxellensis",
            "fermentation_type": "WILD", "propagation_lead_time_days": 14,
            "list_price_cents_per_l": 1500.00}
    validate_error(api.create_yeast_strain(wild, warehouse_operator_headers),
                   "ERR_INVALID_REQUEST", expected_status=400)
    validate_error(api.get_yeast_strain(NON_EXISTENT_UUID,
                                        warehouse_operator_headers),
                   "ERR_YEAST_STRAIN_NOT_FOUND", expected_status=404)

    negative_lead = dict(wild, fermentation_type="ALE",
                         propagation_lead_time_days=-1)
    validate_error(api.create_yeast_strain(negative_lead,
                                           warehouse_operator_headers),
                   "ERR_INVALID_REQUEST", expected_status=400)
    over_scale = dict(wild, fermentation_type="ALE",
                      list_price_cents_per_l=1500.005)
    validate_error(api.create_yeast_strain(over_scale,
                                           warehouse_operator_headers),
                   "ERR_INVALID_REQUEST", expected_status=400)

    lager = validate_success(api.create_yeast_strain(
        dict(wild, fermentation_type="LAGER"), warehouse_operator_headers),
        expected_status=201)
    assert lager["fermentation_type"] == "LAGER", (
        f"a declared member is accepted, got {lager['fermentation_type']}")
    assert lager["viability_pct_at_ship"] == pytest.approx(92.0, abs=0.005), (
        f"viability defaults to 92.0, got {lager['viability_pct_at_ship']}")
    assert lager["cells_per_ml_slurry_billion"] == pytest.approx(1.2, abs=0.005), (
        f"slurry density defaults to 1.2, got {lager['cells_per_ml_slurry_billion']}")
    assert lager["min_batch_l"] == pytest.approx(20.0, abs=0.0005), (
        f"the bench minimum defaults to 20.0, got {lager['min_batch_l']}")
    assert lager["vessel_max_l"] == pytest.approx(2000.0, abs=0.0005), (
        f"the vessel ceiling defaults to 2000.0, got {lager['vessel_max_l']}")


def test_a_temperature_reading_carries_no_version_and_no_updated_at(
        api, warehouse_operator_headers):
    """The one entity outside the audit triple, and the only correction is an append.

    PRD §2.5: "The single exception is the temperature reading: a
    `TemperatureReading` is an append-only telemetry event and carries only `id`
    and `created_at`. It has **no** `updated_at` and **no** `version`, because
    nothing ever modifies a reading once it is filed."

    Design: Corner/entities/temperature_reading_is_immutable_with_no_version_and_no_writer
    """
    pin_clock()
    brewer = create_brewer(name="Immutable Reading Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-12T00:00:00Z",
                         purchase_order_ref="PO-IR")
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"])
    pick_order(order["id"])
    shipment = stage_shipment(order["id"], zone["id"], pallet_count=1,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z",
                              reefer_tolerance_c=2.00)
    depart_shipment(shipment["id"])

    reading = add_reading(shipment["id"], 2.00, "2026-08-01T10:00:00Z")
    assert "version" not in reading, (
        f"a reading has no version, got {reading.get('version')}")
    assert "updated_at" not in reading, (
        f"a reading has no updated_at, got {reading.get('updated_at')}")
    assert reading["cold_chain_shipment_id"] == shipment["id"], (
        f"the reading is stored against its load, got "
        f"{reading['cold_chain_shipment_id']}")
    assert reading["interval_minutes"] == 0, (
        f"the first reading closes no interval, got {reading['interval_minutes']}")
    assert reading["in_violation"] is False, (
        f"2.0 sits inside the 0.0 to 4.0 band, got {reading['in_violation']}")
    assert reading["cumulative_excursion_minutes"] == 0, (
        f"nothing has accrued, got {reading['cumulative_excursion_minutes']}")
    assert reading["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at is the logical clock, got {reading['created_at']}")
    assert reading["recorded_at"].startswith("2026-08-01T10:00:00"), (
        "recorded_at is the reported sampling instant, independent of the "
        f"clock, got {reading['recorded_at']}")

    rows, meta = validate_paginated(api.list_readings(shipment["id"],
                                                      warehouse_operator_headers))
    assert meta["total_count"] == 1, (
        f"the series holds one sample, got {meta['total_count']}")
    assert rows[0]["id"] == reading["id"], (
        f"the listed row is the appended reading, got {rows[0]['id']}")

    load = get_shipment(shipment["id"])
    assert load["reading_count"] == 1, (
        f"the load tracks the series length, got {load['reading_count']}")
    assert load["last_reading_at"].startswith("2026-08-01T10:00:00"), (
        f"the load tracks the latest sample, got {load['last_reading_at']}")
    assert load["excursion_minutes"] == 0, (
        f"an in-tolerance sample accrues nothing, got {load['excursion_minutes']}")


def test_a_bad_path_order_id_outranks_the_bad_variety_id_in_the_body(
        api, allocation_manager_headers):
    """Priority 5 reports the parent before priority 7 looks at the body.

    PRD §2.8: "Within band 3, path identifiers are resolved strictly left to
    right: an outer identifier is reported before an inner one."

    Design: Corner/entities/order_line_create_under_unknown_parent_order_returns_not_found
    """
    pin_clock()
    error = validate_error(api.add_order_line(
        UNUSED_ORDER_ID,
        {"item_type": "HOP", "quantity": 880, "uom": "LB",
         "allocation_source": "SPOT", "hop_variety_id": UNUSED_VARIETY_ID},
        allocation_manager_headers), "ERR_SALES_ORDER_NOT_FOUND",
        expected_status=404)
    assert error["error_id"] != "ERR_HOP_VARIETY_NOT_FOUND", (
        "the body identifier is only checked at priority 7, after the path")

    _, meta = validate_paginated(api.list_order_lines(allocation_manager_headers))
    assert meta["total_count"] == 0, (
        f"the refused create persisted no line, got {meta['total_count']}")


def test_a_real_id_in_the_wrong_slot_reports_the_slot_that_failed(
        api, warehouse_operator_headers):
    """A yeast id offered as a malt product is absent as far as that slot cares.

    PRD §2.8: "Identifiers supplied in a request body or query string are checked
    at priority 7, after the `Brewer` scope check at priority 6, and each reports
    the not-found code for the entity it names"

    Design: Corner/entities/recipe_create_with_a_yeast_id_in_the_malt_product_slot_returns_not_found
    """
    pin_clock()
    brewer = create_brewer(name="Flat Topology Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    payload = {"brewer_id": brewer["id"], "malt_product_id": strain["id"],
               "yeast_strain_id": strain["id"], "name": "Cross Wired Ale",
               "batch_volume_bbl": 30.0, "original_gravity_plato": 12.50,
               "target_color_lovibond": 2.50, "target_extract_pct": 80.00,
               "target_protein_pct": 11.00,
               "requested_pitch_rate_million_cells_per_ml_per_plato": 0.75,
               "adjunct_pct": 0.0}

    validate_error(api.create_brewer_recipe(
        payload, make_brewer_headers(brewer["id"])),
        "ERR_MALT_PRODUCT_NOT_FOUND", expected_status=404)

    _, meta = validate_paginated(api.list_brewer_recipes(
        make_brewer_headers(brewer["id"]), params={"brewer_id": brewer["id"]}))
    assert meta["total_count"] == 0, (
        f"the refused create persisted no recipe, got {meta['total_count']}")

    fixed = validate_success(api.create_brewer_recipe(
        dict(payload, malt_product_id=product["id"]),
        make_brewer_headers(brewer["id"])), expected_status=201)
    assert fixed["malt_product_id"] == product["id"], (
        f"the corrected slot resolves, got {fixed['malt_product_id']}")
    assert fixed["adjunct_pct"] == pytest.approx(0.0, abs=0.005), (
        f"the adjunct share is stored as supplied, got {fixed['adjunct_pct']}")
