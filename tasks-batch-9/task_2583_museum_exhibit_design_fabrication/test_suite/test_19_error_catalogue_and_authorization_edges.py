"""Error-catalogue shape and authorization edges.

The first two tests pin what a refusal looks like — the envelope it carries and
the fact that it writes nothing — and the rest pin who may act: the exclusive
grants, the shared grants, the two identity comparisons that guard decisions,
the ordering of the identity and role gates against path resolution, and the
panel seating check that needs its round row first.

Every test builds its own preconditions against an empty database with the
logical clock at its documented default.
"""

from test_helpers import (
    ACCESSIBILITY,
    CONSERVATOR,
    CURATOR,
    ERR_CASE_HAS_NO_ARTIFACTS,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_PROJECT_PHASE,
    ERR_INVALID_REQUEST,
    ERR_ROUND_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VOTER_NOT_ON_PANEL,
    FABRICATION,
    LATE_CLOCK,
    NON_EXISTENT_UUID,
    NO_USER_ID_HEADER,
    OPERATIONS,
    PANEL_ELIGIBLE_ROLES,
    PM,
    PM_SECOND,
    ROLE_CONSERVATOR,
    ROLE_CURATOR,
    ROLE_MUSEUM_OPERATIONS,
    ROLE_PROJECT_MANAGER,
    USER_ACCESSIBILITY,
    USER_CURATOR,
    USER_FABRICATION,
    USER_OPERATIONS,
    USER_PM,
    USER_PM_SECOND,
    CaseDecision,
    CaseStatus,
    ComplexityTier,
    DrawingStatus,
    FinishGrade,
    InteractiveKind,
    InteractiveStatus,
    MaintenanceTier,
    MaterialStatus,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    PrototypeDecision,
    PunchStatus,
    RoundStatus,
    Severity,
    UsedIn,
    Verdict,
    VoteDecision,
    WindowStatus,
    WorkClass,
    assert_counters,
    assert_error_envelope_shape,
    assert_index,
    assert_ledger,
    assert_unchanged,
    assert_zone_slots,
    factories,
    fixtures,
    get_success_data,
    headers_for,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)


def _rows(response):
    """Validate a list envelope and return its rows."""
    validate_paginated(response)
    return response.json()["data"]


def _assert_page(response, total_count, has_more=False, limit=10, offset=0):
    """Pin the four pagination fields returned on every list response."""
    meta = response.json()["meta"]
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more
    assert meta["limit"] == limit
    assert meta["offset"] == offset


def _assert_at_clock(actual, instant):
    """Assert a stamped timestamp names the same UTC instant as the clock."""
    assert is_iso8601_timestamp(actual), actual
    assert actual[:19] == instant[:19], "%s does not stamp %s" % (actual, instant)


def _refusal(response, expected_error_id, expected_status):
    """Assert a refusal's id, status and the two-key envelope it carries."""
    validate_error(response, expected_error_id, expected_status)
    payload = assert_error_envelope_shape(response)
    assert payload["error_id"] == expected_error_id
    assert isinstance(payload["message"], str)
    assert payload["message"].strip() != ""
    return payload


