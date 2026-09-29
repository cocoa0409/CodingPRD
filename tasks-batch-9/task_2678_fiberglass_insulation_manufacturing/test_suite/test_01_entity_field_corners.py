"""Entity-level corners: creation echoes, retrieval shapes, pagination, defaults,
server-derived fields, closed enumerations, immutability and foreign-key resolution.

Every test builds its own world from scratch through PRD-declared endpoints, because
the server is restarted against an empty database before each test.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import (
    assert_area,
    assert_close,
    assert_field_equals,
    assert_immutable_entity,
    assert_mass,
    assert_versioned_entity,
    ids_of,
)
from test_helpers.constants import (
    DEFAULT_CULLET_RESTRICT_FRACTION,
    DEFAULT_MAX_CULLET_FRACTION,
    DEFAULT_MAX_WIDTH_CHANGE_IN,
    PLANT_NEWARK,
    SKU_PL_A,
    SKU_PL_B,
    SKU_PL_C,
    ZONES_470,
)
from test_helpers.test_users import (
    certification_officer_headers,
    channel_manager_headers,
    corporate_ops_headers,
    plant_operator_headers,
    quality_engineer_headers,
)

# --- Fixture literals --------------------------------------------------------

MELT_CLOCK = "2026-08-03T06:00:00Z"
RUN_START = "2026-08-03T06:00:00Z"
RUN_END = "2026-08-03T14:00:00Z"
LAB_WINDOW_START = "2026-08-03T08:00:00Z"
LAB_WINDOW_END = "2026-08-03T12:00:00Z"

UNKNOWN_PLANT_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_PRODUCT_LINE_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_ID = "44444444-4444-4444-8444-444444444444"

RECORDING_ENGINEER_ID = "qe-7"

# The three plant policy dials of PRD 3.1 are optional at registration; this payload
# deliberately omits them so the server's own defaults are what land on the row.
PLANT_WITHOUT_POLICY_DIALS = {
    key: value
    for key, value in PLANT_NEWARK.items()
    if key
    not in ("max_cullet_fraction", "cullet_restrict_fraction", "max_width_change_in")
}


# --- Local composite setup ---------------------------------------------------


def _program_and_certified_binder(
    client: InsulationApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A PER_SPECIMEN program and a CERTIFIED formaldehyde-free formulation."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    binder = fx.create_certified_formaldehyde_free_binder(client)
    return program, binder


def _reference_data(
    client: InsulationApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Program + plant + CERTIFIED binder: everything a SKU needs to exist."""
    program, binder = _program_and_certified_binder(client)
    plant = fx.create_plant(client)
    return program, plant, binder


