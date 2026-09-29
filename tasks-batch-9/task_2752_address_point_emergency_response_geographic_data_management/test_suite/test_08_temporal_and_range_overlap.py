"""Difficulty rule 8 — resource_temporal_overlap.

Two resources with deliberately different interval conventions:

  * RoadCenterline house-number ranges are CLOSED integer intervals filtered by
    parity, so EVEN [100,198] and EVEN [198,298] share the single member 198 and
    must conflict, while EVEN [100,198] and EVEN [200,298] are merely adjacent.
  * BoundaryCellAssignment service windows are HALF-OPEN datetimes, so windows
    that touch exactly do not intersect, while a window starting one day earlier
    does.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    assert_boundary,
    assert_cell_assignment,
    assert_coverage_pair_conservation,
    assert_coverage_status_shape,
    assert_road_centerline,
    make_agency_liaison_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ===========================================================================
# Instance 1 — road_range_closed_interval_shared_endpoint_overlap_rejected
# ===========================================================================
def _two_same_named_roads(api):
    """R1 VALIDATED left [100,198] EVEN; R2 DRAFT left [198,298] EVEN under the
    same normalized name, with right intervals far enough apart that only the
    shared left endpoint 198 can possibly conflict."""
    world = fx.setup_base_geography(api)
    r1 = fx.setup_road(api, world["j_id"])
    r1 = fx.validate_road(api, r1["id"])
    r2 = validate_success(
        api.create_road_centerline(
            f.road_centerline_payload(
                world["j_id"],
                primary_name="N Maple St",
                from_addr_left=198,
                to_addr_left=298,
                parity_left="EVEN",
                from_addr_right=301,
                to_addr_right=399,
                parity_right="ODD",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    return {"world": world, "r1": r1, "r2": r2}


def test_validating_a_centerline_sharing_one_endpoint_with_a_validated_peer_is_refused(api):
    """Both CLOSED EVEN intervals contain 198, which is the smallest genuinely conflicting configuration.

    Because a conflicting pair always carries the same parity, two intervals that are separated by a gap of one — an `EVEN` interval ending at 198 and an `EVEN` interval starting at 199 — cannot share any house number and therefore do not conflict; the smallest genuinely conflicting configuration shares exactly one endpoint value, as when an `EVEN` interval running 100 through 198 meets an `EVEN` interval running 198 through 298 and 198 belongs to both.

    Design: Difficulty/resource_temporal_overlap/road_range_closed_interval_shared_endpoint_overlap_rejected
    """
    fx.reset_clock_to_startup(api)
    built = _two_same_named_roads(api)
    r2 = built["r2"]
    assert_road_centerline(r2, status="DRAFT", normalized_name="N MAPLE STREET")
    assert built["r1"]["normalized_name"] == "N MAPLE STREET", "the names really do collide"

    resp = api.validate_road_centerline(r2["id"], {}, ANALYST_HEADERS)
    validate_error(resp, ApiErrorId.ROAD_RANGE_OVERLAP, 409)

    after = fx.read_road(api, r2["id"])
    assert_road_centerline(after, status="DRAFT", qc_dirty=True)
    assert fx.read_road(api, built["r1"]["id"])["status"] == "VALIDATED"


def test_shifting_the_left_range_to_pure_adjacency_lets_the_centerline_validate(api):
    """Moving the low bound from 198 to 200 removes the only shared member, and the identical validate then succeeds under the very same colliding name.

    Adjacency with no shared value, such as `EVEN` 100 through 198 against `EVEN` 200 through 298, is explicitly permitted.

    Design: Difficulty/resource_temporal_overlap/road_range_closed_interval_shared_endpoint_overlap_rejected
    """
    fx.reset_clock_to_startup(api)
    built = _two_same_named_roads(api)
    r2 = built["r2"]

    refused = api.validate_road_centerline(r2["id"], {}, ANALYST_HEADERS)
    validate_error(refused, ApiErrorId.ROAD_RANGE_OVERLAP, 409)

    # The refused validate mutated nothing, so the creation version still edits.
    patch = api.patch_road_centerline(
        r2["id"],
        f.road_patch_payload(r2["version"], from_addr_left=200, to_addr_left=298),
        ANALYST_HEADERS,
    )
    edited = validate_success(patch, 200)
    assert_road_centerline(edited, status="DRAFT", from_addr_left=200, to_addr_left=298)

    second = api.validate_road_centerline(r2["id"], {}, ANALYST_HEADERS)
    validated = validate_success(second, 200)
    assert_road_centerline(
        validated,
        status="VALIDATED",
        qc_dirty=False,
        normalized_name="N MAPLE STREET",
    )
    # Capacity floor((298 - 200) / 2) + 1 with no address points consuming a slot.
    assert validated["assignable_slot_count_left"] == 50
    assert fx.read_road(api, built["r1"]["id"])["status"] == "VALIDATED"


# ===========================================================================
# Instance 2 — boundary_cell_half_open_window_adjacency_allowed_overlap_rejected
# ===========================================================================
def _three_law_windows_on_one_cell(api):
    """One ACTIVE LAW agency owning three boundaries on the same cell:
    B1 [2026-08-01, 2026-08-11) already ACTIVE, B2 [2026-08-11, open) PROPOSED
    (it merely touches B1), and B3 [2026-08-10, open) PROPOSED (it intersects)."""
    world = fx.setup_base_geography(api)
    law = fx.setup_agency(api, world["j_id"], "LAW")
    b1 = fx.setup_active_boundary_on_cell(
        api,
        law["id"],
        world["cell_id"],
        boundary_overrides={"effective_end": "2026-08-11T00:00:00Z"},
        claim_overrides={"effective_end": "2026-08-11T00:00:00Z"},
    )
    b2 = fx.setup_proposed_boundary_on_cell(
        api,
        law["id"],
        world["cell_id"],
        boundary_overrides={"effective_start": "2026-08-11T00:00:00Z"},
        claim_overrides={"effective_start": "2026-08-11T00:00:00Z"},
    )
    b3 = fx.setup_proposed_boundary_on_cell(
        api,
        law["id"],
        world["cell_id"],
        boundary_overrides={"effective_start": "2026-08-10T00:00:00Z"},
        claim_overrides={"effective_start": "2026-08-10T00:00:00Z"},
    )
    return {"world": world, "law": law, "b1": b1, "b2": b2, "b3": b3}


def test_a_successor_window_that_only_touches_the_incumbent_activates(api):
    """The incumbent claim ends at 2026-08-11T00:00:00.000Z and the successor starts there, so the two half-open windows do not intersect and both may be ACTIVE on the same cell and service type.

    Windows that merely touch, where the predecessor's `effective_end` exactly equals the successor's `effective_start`, do not intersect and are permitted — that is how an agency hands a cell over to its successor cleanly.

    Design: Difficulty/resource_temporal_overlap/boundary_cell_half_open_window_adjacency_allowed_overlap_rejected
    """
    fx.reset_clock_to_startup(api)
    built = _three_law_windows_on_one_cell(api)
    law_headers = make_agency_liaison_headers(built["law"]["id"])

    resp = api.activate_boundary(built["b2"]["boundary_id"], {}, law_headers)
    activated = validate_success(resp, 200)
    assert_boundary(
        activated,
        status="ACTIVE",
        service_type="LAW",
        effective_start="2026-08-11T00:00:00.000Z",
    )
    assert activated["effective_end"] is None, "the successor window never closes"

    assignment = fx.read_cell_assignment(api, built["b2"]["assignment_id"])
    assert_cell_assignment(
        assignment,
        status="ACTIVE",
        service_type="LAW",
        effective_start="2026-08-11T00:00:00.000Z",
    )
    assert fx.read_cell_assignment(api, built["b1"]["assignment_id"])["status"] == "ACTIVE"


def test_a_window_starting_one_day_before_the_incumbent_ends_is_refused_as_coverage_overlap(api):
    """The window [2026-08-10, open) intersects both the incumbent [2026-08-01, 2026-08-11) and its touching successor [2026-08-11, open), so activation is refused and nothing on the boundary moves.

    And for every cell assignment on this boundary, no *other* `ACTIVE` cell assignment on the same pairing of `cell_id` and `service_type` may have a half-open window that intersects this one; a collision is refused with `ERR_COVERAGE_OVERLAP` (HTTP 409).

    Design: Difficulty/resource_temporal_overlap/boundary_cell_half_open_window_adjacency_allowed_overlap_rejected
    """
    fx.reset_clock_to_startup(api)
    built = _three_law_windows_on_one_cell(api)
    law_headers = make_agency_liaison_headers(built["law"]["id"])

    validate_success(api.activate_boundary(built["b2"]["boundary_id"], {}, law_headers), 200)

    resp = api.activate_boundary(built["b3"]["boundary_id"], {}, law_headers)
    validate_error(resp, ApiErrorId.COVERAGE_OVERLAP, 409)

    assert_boundary(fx.read_boundary(api, built["b3"]["boundary_id"]), status="PROPOSED")
    assert fx.read_cell_assignment(api, built["b3"]["assignment_id"])["status"] == "PENDING"


def test_the_touching_pair_leaves_no_forward_hole_while_only_the_incumbent_answers_now(api):
    """Only the incumbent window contains the current instant, so exactly one assignment responds now, while the merged LAW union still covers the whole thirty-day horizon.

    For each cell-and-service-type pair, the `ACTIVE` assignments' half-open windows are clipped to that thirty-day horizon and merged, and the pair counts as a **forward gap** when the merged union does not cover the whole horizon.

    Design: Difficulty/resource_temporal_overlap/boundary_cell_half_open_window_adjacency_allowed_overlap_rejected
    """
    fx.reset_clock_to_startup(api)
    built = _three_law_windows_on_one_cell(api)
    law_headers = make_agency_liaison_headers(built["law"]["id"])

    validate_success(api.activate_boundary(built["b2"]["boundary_id"], {}, law_headers), 200)
    validate_error(
        api.activate_boundary(built["b3"]["boundary_id"], {}, law_headers),
        ApiErrorId.COVERAGE_OVERLAP,
        409,
    )

    cell = fx.read_cell(api, built["world"]["cell_id"])
    assert cell["active_assignment_count"] == 1, "only the incumbent covers 2026-08-01"

    jurisdiction = fx.read_jurisdiction(api, built["world"]["j_id"])
    assert jurisdiction["gap_pair_count"] == 2, "FIRE and EMS; LAW is covered now"
    assert jurisdiction["forward_gap_pair_count"] == 2, "the touching windows leave no hole"
    assert jurisdiction["covered_cell_count"] == 0

    status = fx.read_coverage_status(api, built["world"]["cell_id"])
    assert_coverage_status_shape(status)
    assert_coverage_pair_conservation(status)
    assert status["covered_service_types"] == ["LAW"]
    assert status["gap_service_types"] == ["FIRE", "EMS"]
    assert status["forward_gap_service_types"] == ["FIRE", "EMS"]
    assert status["responding_assignment_count"] == 1
