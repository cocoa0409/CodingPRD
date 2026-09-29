"""Transitive cascades: one call that propagates five levels deep.

Two triggering transitions are probed. A `RoadCenterline` retirement walks road
-> base point -> subaddress unit -> package pins -> sealed package. A
`DiscrepancyCase` adoption walks case -> road (demoted and re-normalized) ->
address point re-scoring -> report decertification -> package invalidation.
"""

from test_helpers import (
    ANALYST_HEADERS,
    assert_address_point,
    assert_package,
    assert_road_centerline,
    assert_score_equals,
    validate_success,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Shared inline builders (the helpers in test_helpers do not compose a world
# holding a base point AND its subaddress unit under one sealed package).
# ---------------------------------------------------------------------------
def _world_with_base_point_and_unit(api):
    """Jurisdiction LARCO + cell C001 + PUBLISHED road + ACTIVE base point at
    100 LEFT + ACTIVE subaddress unit '1' beneath it."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])
    world["road_id"] = road["id"]
    base = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], geometry_verified=True
    )
    world["base_id"] = base["id"]
    fx.validate_road(api, world["road_id"])
    world["road"] = fx.publish_road(api, world["road_id"])
    fx.activate_point(api, world["base_id"])
    unit = fx.setup_unit_point(
        api,
        world["road_id"],
        world["cell_id"],
        world["base_id"],
        unit_id="1",
        geometry_verified=True,
    )
    world["unit_id_pk"] = unit["id"]
    fx.activate_point(api, world["unit_id_pk"])
    return world


def _world_with_sealed_mapping_package(api):
    """The world above, plus a CERTIFIED ROAD-scoped report and a SEALED MAPPING
    package holding exactly three FRESH pins."""
    world = _world_with_base_point_and_unit(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    world["report_id"] = report["id"]
    world["report"] = fx.certify_report(api, world["report_id"])
    assert world["report"]["status"] == "CERTIFIED", world["report"]
    package = fx.setup_package(api, world["j_id"], world["report_id"], "MAPPING")
    world["package_id"] = package["id"]
    world["package"] = fx.seal_package(api, world["package_id"])
    assert_package(
        world["package"],
        status="SEALED",
        package_version=1,
        pinned_record_count=3,
        fresh_pin_count=3,
        stale_pin_count=0,
        drift_detected=False,
    )
    return world


def _world_with_certified_report_and_concurred_case(api, certify=True):
    """Jurisdiction + cell + PUBLISHED road + one ACTIVE base point, a ROAD-scoped
    report (certified when asked), a DRAFT MAPPING package on it, and a CONCURRED
    ROAD_NAME case proposing 'N MAPLE AVE'."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])
    world["road_id"] = road["id"]
    point = fx.setup_address_point(
        api, world["road_id"], world["cell_id"], geometry_verified=True
    )
    world["point_id"] = point["id"]
    fx.validate_road(api, world["road_id"])
    fx.publish_road(api, world["road_id"])
    fx.activate_point(api, world["point_id"])
    report = fx.setup_road_scoped_report(api, world["road_id"])
    world["report_id"] = report["id"]
    if certify:
        world["report"] = fx.certify_report(api, world["report_id"])
        stamped = fx.read_point(api, world["point_id"])
        assert stamped["confidence_basis"] == "CERTIFIED", stamped
        assert_score_equals(
            stamped["certified_confidence_score"], 96.00, "certified_confidence_score"
        )
    else:
        world["report"] = report
    package = fx.setup_package(api, world["j_id"], world["report_id"], "MAPPING")
    world["package_id"] = package["id"]
    assert package["status"] == "DRAFT", package
    assert package["package_version"] is None, package
    negotiation = fx.setup_concurred_case_on_road(api, world, "N MAPLE AVE")
    world.update(negotiation)
    assert world["case"]["status"] == "CONCURRED", world["case"]
    return world


# ---------------------------------------------------------------------------
# Instance: road_retire_cascades_points_units_pins_package
# ---------------------------------------------------------------------------
def test_road_retirement_cascades_to_units_pins_and_invalidates_the_sealed_package(api):
    """One retire call propagates five ordered levels, ending in a PIN_STALE invalidation.

    PRD: The retirement then cascades in strictly ordered levels.
    PRD: At level 3, caused by level 2 rather than by the retire call itself, every subaddress point whose `parent_address_point_id` is one of the base points just retired and whose `status` is `PENDING` or `ACTIVE` transitions to `RETIRED` with `retire_reason` set to `PARENT_RETIRED`; units are reached **only** through their parent and never directly by level 2.
    PRD: At level 5, caused by level 4, every provisioning package whose `status` is `SEALED` and whose `stale_pin_count` has just become greater than zero transitions to `INVALIDATED` with `invalidated_reason` set to `PIN_STALE` — this is destructive drift, because the retired records no longer exist in the field.
    Design: Difficulty/transitive_cascade/road_retire_cascades_points_units_pins_package
    """
    world = _world_with_sealed_mapping_package(api)

    retired = validate_success(
        api.retire_road_centerline(
            world["road_id"],
            {"retire_reason": "Vacated by county resolution 2026-114"},
            ANALYST_HEADERS,
        ),
        200,
    )

    # Level 1 — the centerline itself.
    assert_road_centerline(
        retired,
        status="RETIRED",
        retired_at="2026-08-01T00:00:00.000Z",
        assignable_slot_count_left=50,
    )

    # Level 2 — the base address point, swept up by the road.
    base = fx.read_point(api, world["base_id"])
    assert_address_point(base, status="RETIRED", retire_reason="ROAD_RETIRED")

    # Level 3 — the subaddress unit, reached only through its parent.
    unit = fx.read_point(api, world["unit_id_pk"])
    assert_address_point(unit, status="RETIRED", retire_reason="PARENT_RETIRED")
    assert unit["retire_reason"] != "ROAD_RETIRED", unit

    # Levels 4 and 5 — every pin stales and the sealed package invalidates.
    package = fx.read_package(api, world["package_id"])
    assert_package(
        package,
        status="INVALIDATED",
        invalidated_reason="PIN_STALE",
        pinned_record_count=3,
        stale_pin_count=3,
        fresh_pin_count=0,
        drift_detected=True,
        package_version=1,
    )


def test_road_retirement_stales_every_fresh_pin_without_decertifying_the_report(api):
    """Level 4 stamps staled_at on all three pins; the certified report is untouched.

    PRD: At level 4, caused by level 3, every `FRESH` package pin referring to any record retired in levels 1 through 3 flips to `STALE`.
    PRD: A pin is `FRESH` while `pinned_version` still equals the live record's `version`, and it flips to `STALE` the instant that live version advances, stamping `staled_at` with the logical clock instant.
    Design: Difficulty/transitive_cascade/road_retire_cascades_points_units_pins_package
    """
    world = _world_with_sealed_mapping_package(api)

    fresh_rows = fx.read_package_records(api, world["package_id"])
    assert len(fresh_rows) == 3, fresh_rows
    assert all(row["pin_state"] == "FRESH" for row in fresh_rows), fresh_rows
    assert all(row["staled_at"] is None for row in fresh_rows), fresh_rows

    validate_success(
        api.retire_road_centerline(
            world["road_id"],
            {"retire_reason": "Vacated by county resolution 2026-114"},
            ANALYST_HEADERS,
        ),
        200,
    )

    rows = fx.read_package_records(api, world["package_id"])
    assert len(rows) == 3, rows
    assert all(row["pin_state"] == "STALE" for row in rows), rows
    assert all(row["staled_at"] == "2026-08-01T00:00:00.000Z" for row in rows), rows
    by_type = sorted(row["record_type"] for row in rows)
    assert by_type == ["ADDRESS_POINT", "ADDRESS_POINT", "ROAD_CENTERLINE"], by_type

    # The retirement cascade never touches the authorising report.
    report = fx.read_report(api, world["report_id"])
    assert report["status"] == "CERTIFIED", report
    assert report["decertified_reason"] is None, report


def test_road_retirement_leaves_an_already_published_package_published_with_drift(api):
    """The distinguishing negative branch of level 5: PUBLISHED is not INVALIDATED.

    PRD: A package that is already `PUBLISHED` stays `PUBLISHED` under either kind of drift, merely flagged with `drift_detected` true; a `DRAFT` package holds no pins at all and is therefore immune.
    Design: Difficulty/transitive_cascade/road_retire_cascades_points_units_pins_package
    """
    world = _world_with_sealed_mapping_package(api)
    published = fx.publish_package(api, world["package_id"])
    assert_package(published, status="PUBLISHED", package_version=1, stale_pin_count=0)

    validate_success(
        api.retire_road_centerline(
            world["road_id"],
            {"retire_reason": "Vacated by county resolution 2026-114"},
            ANALYST_HEADERS,
        ),
        200,
    )

    package = fx.read_package(api, world["package_id"])
    assert_package(
        package,
        status="PUBLISHED",
        drift_detected=True,
        stale_pin_count=3,
        fresh_pin_count=0,
        package_version=1,
    )
    assert package["invalidated_reason"] is None, package
    assert package["published_at"] == "2026-08-01T00:00:00.000Z", package


# ---------------------------------------------------------------------------
# Instance: discrepancy_adopt_cascades_road_points_report_package
# ---------------------------------------------------------------------------
def test_adoption_cascades_through_road_points_certified_report_and_package(api):
    """Adoption renames and demotes the road, re-scores its point, decertifies the report and invalidates the package.

    PRD: At **level 2**, caused by level 1, the subject centerline applies the resolved value — writing it into `primary_name` when the `subject_type` is `ROAD_NAME`, or into that side's range fields when the `subject_type` is `ADDRESS_RANGE` — recomputes `normalized_name`, sets `qc_dirty` to true, refreshes its assignable-slot counters, and increments its own `version` by 1; and if its `status` was `PUBLISHED` it is demoted `PUBLISHED → VALIDATED` and must be re-published.
    PRD: At **level 3**, caused by level 2, every address point on that centerline whose `status` is `PENDING` or `ACTIVE` has `confidence_basis` set back to `PROVISIONAL`, `certified_confidence_score` set back to null, `confidence_score` recomputed under the provisional variant, and its own `version` incremented by 1.
    PRD: At **level 5**, caused by level 4, every provisioning package referencing such a report whose `status` is `DRAFT` or `SEALED` transitions to `INVALIDATED` with `invalidated_reason` set to `REPORT_DECERTIFIED` and its `version` incremented by 1.
    Design: Difficulty/transitive_cascade/discrepancy_adopt_cascades_road_points_report_package
    """
    world = _world_with_certified_report_and_concurred_case(api)

    adopted = fx.adopt(api, world["case_id"])

    # Level 1 — the case itself.
    assert adopted["status"] == "ADOPTED", adopted
    assert adopted["resolved_value"] == "N MAPLE AVE", adopted
    assert adopted["concurred_by_side"] == "COUNTERPARTY", adopted
    assert adopted["adopted_at"] == "2026-08-01T00:00:00.000Z", adopted
    proposals = fx.read_proposals(api, world["case_id"])
    filed = [p for p in proposals if p["id"] == world["proposal_id"]]
    assert len(filed) == 1, proposals
    assert filed[0]["status"] == "ADOPTED", filed[0]

    # Level 2 — the centerline takes the value, re-normalizes and demotes.
    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(
        road,
        primary_name="N MAPLE AVE",
        normalized_name="N MAPLE AVENUE",
        status="VALIDATED",
        qc_dirty=True,
        open_discrepancy_case_count=0,
    )

    # Level 3 — the live point reverts to PROVISIONAL and re-scores at 91.00.
    point = fx.read_point(api, world["point_id"])
    assert_address_point(point, status="ACTIVE", confidence_basis="PROVISIONAL")
    assert point["certified_confidence_score"] is None, point
    assert_score_equals(point["confidence_score"], 91.00, "confidence_score")

    # Level 4 — the certified report is taken away from underneath its owner.
    report = fx.read_report(api, world["report_id"])
    assert report["status"] == "DECERTIFIED", report
    assert report["decertified_reason"] == "SUBJECT_RECORD_CHANGED", report

    # Level 5 — the never-sealed package invalidates and keeps its null version.
    package = fx.read_package(api, world["package_id"])
    assert_package(package, status="INVALIDATED", invalidated_reason="REPORT_DECERTIFIED")
    assert package["package_version"] is None, package


def test_adoption_stops_short_of_decertifying_a_report_that_was_never_certified(api):
    """Levels 4 and 5 are conditional: a GENERATED report and its DRAFT package survive the adoption.

    PRD: At **level 4**, caused by level 3, every `CERTIFIED` QC validation report whose scope covers at least one of those address points transitions `CERTIFIED → DECERTIFIED` with `decertified_reason` set to `SUBJECT_RECORD_CHANGED` and its `version` incremented by 1.
    Design: Difficulty/transitive_cascade/discrepancy_adopt_cascades_road_points_report_package
    """
    world = _world_with_certified_report_and_concurred_case(api, certify=False)

    adopted = fx.adopt(api, world["case_id"])
    assert adopted["status"] == "ADOPTED", adopted
    assert adopted["resolved_value"] == "N MAPLE AVE", adopted

    # Levels 2 and 3 still run.
    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(
        road,
        primary_name="N MAPLE AVE",
        normalized_name="N MAPLE AVENUE",
        status="VALIDATED",
        qc_dirty=True,
    )
    point = fx.read_point(api, world["point_id"])
    assert_address_point(point, status="ACTIVE", confidence_basis="PROVISIONAL")
    assert point["certified_confidence_score"] is None, point
    assert_score_equals(point["confidence_score"], 91.00, "confidence_score")

    # Level 4 does not fire, so level 5 has nothing to invalidate.
    report = fx.read_report(api, world["report_id"])
    assert report["status"] == "GENERATED", report
    assert report["decertified_reason"] is None, report
    package = fx.read_package(api, world["package_id"])
    assert_package(package, status="DRAFT")
    assert package["invalidated_reason"] is None, package
    assert package["package_version"] is None, package
