"""Cascades that fire link by link: material rejection, review veto, window completion.

Each test builds its own commission out of the endpoints the PRD declares, so it
opens against an empty database with the logical clock at its documented default
of 2026-08-01T00:00:00Z and never depends on another test having run.
"""

from test_helpers import (
    CONSERVATOR,
    CURATOR,
    DESIGN_REVISION_REOPENED,
    ERR_MOUNT_NOT_INSTALLED,
    FABRICATION,
    MATERIAL_SPEC_REJECTED,
    OPERATIONS,
    PM,
    OBJECTIVE_PRIMARY,
    OBJECTIVE_SECONDARY,
    CaseStatus,
    DrawingStatus,
    MaterialClass,
    MaterialDecision,
    MaterialStatus,
    MountStatus,
    OccupancyState,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    RoundStatus,
    SecurityTier,
    VoteDecision,
    WindowStatus,
    assert_counters,
    assert_empty_envelope,
    assert_envelope,
    assert_ledger,
    assert_unchanged,
    assert_zone_slots,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

#: Nominal spans for the install calendar, both QUIET so every buffer is zero.
DAY_ONE_START = "2026-09-10T08:00:00Z"
DAY_ONE_END = "2026-09-10T10:00:00Z"
DAY_TWO_START = "2026-09-11T08:00:00Z"
DAY_TWO_END = "2026-09-11T10:00:00Z"


def _commission_with_a_committed_sheet_and_a_reserved_slot(api):
    """A commission in FABRICATION whose only sheet committed 137500 cents.

    The case holds one reserved object, stands APPROVED with a zone slot
    reserved and its mount at MOUNT_FABRICATED, and the material the sheet was
    built from has been re-submitted for screening because a new production lot
    arrived, so it sits in CONSERVATOR_REVIEW with the sheet still APPROVED.
    """
    ctx = fx.project_in_phase(api, Phase.FABRICATION)
    fx.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fx.approve_case(api, ctx["case_id"])
    drawing = fx.create_drawing(
        api,
        ctx["project_id"],
        ctx["material_id"],
        drawing_number="SD-301",
        subject_case_id=ctx["case_id"],
    )
    fx.approve_drawing(
        api, drawing["id"], actual_shop_hours=10.0, actual_waste_factor=1.0
    )
    fx.advance_mount(api, ctx["case_id"], MountStatus.MOUNT_DESIGN)
    fx.advance_mount(api, ctx["case_id"], MountStatus.MOUNT_FABRICATED)
    get_success_data(
        api.submit_material_for_conservation(ctx["material_id"], FABRICATION), 200
    )
    ctx["drawing_id"] = drawing["id"]
    return ctx


def _reject_material(api, material_id):
    return get_success_data(
        api.material_conservator_decision(
            material_id,
            f.material_decision_payload(MaterialDecision.REJECT),
            CONSERVATOR,
        ),
        200,
    )


# ---------------------------------------------------------------------------
# A rejected material spec: four links from the sheet to the zone slot ledger
# ---------------------------------------------------------------------------
def test_material_rejection_voids_the_sheet_and_returns_every_committed_cent(api):
    """A rejection voids the sheet built from the material and releases its money.

    The sheet stood at APPROVED with 137500 cents of actual cost committed, so
    exactly that amount travels back from committed to uncommitted while the
    voided sheet keeps the figure it committed on the record.

    PRD section 3.6: "Every shop drawing built from this material that is not already `VOID` or `REJECTED` — that is, every sheet in `SUBMITTED`, `UNDER_REVIEW`, `APPROVED` or `APPROVED_AS_NOTED` — transitions to `VOID` with its `void_reason` set to the literal string `MATERIAL_SPEC_REJECTED`."

    PRD section 3.6: "Each voided sheet that had actually committed money — one that stood at `APPROVED` or `APPROVED_AS_NOTED` and therefore carries a non-null `actual_cost_cents` — releases exactly that amount from the project's `committed_fabrication_cents` back into `uncommitted_cents`."

    Design: Difficulty/transitive_cascade/material_rejection_cascades_four_links_to_the_ledger_and_the_zone_slot_ledger
    """
    ctx = _commission_with_a_committed_sheet_and_a_reserved_slot(api)
    before = fx.read_project(api, ctx["project_id"])
    assert_ledger(before, committed=137500, uncommitted=8862500)

    material = _reject_material(api, ctx["material_id"])
    assert material["status"] == MaterialStatus.REJECTED

    sheet = get_success_data(api.get_shop_drawing(ctx["drawing_id"], PM), 200)
    assert sheet["status"] == DrawingStatus.VOID
    assert sheet["void_reason"] == MATERIAL_SPEC_REJECTED
    assert sheet["actual_cost_cents"] == 137500

    after = fx.read_project(api, ctx["project_id"])
    assert_ledger(after, committed=0, uncommitted=9000000)


def test_material_rejection_reverts_the_subject_case_and_unwinds_its_mount(api):
    """The voided sheet drags its subject case back to DRAFT and the mount with it.

    The case stood APPROVED with its mount already fabricated; once the sheet
    that detailed it is void the case has no approved documentation left, so it
    returns to DRAFT and the mount falls back one step to MOUNT_DESIGN.

    PRD section 3.6: "Each voided sheet that names a `subject_case_id` whose case stands at `APPROVED` or `CONDITIONALLY_APPROVED` sends that case back to `DRAFT`."

    PRD section 3.6: "The case gives up the zone slot it reserved at approval — `reserved_case_slots` falls by one and `available_case_slots` rises by one on its zone — its stored `conditions` is cleared, and a `mount_status` of `MOUNT_FABRICATED` falls back to `MOUNT_DESIGN`."

    Design: Difficulty/transitive_cascade/material_rejection_cascades_four_links_to_the_ledger_and_the_zone_slot_ledger
    """
    ctx = _commission_with_a_committed_sheet_and_a_reserved_slot(api)
    before = get_success_data(api.get_artifact_case(ctx["case_id"], PM), 200)
    assert before["status"] == CaseStatus.APPROVED
    assert before["mount_status"] == MountStatus.MOUNT_FABRICATED

    _reject_material(api, ctx["material_id"])

    case = get_success_data(api.get_artifact_case(ctx["case_id"], PM), 200)
    assert case["status"] == CaseStatus.DRAFT
    assert case["mount_status"] == MountStatus.MOUNT_DESIGN
    assert case["conditions"] is None


def test_material_rejection_empties_the_reverted_case_of_its_reserved_object(api):
    """The fourth link releases the object the reverted case was holding.

    The reservation dies with the case approval: the object returns to UNPLACED
    with no case assigned, and the case's derived envelope goes back to the null
    bounds an empty case reports.

    PRD section 3.6: "Each reverted case releases its contents: every object in it whose `placement_status` is `RESERVED` returns to `UNPLACED` with `assigned_case_id` cleared, the case's `placed_artifact_count` is zeroed and its derived envelope limits return to null bounds."

    Design: Difficulty/transitive_cascade/material_rejection_cascades_four_links_to_the_ledger_and_the_zone_slot_ledger
    """
    ctx = _commission_with_a_committed_sheet_and_a_reserved_slot(api)
    loaded = get_success_data(api.get_artifact_case(ctx["case_id"], PM), 200)
    assert_envelope(loaded, placed_artifact_count=1, allowed_lux=50.0, env_feasible=True)

    _reject_material(api, ctx["material_id"])

    case = get_success_data(api.get_artifact_case(ctx["case_id"], PM), 200)
    assert_empty_envelope(case)

    artifact = get_success_data(api.get_artifact(ctx["artifact_id"], CURATOR), 200)
    assert artifact["placement_status"] == PlacementStatus.UNPLACED
    assert artifact["assigned_case_id"] is None


def test_material_rejection_frees_the_zone_slot_and_freezes_the_commission(api):
    """The zone slot returns, the rejection freezes the project, and every touched row moves one version.

    The released slot restores the zone to its full capacity, the rejection
    itself is the project's only conservation block so posture becomes
    FROZEN_CONSERVATION, the material stops counting as pending, and each row
    the cascade walked through advances its version by exactly one.

    PRD section 3.6: "The zone's `available_case_slots` is recomputed, the project's `conservation_block_count` rises by one for the rejection itself, and posture therefore becomes `FROZEN_CONSERVATION`."

    PRD section 3.6: "Every row the cascade touched — the material, each voided drawing, each reverted case, each released object, each zone whose slot count moved, and the project — has its `updated_at` refreshed and its `version` incremented by exactly one."

    Design: Difficulty/transitive_cascade/material_rejection_cascades_four_links_to_the_ledger_and_the_zone_slot_ledger
    """
    ctx = _commission_with_a_committed_sheet_and_a_reserved_slot(api)
    zone_before = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    assert_zone_slots(zone_before, reserved=1, available=1)
    project_before = fx.read_project(api, ctx["project_id"])
    case_before = get_success_data(api.get_artifact_case(ctx["case_id"], PM), 200)
    artifact_before = get_success_data(api.get_artifact(ctx["artifact_id"], CURATOR), 200)
    sheet_before = get_success_data(api.get_shop_drawing(ctx["drawing_id"], PM), 200)

    _reject_material(api, ctx["material_id"])

    zone = get_success_data(api.get_gallery_zone(ctx["zone_id"], PM), 200)
    assert_zone_slots(zone, reserved=0, available=2)
    assert zone["available_case_slots"] == zone["case_slot_capacity"]

    project = fx.read_project(api, ctx["project_id"])
    assert_counters(
        project,
        conservation_block_count=1,
        pending_material_count=0,
        conditional_case_count=0,
        open_revision_count=0,
        posture=Posture.FROZEN_CONSERVATION,
    )

    case = get_success_data(api.get_artifact_case(ctx["case_id"], PM), 200)
    artifact = get_success_data(api.get_artifact(ctx["artifact_id"], CURATOR), 200)
    sheet = get_success_data(api.get_shop_drawing(ctx["drawing_id"], PM), 200)
    assert project["version"] == project_before["version"] + 1
    assert zone["version"] == zone_before["version"] + 1
    assert case["version"] == case_before["version"] + 1
    assert artifact["version"] == artifact_before["version"] + 1
    assert sheet["version"] == sheet_before["version"] + 1


# ---------------------------------------------------------------------------
# A curator veto: round, package, phase revert, selective window denials
# ---------------------------------------------------------------------------
def _fabrication_commission_with_two_zones(api, project_overrides=None, zone_overrides=None):
    """A commission standing in FABRICATION with two zones on the visitor walk.

    The first learning objective is carried by an artifact case in the first
    zone and the second by an interactive, so the advance out of DESIGN_DEV
    finds every objective addressed.
    """
    fx.set_clock(api)
    project = fx.create_project(api, **(project_overrides or {}))
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    extra = zone_overrides or {}
    zone_a = fx.create_zone(
        api, project_id, zone_code="Z-A", visitor_route_order=1, **extra
    )
    zone_b = fx.create_zone(
        api, project_id, zone_code="Z-B", visitor_route_order=2, **extra
    )
    case = fx.create_case(
        api, project_id, zone_a["id"], case_code="C-01", objective_code=OBJECTIVE_PRIMARY
    )
    interactive = fx.create_interactive(api, project_id)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    return {
        "project_id": project_id,
        "zone_a": zone_a,
        "zone_a_id": zone_a["id"],
        "zone_b": zone_b,
        "zone_b_id": zone_b["id"],
        "case": case,
        "case_id": case["id"],
        "interactive_id": interactive["id"],
    }


def _commission_awaiting_a_veto_with_three_windows(api):
    """Two requested windows on different zones, one approved window, one live round.

    A design change lands during fabrication as a replacement DESIGN_DEV
    package, and the panel that reviews it seats three roles, so its quorum is
    two votes and a single veto is demonstrably short of it.
    """
    ctx = _fabrication_commission_with_two_zones(api)
    ctx["window_one"] = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_a_id"],
        starts_at=DAY_ONE_START,
        ends_at=DAY_ONE_END,
    )
    ctx["window_two"] = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_b_id"],
        starts_at=DAY_ONE_START,
        ends_at=DAY_ONE_END,
    )
    ctx["window_three"] = fx.create_window(
        api,
        ctx["project_id"],
        ctx["zone_a_id"],
        starts_at=DAY_TWO_START,
        ends_at=DAY_TWO_END,
    )
    fx.decide_window(api, ctx["window_three"]["id"])
    ctx["package"] = fx.create_package(
        api, ctx["project_id"], stage=PackageStage.DESIGN_DEV
    )
    ctx["round"] = fx.open_round(
        api,
        ctx["package"]["id"],
        panel_roles=["Curator", "Conservator", "ProjectManager"],
        decision_deadline_at="2026-08-28T08:00:00Z",
    )
    return ctx


