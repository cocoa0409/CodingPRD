"""State machines that fork, cycle and run backwards.

An artifact case carries two independent state fields on one row; a review round
leaves OPEN by three edges whose side effects disagree; and the project phase
walks backwards out of FABRICATION and forwards over the same edge again. These
tests pin the states, the counters and the errors each of those moves produces.
"""

from test_helpers import (
    CONSERVATOR,
    CURATOR,
    OPERATIONS,
    PM,
    CaseDecision,
    CaseStatus,
    InteractiveKind,
    MaterialClass,
    MountStatus,
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
    assert_error_envelope_shape,
    assert_zone_slots,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import (
    DESIGN_REVISION_REOPENED,
    ERR_INVALID_MOUNT_STATE,
    ERR_PROJECT_FROZEN_CONSERVATION,
    OBJECTIVE_PRIMARY,
)
from test_helpers.fixtures import FAR_DEADLINE

PANEL = ["Curator", "Conservator", "ProjectManager"]


def _read_case(api, case_id):
    return validate_success(api.get_artifact_case(case_id, CONSERVATOR))


def _case_under_review_with_a_mount_designed(api):
    """A loaded case sitting in CONSERVATOR_REVIEW whose mount is at MOUNT_DESIGN.

    The two dimensions are moved separately: the curator sends the loaded case to
    conservation, and the conservator then starts the mount while the ruling is
    still outstanding.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    zone = fx.create_zone(api, project_id)
    artifact = fx.create_artifact(
        api,
        project_id,
        material_class=MaterialClass.PAPER,
        security_class=SecurityTier.ENHANCED,
    )
    case = fx.create_case(
        api,
        project_id,
        zone["id"],
        rh_tolerance_pct=2.0,
        uv_microwatt_per_lumen=20.0,
    )
    fx.place_artifact(api, case["id"], artifact["id"])
    submitted = fx.submit_case(api, case["id"])
    mounted = fx.advance_mount(api, case["id"], MountStatus.MOUNT_DESIGN)
    return {
        "project_id": project_id,
        "zone_id": zone["id"],
        "artifact_id": artifact["id"],
        "case_id": case["id"],
        "submitted": submitted,
        "mounted": mounted,
    }


def test_the_mount_dimension_starts_while_the_conservation_ruling_is_outstanding(api):
    """A case still in CONSERVATOR_REVIEW accepts the first mount-making step.

    The curator's submission puts the conservation dimension in
    CONSERVATOR_REVIEW, and the conservator's mount-advance to MOUNT_DESIGN lands
    on the same row without waiting for the ruling. Afterwards the row reports
    both values at once: status CONSERVATOR_REVIEW and mount_status MOUNT_DESIGN.

    "Mount making runs on a **second, independent** state dimension of the same case."

    "The two dimensions are otherwise independent — a case can legitimately sit in `CONSERVATOR_REVIEW` with its mount already at `MOUNT_DESIGN` — but three couplings exist."

    Design: Difficulty/non_linear_state_machine/case_status_and_mount_status_are_two_independent_dimensions_of_one_row
    """
    world = _case_under_review_with_a_mount_designed(api)

    assert world["submitted"]["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert world["submitted"]["mount_status"] == MountStatus.NOT_STARTED
    assert world["mounted"]["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert world["mounted"]["mount_status"] == MountStatus.MOUNT_DESIGN

    stored = _read_case(api, world["case_id"])
    assert stored["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert stored["mount_status"] == MountStatus.MOUNT_DESIGN


def test_the_conservation_approval_reserves_a_slot_and_leaves_the_mount_untouched(api):
    """Approving the case moves one dimension and one counter, and nothing else.

    The ruling drives status CONSERVATOR_REVIEW -> APPROVED and reserves one of
    the zone's two case slots, so the zone reports one reserved and one available.
    The mount dimension is neither reset to NOT_STARTED nor advanced to
    MOUNT_FABRICATED: it stays exactly where the conservator left it, at
    MOUNT_DESIGN.

    "On success the case becomes `APPROVED`, its `conditions` is set to null, and the zone reserves the slot: `reserved_case_slots` rises by one and `available_case_slots` falls by one, preserving the capacity identity, with the zone's own `updated_at` and `version` advancing."

    Design: Difficulty/non_linear_state_machine/case_status_and_mount_status_are_two_independent_dimensions_of_one_row
    """
    world = _case_under_review_with_a_mount_designed(api)

    decided = fx.decide_case(api, world["case_id"], CaseDecision.APPROVE)

    assert decided["status"] == CaseStatus.APPROVED
    assert decided["mount_status"] == MountStatus.MOUNT_DESIGN
    assert decided["conditions"] is None
    zone = validate_success(api.get_gallery_zone(world["zone_id"], OPERATIONS))
    assert_zone_slots(zone, 1, 1)


def test_the_mount_dimension_refuses_a_destination_that_is_not_its_next_step(api):
    """The approved case's mount still walks one step at a time, and only forwards.

    With the conservation dimension at APPROVED and the mount at MOUNT_DESIGN,
    naming NOT_STARTED is not the immediate successor of the stored value, so the
    step is refused with ERR_INVALID_MOUNT_STATE and HTTP 409. Asking for the real
    successor, MOUNT_FABRICATED, is refused too, because no cleared shop drawing
    details this case; the row is left at MOUNT_DESIGN either way.

    "If the named destination is not the immediate successor of the stored value, the step is refused with `ERR_INVALID_MOUNT_STATE` (HTTP 409)."

    "Entering `MOUNT_FABRICATED` requires the conservation status to be `APPROVED` or `CONDITIONALLY_APPROVED`, and further requires that at least one shop drawing detailing this case stands at `APPROVED` or `APPROVED_AS_NOTED` — you cannot fabricate a mount from a sheet nobody has cleared."

    Design: Difficulty/non_linear_state_machine/case_status_and_mount_status_are_two_independent_dimensions_of_one_row
    """
    world = _case_under_review_with_a_mount_designed(api)
    fx.decide_case(api, world["case_id"], CaseDecision.APPROVE)

    backwards = api.mount_advance(
        world["case_id"],
        f.mount_advance_payload(MountStatus.NOT_STARTED),
        CONSERVATOR,
    )
    validate_error(backwards, ERR_INVALID_MOUNT_STATE, 409)

    uncleared = api.mount_advance(
        world["case_id"],
        f.mount_advance_payload(MountStatus.MOUNT_FABRICATED),
        CONSERVATOR,
    )
    assert uncleared.status_code >= 400, uncleared.text
    assert_error_envelope_shape(uncleared)

    stored = _read_case(api, world["case_id"])
    assert stored["status"] == CaseStatus.APPROVED
    assert stored["mount_status"] == MountStatus.MOUNT_DESIGN


def test_the_rejection_empties_the_case_and_leaves_the_mount_where_it_stood(api):
    """A REJECT strips the case back to empty but never touches the mount dimension.

    The refused case becomes REJECTED, its one reserved object returns to
    UNPLACED with no assigned case, placed_artifact_count falls to 0 and the three
    derived limits are nulled. The mount dimension is not in that cascade and
    still reads MOUNT_DESIGN, and because a case under review never held a slot
    the zone still reports none reserved and both slots available.

    "Every object in it whose `placement_status` is `RESERVED` returns to `UNPLACED` with its `assigned_case_id` cleared; `placed_artifact_count` therefore falls to 0, and `required_rh_min_pct`, `required_rh_max_pct` and `allowed_lux` are all nulled out."

    "No zone slot is released, because a case under review never held one."

    Design: Difficulty/non_linear_state_machine/case_rejection_moves_one_dimension_and_the_freeze_masks_the_other
    """
    world = _case_under_review_with_a_mount_designed(api)

    rejected = fx.decide_case(api, world["case_id"], CaseDecision.REJECT)

    assert rejected["status"] == CaseStatus.REJECTED
    assert rejected["mount_status"] == MountStatus.MOUNT_DESIGN
    assert_empty_envelope(rejected)
    artifact = validate_success(api.get_artifact(world["artifact_id"], CURATOR))
    assert artifact["placement_status"] == PlacementStatus.UNPLACED
    assert artifact["assigned_case_id"] is None
    zone = validate_success(api.get_gallery_zone(world["zone_id"], OPERATIONS))
    assert_zone_slots(zone, 0, 2)


def test_the_freeze_outranks_the_mount_rule_even_on_a_fresh_case_version(api):
    """The rejection freezes the commission, and the freeze answers first.

    One rejected case makes conservation_block_count 1, which puts posture at
    FROZEN_CONSERVATION. The same mount-advance to MOUNT_FABRICATED that the
    mount dimension would refuse on its own now answers
    ERR_PROJECT_FROZEN_CONSERVATION with HTTP 409, because posture is checked
    above the state of the resource. Re-placing the released object with the
    fresh case version taken from the rejection response — so the concurrency
    check above posture is satisfied — is refused for the freeze as well.

    "While a project is frozen, ten forward-moving operations are refused with `ERR_PROJECT_FROZEN_CONSERVATION` (HTTP 409): advancing the phase, creating a design package, issuing a shop drawing, deciding a shop drawing, requesting an install window, deciding an install window, reserving an object into a case, advancing a case's mount making, ruling on an interactive prototype, and closeout."

    "The project's `conservation_block_count` rises by one, which drives posture to `FROZEN_CONSERVATION` and stops every forward-moving operation listed in §2.9 until the case is resubmitted."

    Design: Difficulty/non_linear_state_machine/case_rejection_moves_one_dimension_and_the_freeze_masks_the_other
    """
    world = _case_under_review_with_a_mount_designed(api)
    rejected = fx.decide_case(api, world["case_id"], CaseDecision.REJECT)

    project = fx.read_project(api, world["project_id"])
    assert_counters(
        project, posture=Posture.FROZEN_CONSERVATION, conservation_block_count=1
    )

    frozen_mount = api.mount_advance(
        world["case_id"],
        f.mount_advance_payload(MountStatus.MOUNT_FABRICATED),
        CONSERVATOR,
    )
    validate_error(frozen_mount, ERR_PROJECT_FROZEN_CONSERVATION, 409)

    frozen_placement = api.create_placement(
        world["case_id"],
        f.placement_payload(world["artifact_id"], rejected["version"]),
        CURATOR,
    )
    validate_error(frozen_placement, ERR_PROJECT_FROZEN_CONSERVATION, 409)

    stored = _read_case(api, world["case_id"])
    assert stored["status"] == CaseStatus.REJECTED
    assert stored["mount_status"] == MountStatus.MOUNT_DESIGN
    assert stored["placed_artifact_count"] == 0


def _open_round_on_a_replacement_stage_package(api):
    """A DESIGN_DEV package in IN_REVIEW with round 1 open and no vote cast.

    The panel seats Curator, Conservator and ProjectManager, so the quorum is two
    thirds of three rounded up, which is two votes.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    package = fx.create_package(api, project_id, PackageStage.DESIGN_DEV)
    round_one = fx.open_round(api, package["id"], panel_roles=PANEL)
    return {
        "project_id": project_id,
        "package_id": package["id"],
        "round_id": round_one["id"],
        "round_one": round_one,
    }


def test_one_curator_veto_closes_the_round_short_of_quorum(api):
    """A single VETO decides a round whose quorum is two votes.

    The seated panel of three fixes required_vote_count at 2, yet the curator's
    veto ends the round immediately: cast_vote_count is 1, veto_count is 1 and the
    round is VETOED — not the REVISION_REQUESTED that a quorum of REVISE votes
    produces. The package is sent back for revision with revision_count 1, and the
    project is merely RESTRICTED, with conservation_veto_count still 0.

    "A `VETO` ends the round at once as `VETOED`, and **quorum is not required for a veto** — a single veto closes a round that has collected only one vote out of four."

    "A `Curator` veto ends the round and sends the package back for revision exactly as a conservator's does, but it does not freeze the project."

    Design: Difficulty/non_linear_state_machine/one_open_review_round_has_three_exits_with_three_different_side_effect_sets
    """
    world = _open_round_on_a_replacement_stage_package(api)
    assert world["round_one"]["required_vote_count"] == 2
    assert world["round_one"]["status"] == RoundStatus.OPEN

    vetoed = fx.cast_vote(
        api,
        world["round_id"],
        CURATOR,
        VoteDecision.VETO,
        comment="storyline conflicts with the loan agreement",
    )

    assert vetoed["status"] == RoundStatus.VETOED
    assert vetoed["cast_vote_count"] == 1
    assert vetoed["required_vote_count"] == 2
    assert vetoed["veto_count"] == 1
    package = validate_success(api.get_design_package(world["package_id"], PM))
    assert package["status"] == PackageStatus.REVISION_REQUESTED
    assert package["revision_count"] == 1
    assert_counters(
        fx.read_project(api, world["project_id"]),
        posture=Posture.RESTRICTED,
        conservation_veto_count=0,
        open_revision_count=1,
    )


def test_the_package_re_enters_review_from_revision_requested_as_round_two(api):
    """The vetoed package opens a second round, which is the cycle in this machine.

    A package sitting in REVISION_REQUESTED is eligible for a fresh round, and the
    new round takes the package's review_round_count plus one, so it is round 2.
    Opening it drives the package back into IN_REVIEW with an untouched
    revision_count of 1, and the new round starts OPEN with no votes cast.

    "The new round records the package it reviews through its `package_id` and takes a `round_number` equal to the package's `review_round_count` plus one, so rounds are numbered from 1 within each package."

    "Because a package in `REVISION_REQUESTED` may open a fresh round, and the round that follows may put it back into `REVISION_REQUESTED`, the review machine is genuinely cyclic — a package can re-enter review any number of times."

    Design: Difficulty/non_linear_state_machine/one_open_review_round_has_three_exits_with_three_different_side_effect_sets
    """
    world = _open_round_on_a_replacement_stage_package(api)
    assert world["round_one"]["round_number"] == 1
    fx.cast_vote(api, world["round_id"], CURATOR, VoteDecision.VETO)

    round_two = fx.open_round(
        api,
        world["package_id"],
        panel_roles=PANEL,
        decision_deadline_at=FAR_DEADLINE,
    )

    assert round_two["round_number"] == 2
    assert round_two["status"] == RoundStatus.OPEN
    assert round_two["cast_vote_count"] == 0
    assert round_two["required_vote_count"] == 2
    package = validate_success(api.get_design_package(world["package_id"], PM))
    assert package["status"] == PackageStatus.IN_REVIEW
    assert package["revision_count"] == 1


def test_the_same_veto_from_a_conservator_freezes_the_commission(api):
    """The identical VETO payload has a strictly larger side-effect set at conservation.

    The curator's veto on round 1 leaves the project RESTRICTED with no
    conservation block. The conservator's veto on round 2 sends the package back
    for revision in exactly the same way, but it also raises
    conservation_veto_count to 1, which carries conservation_block_count to 1 and
    drives posture straight to FROZEN_CONSERVATION.

    "When a veto's `voter_role` is `Conservator`, one further consequence fires: the project's `conservation_veto_count` increases by one, which raises `conservation_block_count` and drives the project straight to `FROZEN_CONSERVATION`."

    "If `conservation_block_count` is greater than zero, posture is `FROZEN_CONSERVATION`."

    Design: Difficulty/non_linear_state_machine/one_open_review_round_has_three_exits_with_three_different_side_effect_sets
    """
    world = _open_round_on_a_replacement_stage_package(api)
    fx.cast_vote(api, world["round_id"], CURATOR, VoteDecision.VETO)
    assert_counters(
        fx.read_project(api, world["project_id"]),
        posture=Posture.RESTRICTED,
        conservation_veto_count=0,
    )
    round_two = fx.open_round(api, world["package_id"], panel_roles=PANEL)

    conservator_veto = fx.cast_vote(
        api,
        round_two["id"],
        CONSERVATOR,
        VoteDecision.VETO,
        comment="off-gassing risk in the proposed case liner",
    )

    assert conservator_veto["status"] == RoundStatus.VETOED
    assert conservator_veto["veto_count"] == 1
    assert_counters(
        fx.read_project(api, world["project_id"]),
        posture=Posture.FROZEN_CONSERVATION,
        conservation_veto_count=1,
        conservation_block_count=1,
    )


def _fabrication_with_a_replacement_stage_package_in_review(api):
    """A commission in FABRICATION whose DESIGN_DEV stage has been re-opened.

    Both learning objectives are carried by interactives, so the forward edge into
    FABRICATION is passable more than once. One install window sits at REQUESTED,
    and a replacement DESIGN_DEV package issued during FABRICATION has round 1
    open with a single REVISE vote already cast, so the next REVISE reaches the
    two-vote quorum.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    zone = fx.create_zone(api, project_id)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    stage_package, _ = fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.create_interactive(api, project_id)
    fx.create_interactive(
        api,
        project_id,
        code="INT-RIVER",
        kind=InteractiveKind.AUDIO,
        objective_code=OBJECTIVE_PRIMARY,
        expected_daily_uses=40,
        duty_hours_per_day=4.0,
        mtbf_cycles=2000000,
    )
    fx.advance(api, project_id, Phase.FABRICATION)
    window = fx.create_window(
        api,
        project_id,
        zone["id"],
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T10:00:00Z",
    )
    replacement = fx.create_package(api, project_id, PackageStage.DESIGN_DEV)
    review_round = fx.open_round(api, replacement["id"], panel_roles=PANEL)
    fx.cast_vote(api, review_round["id"], CURATOR, VoteDecision.REVISE)
    return {
        "project_id": project_id,
        "zone_id": zone["id"],
        "stage_package_id": stage_package["id"],
        "replacement_id": replacement["id"],
        "round_id": review_round["id"],
        "window_id": window["id"],
    }


def test_a_quorum_of_revisions_walks_the_project_backwards_out_of_fabrication(api):
    """The second REVISE vote reverts the phase from FABRICATION to DESIGN_DEV.

    Two of the three seated panelists have now asked for revisions, so
    cast_vote_count equals the quorum of 2, revise_count is 2 and no veto was
    cast: the round closes as REVISION_REQUESTED. Because the package under
    revision carries the DESIGN_DEV stage and the project is standing in
    FABRICATION, the phase walks backwards to DESIGN_DEV, and the open revision
    makes the project RESTRICTED.

    "A round that reaches quorum with at least one `REVISE` and no veto becomes `REVISION_REQUESTED`."

    "When a `SCHEMATIC`-stage package of a project sitting in `DESIGN_DEV` falls into `REVISION_REQUESTED`, the project reverts `DESIGN_DEV → SCHEMATIC`; when a `DESIGN_DEV`-stage package of a project sitting in `FABRICATION` falls into `REVISION_REQUESTED`, the project reverts `FABRICATION → DESIGN_DEV`."

    Design: Difficulty/non_linear_state_machine/project_phase_reverts_out_of_fabrication_and_then_re_advances
    """
    world = _fabrication_with_a_replacement_stage_package_in_review(api)

    resolved = fx.cast_vote(
        api,
        world["round_id"],
        CONSERVATOR,
        VoteDecision.REVISE,
        comment="case liner detail needs redrawing",
    )

    assert resolved["status"] == RoundStatus.REVISION_REQUESTED
    assert resolved["cast_vote_count"] == 2
    assert resolved["required_vote_count"] == 2
    assert resolved["revise_count"] == 2
    assert resolved["veto_count"] == 0
    package = validate_success(api.get_design_package(world["replacement_id"], PM))
    assert package["status"] == PackageStatus.REVISION_REQUESTED
    assert_counters(
        fx.read_project(api, world["project_id"]),
        phase=Phase.DESIGN_DEV,
        posture=Posture.RESTRICTED,
        open_revision_count=1,
    )


def test_the_replacement_package_supersedes_the_approved_one_of_the_same_stage(api):
    """Issuing a second DESIGN_DEV package displaces the approved first one.

    The commission reached FABRICATION on an APPROVED DESIGN_DEV package. Issuing
    the replacement at the same stage moves that earlier package to the terminal
    SUPERSEDED and points its superseded_by_package_id at the replacement, which
    is what lets the stage be re-reviewed while the shop is already building.

    "Every existing package of this project whose `stage` matches the new one and whose status is not already `SUPERSEDED` — that is, any package in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED` or `APPROVED` — transitions to `SUPERSEDED`, processed in ascending `created_at` order, and has its `superseded_by_package_id` set to the new package's identifier."

    Design: Difficulty/non_linear_state_machine/project_phase_reverts_out_of_fabrication_and_then_re_advances
    """
    world = _fabrication_with_a_replacement_stage_package_in_review(api)

    displaced = validate_success(
        api.get_design_package(world["stage_package_id"], PM)
    )

    assert displaced["status"] == PackageStatus.SUPERSEDED
    assert displaced["superseded_by_package_id"] == world["replacement_id"]
    replacement = validate_success(api.get_design_package(world["replacement_id"], PM))
    assert replacement["superseded_by_package_id"] is None
    assert replacement["stage"] == PackageStage.DESIGN_DEV


def test_the_revert_denies_the_requested_window_with_the_pinned_reason(api):
    """The phase revert sweeps the outstanding install window away.

    The window was still REQUESTED when the revert fired, so it becomes DENIED and
    its denial_reason is the literal string DESIGN_REVISION_REOPENED — a reason the
    cascade writes itself, with no operator ever supplying it.

    "Whenever a phase revert fires, **every** install window of that project whose status is still `REQUESTED` transitions to `DENIED` with its `denial_reason` set to the literal string `DESIGN_REVISION_REOPENED`, and each denied window has its `updated_at` refreshed and its `version` incremented."

    Design: Difficulty/non_linear_state_machine/project_phase_reverts_out_of_fabrication_and_then_re_advances
    """
    world = _fabrication_with_a_replacement_stage_package_in_review(api)
    before = validate_success(api.get_install_window(world["window_id"], OPERATIONS))
    assert before["status"] == WindowStatus.REQUESTED
    assert before["denial_reason"] is None

    fx.cast_vote(api, world["round_id"], CONSERVATOR, VoteDecision.REVISE)

    window = validate_success(api.get_install_window(world["window_id"], OPERATIONS))
    assert window["status"] == WindowStatus.DENIED
    assert window["denial_reason"] == DESIGN_REVISION_REOPENED


def test_the_forward_edge_into_fabrication_is_traversable_a_second_time(api):
    """Once the replacement is approved the project walks the same edge again.

    Approving the replacement package on a fresh round clears the open revision,
    so open_revision_count returns to 0 and posture to OPEN, and the advance from
    DESIGN_DEV to FABRICATION lands a second time on the strength of the newly
    APPROVED DESIGN_DEV package and the two interactives that carry both learning
    objectives. The advance touches the project row alone: the window denied by the
    revert is still DENIED and must be requested afresh.

    "`DESIGN_DEV → FABRICATION` requires an `APPROVED` package at the `DESIGN_DEV` stage, and additionally requires that every code in `objective_codes` is carried by something buildable: each code must appear as the `objective_code` of at least one artifact case or at least one interactive belonging to the project, and a code carried by nothing fails the advance with `ERR_OBJECTIVE_NOT_ADDRESSED`."

    "Whatever the step, a successful advance refreshes the project's `updated_at`, increments its `version` by one, and recomputes posture."

    Design: Difficulty/non_linear_state_machine/project_phase_reverts_out_of_fabrication_and_then_re_advances
    """
    world = _fabrication_with_a_replacement_stage_package_in_review(api)
    fx.cast_vote(api, world["round_id"], CONSERVATOR, VoteDecision.REVISE)
    second_round = fx.open_round(api, world["replacement_id"], panel_roles=PANEL)
    fx.cast_vote(api, second_round["id"], CURATOR, VoteDecision.APPROVE)
    approved = fx.cast_vote(api, second_round["id"], CONSERVATOR, VoteDecision.APPROVE)
    assert approved["status"] == RoundStatus.APPROVED
    assert_counters(
        fx.read_project(api, world["project_id"]),
        phase=Phase.DESIGN_DEV,
        posture=Posture.OPEN,
        open_revision_count=0,
    )

    re_advanced = fx.advance(api, world["project_id"], Phase.FABRICATION)

    assert re_advanced["phase"] == Phase.FABRICATION
    window = validate_success(api.get_install_window(world["window_id"], OPERATIONS))
    assert window["status"] == WindowStatus.DENIED
    assert window["denial_reason"] == DESIGN_REVISION_REOPENED
