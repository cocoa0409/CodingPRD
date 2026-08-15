"""Measurement sheets, freezing, sail-area computation, and class certificates."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_class_certificate,
    assert_measurement_sheet,
    create_boat,
    create_class_certificate,
    create_customer,
    create_frozen_sheet,
    create_measurement_sheet,
    freeze_measurement_sheet,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

MGR = TEST_USERS["loft_manager_headers"]
MEAS = TEST_USERS["measurer_headers"]


def test_measurement_sheet_created_in_draft(api):
    """PRD §3.2: "The sheet is created in `DRAFT` status with `frozen_at` null,
    and it records the capturing operator's `X-User-ID` as `captured_by_measurer_id`
    alongside its `boat_id`."

    Design: Corner/state_machines/measurement_sheet_initial_state_draft
    """
    customer = create_customer(full_name="C24")
    boat = create_boat(customer["id"], boat_name="B24", hull_length_m=9.0)
    resp = api.create_measurement_sheet(
        boat["id"],
        {"i_height_m": 10.0, "j_base_m": 3.0, "p_main_m": 12.0, "e_main_m": 4.0},
        MEAS,
    )
    sheet = validate_success(resp, expected_status=201)
    assert_measurement_sheet(sheet)
    assert sheet["sheet_status"] == "DRAFT", f"new sheet must be DRAFT, got {sheet['sheet_status']}"
    assert sheet["frozen_at"] is None, f"frozen_at must be null while DRAFT, got {sheet['frozen_at']}"


def test_measurement_sheet_list_paginates(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/measurement_sheet_list_supports_pagination
    """
    customer = create_customer(full_name="C21")
    boat = create_boat(customer["id"], boat_name="B21", hull_length_m=9.0)
    create_measurement_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)
    create_measurement_sheet(boat["id"], i_height_m=11.0, j_base_m=3.5, p_main_m=13.0, e_main_m=4.5)

    resp = api.list_measurement_sheets(boat["id"], MEAS, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be true with 2 rows and limit 1, got {meta['has_more']}"


def test_freeze_computes_measured_area(api):
    """PRD §3.2: "On a successful freeze the sheet's `measured_area_sqm` is
    computed and stored: the mainsail area is one half of `p_main_m` multiplied by
    `e_main_m`, the foretriangle area is one half of `i_height_m` multiplied by
    `j_base_m`, and the measured area is the sum of those two products, rounded
    half-up to two decimal places."

    Design: Corner/calculations/sail_area_computed_on_freeze
    """
    customer = create_customer(full_name="C26")
    boat = create_boat(customer["id"], boat_name="B26", hull_length_m=9.0)
    sheet = create_measurement_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)

    resp = api.freeze_measurement_sheet(boat["id"], sheet["id"], MEAS)
    frozen = validate_success(resp, expected_status=200)
    assert frozen["sheet_status"] == "FROZEN"
    # 0.5*12*4 + 0.5*10*3 = 24 + 15 = 39.00
    assert float(frozen["measured_area_sqm"]) == pytest.approx(39.00, abs=1e-6), (
        f"measured_area_sqm must be 39.00, got {frozen['measured_area_sqm']}"
    )
    assert frozen["frozen_at"] is not None, "freeze must stamp frozen_at"


def test_freeze_rejects_non_positive_dimension(api):
    """PRD §3.2: "When the `Measurer` freezes a sheet, all four dimensions must be
    positive numbers — any non-positive value is rejected with
    `ERR_INVALID_MEASUREMENT` (HTTP 422)."

    Design: Corner/validations/measurement_freeze_rejects_non_positive_dimension
    """
    customer = create_customer(full_name="C29")
    boat = create_boat(customer["id"], boat_name="B29", hull_length_m=9.0)
    sheet = create_measurement_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=0.0)

    resp = api.freeze_measurement_sheet(boat["id"], sheet["id"], MEAS)
    validate_error(resp, ApiErrorId.ERR_INVALID_MEASUREMENT)

    after = validate_success(api.get_measurement_sheet(sheet["id"], MEAS))
    assert after["sheet_status"] == "DRAFT", f"rejected freeze must leave DRAFT, got {after['sheet_status']}"


def test_freeze_supersedes_prior_frozen_and_revokes_certificate(api):
    """PRD §3.2: "Freezing a newer sheet for a boat automatically transitions any
    previously `FROZEN` sheet for that boat to the terminal `SUPERSEDED`, and the
    supersede cascades outward: every **class certificate** referencing the
    superseded sheet transitions from `ACTIVE` to `REVOKED`, and every sail design
    in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` that pins the superseded sheet
    transitions to `ARCHIVED`."

    Design: Corner/state_machines/freeze_sheet_supersedes_prior_frozen_and_revokes_certificate
    """
    customer = create_customer(full_name="C25")
    boat = create_boat(customer["id"], boat_name="B25", hull_length_m=6.5, racing_class="J70")
    sheet_a = create_frozen_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)
    cert = create_class_certificate(boat["id"], sheet_a["id"], "J70")
    assert_class_certificate(cert)
    assert cert["cert_status"] == "ACTIVE"

    sheet_b = create_measurement_sheet(boat["id"], i_height_m=10.5, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)
    freeze_measurement_sheet(boat["id"], sheet_b["id"])

    old_sheet = validate_success(api.get_measurement_sheet(sheet_a["id"], MEAS))
    new_sheet = validate_success(api.get_measurement_sheet(sheet_b["id"], MEAS))
    revoked = validate_success(api.get_class_certificate(cert["id"], MEAS))
    assert old_sheet["sheet_status"] == "SUPERSEDED", (
        f"prior FROZEN sheet must be SUPERSEDED, got {old_sheet['sheet_status']}"
    )
    assert new_sheet["sheet_status"] == "FROZEN", f"new sheet must be FROZEN, got {new_sheet['sheet_status']}"
    assert revoked["cert_status"] == "REVOKED", (
        f"certificate on superseded sheet must be REVOKED, got {revoked['cert_status']}"
    )


def test_class_certificate_rejects_class_mismatch(api):
    """PRD §3.2: "Issuance is refused with `ERR_CLASS_MISMATCH` (HTTP 422) when the
    certificate's `racing_class` differs from the boat's own `racing_class`, when
    the boat's `racing_class` is `NONE`, or when the referenced sheet is not in
    `FROZEN` status."

    Design: Corner/validations/class_certificate_rejects_class_mismatch
    """
    customer = create_customer(full_name="C33")
    boat = create_boat(customer["id"], boat_name="B33", hull_length_m=6.5, racing_class="J70")
    sheet = create_frozen_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)

    resp = api.create_class_certificate(
        boat["id"], {"measurement_sheet_id": sheet["id"], "racing_class": "J105"}, MEAS
    )
    validate_error(resp, ApiErrorId.ERR_CLASS_MISMATCH)
