"""Edges of the derived case envelope, the case geometry, the package flow score
and the blocking-defect gate on the closeout advance.

Every test builds its own preconditions through the documented endpoints: the
harness restarts the server before each test, so each one opens on an empty
database with the logical clock at its documented default instant.
"""

from test_helpers import (
    ACCESSIBILITY,
    CONSERVATOR,
    CURATOR,
    ERR_BLOCKING_PUNCH_ITEMS_OPEN,
    ERR_ENV_ENVELOPE_INFEASIBLE,
    FABRICATION,
    LATE_CLOCK,
    OBJECTIVE_PRIMARY,
    OBJECTIVE_SECONDARY,
    OPERATIONS,
    PM,
    MaterialClass,
    MountStatus,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    PrototypeDecision,
    PunchStatus,
    SecurityTier,
    Severity,
    USER_ACCESSIBILITY,
    assert_counters,
    assert_empty_envelope,
    assert_envelope,
    assert_geometry,
    assert_index,
    assert_unchanged,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)

#: The three sibling collection objects of the envelope probes. Their bands are
#: mutually incompatible, so an envelope that aggregates the wrong set of
#: objects cannot reproduce any of the pinned limits.
PAPER_OBJECT = {
    "accession_number": "2019.14.3",
    "material_class": MaterialClass.PAPER,
    "required_rh_min_pct": 45.0,
    "required_rh_max_pct": 55.0,
    "max_lux": 50.0,
    "security_class": SecurityTier.ENHANCED,
}
TEXTILE_OBJECT = {
    "accession_number": "2019.14.4",
    "material_class": MaterialClass.TEXTILE,
    "required_rh_min_pct": 50.0,
    "required_rh_max_pct": 52.0,
    "max_lux": 30.0,
    "security_class": SecurityTier.ENHANCED,
}
ORGANIC_OBJECT = {
    "accession_number": "2019.14.5",
    "required_rh_min_pct": 48.0,
    "required_rh_max_pct": 51.0,
    "max_lux": 20.0,
    "security_class": SecurityTier.HIGH_VALUE,
}


def _design_dev_project_with_zone(api, **zone_overrides):
    """Walk a commission to DESIGN_DEV and register one gallery zone in it."""
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id, **zone_overrides)
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    return project_id, zone


def _two_sibling_cases_in_one_zone(api):
    """Build two cases in one zone, each holding one object of its own.

    ``C-01`` is an ENHANCED case at 50 +/- 2 percent RH holding the paper
    object; ``C-02`` is a HIGH_VALUE case at 49.5 +/- 1.0 percent RH holding the
    organic object. The textile object is registered but left unplaced, so the
    project holds three objects while each case holds exactly one.
    """
    project_id, zone = _design_dev_project_with_zone(api, case_slot_capacity=4)
    paper = fixtures.create_artifact(api, project_id, **PAPER_OBJECT)
    textile = fixtures.create_artifact(api, project_id, **TEXTILE_OBJECT)
    organic = fixtures.create_artifact(api, project_id, **ORGANIC_OBJECT)
    first = fixtures.create_case(
        api,
        project_id,
        zone["id"],
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
        security_tier=SecurityTier.ENHANCED,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
    )
    second = fixtures.create_case(
        api,
        project_id,
        zone["id"],
        case_code="C-02",
        objective_code=OBJECTIVE_SECONDARY,
        security_tier=SecurityTier.HIGH_VALUE,
        target_rh_pct=49.5,
        rh_tolerance_pct=1.0,
        target_lux=20.0,
        uv_microwatt_per_lumen=20.0,
    )
    fixtures.place_artifact(api, first["id"], paper["id"])
    fixtures.place_artifact(api, second["id"], organic["id"])
    return {
        "project_id": project_id,
        "zone": zone,
        "paper_id": paper["id"],
        "textile_id": textile["id"],
        "organic_id": organic["id"],
        "first_case_id": first["id"],
        "second_case_id": second["id"],
    }


