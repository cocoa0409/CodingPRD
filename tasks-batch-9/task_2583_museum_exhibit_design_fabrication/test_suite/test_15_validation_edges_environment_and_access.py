"""Edges of the scoped-code uniqueness rule, the shop-drawing compound key, the
review-panel composition rule and the install window's time range.

Every test builds its own preconditions through the documented endpoints: the
harness restarts the server before each test, so each one opens on an empty
database with the logical clock at its documented default instant.
"""

from test_helpers import (
    CURATOR,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_PANEL_COMPOSITION,
    ERR_INVALID_TIME_RANGE,
    FABRICATION,
    OBJECTIVE_PRIMARY,
    OBJECTIVE_SECONDARY,
    OPERATIONS,
    PM,
    USER_FABRICATION,
    ComplexityTier,
    DrawingStatus,
    FinishGrade,
    InteractiveKind,
    MaterialClass,
    OccupancyState,
    OddyResult,
    PackageStage,
    PackageStatus,
    Phase,
    RoundStatus,
    SecurityTier,
    UsedIn,
    WindowStatus,
    WorkClass,
    assert_zone_slots,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)

#: The material the interactive housings are built from. Its chamber numbers are
#: inside every INTERACTIVE_HOUSING limit, so it clears conservation outright.
HOUSING_MATERIAL = {
    "material_name": "Powder-coated aluminium housing",
    "used_in": UsedIn.INTERACTIVE_HOUSING,
    "oddy_test_result": OddyResult.PASS,
    "voc_mg_per_m2_day": 0.12,
    "formaldehyde_ppm": 0.02,
    "cure_days": 14,
}
#: The five panel roles the review rules declare eligible.
FULL_ELIGIBLE_PANEL = [
    "Curator",
    "Conservator",
    "ProjectManager",
    "AccessibilitySpecialist",
    "FabricationLead",
]
PANEL_DEADLINE = "2026-08-20T00:00:00Z"


def _design_dev_project_with_one_of_every_coded_child(api):
    """Walk a commission to DESIGN_DEV carrying one row of each coded entity.

    The zone, the collection object, the case, the two interactive stations and
    the screened material all carry human-authored codes, which is what the
    scoped-uniqueness probes collide with.
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id, headers=OPERATIONS, zone_code="Z-A")
    artifact = fixtures.create_artifact(
        api,
        project_id,
        accession_number="2019.14.3",
        material_class=MaterialClass.PAPER,
        security_class=SecurityTier.ENHANCED,
    )
    case = fixtures.create_case(
        api,
        project_id,
        zone["id"],
        headers=CURATOR,
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
    )
    station = fixtures.create_interactive(
        api,
        project_id,
        code="INT-STRATA",
        kind=InteractiveKind.TOUCHSCREEN,
        objective_code=OBJECTIVE_SECONDARY,
        expected_daily_uses=150,
        mtbf_cycles=1200000,
    )
    fixtures.create_interactive(
        api,
        project_id,
        code="INT-EXT",
        kind=InteractiveKind.AUDIO,
        objective_code=OBJECTIVE_PRIMARY,
        expected_daily_uses=40,
        duty_hours_per_day=4.0,
        mtbf_cycles=2000000,
    )
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    material = fixtures.create_material(api, project_id, **HOUSING_MATERIAL)
    fixtures.approve_material(api, material["id"])
    return {
        "project_id": project_id,
        "zone": zone,
        "artifact_id": artifact["id"],
        "case_id": case["id"],
        "station_id": station["id"],
        "material_id": material["id"],
    }


def _fabrication_project_with_an_approved_case_and_a_housing_material(api):
    """Walk a commission to FABRICATION with a loaded, approved case.

    The case holds one collection object and has been approved by a conservator,
    so it may be named as the subject of a shop drawing, and the housing
    material has cleared conservation so the sheet may be built from it.
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    fixtures.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fixtures.approve_case(api, ctx["case_id"])
    housing = fixtures.create_material(api, ctx["project_id"], **HOUSING_MATERIAL)
    fixtures.approve_material(api, housing["id"])
    ctx["housing_id"] = housing["id"]
    return ctx


