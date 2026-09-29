"""Initial states, phase gating and terminal states of the commission machines.

These tests pin the state every machine is born in, the estimate-only figures a
new shop drawing and a new install window carry, the punch item's walk from OPEN
through verification and waiver to the CLOSED it only reaches at settlement, the
refusal of any phase target that is not the immediate successor, and the
terminality of a settled commission.
"""

from test_helpers import (
    CONSERVATOR,
    ERR_BLOCKING_PUNCH_ITEMS_OPEN,
    ERR_INVALID_PROJECT_PHASE,
    ERR_INVALID_PUNCH_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    FABRICATION,
    OPERATIONS,
    PM,
    USER_FABRICATION,
    USER_OPERATIONS,
    USER_PM,
    CaseStatus,
    DrawingStatus,
    InteractiveStatus,
    MaintenanceTier,
    MaterialStatus,
    MountStatus,
    OccupancyState,
    OddyResult,
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
    WindowStatus,
    WorkClass,
    assert_counters,
    assert_index,
    assert_ledger,
    assert_money_identity,
    assert_zone_slots,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant the install and commissioning stages run at, reached by moving the
#: logical clock forward once the calendar work begins.
INSTALL_CLOCK = fixtures.LATE_CLOCK


def _commission_ready_for_punch_list(api):
    """Drive one commission to COMMISSIONING with its single station commissioned.

    Every step is a real call in the order the PRD's admission tests allow: the
    prototype is bench-tested and marked built while the project is still in
    FABRICATION, the loaded case is approved and detailed by an approved sheet,
    the mount is walked to installed inside an approved window, and the window is
    completed before the advance to COMMISSIONING.
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id)
    artifact = fixtures.create_artifact(api, project_id)
    interactive = fixtures.create_interactive(api, project_id)
    case = fixtures.create_case(api, project_id, zone["id"])

    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fixtures.advance(api, project_id, Phase.FABRICATION)

    material = fixtures.create_material(api, project_id)
    fixtures.approve_material(api, material["id"])

    get_success_data(
        api.submit_prototype(interactive["id"], factories.prototype_payload(), FABRICATION),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive["id"],
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    get_success_data(api.mark_fabricated(interactive["id"], FABRICATION), 200)

    fixtures.place_artifact(api, case["id"], artifact["id"])
    fixtures.approve_case(api, case["id"])
    drawing = fixtures.create_drawing(
        api, project_id, material["id"], subject_case_id=case["id"]
    )
    fixtures.approve_drawing(api, drawing["id"])

    fixtures.advance_mount(api, case["id"], MountStatus.MOUNT_DESIGN)
    fixtures.advance_mount(api, case["id"], MountStatus.MOUNT_FABRICATED)
    window = fixtures.create_window(
        api,
        project_id,
        zone["id"],
        starts_at="2026-09-09T09:00:00Z",
        ends_at="2026-09-09T12:00:00Z",
    )
    fixtures.decide_window(api, window["id"])

    fixtures.advance(api, project_id, Phase.INSTALLATION)
    fixtures.set_clock(api, INSTALL_CLOCK)
    fixtures.start_window(api, window["id"])
    fixtures.advance_mount(api, case["id"], MountStatus.MOUNT_INSTALLED)
    fixtures.complete_window(api, window["id"])
    fixtures.advance(api, project_id, Phase.COMMISSIONING)
    get_success_data(
        api.commission_interactive(interactive["id"], factories.commission_payload(), PM),
        200,
    )
    return {
        "project_id": project_id,
        "zone_id": zone["id"],
        "case_id": case["id"],
        "artifact_id": artifact["id"],
        "interactive_id": interactive["id"],
        "material_id": material["id"],
        "drawing_id": drawing["id"],
        "window_id": window["id"],
    }


def test_every_pre_fabrication_machine_starts_in_its_declared_initial_state(api):
    """A commission and each child registered before fabrication report the exact
    initial state the PRD declares for them: the project interpretive and open, the
    package a draft with no rounds, the round open with four zero tallies, the zone
    operating with an empty slot pool, the object unplaced, the case a draft with
    no mount work, and the station specified with only its catalogue index.

    "The new project opens in phase `INTERPRETIVE` at `version` 1, with `created_by_user_id` taken from the caller's header."
    "The round opens with `status` `OPEN`, with `cast_vote_count`, `approve_count`, `revise_count` and `veto_count` all 0, with `swept_by_deadline` false and `decided_at` null."
    "A new zone starts with `reserved_case_slots` at 0 and `available_case_slots` equal to its capacity, so the slot identity of §2.7 holds from creation, and with `occupancy_state` at `OPERATING`."
    "Every object begins `UNPLACED` with `assigned_case_id` null, and its `placement_status` walks `UNPLACED`, `RESERVED`, `PLACED` and the terminal `DEINSTALLED`."
    "The case is stored with `status` `DRAFT`, `mount_status` `NOT_STARTED`, `placed_artifact_count` 0, `conditions` null and `decided_at` null."
    "The new row is stored at status `SPECIFIED` with `prototype_iteration` zero, `submitted_by_user_id` from the caller, and `durability_index_verified`, `measured_daily_uses` and `measured_mtbf_cycles` all null."

    Design: Corner/state_machines/all_eight_pre_fabrication_machines_start_in_their_declared_initial_state
    """
    fixtures.set_clock(api)

    project = fixtures.create_project(api)
    project_id = project["id"]
    assert project["phase"] == Phase.INTERPRETIVE
    assert project["posture"] == Posture.OPEN
    assert project["version"] == 1

    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    package = fixtures.create_package(api, project_id, stage=PackageStage.SCHEMATIC)
    assert package["status"] == PackageStatus.DRAFT
    assert package["review_round_count"] == 0
    assert package["revision_count"] == 0
    assert package["approved_at"] is None
    assert package["superseded_by_package_id"] is None
    assert package["submitted_by_user_id"] == USER_PM
    assert package["version"] == 1

    review_round = fixtures.open_round(
        api,
        package["id"],
        panel_roles=["Curator", "Conservator", "FabricationLead"],
        decision_deadline_at=fixtures.FAR_DEADLINE,
    )
    assert review_round["status"] == RoundStatus.OPEN
    assert review_round["round_number"] == 1
    assert review_round["required_vote_count"] == 2
    assert review_round["cast_vote_count"] == 0
    assert review_round["approve_count"] == 0
    assert review_round["revise_count"] == 0
    assert review_round["veto_count"] == 0
    assert review_round["swept_by_deadline"] is False
    assert review_round["decided_at"] is None

    package_in_review = validate_success(api.get_design_package(package["id"], PM))
    assert package_in_review["status"] == PackageStatus.IN_REVIEW
    assert package_in_review["review_round_count"] == 1

    zone = fixtures.create_zone(api, project_id)
    assert zone["occupancy_state"] == OccupancyState.OPERATING
    assert_zone_slots(zone, reserved=0, available=2)
    assert zone["version"] == 1

    artifact = fixtures.create_artifact(api, project_id)
    assert artifact["placement_status"] == PlacementStatus.UNPLACED
    assert artifact["assigned_case_id"] is None
    assert artifact["version"] == 1

    case = fixtures.create_case(api, project_id, zone["id"])
    assert case["status"] == CaseStatus.DRAFT
    assert case["mount_status"] == MountStatus.NOT_STARTED
    assert case["placed_artifact_count"] == 0
    assert case["conditions"] is None
    assert case["decided_at"] is None
    assert case["version"] == 1

    interactive = fixtures.create_interactive(
        api,
        project_id,
        expected_daily_uses=150,
        duty_hours_per_day=6.0,
        mtbf_cycles=1200000,
        parts_availability_years=10,
        warranty_months=24,
    )
    assert interactive["status"] == InteractiveStatus.SPECIFIED
    assert interactive["prototype_iteration"] == 0
    assert interactive["submitted_by_user_id"] == USER_FABRICATION
    assert interactive["measured_daily_uses"] is None
    assert interactive["measured_mtbf_cycles"] is None
    assert interactive["durability_index_verified"] is None
    assert_index(interactive["durability_index_spec"], 70.60)
    assert interactive["maintenance_tier"] == MaintenanceTier.MEDIUM
    assert interactive["version"] == 1


def test_a_screened_material_starts_submitted_and_makes_the_commission_restricted(api):
    """A material lands in SUBMITTED with its verdict already derived from the
    assembly it is proposed for, with no conservator ruling recorded, and its
    arrival alone lifts the pending-material counter and moves an otherwise clean
    commission to RESTRICTED.

    "A freshly submitted material lands in `SUBMITTED` status with its verdict already computed, its `conditions` null and its `decided_at` null."
    "That alone raises the project's `pending_material_count` and is enough to make an otherwise clean project `RESTRICTED`, and it increments the project's `version`."
    "Failing that, it is `CONSERVATION_SAFE` if its Oddy class is exactly `PASS` **and** its VOC rate is at most the ceiling **and** its formaldehyde concentration is at most the ceiling **and** its `cure_days` is at least the minimum."

    Design: Corner/state_machines/all_eight_pre_fabrication_machines_start_in_their_declared_initial_state
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    before = fixtures.read_project(api, project_id)
    assert before["posture"] == Posture.OPEN

    material = fixtures.create_material(
        api,
        project_id,
        material_name="Baltic Birch Housing Panel",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        oddy_test_result=OddyResult.PASS,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    assert material["status"] == MaterialStatus.SUBMITTED
    assert material["verdict"] == Verdict.CONSERVATION_SAFE
    assert material["conditions"] is None
    assert material["decided_at"] is None
    assert material["version"] == 1

    after = fixtures.read_project(api, project_id)
    assert_counters(
        after,
        pending_material_count=1,
        conservation_block_count=0,
        open_revision_count=0,
        conditional_case_count=0,
    )
    assert after["posture"] == Posture.RESTRICTED
    assert after["version"] == before["version"] + 1


def test_a_new_shop_drawing_starts_submitted_with_only_its_estimate_filled(api):
    """A sheet issued against an approved case and an approved material opens in
    SUBMITTED with every actual figure still null, carries the three separately
    rounded estimate line items and their plain sum, and moves no money.

    "The sheet is stored in `SUBMITTED` status with `submitted_by_user_id` from the caller's header, `void_reason` null, and every actual figure — `actual_shop_hours`, `actual_waste_factor`, `actual_labor_cents`, `actual_material_cents`, `actual_finishing_cents` and `actual_cost_cents` — still null."
    "The three results land in `estimate_labor_cents`, `estimate_material_cents` and `estimate_finishing_cents`, with `estimate_total_cents` as their sum, and **no money moves** — the estimate is advisory."
    "At issue it runs as a **schematic estimate**: the hours are the submitted `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and the waste factor is the schematic allowance of 1.20."

    Design: Corner/state_machines/shop_drawing_and_install_window_start_in_submitted_and_requested_with_only_estimates_filled
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    project_id = ctx["project_id"]
    fixtures.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fixtures.approve_case(api, ctx["case_id"])
    housing = fixtures.create_material(
        api,
        project_id,
        material_name="Baltic Birch Housing Panel",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        oddy_test_result=OddyResult.PASS,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    fixtures.approve_material(api, housing["id"])

    drawing = validate_success(
        api.create_shop_drawing(
            factories.shop_drawing_payload(
                project_id,
                housing["id"],
                drawing_number="SD-601",
                subject_case_id=ctx["case_id"],
                shop_hours=10.0,
                material_area_m2=1.0,
            ),
            FABRICATION,
        ),
        201,
    )

    assert drawing["status"] == DrawingStatus.SUBMITTED
    assert drawing["submitted_by_user_id"] == USER_FABRICATION
    assert drawing["void_reason"] is None
    assert drawing["revision"] == 1
    assert drawing["version"] == 1
    assert drawing["subject_case_id"] == ctx["case_id"]
    assert drawing["subject_interactive_id"] is None

    assert drawing["estimate_labor_cents"] == 109250
    assert drawing["estimate_material_cents"] == 57000
    assert drawing["estimate_finishing_cents"] == 0
    assert drawing["estimate_total_cents"] == 166250

    for actual_field in (
        "actual_shop_hours",
        "actual_waste_factor",
        "actual_labor_cents",
        "actual_material_cents",
        "actual_finishing_cents",
        "actual_cost_cents",
    ):
        assert drawing[actual_field] is None, (
            "%s must still be null on a freshly issued sheet" % actual_field
        )

    project = fixtures.read_project(api, project_id)
    assert_ledger(project, committed=0, uncommitted=9000000)


def test_a_new_install_window_starts_requested_and_leaves_the_gallery_open(api):
    """A QUIET window opens at REQUESTED with no denial recorded and effective
    instants identical to the nominal ones, and requesting it leaves the zone
    operating with its slot split untouched.

    "The window is stored at status `REQUESTED` with `requested_by_user_id` from the caller and `denial_reason` null."
    "Requesting a window does not change the zone's `occupancy_state` — the gallery stays open until work actually starts — but a merely `REQUESTED` window already occupies the zone for conflict purposes, so the first request in a slot blocks the second even before anyone approves it."
    "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."

    Design: Corner/state_machines/shop_drawing_and_install_window_start_in_submitted_and_requested_with_only_estimates_filled
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    fixtures.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fixtures.approve_case(api, ctx["case_id"])

    window = validate_success(
        api.create_install_window(
            factories.install_window_payload(
                ctx["project_id"],
                ctx["zone_id"],
                work_class=WorkClass.QUIET,
                noise_dba=50.0,
                starts_at="2026-09-10T09:00:00Z",
                ends_at="2026-09-10T12:00:00Z",
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
    assert window["effective_start_at"] == window["starts_at"]
    assert window["effective_end_at"] == window["ends_at"]
    assert window["version"] == 1

    zone = validate_success(api.get_gallery_zone(ctx["zone_id"], PM))
    assert zone["occupancy_state"] == OccupancyState.OPERATING
    assert_zone_slots(zone, reserved=1, available=1)

    windows, meta = validate_paginated(
        api.list_zone_install_windows(ctx["zone_id"], PM)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in windows] == [window["id"]]


def test_a_blocking_defect_cannot_be_waived_and_never_by_the_person_who_raised_it(api):
    """A blocking defect raised in commissioning lifts the blocking counter without
    touching posture, refuses a waiver outright, refuses verification by its own
    author, is verified once by someone else, and refuses a second verification.

    "The item is stored `OPEN` with `raised_by_role` set from the caller's role header and `raised_by_user_id` from the caller, and a `BLOCKING` item increments the project's `blocking_punch_count`."
    "A `FabricationLead` or a `ProjectManager` verifies an `OPEN` item while the project is in `COMMISSIONING` or `CLOSEOUT`, supplying a `verification_note`; the caller may not be the person who raised it, the item becomes `VERIFIED`, `verified_by_user_id`, `verification_note` and `verified_at` are recorded, and a `BLOCKING` item decrements `blocking_punch_count`."
    "A `ProjectManager` waives an `OPEN` item with a `waiver_reason`, again while the project is in `COMMISSIONING` or `CLOSEOUT`, but only when the severity is `MAJOR` or `MINOR`: **a `BLOCKING` defect can never be waived** and the attempt answers `ERR_INVALID_PUNCH_STATE`, which is also the answer when the item is not `OPEN`."
    "A waived item becomes `WAIVED` with its `waiver_reason` and `verified_at` recorded."

    Design: Corner/state_machines/the_punch_item_runs_open_to_verified_and_waived_and_only_closes_at_settlement
    """
    ctx = _commission_ready_for_punch_list(api)
    project_id = ctx["project_id"]

    blocking = fixtures.raise_punch_item(
        api,
        project_id,
        severity=Severity.BLOCKING,
        description="Vitrine gasket torn at the mullion",
    )
    assert blocking["status"] == PunchStatus.OPEN
    assert blocking["raised_by_role"] == "MuseumOperations"
    assert blocking["raised_by_user_id"] == USER_OPERATIONS
    assert blocking["verified_at"] is None

    major = fixtures.raise_punch_item(
        api,
        project_id,
        severity=Severity.MAJOR,
        description="Graphic panel edge lifting",
    )
    self_raised = validate_success(
        api.create_punch_item(
            project_id,
            factories.punch_item_payload(
                severity=Severity.MINOR, description="Label typo on the plinth"
            ),
            PM,
        ),
        201,
    )
    assert self_raised["raised_by_user_id"] == USER_PM

    with_blocking = fixtures.read_project(api, project_id)
    assert with_blocking["blocking_punch_count"] == 1
    assert with_blocking["posture"] == Posture.OPEN

    validate_error(
        api.waive_punch_item(blocking["id"], factories.waive_payload(), PM),
        ERR_INVALID_PUNCH_STATE,
        409,
    )
    validate_error(
        api.verify_punch_item(self_raised["id"], factories.verify_payload(), PM),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    verified = validate_success(
        api.verify_punch_item(
            blocking["id"],
            factories.verify_payload(verification_note="Gasket replaced and inspected"),
            FABRICATION,
        )
    )
    assert verified["status"] == PunchStatus.VERIFIED
    assert verified["verified_by_user_id"] == USER_FABRICATION
    assert verified["verification_note"] == "Gasket replaced and inspected"
    assert is_iso8601_timestamp(verified["verified_at"])
    assert verified["verified_at"].startswith("2026-09-10T08:00:00")

    validate_error(
        api.verify_punch_item(blocking["id"], factories.verify_payload(), FABRICATION),
        ERR_INVALID_PUNCH_STATE,
        409,
    )

    waived = validate_success(
        api.waive_punch_item(
            major["id"],
            factories.waive_payload(waiver_reason="Cosmetic only; accepted by the museum"),
            PM,
        )
    )
    assert waived["status"] == PunchStatus.WAIVED
    assert waived["waiver_reason"] == "Cosmetic only; accepted by the museum"
    assert is_iso8601_timestamp(waived["verified_at"])

    cleared = fixtures.read_project(api, project_id)
    assert cleared["blocking_punch_count"] == 0
    assert cleared["posture"] == Posture.OPEN


def test_settlement_closes_verified_and_waived_defects_and_leaves_open_ones(api):
    """A blocking defect holds the advance out of commissioning until it is
    verified; settlement then closes the verified and the waived item and leaves an
    untouched item exactly as it was.

    "`COMMISSIONING → CLOSEOUT` requires `blocking_punch_count` to be 0, failing with `ERR_BLOCKING_PUNCH_ITEMS_OPEN` when a blocking defect is still open, and requires every interactive of the project to be `COMMISSIONED`."
    "The handover fields `docent_kit_url`, `maintenance_manual_url` and `parts_commitment_years` are stored, `warranty_registered_at` is stamped with the current logical clock instant, and every punch item standing at `VERIFIED` or `WAIVED` is transitioned to `CLOSED` — items still `OPEN` are left alone, which is why a project carrying a blocking defect cannot have reached this phase in the first place."

    Design: Corner/state_machines/the_punch_item_runs_open_to_verified_and_waived_and_only_closes_at_settlement
    """
    ctx = _commission_ready_for_punch_list(api)
    project_id = ctx["project_id"]

    blocking = fixtures.raise_punch_item(
        api,
        project_id,
        severity=Severity.BLOCKING,
        description="Vitrine gasket torn at the mullion",
    )
    major = fixtures.raise_punch_item(
        api,
        project_id,
        severity=Severity.MAJOR,
        description="Graphic panel edge lifting",
    )
    untouched = fixtures.raise_punch_item(
        api,
        project_id,
        severity=Severity.MINOR,
        description="Label typo on the plinth",
    )

    validate_error(
        api.advance_phase(
            project_id, factories.advance_phase_payload(Phase.CLOSEOUT), PM
        ),
        ERR_BLOCKING_PUNCH_ITEMS_OPEN,
        409,
    )

    validate_success(
        api.verify_punch_item(blocking["id"], factories.verify_payload(), FABRICATION)
    )
    validate_success(api.waive_punch_item(major["id"], factories.waive_payload(), PM))

    in_closeout = fixtures.advance(api, project_id, Phase.CLOSEOUT)
    assert in_closeout["phase"] == Phase.CLOSEOUT

    settled = fixtures.settle_project(api, project_id)
    assert settled["phase"] == Phase.WARRANTY_CLOSED

    closed_after_verification = validate_success(api.get_punch_item(blocking["id"], PM))
    assert closed_after_verification["status"] == PunchStatus.CLOSED
    closed_after_waiver = validate_success(api.get_punch_item(major["id"], PM))
    assert closed_after_waiver["status"] == PunchStatus.CLOSED
    still_open = validate_success(api.get_punch_item(untouched["id"], PM))
    assert still_open["status"] == PunchStatus.OPEN
    assert still_open["verified_at"] is None


def test_advance_phase_refuses_every_target_that_is_not_the_immediate_successor(api):
    """Naming a phase that is two steps ahead, the terminal phase, the phase already
    stored, or a phase behind the stored one is refused, and each refusal leaves the
    stored phase and version exactly as they were; only the immediate successor is
    accepted.

    "The project's `phase` walks a ladder of eight values — `INTERPRETIVE`, `SCHEMATIC`, `DESIGN_DEV`, `FABRICATION`, `INSTALLATION`, `COMMISSIONING`, `CLOSEOUT` and finally the terminal `WARRANTY_CLOSED`."
    "A `ProjectManager` advances it one step at a time by naming the destination in `to_phase`; if the named destination is not the immediate successor of the phase currently stored, the request is refused with `ERR_INVALID_PROJECT_PHASE`."
    "Whatever the step, a successful advance refreshes the project's `updated_at`, increments its `version` by one, and recomputes posture."

    Design: Corner/state_machines/advance_phase_rejects_every_target_that_is_not_the_immediate_successor
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]

    for target in (Phase.DESIGN_DEV, Phase.WARRANTY_CLOSED, Phase.INTERPRETIVE):
        validate_error(
            api.advance_phase(
                project_id, factories.advance_phase_payload(target), PM
            ),
            ERR_INVALID_PROJECT_PHASE,
            409,
        )

    untouched = fixtures.read_project(api, project_id)
    assert untouched["phase"] == Phase.INTERPRETIVE
    assert untouched["version"] == 1

    advanced = fixtures.advance(api, project_id, Phase.SCHEMATIC)
    assert advanced["phase"] == Phase.SCHEMATIC
    assert advanced["version"] == 2

    for target in (Phase.INTERPRETIVE, Phase.SCHEMATIC, Phase.FABRICATION):
        validate_error(
            api.advance_phase(
                project_id, factories.advance_phase_payload(target), PM
            ),
            ERR_INVALID_PROJECT_PHASE,
            409,
        )

    final = fixtures.read_project(api, project_id)
    assert final["phase"] == Phase.SCHEMATIC
    assert final["version"] == 2


def test_children_of_a_later_phase_are_refused_for_the_phase_not_their_own_state(api):
    """A sheet, a commissioning, a punch item and a settlement all attempted from
    SCHEMATIC are refused for the project's phase, even though each request also
    names a child whose own state would refuse it and the commission has no money
    to settle, because phase is read above resource state and above the money.

    "Phase also decides which children may be created at all, and a mismatch is `ERR_INVALID_PROJECT_PHASE`."
    "Shop drawings may be issued and decided only in `FABRICATION`, though taking an already-submitted sheet into review is permitted in either `DESIGN_DEV` or `FABRICATION`."
    "Punch items may be raised, and interactives commissioned, only in `COMMISSIONING`."
    "Settlement requires `CLOSEOUT`."
    "14. Fiscal capacity last of all (`ERR_FABRICATION_BUDGET_EXCEEDED`, `ERR_NOTHING_TO_SETTLE`). Because money is checked last, a request that also violates a conservation or constraint rule never reports a budget error."

    Design: Corner/state_machines/advance_phase_rejects_every_target_that_is_not_the_immediate_successor
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id)
    case = fixtures.create_case(api, project_id, zone["id"])
    interactive = fixtures.create_interactive(api, project_id)
    material = fixtures.create_material(api, project_id)
    fixtures.approve_material(api, material["id"])

    validate_error(
        api.create_shop_drawing(
            factories.shop_drawing_payload(
                project_id, material["id"], subject_case_id=case["id"]
            ),
            FABRICATION,
        ),
        ERR_INVALID_PROJECT_PHASE,
        409,
    )
    validate_error(
        api.commission_interactive(
            interactive["id"], factories.commission_payload(), PM
        ),
        ERR_INVALID_PROJECT_PHASE,
        409,
    )
    validate_error(
        api.create_punch_item(
            project_id, factories.punch_item_payload(), OPERATIONS
        ),
        ERR_INVALID_PROJECT_PHASE,
        409,
    )
    validate_error(
        api.closeout(project_id, factories.closeout_payload(), PM),
        ERR_INVALID_PROJECT_PHASE,
        409,
    )

    unchanged = fixtures.read_project(api, project_id)
    assert unchanged["phase"] == Phase.SCHEMATIC
    assert unchanged["posture"] == Posture.OPEN
    assert unchanged["warranty_registered_at"] is None
    assert unchanged["parts_commitment_years"] == 0
    assert_ledger(unchanged, committed=0, uncommitted=9000000)
    stored_case = validate_success(api.get_artifact_case(case["id"], PM))
    assert stored_case["status"] == CaseStatus.DRAFT
    stored_interactive = validate_success(api.get_interactive(interactive["id"], PM))
    assert stored_interactive["status"] == InteractiveStatus.SPECIFIED


def test_a_settled_commission_is_terminal_and_refuses_a_further_advance(api):
    """Settlement stamps the handover fields, zeroes the committed bucket and leaves
    the commission in its terminal phase; a further advance and a second settlement
    are both refused for the phase, and neither overwrites what settlement wrote.

    "Finally the phase advances from `CLOSEOUT` to `WARRANTY_CLOSED` and the project's `version` is incremented by one."
    "`WARRANTY_CLOSED` is terminal: nothing further may be written to the commission."
    "The `committed_fabrication_cents` bucket is zeroed, and `uncommitted_cents` is recomputed as the `contract_value_cents` less the sum of the three settlement figures, so the five-bucket ledger still reconciles exactly after settlement."
    "The final step to `WARRANTY_CLOSED` is not an advance at all but the settlement operation described in §3.9."

    Design: Corner/state_machines/the_four_terminal_states_reached_at_settlement_accept_no_further_trigger
    """
    ctx = _commission_ready_for_punch_list(api)
    project_id = ctx["project_id"]
    defect = fixtures.raise_punch_item(
        api, project_id, severity=Severity.MINOR, description="Label typo on the plinth"
    )
    validate_success(
        api.verify_punch_item(defect["id"], factories.verify_payload(), FABRICATION)
    )
    fixtures.advance(api, project_id, Phase.CLOSEOUT)

    before = fixtures.read_project(api, project_id)
    assert before["committed_fabrication_cents"] > 0

    settled = fixtures.settle_project(api, project_id, parts_commitment_years=10)
    assert settled["phase"] == Phase.WARRANTY_CLOSED
    assert settled["committed_fabrication_cents"] == 0
    assert settled["parts_commitment_years"] == 10
    assert is_iso8601_timestamp(settled["warranty_registered_at"])
    assert settled["warranty_registered_at"].startswith("2026-09-10T08:00:00")
    assert_money_identity(settled)

    validate_error(
        api.advance_phase(
            project_id, factories.advance_phase_payload(Phase.WARRANTY_CLOSED), PM
        ),
        ERR_INVALID_PROJECT_PHASE,
        409,
    )
    validate_error(
        api.closeout(
            project_id, factories.closeout_payload(parts_commitment_years=3), PM
        ),
        ERR_INVALID_PROJECT_PHASE,
        409,
    )

    after = fixtures.read_project(api, project_id)
    assert after["phase"] == Phase.WARRANTY_CLOSED
    assert after["parts_commitment_years"] == 10
    assert after["warranty_registered_at"] == settled["warranty_registered_at"]
    assert after["version"] == settled["version"]
    assert after["committed_fabrication_cents"] == 0
