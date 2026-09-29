"""Registering the plant's master data: what the server derives, defaults and refuses.

This module covers the creation contract for the reference records a fastener plant
opens before any material moves — part specifications, furnaces, wire lots and steel
heats — asserting the fields the server derives from other inputs (the embrittlement
bake duty, the drawing reduction), the fields it fills in when the client omits them
(the scrap and count-tolerance fractions, the furnace cooldown), the provenance fields
it mints for itself, and the payloads it refuses outright at the schema tier of the
PRD's rule ladder before any ledger is touched.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_engineer_headers, make_inspector_headers

CLOCK = "2026-09-01T06:00:00Z"


# ---------------------------------------------------------------------------
# Part specification: the derived bake duty and the omitted-fraction defaults
# ---------------------------------------------------------------------------
def test_part_spec_derives_the_bake_duty_from_finish_and_strength_class(api):
    """A ZINC_CLEAR CLASS_10_9 spec is born needing a four-hour relief bake.

    PRD: "`he_bake_required` is true exactly when the part is plated with something — that is, `plating_spec` is not `NONE` — *and* its `strength_class` is one of the three embrittlement-prone classes `CLASS_10_9`, `CLASS_12_9` and `GRADE_8`; in every other combination it is false."

    PRD: "`he_bake_min_minutes` follows from it: zero when no bake is required; a full eight hours, expressed as 480 minutes, for `CLASS_12_9` and `GRADE_8`; and four hours, expressed as 240 minutes, for `CLASS_10_9`."

    Design: Corner/entities/part_spec_creation_derives_bake_fields_and_applies_defaults
    """
    fixtures.set_clock(CLOCK)

    payload = factories.create_part_spec_payload(
        part_number="HX-M8-109",
        strength_class="CLASS_10_9",
        plating_spec="ZINC_CLEAR",
        required_secondary_ops=["THREAD_ROLL", "POINT"],
        max_decarb_depth_mm=0.150,
        packaging_mode="BY_WEIGHT",
        nominal_pack_count=500,
        pieces_per_kg=62.5,
    )
    spec = validate_success(
        api.create_part_spec(payload, make_engineer_headers("eng-1")), 201
    )

    assert spec["he_bake_required"] is True, (
        "A ZINC_CLEAR CLASS_10_9 part is embrittlement-prone and plated, so "
        f"he_bake_required must be true, got {spec['he_bake_required']}"
    )
    assert spec["he_bake_min_minutes"] == 240, (
        f"Expected 240 he_bake_min_minutes for CLASS_10_9, got {spec['he_bake_min_minutes']}"
    )
    # Every submitted field is echoed unchanged, including the ones the bake duty
    # was derived from.
    assert spec["part_number"] == "HX-M8-109", (
        f"Expected part_number HX-M8-109, got {spec['part_number']}"
    )
    assert spec["plating_spec"] == "ZINC_CLEAR", (
        f"Expected plating_spec ZINC_CLEAR, got {spec['plating_spec']}"
    )
    assert spec["strength_class"] == "CLASS_10_9", (
        f"Expected strength_class CLASS_10_9, got {spec['strength_class']}"
    )
    assert spec["required_secondary_ops"] == ["THREAD_ROLL", "POINT"], (
        "required_secondary_ops must be echoed unchanged, got "
        f"{spec['required_secondary_ops']}"
    )
    assert spec["max_decarb_depth_mm"] == pytest.approx(0.150, abs=0.001), (
        f"Expected max_decarb_depth_mm 0.150, got {spec['max_decarb_depth_mm']}"
    )


def test_part_spec_applies_the_scrap_and_count_tolerance_defaults(api):
    """A spec posted without either fraction stores 0.05 and 0.02 at version 1.

    PRD: "A `scrap_allowance_pct` expresses, as a fraction of planned output, how much heading overrun and scrap the process may produce; it defaults to 0.05 when omitted and must be at least 0 and no more than 0.20."

    PRD: "`packaging_mode` is either `BY_COUNT` or `BY_WEIGHT`; `nominal_pack_count` is the target number of pieces per pack and must be at least 1; `pieces_per_kg` is the nominal piece count per kilogram used to derive a declared count from a weighed pack and must be strictly positive; and `count_tolerance_pct` is the fraction of the nominal pack count tolerated as deviation, defaulting to 0.02 when omitted."

    PRD: "**`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at the moment the record was created."

    Design: Corner/entities/part_spec_creation_derives_bake_fields_and_applies_defaults
    """
    fixtures.set_clock(CLOCK)

    payload = factories.create_part_spec_payload(
        part_number="HX-M8-109",
        plating_spec="ZINC_CLEAR",
        packaging_mode="BY_WEIGHT",
        nominal_pack_count=500,
        pieces_per_kg=62.5,
    )
    assert "scrap_allowance_pct" not in payload, "The payload must omit scrap_allowance_pct"
    assert "count_tolerance_pct" not in payload, "The payload must omit count_tolerance_pct"

    spec = validate_success(
        api.create_part_spec(payload, make_engineer_headers("eng-1")), 201
    )

    assert spec["scrap_allowance_pct"] == pytest.approx(0.05, abs=0.001), (
        f"Expected the 0.05 default scrap_allowance_pct, got {spec['scrap_allowance_pct']}"
    )
    assert spec["count_tolerance_pct"] == pytest.approx(0.02, abs=0.001), (
        f"Expected the 0.02 default count_tolerance_pct, got {spec['count_tolerance_pct']}"
    )
    assert spec["version"] == 1, f"A freshly created spec starts at version 1, got {spec['version']}"
    assert is_valid_uuid(spec["id"]), f"id must be a server-minted UUID, got {spec['id']!r}"
    assert is_iso8601_timestamp(spec["created_at"]), (
        f"created_at must be ISO 8601, got {spec['created_at']!r}"
    )
    assert spec["created_at"].startswith("2026-09-01T06:00:00"), (
        "created_at is taken from the logical clock, expected 2026-09-01T06:00:00, got "
        f"{spec['created_at']}"
    )


# ---------------------------------------------------------------------------
# Furnace: the cooldown default and the opening run state
# ---------------------------------------------------------------------------
def test_furnace_omitting_cooldown_minutes_stores_thirty(api):
    """A furnace registered without a cooldown buffer gets the plant's 30-minute default.

    PRD: "Heat treatment runs on furnaces, which a `ProcessEngineer` or `PlantAdmin` registers with a unique `furnace_code`, a strictly positive `max_charge_mass_kg` per run, and an optional `cooldown_minutes` — the mandatory idle buffer after a run window before the next one may open — which defaults to 30 minutes and may not be negative."

    PRD: "A furnace starts `IDLE` with `last_run_end_at` empty."

    Design: Corner/entities/furnace_defaults_cooldown_to_thirty_minutes
    """
    fixtures.set_clock(CLOCK)

    payload = {"furnace_code": "FCE-1", "max_charge_mass_kg": 400.0}
    furnace = validate_success(
        api.create_furnace(payload, make_engineer_headers("eng-1")), 201
    )

    assert furnace["cooldown_minutes"] == 30, (
        f"Expected the 30-minute default cooldown_minutes, got {furnace['cooldown_minutes']}"
    )
    assert furnace["status"] == "IDLE", (
        f"Expected a fresh furnace to start IDLE, got {furnace['status']}"
    )
    assert furnace["last_run_end_at"] is None, (
        f"Expected last_run_end_at empty on a fresh furnace, got {furnace['last_run_end_at']}"
    )
    assert furnace["max_charge_mass_kg"] == pytest.approx(400.0, abs=0.001), (
        f"Expected max_charge_mass_kg 400.0, got {furnace['max_charge_mass_kg']}"
    )
    assert furnace["version"] == 1, (
        f"A freshly registered furnace starts at version 1, got {furnace['version']}"
    )


# ---------------------------------------------------------------------------
# Wire lot: the reduction the server computes and the ledger it opens
# ---------------------------------------------------------------------------
def test_wire_lot_reduction_pct_is_derived_from_the_two_diameters(api):
    """Drawing 8.00 mm down to 6.80 mm stores a reduction of 27.75 percent.

    PRD: "The server derives `reduction_pct` from the diameters: divide the outlet diameter by the inlet diameter, square that ratio to get the surviving cross-sectional area fraction, subtract it from one, multiply by one hundred, and round the result half up to two decimal places."

    PRD: "The three mass ledger members are initialised so the identity holds trivially — `available_mass_kg` equals `gross_mass_kg`, while `reserved_mass_kg` and `consumed_mass_kg` are both zero — and `status` starts at `DRAWN` with `quarantine_source` of `NONE` and `inspected_at` empty."

    Design: Corner/entities/wire_lot_reduction_pct_computed_from_diameters
    """
    fixtures.set_clock(CLOCK)
    # A heat gives the wire lot a resolvable parent; it is deliberately left
    # unverified, which does not block registering the drawn coil.
    heat = validate_success(
        api.create_steel_heat(
            factories.create_steel_heat_payload(
                heat_number="H-77410", grade="SAE_10B21", gross_mass_kg=500.0
            ),
            make_inspector_headers("insp-1"),
        ),
        201,
    )

    payload = factories.create_wire_lot_payload(
        heat["id"],
        draw_pass_count=3,
        inlet_diameter_mm=8.00,
        outlet_diameter_mm=6.80,
        lubricant_coating="PHOSPHATE",
        coating_weight_gsm=4.5,
        gross_mass_kg=500.0,
    )
    assert "reduction_pct" not in payload, "reduction_pct is not an input at all"

    wire = validate_success(
        api.create_wire_lot(payload, make_engineer_headers("eng-1")), 201
    )

    assert wire["reduction_pct"] == pytest.approx(27.75, abs=0.001), (
        "100 * (1 - (6.80/8.00)^2) rounded half up to 2 dp is 27.75, got "
        f"{wire['reduction_pct']}"
    )
    assert wire["available_mass_kg"] == pytest.approx(500.000, abs=0.001), (
        f"available_mass_kg opens at gross_mass_kg, got {wire['available_mass_kg']}"
    )
    assert wire["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"reserved_mass_kg opens at zero, got {wire['reserved_mass_kg']}"
    )
    assert wire["consumed_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"consumed_mass_kg opens at zero, got {wire['consumed_mass_kg']}"
    )
    assert wire["status"] == "DRAWN", (
        f"A newly recorded coil starts DRAWN, got {wire['status']}"
    )
    assert wire["quarantine_source"] == "NONE", (
        f"Expected quarantine_source NONE on a fresh coil, got {wire['quarantine_source']}"
    )
    assert wire["inspected_at"] is None, (
        f"Expected inspected_at empty before release, got {wire['inspected_at']}"
    )
    assert wire["steel_heat_id"] == heat["id"], (
        f"Expected steel_heat_id {heat['id']}, got {wire['steel_heat_id']}"
    )
    assert wire["version"] == 1, (
        f"A freshly recorded wire lot starts at version 1, got {wire['version']}"
    )


# ---------------------------------------------------------------------------
# Steel heat: the provenance fields only the server may write
# ---------------------------------------------------------------------------
def test_steel_heat_provenance_fields_start_empty_and_ids_are_server_minted(api):
    """A freshly registered heat carries PENDING paperwork and no verification trail.

    PRD: "A new heat begins with `cert_status` of `PENDING`, with `lab_report_reference`, `verified_at`, `verified_by_user_id` and `counterfeit_reason` all empty."

    PRD: "It carries no type prefix and is never supplied by the client."

    PRD: "**`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed from the logical clock on every mutation of the record."

    Design: Corner/entities/steel_heat_system_fields_are_server_generated
    """
    fixtures.set_clock(CLOCK)

    payload = factories.create_steel_heat_payload(
        heat_number="H-77410",
        mill_code="MC-A",
        grade="SAE_10B21",
        carbon_pct=0.21,
        boron_ppm=25,
        gross_mass_kg=500.0,
        mill_cert_serial="MC-2026-000481",
    )
    heat = validate_success(
        api.create_steel_heat(payload, make_inspector_headers("insp-1")), 201
    )

    assert heat["cert_status"] == "PENDING", (
        f"A new heat's paperwork starts PENDING, got {heat['cert_status']}"
    )
    for field in (
        "lab_report_reference",
        "verified_at",
        "verified_by_user_id",
        "counterfeit_reason",
    ):
        assert heat[field] is None, (
            f"Expected {field} empty on a freshly registered heat, got {heat[field]}"
        )

    assert is_valid_uuid(heat["id"]), (
        f"id must be a server-minted UUID, got {heat['id']!r}"
    )
    assert heat["id"] not in payload.values(), (
        "id must not be a value present in the request body"
    )
    assert heat["created_at"].startswith("2026-09-01T06:00:00"), (
        f"created_at is read from the logical clock, got {heat['created_at']}"
    )
    assert heat["updated_at"].startswith("2026-09-01T06:00:00"), (
        f"updated_at is read from the logical clock, got {heat['updated_at']}"
    )
    assert heat["version"] == 1, (
        f"A freshly registered heat starts at version 1, got {heat['version']}"
    )


# ---------------------------------------------------------------------------
# Production lot: the payloads the schema tier refuses before anything is reserved
# ---------------------------------------------------------------------------
def _lot_opening_environment():
    """Part spec, VERIFIED heat, RELEASED 500 kg coil and a MOUNTED die set on PRESS-3."""
    return fixtures.setup_master_data(
        clock=CLOCK,
        unplated=True,
        spec_overrides={
            "part_number": "NP-M8-088",
            "max_decarb_depth_mm": 0.100,
            "nominal_pack_count": 100,
            "pieces_per_kg": 62.5,
        },
        wire_overrides={"gross_mass_kg": 500.0},
        tool_overrides={"rated_life_pieces": 120000},
        press_code="PRESS-3",
    )


def test_production_lot_without_expected_wire_lot_version_is_rejected(api):
    """Omitting the wire lot's expected version is a schema violation, not a reservation.

    PRD: "**Opening a production lot** — `POST /production-lots` — requires a non-optional `expected_wire_lot_version` field carrying the `version` the client last observed on the wire lot named by `wire_lot_id`."

    PRD: "**Schema.** Required fields present, enum values within their declared sets, numbers within their declared constraints, datetimes well-formed ISO 8601 UTC, `press_window_end_at` strictly after `press_window_start_at`, `window_end_at` strictly after `window_start_at`, `planned_pieces` at least 1, `sequence_no` at least 1, `limit` within its declared range and `offset` not negative — otherwise `ERR_VALIDATION` (400)."

    PRD: "Opening a production lot moves mass from available to reserved."

    Design: Corner/entities/production_lot_rejects_a_payload_missing_the_occ_field
    """
    env = _lot_opening_environment()
    wire_before = fixtures.read_wire_lot(env["wire"]["id"])

    payload = {
        "lot_code": "L-2601",
        "part_spec_id": env["spec"]["id"],
        "wire_lot_id": env["wire"]["id"],
        "heading_tool_id": env["tool"]["id"],
        "press_code": "PRESS-3",
        "press_window_start_at": "2026-09-01T06:00:00Z",
        "press_window_end_at": "2026-09-01T10:00:00Z",
        "planned_pieces": 5000,
    }
    resp = api.create_production_lot(payload, make_engineer_headers("eng-1"))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(
        api.list_production_lots(
            make_engineer_headers("eng-1"), params={"wire_lot_id": env["wire"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"No lot row may be written by a rejected create, got total_count {meta['total_count']}"
    )

    wire_after = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire_after["available_mass_kg"] == pytest.approx(500.000, abs=0.001), (
        "No reservation may be attempted, so available_mass_kg stays at 500.000, got "
        f"{wire_after['available_mass_kg']}"
    )
    assert wire_after["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"reserved_mass_kg must stay 0.000, got {wire_after['reserved_mass_kg']}"
    )
    assert wire_after["version"] == wire_before["version"], (
        f"Expected the wire lot version to stay {wire_before['version']}, got "
        f"{wire_after['version']}"
    )


def test_production_lot_with_an_inverted_press_window_is_rejected(api):
    """A window that ends before it starts fails the schema tier, not the overlap rule.

    PRD: "**Schema.** Required fields present, enum values within their declared sets, numbers within their declared constraints, datetimes well-formed ISO 8601 UTC, `press_window_end_at` strictly after `press_window_start_at`, `window_end_at` strictly after `window_start_at`, `planned_pieces` at least 1, `sequence_no` at least 1, `limit` within its declared range and `offset` not negative — otherwise `ERR_VALIDATION` (400)."

    PRD: "**The first rule violated decides the response, and no later rule runs.**"

    Design: Corner/entities/production_lot_rejects_a_press_window_that_ends_before_it_starts
    """
    env = _lot_opening_environment()
    wire_before = fixtures.read_wire_lot(env["wire"]["id"])

    payload = factories.create_production_lot_payload(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        wire_before["version"],
        lot_code="L-2601",
        press_code="PRESS-3",
        press_window_start_at="2026-09-01T10:00:00Z",
        press_window_end_at="2026-09-01T06:00:00Z",
        planned_pieces=5000,
    )
    resp = api.create_production_lot(payload, make_engineer_headers("eng-1"))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(
        api.list_production_lots(
            make_engineer_headers("eng-1"), params={"wire_lot_id": env["wire"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"No lot row may be written by a rejected create, got total_count {meta['total_count']}"
    )

    wire_after = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire_after["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"reserved_mass_kg must stay 0.000, got {wire_after['reserved_mass_kg']}"
    )
    assert wire_after["version"] == wire_before["version"], (
        f"Expected the wire lot version to stay {wire_before['version']}, got "
        f"{wire_after['version']}"
    )


# ---------------------------------------------------------------------------
# Part specification: the enum domain of strength_class
# ---------------------------------------------------------------------------
def test_part_spec_with_an_unknown_strength_class_is_rejected_and_nothing_persists(api):
    """CLASS_9_9 is outside the declared strength_class set, so no spec row is written.

    PRD: "The payload carries the customer's `part_number` (unique across the plant), the thread callout in `thread_designation` (a value such as M8x1.25), the target `strength_class` — one of `CLASS_8_8`, `CLASS_10_9`, `CLASS_12_9`, `GRADE_5` or `GRADE_8` — and the `qualification_program` under which the part is built, which is `NONE`, `AUTOMOTIVE_PPAP` or `AEROSPACE_NADCAP` and defaults to `NONE` when omitted."

    PRD: "**Schema.** Required fields present, enum values within their declared sets, numbers within their declared constraints, datetimes well-formed ISO 8601 UTC, `press_window_end_at` strictly after `press_window_start_at`, `window_end_at` strictly after `window_start_at`, `planned_pieces` at least 1, `sequence_no` at least 1, `limit` within its declared range and `offset` not negative — otherwise `ERR_VALIDATION` (400)."

    PRD: "Every other business identifier collision reports `ERR_DUPLICATE_IDENTIFIER` (409): `part_number` on part-spec registration, `lot_code` on lot opening, `tool_code` on die-set registration, `furnace_code` on furnace registration, `cert_serial` on certificate drafting and on certificate reissue, `label_serial` on pack-unit opening — each unique across the whole plant — and `sequence_no` on secondary-operation queueing, unique within its production lot."

    Design: Corner/entities/part_spec_rejects_an_unknown_strength_class_enum
    """
    fixtures.set_clock(CLOCK)
    headers = make_engineer_headers("eng-1")

    bad = factories.create_part_spec_payload(
        part_number="BAD-M8-001",
        strength_class="CLASS_9_9",
        plating_spec="NONE",
        max_decarb_depth_mm=0.100,
        nominal_pack_count=100,
        pieces_per_kg=62.5,
    )
    validate_error(
        api.create_part_spec(bad, headers), ApiErrorId.ERR_VALIDATION.value
    )

    # Nothing was persisted under that part_number: reposting it with a declared
    # strength class succeeds instead of colliding on the unique identifier.
    good = factories.create_part_spec_payload(
        part_number="BAD-M8-001",
        strength_class="CLASS_10_9",
        plating_spec="NONE",
        max_decarb_depth_mm=0.100,
        nominal_pack_count=100,
        pieces_per_kg=62.5,
    )
    spec = validate_success(api.create_part_spec(good, headers), 201)
    assert spec["part_number"] == "BAD-M8-001", (
        f"Expected part_number BAD-M8-001, got {spec['part_number']}"
    )
    assert spec["strength_class"] == "CLASS_10_9", (
        f"Expected strength_class CLASS_10_9, got {spec['strength_class']}"
    )
    assert spec["version"] == 1, (
        f"The surviving spec is the first row under that part number, got version {spec['version']}"
    )
