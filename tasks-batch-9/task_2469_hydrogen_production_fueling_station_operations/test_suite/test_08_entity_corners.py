"""Entity-level corners: creation defaults, computed fields, 404 identity and listing."""

import pytest
from test_helpers import (
    ADMIN,
    ANALYST,
    DISPATCHER,
    ENGINEER,
    HALF_LIMIT_PURITY,
    NON_EXISTENT_UUID,
    api_client,
    assert_inventory_ledger_entry,
    commission_vessel,
    create_funding_agreement,
    create_power_supply_contract,
    create_production_asset,
    create_production_lot,
    create_station,
    funding_agreement_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_meta,
    list_rows,
    power_supply_contract_payload,
    production_asset_payload,
    production_lot_payload,
    purity_test_payload,
    read_ledger,
    read_station,
    set_clock,
    station_payload,
    tube_trailer_delivery_payload,
    validate_error,
    validate_success,
)

AGREEMENT = {
    "funder_name": "State Clean Transport Fund",
    "min_uptime_pct": 99.000,
    "penalty_per_point_cents": 250000,
    "initial_holdback_cents": 500000,
    "uptime_method": "NOZZLE_WEIGHTED",
}
BIRTH_STATION = {
    "nozzle_count": 4,
    "offload_bay_count": 2,
    "storage_capacity_kg": 900.000,
    "reserve_floor_kg": 100.000,
    "max_pressure_class": "H70",
    "setback_compliant": True,
}
SMALL_STATION = {
    "nozzle_count": 2,
    "offload_bay_count": 2,
    "storage_capacity_kg": 900.000,
    "reserve_floor_kg": 20.000,
    "max_pressure_class": "H35",
    "setback_compliant": True,
}
HIGH_VESSEL = {
    "bank_tier": "HIGH",
    "water_volume_l": 600.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 200.00,
    "initial_pressure_bar": 950.00,
    "next_inspection_due_date": "2027-06-30",
}
LOW_VESSEL = {
    "bank_tier": "LOW",
    "water_volume_l": 5000.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 100.00,
    "initial_pressure_bar": 300.00,
    "next_inspection_due_date": "2027-06-30",
}
GRID_CONTRACT = {
    "grid_ci_gco2e_per_mwh": 385000.00,
    "annual_renewable_pct": 50.000,
    "hourly_matched_renewable_pct": 50.000,
    "hourly_matching_enabled": False,
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}


# ─── Recipe builders ──────────────────────────────────────────────────────


def _agreement(code):
    set_clock("2026-08-01T00:00:00Z")
    return create_funding_agreement(agreement_code=code, **AGREEMENT)


def _electrolysis_asset_with_contract(asset_code, contract_code, **contract_overrides):
    asset = create_production_asset(
        asset_code=asset_code,
        pathway="PEM_ELECTROLYSIS",
        nameplate_kg_per_day=1200.000,
        ccs_capture_rate=0.0000,
        operator_org="Harbor H2 Production",
    )
    create_power_supply_contract(
        asset["id"],
        contract_code=contract_code,
        **{**GRID_CONTRACT, **contract_overrides},
    )
    return asset


# ─── Creation seeds derived state ─────────────────────────────────────────