def _schematic_project_with_a_draft_package(api):
    """Open a commission, walk it to SCHEMATIC and issue one design package."""
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    package = fixtures.create_package(api, project["id"], PackageStage.SCHEMATIC)
    return project["id"], package["id"]


def test_a_repeated_code_inside_one_commission_is_refused_on_every_coded_entity(api):
    """Five different entities, five different code fields, one error id.

    Each probe repeats a code that already exists in this commission while
    changing every other field it can, and the zone probe also moves to a free
    route ordinal so the collision can only be the code itself.

    "Scoped uniqueness of human-authored codes (`ERR_DUPLICATE_CODE`), then single-instance constraints on votes and open rounds (`ERR_DUPLICATE_VOTE`, `ERR_ROUND_ALREADY_OPEN`), then panel seating (`ERR_VOTER_NOT_ON_PANEL`)."
    "Each zone carries a `zone_code` of 1 to 40 characters that must be unique among the project's zones, and a `visitor_route_order` of at least 1 that places it on the interpretive walk and must likewise be unique among the project's zones — a collision on either is reported as `ERR_DUPLICATE_CODE` (HTTP 409), with codes compared case-sensitively and exactly."
    "Each carries an `accession_number` of 1 to 40 characters unique among the project's objects, a `material_class` of `ORGANIC`, `METAL`, `PAPER`, `TEXTILE` or `COMPOSITE` naming the dominant material that drives its conservation limits, and the conservation envelope the object itself demands: `required_rh_min_pct` and `required_rh_max_pct`, both strictly between 0 and 100 with the maximum strictly greater than the minimum, and `max_lux`, the highest illuminance it tolerates, which may be 0 or more."
    "It carries a `case_code` of 1 to 40 characters unique among the project's cases, and optionally an `objective_code` naming the learning objective it interprets — null when the case is purely architectural, and, when non-null, required to be one of the owning project's `objective_codes`; a code that is not a member of that array is a malformed request and answers `ERR_INVALID_REQUEST`."
    "The specification carries a `code` of 1 to 40 characters unique among the project's interactives, a `kind` of `TOUCHSCREEN`, `MECHANICAL`, `PROJECTION`, `AUDIO` or `AR_HEADSET`, and an `objective_code` that must be one of the strings in the project's `objective_codes` list, so no station exists outside the interpretive plan."
    "A `FabricationLead` or a `Conservator` submits a material for screening, naming the proprietary `material_name` — 1 to 120 characters, unique among the project's materials — and the assembly it is proposed for in `used_in`, one of `CASE_INTERIOR`, `CASE_EXTERIOR`, `MOUNT`, `GRAPHIC` or `INTERACTIVE_HOUSING`."
    Design: Corner/validations/every_scoped_unique_code_collides_only_inside_its_own_project_and_only_exactly
    """
    ctx = _design_dev_project_with_one_of_every_coded_child(api)
    project_id = ctx["project_id"]

    repeated_zone = api.create_gallery_zone(
        project_id,
        factories.gallery_zone_payload(
            zone_code="Z-A",
            visitor_route_order=7,
            max_noise_dba=70.0,
            case_slot_capacity=3,
        ),
        OPERATIONS,
    )
    validate_error(repeated_zone, ERR_DUPLICATE_CODE)

    repeated_object = api.create_artifact(
        project_id,
        factories.artifact_payload(
            accession_number="2019.14.3",
            material_class=MaterialClass.METAL,
            required_rh_min_pct=30.0,
            required_rh_max_pct=40.0,
            max_lux=200.0,
            security_class=SecurityTier.BASIC,
        ),
        CURATOR,
    )
    validate_error(repeated_object, ERR_DUPLICATE_CODE)

    repeated_case = api.create_artifact_case(
        project_id,
        factories.artifact_case_payload(
            ctx["zone"]["id"],
            case_code="C-01",
            objective_code=OBJECTIVE_SECONDARY,
            security_tier=SecurityTier.BASIC,
            target_rh_pct=45.0,
            rh_tolerance_pct=5.0,
            target_lux=100.0,
            uv_microwatt_per_lumen=10.0,
            interior_l_cm=50.0,
            interior_w_cm=50.0,
            interior_h_cm=50.0,
            air_exchanges_per_day=1.0,
        ),
        CURATOR,
    )
    validate_error(repeated_case, ERR_DUPLICATE_CODE)

    repeated_station = api.create_interactive(
        project_id,
        factories.interactive_payload(
            code="INT-STRATA",
            kind=InteractiveKind.MECHANICAL,
            objective_code=OBJECTIVE_SECONDARY,
            expected_daily_uses=20,
            duty_hours_per_day=2.0,
            mtbf_cycles=500000,
        ),
        FABRICATION,
    )
    validate_error(repeated_station, ERR_DUPLICATE_CODE)

    repeated_material = api.create_material_spec(
        project_id,
        factories.material_spec_payload(
            material_name="Powder-coated aluminium housing",
            used_in=UsedIn.GRAPHIC,
            oddy_test_result=OddyResult.PASS,
            voc_mg_per_m2_day=0.1,
            formaldehyde_ppm=0.01,
            cure_days=5,
        ),
        FABRICATION,
    )
    validate_error(repeated_material, ERR_DUPLICATE_CODE)


