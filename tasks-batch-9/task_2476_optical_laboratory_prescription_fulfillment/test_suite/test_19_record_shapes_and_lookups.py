"""Row shapes, server-initialised fields and lookups across the registry."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLOCK_START_RENDERED,
    TEST_DEFAULTS,
    UNISSUED_DESIGN_UUID,
    UNISSUED_UUID,
)
from test_helpers.test_users import (
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)


def test_a_new_prescriber_starts_active_with_nothing_verified(api):
    """Standing and the verified count are server-initialised, not supplied.

    PRD 3.1: "A new prescriber begins with `status` of `ACTIVE` and
    `verified_rx_count` of 0."

    Design: Corner/entities/prescriber_creation_returns_active_standing_with_zero_verified_count
    """
    fixtures.set_clock(api)

    prescriber = validate_success(
        api.create_prescriber(f.create_prescriber_payload(), OPTICIAN_A_HEADERS),
        expected_status=201,
    )

    assert prescriber["npi"] == TEST_DEFAULTS["npi_primary"]
    assert prescriber["full_name"] == TEST_DEFAULTS["prescriber_name"]
    assert prescriber["license_state"] == TEST_DEFAULTS["license_state"]
    assert prescriber["max_rx_validity_months"] == 12
    assert prescriber["status"] == "ACTIVE"
    assert prescriber["verified_rx_count"] == 0
    assert prescriber["version"] == 1
    assert prescriber["created_at"] == CLOCK_START_RENDERED
    assert prescriber["updated_at"] == CLOCK_START_RENDERED
    assertions.assert_prescriber(prescriber)


def test_reading_a_lens_design_echoes_every_catalogue_field(api):
    """The stored array order and the one-decimal geometry come back unchanged.

    PRD 3.1: "A design carries a `design_code` unique across designs — a duplicate is
    rejected with `ERR_DUPLICATE_DESIGN_CODE` — a `design_type` of `SINGLE_VISION`,
    `PROGRESSIVE` or `SPECIALTY`, and a `material` of `CR39`, `POLYCARBONATE`,
    `TRIVEX` or `HIGH_INDEX_167`."

    Design: Corner/entities/lens_design_retrieval_returns_every_stored_catalogue_field
    """
    fixtures.set_clock(api)
    created = fixtures.create_sv_design(api)

    design = validate_success(
        api.get_lens_design(created["id"], TECHNICIAN_A_HEADERS)
    )

    assert design["design_code"] == "SV-POLY"
    assert design["design_type"] == "SINGLE_VISION"
    assert design["material"] == "POLYCARBONATE"
    assert design["allowed_coatings"] == ["AR_STANDARD", "HARDCOAT"]
    assert design["retail_price_cents"] == 11995
    assert design["min_fitting_height_mm"] == 14.0
    assert design["min_blank_diameter_mm"] == 65.0
    assert design["product_tier"] == "STANDARD"
    assert design["stock_sku_available"] is True
    assert design["base_curve"] == 6.0
    assertions.assert_lens_design(design)


def test_the_prescriber_list_pages_by_offset_over_the_oldest_first_order(api):
    """Three prescribers, limit 2 and offset 2 leave exactly the newest one.

    PRD 2.3: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending, oldest row first."

    Design: Corner/entities/prescriber_listing_pages_by_offset_and_reports_total_count
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    fixtures.create_prescriber(api, MANAGER_A_HEADERS, npi=TEST_DEFAULTS["npi_primary"])
    fixtures.set_clock(api, "2026-08-01T00:01:00Z")
    fixtures.create_prescriber(
        api, MANAGER_A_HEADERS, npi=TEST_DEFAULTS["npi_secondary"]
    )
    fixtures.set_clock(api, "2026-08-01T00:02:00Z")
    third = fixtures.create_prescriber(
        api, MANAGER_A_HEADERS, npi=TEST_DEFAULTS["npi_tertiary"]
    )

    rows, meta = validate_paginated(
        api.list_prescribers(MANAGER_A_HEADERS, {"limit": 2, "offset": 2})
    )

    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]
    assert rows[0]["npi"] == TEST_DEFAULTS["npi_tertiary"]
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_reading_an_order_that_was_never_created_returns_not_found(api):
    """A well-formed uuid nobody minted is a 404, not an empty object.

    PRD 2.10: "**Addressed entity exists.** An identifier in the URL path that matches
    no row of the collection it sits under is rejected with that collection's
    not-found code (HTTP 404)."

    Design: Corner/entities/rx_order_read_with_an_unissued_uuid_returns_not_found
    """
    fixtures.set_clock(api)

    error = validate_error(
        api.get_rx_order(UNISSUED_UUID, OPTICIAN_A_HEADERS),
        ApiErrorId.RX_ORDER_NOT_FOUND.value,
        404,
    )

    assert isinstance(error["message"], str)
    assert error["message"] != ""

    _, meta = validate_paginated(api.list_rx_orders(OPTICIAN_A_HEADERS))
    assert meta["total_count"] == 0