def test_a_new_funding_agreement_holds_its_whole_pool_at_version_one():
    """Nothing is charged before a report is finalised, so the pool is intact.

    "At creation the agreement's live `holdback_balance_cents` equals
    `initial_holdback_cents`, because no penalty has yet been charged."  And
    `version` is "an integer that begins at 1 on creation and increments by one on
    every mutation of the row".

    Design: Corner/entities/funding_agreement_creation_seeds_holdback_and_version
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_funding_agreement(
        funding_agreement_payload(agreement_code="FA-E1", **AGREEMENT), ADMIN
    )

    agreement = validate_success(response, expected_status=201)
    assert agreement["holdback_balance_cents"] == 500000
    assert agreement["initial_holdback_cents"] == 500000
    assert agreement["min_uptime_pct"] == pytest.approx(99.000, abs=0.0005)
    assert agreement["uptime_method"] == "NOZZLE_WEIGHTED"
    assert agreement["version"] == 1
    assert is_valid_uuid(agreement["id"])
    assert is_iso8601_timestamp(agreement["created_at"])
    assert is_iso8601_timestamp(agreement["updated_at"])


def test_a_station_is_born_restricted_because_its_high_bank_is_empty():
    """Creation is not a clean OPEN slate: the high-bank floor is unmet from birth.

    "But with no pressure vessels commissioned, `high_bank_deliverable_kg` is 0.000,
    which is below the 10.000 kg high-bank minimum, so posture is computed as
    `RESTRICTED` at birth. `supply_alert` is computed at the same moment."

    Design: Corner/entities/station_creation_is_restricted_at_birth_with_zero_high_bank
    """
    agreement = _agreement("FA-E2")

    response = api_client.create_station(
        station_payload(
            agreement["id"], code="STN-E2", name="Birth State Station", **BIRTH_STATION
        ),
        ADMIN,
    )

    station = validate_success(response, expected_status=201)
    assert station["ventilation_status"] == "NORMAL"
    assert station["leak_detection_status"] == "NORMAL"
    assert station["compressor_status"] == "ONLINE"
    for field in (
        "onsite_inventory_kg",
        "reserved_kg",
        "available_kg",
        "total_deliverable_kg",
        "high_bank_deliverable_kg",
        "inbound_planned_kg",
        "projected_available_kg",
        "metered_kg_mtd",
    ):
        assert station[field] == pytest.approx(0.000, abs=0.001), field
    assert station["supply_alert"] is True, "0.000 kg is below the 100.000 kg floor"
    assert station["safety_posture"] == "RESTRICTED"
    assert station["metering_accuracy_flag"] == "WITHIN_TOLERANCE"
    assert station["version"] == 1


def test_omitted_optional_inputs_take_their_declared_defaults():
    """Four defaults on three entities are applied when the field is left out.

    "An optional `setback_compliant` flag records whether the station currently
    satisfies its permitted setback distances and defaults to true."  The capture
    rate "defaults to 0", `hourly_matching_enabled` is "an optional
    `hourly_matching_enabled` flag defaulting to false", and on a lot "Feedstock
    defaults to 0" while "Carryover defaults to 0".

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    agreement = _agreement("FA-E3")
    station_request = station_payload(
        agreement["id"],
        code="STN-E3",
        name="Default Station",
        nozzle_count=2,
        offload_bay_count=1,
        storage_capacity_kg=900.000,
        reserve_floor_kg=50.000,
        max_pressure_class="H35",
    )
    asset_request = production_asset_payload(
        asset_code="PA-E3-1",
        pathway="PEM_ELECTROLYSIS",
        nameplate_kg_per_day=1200.000,
        operator_org="Harbor H2 Production",
    )
    assert "setback_compliant" not in station_request
    assert "ccs_capture_rate" not in asset_request
    station = validate_success(
        api_client.create_station(station_request, ADMIN), expected_status=201
    )
    asset = validate_success(
        api_client.create_production_asset(asset_request, ENGINEER), expected_status=201
    )
    contract_request = power_supply_contract_payload(
        asset["id"],
        contract_code="PSC-E3-1",
        grid_ci_gco2e_per_mwh=385000.00,
        annual_renewable_pct=0.000,
        hourly_matched_renewable_pct=0.000,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )
    contract_request.pop("hourly_matching_enabled")
    lot_request = production_lot_payload(
        asset["id"],
        lot_code="LOT-E3-1",
        mass_kg=1000.000,
        energy_consumed_kwh=0.0,
        production_start_at="2026-07-20T00:00:00Z",
        production_end_at="2026-07-21T00:00:00Z",
    )
    assert "feedstock_consumed_mmbtu" not in lot_request
    assert "carryover_kg" not in lot_request

    contract = validate_success(
        api_client.create_power_supply_contract(asset["id"], contract_request, ENGINEER),
        expected_status=201,
    )
    lot = validate_success(
        api_client.create_production_lot(lot_request, ENGINEER), expected_status=201
    )

    assert station["setback_compliant"] is True
    assert asset["ccs_capture_rate"] == pytest.approx(0, abs=0.00005)
    assert contract["hourly_matching_enabled"] is False
    assert lot["feedstock_consumed_mmbtu"] == pytest.approx(0, abs=0.001)
    assert lot["carryover_kg"] == pytest.approx(0, abs=0.001)
    assert lot["ci_provisional_gco2e_per_mj"] == pytest.approx(2.50, abs=0.005), (
        "with no electricity and no feedstock only the 300 g per kg compression adder remains"
    )
    assert lot["ci_variant_applied"] is None