def test_a_lower_case_zone_code_is_a_different_code_in_the_same_commission(api):
    """Codes are compared exactly, so "z-a" does not collide with "Z-A".

    "Each zone carries a `zone_code` of 1 to 40 characters that must be unique among the project's zones, and a `visitor_route_order` of at least 1 that places it on the interpretive walk and must likewise be unique among the project's zones — a collision on either is reported as `ERR_DUPLICATE_CODE` (HTTP 409), with codes compared case-sensitively and exactly."
    "A new zone starts with `reserved_case_slots` at 0 and `available_case_slots` equal to its capacity, so the slot identity of §2.7 holds from creation, and with `occupancy_state` at `OPERATING`."
    Design: Corner/validations/every_scoped_unique_code_collides_only_inside_its_own_project_and_only_exactly
    """
    ctx = _design_dev_project_with_one_of_every_coded_child(api)

    lower = get_success_data(
        api.create_gallery_zone(
            ctx["project_id"],
            factories.gallery_zone_payload(
                zone_code="z-a",
                visitor_route_order=2,
                max_noise_dba=70.0,
                case_slot_capacity=3,
            ),
            OPERATIONS,
        ),
        201,
    )
    assert lower["zone_code"] == "z-a"
    assert_zone_slots(lower, reserved=0, available=3)


def test_a_second_commission_reuses_the_zone_code_of_the_first_verbatim(api):
    """The uniqueness scope is one commission, so a sibling project may repeat it.

    "Each zone carries a `zone_code` of 1 to 40 characters that must be unique among the project's zones, and a `visitor_route_order` of at least 1 that places it on the interpretive walk and must likewise be unique among the project's zones — a collision on either is reported as `ERR_DUPLICATE_CODE` (HTTP 409), with codes compared case-sensitively and exactly."
    "Gallery zones, collection objects and interactives may be registered only while the phase is `INTERPRETIVE`, `SCHEMATIC` or `DESIGN_DEV`."
    Design: Corner/validations/every_scoped_unique_code_collides_only_inside_its_own_project_and_only_exactly
    """
    _design_dev_project_with_one_of_every_coded_child(api)

    second = fixtures.create_project(
        api,
        name="Coastal Light",
        storyline_title="Coastal Light: Salt, Sand and Survival",
        objective_codes=["OBJ-TIDE", "OBJ-DUNE"],
        target_open_date="2027-11-01T00:00:00Z",
        contract_value_cents=4000000,
    )
    reused = get_success_data(
        api.create_gallery_zone(
            second["id"],
            factories.gallery_zone_payload(
                zone_code="Z-A",
                visitor_route_order=1,
                max_noise_dba=70.0,
                case_slot_capacity=3,
            ),
            OPERATIONS,
        ),
        201,
    )
    assert reused["zone_code"] == "Z-A"
    assert_zone_slots(reused, reserved=0, available=3)