def _commissioning_project_with_a_commissioned_station(api):
    """Walk a commission to COMMISSIONING and commission its one station.

    The bench work is submitted and ruled on while the shop is still building,
    which is the only stretch of the ladder that accepts a prototype, so by the
    time the gallery is handed back every interactive of the project is
    ``COMMISSIONED`` and the only remaining admission test on the step to
    CLOSEOUT is the blocking-defect one.
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    project_id = ctx["project_id"]
    case_id = ctx["case_id"]
    station_id = ctx["interactive_id"]

    get_success_data(
        api.submit_prototype(station_id, factories.prototype_payload(), FABRICATION), 200
    )
    get_success_data(
        api.prototype_decision(
            station_id,
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    get_success_data(api.mark_fabricated(station_id, FABRICATION), 200)

    fixtures.place_artifact(api, case_id, ctx["artifact_id"])
    fixtures.approve_case(api, case_id)
    drawing = fixtures.create_drawing(
        api, project_id, ctx["material_id"], subject_case_id=case_id
    )
    fixtures.approve_drawing(api, drawing["id"])
    fixtures.advance_mount(api, case_id, MountStatus.MOUNT_DESIGN)
    fixtures.advance_mount(api, case_id, MountStatus.MOUNT_FABRICATED)

    window = fixtures.create_window(
        api,
        project_id,
        ctx["zone_id"],
        starts_at="2026-09-09T09:00:00Z",
        ends_at="2026-09-09T12:00:00Z",
    )
    fixtures.decide_window(api, window["id"])
    fixtures.advance(api, project_id, Phase.INSTALLATION)
    fixtures.set_clock(api, LATE_CLOCK)
    fixtures.start_window(api, window["id"])
    fixtures.advance_mount(api, case_id, MountStatus.MOUNT_INSTALLED)
    fixtures.complete_window(api, window["id"])
    fixtures.advance(api, project_id, Phase.COMMISSIONING)
    get_success_data(
        api.commission_interactive(station_id, factories.commission_payload(), PM), 200
    )
    return ctx


def test_the_case_envelope_reads_only_the_objects_reserved_in_that_one_case(api):
    """Two cases in one zone keep disjoint envelope input sets.

    The project holds three objects with mutually incompatible bands, yet each
    case derives its limits from the single object reserved in it: the unplaced
    textile object and the organic object sitting in the sibling case never
    reach C-01's derivation.

    "The case's real constraint appears when objects go into it, and it is a **strictest-wins** envelope recomputed over the set of objects currently reserved or placed in the case."
    "Objects that are `UNPLACED` or `DEINSTALLED` are excluded from that set even if they once sat in this case."
    "When it is not empty, `required_rh_min_pct` becomes the **largest** of the objects' individual humidity floors, `required_rh_max_pct` becomes the **smallest** of their humidity ceilings, and `allowed_lux` becomes the **smallest** of their `max_lux` values."
    "`env_feasible` is true only when all five of the following hold together: the derived floor is no greater than the derived ceiling; the case's setpoint less its tolerance is at least the derived floor; the case's setpoint plus its tolerance is at most the derived ceiling; the case's `target_lux` is at most `allowed_lux`; and the case's `uv_microwatt_per_lumen` is at most 75.0 microwatts per lumen."
    "`security_ok` is true when the case's build tier ranks at or above the highest security class among the objects in it, ranking `BASIC` as 1, `ENHANCED` as 2 and `HIGH_VALUE` as 3."
    Design: Corner/calculations/the_case_envelope_reads_only_reserved_or_placed_artifacts_of_that_one_case
    """
    ctx = _two_sibling_cases_in_one_zone(api)

    first = get_success_data(api.get_artifact_case(ctx["first_case_id"], CURATOR), 200)
    assert_envelope(
        first,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )

    second = get_success_data(api.get_artifact_case(ctx["second_case_id"], CURATOR), 200)
    assert_envelope(
        second,
        placed_artifact_count=1,
        required_rh_min_pct=48.0,
        required_rh_max_pct=51.0,
        allowed_lux=20.0,
        env_feasible=True,
        security_ok=True,
    )


def test_a_case_reports_its_volume_and_silica_charge_from_its_own_geometry(api):
    """A case 120 by 60 by 90 centimetres at 0.4 air exchanges a day.

    "`case_volume_m3` is the product of the three interior dimensions in centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic metre — rounded half up to four decimal places."
    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."
    Design: Corner/calculations/the_case_envelope_reads_only_reserved_or_placed_artifacts_of_that_one_case
    """
    ctx = _two_sibling_cases_in_one_zone(api)

    first = get_success_data(api.get_artifact_case(ctx["first_case_id"], CURATOR), 200)
    assert_geometry(first, case_volume_m3=0.648, silica_gel_kg=0.91)


def test_a_placement_refused_for_the_envelope_leaves_the_case_and_the_object_alone(api):
    """The textile object cannot join the paper object in C-01.

    Its 50 percent floor would raise the derived floor to 50.0 while the case
    guarantees only 50.0 less 2.0, so the placement is refused and nothing about
    the case or the candidate object moves.

    "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."
    "A successful placement sets the object's `assigned_case_id` to the case, moves its `placement_status` `UNPLACED → RESERVED`, increments the case's `placed_artifact_count`, and rewrites `required_rh_min_pct`, `required_rh_max_pct`, `allowed_lux`, `env_feasible` and `security_ok` from the new set."
    "Both rows have their `updated_at` refreshed and their `version` incremented by one."
    "Every object begins `UNPLACED` with `assigned_case_id` null, and its `placement_status` walks `UNPLACED`, `RESERVED`, `PLACED` and the terminal `DEINSTALLED`."
    "Either way both rows have their `updated_at` and `version` advanced, and the case's list of assigned objects — which shows objects in any `placement_status` and accepts a `placement_status` filter — remains the reverse-lookup channel from a case to its contents."
    Design: Corner/calculations/the_case_envelope_reads_only_reserved_or_placed_artifacts_of_that_one_case
    """
    ctx = _two_sibling_cases_in_one_zone(api)
    case_id = ctx["first_case_id"]
    before = get_success_data(api.get_artifact_case(case_id, CURATOR), 200)

    refused = api.create_placement(
        case_id,
        factories.placement_payload(ctx["textile_id"], before["version"]),
        CURATOR,
    )
    validate_error(refused, ERR_ENV_ENVELOPE_INFEASIBLE)

    after = get_success_data(api.get_artifact_case(case_id, CURATOR), 200)
    assert_envelope(
        after,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )
    assert_unchanged(before, after, ["version", "placed_artifact_count"])

    candidate = get_success_data(api.get_artifact(ctx["textile_id"], CURATOR), 200)
    assert candidate["placement_status"] == PlacementStatus.UNPLACED
    assert candidate["assigned_case_id"] is None

    rows, meta = validate_paginated(api.list_placements(case_id, CURATOR))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [ctx["paper_id"]]
    assert rows[0]["placement_status"] == PlacementStatus.RESERVED


def test_each_design_package_is_scored_from_its_own_four_route_numbers(api):
    """Three same-stage packages, three unrelated flow scores.

    The first route carries 180 visitors an hour across 95 square metres, the
    second 400 across 200, and the third only 100 across 300 — so far above the
    requirement that the ceiling binds before the two-decimal rounding.

    "The route must provide 0.65 square metres of circulation area per visitor per hour of designed peak throughput, so the required area is `peak_visitors_per_hour` multiplied by 0.65."
    "The circulation ratio is `circulation_area_sqm` divided by that required area, and `flow_capacity_score` is that ratio multiplied by 100, capped at 100.0, then rounded half up to two decimal places — a route with exactly the required area therefore scores 100.00, and a route with double the required area also scores 100.00 because of the cap."
    "`accessibility_pass` is true only when all three minimums hold together: `egress_clear_width_cm` is at least 112, `wheelchair_turning_radius_cm` is at least 76, and `flow_capacity_score` is at least 60.0."
    "A package that passes is stored in status `DRAFT` with `review_round_count` and `revision_count` both 0, `submitted_by_user_id` taken from the caller's header, `approved_at` null and `superseded_by_package_id` null."
    Design: Corner/calculations/each_design_package_is_scored_from_its_own_four_inputs_and_never_re_scored
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    narrow = fixtures.create_package(
        api,
        project_id,
        PackageStage.SCHEMATIC,
        egress_clear_width_cm=112.0,
        wheelchair_turning_radius_cm=76.0,
        peak_visitors_per_hour=180,
        circulation_area_sqm=95.0,
    )
    assert_index(narrow["flow_capacity_score"], 81.20)
    assert narrow["accessibility_pass"] is True

    busy = fixtures.create_package(
        api,
        project_id,
        PackageStage.SCHEMATIC,
        egress_clear_width_cm=150.0,
        wheelchair_turning_radius_cm=90.0,
        peak_visitors_per_hour=400,
        circulation_area_sqm=200.0,
    )
    assert_index(busy["flow_capacity_score"], 76.92)
    assert busy["accessibility_pass"] is True

    generous = fixtures.create_package(
        api,
        project_id,
        PackageStage.SCHEMATIC,
        headers=ACCESSIBILITY,
        egress_clear_width_cm=112.0,
        wheelchair_turning_radius_cm=76.0,
        peak_visitors_per_hour=100,
        circulation_area_sqm=300.0,
    )
    assert_index(generous["flow_capacity_score"], 100.00)
    assert generous["accessibility_pass"] is True
    assert generous["status"] == PackageStatus.DRAFT
    assert generous["submitted_by_user_id"] == USER_ACCESSIBILITY
    assert generous["superseded_by_package_id"] is None


