"""Endpoint-surface contract edges: CRUD shape, reverse channels, computed reads.

Every test builds its own preconditions against an empty database with the
logical clock at its documented default, then pins the exact values the PRD
derives for the endpoint under test.
"""

import pytest

from test_helpers import (
    ACCESSIBILITY,
    CONSERVATOR,
    CURATOR,
    ERR_ARTIFACT_NOT_FOUND,
    ERR_ARTIFACT_NOT_IN_CASE,
    ERR_INTERACTIVE_NOT_FOUND,
    FABRICATION,
    NON_EXISTENT_UUID,
    OPERATIONS,
    PM,
    CaseStatus,
    ComplexityTier,
    FinishGrade,
    MaterialClass,
    OccupancyState,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    RoundStatus,
    SecurityTier,
    UsedIn,
    VoteDecision,
    assert_common_fields,
    assert_counters,
    assert_empty_envelope,
    assert_ids_in_order,
    assert_ledger,
    assert_unchanged,
    assert_zone_slots,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)


def _rows(response):
    """Validate a list envelope and return its rows."""
    validate_paginated(response)
    return response.json()["data"]


def _meta(response):
    return response.json()["meta"]


def _assert_page(response, total_count, has_more=False, limit=10, offset=0):
    """Pin the four pagination fields the PRD returns on every list response."""
    meta = _meta(response)
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more
    assert meta["limit"] == limit
    assert meta["offset"] == offset


def _assert_at_clock(actual, instant):
    """Assert a stamped timestamp names the same UTC instant as the clock."""
    assert is_iso8601_timestamp(actual), actual
    assert actual[:19] == instant[:19], "%s does not stamp %s" % (actual, instant)