def test_a_sheet_number_is_refused_only_at_a_revision_that_is_already_taken(api):
    """The sheet key is the pair, so the same number at a new revision is legal.

    The first sheet is issued at revision 1 and priced as a schematic estimate;
    a second sheet repeating the pair is refused however different its pricing
    inputs are, while the same number at revision 2 is accepted.

    "The sheet identifies itself with a `drawing_number` of 1 to 40 characters and an optional `revision` index of at least 1 that defaults to 1; the pair of number and revision must be unique among the project's drawings counting only sheets that are not `VOID`, so a voided sheet frees its number for re-issue at the same revision, and a collision answers `ERR_DUPLICATE_CODE`."
    "At issue it runs as a **schematic estimate**: the hours are the submitted `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and the waste factor is the schematic allowance of 1.20."
    "Labour is the hours multiplied by the shop rate for the sheet's complexity tier multiplied by a labour multiplier: the shop charges 95 dollars per hour at `STANDARD`, 145 dollars per hour at `PRECISION` and 185 dollars per hour at `CONSERVATION_GRADE`, recorded as 9,500, 14,500 and 18,500 cents per hour respectively."
    "Material is the `material_area_m2` multiplied by the rate for the **material's** `used_in` assembly multiplied by a waste factor, where the rates per square metre are 42,500 cents for `CASE_INTERIOR`, 31,000 for `CASE_EXTERIOR`, 58,000 for `MOUNT`, 12,500 for `GRAPHIC` and 47,500 for `INTERACTIVE_HOUSING`."
    "Finishing is a percentage of the **already-rounded** material line item — 0 percent for `MILL`, 7.5 percent for `SATIN` and 13.5 percent for `MUSEUM_GLOSS` — and it too is rounded to whole cents."
    "The total is the plain sum of the three rounded line items."
    Design: Corner/validations/a_voided_shop_drawing_frees_its_number_and_revision_pair_for_re_issue
    """
    ctx = _fabrication_project_with_an_approved_case_and_a_housing_material(api)

    first = fixtures.create_drawing(
        api,
        ctx["project_id"],
        ctx["housing_id"],
        drawing_number="SD-601",
        revision=1,
        subject_case_id=ctx["case_id"],
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=10.0,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
    )
    assert first["drawing_number"] == "SD-601"
    assert first["revision"] == 1
    assert first["estimate_total_cents"] == 166250
    assert first["status"] == DrawingStatus.SUBMITTED

    collision = api.create_shop_drawing(
        factories.shop_drawing_payload(
            ctx["project_id"],
            ctx["housing_id"],
            drawing_number="SD-601",
            revision=1,
            subject_case_id=ctx["case_id"],
            complexity_tier=ComplexityTier.PRECISION,
            shop_hours=4.0,
            material_area_m2=0.5,
            finish_grade=FinishGrade.SATIN,
        ),
        FABRICATION,
    )
    validate_error(collision, ERR_DUPLICATE_CODE)

    next_revision = fixtures.create_drawing(
        api,
        ctx["project_id"],
        ctx["housing_id"],
        drawing_number="SD-601",
        revision=2,
        subject_case_id=ctx["case_id"],
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=10.0,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
    )
    assert next_revision["drawing_number"] == "SD-601"
    assert next_revision["revision"] == 2