def test_a_superseded_package_keeps_its_score_and_names_the_package_that_displaced_it(api):
    """Scoring happens once, at creation, and supersession never re-scores.

    Each new same-stage package displaces only the packages still standing, so
    the first package points at the second and the second at the third.

    "Before the package is stored, the system computes its flow and accessibility results."
    "Every existing package of this project whose `stage` matches the new one and whose status is not already `SUPERSEDED` — that is, any package in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED` or `APPROVED` — transitions to `SUPERSEDED`, processed in ascending `created_at` order, and has its `superseded_by_package_id` set to the new package's identifier."
    "Packages of a project may be listed with `stage` and `status` filters, and a single package read back with its computed flow figures."
    Design: Corner/calculations/each_design_package_is_scored_from_its_own_four_inputs_and_never_re_scored
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    narrow = fixtures.create_package(
        api,
        project_id,
        PackageStage.SCHEMATIC,
        egress_clear_width_cm=112.0,
        wheelchair_turning_radius_cm=76.0,
        peak_visitors_per_hour=180,
        circulation_area_sqm=95.0,
    )
    busy = fixtures.create_package(
        api,
        project_id,
        PackageStage.SCHEMATIC,
        egress_clear_width_cm=150.0,
        wheelchair_turning_radius_cm=90.0,
        peak_visitors_per_hour=400,
        circulation_area_sqm=200.0,
    )
    generous = fixtures.create_package(
        api,
        project_id,
        PackageStage.SCHEMATIC,
        headers=ACCESSIBILITY,
        egress_clear_width_cm=112.0,
        wheelchair_turning_radius_cm=76.0,
        peak_visitors_per_hour=100,
        circulation_area_sqm=300.0,
    )

    first = get_success_data(api.get_design_package(narrow["id"], ACCESSIBILITY), 200)
    assert_index(first["flow_capacity_score"], 81.20)
    assert first["status"] == PackageStatus.SUPERSEDED
    assert first["superseded_by_package_id"] == busy["id"]

    second = get_success_data(api.get_design_package(busy["id"], ACCESSIBILITY), 200)
    assert_index(second["flow_capacity_score"], 76.92)
    assert second["status"] == PackageStatus.SUPERSEDED
    assert second["superseded_by_package_id"] == generous["id"]

    third = get_success_data(api.get_design_package(generous["id"], PM), 200)
    assert_index(third["flow_capacity_score"], 100.00)
    assert third["status"] == PackageStatus.DRAFT
    assert third["superseded_by_package_id"] is None


def _design_dev_project_with_two_paper_objects(api):
    """A commission in DESIGN_DEV with one zone and two identical paper objects."""
    project_id, zone = _design_dev_project_with_zone(api, case_slot_capacity=4)
    first = fixtures.create_artifact(api, project_id, **PAPER_OBJECT)
    second = fixtures.create_artifact(
        api, project_id, **dict(PAPER_OBJECT, accession_number="2019.14.6")
    )
    return project_id, zone["id"], first["id"], second["id"]


def test_a_case_lit_exactly_at_the_uv_ceiling_accepts_its_first_object(api):
    """75.0 microwatts per lumen sits on the ceiling, and the ceiling is inclusive.

    Every other comparison in the chain also passes on equality: the object's
    band 45 to 55 contains the case's 50 plus or minus 2, and the case's target
    illuminance equals the object's own limit.

    "`env_feasible` is true only when all five of the following hold together: the derived floor is no greater than the derived ceiling; the case's setpoint less its tolerance is at least the derived floor; the case's setpoint plus its tolerance is at most the derived ceiling; the case's `target_lux` is at most `allowed_lux`; and the case's `uv_microwatt_per_lumen` is at most 75.0 microwatts per lumen."
    "Every one of those comparisons is inclusive, so a case whose `target_lux` exactly equals the strictest `allowed_lux` passes."
    "A successful placement sets the object's `assigned_case_id` to the case, moves its `placement_status` `UNPLACED → RESERVED`, increments the case's `placed_artifact_count`, and rewrites `required_rh_min_pct`, `required_rh_max_pct`, `allowed_lux`, `env_feasible` and `security_ok` from the new set."
    Design: Corner/calculations/the_uv_ceiling_and_the_silica_constant_are_the_two_untested_constants_of_the_envelope
    """
    project_id, zone_id, object_id, _ = _design_dev_project_with_two_paper_objects(api)

    case = fixtures.create_case(
        api,
        project_id,
        zone_id,
        headers=CURATOR,
        case_code="C-UV1",
        security_tier=SecurityTier.ENHANCED,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=75.0,
    )
    assert_empty_envelope(case)

    placed = get_success_data(
        api.create_placement(
            case["id"], factories.placement_payload(object_id, case["version"]), CURATOR
        ),
        201,
    )
    assert placed["placement_status"] == PlacementStatus.RESERVED

    loaded = get_success_data(api.get_artifact_case(case["id"], CONSERVATOR), 200)
    assert_envelope(
        loaded,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )


def test_a_case_over_the_uv_ceiling_is_stored_feasible_and_refuses_its_first_object(api):
    """75.1 microwatts per lumen is stored without complaint and then refused.

    The empty case reports null bounds and a feasible envelope, because the UV
    comparison lives inside the non-empty branch; the first placement is the
    moment the ceiling is consulted, and it is the only failing comparison.

    "When the set is empty, the three derived limits are null and both feasibility flags are true."
    "Because the case is empty, `required_rh_min_pct`, `required_rh_max_pct` and `allowed_lux` are all null while `env_feasible` and `security_ok` are both true."
    "`env_feasible` is true only when all five of the following hold together: the derived floor is no greater than the derived ceiling; the case's setpoint less its tolerance is at least the derived floor; the case's setpoint plus its tolerance is at most the derived ceiling; the case's `target_lux` is at most `allowed_lux`; and the case's `uv_microwatt_per_lumen` is at most 75.0 microwatts per lumen."
    "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."
    Design: Corner/calculations/the_uv_ceiling_and_the_silica_constant_are_the_two_untested_constants_of_the_envelope
    """
    project_id, zone_id, _, object_id = _design_dev_project_with_two_paper_objects(api)

    case = fixtures.create_case(
        api,
        project_id,
        zone_id,
        headers=CURATOR,
        case_code="C-UV2",
        security_tier=SecurityTier.ENHANCED,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=75.1,
    )
    assert_empty_envelope(case)

    refused = api.create_placement(
        case["id"], factories.placement_payload(object_id, case["version"]), CURATOR
    )
    validate_error(refused, ERR_ENV_ENVELOPE_INFEASIBLE)


def test_a_one_cubic_metre_case_charges_three_and_a_half_kilograms_per_air_exchange(api):
    """A metre cube at one air exchange a day shows the silica constant undisguised.

    "`case_volume_m3` is the product of the three interior dimensions in centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic metre — rounded half up to four decimal places."
    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."
    Design: Corner/calculations/the_uv_ceiling_and_the_silica_constant_are_the_two_untested_constants_of_the_envelope
    """
    project_id, zone_id, _, _ = _design_dev_project_with_two_paper_objects(api)

    case = fixtures.create_case(
        api,
        project_id,
        zone_id,
        headers=CURATOR,
        case_code="C-UV3",
        security_tier=SecurityTier.ENHANCED,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
        interior_l_cm=100.0,
        interior_w_cm=100.0,
        interior_h_cm=100.0,
        air_exchanges_per_day=1.0,
    )
    assert_geometry(case, case_volume_m3=1.0, silica_gel_kg=3.5)


def test_the_silica_charge_follows_the_already_rounded_volume_at_a_half_up_tie(api):
    """A case of 100 by 61 by 33.6 centimetres at 2.0 air exchanges a day.

    The raw product is 0.20496 cubic metres, which carries up to 0.2050 at four
    decimals; that rounded volume priced at 2.0 exchanges lands exactly on the
    midpoint 1.435 and must round away from zero. Carrying the unrounded product
    forward would give 1.43472 and therefore a different charge.

    "Every rounding in this system is **round half up** — a value exactly on the midpoint rounds away from zero — and every rounding happens at a named point, never "at the end" as a convenience."
    "A case's interior volume is rounded to four decimal places in cubic metres, and its silica gel charge is rounded to two decimal places using the already-rounded volume."
    "`case_volume_m3` is the product of the three interior dimensions in centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic metre — rounded half up to four decimal places."
    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."
    Design: Corner/calculations/the_silica_charge_is_computed_from_the_already_rounded_volume_not_the_raw_product
    """
    project_id, zone = _design_dev_project_with_zone(api, case_slot_capacity=4)

    case = fixtures.create_case(
        api,
        project_id,
        zone["id"],
        headers=CURATOR,
        case_code="C-P1",
        security_tier=SecurityTier.BASIC,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
        interior_l_cm=100.0,
        interior_w_cm=61.0,
        interior_h_cm=33.6,
        air_exchanges_per_day=2.0,
    )
    assert_geometry(case, case_volume_m3=0.2050, silica_gel_kg=1.44)

    loaded = get_success_data(api.get_artifact_case(case["id"], FABRICATION), 200)
    assert_geometry(loaded, case_volume_m3=0.2050, silica_gel_kg=1.44)


def test_a_four_decimal_volume_tie_rounds_away_from_zero_before_the_charge_is_priced(api):
    """A case of 82.3 by 50 by 30 centimetres at 0.4 air exchanges a day.

    The product is exactly 0.12345 cubic metres, a true four-decimal midpoint,
    and the charge is then priced from the 0.1235 the rounding produced.

    "Every rounding in this system is **round half up** — a value exactly on the midpoint rounds away from zero — and every rounding happens at a named point, never "at the end" as a convenience."
    "A case's interior volume is rounded to four decimal places in cubic metres, and its silica gel charge is rounded to two decimal places using the already-rounded volume."
    "`case_volume_m3` is the product of the three interior dimensions in centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic metre — rounded half up to four decimal places."
    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."
    Design: Corner/calculations/the_silica_charge_is_computed_from_the_already_rounded_volume_not_the_raw_product
    """
    project_id, zone = _design_dev_project_with_zone(api, case_slot_capacity=4)

    case = fixtures.create_case(
        api,
        project_id,
        zone["id"],
        headers=CURATOR,
        case_code="C-P2",
        security_tier=SecurityTier.BASIC,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
        interior_l_cm=82.3,
        interior_w_cm=50.0,
        interior_h_cm=30.0,
        air_exchanges_per_day=0.4,
    )
    assert_geometry(case, case_volume_m3=0.1235, silica_gel_kg=0.17)


def test_a_blocking_defect_holds_the_closeout_advance_while_the_posture_stays_open(api):
    """The blocking counter gates the step to CLOSEOUT and nothing else.

    A blocking defect raised in commissioning is not one of the three counters
    that soften a commission to RESTRICTED, so the project reads OPEN while the
    advance is refused for the defect itself.

    "The item is stored `OPEN` with `raised_by_role` set from the caller's role header and `raised_by_user_id` from the caller, and a `BLOCKING` item increments the project's `blocking_punch_count`."
    "Otherwise, if `open_revision_count` is greater than zero, or `conditional_case_count` is greater than zero, or `pending_material_count` is greater than zero, posture is `RESTRICTED`."
    "Otherwise posture is `OPEN`."
    "`COMMISSIONING → CLOSEOUT` requires `blocking_punch_count` to be 0, failing with `ERR_BLOCKING_PUNCH_ITEMS_OPEN` when a blocking defect is still open, and requires every interactive of the project to be `COMMISSIONED`."
    Design: Corner/calculations/blocking_punch_items_gate_the_closeout_advance_without_ever_touching_the_posture
    """
    ctx = _commissioning_project_with_a_commissioned_station(api)
    project_id = ctx["project_id"]

    opening = fixtures.read_project(api, project_id)
    assert opening["phase"] == Phase.COMMISSIONING
    assert_counters(opening, blocking_punch_count=0, posture=Posture.OPEN)

    defect = fixtures.raise_punch_item(
        api,
        project_id,
        headers=OPERATIONS,
        severity=Severity.BLOCKING,
        description="Case C-01 door gasket does not seal; RH excursion measured at 6 percent.",
    )
    assert defect["status"] == PunchStatus.OPEN

    loaded = fixtures.read_project(api, project_id)
    assert_counters(loaded, blocking_punch_count=1, posture=Posture.OPEN)

    refused = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.CLOSEOUT), PM
    )
    validate_error(refused, ERR_BLOCKING_PUNCH_ITEMS_OPEN)
    assert fixtures.read_project(api, project_id)["phase"] == Phase.COMMISSIONING


def test_verifying_the_blocking_defect_decrements_the_counter_and_opens_the_advance(api):
    """Verification clears exactly the count the defect added.

    "The item is stored `OPEN` with `raised_by_role` set from the caller's role header and `raised_by_user_id` from the caller, and a `BLOCKING` item increments the project's `blocking_punch_count`."
    "A `FabricationLead` or a `ProjectManager` verifies an `OPEN` item while the project is in `COMMISSIONING` or `CLOSEOUT`, supplying a `verification_note`; the caller may not be the person who raised it, the item becomes `VERIFIED`, `verified_by_user_id`, `verification_note` and `verified_at` are recorded, and a `BLOCKING` item decrements `blocking_punch_count`."
    "Otherwise posture is `OPEN`."
    "`COMMISSIONING → CLOSEOUT` requires `blocking_punch_count` to be 0, failing with `ERR_BLOCKING_PUNCH_ITEMS_OPEN` when a blocking defect is still open, and requires every interactive of the project to be `COMMISSIONED`."
    Design: Corner/calculations/blocking_punch_items_gate_the_closeout_advance_without_ever_touching_the_posture
    """
    ctx = _commissioning_project_with_a_commissioned_station(api)
    project_id = ctx["project_id"]

    defect = fixtures.raise_punch_item(
        api,
        project_id,
        headers=OPERATIONS,
        severity=Severity.BLOCKING,
        description="Case C-01 door gasket does not seal; RH excursion measured at 6 percent.",
    )
    assert_counters(
        fixtures.read_project(api, project_id), blocking_punch_count=1, posture=Posture.OPEN
    )

    verified = get_success_data(
        api.verify_punch_item(
            defect["id"],
            factories.verify_payload(
                verification_note="Gasket replaced and RH held at 50 +/- 1 percent over 72 hours."
            ),
            FABRICATION,
        ),
        200,
    )
    assert verified["status"] == PunchStatus.VERIFIED

    cleared = fixtures.read_project(api, project_id)
    assert_counters(cleared, blocking_punch_count=0, posture=Posture.OPEN)

    advanced = fixtures.advance(api, project_id, Phase.CLOSEOUT)
    assert advanced["phase"] == Phase.CLOSEOUT


def test_a_major_defect_never_moves_the_blocking_counter_nor_holds_the_advance(api):
    """Only BLOCKING severity participates in the gate.

    A major defect raised by the curator leaves the counter at zero, the posture
    OPEN and the step to CLOSEOUT available, and it is still standing OPEN once
    the commission has moved on.

    "`MuseumOperations`, a `Curator`, a `ProjectManager` or an `AccessibilitySpecialist` may raise one while the project is in `COMMISSIONING`, giving a `severity` of `BLOCKING`, `MAJOR` or `MINOR` and a `description` of 1 to 500 characters that must not be blank."
    "The counters are: `conservation_veto_count`, the number of veto votes cast by a `Conservator` across every round of the project; `conservation_block_count`, which is the number of the project's artifact cases in `REJECTED` status plus the number of its material specifications in `REJECTED` status plus `conservation_veto_count`; `open_revision_count`, the number of the project's design packages sitting in `REVISION_REQUESTED`; `conditional_case_count`, the number of its artifact cases in `CONDITIONALLY_APPROVED`; `pending_material_count`, the number of its material specifications whose status is `SUBMITTED` or `CONSERVATOR_REVIEW`; and `blocking_punch_count`, the number of its punch items whose severity is `BLOCKING` and whose status is still `OPEN`."
    "`COMMISSIONING → CLOSEOUT` requires `blocking_punch_count` to be 0, failing with `ERR_BLOCKING_PUNCH_ITEMS_OPEN` when a blocking defect is still open, and requires every interactive of the project to be `COMMISSIONED`."
    "The project-scoped punch list accepts `status` and `severity`; the global list accepts `project_id`, `interactive_id`, `case_id`, `status` and `severity`."
    Design: Corner/calculations/blocking_punch_items_gate_the_closeout_advance_without_ever_touching_the_posture
    """
    ctx = _commissioning_project_with_a_commissioned_station(api)
    project_id = ctx["project_id"]

    defect = fixtures.raise_punch_item(
        api,
        project_id,
        headers=CURATOR,
        severity=Severity.MAJOR,
        description="Docent bench laminate edge is lifting at the north end of the zone.",
    )
    assert defect["status"] == PunchStatus.OPEN

    loaded = fixtures.read_project(api, project_id)
    assert_counters(loaded, blocking_punch_count=0, posture=Posture.OPEN)

    advanced = fixtures.advance(api, project_id, Phase.CLOSEOUT)
    assert advanced["phase"] == Phase.CLOSEOUT

    rows, meta = validate_paginated(
        api.list_project_punch_items(project_id, PM, params={"status": PunchStatus.OPEN})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [defect["id"]]
    assert rows[0]["severity"] == Severity.MAJOR