def test_a_single_curator_veto_closes_the_round_short_of_quorum(api):
    """One veto out of a three-seat panel ends the round and demands a revision.

    The round's quorum is two votes, yet the veto resolves it on the first vote
    cast, and the package it reviews falls out of review with its revision
    tally advanced.

    PRD section 3.3: "A `VETO` ends the round at once as `VETOED`, and **quorum is not required for a veto** — a single veto closes a round that has collected only one vote out of four."

    PRD section 3.3: "A `VETOED` round and a quorum-with-revisions round both drive the package `IN_REVIEW → REVISION_REQUESTED`."

    Design: Difficulty/transitive_cascade/curator_veto_cascades_through_package_and_phase_into_selective_window_denials
    """
    ctx = _commission_awaiting_a_veto_with_three_windows(api)
    assert ctx["round"]["required_vote_count"] == 2

    resolved = fx.cast_vote(api, ctx["round"]["id"], CURATOR, VoteDecision.VETO)
    assert resolved["status"] == RoundStatus.VETOED
    assert resolved["cast_vote_count"] == 1
    assert resolved["veto_count"] == 1
    assert resolved["approve_count"] == 0
    assert resolved["revise_count"] == 0
    assert resolved["decided_at"] is not None

    package = get_success_data(api.get_design_package(ctx["package"]["id"], PM), 200)
    assert package["status"] == PackageStatus.REVISION_REQUESTED
    assert package["revision_count"] == 1