def _role_only(role):
    """Headers that name a role but carry no operator identifier."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def test_the_error_envelope_carries_only_an_id_and_a_message(api):
    """Four refusals across four status families share one two-key envelope.

    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/the_error_envelope_carries_only_an_id_and_a_message_across_all_four_status_families
    """
    ctx = fixtures.project_in_phase(api, Phase.DESIGN_DEV)
    project_id = ctx["project_id"]

    malformed = api.create_artifact(
        project_id,
        factories.artifact_payload(
            accession_number="2021.02.9", condition_status="PRISTINE"
        ),
        CURATOR,
    )
    _refusal(malformed, ERR_INVALID_REQUEST, 400)

    unknown_round = api.cast_vote(
        NON_EXISTENT_UUID, factories.vote_payload(VoteDecision.APPROVE), CURATOR
    )
    _refusal(unknown_round, ERR_ROUND_NOT_FOUND, 404)

    duplicate_accession = api.create_artifact(
        project_id, factories.artifact_payload(accession_number="2019.14.3"), CURATOR
    )
    _refusal(duplicate_accession, ERR_DUPLICATE_CODE, 409)

    empty_case = api.submit_case_for_conservation(ctx["case_id"], CURATOR)
    _refusal(empty_case, ERR_CASE_HAS_NO_ARTIFACTS, 422)

    surviving = api.list_artifacts(project_id, CURATOR)
    assert [row["accession_number"] for row in _rows(surviving)] == ["2019.14.3"]
    _assert_page(surviving, total_count=1)

    untouched_case = get_success_data(api.get_artifact_case(ctx["case_id"], CURATOR), 200)
    assert untouched_case["status"] == CaseStatus.DRAFT
    assert untouched_case["placed_artifact_count"] == 0
    assert untouched_case["version"] == 1


def test_a_refused_settlement_leaves_no_version_bump_anywhere(api):
    """The refused closeout writes nothing: no bucket, no field, no version.

    "The project must be in `CLOSEOUT`; its `posture` must be exactly `OPEN`, so
    a `RESTRICTED` or `FROZEN_CONSERVATION` commission cannot be settled and
    answers `ERR_PROJECT_POSTURE_RESTRICTED`; and `committed_fabrication_cents`
    must be greater than zero, or there is nothing to settle and the request
    answers `ERR_NOTHING_TO_SETTLE` (HTTP 409)."

    "Resources that can be mutated after creation additionally carry an
    `updated_at` timestamp in the same format and an integer `version` that
    starts at 1 on creation and increments by exactly 1 on every mutation that
    touches the row — including mutations the caller did not ask for directly,
    such as a counter refreshed by a cascade."

    Design: Corner/errors/a_rejected_call_is_a_full_rollback_with_no_version_bump_anywhere
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    project_id = ctx["project_id"]
    case_id = ctx["case_id"]

    fixtures.place_artifact(api, case_id, ctx["artifact_id"])
    fixtures.approve_case(api, case_id)

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

    drawing = fixtures.create_drawing(
        api,
        project_id,
        housing["id"],
        drawing_number="SD-301",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=10.0,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
        subject_case_id=case_id,
    )
    approved_sheet = fixtures.approve_drawing(
        api, drawing["id"], actual_shop_hours=10.0, actual_waste_factor=1.0
    )
    assert approved_sheet["status"] == DrawingStatus.APPROVED
    assert approved_sheet["actual_labor_cents"] == 95000
    assert approved_sheet["actual_material_cents"] == 47500
    assert approved_sheet["actual_finishing_cents"] == 0
    assert approved_sheet["actual_cost_cents"] == 142500
    assert approved_sheet["version"] == 3

    before_project = fixtures.read_project(api, project_id)
    assert_counters(before_project, posture=Posture.OPEN)
    assert_ledger(before_project, 142500, 8857500)
    assert before_project["retainage_held_cents"] == 0
    assert before_project["warranty_reserve_cents"] == 0
    assert before_project["released_cents"] == 0
    assert before_project["parts_commitment_years"] == 0
    assert before_project["docent_kit_url"] is None
    assert before_project["maintenance_manual_url"] is None
    assert before_project["warranty_registered_at"] is None
    before_zone = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    before_case = get_success_data(api.get_artifact_case(case_id, PM), 200)
    before_sheet = get_success_data(api.get_shop_drawing(drawing["id"], PM), 200)

    refused = api.closeout(project_id, factories.closeout_payload(), PM)
    validate_error(refused, ERR_INVALID_PROJECT_PHASE, 409)

    after_project = fixtures.read_project(api, project_id)
    assert after_project["phase"] == Phase.FABRICATION
    assert_ledger(after_project, 142500, 8857500)
    assert after_project["retainage_held_cents"] == 0
    assert after_project["warranty_reserve_cents"] == 0
    assert after_project["released_cents"] == 0
    assert after_project["parts_commitment_years"] == 0
    assert after_project["docent_kit_url"] is None
    assert after_project["maintenance_manual_url"] is None
    assert after_project["warranty_registered_at"] is None
    assert_unchanged(
        before_project,
        after_project,
        [
            "version",
            "updated_at",
            "phase",
            "posture",
            "committed_fabrication_cents",
            "uncommitted_cents",
            "retainage_held_cents",
            "warranty_reserve_cents",
            "released_cents",
        ],
    )

    after_sheet = get_success_data(api.get_shop_drawing(drawing["id"], PM), 200)
    assert after_sheet["status"] == DrawingStatus.APPROVED
    assert after_sheet["actual_cost_cents"] == 142500
    assert after_sheet["version"] == 3
    assert_unchanged(
        before_sheet, after_sheet, ["status", "actual_cost_cents", "version", "updated_at"]
    )

    after_zone = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    assert_zone_slots(after_zone, 1, 1)
    assert_unchanged(
        before_zone,
        after_zone,
        ["reserved_case_slots", "available_case_slots", "version", "updated_at"],
    )

    after_case = get_success_data(api.get_artifact_case(case_id, PM), 200)
    assert after_case["status"] == CaseStatus.APPROVED
    assert_unchanged(before_case, after_case, ["status", "version", "updated_at"])