def _run_at_curing(client: InsulationApiClient) -> Dict[str, Any]:
    """Plant NWK, SKU PL-A and one run driven SCHEDULED -> MELTING -> CURING.

    oven_length_ft 120 at 40 fpm gives dwell_s 180.00; the binder's minimum dwell of
    150 s and minimum cure temperature of 420 F against a measured 470 F give a
    cure_index of 110.00, which clears the 100.00 floor.
    """
    program, plant, binder = _reference_data(client)
    sku = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_A
    )
    fx.set_clock(client, MELT_CLOCK)
    run = fx.schedule_run(
        client,
        plant["id"],
        sku["id"],
        line_index=1,
        scheduled_start=RUN_START,
        scheduled_end=RUN_END,
        target_pull_kg=9200.0,
        zone_setpoints_f=ZONES_470,
    )
    fx.start_melt(client, plant["id"], run["id"], [])
    curing = fx.start_cure(
        client,
        plant["id"],
        run["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    return {
        "program": program,
        "plant": plant,
        "binder": binder,
        "sku": sku,
        "run": curing,
        "operator": plant_operator_headers(plant["id"]),
    }


# --- Creation echo -----------------------------------------------------------


def test_create_certification_program_echoes_every_declared_field(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "A program declares a `code` unique across all programs, and a
    `conformance_basis` of either `PER_SPECIMEN` or `LOT_MEAN` that decides which of the
    two thermal verdict variants in 3.6 governs its tests."
    PRD 3.1: "`min_specimen_count` is the minimum number of specimen R-values a recorded
    result must carry and must be at least one; `max_concurrent_lab_tests` is the ceiling
    on how many of the program's in-lab tests may hold overlapping laboratory windows and
    must be at least one; `retest_limit` is the highest attempt number a test of this
    program may ever reach and must be at least one."
    PRD 3.1: "`derate_allowed` is the boolean policy switch that decides whether the
    program permits publishing a lowered declared R-value instead of rejecting a SKU
    outright."
    PRD 2.4: "Creating a new resource returns HTTP 201."

    Design: Corner/entities/create_certification_program_echoes_every_declared_field
    """
    fx.reset_clock(client)
    payload = f.per_specimen_program_payload()

    response = client.create_certification_program(payload, corporate_ops_headers())
    program = validate_success(response, 201)

    assert_field_equals(program, "code", "RCERT-PS")
    assert_field_equals(program, "conformance_basis", "PER_SPECIMEN")
    assert_close(program["r_value_tolerance"], 0.30, 2, "r_value_tolerance")
    assert_field_equals(program, "min_specimen_count", 3)
    assert_field_equals(program, "max_concurrent_lab_tests", 2)
    assert_field_equals(program, "retest_limit", 2)
    assert_field_equals(program, "derate_allowed", True)

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource must answer with response_type 'object', got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)


# --- Retrieval ---------------------------------------------------------------


def test_get_plant_returns_stored_reference_data_and_a_zeroed_cullet_ledger(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "A newly registered plant begins with `melt_posture` `OPEN`,
    `posture_reason` null, `emissions_status` `COMPLIANT`, `version` 1, and every cullet
    and charge counter at zero."
    PRD 3.1: "From those two accumulators the plant derives `cullet_fraction_ytd`: the
    charged cullet mass divided by the total charge mass, rounded half up to four decimal
    places, and reported as 0.0000 whenever the total charge mass is zero."

    Design: Corner/entities/get_plant_returns_stored_reference_data_and_a_zeroed_cullet_ledger
    """
    fx.reset_clock(client)
    created = fx.create_plant(client)
    assert_field_equals(created, "version", 1)

    fetched = validate_success(
        client.get_plant(created["id"], plant_operator_headers(created["id"]))
    )

    assert_field_equals(fetched, "id", created["id"])
    assert_field_equals(fetched, "name", PLANT_NEWARK["name"])
    assert_field_equals(fetched, "site_code", "NWK")
    assert_field_equals(fetched, "permit_number", PLANT_NEWARK["permit_number"])
    assert_field_equals(fetched, "oven_zone_count", 4)
    assert_close(fetched["oven_length_ft"], 120.0, 2, "oven_length_ft")
    assert_field_equals(fetched, "production_line_count", 2)
    assert_close(
        fetched["formaldehyde_allowance_kg"], 0.200, 3, "formaldehyde_allowance_kg"
    )
    assert_close(fetched["voc_allowance_kg"], 12.0, 4, "voc_allowance_kg")

    assert_mass(fetched["cullet_received_kg_ytd"], 0.00, "cullet_received_kg_ytd")
    assert_mass(fetched["cullet_charged_kg_ytd"], 0.00, "cullet_charged_kg_ytd")
    assert_mass(fetched["cullet_rejected_kg_ytd"], 0.00, "cullet_rejected_kg_ytd")
    assert_mass(fetched["cullet_on_hand_kg"], 0.00, "cullet_on_hand_kg")
    assert_mass(fetched["total_charge_kg_ytd"], 0.00, "total_charge_kg_ytd")
    assert_close(fetched["cullet_fraction_ytd"], 0.0000, 4, "cullet_fraction_ytd")

    assert_field_equals(fetched, "melt_posture", "OPEN")
    assert fetched["posture_reason"] is None, (
        f"posture_reason must be null on a fresh plant, got {fetched['posture_reason']!r}"
    )
    assert_field_equals(fetched, "emissions_status", "COMPLIANT")
    assert_field_equals(fetched, "version", 1)
    assert_versioned_entity(fetched, "Plant")


# --- Listing and pagination --------------------------------------------------


def test_list_product_lines_paginates_with_total_count_and_has_more(
    client: InsulationApiClient,
) -> None:
    """PRD 2.3: "`limit` caps the number of rows returned; when omitted it defaults to 10,
    its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "`offset` is the number of rows to skip and defaults to 0."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    the `meta` object of the envelope."
    PRD 2.3: "`GET /product-lines` accepts `plant_id`, `binder_formulation_id`,
    `certification_program_id`, `form`, `facing_type` and `certification_status`."

    Design: Corner/entities/list_product_lines_paginates_with_total_count_and_has_more
    """
    program, plant, binder = _reference_data(client)
    sku_a = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_A
    )
    sku_b = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_B
    )
    sku_c = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_C
    )

    manager = channel_manager_headers()

    page_one, meta_one = validate_paginated(
        client.list_product_lines(manager, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, f"limit=2 must cap the page at 2 rows, got {len(page_one)}"
    assert meta_one["total_count"] == 3, (
        f"three SKUs are on file, meta.total_count says {meta_one['total_count']}"
    )
    assert meta_one["has_more"] is True, "two of three rows returned leaves more to fetch"
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        client.list_product_lines(manager, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, f"offset=2 leaves one row, got {len(page_two)}"
    assert meta_two["total_count"] == 3, (
        f"total_count is the whole match set, not the page: {meta_two['total_count']}"
    )
    assert meta_two["has_more"] is False, "the last page must report has_more false"
    assert meta_two["offset"] == 2

    seen = ids_of(page_one) + ids_of(page_two)
    assert len(seen) == len(set(seen)), f"no id may appear on two pages, got {seen}"
    assert set(seen) == {sku_a["id"], sku_b["id"], sku_c["id"]}, (
        f"the two pages together must cover every SKU, got {seen}"
    )

    filtered, meta_filtered = validate_paginated(
        client.list_product_lines(manager, {"facing_type": "KRAFT", "limit": 10})
    )
    assert meta_filtered["total_count"] == 1, (
        "the facing_type filter narrows total_count, it does not merely hide rows: "
        f"got {meta_filtered['total_count']}"
    )
    assert ids_of(filtered) == [sku_b["id"]], (
        f"only the KRAFT SKU matches, got {ids_of(filtered)}"
    )


# --- Not found ---------------------------------------------------------------


def test_get_thermal_test_with_unknown_id_returns_not_found(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "Path identifiers are resolved strictly left to right before any body
    content is examined, and the leftmost unresolved identifier decides the error."
    PRD 2.9: "The twelve not-found identifiers are `ERR_PLANT_NOT_FOUND` (for `plantId` in
    a path or `plant_id` in a body), `ERR_CERTIFICATION_PROGRAM_NOT_FOUND` (`programId`,
    `certification_program_id`), `ERR_BINDER_FORMULATION_NOT_FOUND` (`binderId`,
    `binder_formulation_id`), `ERR_PRODUCT_LINE_NOT_FOUND` (`productLineId`,
    `product_line_id`), `ERR_PRODUCTION_RUN_NOT_FOUND` (`runId`, and `production_run_id`,
    `outgoing_run_id`, `incoming_run_id` or `source_run_id` in a body),
    `ERR_CHANGEOVER_EVENT_NOT_FOUND` (`changeoverId`), `ERR_THERMAL_TEST_NOT_FOUND`
    (`testId`), `ERR_INVENTORY_LOT_NOT_FOUND` (`lotId`, `inventory_lot_id`),
    `ERR_ALLOCATION_CYCLE_NOT_FOUND` (`cycleId`, `allocation_cycle_id`),
    `ERR_CHANNEL_ORDER_NOT_FOUND` (`orderId`, `channel_order_id`),
    `ERR_ALLOCATION_LINE_NOT_FOUND` (`lineId`) and `ERR_CULLET_BATCH_NOT_FOUND`
    (`batchId`, and any element of a supplied `cullet_batch_ids` array). All twelve carry
    HTTP 404."

    Design: Corner/entities/get_thermal_test_with_unknown_id_returns_not_found
    """
    fx.reset_clock(client)
    engineer = quality_engineer_headers()

    validate_error(
        client.get_thermal_test(NON_EXISTENT_UUID, engineer),
        ApiErrors.THERMAL_TEST_NOT_FOUND,
    )
    validate_error(
        client.get_thermal_test(UNKNOWN_ID, engineer),
        ApiErrors.THERMAL_TEST_NOT_FOUND,
    )
    # The same shape of miss on a different resource selects that resource's own id.
    validate_error(
        client.get_binder_formulation(NON_EXISTENT_UUID, engineer),
        ApiErrors.BINDER_FORMULATION_NOT_FOUND,
    )


# --- Required fields ---------------------------------------------------------


def test_create_plant_missing_voc_allowance_returns_invalid_request(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "The permit envelope is captured by `permit_number`, the air-emissions
    permit identifier on file with the regulator, together with
    `formaldehyde_allowance_kg` and `voc_allowance_kg`, the permitted masses in kilograms
    for one reporting period, both of which must be positive."
    PRD 2.8: "Request shape: required fields present, enum values drawn from their
    declared sets, numeric fields inside their declared ranges, timestamps expressed as
    RFC3339 UTC instants, every interval's end strictly after its start, and required
    arrays non-empty - `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_plant_missing_voc_allowance_returns_invalid_request
    """
    fx.reset_clock(client)
    ops = corporate_ops_headers()

    payload = f.plant_payload()
    del payload["voc_allowance_kg"]
    validate_error(client.create_plant(payload, ops), ApiErrors.INVALID_REQUEST)

    payload = f.plant_payload()
    del payload["permit_number"]
    validate_error(client.create_plant(payload, ops), ApiErrors.INVALID_REQUEST)

    payload = f.plant_payload()
    del payload["formaldehyde_allowance_kg"]
    validate_error(client.create_plant(payload, ops), ApiErrors.INVALID_REQUEST)

    # A rejected shape must not have banked a partial row.
    _, meta = validate_paginated(client.list_plants(ops, {"limit": 10}))
    assert meta["total_count"] == 0, (
        f"a rejected registration must leave no plant on file, total_count is {meta['total_count']}"
    )


# --- Declared defaults -------------------------------------------------------


def test_omitting_the_cullet_and_width_limits_applies_the_declared_defaults(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "`max_cullet_fraction` is the hard permit cap on the recycled-glass share
    of any single melt charge; it must be greater than zero and no more than 0.5, is held
    to two decimal places, and defaults to 0.30 - thirty percent of the charge."
    PRD 3.1: "`cullet_restrict_fraction` is the year-to-date recycling level at or above
    which the melt shop tightens; it must be greater than zero and no more than
    `max_cullet_fraction`, is held to two decimal places, and defaults to 0.28."
    PRD 3.1: "`max_width_change_in` is the largest absolute batt-width step, in inches,
    that the plant's mandrel and chopper set can absorb in a single changeover; it must be
    positive and defaults to 8.0 inches."
    PRD 3.3: "Finally `compression_ratio` - uncompressed volume divided by bagged volume -
    is optional, must lie between 1.0 and 8.0 inclusive, is held to one decimal place, and
    defaults to 6.0."
    PRD 3.3: "`compressed_bale_volume_ft3` is the uncompressed `bale_volume_ft3` divided
    by the `compression_ratio`, rounded half up to three decimal places."

    Design: Corner/entities/omitting_the_cullet_and_width_limits_applies_the_declared_defaults
    """
    fx.reset_clock(client)
    ops = corporate_ops_headers()

    plant = validate_success(
        client.create_plant(f.plant_payload(**PLANT_WITHOUT_POLICY_DIALS), ops), 201
    )
    assert_close(
        plant["max_cullet_fraction"],
        DEFAULT_MAX_CULLET_FRACTION,
        2,
        "max_cullet_fraction",
    )
    assert_close(
        plant["cullet_restrict_fraction"],
        DEFAULT_CULLET_RESTRICT_FRACTION,
        2,
        "cullet_restrict_fraction",
    )
    assert_close(
        plant["max_width_change_in"],
        DEFAULT_MAX_WIDTH_CHANGE_IN,
        1,
        "max_width_change_in",
    )

    program, binder = _program_and_certified_binder(client)
    sku_payload = f.product_line_payload(
        plant["id"], binder["id"], program["id"], **SKU_PL_A
    )
    del sku_payload["compression_ratio"]

    sku = validate_success(client.create_product_line(sku_payload, ops), 201)

    assert_close(sku["compression_ratio"], 6.0, 1, "compression_ratio")
    # 21.0 uncompressed cubic feet over the defaulted ratio of 6.0 is 3.500 ft3.
    assert_close(sku["compressed_bale_volume_ft3"], 3.500, 3, "compressed_bale_volume_ft3")


# --- Server-computed fields --------------------------------------------------


def test_run_and_lot_coverage_fields_are_computed_with_supplied_input_ignored(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "Unknown fields, and fields the server itself derives, are ignored rather
    than rejected."
    PRD 3.4: "The total charge is derived from the pull target alone: `total_charge_kg` is
    `target_pull_kg` divided by a melt yield of 0.92, meaning ninety-two percent of what is
    charged survives as fiberized product, rounded half up to two decimal places."
    PRD 3.4: "The cullet ceiling is then taken against that total and never against the
    virgin mass: `allowed_cullet_kg` is `total_charge_kg` multiplied by the plant's
    `max_cullet_fraction`, truncated **down** to two decimal places."
    PRD 3.4: "Dwell time follows from oven geometry: `dwell_s` is the plant's
    `oven_length_ft` divided by `line_speed_fpm`, multiplied by 60 to convert minutes to
    seconds, rounded half up to two decimal places."
    PRD 3.4: "On success `produced_sqft` on the run is `bags_produced` multiplied by the
    SKU's `bag_sqft`, and the server cascade-creates exactly one finished-goods lot: status
    `AVAILABLE`, `parent_lot_id` null, `bags` equal to `bags_produced`, `produced_sqft`
    equal to the run's `produced_sqft`, `allocated_sqft` 0.00 and `available_sqft` equal to
    `produced_sqft`."

    Design: Corner/entities/run_and_lot_coverage_fields_are_computed_with_supplied_input_ignored
    """
    ctx = _run_at_curing(client)
    curing = ctx["run"]

    # 9200 / 0.92 = 10000.00 kg charged; 10000.00 * 0.30 = 3000.00 kg of cullet headroom.
    assert_mass(curing["total_charge_kg"], 10000.00, "total_charge_kg")
    assert_mass(curing["allowed_cullet_kg"], 3000.00, "allowed_cullet_kg")
    # 120 ft of oven at 40 fpm is 3 minutes, i.e. 180.00 s of dwell.
    assert_close(curing["dwell_s"], 180.00, 2, "dwell_s")
    # dwell ratio 180/150 = 1.2; temperature margin (470 - 420) / 60 = 0.8333...;
    # 1.2 * (1 + 0.8333...) / 2 * 100 = 110.00.
    assert_close(curing["cure_index"], 110.00, 2, "cure_index")

    # The packaging call hands the server figures it derives for itself, plus a field the
    # PRD never declares. Every one of them must be ignored, not stored and not rejected.
    packaged = validate_success(
        client._request(
            "POST",
            f"/production-runs/{curing['id']}/package",
            {
                "bags_produced": 120,
                "produced_sqft": 99999.99,
                "total_charge_kg": 1.00,
                "allowed_cullet_kg": 999999.99,
                "dwell_s": 1.00,
                "cure_index": 500.00,
                "not_a_declared_field": "ignored",
            },
            headers=ctx["operator"],
        )
    )

    assert_field_equals(packaged, "run_status", "PACKAGED")
    # 120 bags * 88.00 sqft per bag = 10560.00 sqft.
    assert_area(packaged["produced_sqft"], 10560.00, "produced_sqft")
    assert_mass(packaged["total_charge_kg"], 10000.00, "total_charge_kg")
    assert_mass(packaged["allowed_cullet_kg"], 3000.00, "allowed_cullet_kg")
    assert_close(packaged["dwell_s"], 180.00, 2, "dwell_s")
    assert_close(packaged["cure_index"], 110.00, 2, "cure_index")

    lot = fx.lot_for_run(client, curing["id"])
    assert_field_equals(lot, "status", "AVAILABLE")
    assert lot["parent_lot_id"] is None, (
        f"a packaging lot has no parent, got {lot['parent_lot_id']!r}"
    )
    assert_field_equals(lot, "bags", 120)
    assert_field_equals(lot, "production_run_id", curing["id"])
    assert_field_equals(lot, "product_line_id", ctx["sku"]["id"])
    assert_field_equals(lot, "form", "BATT")
    assert_area(lot["produced_sqft"], 10560.00, "produced_sqft")
    assert_area(lot["allocated_sqft"], 0.00, "allocated_sqft")
    assert_area(lot["available_sqft"], 10560.00, "available_sqft")


# --- System-stamped fields ---------------------------------------------------


def test_thermal_test_recorded_by_user_id_is_stamped_from_the_recording_header(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The recorded values are stored on the row and `recorded_by_user_id` is set
    to the acting `X-User-ID`."
    PRD 3.6: "`specimen_count` is the array length; `mean_r_value` is the sum of the
    specimens divided by `specimen_count`, quantized to two decimal places; `min_r_value`
    is the smallest specimen, quantized to two decimal places."
    PRD 3.6: "A `CONFORMING` verdict moves the test `IN_LAB -> COMPLETED`."

    Design: Corner/entities/thermal_test_recorded_by_user_id_is_stamped_from_the_recording_header
    """
    ctx = _run_at_curing(client)
    fx.package_run(client, ctx["plant"]["id"], ctx["run"]["id"], bags_produced=120)

    requested = fx.request_thermal_test(
        client,
        ctx["run"]["id"],
        ctx["sku"]["id"],
        ctx["program"]["id"],
        window_start=LAB_WINDOW_START,
        window_end=LAB_WINDOW_END,
    )
    assert requested["recorded_by_user_id"] is None, (
        "a requested test has recorded nothing yet, so the stamp must still be null"
    )

    # The lab is opened by qe-1 but the measurement is filed by a different engineer.
    in_lab = validate_success(
        client.start_lab(requested["id"], quality_engineer_headers())
    )
    assert_field_equals(in_lab, "status", "IN_LAB")

    recorded = validate_success(
        client.record_result(
            requested["id"],
            [13.10, 13.20, 12.90],
            quality_engineer_headers(RECORDING_ENGINEER_ID),
        )
    )

    assert_field_equals(recorded, "recorded_by_user_id", RECORDING_ENGINEER_ID)
    assert_field_equals(recorded, "specimen_count", 3)
    assert_field_equals(recorded, "specimen_r_values", [13.10, 13.20, 12.90])
    # (13.10 + 13.20 + 12.90) / 3 = 13.0666... -> 13.07; floor is 13.0 - 0.30 = 12.70.
    assert_close(recorded["mean_r_value"], 13.07, 2, "mean_r_value")
    assert_close(recorded["min_r_value"], 12.90, 2, "min_r_value")
    assert_field_equals(recorded, "conformance_verdict", "CONFORMING")
    assert_field_equals(recorded, "status", "COMPLETED")
    assert recorded["version"] > requested["version"], (
        "recording a result mutates the row, so version must have advanced past "
        f"{requested['version']}, got {recorded['version']}"
    )

    # The stamp is durable and visible to another reader of the row.
    fetched = validate_success(
        client.get_thermal_test(requested["id"], certification_officer_headers())
    )
    assert_field_equals(fetched, "recorded_by_user_id", RECORDING_ENGINEER_ID)


# --- Closed enumerations and declared ranges ---------------------------------


def test_create_product_line_with_bad_enum_and_bad_width_returns_invalid_request(
    client: InsulationApiClient,
) -> None:
    """PRD 3.3: "`facing_type` is the vapour-retarder facing applied to the blanket and is
    one of `UNFACED`, `KRAFT`, `FSK` or `FOIL`."
    PRD 3.3: "`width_in` is the finished width in inches and must be exactly one of 15, 16,
    23 or 24."
    PRD 3.3: "`density_pcf` is the nominal product density in pounds per cubic foot,
    positive and held to two decimal places."
    PRD 3.3: "Finally `compression_ratio` - uncompressed volume divided by bagged volume -
    is optional, must lie between 1.0 and 8.0 inclusive, is held to one decimal place, and
    defaults to 6.0."
    PRD 2.8: "Request shape: required fields present, enum values drawn from their
    declared sets, numeric fields inside their declared ranges, timestamps expressed as
    RFC3339 UTC instants, every interval's end strictly after its start, and required
    arrays non-empty - `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_product_line_with_bad_enum_and_bad_width_returns_invalid_request
    """
    program, plant, binder = _reference_data(client)
    ops = corporate_ops_headers()

    def _rejected(**overrides: Any) -> None:
        payload = f.product_line_payload(
            plant["id"], binder["id"], program["id"], **overrides
        )
        validate_error(client.create_product_line(payload, ops), ApiErrors.INVALID_REQUEST)

    # A facing outside the declared four-value set.
    _rejected(facing_type="FOIL_MESH")
    # A width that is not one of the four tooled widths, though it sits between them.
    _rejected(width_in=20.0)
    # 24 is legal, 24.5 is not: the set is exact, not a range.
    _rejected(width_in=24.5)
    # A compression ratio past the inclusive upper bound of 8.0.
    _rejected(compression_ratio=9.5)
    # A non-positive density.
    _rejected(density_pcf=0.0)

    _, meta = validate_paginated(client.list_product_lines(ops, {"limit": 10}))
    assert meta["total_count"] == 0, (
        f"no rejected SKU may have been banked, total_count is {meta['total_count']}"
    )


# --- Immutability ------------------------------------------------------------


def test_certification_program_is_immutable_and_exposes_no_version(
    client: InsulationApiClient,
) -> None:
    """PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that starts at 1 on creation and
    increments by one on every mutation of that row - including mutations that only touch
    derived fields such as a plant's cullet ledger or an allocation cycle's coverage
    totals. The single exception is `CertificationProgram`, which is immutable once
    registered: a certification program row carries only `id` and `created_at`. It has
    neither `updated_at` nor `version`, and there is no endpoint that modifies one."

    Design: Corner/entities/certification_program_is_immutable_and_exposes_no_version
    """
    fx.reset_clock(client)
    officer_readable = corporate_ops_headers()

    created = validate_success(
        client.create_certification_program(
            f.per_specimen_program_payload(), officer_readable
        ),
        201,
    )
    assert_immutable_entity(created, "CertificationProgram")

    fetched = validate_success(
        client.get_certification_program(created["id"], officer_readable)
    )
    assert_immutable_entity(fetched, "CertificationProgram")
    assert_field_equals(fetched, "created_at", created["created_at"])

    # A second program is an independent row: registering it cannot rewrite the first.
    other = validate_success(
        client.create_certification_program(
            f.lot_mean_program_payload(derate_allowed=False), officer_readable
        ),
        201,
    )
    assert_immutable_entity(other, "CertificationProgram")
    assert other["id"] != created["id"]
    assert_field_equals(other, "conformance_basis", "LOT_MEAN")
    assert_field_equals(other, "derate_allowed", False)

    reread = validate_success(
        client.get_certification_program(created["id"], officer_readable)
    )
    assert_field_equals(reread, "conformance_basis", "PER_SPECIMEN")
    assert_field_equals(reread, "derate_allowed", True)
    assert_field_equals(reread, "max_concurrent_lab_tests", 2)
    assert_field_equals(reread, "created_at", created["created_at"])
    assert_immutable_entity(reread, "CertificationProgram")


# --- Parent relationships ----------------------------------------------------


def test_create_production_run_against_unknown_plant_returns_not_found(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "Body foreign keys are resolved only after the request shape has been
    accepted, and they are resolved in the order the endpoint declares them."
    PRD 2.9: "Concretely: a SKU creation resolves `plant_id`, then
    `binder_formulation_id`, then `certification_program_id`; a run creation resolves
    `plant_id` then `product_line_id`; a changeover creation resolves `plant_id`, then
    `outgoing_run_id`, then `incoming_run_id`; a thermal test request resolves
    `production_run_id`, then `product_line_id`, then `certification_program_id`; an
    allocation cycle resolves `plant_id` then `product_line_id`; a channel order resolves
    `product_line_id`; a manual allocation line resolves `allocation_cycle_id`, then
    `channel_order_id`, then `inventory_lot_id`; a cullet stage resolves `plant_id` and
    then an optionally supplied `source_run_id`; and a furnace charge resolves each element
    of `cullet_batch_ids`."
    PRD 2.9: "All twelve carry HTTP 404."

    Design: Corner/entities/create_production_run_against_unknown_plant_returns_not_found
    """
    program, plant, binder = _reference_data(client)
    sku = fx.create_product_line(
        client, plant["id"], binder["id"], program["id"], **SKU_PL_A
    )

    # The operator's own identity is the plant it acts for, so an operator of the unknown
    # plant clears the ownership rung and the request dies on the unresolved body key.
    validate_error(
        client.create_production_run(
            f.production_run_payload(UNKNOWN_PLANT_ID, sku["id"]),
            plant_operator_headers(UNKNOWN_PLANT_ID),
        ),
        ApiErrors.PLANT_NOT_FOUND,
    )

    # A real plant with an unresolvable SKU fails on the second declared key instead.
    validate_error(
        client.create_production_run(
            f.production_run_payload(plant["id"], UNKNOWN_PRODUCT_LINE_ID),
            plant_operator_headers(plant["id"]),
        ),
        ApiErrors.PRODUCT_LINE_NOT_FOUND,
    )

    _, meta = validate_paginated(
        client.list_production_runs(corporate_ops_headers(), {"limit": 10})
    )
    assert meta["total_count"] == 0, (
        f"neither rejected schedule may have created a run, total_count is {meta['total_count']}"
    )


# --- Body foreign keys in declared order -------------------------------------


def test_product_line_body_foreign_keys_are_checked_in_declared_field_order(
    client: InsulationApiClient,
) -> None:
    """PRD 2.9: "Body foreign keys are resolved only after the request shape has been
    accepted, and they are resolved in the order the endpoint declares them."
    PRD 2.9: "Concretely: a SKU creation resolves `plant_id`, then
    `binder_formulation_id`, then `certification_program_id`; a run creation resolves
    `plant_id` then `product_line_id`; a changeover creation resolves `plant_id`, then
    `outgoing_run_id`, then `incoming_run_id`; a thermal test request resolves
    `production_run_id`, then `product_line_id`, then `certification_program_id`; an
    allocation cycle resolves `plant_id` then `product_line_id`; a channel order resolves
    `product_line_id`; a manual allocation line resolves `allocation_cycle_id`, then
    `channel_order_id`, then `inventory_lot_id`; a cullet stage resolves `plant_id` and
    then an optionally supplied `source_run_id`; and a furnace charge resolves each element
    of `cullet_batch_ids`."
    PRD 2.8: "Request shape: required fields present, enum values drawn from their
    declared sets, numeric fields inside their declared ranges, timestamps expressed as
    RFC3339 UTC instants, every interval's end strictly after its start, and required
    arrays non-empty - `ERR_INVALID_REQUEST`."

    Design: Corner/entities/product_line_body_foreign_keys_are_checked_in_declared_field_order
    """
    program, plant, binder = _reference_data(client)
    ops = corporate_ops_headers()
    # Two further unresolvable ids, one standing in for the binder and one for the program.
    unknown_binder_id = UNKNOWN_ID
    unknown_program_id = NON_EXISTENT_UUID

    # Each key alone selects its own not-found identifier.
    validate_error(
        client.create_product_line(
            f.product_line_payload(UNKNOWN_PLANT_ID, binder["id"], program["id"]), ops
        ),
        ApiErrors.PLANT_NOT_FOUND,
    )
    validate_error(
        client.create_product_line(
            f.product_line_payload(plant["id"], unknown_binder_id, program["id"]), ops
        ),
        ApiErrors.BINDER_FORMULATION_NOT_FOUND,
    )
    validate_error(
        client.create_product_line(
            f.product_line_payload(plant["id"], binder["id"], unknown_program_id), ops
        ),
        ApiErrors.CERTIFICATION_PROGRAM_NOT_FOUND,
    )

    # All three unresolvable: the first declared key wins, not the last.
    validate_error(
        client.create_product_line(
            f.product_line_payload(
                UNKNOWN_PLANT_ID, unknown_binder_id, unknown_program_id
            ),
            ops,
        ),
        ApiErrors.PLANT_NOT_FOUND,
    )

    # Plant resolves, so the second declared key decides even though the third is bad too.
    validate_error(
        client.create_product_line(
            f.product_line_payload(plant["id"], unknown_binder_id, unknown_program_id),
            ops,
        ),
        ApiErrors.BINDER_FORMULATION_NOT_FOUND,
    )

    # A bad shape outranks every unresolved body key: rung 5 precedes rung 6.
    validate_error(
        client.create_product_line(
            f.product_line_payload(
                UNKNOWN_PLANT_ID,
                unknown_binder_id,
                unknown_program_id,
                facing_type="FOIL_MESH",
            ),
            ops,
        ),
        ApiErrors.INVALID_REQUEST,
    )

    _, meta = validate_paginated(client.list_product_lines(ops, {"limit": 10}))
    assert meta["total_count"] == 0, (
        f"no rejected SKU may have been banked, total_count is {meta['total_count']}"
    )