def test_the_vetoed_design_dev_package_walks_the_commission_back_out_of_fabrication(api):
    """The revision request reverts FABRICATION to DESIGN_DEV without freezing anything.

    The package under veto is the DESIGN_DEV one, so the stage and the phase
    line up and the ladder runs backwards one step; because the veto came from
    the Curator rather than the Conservator the commission is merely restricted.

    PRD section 3.1: "When a `SCHEMATIC`-stage package of a project sitting in `DESIGN_DEV` falls into `REVISION_REQUESTED`, the project reverts `DESIGN_DEV → SCHEMATIC`; when a `DESIGN_DEV`-stage package of a project sitting in `FABRICATION` falls into `REVISION_REQUESTED`, the project reverts `FABRICATION → DESIGN_DEV`."

    PRD section 3.3: "A `Curator` veto ends the round and sends the package back for revision exactly as a conservator's does, but it does not freeze the project."

    Design: Difficulty/transitive_cascade/curator_veto_cascades_through_package_and_phase_into_selective_window_denials
    """
    ctx = _commission_awaiting_a_veto_with_three_windows(api)
    before = fx.read_project(api, ctx["project_id"])
    assert before["phase"] == Phase.FABRICATION

    fx.cast_vote(api, ctx["round"]["id"], CURATOR, VoteDecision.VETO)

    project = fx.read_project(api, ctx["project_id"])
    assert project["phase"] == Phase.DESIGN_DEV
    assert_counters(
        project,
        open_revision_count=1,
        conservation_veto_count=0,
        conservation_block_count=0,
        posture=Posture.RESTRICTED,
    )