def test_voiding_a_sheet_frees_its_number_and_revision_for_re_issue(api):
    """A void takes the pair out of the uniqueness set entirely.

    The voided sheet was still `SUBMITTED`, so no money moves and the case it
    detailed is left alone, and the pair it occupied is re-issued at the same
    revision with the shop's revised hours.

    "The sheet identifies itself with a `drawing_number` of 1 to 40 characters and an optional `revision` index of at least 1 that defaults to 1; the pair of number and revision must be unique among the project's drawings counting only sheets that are not `VOID`, so a voided sheet frees its number for re-issue at the same revision, and a collision answers `ERR_DUPLICATE_CODE`."
    "A sheet in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED` or `APPROVED_AS_NOTED` becomes `VOID`; a sheet that is already `VOID` cannot be voided again and answers `ERR_INVALID_DRAWING_STATE`, and neither can a `REJECTED` one."
    "Voiding a sheet still in `SUBMITTED` or `UNDER_REVIEW` moves no money and reverts no case."
    "At issue it runs as a **schematic estimate**: the hours are the submitted `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and the waste factor is the schematic allowance of 1.20."
    "The total is the plain sum of the three rounded line items."
    "The project-scoped list accepts a `status` filter; the global list accepts any combination of `project_id`, `material_spec_id`, `subject_case_id`, `subject_interactive_id` and `status`, and is the reverse-lookup channel from a case or an interactive back to the sheets that detail it."
    Design: Corner/validations/a_voided_shop_drawing_frees_its_number_and_revision_pair_for_re_issue
    """
    ctx = _fabrication_project_with_an_approved_case_and_a_housing_material(api)
    sheet_fields = dict(
        drawing_number="SD-601",
        subject_case_id=ctx["case_id"],
        complexity_tier=ComplexityTier.STANDARD,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
    )

    first = fixtures.create_drawing(
        api, ctx["project_id"], ctx["housing_id"], revision=1, shop_hours=10.0, **sheet_fields
    )
    second = fixtures.create_drawing(
        api, ctx["project_id"], ctx["housing_id"], revision=2, shop_hours=10.0, **sheet_fields
    )

    voided = get_success_data(
        api.void_drawing(
            first["id"],
            factories.void_payload(
                void_reason="Superseded by a re-drawn sheet at the same revision after the plinth detail changed."
            ),
            FABRICATION,
        ),
        200,
    )
    assert voided["status"] == DrawingStatus.VOID

    reissued = fixtures.create_drawing(
        api, ctx["project_id"], ctx["housing_id"], revision=1, shop_hours=12.0, **sheet_fields
    )
    assert reissued["revision"] == 1
    assert reissued["drawing_number"] == "SD-601"
    assert reissued["estimate_total_cents"] == 188100

    rows, meta = validate_paginated(
        api.list_shop_drawings(
            PM,
            params={"project_id": ctx["project_id"], "status": DrawingStatus.SUBMITTED},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [second["id"], reissued["id"]]
    assert [row["drawing_number"] for row in rows] == ["SD-601", "SD-601"]
    assert [row["revision"] for row in rows] == [2, 1]


def test_four_malformed_panels_are_refused_by_the_one_composition_rule(api):
    """Too small, duplicated, ineligible and veto-less panels all fail alike.

    Each probe breaks exactly one clause of the seating rule while satisfying
    the others as far as it can, so the single error id is reached four
    different ways.

    "A panel must have between 3 and 5 entries with no duplicates, every entry drawn from `Curator`, `Conservator`, `ProjectManager`, `AccessibilitySpecialist` and `FabricationLead`, and it must include both `Curator` and `Conservator`, because those two hold the veto; any other composition is rejected with `ERR_INVALID_PANEL_COMPOSITION` (HTTP 422)."
    "`MuseumOperations` speaks for the operating museum: it owns the gallery calendar and rules on every install window, noise limit and closure request, and it does not sit on the review panel."
    Design: Corner/validations/the_review_panel_composition_rule_rejects_four_distinct_malformations
    """
    project_id, package_id = _schematic_project_with_a_draft_package(api)

    too_small = api.create_review_round(
        package_id,
        factories.review_round_payload(
            panel_roles=["Curator", "Conservator"], decision_deadline_at=PANEL_DEADLINE
        ),
        PM,
    )
    validate_error(too_small, ERR_INVALID_PANEL_COMPOSITION)

    duplicated = api.create_review_round(
        package_id,
        factories.review_round_payload(
            panel_roles=["Curator", "Curator", "Conservator"],
            decision_deadline_at=PANEL_DEADLINE,
        ),
        PM,
    )
    validate_error(duplicated, ERR_INVALID_PANEL_COMPOSITION)

    ineligible = api.create_review_round(
        package_id,
        factories.review_round_payload(
            panel_roles=["Curator", "Conservator", "MuseumOperations"],
            decision_deadline_at=PANEL_DEADLINE,
        ),
        PM,
    )
    validate_error(ineligible, ERR_INVALID_PANEL_COMPOSITION)

    missing_veto = api.create_review_round(
        package_id,
        factories.review_round_payload(
            panel_roles=["Curator", "ProjectManager", "FabricationLead"],
            decision_deadline_at=PANEL_DEADLINE,
        ),
        PM,
    )
    validate_error(missing_veto, ERR_INVALID_PANEL_COMPOSITION)

    rows, meta = validate_paginated(api.list_review_rounds(package_id, PM))
    assert meta["total_count"] == 0
    assert rows == []


def test_the_widest_legal_panel_seats_five_roles_and_needs_four_votes(api):
    """Five eligible roles is the maximum, and its quorum is four votes.

    "A panel must have between 3 and 5 entries with no duplicates, every entry drawn from `Curator`, `Conservator`, `ProjectManager`, `AccessibilitySpecialist` and `FabricationLead`, and it must include both `Curator` and `Conservator`, because those two hold the veto; any other composition is rejected with `ERR_INVALID_PANEL_COMPOSITION` (HTTP 422)."
    "The new round records the package it reviews through its `package_id` and takes a `round_number` equal to the package's `review_round_count` plus one, so rounds are numbered from 1 within each package."
    "Its `required_vote_count` is the quorum: two thirds of the seated panel, rounded **up** to a whole vote."
    "A panel of three therefore needs 2 votes, a panel of four needs 3, and a panel of five needs 4."
    "The round opens with `status` `OPEN`, with `cast_vote_count`, `approve_count`, `revise_count` and `veto_count` all 0, with `swept_by_deadline` false and `decided_at` null."
    "The package's `review_round_count` is incremented and the package moves from `DRAFT` or `REVISION_REQUESTED` into `IN_REVIEW`; the project's `open_revision_count` and posture are recomputed, and the package's and project's `version` values each advance by one."
    "A round's list channel accepts a `status` filter, and a single round can be read back with its live tallies and its quorum target."
    Design: Corner/validations/the_review_panel_composition_rule_rejects_four_distinct_malformations
    """
    project_id, package_id = _schematic_project_with_a_draft_package(api)

    opened = get_success_data(
        api.create_review_round(
            package_id,
            factories.review_round_payload(
                panel_roles=FULL_ELIGIBLE_PANEL, decision_deadline_at=PANEL_DEADLINE
            ),
            PM,
        ),
        201,
    )
    assert opened["package_id"] == package_id
    assert opened["round_number"] == 1
    assert opened["required_vote_count"] == 4
    assert opened["status"] == RoundStatus.OPEN
    assert opened["cast_vote_count"] == 0
    assert opened["approve_count"] == 0
    assert opened["revise_count"] == 0
    assert opened["veto_count"] == 0
    assert opened["swept_by_deadline"] is False
    assert opened["decided_at"] is None
    assert len(opened["panel_roles"]) == 5
    assert sorted(opened["panel_roles"]) == sorted(FULL_ELIGIBLE_PANEL)

    package = get_success_data(api.get_design_package(package_id, PM), 200)
    assert package["status"] == PackageStatus.IN_REVIEW
    assert package["review_round_count"] == 1

    rows, meta = validate_paginated(
        api.list_review_rounds(package_id, PM, params={"status": RoundStatus.OPEN})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [opened["id"]]
    assert rows[0]["required_vote_count"] == 4


def test_a_window_that_ends_when_or_before_it_starts_is_refused(api):
    """The nominal end must be strictly later, so equal and inverted both fail.

    "The `ends_at` must be strictly after the `starts_at`, and a zero-length or inverted range answers `ERR_INVALID_TIME_RANGE` (HTTP 422)."
    "The project-scoped and zone-scoped window lists accept `status`, and the project-scoped list also accepts `zone_id` and `requires_gallery_closure`."
    Design: Corner/validations/a_zero_length_install_window_is_rejected_and_one_minute_is_enough
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)

    zero_length = api.create_install_window(
        factories.install_window_payload(
            ctx["project_id"],
            ctx["zone_id"],
            work_class=WorkClass.QUIET,
            noise_dba=50.0,
            starts_at="2026-09-10T09:00:00Z",
            ends_at="2026-09-10T09:00:00Z",
        ),
        FABRICATION,
    )
    validate_error(zero_length, ERR_INVALID_TIME_RANGE)

    inverted = api.create_install_window(
        factories.install_window_payload(
            ctx["project_id"],
            ctx["zone_id"],
            work_class=WorkClass.QUIET,
            noise_dba=50.0,
            starts_at="2026-09-10T12:00:00Z",
            ends_at="2026-09-10T09:00:00Z",
        ),
        FABRICATION,
    )
    validate_error(inverted, ERR_INVALID_TIME_RANGE)

    rows, meta = validate_paginated(
        api.list_project_install_windows(ctx["project_id"], PM)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_one_minute_quiet_window_is_accepted_with_no_buffers_at_all(api):
    """One minute of separation is enough, and quiet work spreads no further.

    Both buffers of quiet work are zero, so the effective instants the calendar
    reasons about are exactly the nominal ones, and the request leaves the
    gallery open.

    "The `ends_at` must be strictly after the `starts_at`, and a zero-length or inverted range answers `ERR_INVALID_TIME_RANGE` (HTTP 422)."
    "The window is stored at status `REQUESTED` with `requested_by_user_id` from the caller and `denial_reason` null."
    "The `pre_access_buffer_minutes` — the time the crew needs to protect objects and lay down floor covering before the nominal start — is 0 for `QUIET`, 15 for `NOISY`, 30 for `DUST_GENERATING` and 45 for `CRANE_ACCESS`."
    "The `settling_buffer_minutes` — the time airborne dust and noise need to clear before visitors return — is 0 for `QUIET`, 30 for `NOISY`, 120 for `DUST_GENERATING` and 60 for `CRANE_ACCESS`, except that for `DUST_GENERATING` work the buffer is the **larger** of that 120-minute floor and the zone's own `dust_settling_buffer_minutes`, so a zone with a slow air exchange lengthens the window it hosts."
    "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."
    "Requesting a window does not change the zone's `occupancy_state` — the gallery stays open until work actually starts — but a merely `REQUESTED` window already occupies the zone for conflict purposes, so the first request in a slot blocks the second even before anyone approves it."
    "The project-scoped and zone-scoped window lists accept `status`, and the project-scoped list also accepts `zone_id` and `requires_gallery_closure`."
    Design: Corner/validations/a_zero_length_install_window_is_rejected_and_one_minute_is_enough
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)

    window = get_success_data(
        api.create_install_window(
            factories.install_window_payload(
                ctx["project_id"],
                ctx["zone_id"],
                work_class=WorkClass.QUIET,
                noise_dba=50.0,
                starts_at="2026-09-10T09:00:00Z",
                ends_at="2026-09-10T09:01:00Z",
            ),
            FABRICATION,
        ),
        201,
    )
    assert window["status"] == WindowStatus.REQUESTED
    assert window["requested_by_user_id"] == USER_FABRICATION
    assert window["denial_reason"] is None
    assert window["requires_gallery_closure"] is False
    assert window["pre_access_buffer_minutes"] == 0
    assert window["settling_buffer_minutes"] == 0
    assert is_iso8601_timestamp(window["effective_start_at"])
    assert is_iso8601_timestamp(window["effective_end_at"])
    assert window["effective_start_at"].startswith("2026-09-10T09:00:00")
    assert window["effective_end_at"].startswith("2026-09-10T09:01:00")

    zone = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    assert zone["occupancy_state"] == OccupancyState.OPERATING

    rows, meta = validate_paginated(
        api.list_project_install_windows(
            ctx["project_id"], PM, params={"zone_id": ctx["zone_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [window["id"]]
    assert rows[0]["status"] == WindowStatus.REQUESTED
