"""Endpoint-surface corners of the County Address and Emergency Response GIS API.

These tests pin the observable behaviour of individual endpoints where the
endpoint itself — rather than a formula or a state machine — carries the rule:
the fixed emission order of the coverage-status arrays, the direction of the
cell-assignment link, the forecasting read that predicts an activation refusal,
the partial-merge semantics of the centerline PATCH, and the deliberately
side-effect-free logical clock.
"""

from test_helpers import (
    ANALYST_HEADERS,
    PROV_HEADERS,
    SYSADMIN_HEADERS,
    ApiErrorId,
    assert_address_point,
    assert_agency,
    assert_boundary,
    assert_cell_assignment,
    assert_coverage_cell,
    assert_coverage_pair_conservation,
    assert_coverage_status_shape,
    assert_jurisdiction,
    assert_road_centerline,
    assert_score_equals,
    assert_service_type_order,
    assert_slot_counters,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ===========================================================================
# coverage_status_read_emits_service_types_in_the_constant_order
# ===========================================================================
def test_coverage_status_read_emits_service_types_in_the_constant_order(api):
    """EMS coverage is activated first and LAW second, yet the read answers
    ["LAW", "EMS"] — the constant order, not the insertion order.

    The three service types form an **ordered** constant, `LAW` then `FIRE` then `EMS`, and every one of those four arrays is produced by filtering that sequence in that order.
    Alphabetical ordering and insertion ordering are both wrong.

    Design: Corner/endpoints/coverage_status_read_emits_service_types_in_the_constant_order
    """
    base = fx.setup_base_geography(api)
    cell_id = base["cell_id"]

    ems_agency = fx.setup_agency(api, base["j_id"], "EMS", name="Thompson Valley EMS")
    law_agency = fx.setup_agency(api, base["j_id"], "LAW", name="Larimer County Sheriff")
    fire_agency = fx.setup_agency(api, base["j_id"], "FIRE", name="Poudre Fire Authority")

    # EMS is activated FIRST and LAW second; FIRE never gets a boundary at all.
    ems_built = fx.setup_active_boundary_on_cell(api, ems_agency["id"], cell_id)
    law_built = fx.setup_active_boundary_on_cell(api, law_agency["id"], cell_id)

    status = validate_success(api.get_coverage_status(cell_id, PROV_HEADERS), 200)
    assert_coverage_status_shape(status)
    assert status["cell_id"] == cell_id, "the read is anchored to the requested cell"
    assert status["evaluated_at"] == "2026-08-01T00:00:00.000Z", (
        "evaluated_at is the logical clock instant, not wall-clock time"
    )

    assert status["covered_service_types"] == ["LAW", "EMS"], (
        "LAW precedes EMS even though the EMS claim was activated first"
    )
    assert status["gap_service_types"] == ["FIRE"]
    assert status["forward_gap_service_types"] == ["FIRE"], (
        "both claims are open-ended, so the forward window agrees with the instant"
    )
    assert status["proposed_conflict_service_types"] == []
    assert status["responding_assignment_count"] == 2
    assert_service_type_order(status["covered_service_types"], "covered_service_types")
    assert_coverage_pair_conservation(status)

    cell = fx.read_cell(api, cell_id)
    assert_coverage_cell(cell, active_assignment_count=2)

    assert_cell_assignment(
        fx.read_cell_assignment(api, ems_built["assignment_id"]),
        status="ACTIVE",
        service_type="EMS",
    )
    assert_cell_assignment(
        fx.read_cell_assignment(api, law_built["assignment_id"]),
        status="ACTIVE",
        service_type="LAW",
    )

    jurisdiction = fx.read_jurisdiction(api, base["j_id"])
    assert_jurisdiction(jurisdiction, gap_pair_count=1, covered_cell_count=0)

    # The FIRE gap is a missing boundary, not a missing or suspended agency.
    assert_agency(fx.read_agency(api, fire_agency["id"]), status="ACTIVE")


# ===========================================================================
# cell_assignment_links_a_boundary_to_a_cell_in_both_directions
# ===========================================================================
def test_cell_assignment_links_a_boundary_to_a_cell_in_both_directions(api):
    """The new claim takes its boundary from the path and its cell from the body,
    inherits FIRE from the parent, and counts on the boundary but not on the cell.

    The assignment's `boundary_id` is taken from the parent named in the path of the creating call, and its `service_type` is copied from the parent boundary, which matters because the overlap key throughout this system is the pairing of `cell_id` with `service_type`.

    Design: Corner/endpoints/cell_assignment_links_a_boundary_to_a_cell_in_both_directions
    """
    base = fx.setup_base_geography(api)
    cell_id = base["cell_id"]
    agency = fx.setup_agency(
        api, base["j_id"], "FIRE", name="Poudre Fire Authority", contact_phone="970-416-2891"
    )
    headers = make_agency_liaison_headers(agency["id"])

    boundary = fx.setup_boundary(api, agency["id"])
    assert_boundary(boundary, status="DRAFT", service_type="FIRE", version=1)

    created = validate_success(
        api.create_cell_assignment(
            boundary["id"],
            f.cell_assignment_payload(cell_id, boundary["version"]),
            headers,
        ),
        201,
    )
    assert_cell_assignment(
        created,
        boundary_id=boundary["id"],
        cell_id=cell_id,
        service_type="FIRE",
        status="PENDING",
    )
    assert created["effective_end"] is None, "an open-ended claim has no end instant"

    parent = fx.read_boundary(api, boundary["id"])
    assert_boundary(parent, assigned_cell_count=1, status="DRAFT", version=2)

    cell = fx.read_cell(api, cell_id)
    assert_coverage_cell(cell, active_assignment_count=0)

    rows, meta = validate_paginated(
        api.list_boundary_cell_assignments_of(boundary["id"], {"limit": 100}, headers)
    )
    assert meta["total_count"] == 1, "the claim is reachable from its parent boundary"
    assert rows[0]["id"] == created["id"]

    status = validate_success(api.get_coverage_status(cell_id, PROV_HEADERS), 200)
    assert_coverage_status_shape(status)
    assert status["responding_assignment_count"] == 0, "PENDING is not responding coverage"
    assert status["gap_service_types"] == ["LAW", "FIRE", "EMS"]


# ===========================================================================
# proposed_conflict_service_types_forecasts_the_activation_refusal
# ===========================================================================
def test_proposed_conflict_service_types_forecasts_the_activation_refusal(api):
    """The read names FIRE as a proposed conflict before anyone tries to activate,
    and the activation then fails with exactly that collision.

    And for every cell assignment on this boundary, no *other* `ACTIVE` cell assignment on the same pairing of `cell_id` and `service_type` may have a half-open window that intersects this one; a collision is refused with `ERR_COVERAGE_OVERLAP` (HTTP 409).
    Note the asymmetry that this creates and that the QC scan later reports on: two *pending* claims on the same cell and service type with intersecting windows are perfectly legal, because proposed boundaries are allowed to conflict on paper and activation is the gate that resolves the conflict.

    Design: Corner/endpoints/proposed_conflict_service_types_forecasts_the_activation_refusal
    """
    base = fx.setup_base_geography(api)
    cell_id = base["cell_id"]

    incumbent_agency = fx.setup_agency(
        api, base["j_id"], "FIRE", name="Poudre Fire Authority"
    )
    challenger_agency = fx.setup_agency(
        api, base["j_id"], "FIRE", name="Loveland Fire Rescue Authority"
    )

    incumbent = fx.setup_active_boundary_on_cell(api, incumbent_agency["id"], cell_id)
    challenger = fx.setup_proposed_boundary_on_cell(api, challenger_agency["id"], cell_id)

    challenger_headers = make_agency_liaison_headers(challenger_agency["id"])
    status = validate_success(api.get_coverage_status(cell_id, challenger_headers), 200)
    assert_coverage_status_shape(status)
    assert status["proposed_conflict_service_types"] == ["FIRE"], (
        "the pending claim collides with the active one on the same cell and type"
    )
    assert status["covered_service_types"] == ["FIRE"]
    assert status["gap_service_types"] == ["LAW", "EMS"]
    assert status["responding_assignment_count"] == 1, "the PENDING claim is not responding"

    refused = api.activate_boundary(challenger["boundary_id"], {}, challenger_headers)
    validate_error(refused, ApiErrorId.COVERAGE_OVERLAP)

    held = fx.read_boundary(api, challenger["boundary_id"])
    assert_boundary(held, status="PROPOSED", version=3)

    assert_cell_assignment(
        fx.read_cell_assignment(api, challenger["assignment_id"]), status="PENDING"
    )
    assert_cell_assignment(
        fx.read_cell_assignment(api, incumbent["assignment_id"]), status="ACTIVE"
    )
    assert_coverage_cell(fx.read_cell(api, cell_id), active_assignment_count=1)
    assert_jurisdiction(fx.read_jurisdiction(api, base["j_id"]), gap_pair_count=2)


# ===========================================================================
# patch_road_merges_only_supplied_fields_and_demotes
# ===========================================================================
def test_patch_road_merges_only_supplied_fields_and_demotes(api):
    """A PATCH carrying only primary_name renames and demotes the centerline while
    every omitted range field keeps its stored value.

    Editing a centerline is the system's first optimistic-concurrency operation. The payload carries `expected_road_version` and may carry any subset of `primary_name`, `from_addr_left`, `to_addr_left`, `parity_left`, `from_addr_right`, `to_addr_right` and `parity_right`.
    An edit of a `DRAFT` centerline leaves it in `DRAFT` — `DRAFT → DRAFT` is a real transition, not a no-op — while an edit of a `VALIDATED` centerline **demotes** it, `VALIDATED → DRAFT`, because a validated road whose name or ranges have moved must be re-validated before it may be published again.

    Design: Corner/endpoints/patch_road_merges_only_supplied_fields_and_demotes
    """
    world = fx.setup_validated_road_world(api, primary_name="N MAPLE STREET")
    road_id = world["road_id"]
    assert_road_centerline(world["road"], status="VALIDATED", version=2)

    point = fx.setup_address_point(
        api, road_id, world["cell_id"], house_number=100, geometry_verified=True
    )
    # 70 PARCEL + 12 geometry + 8 postal match + 6 base address - 5 VALIDATED.
    assert_score_equals(point["confidence_score"], 91.00)

    patched = validate_success(
        api.patch_road_centerline(
            road_id,
            f.road_patch_payload(2, primary_name="S. Elm Dr"),
            ANALYST_HEADERS,
        ),
        200,
    )
    assert_road_centerline(
        patched,
        primary_name="S. Elm Dr",
        normalized_name="S ELM DRIVE",
        status="DRAFT",
        qc_dirty=True,
        version=3,
        from_addr_left=100,
        to_addr_left=198,
        parity_left="EVEN",
        from_addr_right=101,
        to_addr_right=199,
        parity_right="ODD",
    )
    assert_slot_counters(patched, 49, 50)

    refreshed = fx.read_point(api, point["id"])
    assert_address_point(refreshed, version=2, status="PENDING")
    # The road-status penalty moved from 5 up to 15 as the road fell back to DRAFT.
    assert_score_equals(refreshed["confidence_score"], 81.00)

    _, meta = validate_paginated(
        api.list_road_centerlines(
            {"normalized_name": "N MAPLE STREET", "limit": 100}, ANALYST_HEADERS
        )
    )
    assert meta["total_count"] == 0, "the old normalized key no longer resolves"


# ===========================================================================
# clock_endpoint_moves_time_without_mutating_any_entity
# ===========================================================================
def test_clock_endpoint_moves_time_without_mutating_any_entity(api):
    """Jumping the clock ten weeks forward leaves the existing centerline and the
    jurisdiction counters untouched, yet the next record is stamped at the new instant.

    Setting the clock mutates no stored entity and recomputes no counter by itself; only subsequent operations observe the new instant.
    An administrative test-driving capability sets the clock to a supplied instant, taking a single field `to_iso8601` and answering with the new value under the key `current_utc`.

    Design: Corner/endpoints/clock_endpoint_moves_time_without_mutating_any_entity
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_draft_road_world(api, primary_name="N MAPLE STREET")
    road_id = world["road_id"]

    before = fx.read_road(api, road_id)
    assert_road_centerline(
        before,
        version=1,
        status="DRAFT",
        qc_dirty=True,
        created_at="2026-08-01T00:00:00.000Z",
        updated_at="2026-08-01T00:00:00.000Z",
    )

    moved = validate_success(
        api.set_clock("2026-10-15T12:30:45Z", SYSADMIN_HEADERS), 200
    )
    assert moved["current_utc"] == "2026-10-15T12:30:45.000Z", (
        "the answer carries the new instant under current_utc"
    )

    after = fx.read_road(api, road_id)
    assert after == before, "the clock call mutated no field of the stored centerline"

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert_jurisdiction(jurisdiction, cell_count=1, gap_pair_count=3)

    point = fx.setup_address_point(
        api, road_id, world["cell_id"], house_number=100, geometry_verified=True
    )
    assert_address_point(
        point, created_at="2026-10-15T12:30:45.000Z", status="PENDING"
    )
    # 70 PARCEL + 12 geometry + 8 postal match + 6 base address - 15 DRAFT.
    assert_score_equals(point["confidence_score"], 81.00)

    status = validate_success(
        api.get_coverage_status(world["cell_id"], PROV_HEADERS), 200
    )
    assert status["evaluated_at"] == "2026-10-15T12:30:45.000Z", (
        "every later read evaluates against the moved clock"
    )