def test_zone_and_object_surface_is_create_read_and_list_only(api):
    """A child is created parent-scoped, read flat and listed with an exact filter.

    "A new zone starts with `reserved_case_slots` at 0 and `available_case_slots`
    equal to its capacity, so the slot identity of §2.7 holds from creation, and
    with `occupancy_state` at `OPERATING`."

    Design: Corner/endpoints/the_crud_surface_is_create_read_list_only_with_one_delete_in_the_whole_api
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]

    zone_a = get_success_data(
        api.create_gallery_zone(
            project_id,
            factories.gallery_zone_payload(
                zone_code="Z-A",
                visitor_route_order=1,
                max_noise_dba=85.0,
                case_slot_capacity=2,
                closure_allowed=True,
                dust_settling_buffer_minutes=120,
            ),
            OPERATIONS,
        ),
        201,
    )
    assert_common_fields(zone_a, expected_version=1)
    assert zone_a["zone_code"] == "Z-A"
    assert zone_a["occupancy_state"] == OccupancyState.OPERATING
    assert_zone_slots(zone_a, 0, 2)

    flat_read = get_success_data(api.get_gallery_zone(zone_a["id"], FABRICATION), 200)
    assert flat_read["id"] == zone_a["id"]
    assert flat_read["zone_code"] == "Z-A"
    assert flat_read["max_noise_dba"] == pytest.approx(85.0, abs=0.01)
    assert flat_read["case_slot_capacity"] == 2
    assert flat_read["closure_allowed"] is True
    assert flat_read["dust_settling_buffer_minutes"] == 120
    assert flat_read["version"] == 1

    zone_b = get_success_data(
        api.create_gallery_zone(
            project_id,
            factories.gallery_zone_payload(
                zone_code="Z-B",
                visitor_route_order=2,
                max_noise_dba=70.0,
                case_slot_capacity=20,
            ),
            PM,
        ),
        201,
    )
    assert zone_b["is_public_operating"] is True
    assert zone_b["closure_allowed"] is False
    assert zone_b["dust_settling_buffer_minutes"] == 120
    assert_zone_slots(zone_b, 0, 20)

    operating = api.list_gallery_zones(
        project_id, CURATOR, {"occupancy_state": OccupancyState.OPERATING}
    )
    assert_ids_in_order(_rows(operating), [zone_a["id"], zone_b["id"]])
    _assert_page(operating, total_count=2)

    closed = api.list_gallery_zones(
        project_id, CURATOR, {"occupancy_state": OccupancyState.CLOSED}
    )
    assert _rows(closed) == []
    _assert_page(closed, total_count=0)

    artifact = get_success_data(
        api.create_artifact(
            project_id,
            factories.artifact_payload(
                accession_number="2019.14.3",
                material_class=MaterialClass.PAPER,
                security_class=SecurityTier.ENHANCED,
            ),
            CURATOR,
        ),
        201,
    )
    assert artifact["placement_status"] == PlacementStatus.UNPLACED
    assert artifact["assigned_case_id"] is None

    object_read = get_success_data(api.get_artifact(artifact["id"], CONSERVATOR), 200)
    assert object_read["id"] == artifact["id"]
    assert object_read["accession_number"] == "2019.14.3"
    assert object_read["placement_status"] == PlacementStatus.UNPLACED

    unplaced = api.list_artifacts(
        project_id, CONSERVATOR, {"placement_status": PlacementStatus.UNPLACED}
    )
    assert_ids_in_order(_rows(unplaced), [artifact["id"]])
    _assert_page(unplaced, total_count=1)

    placed = api.list_artifacts(
        project_id, CONSERVATOR, {"placement_status": PlacementStatus.PLACED}
    )
    assert _rows(placed) == []
    _assert_page(placed, total_count=0)


def test_every_foreign_key_has_a_reverse_listing_channel(api):
    """Four reverse channels each return only the rows that carry their key.

    "The project-scoped list accepts a `status` filter; the global list accepts
    any combination of `project_id`, `material_spec_id`, `subject_case_id`,
    `subject_interactive_id` and `status`, and is the reverse-lookup channel from
    a case or an interactive back to the sheets that detail it."

    Design: Corner/endpoints/every_foreign_key_has_a_reverse_listing_channel_that_filters_by_that_key
    """
    fixtures.set_clock(api)
    project_id = fixtures.create_project(api)["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    zone_a = fixtures.create_zone(
        api, project_id, headers=OPERATIONS, zone_code="Z-A", visitor_route_order=1
    )
    zone_b = fixtures.create_zone(
        api, project_id, headers=OPERATIONS, zone_code="Z-B", visitor_route_order=2
    )
    artifact = fixtures.create_artifact(api, project_id)
    case = fixtures.create_case(api, project_id, zone_a["id"], headers=CURATOR)
    interactive = fixtures.create_interactive(api, project_id)

    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fixtures.place_artifact(api, case["id"], artifact["id"])
    fixtures.approve_case(api, case["id"])
    fixtures.advance(api, project_id, Phase.FABRICATION)

    housing = fixtures.create_material(
        api,
        project_id,
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    fixtures.approve_material(api, housing["id"])
    mount_board = fixtures.create_material(
        api,
        project_id,
        material_name="Museum board mount substrate",
        used_in=UsedIn.MOUNT,
        voc_mg_per_m2_day=0.01,
        formaldehyde_ppm=0.005,
        cure_days=25,
    )
    fixtures.approve_material(api, mount_board["id"])

    get_success_data(
        api.submit_prototype(
            interactive["id"], factories.prototype_payload(60, 1500000), FABRICATION
        ),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive["id"], factories.prototype_decision_payload("APPROVE"), PM
        ),
        200,
    )
    get_success_data(api.mark_fabricated(interactive["id"], FABRICATION), 200)

    interactive_sheet = fixtures.create_drawing(
        api,
        project_id,
        housing["id"],
        drawing_number="SD-701",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=8.0,
        material_area_m2=0.5,
        finish_grade=FinishGrade.MILL,
        subject_interactive_id=interactive["id"],
    )
    case_sheet = fixtures.create_drawing(
        api,
        project_id,
        mount_board["id"],
        drawing_number="SD-702",
        complexity_tier=ComplexityTier.CONSERVATION_GRADE,
        shop_hours=6.0,
        material_area_m2=0.25,
        finish_grade=FinishGrade.SATIN,
        subject_case_id=case["id"],
    )

    by_housing = api.list_material_shop_drawings(housing["id"], PM)
    assert [row["drawing_number"] for row in _rows(by_housing)] == ["SD-701"]
    _assert_page(by_housing, total_count=1)

    by_mount = api.list_material_shop_drawings(mount_board["id"], PM)
    assert [row["drawing_number"] for row in _rows(by_mount)] == ["SD-702"]
    _assert_page(by_mount, total_count=1)

    by_case = api.list_shop_drawings(PM, {"subject_case_id": case["id"]})
    assert_ids_in_order(_rows(by_case), [case_sheet["id"]])
    _assert_page(by_case, total_count=1)

    by_interactive = api.list_shop_drawings(
        PM, {"subject_interactive_id": interactive["id"]}
    )
    assert_ids_in_order(_rows(by_interactive), [interactive_sheet["id"]])
    _assert_page(by_interactive, total_count=1)

    cases_in_a = api.list_zone_artifact_cases(zone_a["id"], OPERATIONS)
    assert [row["case_code"] for row in _rows(cases_in_a)] == ["C-01"]
    _assert_page(cases_in_a, total_count=1)

    cases_in_b = api.list_zone_artifact_cases(zone_b["id"], OPERATIONS)
    assert _rows(cases_in_b) == []
    _assert_page(cases_in_b, total_count=0)

    submitted = api.list_project_shop_drawings(project_id, PM, {"status": "SUBMITTED"})
    assert [row["drawing_number"] for row in _rows(submitted)] == ["SD-701", "SD-702"]
    _assert_page(submitted, total_count=2)


def test_project_read_is_a_pure_computed_projection_of_its_children(api):
    """Reads never bump the version and one child create moves counter, posture and version.

    "A freshly submitted material lands in `SUBMITTED` status with its verdict
    already computed, its `conditions` null and its `decided_at` null. That alone
    raises the project's `pending_material_count` and is enough to make an
    otherwise clean project `RESTRICTED`, and it increments the project's
    `version`."

    Design: Corner/endpoints/the_project_read_is_a_pure_computed_projection_of_its_children
    """
    ctx = fixtures.project_in_phase(api, Phase.DESIGN_DEV)
    project_id = ctx["project_id"]
    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fixtures.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fixtures.approve_case(api, ctx["case_id"])

    first = fixtures.read_project(api, project_id, ACCESSIBILITY)
    assert_counters(
        first,
        posture=Posture.OPEN,
        conservation_veto_count=0,
        conservation_block_count=0,
        open_revision_count=0,
        conditional_case_count=0,
        pending_material_count=0,
        blocking_punch_count=0,
    )
    assert first["retainage_held_cents"] == 0
    assert first["warranty_reserve_cents"] == 0
    assert first["released_cents"] == 0
    assert_ledger(first, 0, 9000000)

    second = fixtures.read_project(api, project_id, OPERATIONS)
    assert second["version"] == first["version"]
    assert second["posture"] == first["posture"]
    assert_unchanged(
        first,
        second,
        [
            "version",
            "posture",
            "updated_at",
            "committed_fabrication_cents",
            "uncommitted_cents",
        ],
    )

    material = fixtures.create_material(
        api,
        project_id,
        material_name="Zinc-coated steel deck",
        used_in=UsedIn.CASE_EXTERIOR,
        voc_mg_per_m2_day=0.2,
        formaldehyde_ppm=0.05,
        cure_days=10,
    )
    assert material["status"] == "SUBMITTED"

    third = fixtures.read_project(api, project_id, ACCESSIBILITY)
    assert_counters(third, pending_material_count=1, posture=Posture.RESTRICTED)
    assert third["version"] > first["version"]
    assert_ledger(third, 0, 9000000)

    missing = api.get_interactive(NON_EXISTENT_UUID, PM)
    validate_error(missing, ERR_INTERACTIVE_NOT_FOUND, 404)


def test_one_review_sweep_lapses_exactly_the_rounds_whose_deadline_has_passed(api):
    """The sweep lapses the due round, leaves the future one live and is idempotent.

    "Every round of that project that is still `OPEN` and whose
    `decision_deadline_at` is at or before the current logical-clock instant is
    lapsed, and the qualifying rounds are processed in ascending order of
    `decision_deadline_at` with `created_at` ascending as the tie-break, so the
    sweep's effects are order-deterministic."

    Design: Corner/endpoints/one_review_sweep_lapses_exactly_the_rounds_whose_deadline_has_passed
    """
    fixtures.set_clock(api)
    project_id = fixtures.create_project(api)["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    schematic_package = fixtures.create_package(
        api, project_id, stage=PackageStage.SCHEMATIC
    )
    design_dev_package = fixtures.create_package(
        api,
        project_id,
        stage=PackageStage.DESIGN_DEV,
        egress_clear_width_cm=130.0,
        wheelchair_turning_radius_cm=80.0,
        peak_visitors_per_hour=200,
        circulation_area_sqm=140.0,
    )
    due_round = fixtures.open_round(
        api, schematic_package["id"], decision_deadline_at="2026-08-10T00:00:00Z"
    )
    future_round = fixtures.open_round(
        api, design_dev_package["id"], decision_deadline_at="2026-08-25T00:00:00Z"
    )

    swept_instant = "2026-08-20T09:00:00Z"
    fixtures.set_clock(api, swept_instant)
    swept_project = get_success_data(api.review_sweep(project_id, PM), 200)
    assert_counters(
        swept_project, posture=Posture.RESTRICTED, open_revision_count=1
    )

    lapsed = get_success_data(api.get_review_round(due_round["id"], CURATOR), 200)
    assert lapsed["status"] == RoundStatus.REVISION_REQUESTED
    assert lapsed["swept_by_deadline"] is True
    _assert_at_clock(lapsed["decided_at"], swept_instant)
    assert lapsed["cast_vote_count"] == 0

    survivor = get_success_data(api.get_review_round(future_round["id"], CURATOR), 200)
    assert survivor["status"] == RoundStatus.OPEN
    assert survivor["swept_by_deadline"] is False
    assert survivor["decided_at"] is None

    lapsed_package = get_success_data(
        api.get_design_package(schematic_package["id"], CURATOR), 200
    )
    assert lapsed_package["status"] == PackageStatus.REVISION_REQUESTED
    assert lapsed_package["revision_count"] == 1

    untouched_package = get_success_data(
        api.get_design_package(design_dev_package["id"], CURATOR), 200
    )
    assert untouched_package["status"] == PackageStatus.IN_REVIEW
    assert untouched_package["revision_count"] == 0

    voted = fixtures.cast_vote(
        api, future_round["id"], CURATOR, VoteDecision.APPROVE
    )
    assert voted["cast_vote_count"] == 1
    assert voted["status"] == RoundStatus.OPEN

    before_second_sweep = get_success_data(
        api.get_review_round(future_round["id"], CURATOR), 200
    )
    second_sweep = get_success_data(api.review_sweep(project_id, PM), 200)
    assert_counters(second_sweep, posture=Posture.RESTRICTED, open_revision_count=1)
    after_second_sweep = get_success_data(
        api.get_review_round(future_round["id"], CURATOR), 200
    )
    assert after_second_sweep["status"] == RoundStatus.OPEN
    assert after_second_sweep["swept_by_deadline"] is False
    assert_unchanged(
        before_second_sweep,
        after_second_sweep,
        ["status", "swept_by_deadline", "decided_at", "cast_vote_count", "version"],
    )


def test_withdrawing_a_placement_checks_the_case_object_pair(api):
    """The withdrawal is a join condition, so the sibling case and the repeat both refuse.

    "The object must currently be assigned to that case with `placement_status`
    `RESERVED` or `PLACED`, or the request answers `ERR_ARTIFACT_NOT_IN_CASE`
    (HTTP 409)."

    Design: Corner/endpoints/withdrawing_a_placement_checks_the_pair_and_not_just_the_two_ids
    """
    ctx = fixtures.project_in_phase(
        api, Phase.DESIGN_DEV, zone_overrides={"case_slot_capacity": 4}
    )
    project_id = ctx["project_id"]
    first_case_id = ctx["case_id"]
    first_object_id = ctx["artifact_id"]

    second_object = fixtures.create_artifact(
        api, project_id, accession_number="2019.14.6"
    )
    second_case = fixtures.create_case(
        api,
        project_id,
        ctx["zone_id"],
        headers=CURATOR,
        case_code="C-02",
        objective_code=factories.OBJECTIVE_SECONDARY,
    )

    fixtures.place_artifact(api, first_case_id, first_object_id)
    fixtures.place_artifact(api, second_case["id"], second_object["id"])

    sibling_before = get_success_data(api.get_artifact(second_object["id"], CURATOR), 200)
    case_before = get_success_data(api.get_artifact_case(first_case_id, CURATOR), 200)

    cross_case = api.delete_placement(first_case_id, second_object["id"], CURATOR)
    validate_error(cross_case, ERR_ARTIFACT_NOT_IN_CASE, 409)

    unknown_object = api.delete_placement(first_case_id, NON_EXISTENT_UUID, CURATOR)
    validate_error(unknown_object, ERR_ARTIFACT_NOT_FOUND, 404)

    sibling_after = get_success_data(api.get_artifact(second_object["id"], CURATOR), 200)
    assert sibling_after["placement_status"] == PlacementStatus.RESERVED
    assert sibling_after["assigned_case_id"] == second_case["id"]
    assert_unchanged(
        sibling_before,
        sibling_after,
        ["placement_status", "assigned_case_id", "version", "updated_at"],
    )
    case_after_refusals = get_success_data(
        api.get_artifact_case(first_case_id, CURATOR), 200
    )
    assert_unchanged(
        case_before,
        case_after_refusals,
        ["placed_artifact_count", "status", "version", "updated_at"],
    )

    withdrawn = get_success_data(
        api.delete_placement(first_case_id, first_object_id, CONSERVATOR), 200
    )
    assert withdrawn["id"] == first_object_id
    assert withdrawn["placement_status"] == PlacementStatus.UNPLACED
    assert withdrawn["assigned_case_id"] is None

    repeated = api.delete_placement(first_case_id, first_object_id, CONSERVATOR)
    validate_error(repeated, ERR_ARTIFACT_NOT_IN_CASE, 409)

    emptied = get_success_data(api.get_artifact_case(first_case_id, CURATOR), 200)
    assert_empty_envelope(emptied)
    assert emptied["status"] == CaseStatus.DRAFT

    sibling_case = get_success_data(
        api.get_artifact_case(second_case["id"], CURATOR), 200
    )
    assert sibling_case["placed_artifact_count"] == 1