def test_the_revert_denies_only_the_windows_still_merely_requested(api):
    """Both requested windows are denied with the literal reason; the approved one is untouched.

    The two windows still awaiting a ruling sit on different zones and both are
    swept, which shows the denial is scoped to the project rather than to the
    zone the design change touched; the window that already earned its
    approval keeps it, and no zone changes occupancy because no work started.

    PRD section 3.3: "Whenever a phase revert fires, **every** install window of that project whose status is still `REQUESTED` transitions to `DENIED` with its `denial_reason` set to the literal string `DESIGN_REVISION_REOPENED`, and each denied window has its `updated_at` refreshed and its `version` incremented."

    PRD section 3.3: "Approved and in-progress windows are untouched; only requested ones are swept away, on the reasoning that a design under revision cannot justify booking gallery time it has not earned."

    Design: Difficulty/transitive_cascade/curator_veto_cascades_through_package_and_phase_into_selective_window_denials
    """
    ctx = _commission_awaiting_a_veto_with_three_windows(api)
    approved_before = get_success_data(
        api.get_install_window(ctx["window_three"]["id"], PM), 200
    )
    assert approved_before["status"] == WindowStatus.APPROVED

    fx.cast_vote(api, ctx["round"]["id"], CURATOR, VoteDecision.VETO)

    for key in ("window_one", "window_two"):
        denied = get_success_data(api.get_install_window(ctx[key]["id"], PM), 200)
        assert denied["status"] == WindowStatus.DENIED
        assert denied["denial_reason"] == DESIGN_REVISION_REOPENED
        assert denied["version"] == ctx[key]["version"] + 1

    approved_after = get_success_data(
        api.get_install_window(ctx["window_three"]["id"], PM), 200
    )
    assert approved_after["status"] == WindowStatus.APPROVED
    assert approved_after["denial_reason"] is None
    assert_unchanged(approved_before, approved_after, ["status", "version", "updated_at"])

    for zone_id in (ctx["zone_a_id"], ctx["zone_b_id"]):
        zone = get_success_data(api.get_gallery_zone(zone_id, PM), 200)
        assert zone["occupancy_state"] == OccupancyState.OPERATING