# ─── Schema validation refuses before anything is written ─────────────────


def test_a_station_without_a_nozzle_count_is_a_schema_failure():
    """A required field with no default cannot be defaulted away.

    "Schema validation covers required fields, correct types, valid enum members,
    numeric ranges and declared decimal precision, and pagination bounds"  and "Any
    of these failing yields `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/station_create_with_missing_nozzle_count_rejected
    """
    agreement = _agreement("FA-E4")

    request = station_payload(
        agreement["id"], code="STN-E4", name="Incomplete Station", **SMALL_STATION
    )
    request.pop("nozzle_count")

    response = api_client.create_station(request, ADMIN)

    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)
    listing = api_client.list_stations(ADMIN, params={"limit": 10, "offset": 0})
    assert list_meta(listing)["total_count"] == 0, "no partial row was persisted"


@pytest.mark.parametrize(
    "code,overrides,why",
    [
        ("FA-E5a", {"uptime_method": "MONTHLY_AVERAGE"}, "enum membership"),
        ("FA-E5b", {"min_uptime_pct": 120.000}, "numeric range"),
    ],
)
def test_an_agreement_failing_enum_or_range_is_rejected(code, overrides, why):
    """Enum membership and numeric range are both schema constraints.

    "The uptime floor is a percentage between 0 and 100 inclusive carried to three
    decimal places" and the method is "either `NOZZLE_WEIGHTED` or `STATION_LEVEL`".
    "Any of these failing yields `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/funding_agreement_with_invalid_uptime_method_enum_rejected
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_funding_agreement(
        funding_agreement_payload(agreement_code=code, **{**AGREEMENT, **overrides}), ADMIN
    )

    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)
    listing = api_client.list_funding_agreements(ADMIN, params={"limit": 10, "offset": 0})
    assert list_meta(listing)["total_count"] == 0, f"{why} is enforced before any write"


def test_every_aggregate_root_reports_its_own_not_found_error():
    """One unknown UUID produces ten different entity-specific 404 codes.

    "Each entity type has its own 404: `ERR_STATION_NOT_FOUND`,
    `ERR_FUNDING_AGREEMENT_NOT_FOUND`, `ERR_PRESSURE_VESSEL_NOT_FOUND`,
    `ERR_PRODUCTION_ASSET_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`,
    `ERR_DELIVERY_NOT_FOUND`, `ERR_DISPENSE_SESSION_NOT_FOUND`,
    `ERR_SAFETY_EVENT_NOT_FOUND`, `ERR_INCENTIVE_CLAIM_NOT_FOUND` and
    `ERR_UPTIME_REPORT_NOT_FOUND`."

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found_errors
    """
    set_clock("2026-08-01T00:00:00Z")
    probes = [
        (api_client.get_funding_agreement, "ERR_FUNDING_AGREEMENT_NOT_FOUND"),
        (api_client.get_station, "ERR_STATION_NOT_FOUND"),
        (api_client.get_pressure_vessel, "ERR_PRESSURE_VESSEL_NOT_FOUND"),
        (api_client.get_production_asset, "ERR_PRODUCTION_ASSET_NOT_FOUND"),
        (api_client.get_production_lot, "ERR_PRODUCTION_LOT_NOT_FOUND"),
        (api_client.get_delivery, "ERR_DELIVERY_NOT_FOUND"),
        (api_client.get_dispense_session, "ERR_DISPENSE_SESSION_NOT_FOUND"),
        (api_client.get_safety_event, "ERR_SAFETY_EVENT_NOT_FOUND"),
        (api_client.get_incentive_claim, "ERR_INCENTIVE_CLAIM_NOT_FOUND"),
        (api_client.get_uptime_report, "ERR_UPTIME_REPORT_NOT_FOUND"),
    ]

    for reader, expected in probes:
        validate_error(reader(NON_EXISTENT_UUID, ADMIN), expected, expected_status=404)


# ─── Computed and system-assigned fields ──────────────────────────────────


def test_vessel_stored_mass_and_station_deliverable_mass_differ_by_the_residual():
    """Stored mass counts everything; deliverable mass counts only the headroom.

    "The vessel's `current_pressure_bar` starts at its `initial_pressure_bar`, and
    its `stored_mass_kg` is derived as the current pressure multiplied by the water
    volume multiplied by the mass constant of 0.00008 kilograms per litre per bar,
    rounded half-up to three decimal places."  The station's deliverable figure
    instead subtracts "the vessel's `min_residual_bar` from its
    `current_pressure_bar`".

    Design: Corner/entities/pressure_vessel_stored_mass_computed_from_initial_pressure
    """
    agreement = _agreement("FA-E7")
    station = create_station(
        agreement["id"],
        code="STN-E7",
        name="Vessel Math Station",
        **{**BIRTH_STATION, "reserve_floor_kg": 20.000},
    )

    vessel = commission_vessel(station["id"], **HIGH_VESSEL)

    assert vessel["stored_mass_kg"] == pytest.approx(45.600, abs=0.001)
    assert vessel["current_pressure_bar"] == pytest.approx(950.00, abs=0.01)
    assert vessel["inspection_status"] == "CURRENT"
    assert vessel["inspection_count"] == 0
    assert vessel["last_inspection_date"] is None
    reread = read_station(station["id"])
    assert reread["onsite_inventory_kg"] == pytest.approx(45.600, abs=0.001)
    assert reread["total_deliverable_kg"] == pytest.approx(36.000, abs=0.001)
    assert reread["high_bank_deliverable_kg"] == pytest.approx(36.000, abs=0.001)
    assert reread["safety_posture"] == "OPEN"


def test_the_ledger_numbers_its_own_rows_and_carries_the_running_balance():
    """Commissioning two vessels appends two rows the client never posted.

    "Replay order is pinned: entries are ordered by `occurred_at` ascending, then by
    `sequence_no` ascending, where `sequence_no` is assigned per station in append
    order, beginning at 1 and incrementing by one for each subsequent entry, so that
    the secondary key fully disambiguates entries sharing a single logical-clock
    instant."

    Design: Corner/entities/inventory_ledger_sequence_no_is_system_assigned_and_monotonic
    """
    agreement = _agreement("FA-E8")
    station = create_station(
        agreement["id"],
        code="STN-E8",
        name="Ledger Station",
        **{**BIRTH_STATION, "reserve_floor_kg": 20.000},
    )
    commission_vessel(station["id"], **HIGH_VESSEL)
    commission_vessel(station["id"], **LOW_VESSEL)

    entries = read_ledger(station["id"], params={"limit": 10, "offset": 0})

    assert len(entries) == 2
    for entry in entries:
        assert_inventory_ledger_entry(entry)
        assert entry["reason"] == "OPENING_BALANCE"
        assert entry["source_ref_type"] == "PRESSURE_VESSEL"
        assert entry["occurred_at"].startswith("2026-08-01T00:00:00"), (
            "ledger timestamps read the logical clock, not wall-clock time"
        )
    assert [entry["sequence_no"] for entry in entries] == [1, 2]
    assert entries[0]["delta_kg"] == pytest.approx(45.600, abs=0.001)
    assert entries[0]["resulting_onsite_kg"] == pytest.approx(45.600, abs=0.001)
    assert entries[1]["delta_kg"] == pytest.approx(120.000, abs=0.001)
    assert entries[1]["resulting_onsite_kg"] == pytest.approx(165.600, abs=0.001)
    assert read_station(station["id"])["onsite_inventory_kg"] == pytest.approx(
        165.600, abs=0.001
    )


def test_a_purity_test_is_an_immutable_record_with_no_version_axis():
    """The laboratory row carries only `id` and `created_at` and never drifts.

    "A purity test is an immutable laboratory record: it carries `id` and
    `created_at` and nothing else in the way of common properties — no `updated_at`,
    no `version`."

    Design: Corner/entities/purity_test_is_immutable_and_carries_no_version_axis
    """
    set_clock("2026-08-01T00:00:00Z")
    asset = _electrolysis_asset_with_contract("PA-E9-1", "PSC-E9-1")
    lot = create_production_lot(
        asset["id"],
        lot_code="LOT-E9-1",
        mass_kg=500.000,
        energy_consumed_kwh=26000.0,
        feedstock_consumed_mmbtu=0.000,
        carryover_kg=0.000,
        production_start_at="2026-07-20T00:00:00Z",
        production_end_at="2026-07-21T00:00:00Z",
    )

    created = validate_success(
        api_client.create_purity_test(
            lot["id"],
            purity_test_payload(lot["id"], **HALF_LIMIT_PURITY),
            ANALYST,
        ),
        expected_status=201,
    )

    assert created["performed_by_user_id"] == "QA-1"
    assert "version" not in created, "PurityTest carries no version axis"
    assert "updated_at" not in created, "PurityTest carries no updated_at"
    listing = api_client.list_purity_tests(
        lot["id"], ANALYST, params={"limit": 10, "offset": 0}
    )
    rows = list_rows(listing)
    assert list_meta(listing)["total_count"] == 1
    assert rows[0]["verdict"] == "PASS"
    assert rows[0]["purity_margin_pct"] == pytest.approx(50.000, abs=0.0005), (
        "every analyte sits at exactly half its limit"
    )
    assert rows[0]["failing_analytes"] == []
    assert rows[0]["created_at"] == created["created_at"], "the stored row never drifts"


# ─── Referenced identifiers ───────────────────────────────────────────────


def test_a_lot_naming_an_unknown_asset_reports_the_assets_not_found_error():
    """A body-referenced foreign key resolves after schema validation, not before.

    "Body-referenced identifiers are checked as a group after schema validation:
    `funding_agreement_id`, `station_id`, `production_asset_id`, `production_lot_id`,
    `predecessor_lot_id`, `receiving_vessel_id`, `amended_from_report_id`, and each
    element of `production_lot_ids` must resolve to an existing row, failing with
    that entity's not-found error."

    Design: Corner/entities/production_lot_creation_rejects_unknown_production_asset_id
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_production_lot(
        production_lot_payload(
            NON_EXISTENT_UUID,
            lot_code="LOT-E10-1",
            mass_kg=500.000,
            energy_consumed_kwh=26000.0,
            feedstock_consumed_mmbtu=0.000,
            carryover_kg=0.000,
            production_start_at="2026-07-20T00:00:00Z",
            production_end_at="2026-07-21T00:00:00Z",
        ),
        ENGINEER,
    )

    validate_error(response, "ERR_PRODUCTION_ASSET_NOT_FOUND", expected_status=404)
    listing = api_client.list_production_lots(ENGINEER, params={"limit": 10, "offset": 0})
    assert list_meta(listing)["total_count"] == 0


