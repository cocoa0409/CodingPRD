"""Difficulty rule 9 — compensating_invariant.

Three different conserved quantities, each restored exactly by a compensating
action rather than merely moved in the right direction:

  * the road side's assignable_slot_count, restored to 50 by voiding a request
    that minted one base point and two units;
  * the (cell x service_type) coverage pair count, where covered + gap pairs is
    always cell_count * 3 before and after a boundary retirement;
  * the single-PUBLISHED-package-per-(channel, jurisdiction) rule, preserved by
    a rollback that restores its predecessor in the same request.
"""

from test_helpers import (
    ANALYST_HEADERS,
    PERMIT_HEADERS,
    PROV_HEADERS,
    assert_address_point,
    assert_boundary,
    assert_coverage_pair_conservation,
    assert_coverage_status_shape,
    assert_package,
    assert_service_type_order,
    assert_slot_counters,
    make_agency_liaison_headers,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ===========================================================================
# Instance 1 — assignment_void_restores_assignable_slot_count
# ===========================================================================
def _fulfilled_request_minting_a_base_point_and_two_units(api):
    """A VALIDATED road whose left capacity is 50, and one FULFILLED request for
    permit BP-2026-0002 that minted the base point at 100 plus two units."""
    world = fx.setup_validated_road_world(api)
    before = fx.read_road(api, world["road_id"])
    assert_slot_counters(before, 50, 50)

    request = fx.setup_fulfilled_request(
        api,
        world["road_id"],
        permit_number="BP-2026-0002",
        parcel_id="8712300002",
        requested_unit_count=2,
    )
    assert request["fulfillment_status"] == "FULFILLED"
    assert request["minted_point_count"] == 3
    assert request["assigned_house_number"] == 100
    return {"world": world, "request": request}


def test_voiding_a_fulfilled_request_restores_the_assignable_slot_count_exactly(api):
    """The left count reads 50 before the assignment, 49 while the base point lives, and exactly 50 again after the void — not 48, because the two units never consumed a slot.

    From `FULFILLED` the void reaches into the minted data: every address point the request created — the base point and each of its units, processed with the base point first and then the units in ascending `unit_id` order — transitions to `VOIDED` with `retire_reason` set to `REQUEST_VOIDED`, the centerline's slot counters are refreshed so that the assignable count for that side is restored to exactly its pre-assignment value, and pin staleness is evaluated for each voided point.

    Design: Difficulty/compensating_invariant/assignment_void_restores_assignable_slot_count
    """
    fx.reset_clock_to_startup(api)
    built = _fulfilled_request_minting_a_base_point_and_two_units(api)
    world = built["world"]

    while_live = fx.read_road(api, world["road_id"])
    assert_slot_counters(while_live, 49, 50)

    resp = api.void_assignment_request(
        built["request"]["id"], f.void_request_payload(), PERMIT_HEADERS
    )
    voided = validate_success(resp, 200)
    assert voided["fulfillment_status"] == "VOIDED"

    after = fx.read_road(api, world["road_id"])
    assert_slot_counters(after, 50, 50)


def test_the_voided_request_keeps_its_minted_point_count_and_every_point_is_retained(api):
    """minted_point_count stays 3 because it is a historical fact rather than a live count, and all three points remain queryable as VOIDED rows carrying REQUEST_VOIDED.

    The request records `assigned_address_point_id` as the base point's identifier and `minted_point_count` as one plus `requested_unit_count` — a count that stands regardless of what happens to those points later.

    Design: Difficulty/compensating_invariant/assignment_void_restores_assignable_slot_count
    """
    fx.reset_clock_to_startup(api)
    built = _fulfilled_request_minting_a_base_point_and_two_units(api)
    world = built["world"]
    base_point_id = built["request"]["assigned_address_point_id"]

    voided = validate_success(
        api.void_assignment_request(
            built["request"]["id"], f.void_request_payload(), PERMIT_HEADERS
        ),
        200,
    )
    assert voided["fulfillment_status"] == "VOIDED"
    assert voided["void_reason"] == (
        "Permit withdrawn by the applicant before foundation inspection"
    )
    assert voided["minted_point_count"] == 3, "historical, never decremented"
    assert voided["assigned_house_number"] == 100

    base = fx.read_point(api, base_point_id)
    assert_address_point(base, status="VOIDED", retire_reason="REQUEST_VOIDED")
    assert base["retired_at"] == "2026-08-01T00:00:00.000Z"

    rows, meta = validate_paginated(
        api.list_address_points(
            {
                "road_centerline_id": world["road_id"],
                "include_retired": "true",
                "limit": 100,
            },
            ANALYST_HEADERS,
        )
    )
    assert meta["total_count"] == 3, "all three minted points are retained"
    assert len(rows) == 3
    for row in rows:
        assert_address_point(row, status="VOIDED", retire_reason="REQUEST_VOIDED")


# ===========================================================================
# Instance 2 — boundary_retire_restores_coverage_pair_conservation
# ===========================================================================
def _one_cell_covered_by_all_three_service_types(api):
    """One cell, three ACTIVE agencies, three ACTIVE open-ended boundaries, so the
    conserved total is cell_count * 3 == 3 pairs and none of them is a gap."""
    world = fx.setup_base_geography(api)
    coverage = fx.setup_full_coverage(api, world["j_id"], world["cell_id"])

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["cell_count"] == 1
    assert jurisdiction["gap_pair_count"] == 0
    assert jurisdiction["forward_gap_pair_count"] == 0
    assert jurisdiction["covered_cell_count"] == 1
    assert fx.read_cell(api, world["cell_id"])["active_assignment_count"] == 3
    return {"world": world, "coverage": coverage}


def test_retiring_one_boundary_moves_exactly_one_pair_from_covered_to_gap(api):
    """Before the retire the cell holds three covered pairs and no gaps; afterwards exactly one pair has moved, so gap_pair_count plus covered pairs is still cell_count times three.

    Retiring from `ACTIVE` transitions every cell assignment on the boundary from `ACTIVE` to `RETIRED`, each incrementing its own `version` by 1 and refreshing its cell's `active_assignment_count`, refreshes the jurisdiction's coverage counters so that `covered_cell_count` and `gap_pair_count` return to exactly their pre-activation values, and evaluates pin staleness for the boundary — which, because `RETIRED` is terminal, is destructive drift and invalidates any sealed package that had pinned it.

    Design: Difficulty/compensating_invariant/boundary_retire_restores_coverage_pair_conservation
    """
    fx.reset_clock_to_startup(api)
    built = _one_cell_covered_by_all_three_service_types(api)
    world = built["world"]
    coverage = built["coverage"]

    before = fx.read_coverage_status(api, world["cell_id"])
    assert_coverage_status_shape(before)
    assert_coverage_pair_conservation(before)
    assert before["covered_service_types"] == ["LAW", "FIRE", "EMS"]

    fire_agency_id = coverage["agencies"]["FIRE"]["id"]
    fire_boundary = coverage["boundaries"]["FIRE"]
    resp = api.retire_boundary(
        fire_boundary["id"], f.retire_boundary_payload(), make_agency_liaison_headers(fire_agency_id)
    )
    retired = validate_success(resp, 200)
    assert_boundary(retired, status="RETIRED", service_type="FIRE")
    assert retired["retired_at"] == "2026-08-01T00:00:00.000Z"
    assert retired["retire_reason"] == "Fire district dissolved into the regional authority"

    assert (
        fx.read_cell_assignment(api, coverage["assignments"]["FIRE"]["id"])["status"]
        == "RETIRED"
    ), "the child assignment follows its boundary"
    assert fx.read_boundary(api, coverage["boundaries"]["LAW"]["id"])["status"] == "ACTIVE"
    assert fx.read_boundary(api, coverage["boundaries"]["EMS"]["id"])["status"] == "ACTIVE"

    cell = fx.read_cell(api, world["cell_id"])
    assert cell["active_assignment_count"] == 2, "exactly one pair was released"

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["cell_count"] == 1
    assert jurisdiction["gap_pair_count"] == 1, "one gap plus two covered is cell_count * 3"
    assert jurisdiction["forward_gap_pair_count"] == 1
    assert jurisdiction["covered_cell_count"] == 0, "a cell needs all THREE service types"

    after = fx.read_coverage_status(api, world["cell_id"])
    assert_coverage_pair_conservation(after)


def test_the_released_pair_is_reported_in_service_type_order_rather_than_alphabetically(api):
    """With FIRE retired the covered array reads LAW then EMS, which is the SERVICE_TYPES sequence filtered in order and not an alphabetical or insertion ordering.

    The three service types form an **ordered** constant, `LAW` then `FIRE` then `EMS`, and every one of those four arrays is produced by filtering that sequence in that order.

    Design: Difficulty/compensating_invariant/boundary_retire_restores_coverage_pair_conservation
    """
    fx.reset_clock_to_startup(api)
    built = _one_cell_covered_by_all_three_service_types(api)
    world = built["world"]
    coverage = built["coverage"]

    fx.retire_boundary(
        api, coverage["boundaries"]["FIRE"]["id"], coverage["agencies"]["FIRE"]["id"]
    )

    status = fx.read_coverage_status(api, world["cell_id"])
    assert_coverage_status_shape(status)
    assert status["covered_service_types"] == ["LAW", "EMS"]
    assert status["gap_service_types"] == ["FIRE"]
    assert status["forward_gap_service_types"] == ["FIRE"]
    assert status["responding_assignment_count"] == 2
    assert_service_type_order(status["covered_service_types"], "covered_service_types")
    assert_service_type_order(status["gap_service_types"], "gap_service_types")
    assert_coverage_pair_conservation(status)

# ===========================================================================
# Instance 3 — package_rollback_preserves_single_published_package
# ===========================================================================
def _two_mapping_releases_on_one_jurisdiction(api):
    """MAPPING v1 published at 2026-08-01, then v2 published exactly fourteen days
    later, which supersedes v1 so the channel again holds one PUBLISHED package."""
    world = fx.setup_published_package(api, "MAPPING")
    pkg1 = world["package"]
    assert_package(
        pkg1,
        status="PUBLISHED",
        channel="MAPPING",
        package_version=1,
        pinned_record_count=2,
        stale_pin_count=0,
        drift_detected=False,
        published_by_user_id="prov-1",
    )
    assert pkg1["published_at"] == "2026-08-01T00:00:00.000Z"

    # Fourteen days is the MAPPING cadence interval and the comparison is inclusive.
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    draft2 = fx.setup_package(api, world["j_id"], world["report_id"], "MAPPING")
    sealed2 = fx.seal_package(api, draft2["id"])
    assert_package(sealed2, status="SEALED", package_version=2, stale_pin_count=0)
    pkg2 = fx.publish_package(api, draft2["id"])
    assert_package(pkg2, status="PUBLISHED", package_version=2)
    assert pkg2["published_at"] == "2026-08-15T00:00:00.000Z"
    assert fx.read_package(api, pkg1["id"])["status"] == "SUPERSEDED"

    return {
        "world": world,
        "pkg1_id": pkg1["id"],
        "pkg2_id": pkg2["id"],
    }


def test_rolling_back_the_incumbent_restores_its_superseded_predecessor_untouched(api):
    """One request retracts v2 and promotes v1 back, and v1 keeps the 2026-08-01 publication instant it originally earned rather than being restamped at 2026-08-15.

    Rollback records `rollback_reason`, moves the package `PUBLISHED → ROLLED_BACK`, increments its `version` by 1, and restores the predecessor: the `SUPERSEDED` package on the same pairing with the highest `package_version`, ties broken by `created_at` ascending, transitions `SUPERSEDED → PUBLISHED` and increments its own `version` by 1.

    Design: Difficulty/compensating_invariant/package_rollback_preserves_single_published_package
    """
    fx.reset_clock_to_startup(api)
    built = _two_mapping_releases_on_one_jurisdiction(api)

    resp = api.rollback_package(
        built["pkg2_id"], f.rollback_package_payload(), PROV_HEADERS
    )
    rolled = validate_success(resp, 200)
    assert_package(rolled, status="ROLLED_BACK", channel="MAPPING", package_version=2)
    assert rolled["rollback_reason"] == (
        "Dispatch reported bad geometry on the 100 block after cutover"
    )
    assert rolled["published_at"] == "2026-08-15T00:00:00.000Z", (
        "a rolled-back package keeps the history of having been published"
    )

    restored = fx.read_package(api, built["pkg1_id"])
    assert_package(restored, status="PUBLISHED", channel="MAPPING", package_version=1)
    assert restored["published_at"] == "2026-08-01T00:00:00.000Z", (
        "the cadence baseline is the original instant, not the restoration"
    )
    assert restored["rollback_reason"] is None


def test_the_channel_holds_exactly_one_published_package_before_and_after_the_rollback(api):
    """The PUBLISHED listing for the pairing has length one on both sides of the rollback; only which package answers changes, from v2 to v1.

    Exactly one package is published per channel and jurisdiction at any moment.

    Design: Difficulty/compensating_invariant/package_rollback_preserves_single_published_package
    """
    fx.reset_clock_to_startup(api)
    built = _two_mapping_releases_on_one_jurisdiction(api)
    jurisdiction_id = built["world"]["j_id"]
    published_query = {
        "channel": "MAPPING",
        "jurisdiction_id": jurisdiction_id,
        "status": "PUBLISHED",
        "limit": 100,
    }

    rows, meta = validate_paginated(api.list_packages(published_query, PROV_HEADERS))
    assert meta["total_count"] == 1, "v2 superseded v1 on publication"
    assert rows[0]["id"] == built["pkg2_id"]

    validate_success(
        api.rollback_package(
            built["pkg2_id"], f.rollback_package_payload(), PROV_HEADERS
        ),
        200,
    )

    rows, meta = validate_paginated(api.list_packages(published_query, PROV_HEADERS))
    assert meta["total_count"] == 1, "the invariant survives the rollback"
    assert len(rows) == 1
    assert rows[0]["id"] == built["pkg1_id"], "the predecessor answers for the channel"
    assert_package(rows[0], status="PUBLISHED", package_version=1)

    superseded_rows, superseded_meta = validate_paginated(
        api.list_packages(
            {
                "channel": "MAPPING",
                "jurisdiction_id": jurisdiction_id,
                "status": "SUPERSEDED",
                "limit": 100,
            },
            PROV_HEADERS,
        )
    )
    assert superseded_meta["total_count"] == 0, "v1 left SUPERSEDED when it was restored"
    assert superseded_rows == []
