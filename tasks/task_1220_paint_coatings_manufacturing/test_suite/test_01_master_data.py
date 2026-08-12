"""Master data: customer registration, tint base schema, formula creation
defaults, and the error envelope on missing records."""

import test_helpers as fx
from test_helpers import (
    LAB_TECHNICIAN,
    NON_EXISTENT_UUID,
    PLANT_MANAGER,
    ApiErrorId,
    is_valid_uuid,
    validate_error,
    validate_success,
)


def test_customer_create_defaults_and_computed_zeroes(api):
    """PRD §3.8: "The customer record itself — registered by a `PlantManager`
    with a display `name`, a two-letter `home_state_code`, and the
    `annual_credit_cap_cents` ceiling — therefore always shows
    `credit_balance_cents` as the open memo balance, the settled credits net of
    voids, and `credit_used_ytd_cents` as the year's draw against the cap; both
    start at 0 at registration."
    PRD §2.5: "Before any client touches the clock, it reads exactly
    2026-05-01T00:00:00Z, and it never falls back to wall-clock time."

    Design: Corner/entities/customer_create_defaults_and_computed_zeroes
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    data = validate_success(
        api.create_customer(
            {
                "name": "Sunbelt Paints AZ",
                "home_state_code": "AZ",
                "annual_credit_cap_cents": 50000,
            },
            PLANT_MANAGER,
        ),
        expected_status=201,
    )
    fx.assert_customer(data)
    assert data["credit_balance_cents"] == 0
    assert data["credit_used_ytd_cents"] == 0
    assert is_valid_uuid(data["id"])
    assert isinstance(data["version"], int)
    assert data["created_at"].startswith("2026-05-01T00:00:00"), (
        f"created_at must come from the logical clock, got {data['created_at']}"
    )


def test_customer_create_system_field_input_ignored(api):
    """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
    as a UUID, with no type prefix."
    PRD §3.8: "both start at 0 at registration."

    Design: Corner/entities/customer_create_system_field_input_ignored
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    data = validate_success(
        api.create_customer(
            {
                "name": "Sunbelt Paints AZ",
                "home_state_code": "AZ",
                "annual_credit_cap_cents": 50000,
                "id": "99999999-9999-9999-9999-999999999999",
                "credit_balance_cents": 777,
            },
            PLANT_MANAGER,
        ),
        expected_status=201,
    )
    assert data["id"] != "99999999-9999-9999-9999-999999999999", (
        "the id must be server-minted, not client-supplied"
    )
    assert data["credit_balance_cents"] == 0


def test_formula_create_computed_min_batch_and_version(api):
    """PRD §3.1: "The new formula starts life in `DRAFT` status with
    `formula_version_no` 1 and a null `predecessor_formula_id`; its lines are
    persisted as formula-line records owned by the formula through their
    `formula_id`; and its `min_batch_gallons` is computed as 50 for a custom
    formula and 1 otherwise — the same figure that floors batch sizes and
    order-line quantities for this formula."

    Design: Corner/entities/formula_create_computed_min_batch_and_version
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb2 = fx.create_tb2()
    c2 = fx.create_c2()

    custom = validate_success(
        api.create_formula(
            {
                "formula_code": "CLR-C100",
                "color_name": "Custom Ember",
                "tint_base_id": tb2["id"],
                "is_custom": True,
                "target_delta_e": 0.5,
                "lines": [
                    {"colorant_id": c2["id"], "shots_per_gallon": 6, "sequence": 1}
                ],
            },
            LAB_TECHNICIAN,
        ),
        expected_status=201,
    )
    stock = validate_success(
        api.create_formula(
            {
                "formula_code": "CLR-S10",
                "color_name": "Stock Ash",
                "tint_base_id": tb2["id"],
                "is_custom": False,
                "target_delta_e": 0.8,
                "lines": [
                    {"colorant_id": c2["id"], "shots_per_gallon": 2, "sequence": 1}
                ],
            },
            LAB_TECHNICIAN,
        ),
        expected_status=201,
    )

    fx.assert_formula(custom)
    fx.assert_formula(stock)
    assert custom["min_batch_gallons"] == 50
    assert stock["min_batch_gallons"] == 1
    for formula in (custom, stock):
        assert formula["status"] == "DRAFT"
        assert formula["formula_version_no"] == 1
        assert formula.get("predecessor_formula_id") is None

    lines, _meta = fx.validate_paginated(
        api.list_formula_lines(custom["id"], LAB_TECHNICIAN)
    )
    assert len(lines) == 1
    fx.assert_formula_line(lines[0])
    assert lines[0]["formula_id"] == custom["id"]
    assert lines[0]["shots_per_gallon"] == 6


def test_get_missing_batch_returns_not_found(api):
    """PRD §2.9: "Gate four is existence: every identifier in the path and in
    the body must exist, validated left to right through the path, with the
    first missing identifier producing `ERR_NOT_FOUND`."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/get_missing_batch_returns_not_found
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    response = api.get_batch(NON_EXISTENT_UUID, PLANT_MANAGER)
    error = validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)
    assert error["message"].strip()
    body = response.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]