def test_every_role_drives_its_own_exclusive_operations_end_to_end(api):
    """One commission walks to fabrication on each role's own exclusive grants.

    "A `ProjectManager` owns the commission end to end: it opens the project,
    advances the phase, opens review rounds, rules on shop drawings and
    prototypes, sweeps lapsed review deadlines, waives non-blocking defects and
    settles closeout."

    "Either a `ProjectManager` or an `AccessibilitySpecialist` may author one,
    naming the `stage` as `SCHEMATIC` or `DESIGN_DEV` and carrying the
    `expected_project_version` demanded by §2.6."

    "`MuseumOperations` speaks for the operating museum: it owns the gallery
    calendar and rules on every install window, noise limit and closure request,
    and it does not sit on the review panel."

    Design: Corner/rbac/every_role_can_drive_its_own_exclusive_operations_end_to_end
    """
    fixtures.set_clock(api)
    project_id = fixtures.create_project(api)["id"]

    first_step = fixtures.advance(api, project_id, Phase.SCHEMATIC)
    assert first_step["phase"] == Phase.SCHEMATIC

    version_as_read_by_accessibility = fixtures.project_version(
        api, project_id, ACCESSIBILITY
    )
    package = get_success_data(
        api.create_design_package(
            project_id,
            factories.design_package_payload(
                version_as_read_by_accessibility, stage=PackageStage.SCHEMATIC
            ),
            ACCESSIBILITY,
        ),
        201,
    )
    assert package["status"] == PackageStatus.DRAFT
    assert package["submitted_by_user_id"] == USER_ACCESSIBILITY

    review_round = fixtures.open_round(
        api,
        package["id"],
        panel_roles=PANEL_ELIGIBLE_ROLES,
        decision_deadline_at="2026-08-20T00:00:00Z",
    )
    assert review_round["required_vote_count"] == 4
    fixtures.cast_vote(api, review_round["id"], CURATOR, VoteDecision.APPROVE)
    fixtures.cast_vote(api, review_round["id"], CONSERVATOR, VoteDecision.APPROVE)
    fixtures.cast_vote(api, review_round["id"], FABRICATION, VoteDecision.APPROVE)
    resolved = fixtures.cast_vote(api, review_round["id"], PM, VoteDecision.APPROVE)
    assert resolved["cast_vote_count"] == 4
    assert resolved["approve_count"] == 4
    assert resolved["status"] == RoundStatus.APPROVED

    second_step = fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    assert second_step["phase"] == Phase.DESIGN_DEV

    collection_object = fixtures.create_artifact(api, project_id, headers=CURATOR)
    zone = fixtures.create_zone(
        api, project_id, headers=OPERATIONS, closure_allowed=True
    )
    case = fixtures.create_case(api, project_id, zone["id"], headers=CURATOR)
    fixtures.place_artifact(api, case["id"], collection_object["id"], headers=CURATOR)
    fixtures.submit_case(api, case["id"], headers=CURATOR)
    ruled_case = fixtures.decide_case(
        api, case["id"], CaseDecision.APPROVE, CONSERVATOR
    )
    assert ruled_case["status"] == CaseStatus.APPROVED

    interactive = fixtures.create_interactive(api, project_id, headers=CURATOR)
    assert interactive["status"] == InteractiveStatus.SPECIFIED
    assert interactive["submitted_by_user_id"] == USER_CURATOR

    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    third_step = fixtures.advance(api, project_id, Phase.FABRICATION)
    assert third_step["phase"] == Phase.FABRICATION

    bench = get_success_data(
        api.submit_prototype(
            interactive["id"], factories.prototype_payload(60, 1500000), FABRICATION
        ),
        200,
    )
    assert bench["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert bench["submitted_by_user_id"] == USER_FABRICATION

    cleared_bench = get_success_data(
        api.prototype_decision(
            interactive["id"],
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    assert cleared_bench["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    built = get_success_data(api.mark_fabricated(interactive["id"], FABRICATION), 200)
    assert built["status"] == InteractiveStatus.FABRICATED

    housing = fixtures.create_material(
        api,
        project_id,
        headers=FABRICATION,
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    cleared_material = fixtures.approve_material(api, housing["id"])
    assert cleared_material["status"] == MaterialStatus.APPROVED

    sheet = fixtures.create_drawing(
        api,
        project_id,
        housing["id"],
        headers=FABRICATION,
        drawing_number="SD-901",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=8.0,
        material_area_m2=0.5,
        finish_grade=FinishGrade.MILL,
        subject_interactive_id=interactive["id"],
    )
    assert sheet["status"] == DrawingStatus.SUBMITTED
    assert sheet["submitted_by_user_id"] == USER_FABRICATION

    window = fixtures.create_window(
        api,
        project_id,
        zone["id"],
        headers=FABRICATION,
        work_class=WorkClass.QUIET,
        noise_dba=50.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
    )
    assert window["requested_by_user_id"] == USER_FABRICATION
    assert window["status"] == WindowStatus.REQUESTED

    calendared = fixtures.decide_window(api, window["id"], headers=OPERATIONS)
    assert calendared["status"] == WindowStatus.APPROVED


def test_each_shared_operation_accepts_either_of_its_declared_roles(api):
    """Six shared writes all land through their non-obvious role and stamp it.

    "The gallery is described as a set of zones, registered by either
    `MuseumOperations` or a `ProjectManager`."

    "A case is designed by a `ProjectManager` or a `Curator` and sited in a zone
    by naming its `zone_id`."

    "Placing an object into a case is done by a `Curator` or a `Conservator`, and
    the request names the `artifact_id` alongside the `expected_case_version` of
    §2.6."

    "A loaded case goes to the conservators for review, and either a
    `ProjectManager` or a `Curator` sends it."

    "A `FabricationLead` or a `Conservator` submits a material for screening,
    naming the proprietary `material_name` — 1 to 120 characters, unique among
    the project's materials — and the assembly it is proposed for in `used_in`,
    one of `CASE_INTERIOR`, `CASE_EXTERIOR`, `MOUNT`, `GRAPHIC` or
    `INTERACTIVE_HOUSING`."

    "Moving a material into review is done by a `FabricationLead` or a
    `ProjectManager`, and the status may be `SUBMITTED`, `REJECTED`, `APPROVED`
    or `CONDITIONAL`; anything else answers `ERR_INVALID_MATERIAL_STATE`."

    "An interactive is a hands-on station — a touchscreen, a crank-and-gear
    mechanism, a projection, an audio post or a headset rig — and either a
    `FabricationLead` or a `Curator` may specify one while the project is in
    `INTERPRETIVE`, `SCHEMATIC` or `DESIGN_DEV`."

    "Designing a case does **not** touch the zone's slot counters; a slot is only
    consumed when a conservator approves the case."

    Design: Corner/rbac/each_shared_operation_accepts_either_of_its_declared_roles
    """
    fixtures.set_clock(api)
    project_id = fixtures.create_project(api)["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    collection_object = fixtures.create_artifact(api, project_id, headers=CURATOR)

    zone = fixtures.create_zone(
        api, project_id, headers=PM, case_slot_capacity=4, closure_allowed=True
    )
    assert zone["case_slot_capacity"] == 4
    assert_zone_slots(zone, 0, 4)

    case = fixtures.create_case(api, project_id, zone["id"], headers=PM)
    assert case["status"] == CaseStatus.DRAFT

    reserved = fixtures.place_artifact(
        api, case["id"], collection_object["id"], headers=CONSERVATOR
    )
    assert reserved["placement_status"] == PlacementStatus.RESERVED
    assert reserved["assigned_case_id"] == case["id"]

    handed_over = fixtures.submit_case(api, case["id"], headers=PM)
    assert handed_over["status"] == CaseStatus.CONSERVATOR_REVIEW

    material = fixtures.create_material(
        api,
        project_id,
        headers=CONSERVATOR,
        material_name="Buffered museum board",
        used_in=UsedIn.CASE_INTERIOR,
        voc_mg_per_m2_day=0.04,
        formaldehyde_ppm=0.015,
        cure_days=25,
    )
    assert material["status"] == MaterialStatus.SUBMITTED
    assert material["verdict"] == Verdict.CONSERVATION_SAFE

    screening = get_success_data(
        api.submit_material_for_conservation(material["id"], PM), 200
    )
    assert screening["status"] == MaterialStatus.CONSERVATOR_REVIEW

    station = fixtures.create_interactive(
        api,
        project_id,
        headers=CURATOR,
        code="INT-EXT",
        kind=InteractiveKind.AUDIO,
        objective_code=factories.OBJECTIVE_SECONDARY,
        expected_daily_uses=40,
        duty_hours_per_day=4.0,
        mtbf_cycles=2000000,
    )
    assert station["status"] == InteractiveStatus.SPECIFIED
    assert station["submitted_by_user_id"] == USER_CURATOR

    zone_read_by_accessibility = get_success_data(
        api.get_gallery_zone(zone["id"], ACCESSIBILITY), 200
    )
    assert_zone_slots(zone_read_by_accessibility, 0, 4)
    assert zone_read_by_accessibility["version"] == 1

    case_read_by_operations = get_success_data(
        api.get_artifact_case(case["id"], OPERATIONS), 200
    )
    assert case_read_by_operations["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert case_read_by_operations["placed_artifact_count"] == 1


def test_the_prototype_and_window_decisions_compare_user_ids_not_roles(api):
    """The same shop identity is refused under both deciding roles, then cancels.

    "Five pairings are enforced, each rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403): the caller deciding a shop drawing may not be the caller stored
    in that drawing's `submitted_by_user_id`; the caller ruling on a prototype
    may not be the caller stored in that interactive's `submitted_by_user_id`;
    the caller verifying or waiving a punch item may not be the caller stored in
    that item's `raised_by_user_id`; the caller deciding an install window may
    not be the caller stored in that window's `requested_by_user_id`; and the
    caller casting a panel vote may not be the caller stored in the package's
    `submitted_by_user_id`."

    "The prototype ruling belongs to a `ProjectManager` or a `Conservator`,
    carries a `decision` of `APPROVE` or `REJECT` plus an optional `note`,
    requires status `PROTOTYPE_SUBMITTED`, requires the project not be frozen,
    and forbids the submitter from ruling on their own bench work."

    "Only `MuseumOperations` rules on a window, and the caller may not be the
    requester."

    "A window may also be cancelled by `MuseumOperations` or the
    `FabricationLead` from `REQUESTED` or `APPROVED`, with an optional
    `denial_reason`; it becomes `CANCELLED` and stops occupying its zone."

    Design: Corner/rbac/the_prototype_and_window_decisions_compare_user_ids_not_roles
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    interactive_id = ctx["interactive_id"]

    bench = get_success_data(
        api.submit_prototype(
            interactive_id, factories.prototype_payload(60, 1500000), FABRICATION
        ),
        200,
    )
    assert bench["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert bench["submitted_by_user_id"] == USER_FABRICATION

    shop_identity_as_manager = headers_for(ROLE_PROJECT_MANAGER, USER_FABRICATION)
    refused_as_manager = api.prototype_decision(
        interactive_id,
        factories.prototype_decision_payload(PrototypeDecision.APPROVE),
        shop_identity_as_manager,
    )
    validate_error(refused_as_manager, ERR_SEGREGATION_OF_DUTIES, 403)

    shop_identity_as_conservator = headers_for(ROLE_CONSERVATOR, USER_FABRICATION)
    refused_as_conservator = api.prototype_decision(
        interactive_id,
        factories.prototype_decision_payload(PrototypeDecision.APPROVE),
        shop_identity_as_conservator,
    )
    validate_error(refused_as_conservator, ERR_SEGREGATION_OF_DUTIES, 403)

    after_refusals = get_success_data(api.get_interactive(interactive_id, PM), 200)
    assert after_refusals["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert after_refusals["durability_index_verified"] is None
    assert_unchanged(
        bench,
        after_refusals,
        [
            "status",
            "version",
            "updated_at",
            "durability_index_verified",
            "prototype_iteration",
        ],
    )

    ruled = get_success_data(
        api.prototype_decision(
            interactive_id,
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    assert ruled["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    assert_index(ruled["durability_index_verified"], 87.58)
    assert ruled["maintenance_tier"] == MaintenanceTier.LOW

    window = fixtures.create_window(
        api,
        ctx["project_id"],
        ctx["zone_id"],
        headers=FABRICATION,
        work_class=WorkClass.QUIET,
        noise_dba=50.0,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
    )
    assert window["requested_by_user_id"] == USER_FABRICATION
    assert window["status"] == WindowStatus.REQUESTED

    shop_identity_as_operations = headers_for(ROLE_MUSEUM_OPERATIONS, USER_FABRICATION)
    refused_decision = api.window_decision(
        window["id"], factories.window_decision_payload(), shop_identity_as_operations
    )
    validate_error(refused_decision, ERR_SEGREGATION_OF_DUTIES, 403)

    still_requested = get_success_data(api.get_install_window(window["id"], PM), 200)
    assert still_requested["status"] == WindowStatus.REQUESTED
    assert still_requested["denial_reason"] is None
    assert_unchanged(
        window, still_requested, ["status", "version", "updated_at", "denial_reason"]
    )

    calendared = fixtures.decide_window(api, window["id"], headers=OPERATIONS)
    assert calendared["status"] == WindowStatus.APPROVED

    withdrawn = get_success_data(api.cancel_window(window["id"], FABRICATION), 200)
    assert withdrawn["status"] == WindowStatus.CANCELLED


def test_the_punch_verifier_may_never_be_the_person_who_raised_the_defect(api):
    """Verify and waive both compare the same stored raiser identity.

    "The item is stored `OPEN` with `raised_by_role` set from the caller's role
    header and `raised_by_user_id` from the caller, and a `BLOCKING` item
    increments the project's `blocking_punch_count`."

    "A `FabricationLead` or a `ProjectManager` verifies an `OPEN` item while the
    project is in `COMMISSIONING` or `CLOSEOUT`, supplying a
    `verification_note`; the caller may not be the person who raised it, the item
    becomes `VERIFIED`, `verified_by_user_id`, `verification_note` and
    `verified_at` are recorded, and a `BLOCKING` item decrements
    `blocking_punch_count`."

    "A waived item becomes `WAIVED` with its `waiver_reason` and `verified_at`
    recorded."

    Design: Corner/rbac/the_punch_verifier_may_never_be_the_person_who_raised_the_defect
    """
    ctx = fixtures.project_in_phase(api, Phase.COMMISSIONING)
    project_id = ctx["project_id"]

    lifting_vinyl = fixtures.raise_punch_item(
        api,
        project_id,
        headers=OPERATIONS,
        severity=Severity.MINOR,
        description="Vinyl lettering lifting along the lower edge of the intro panel.",
        case_id=ctx["case_id"],
    )
    assert lifting_vinyl["raised_by_user_id"] == USER_OPERATIONS
    assert lifting_vinyl["raised_by_role"] == ROLE_MUSEUM_OPERATIONS
    assert lifting_vinyl["status"] == PunchStatus.OPEN

    operations_identity_as_manager = headers_for(ROLE_PROJECT_MANAGER, USER_OPERATIONS)
    refused_verification = api.verify_punch_item(
        lifting_vinyl["id"],
        factories.verify_payload("Re-adhered and rolled."),
        operations_identity_as_manager,
    )
    validate_error(refused_verification, ERR_SEGREGATION_OF_DUTIES, 403)

    still_open = get_success_data(api.get_punch_item(lifting_vinyl["id"], PM), 200)
    assert still_open["status"] == PunchStatus.OPEN
    assert still_open["verified_by_user_id"] is None
    assert still_open["verified_at"] is None
    assert_unchanged(
        lifting_vinyl,
        still_open,
        ["status", "version", "updated_at", "verified_by_user_id", "verified_at"],
    )

    verified = get_success_data(
        api.verify_punch_item(
            lifting_vinyl["id"],
            factories.verify_payload("Re-adhered and rolled."),
            FABRICATION,
        ),
        200,
    )
    assert verified["status"] == PunchStatus.VERIFIED
    assert verified["verified_by_user_id"] == USER_FABRICATION
    assert verified["verification_note"] == "Re-adhered and rolled."
    _assert_at_clock(verified["verified_at"], LATE_CLOCK)

    lamp_colour = fixtures.raise_punch_item(
        api,
        project_id,
        headers=CURATOR,
        severity=Severity.MAJOR,
        description="Case interior lamp colour temperature reads warm against the specified 3000K.",
    )
    assert lamp_colour["raised_by_user_id"] == USER_CURATOR

    waiver_text = "Accepted by the curator as within tolerance for the opening."
    curator_identity_as_manager = headers_for(ROLE_PROJECT_MANAGER, USER_CURATOR)
    refused_waiver = api.waive_punch_item(
        lamp_colour["id"], factories.waive_payload(waiver_text), curator_identity_as_manager
    )
    validate_error(refused_waiver, ERR_SEGREGATION_OF_DUTIES, 403)

    waived = get_success_data(
        api.waive_punch_item(lamp_colour["id"], factories.waive_payload(waiver_text), PM),
        200,
    )
    assert waived["status"] == PunchStatus.WAIVED
    assert waived["waiver_reason"] == waiver_text
    _assert_at_clock(waived["verified_at"], LATE_CLOCK)

    bezel_gap = fixtures.raise_punch_item(
        api,
        project_id,
        headers=PM,
        severity=Severity.MINOR,
        description="Touchscreen bezel gap on the right hand side exceeds 2mm.",
    )
    assert bezel_gap["raised_by_user_id"] == USER_PM

    refused_self_verification = api.verify_punch_item(
        bezel_gap["id"], factories.verify_payload("Bezel shimmed."), PM
    )
    validate_error(refused_self_verification, ERR_SEGREGATION_OF_DUTIES, 403)

    refused_self_waiver = api.waive_punch_item(
        bezel_gap["id"], factories.waive_payload("Within shop tolerance."), PM
    )
    validate_error(refused_self_waiver, ERR_SEGREGATION_OF_DUTIES, 403)

    unclosable_by_its_author = get_success_data(
        api.get_punch_item(bezel_gap["id"], PM), 200
    )
    assert unclosable_by_its_author["status"] == PunchStatus.OPEN
    assert unclosable_by_its_author["verified_by_user_id"] is None
    assert unclosable_by_its_author["verified_at"] is None
    assert_unchanged(
        bezel_gap,
        unclosable_by_its_author,
        ["status", "version", "updated_at", "verified_by_user_id", "verified_at"],
    )


def test_the_role_gate_runs_before_the_path_is_resolved(api):
    """A forbidden role is refused with 403 even for identifiers that do not exist.

    "Authorisation is checked against the endpoint's permitted role list **before
    any path segment is resolved**, so a caller whose role is not permitted
    receives `ERR_UNAUTHORIZED` (HTTP 403) rather than a 404, and therefore cannot
    probe the API for the existence of an identifier it has no right to see."

    "If `X-User-Role` is absent or does not name one of the six roles below, or if
    `X-User-ID` is absent or blank on a mutating request, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    "Collection objects are registered by a `Curator` alone."

    "In the Authorized Role(s) column, "All roles" means all six of
    `ProjectManager`, `Curator`, `Conservator`, `AccessibilitySpecialist`,
    `FabricationLead` and `MuseumOperations`; every read endpoint is open to all
    six, and every write endpoint is restricted to the roles named."

    Design: Corner/rbac/the_role_gate_runs_before_the_path_is_resolved_and_the_identity_gate_runs_before_that
    """
    ctx = fixtures.project_in_phase(api, Phase.DESIGN_DEV)
    project_id = ctx["project_id"]
    case_id = ctx["case_id"]

    project_before = fixtures.read_project(api, project_id, PM)
    case_before = get_success_data(api.get_artifact_case(case_id, PM), 200)

    curator_advancing = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.FABRICATION), CURATOR
    )
    validate_error(curator_advancing, ERR_UNAUTHORIZED, 403)

    shop_ruling_on_a_case = api.case_conservator_decision(
        case_id, factories.case_decision_payload(CaseDecision.APPROVE), FABRICATION
    )
    validate_error(shop_ruling_on_a_case, ERR_UNAUTHORIZED, 403)

    shop_ruling_on_a_phantom_case = api.case_conservator_decision(
        NON_EXISTENT_UUID,
        factories.case_decision_payload(CaseDecision.APPROVE),
        FABRICATION,
    )
    validate_error(shop_ruling_on_a_phantom_case, ERR_UNAUTHORIZED, 403)

    operations_registering_an_object = api.create_artifact(
        project_id, factories.artifact_payload(accession_number="2019.14.9"), OPERATIONS
    )
    validate_error(operations_registering_an_object, ERR_UNAUTHORIZED, 403)

    operations_registering_into_a_phantom_project = api.create_artifact(
        NON_EXISTENT_UUID,
        factories.artifact_payload(accession_number="2019.14.9"),
        OPERATIONS,
    )
    validate_error(operations_registering_into_a_phantom_project, ERR_UNAUTHORIZED, 403)

    sweep_of_a_phantom_project = api.review_sweep(NON_EXISTENT_UUID, ACCESSIBILITY)
    validate_error(sweep_of_a_phantom_project, ERR_UNAUTHORIZED, 403)

    nameless_curator_registering_an_object = api.create_artifact(
        project_id,
        factories.artifact_payload(accession_number="2019.14.9"),
        NO_USER_ID_HEADER,
    )
    validate_error(nameless_curator_registering_an_object, ERR_UNAUTHENTICATED, 401)

    nameless_curator_advancing = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.FABRICATION), NO_USER_ID_HEADER
    )
    validate_error(nameless_curator_advancing, ERR_UNAUTHENTICATED, 401)

    project_after = fixtures.read_project(api, project_id, PM)
    assert project_after["phase"] == Phase.DESIGN_DEV
    assert_unchanged(
        project_before,
        project_after,
        ["phase", "version", "updated_at", "posture"],
    )
    case_after = get_success_data(api.get_artifact_case(case_id, PM), 200)
    assert case_after["status"] == CaseStatus.DRAFT
    assert_unchanged(case_before, case_after, ["status", "version", "updated_at"])

    read_without_an_operator_name = get_success_data(
        api.get_project(project_id, _role_only(ROLE_MUSEUM_OPERATIONS)), 200
    )
    assert read_without_an_operator_name["id"] == project_id
    assert read_without_an_operator_name["phase"] == Phase.DESIGN_DEV

    read_by_the_shop = get_success_data(api.get_artifact_case(case_id, FABRICATION), 200)
    assert read_by_the_shop["status"] == CaseStatus.DRAFT

    objects_seen_by_accessibility = api.list_artifacts(project_id, ACCESSIBILITY)
    rows = _rows(objects_seen_by_accessibility)
    assert [row["accession_number"] for row in rows] == ["2019.14.3"]
    _assert_page(objects_seen_by_accessibility, total_count=1)


def test_panel_membership_is_a_property_of_the_round(api):
    """Seating is checked per round, after existence, and only seated roles tally.

    "Each panelist casts exactly one vote, recording their `decision` as
    `APPROVE`, `REVISE` or `VETO` and optionally attaching a `comment` of up to
    500 characters, which is stored as null when omitted."

    "Four admission tests guard a vote, evaluated in the ladder order of §2.11:
    the caller may not be the author of the package under review, or the vote is
    refused with `ERR_SEGREGATION_OF_DUTIES`; the round must not already hold a
    vote from this caller — neither the same `voter_role` nor the same
    `voter_user_id` may appear twice, since one role votes once per round and no
    role may revise its position — or the vote is refused with
    `ERR_DUPLICATE_VOTE`; the caller's role must be seated on `panel_roles`, or
    the vote is refused with `ERR_VOTER_NOT_ON_PANEL`; and the round must still be
    `OPEN`, since a round that has reached `APPROVED`, `REVISION_REQUESTED`,
    `VETOED` or `CLOSED_SUPERSEDED` accepts nothing further and answers
    `ERR_INVALID_ROUND_STATE`."

    "5. Existence of every referenced row, path-supplied and body-supplied alike,
    in the order the eleven 404s are listed in §2.5."

    "8. Scoped uniqueness of human-authored codes (`ERR_DUPLICATE_CODE`), then
    single-instance constraints on votes and open rounds (`ERR_DUPLICATE_VOTE`,
    `ERR_ROUND_ALREADY_OPEN`), then panel seating (`ERR_VOTER_NOT_ON_PANEL`)."

    "The vote row is immutable: it captures the `round_id` it belongs to, the
    caller's `voter_role` and the caller's `voter_user_id`, and it is never
    edited."

    Design: Corner/rbac/panel_membership_is_a_property_of_the_round_and_is_checked_after_existence
    """
    ctx = fixtures.project_in_phase(api, Phase.SCHEMATIC)
    project_id = ctx["project_id"]

    package = fixtures.create_package(
        api, project_id, stage=PackageStage.SCHEMATIC, headers=PM
    )
    assert package["submitted_by_user_id"] == USER_PM

    seated_round = fixtures.open_round(
        api,
        package["id"],
        headers=PM,
        panel_roles=[ROLE_CURATOR, ROLE_CONSERVATOR, ROLE_PROJECT_MANAGER],
        decision_deadline_at="2026-08-20T08:00:00Z",
    )
    assert seated_round["panel_roles"] == [
        ROLE_CURATOR,
        ROLE_CONSERVATOR,
        ROLE_PROJECT_MANAGER,
    ]
    assert seated_round["required_vote_count"] == 2
    assert seated_round["status"] == RoundStatus.OPEN
    assert seated_round["cast_vote_count"] == 0

    unseated_accessibility = api.cast_vote(
        seated_round["id"], factories.vote_payload(VoteDecision.APPROVE), ACCESSIBILITY
    )
    validate_error(unseated_accessibility, ERR_VOTER_NOT_ON_PANEL, 403)

    unseated_shop = api.cast_vote(
        seated_round["id"], factories.vote_payload(VoteDecision.REVISE), FABRICATION
    )
    validate_error(unseated_shop, ERR_VOTER_NOT_ON_PANEL, 403)

    operations_never_sits = api.cast_vote(
        seated_round["id"], factories.vote_payload(VoteDecision.APPROVE), OPERATIONS
    )
    validate_error(operations_never_sits, ERR_UNAUTHORIZED, 403)

    vote_on_a_phantom_round = api.cast_vote(
        NON_EXISTENT_UUID, factories.vote_payload(VoteDecision.APPROVE), ACCESSIBILITY
    )
    validate_error(vote_on_a_phantom_round, ERR_ROUND_NOT_FOUND, 404)

    author_voting_on_their_own_package = api.cast_vote(
        seated_round["id"], factories.vote_payload(VoteDecision.APPROVE), PM
    )
    validate_error(author_voting_on_their_own_package, ERR_SEGREGATION_OF_DUTIES, 403)

    untallied = get_success_data(api.get_review_round(seated_round["id"], CURATOR), 200)
    assert untallied["cast_vote_count"] == 0
    assert untallied["approve_count"] == 0
    assert untallied["revise_count"] == 0
    assert untallied["veto_count"] == 0
    assert untallied["status"] == RoundStatus.OPEN
    assert untallied["decided_at"] is None
    assert_unchanged(
        seated_round,
        untallied,
        ["cast_vote_count", "approve_count", "status", "version", "updated_at"],
    )

    seated_other_manager = fixtures.cast_vote(
        api, seated_round["id"], PM_SECOND, VoteDecision.APPROVE
    )
    assert seated_other_manager["cast_vote_count"] == 1
    assert seated_other_manager["approve_count"] == 1
    assert seated_other_manager["status"] == RoundStatus.OPEN
    assert seated_other_manager["decided_at"] is None

    resolved = fixtures.cast_vote(
        api, seated_round["id"], CURATOR, VoteDecision.APPROVE
    )
    assert resolved["cast_vote_count"] == 2
    assert resolved["approve_count"] == 2
    assert resolved["cast_vote_count"] == resolved["required_vote_count"]
    assert resolved["status"] == RoundStatus.APPROVED
    _assert_at_clock(resolved["decided_at"], "2026-08-01T00:00:00Z")

    approved_package = get_success_data(
        api.get_design_package(package["id"], ACCESSIBILITY), 200
    )
    assert approved_package["status"] == PackageStatus.APPROVED

    ballots = api.list_votes(seated_round["id"], ACCESSIBILITY)
    rows = _rows(ballots)
    assert len(rows) == 2
    _assert_page(ballots, total_count=2)
    assert rows[0]["voter_role"] == ROLE_PROJECT_MANAGER
    assert rows[0]["voter_user_id"] == USER_PM_SECOND
    assert rows[0]["decision"] == VoteDecision.APPROVE
    assert rows[0]["round_id"] == seated_round["id"]
    assert rows[0]["comment"] is None
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]
    assert rows[1]["voter_role"] == ROLE_CURATOR
    assert rows[1]["voter_user_id"] == USER_CURATOR