def test_a_receiving_vessel_belonging_to_another_station_is_refused():
    """Both rows exist, so this is an ownership conflict rather than a 404.

    "The receiving vessel must belong to the receiving station: a
    `receiving_vessel_id` naming a vessel whose `station_id` differs from the
    delivery's `station_id` is a cross-aggregate ownership breach and is refused with
    `ERR_AGREEMENT_MISMATCH` (HTTP 409)."

    Design: Corner/entities/delivery_receiving_vessel_from_another_station_rejected
    """
    agreement = _agreement("FA-E11")
    station_a = create_station(
        agreement["id"], code="STN-E11A", name="Station A", **SMALL_STATION
    )
    station_b = create_station(
        agreement["id"], code="STN-E11B", name="Station B", **SMALL_STATION
    )
    vessel_a = commission_vessel(station_a["id"], **LOW_VESSEL)
    vessel_b = commission_vessel(station_b["id"], **LOW_VESSEL)
    asset = _electrolysis_asset_with_contract("PA-E11-1", "PSC-E11-1")
    lot = create_production_lot(
        asset["id"],
        lot_code="LOT-E11-1",
        mass_kg=300.000,
        energy_consumed_kwh=15600.0,
        feedstock_consumed_mmbtu=0.000,
        carryover_kg=0.000,
        production_start_at="2026-07-20T00:00:00Z",
        production_end_at="2026-07-21T00:00:00Z",
    )
    booking = dict(
        planned_kg=100.000,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        departed_at="2026-08-01T12:00:00Z",
        trailer_water_volume_l=2500.0,
        trailer_final_pressure_bar=210.00,
    )

    response = api_client.create_delivery(
        tube_trailer_delivery_payload(
            station_a["id"], lot["id"], vessel_b["id"], **booking
        ),
        DISPATCHER,
    )

    validate_error(response, "ERR_AGREEMENT_MISMATCH", expected_status=409)
    assert read_station(station_a["id"])["inbound_planned_kg"] == pytest.approx(
        0.000, abs=0.001
    )
    assert read_station(station_b["id"])["inbound_planned_kg"] == pytest.approx(
        0.000, abs=0.001
    )
    accepted = validate_success(
        api_client.create_delivery(
            tube_trailer_delivery_payload(
                station_a["id"], lot["id"], vessel_a["id"], **booking
            ),
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert read_station(station_a["id"])["inbound_planned_kg"] == pytest.approx(
        100.000, abs=0.001
    )


# ─── Listing, filtering and paging ────────────────────────────────────────


def test_station_paging_and_the_posture_filter_compose():
    """`total_count` counts the filtered set, and paging runs off the end cleanly.

    "For list responses the `meta` object carries `limit` and `offset` as applied,
    `total_count` as the number of rows matching the filter before pagination, and
    `has_more` as a boolean indicating whether rows remain beyond the current page."

    Design: Corner/entities/station_listing_pagination_reports_total_count_and_has_more
    """
    agreement = _agreement("FA-E12")
    station_a = create_station(
        agreement["id"],
        code="STN-E12A",
        name="Station A",
        **{**SMALL_STATION, "max_pressure_class": "H70"},
    )
    station_b = create_station(
        agreement["id"],
        code="STN-E12B",
        name="Station B",
        **{**SMALL_STATION, "max_pressure_class": "H70"},
    )
    station_c = create_station(
        agreement["id"],
        code="STN-E12C",
        name="Station C",
        **{**SMALL_STATION, "max_pressure_class": "H70"},
    )
    commission_vessel(station_a["id"], **HIGH_VESSEL)

    page1 = api_client.list_stations(ADMIN, params={"limit": 2, "offset": 0})
    page2 = api_client.list_stations(ADMIN, params={"limit": 2, "offset": 2})
    restricted = api_client.list_stations(
        ADMIN, params={"safety_posture": "RESTRICTED", "limit": 10, "offset": 0}
    )
    beyond = api_client.list_stations(
        ADMIN,
        params={"funding_agreement_id": agreement["id"], "limit": 10, "offset": 101},
    )

    assert len(list_rows(page1)) == 2
    assert list_meta(page1)["total_count"] == 3
    assert list_meta(page1)["has_more"] is True
    assert len(list_rows(page2)) == 1
    assert list_meta(page2)["total_count"] == 3
    assert list_meta(page2)["has_more"] is False
    assert {row["id"] for row in list_rows(restricted)} == {station_b["id"], station_c["id"]}
    assert list_meta(restricted)["total_count"] == 2, "station A alone reached OPEN"
    assert list_rows(beyond) == []
    assert list_meta(beyond)["total_count"] == 3
    assert list_meta(beyond)["has_more"] is False
    assert read_station(station_a["id"])["safety_posture"] == "OPEN"