# ---------------------------------------------------------------------------
# Window completion: occupancy, and only the completed zone's objects
# ---------------------------------------------------------------------------
def _installation_commission_with_two_loaded_zones(api):
    """Two zones, each with one loaded and approved case, one window running.

    The first zone's case holds two reserved objects and has its mount
    fabricated off an approved sheet; the second zone's case holds one reserved
    object and has had no mount work at all. Work is under way on the first
    zone only, and the second zone's window is still merely requested.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone_a = fx.create_zone(api, project_id, zone_code="Z-A", visitor_route_order=1)
    zone_b = fx.create_zone(api, project_id, zone_code="Z-B", visitor_route_order=2)
    first = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.3",
        material_class=MaterialClass.PAPER,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    second = fx.create_artifact(
        api,
        project_id,
        accession_number="2019.14.4",
        material_class=MaterialClass.TEXTILE,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    sibling = fx.create_artifact(
        api,
        project_id,
        accession_number="2020.7.1",
        material_class=MaterialClass.COMPOSITE,
        required_rh_min_pct=40.0,
        required_rh_max_pct=60.0,
        max_lux=80.0,
        security_class=SecurityTier.BASIC,
    )
    case_a = fx.create_case(
        api,
        project_id,
        zone_a["id"],
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
        rh_tolerance_pct=2.0,
    )
    case_b = fx.create_case(
        api,
        project_id,
        zone_b["id"],
        case_code="C-02",
        objective_code=OBJECTIVE_SECONDARY,
        rh_tolerance_pct=2.0,
    )
    fx.place_artifact(api, case_a["id"], first["id"])
    fx.place_artifact(api, case_a["id"], second["id"])
    fx.place_artifact(api, case_b["id"], sibling["id"])
    fx.approve_case(api, case_a["id"])
    fx.approve_case(api, case_b["id"])
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    material = fx.create_material(api, project_id)
    fx.approve_material(api, material["id"])
    drawing = fx.create_drawing(
        api,
        project_id,
        material["id"],
        drawing_number="SD-401",
        subject_case_id=case_a["id"],
    )
    fx.approve_drawing(
        api, drawing["id"], actual_shop_hours=10.0, actual_waste_factor=1.0
    )
    fx.advance_mount(api, case_a["id"], MountStatus.MOUNT_DESIGN)
    fx.advance_mount(api, case_a["id"], MountStatus.MOUNT_FABRICATED)
    fx.advance(api, project_id, Phase.INSTALLATION)
    window_a = fx.create_window(
        api, project_id, zone_a["id"], starts_at=DAY_ONE_START, ends_at=DAY_ONE_END
    )
    window_b = fx.create_window(
        api, project_id, zone_b["id"], starts_at=DAY_ONE_START, ends_at=DAY_ONE_END
    )
    fx.decide_window(api, window_a["id"])
    fx.set_clock(api, DAY_ONE_START)
    fx.start_window(api, window_a["id"])
    return {
        "project_id": project_id,
        "zone_a_id": zone_a["id"],
        "zone_b_id": zone_b["id"],
        "case_a_id": case_a["id"],
        "case_b_id": case_b["id"],
        "first_id": first["id"],
        "second_id": second["id"],
        "sibling_id": sibling["id"],
        "window_a_id": window_a["id"],
        "window_b_id": window_b["id"],
    }


def test_completion_is_refused_while_a_loaded_case_in_the_zone_lacks_its_mount(api):
    """A case in the zone holds reserved objects with the mount only fabricated.

    The gallery cannot be handed back, so the completion is refused, the window
    stays in progress, the zone stays partly closed, and no object is promoted.

    PRD section 3.9: "Every case in the window's zone that holds at least one `RESERVED` object must have reached `MOUNT_INSTALLED`, or completion is refused with `ERR_MOUNT_NOT_INSTALLED` (HTTP 409) — you may not hand the gallery back with objects sitting in cases whose mounts are not in."

    Design: Difficulty/transitive_cascade/window_completion_cascades_to_zone_occupancy_and_only_that_zones_artifacts
    """
    ctx = _installation_commission_with_two_loaded_zones(api)
    before = get_success_data(api.get_install_window(ctx["window_a_id"], PM), 200)
    assert before["status"] == WindowStatus.IN_PROGRESS

    validate_error(
        api.complete_window(ctx["window_a_id"], OPERATIONS), ERR_MOUNT_NOT_INSTALLED, 409
    )

    after = get_success_data(api.get_install_window(ctx["window_a_id"], PM), 200)
    assert_unchanged(before, after, ["status", "version", "updated_at"])
    zone = get_success_data(api.get_gallery_zone(ctx["zone_a_id"], PM), 200)
    assert zone["occupancy_state"] == OccupancyState.PARTIAL_CLOSURE
    for artifact_id in (ctx["first_id"], ctx["second_id"]):
        artifact = get_success_data(api.get_artifact(artifact_id, CURATOR), 200)
        assert artifact["placement_status"] == PlacementStatus.RESERVED


def test_completing_the_window_reopens_its_own_zone_and_leaves_the_sibling_alone(api):
    """With the mount in, the identical completion succeeds and the gallery reopens.

    The mount can only be installed because a window is running on this case's
    own zone; once it is, the window completes and its zone returns to
    OPERATING, while the untouched zone was operating all along.

    PRD section 3.5: "Entering `MOUNT_INSTALLED` requires the conservation status to be `APPROVED` or `CONDITIONALLY_APPROVED`, requires the project phase to be `INSTALLATION`, failing otherwise with `ERR_INVALID_PROJECT_PHASE`, and requires that at least one install window **on this case's own zone** is currently `IN_PROGRESS`, failing otherwise with `ERR_INVALID_WINDOW_STATE` — a window running on a sibling zone of the same project does not unlock the mount."

    PRD section 3.9: "On success the window becomes `COMPLETED`, the zone returns to `OPERATING`, and every `RESERVED` object whose case sits in this zone becomes `PLACED`, processed in ascending order of the case's `created_at` and then the object's `created_at` so the resulting sequence is deterministic."

    Design: Difficulty/transitive_cascade/window_completion_cascades_to_zone_occupancy_and_only_that_zones_artifacts
    """
    ctx = _installation_commission_with_two_loaded_zones(api)
    mounted = fx.advance_mount(api, ctx["case_a_id"], MountStatus.MOUNT_INSTALLED)
    assert mounted["mount_status"] == MountStatus.MOUNT_INSTALLED

    completed = fx.complete_window(api, ctx["window_a_id"])
    assert completed["status"] == WindowStatus.COMPLETED

    assert (
        get_success_data(api.get_gallery_zone(ctx["zone_a_id"], PM), 200)["occupancy_state"]
        == OccupancyState.OPERATING
    )
    assert (
        get_success_data(api.get_gallery_zone(ctx["zone_b_id"], PM), 200)["occupancy_state"]
        == OccupancyState.OPERATING
    )
    assert (
        get_success_data(api.get_install_window(ctx["window_b_id"], PM), 200)["status"]
        == WindowStatus.REQUESTED
    )


def test_completion_installs_only_the_objects_whose_case_sits_in_that_zone(api):
    """Both objects in the completed zone become PLACED; the sibling zone's stays RESERVED.

    The promotion is scoped to the zone the window occupied, and the two objects
    of that zone's case are walked in ascending order of their creation, which
    is the order the case's own object list reports them in.

    PRD section 3.9: "On success the window becomes `COMPLETED`, the zone returns to `OPERATING`, and every `RESERVED` object whose case sits in this zone becomes `PLACED`, processed in ascending order of the case's `created_at` and then the object's `created_at` so the resulting sequence is deterministic."

    Design: Difficulty/transitive_cascade/window_completion_cascades_to_zone_occupancy_and_only_that_zones_artifacts
    """
    ctx = _installation_commission_with_two_loaded_zones(api)
    fx.advance_mount(api, ctx["case_a_id"], MountStatus.MOUNT_INSTALLED)
    fx.complete_window(api, ctx["window_a_id"])

    rows, meta = validate_paginated(api.list_placements(ctx["case_a_id"], CURATOR))
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [ctx["first_id"], ctx["second_id"]]
    assert [row["placement_status"] for row in rows] == [
        PlacementStatus.PLACED,
        PlacementStatus.PLACED,
    ]
    for row in rows:
        assert row["assigned_case_id"] == ctx["case_a_id"]

    sibling = get_success_data(api.get_artifact(ctx["sibling_id"], CURATOR), 200)
    assert sibling["placement_status"] == PlacementStatus.RESERVED
    assert sibling["assigned_case_id"] == ctx["case_b_id"]