def test_opening_an_order_without_a_fitting_height_is_a_structural_failure(api):
    """The required input is missing, so nothing about the prescription is consulted.

    PRD 2.10: "**Structural well-formedness.** A required input field missing, a field
    of the wrong JSON type, or an enumerated field carrying a value outside its
    declared set is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/rx_order_creation_missing_fitting_height_is_rejected
    """
    scenario = fixtures.stock_verified_prescription(api)
    payload = f.create_rx_order_payload(
        scenario["patient_id"], scenario["prescription_id"], scenario["design_id"]
    )
    payload.pop("fitting_height_mm")

    validate_error(
        api.create_rx_order(payload, OPTICIAN_A_HEADERS),
        ApiErrorId.VALIDATION.value,
        400,
    )

    _, meta = validate_paginated(api.list_rx_orders(OPTICIAN_A_HEADERS))
    assert meta["total_count"] == 0
    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["verification_status"] == "VERIFIED"


def test_an_omitted_validity_window_stores_twelve_months_and_drives_expiry(api):
    """The stored default, not a hard-coded constant, produces the expiry instant.

    PRD 3.1: "That last value defaults to 12 and must be between 1 and 36 inclusive."

    Design: Corner/entities/prescriber_validity_window_defaults_to_twelve_months
    """
    fixtures.set_clock(api)
    payload = f.create_prescriber_payload()
    payload.pop("max_rx_validity_months")
    prescriber = validate_success(
        api.create_prescriber(payload, MANAGER_A_HEADERS), expected_status=201
    )
    assert prescriber["max_rx_validity_months"] == 12

    patient = fixtures.create_self_pay_patient(api)
    prescription = validate_success(
        api.create_prescription(
            f.create_prescription_payload(patient["id"], prescriber["id"]),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert prescription["expires_at"] == "2027-03-01T00:00:00.000Z"
    assert prescription["verification_status"] == "UNVERIFIED"
    assert prescription["resubmit_count"] == 0


def test_the_add_power_and_expiry_are_derived_rather_than_supplied(api):
    """One add input lands on both eyes and an omitted prism stores as zero.

    PRD 3.2: "The single `add_power` input is stored on **both** `add_power_od` and
    `add_power_os`; when `add_power` is omitted, both add fields are stored as null."

    Design: Corner/entities/prescription_expiry_and_multifocal_flag_are_derived_from_the_intake_payload
    """
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api, MANAGER_A_HEADERS)
    patient = fixtures.create_self_pay_patient(api)
    payload = f.create_multifocal_prescription_payload(patient["id"], prescriber["id"])
    payload.pop("prism_os")

    prescription = validate_success(
        api.create_prescription(payload, OPTICIAN_A_HEADERS), expected_status=201
    )

    assert prescription["requires_multifocal"] is True
    assert prescription["expires_at"] == "2027-03-01T00:00:00.000Z"
    assert prescription["add_power_od"] == 2.0
    assert prescription["add_power_os"] == 2.0
    assert prescription["prism_diopter_od"] == 0.5
    assert prescription["prism_diopter_os"] == 0.0


def test_a_received_lot_initialises_its_whole_quantity_ledger(api):
    """Only the received quantity is supplied; the other three counters start at zero.

    PRD 3.1: "A newly received lot has `status` `AVAILABLE`, `on_hand_qty` equal to
    `received_qty`, and `allocated_qty`, `consumed_qty` and `scrapped_qty` all at
    zero."

    Design: Corner/entities/blank_lot_quantity_ledger_is_system_initialised_from_received_qty
    """
    fixtures.set_clock(api)
    design = fixtures.create_progressive_design(api)

    lot = validate_success(
        api.create_lens_blank_lot(
            f.create_lens_blank_lot_payload(design["id"], received_qty=3),
            MANAGER_A_HEADERS,
        ),
        expected_status=201,
    )

    assert lot["received_qty"] == 3
    assertions.assert_lot_quantities(
        lot, on_hand=3, allocated=0, consumed=0, scrapped=0, status="AVAILABLE"
    )
    assert lot["version"] == 1
    assert lot["created_at"] == CLOCK_START_RENDERED
    assertions.assert_blank_ledger_conserved(lot)


def test_a_design_type_outside_the_vocabulary_is_refused(api):
    """BIFOCAL is not one of the three declared design types.

    PRD 3.1: "A design carries a `design_code` unique across designs — a duplicate is
    rejected with `ERR_DUPLICATE_DESIGN_CODE` — a `design_type` of `SINGLE_VISION`,
    `PROGRESSIVE` or `SPECIALTY`, and a `material` of `CR39`, `POLYCARBONATE`,
    `TRIVEX` or `HIGH_INDEX_167`."

    Design: Corner/entities/lens_design_with_an_unknown_design_type_is_rejected
    """
    fixtures.set_clock(api)

    validate_error(
        api.create_lens_design(
            f.create_lens_design_payload(
                design_code="BF-CR39",
                design_type="BIFOCAL",
                material="CR39",
                allowed_coatings=["HARDCOAT"],
                retail_price_cents=9995,
                min_fitting_height_mm=16.0,
                min_blank_diameter_mm=65.0,
                product_tier="ECONOMY",
            ),
            MANAGER_A_HEADERS,
        ),
        ApiErrorId.VALIDATION.value,
        400,
    )


def test_a_recorded_inspection_carries_no_version_and_no_updated_at(api):
    """The event row is append-only: a correction can only be a new cycle's row.

    PRD 2.4: "A quality inspection and a settlement entry each carry only `id` and
    `created_at`: they have **no** `updated_at` and **no** `version`, because nothing
    ever mutates them after they are written."

    Design: Corner/entities/quality_inspection_has_no_version_field_and_no_mutating_endpoint
    """
    scenario = fixtures.stock_edged_job(api)
    recorded = fixtures.inspect_eye(api, scenario["job_id"], "OD")

    inspection = fixtures.read_inspection(api, recorded["id"], MANAGER_A_HEADERS)

    assertions.assert_event_row_fields(inspection)
    assert inspection["cycle_index"] == 0
    assert inspection["tolerance_standard_id"] == scenario["standard_id"]
    assert inspection["verdict"] == "PASS"
    assert inspection["failed_metrics"] == []
    assertions.assert_quality_inspection(inspection)


def test_an_order_naming_a_design_nobody_published_reports_the_design_missing(api):
    """The parent lookup answers before any rule that would read the design's fields.

    PRD 2.10: "**Referenced entity exists.** A foreign key in the request body that
    matches no row of the collection it references is rejected with that collection's
    not-found code (HTTP 404)."

    Design: Corner/entities/rx_order_pointing_at_a_missing_lens_design_returns_lens_design_not_found
    """
    scenario = fixtures.stock_verified_prescription(api)

    error = validate_error(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                UNISSUED_DESIGN_UUID,
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.LENS_DESIGN_NOT_FOUND.value,
        404,
    )

    assert error["error_id"] != ApiErrorId.COATING_NOT_AVAILABLE_FOR_DESIGN.value
    assert error["error_id"] != ApiErrorId.VALIDATION.value

    _, meta = validate_paginated(api.list_rx_orders(OPTICIAN_A_HEADERS))
    assert meta["total_count"] == 0


def test_a_job_is_found_by_filtering_the_collection_on_its_order(api):
    """The child points back at its order and at the layout of record.

    PRD 3.5: "The job is created with `status` `QUEUED`, its `route` as determined
    above, `frame_layout_id` pointing at the newest `COMPUTED` layout,
    `rework_cycle_count` 0, `breakage_count` 0, a null `released_at` and a null
    `scrap_reason`."

    Design: Corner/entities/lab_job_is_reachable_from_its_order_through_the_filtered_list
    """
    scenario = fixtures.stock_queued_job(api)

    rows, meta = validate_paginated(
        api.list_lab_jobs(MANAGER_A_HEADERS, {"rx_order_id": scenario["order_id"]})
    )

    assert len(rows) == 1
    assert rows[0]["id"] == scenario["job_id"]
    assert rows[0]["rx_order_id"] == scenario["order_id"]
    assert rows[0]["frame_layout_id"] == scenario["layout_id"]
    assert rows[0]["blank_lot_id"] is None
    assert rows[0]["route"] == "STOCK_EDGE_ONLY"
    assert rows[0]["status"] == "QUEUED"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
