"""Reading the plant's records back out again.

This module covers the read side of the fastener API as PRD.md specifies it: the
entity-specific 404 each path-placeholder family answers an unknown identifier
with, the life projection a freshly registered die set hands back on a plain
read, the paginated production-lot listing and its filtered ``total_count`` and
``has_more``, the refusal of an unresolvable foreign key supplied in a request
body, and a production lot's pinned part-specification version surviving a later
revision of that very specification untouched.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_heading_tool,
    assert_production_lot,
    assert_sorted_by_created_at_asc,
    assert_wire_lot,
    assert_wire_mass_ledger,
    create_heading_tool_payload,
    create_production_lot_payload,
    create_wire_lot_payload,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# The unassigned identifier every "unknown id" probe below reaches for. No
# record in an empty plant can ever carry it.
UNASSIGNED_ID = "00000000-0000-0000-0000-0000000000ff"

CLOCK = "2026-09-01T06:00:00Z"


# ---------------------------------------------------------------------------
# Unknown identifiers
# ---------------------------------------------------------------------------
NOT_FOUND_PROBES = [
    (
        "part specification",
        ApiErrorId.ERR_PART_SPEC_NOT_FOUND.value,
        lambda api, hdr: api.get_part_spec(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "steel heat",
        ApiErrorId.ERR_STEEL_HEAT_NOT_FOUND.value,
        lambda api, hdr: api.get_steel_heat(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "wire lot",
        ApiErrorId.ERR_WIRE_LOT_NOT_FOUND.value,
        lambda api, hdr: api.get_wire_lot(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "heading tool",
        ApiErrorId.ERR_HEADING_TOOL_NOT_FOUND.value,
        lambda api, hdr: api.get_heading_tool(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "furnace",
        ApiErrorId.ERR_FURNACE_NOT_FOUND.value,
        lambda api, hdr: api.get_furnace(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "production lot",
        ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND.value,
        lambda api, hdr: api.get_production_lot(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "secondary operation",
        ApiErrorId.ERR_SECONDARY_OPERATION_NOT_FOUND.value,
        lambda api, hdr: api.complete_secondary_operation(
            UNASSIGNED_ID, {"pieces_out": 10}, hdr["engineer"]
        ),
    ),
    (
        "heat treatment run",
        ApiErrorId.ERR_HEAT_TREAT_RUN_NOT_FOUND.value,
        lambda api, hdr: api.get_heat_treat_run(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "plating run",
        ApiErrorId.ERR_PLATING_RUN_NOT_FOUND.value,
        lambda api, hdr: api.complete_plating(UNASSIGNED_ID, hdr["heat_treat"]),
    ),
    (
        "lot test",
        ApiErrorId.ERR_LOT_TEST_NOT_FOUND.value,
        lambda api, hdr: api.record_lot_test_results(
            UNASSIGNED_ID,
            {
                "proof_load_failures": 0,
                "tensile_failures": 0,
                "min_measured_core_hardness_hv": 320.0,
            },
            hdr["inspector"],
        ),
    ),
    (
        "certification document",
        ApiErrorId.ERR_CERT_DOCUMENT_NOT_FOUND.value,
        lambda api, hdr: api.get_certification_document(UNASSIGNED_ID, hdr["admin"]),
    ),
    (
        "pack unit",
        ApiErrorId.ERR_PACK_UNIT_NOT_FOUND.value,
        lambda api, hdr: api.get_pack_unit(UNASSIGNED_ID, hdr["admin"]),
    ),
]


@pytest.mark.parametrize(
    "resource, expected_error_id, probe",
    NOT_FOUND_PROBES,
    ids=[case[0].replace(" ", "_") for case in NOT_FOUND_PROBES],
)
def test_unknown_id_answers_with_its_own_not_found_code(
    api,
    resource,
    expected_error_id,
    probe,
    admin_headers,
    engineer_headers,
    heat_treat_headers,
    inspector_headers,
):
    """Each of the twelve path-placeholder families refuses an unassigned id with its own 404.

    PRD: "**Path existence**, left to right, yielding the 404 code for whichever resource type failed to resolve: `ERR_PART_SPEC_NOT_FOUND`, `ERR_STEEL_HEAT_NOT_FOUND`, `ERR_WIRE_LOT_NOT_FOUND`, `ERR_HEADING_TOOL_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_SECONDARY_OPERATION_NOT_FOUND`, `ERR_HEAT_TREAT_RUN_NOT_FOUND`, `ERR_PLATING_RUN_NOT_FOUND`, `ERR_LOT_TEST_NOT_FOUND`, `ERR_CERT_DOCUMENT_NOT_FOUND`, `ERR_PACK_UNIT_NOT_FOUND`."

    PRD: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/unknown_ids_return_their_own_not_found_error
    """
    fixtures.set_clock(CLOCK)

    headers = {
        "admin": admin_headers,
        "engineer": engineer_headers,
        "heat_treat": heat_treat_headers,
        "inspector": inspector_headers,
    }
    response = probe(api, headers)

    error = validate_error(response, expected_error_id, 404)
    assert response.status_code == 404, (
        f"Expected HTTP 404 for an unknown {resource} id, got {response.status_code}"
    )
    assert error["error_id"] == expected_error_id, (
        f"Expected {expected_error_id} for an unknown {resource} id, "
        f"got {error['error_id']}"
    )
    body = response.json()
    assert body["response_type"] == "error", (
        f"Expected response_type 'error' for an unknown {resource} id, "
        f"got {body['response_type']!r}"
    )
    assert body["data"]["message"].strip(), (
        f"Expected a human-readable message alongside {expected_error_id}"
    )


# ---------------------------------------------------------------------------
# The die set's initial life projection
# ---------------------------------------------------------------------------
def test_fresh_die_set_read_returns_its_initial_life_projection(
    api, engineer_headers, manager_headers
):
    """A read of a just-registered die set shows both budgets at the nameplate and no history.

    PRD: "A fresh set begins `AVAILABLE`, with `regrind_count` and `cumulative_pieces_current_cycle` at zero, an empty `cycle_pieces_history`, `completed_cycle_count` and `lifetime_pieces` at zero, `observed_avg_cycle_pieces` empty, and `mounted_press_code` and `condemn_reason` both empty."

    PRD: "`rated_derated_life_pieces` is the nameplate `rated_life_pieces` multiplied by one minus 0.15 for each completed regrind — that is, by one minus the product of `regrind_count` and 0.15 — with the result truncated downward to a whole number of pieces."

    PRD: "When `completed_cycle_count` is zero there is no history to listen to: `observed_avg_cycle_pieces` is empty and `conservative_life_pieces` simply equals `rated_derated_life_pieces`."

    PRD: "and optionally `max_regrinds`, the number of regrind cycles it may take before condemnation, which defaults to 3 and may not be negative."

    Design: Corner/entities/heading_tool_read_returns_its_initial_life_projection
    """
    fixtures.set_clock(CLOCK)

    created = validate_success(
        api.create_heading_tool(
            create_heading_tool_payload(
                tool_code="DIE-4S-001", station_count=4, rated_life_pieces=120000
            ),
            engineer_headers,
        ),
        201,
    )

    tool = validate_success(api.get_heading_tool(created["id"], manager_headers), 200)
    assert_heading_tool(tool)

    assert tool["id"] == created["id"], "The read must return the die set that was stored"
    assert tool["tool_code"] == "DIE-4S-001", (
        f"Expected tool_code DIE-4S-001, got {tool['tool_code']}"
    )
    assert tool["station_count"] == 4, (
        f"Expected station_count 4, got {tool['station_count']}"
    )
    assert tool["rated_life_pieces"] == 120000, (
        f"Expected the 120000 nameplate, got {tool['rated_life_pieces']}"
    )

    # No regrind has happened, so the derate factor is one and both budgets equal
    # the nameplate.
    assert tool["rated_derated_life_pieces"] == 120000, (
        f"Expected rated_derated_life_pieces 120000 with regrind_count 0, "
        f"got {tool['rated_derated_life_pieces']}"
    )
    assert tool["conservative_life_pieces"] == 120000, (
        f"Expected conservative_life_pieces to fall back to the derated nameplate "
        f"120000, got {tool['conservative_life_pieces']}"
    )
    assert tool["observed_avg_cycle_pieces"] is None, (
        f"Expected observed_avg_cycle_pieces empty with no closed cycle, "
        f"got {tool['observed_avg_cycle_pieces']}"
    )

    assert tool["cycle_pieces_history"] == [], (
        f"Expected an empty cycle_pieces_history, got {tool['cycle_pieces_history']}"
    )
    assert tool["completed_cycle_count"] == 0, (
        f"Expected completed_cycle_count 0, got {tool['completed_cycle_count']}"
    )
    assert tool["lifetime_pieces"] == 0, (
        f"Expected lifetime_pieces 0, got {tool['lifetime_pieces']}"
    )
    assert tool["regrind_count"] == 0, (
        f"Expected regrind_count 0, got {tool['regrind_count']}"
    )
    assert tool["max_regrinds"] == 3, (
        f"Expected max_regrinds to default to 3, got {tool['max_regrinds']}"
    )
    assert tool["cumulative_pieces_current_cycle"] == 0, (
        f"Expected cumulative_pieces_current_cycle 0, "
        f"got {tool['cumulative_pieces_current_cycle']}"
    )

    assert tool["status"] == "AVAILABLE", (
        f"Expected a fresh set to be AVAILABLE, got {tool['status']}"
    )
    assert tool["mounted_press_code"] is None, (
        f"Expected mounted_press_code empty on an unmounted set, "
        f"got {tool['mounted_press_code']}"
    )
    assert tool["condemn_reason"] is None, (
        f"Expected condemn_reason empty on a fresh set, got {tool['condemn_reason']}"
    )
    assert tool["version"] == 1, (
        f"Expected version 1 on a record that has never been mutated, "
        f"got {tool['version']}"
    )


# ---------------------------------------------------------------------------
# Paginated production-lot listing
# ---------------------------------------------------------------------------
def test_production_lot_listing_paginates_and_counts_the_filtered_set(
    api, clerk_headers
):
    """Three lots on one die set page two at a time, and the SETUP filter still counts all three.

    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object."

    PRD: "Both `total_count` and `has_more` are computed against the *filtered* result set, not against the whole collection: when a caller filters wire lots by `steel_heat_id` and `status`, `total_count` reports how many wire lots match those filters, and `has_more` reports whether records matching those filters remain beyond the current page."

    PRD: "Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order."

    PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

    Design: Corner/entities/production_lot_listing_paginates_with_total_count_and_has_more
    """
    env = fixtures.setup_master_data(
        clock=CLOCK,
        unplated=True,
        spec_overrides={"part_number": "NP-M8-088", "blank_mass_g": 20.0},
        wire_overrides={"gross_mass_kg": 500.0},
        tool_overrides={"tool_code": "DIE-4S-001", "rated_life_pieces": 120000},
    )

    # Three lots of 1000 pieces on disjoint press windows of the same die set.
    windows = [
        ("2026-09-01T06:00:00Z", "2026-09-01T08:00:00Z"),
        ("2026-09-01T08:00:00Z", "2026-09-01T10:00:00Z"),
        ("2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"),
    ]
    lot_ids = []
    for index, (window_start, window_end) in enumerate(windows, start=1):
        lot = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            lot_code=f"L-260{index}",
            press_code=env["press_code"],
            press_window_start_at=window_start,
            press_window_end_at=window_end,
            planned_pieces=1000,
        )
        lot_ids.append(lot["id"])

    first_page, first_meta = validate_paginated(
        api.list_production_lots(clerk_headers, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, (
        f"Expected 2 rows on a limit=2 first page, got {len(first_page)}"
    )
    assert first_meta["total_count"] == 3, (
        f"Expected total_count 3 across the whole collection, "
        f"got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "Expected has_more true with a third lot beyond the first page"
    )
    assert first_meta["limit"] == 2, f"Expected limit 2 echoed, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, (
        f"Expected offset 0 echoed, got {first_meta['offset']}"
    )

    second_page, second_meta = validate_paginated(
        api.list_production_lots(clerk_headers, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, (
        f"Expected 1 row on the second page, got {len(second_page)}"
    )
    assert second_meta["total_count"] == 3, (
        f"Expected total_count 3 on the second page too, "
        f"got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "Expected has_more false once the last lot has been returned"
    )

    walked = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(walked)) == 3, f"Expected no repetition across the pages, got {walked}"
    assert set(walked) == set(lot_ids), (
        f"Expected the two pages to cover exactly {lot_ids}, got {walked}"
    )
    assert_sorted_by_created_at_asc(first_page + second_page)

    filtered, filtered_meta = validate_paginated(
        api.list_production_lots(
            clerk_headers, {"process_state": "SETUP", "limit": 10, "offset": 0}
        )
    )
    assert len(filtered) == 3, (
        f"Expected all 3 SETUP lots on one page of 10, got {len(filtered)}"
    )
    assert filtered_meta["total_count"] == 3, (
        f"Expected the filtered total_count to be 3, got {filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False, (
        "Expected has_more false when every matching lot fits on the page"
    )
    for row in filtered:
        assert_production_lot(row)
        assert row["process_state"] == "SETUP", (
            f"Expected every filtered row in SETUP, got {row['process_state']}"
        )
        assert row["disposition"] == "IN_PROCESS", (
            f"Expected a newly opened lot to be IN_PROCESS, got {row['disposition']}"
        )

    # Each lot reserved 1000 x 20.0 g x 1.05 / 1000 = 21.000 kg of the coil.
    wire = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire["reserved_mass_kg"] == pytest.approx(63.000, abs=0.001), (
        f"Expected 63.000 kg reserved after three 21.000 kg reservations, "
        f"got {wire['reserved_mass_kg']}"
    )
    assert wire["available_mass_kg"] == pytest.approx(437.000, abs=0.001), (
        f"Expected 437.000 kg still free, got {wire['available_mass_kg']}"
    )
    assert_wire_mass_ledger(wire)


# ---------------------------------------------------------------------------
# Unresolvable foreign keys in the request body
# ---------------------------------------------------------------------------
def test_wire_lot_registration_rejects_an_unknown_steel_heat(api, engineer_headers):
    """A drawn coil cannot be recorded against a steel heat the register has never seen.

    PRD: "**Body foreign-key existence**, in input-field order, yielding `ERR_PART_SPEC_NOT_FOUND`, `ERR_STEEL_HEAT_NOT_FOUND`, `ERR_WIRE_LOT_NOT_FOUND`, `ERR_HEADING_TOOL_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_LOT_TEST_NOT_FOUND` or `ERR_CERT_DOCUMENT_NOT_FOUND`."

    PRD: "A `ProcessEngineer` or `PlantAdmin` records a drawn and coated lot against a `steel_heat_id`, giving the `draw_pass_count` (at least 1), the `inlet_diameter_mm` entering the bench and the `outlet_diameter_mm` leaving it (both strictly positive, with the outlet strictly smaller than the inlet), the `lubricant_coating` applied — `PHOSPHATE`, `POLYMER`, `LIME` or `NONE` — the `coating_weight_gsm` in grams per square metre (not negative), and the `gross_mass_kg` of drawn wire (strictly positive)."

    Design: Corner/entities/wire_lot_rejects_an_unknown_steel_heat_parent
    """
    fixtures.set_clock(CLOCK)

    response = api.create_wire_lot(
        create_wire_lot_payload(
            UNASSIGNED_ID,
            draw_pass_count=3,
            inlet_diameter_mm=8.00,
            outlet_diameter_mm=6.80,
            lubricant_coating="PHOSPHATE",
            coating_weight_gsm=4.5,
            gross_mass_kg=500.0,
        ),
        engineer_headers,
    )
    validate_error(response, ApiErrorId.ERR_STEEL_HEAT_NOT_FOUND.value, 404)

    # Nothing was persisted: the register is still empty.
    rows, meta = validate_paginated(
        api.list_wire_lots(engineer_headers, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"Expected no wire lot to have been created, total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty wire-lot listing, got {rows}"


def test_production_lot_opening_rejects_an_unknown_heading_tool(api, engineer_headers):
    """With a good part spec and wire lot but an unknown die set, the third reference is the one that fails.

    PRD: "Foreign keys supplied inside a request body are resolved after all path identifiers, and among themselves in the order in which the fields appear in the endpoint's declared input list."

    PRD: "A `ProcessEngineer` opens a production lot with a unique `lot_code`, the `part_spec_id` being produced, the `wire_lot_id` to be consumed, the `heading_tool_id` to be used, the `press_code` the lot will run on, an inclusive `press_window_start_at` and an exclusive `press_window_end_at` bounding the die set's occupation, the `planned_pieces` of good output (at least 1), and the `expected_wire_lot_version` described in §2.7."

    PRD: "**Body foreign-key existence**, in input-field order, yielding `ERR_PART_SPEC_NOT_FOUND`, `ERR_STEEL_HEAT_NOT_FOUND`, `ERR_WIRE_LOT_NOT_FOUND`, `ERR_HEADING_TOOL_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_LOT_TEST_NOT_FOUND` or `ERR_CERT_DOCUMENT_NOT_FOUND`."

    Design: Corner/entities/production_lot_rejects_an_unknown_heading_tool_cross_reference
    """
    env = fixtures.setup_master_data(
        clock=CLOCK,
        unplated=True,
        spec_overrides={"part_number": "NP-M8-088", "blank_mass_g": 20.0},
        wire_overrides={"gross_mass_kg": 500.0},
    )
    wire_version_before = env["wire"]["version"]

    response = api.create_production_lot(
        create_production_lot_payload(
            env["spec"]["id"],
            env["wire"]["id"],
            UNASSIGNED_ID,
            wire_version_before,
            lot_code="L-2601",
            press_code=env["press_code"],
            press_window_start_at="2026-09-01T06:00:00Z",
            press_window_end_at="2026-09-01T10:00:00Z",
            planned_pieces=5000,
        ),
        engineer_headers,
    )
    validate_error(response, ApiErrorId.ERR_HEADING_TOOL_NOT_FOUND.value, 404)

    lots, lots_meta = validate_paginated(
        api.list_production_lots(engineer_headers, {"part_spec_id": env["spec"]["id"]})
    )
    assert lots_meta["total_count"] == 0, (
        f"Expected no lot to have been opened, total_count {lots_meta['total_count']}"
    )
    assert lots == [], f"Expected an empty production-lot listing, got {lots}"

    # No reservation was made against the coil, and its version did not move.
    wire = fixtures.read_wire_lot(env["wire"]["id"])
    assert_wire_lot(wire)
    assert wire["available_mass_kg"] == pytest.approx(500.000, abs=0.001), (
        f"Expected the full 500.000 kg still free, got {wire['available_mass_kg']}"
    )
    assert wire["reserved_mass_kg"] == pytest.approx(0.000, abs=0.001), (
        f"Expected nothing reserved, got {wire['reserved_mass_kg']}"
    )
    assert wire["version"] == wire_version_before, (
        f"Expected the wire lot's version to stay at {wire_version_before}, "
        f"got {wire['version']}"
    )


# ---------------------------------------------------------------------------
# The pinned specification version
# ---------------------------------------------------------------------------
def test_lot_keeps_its_pinned_spec_version_after_the_spec_is_revised(
    api, engineer_headers
):
    """Revising the part specification bumps its own version but never re-pins the open lot.

    PRD: "Specifications may be revised later by a `ProcessEngineer` or a `PlantAdmin`, and a revision may touch `min_core_hardness_hv`, `max_core_hardness_hv`, `max_decarb_depth_mm`, `nominal_pack_count`, `count_tolerance_pct`, `plating_spec` and `proof_load_kn`, each optional."

    PRD: "A revision increments the specification's `version` by 1, and when `plating_spec` changes it re-derives both `he_bake_required` and `he_bake_min_minutes` from the new finish and the unchanged strength class."

    PRD: "Crucially, a revision never re-pins anything: production lots keep the `pinned_part_spec_version` they captured when they were opened, and certificates keep theirs."

    PRD: "And `traceability_heat_id` copies the wire lot's `steel_heat_id`, denormalising the provenance edge so the lot's origin survives even as the wire lot's own record moves on."

    Design: Corner/entities/lot_keeps_its_pinned_part_spec_version_after_a_revision
    """
    env = fixtures.setup_lot_in_setup(
        planned_pieces=5000,
        clock=CLOCK,
        unplated=True,
        spec_overrides={
            "part_number": "NP-M8-088",
            "blank_mass_g": 20.0,
            "max_decarb_depth_mm": 0.100,
        },
        wire_overrides={"gross_mass_kg": 500.0},
        tool_overrides={"tool_code": "DIE-4S-001", "rated_life_pieces": 120000},
    )
    spec_id = env["spec"]["id"]
    lot = env["lot"]

    assert env["spec"]["version"] == 1, (
        f"Expected the freshly registered spec at version 1, "
        f"got {env['spec']['version']}"
    )
    assert lot["pinned_part_spec_version"] == 1, (
        f"Expected the lot to pin spec version 1 at opening, "
        f"got {lot['pinned_part_spec_version']}"
    )
    # 5000 x 20.0 g x 1.05 / 1000 = 105.000 kg reserved at opening.
    assert lot["wire_reserved_kg"] == pytest.approx(105.000, abs=0.001), (
        f"Expected 105.000 kg reserved, got {lot['wire_reserved_kg']}"
    )

    revised = validate_success(
        api.revise_part_spec(spec_id, {"max_decarb_depth_mm": 0.200}, engineer_headers),
        200,
    )
    assert revised["version"] == 2, (
        f"Expected the revision to take the spec to version 2, got {revised['version']}"
    )
    assert revised["max_decarb_depth_mm"] == pytest.approx(0.200, abs=0.001), (
        f"Expected the revised ceiling 0.200, got {revised['max_decarb_depth_mm']}"
    )

    spec_after = validate_success(api.get_part_spec(spec_id, engineer_headers), 200)
    assert spec_after["version"] == 2, (
        f"Expected the stored spec at version 2, got {spec_after['version']}"
    )
    assert spec_after["max_decarb_depth_mm"] == pytest.approx(0.200, abs=0.001), (
        f"Expected the stored ceiling 0.200, got {spec_after['max_decarb_depth_mm']}"
    )

    lot_after = validate_success(
        api.get_production_lot(lot["id"], engineer_headers), 200
    )
    assert_production_lot(lot_after)
    assert lot_after["pinned_part_spec_version"] == 1, (
        f"Expected the lot to keep pinned_part_spec_version 1 after the revision, "
        f"got {lot_after['pinned_part_spec_version']}"
    )
    assert lot_after["version"] == lot["version"], (
        f"Expected the revision to leave the lot row untouched at version "
        f"{lot['version']}, got {lot_after['version']}"
    )
    assert lot_after["traceability_heat_id"] == env["heat"]["id"], (
        f"Expected traceability_heat_id {env['heat']['id']}, "
        f"got {lot_after['traceability_heat_id']}"
    )
    assert lot_after["part_spec_id"] == spec_id, (
        f"Expected the lot to still name spec {spec_id}, "
        f"got {lot_after['part_spec_id']}"
    )
    assert lot_after["wire_reserved_kg"] == pytest.approx(105.000, abs=0.001), (
        f"Expected the 105.000 kg reservation intact, "
        f"got {lot_after['wire_reserved_kg']}"
    )