def test_tint_base_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "The base record also fixes its physical and commercial
    constants: `base_voc_gpl`, the base's own VOC contribution in grams per
    liter of batch volume; `water_fraction_pct`, the percent of batch volume
    that is water, which must be at least 0 and strictly below 100;
    `density_kg_per_gal`, used for fill reconciliation;
    `base_cost_per_gal_cents` and `unit_price_per_gal_cents` for costing and
    pricing; `shelf_life_months`, the calendar-month lifetime stamped onto
    every filled container; and `grind_spec_um`, the maximum acceptable
    dispersion grind reading in microns."
    PRD §2.9: "Gate three is request schema: required fields present, types
    valid, enum values in range, an order's lines array and a disposal
    request's container array non-empty where required, a mill window's end
    strictly after its start, a rule's `effective_to` strictly after its
    `effective_from` when present — violations are `ERR_INVALID_REQUEST`."

    Design: Corner/entities/tint_base_missing_required_field_returns_invalid_request
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    response = api.create_tint_base(
        {
            "base_code": "B-100",
            "product_category": "NONFLAT",
            "base_family": "LATEX_EXTERIOR",
            # base_voc_gpl intentionally omitted
            "water_fraction_pct": 40,
            "density_kg_per_gal": 4.6,
            "base_cost_per_gal_cents": 1500,
            "unit_price_per_gal_cents": 3200,
            "shelf_life_months": 24,
            "grind_spec_um": 25,
        },
        LAB_TECHNICIAN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_tint_base_invalid_enum_rejected(api):
    """PRD §3.1: "A `LabTechnician` registers each base with a unique
    `base_code` (a duplicate code is rejected with `ERR_DUPLICATE_CODE`), a
    `product_category` of `FLAT`, `NONFLAT`, `PRIMER`,
    `INDUSTRIAL_MAINTENANCE`, or `TRAFFIC_MARKING` — the key every VOC rule
    hangs off — and a `base_family` of `LATEX_INTERIOR`, `LATEX_EXTERIOR`, or
    `ALKYD`, which drives the mill washdown sharing described in §2.10."
    PRD §2.9: "Gate three is request schema: required fields present, types
    valid, enum values in range, an order's lines array and a disposal
    request's container array non-empty where required, a mill window's end
    strictly after its start, a rule's `effective_to` strictly after its
    `effective_from` when present — violations are `ERR_INVALID_REQUEST`."

    Design: Corner/entities/tint_base_invalid_enum_rejected
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    response = api.create_tint_base(
        {
            "base_code": "B-100",
            "product_category": "GLOSSY",
            "base_family": "LATEX_EXTERIOR",
            "base_voc_gpl": 80,
            "water_fraction_pct": 40,
            "density_kg_per_gal": 4.6,
            "base_cost_per_gal_cents": 1500,
            "unit_price_per_gal_cents": 3200,
            "shelf_life_months": 24,
            "grind_spec_um": 25,
        },
        LAB_TECHNICIAN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_duplicate_formula_code_rejected(api):
    """PRD §3.1: "A `formula_code` must be unique among all formulas that are
    not `DEPRECATED`; a colliding code is rejected with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/duplicate_formula_code_rejected
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1 = fx.setup_lab_catalog()

    dup = api.create_formula(
        {
            "formula_code": "CLR-8841",
            "color_name": "Duplicate",
            "tint_base_id": tb1["id"],
            "is_custom": False,
            "target_delta_e": 0.9,
            "lines": [
                {"colorant_id": c1["id"], "shots_per_gallon": 2, "sequence": 1}
            ],
        },
        LAB_TECHNICIAN,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)

    # Deprecating the original releases the code for reuse.
    validate_success(api.deprecate_formula(f1["id"], LAB_TECHNICIAN))
    reused = validate_success(
        api.create_formula(
            {
                "formula_code": "CLR-8841",
                "color_name": "Reuse OK",
                "tint_base_id": tb1["id"],
                "is_custom": False,
                "target_delta_e": 0.9,
                "lines": [
                    {"colorant_id": c1["id"], "shots_per_gallon": 2, "sequence": 1}
                ],
            },
            LAB_TECHNICIAN,
        ),
        expected_status=201,
    )
    assert reused["status"] == "DRAFT"


def test_immediate_read_after_write_visibility(api):
    """PRD §2.8: "State changes propagate across aggregate boundaries, and
    every propagation is immediate — all side effects of a request are visible
    in that request's response and in any subsequent read."
    PRD §3.1: "On activation the formula's `activated_at` is stamped from the
    logical clock and its status becomes `ACTIVE`."

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1 = fx.setup_lab_catalog()

    activated = validate_success(api.activate_formula(f1["id"], LAB_TECHNICIAN))
    assert activated["status"] == "ACTIVE", (
        "the mutation must be visible in the mutating response itself"
    )
    reread = validate_success(api.get_formula(f1["id"], LAB_TECHNICIAN))
    assert reread["status"] == "ACTIVE", (
        "the very next read must not observe a stale state"
    )
    assert reread["activated_at"].startswith("2026-05-01T00:00:00"), (
        f"activated_at must come from the logical clock, got {reread['activated_at']}"
    )
