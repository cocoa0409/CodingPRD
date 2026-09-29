"""Edges of the review-round, prototype, posture and objective-coverage gates.

Every test builds its own preconditions through the documented endpoints: the
harness restarts the server before each test, so each one opens on an empty
database with the logical clock at its documented default instant.
"""

from test_helpers import (
    CONSERVATOR,
    CURATOR,
    ERR_INVALID_INTERACTIVE_STATE,
    ERR_INVALID_PACKAGE_STATE,
    ERR_INVALID_ROUND_STATE,
    ERR_OBJECTIVE_NOT_ADDRESSED,
    ERR_PROJECT_POSTURE_RESTRICTED,
    ERR_PROTOTYPE_NOT_APPROVED,
    ERR_ROUND_ALREADY_OPEN,
    FABRICATION,
    OBJECTIVE_PRIMARY,
    OBJECTIVE_SECONDARY,
    PM,
    InteractiveStatus,
    MaintenanceTier,
    MaterialDecision,
    MaterialStatus,
    OddyResult,
    PackageStage,
    PackageStatus,
    Phase,
    Posture,
    PrototypeDecision,
    RoundStatus,
    UsedIn,
    Verdict,
    VoteDecision,
    assert_counters,
    assert_index,
    factories,
    fixtures,
    get_success_data,
    validate_error,
)

FOUR_ROLE_PANEL = ["Curator", "Conservator", "ProjectManager", "AccessibilitySpecialist"]
LATER_DEADLINE = "2026-08-25T00:00:00Z"
LATEST_DEADLINE = "2026-08-30T00:00:00Z"


def _schematic_project_with_package(api):
    """Open a commission, walk it to SCHEMATIC and issue one design package."""
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    fixtures.advance(api, project["id"], Phase.SCHEMATIC)
    package = fixtures.create_package(api, project["id"], PackageStage.SCHEMATIC)
    return project, package


def _fabrication_project_with_interactive(api, **interactive_overrides):
    """Walk a commission to FABRICATION carrying one interactive station.

    The case carries the first learning objective and the interactive the
    second, so the objective-coverage gate on the FABRICATION step is met.
    """
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id)
    case = fixtures.create_case(api, project_id, zone["id"])
    interactive = fixtures.create_interactive(api, project_id, **interactive_overrides)
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fixtures.advance(api, project_id, Phase.FABRICATION)
    return {
        "project_id": project_id,
        "zone": zone,
        "case": case,
        "interactive": interactive,
    }


def _project_ready_for_the_installation_advance(api):
    """Build a FABRICATION commission that meets every non-posture admission test.

    The single case is loaded and APPROVED and one shop drawing stands at
    APPROVED, so the only thing that can still refuse the INSTALLATION step is
    the project's own posture.
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    fixtures.place_artifact(api, ctx["case_id"], ctx["artifact_id"])
    fixtures.approve_case(api, ctx["case_id"])
    drawing = fixtures.create_drawing(
        api, ctx["project_id"], ctx["material_id"], subject_case_id=ctx["case_id"]
    )
    fixtures.approve_drawing(
        api, drawing["id"], actual_shop_hours=10.0, actual_waste_factor=1.0
    )
    ctx["drawing"] = drawing
    return ctx


def _design_dev_project_with_one_carried_objective(api):
    """Walk a commission to DESIGN_DEV where only one objective code is carried."""
    fixtures.set_clock(api)
    project = fixtures.create_project(api)
    project_id = project["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)
    zone = fixtures.create_zone(api, project_id)
    case = fixtures.create_case(api, project_id, zone["id"])
    fixtures.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fixtures.advance(api, project_id, Phase.DESIGN_DEV)
    package, _ = fixtures.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    return {"project_id": project_id, "case": case, "package": package}


def test_a_second_round_is_refused_while_the_package_holds_an_open_round(api):
    """One live round per package, whatever panel the second request seats.

    "A package carries at most one live round: if any round of that package is
    still `OPEN`, the request fails with `ERR_ROUND_ALREADY_OPEN`."

    Design: Corner/state_machines/a_package_holds_one_open_round_at_a_time_and_a_resolved_round_takes_no_more_votes
    """
    _project, package = _schematic_project_with_package(api)
    first = fixtures.open_round(api, package["id"])
    assert first["status"] == RoundStatus.OPEN
    assert first["round_number"] == 1

    response = api.create_review_round(
        package["id"],
        factories.review_round_payload(
            panel_roles=["Curator", "Conservator", "AccessibilitySpecialist"],
            decision_deadline_at=LATER_DEADLINE,
        ),
        PM,
    )
    validate_error(response, ERR_ROUND_ALREADY_OPEN)

    rounds = get_success_data(api.list_review_rounds(package["id"], PM), 200)
    assert len(rounds) == 1
    assert rounds[0]["id"] == first["id"]
    stored = get_success_data(api.get_design_package(package["id"], PM), 200)
    assert stored["review_round_count"] == 1
    assert stored["status"] == PackageStatus.IN_REVIEW


def test_a_resolved_round_takes_no_more_votes_and_its_package_refuses_a_fresh_round(api):
    """The quorum resolves the round, and two different refusals follow it.

    "A round that reaches quorum with every vote an approval, that is with
    `cast_vote_count` equal to `required_vote_count` and `approve_count` equal
    to `required_vote_count`, becomes `APPROVED`."

    "the round must still be `OPEN`, since a round that has reached `APPROVED`,
    `REVISION_REQUESTED`, `VETOED` or `CLOSED_SUPERSEDED` accepts nothing
    further and answers `ERR_INVALID_ROUND_STATE`"

    "A round may only be opened on a package whose status is `DRAFT` or
    `REVISION_REQUESTED`; a `SUPERSEDED`, `IN_REVIEW` or `APPROVED` package
    refuses with `ERR_INVALID_PACKAGE_STATE`, and a package whose
    `superseded_by_package_id` is set is never eligible."

    Design: Corner/state_machines/a_package_holds_one_open_round_at_a_time_and_a_resolved_round_takes_no_more_votes
    """
    _project, package = _schematic_project_with_package(api)
    review_round = fixtures.open_round(api, package["id"])
    assert review_round["required_vote_count"] == 2

    after_first_vote = fixtures.cast_vote(
        api, review_round["id"], CURATOR, VoteDecision.APPROVE
    )
    assert after_first_vote["status"] == RoundStatus.OPEN
    assert after_first_vote["cast_vote_count"] == 1

    resolved = fixtures.cast_vote(
        api, review_round["id"], CONSERVATOR, VoteDecision.APPROVE
    )
    assert resolved["status"] == RoundStatus.APPROVED
    assert resolved["cast_vote_count"] == 2
    assert resolved["approve_count"] == 2
    assert resolved["decided_at"].startswith("2026-08-01T00:00:00")

    late_vote = api.cast_vote(
        review_round["id"], factories.vote_payload(VoteDecision.APPROVE), FABRICATION
    )
    validate_error(late_vote, ERR_INVALID_ROUND_STATE)

    second_round = api.create_review_round(
        package["id"],
        factories.review_round_payload(decision_deadline_at=LATER_DEADLINE),
        PM,
    )
    validate_error(second_round, ERR_INVALID_PACKAGE_STATE)

    stored = get_success_data(api.get_design_package(package["id"], PM), 200)
    assert stored["status"] == PackageStatus.APPROVED
    assert stored["review_round_count"] == 1
    assert stored["revision_count"] == 0
    assert stored["approved_at"].startswith("2026-08-01T00:00:00")


def test_a_revision_requested_package_re_enters_review_under_the_next_round_number(api):
    """The same endpoint that refuses an approved package succeeds on a revised one.

    "Because a package in `REVISION_REQUESTED` may open a fresh round, and the
    round that follows may put it back into `REVISION_REQUESTED`, the review
    machine is genuinely cyclic — a package can re-enter review any number of
    times."

    "The new round records the package it reviews through its `package_id` and
    takes a `round_number` equal to the package's `review_round_count` plus one,
    so rounds are numbered from 1 within each package."

    "A panel of three therefore needs 2 votes, a panel of four needs 3, and a
    panel of five needs 4."

    Design: Corner/state_machines/a_package_holds_one_open_round_at_a_time_and_a_resolved_round_takes_no_more_votes
    """
    project, package = _schematic_project_with_package(api)
    first = fixtures.open_round(api, package["id"])
    fixtures.cast_vote(
        api,
        first["id"],
        CURATOR,
        VoteDecision.REVISE,
        comment="Raise the case rail to 900 mm.",
    )
    resolved = fixtures.cast_vote(api, first["id"], CONSERVATOR, VoteDecision.APPROVE)
    assert resolved["status"] == RoundStatus.REVISION_REQUESTED
    assert resolved["revise_count"] == 1
    assert resolved["approve_count"] == 1

    revised = get_success_data(api.get_design_package(package["id"], PM), 200)
    assert revised["status"] == PackageStatus.REVISION_REQUESTED
    assert revised["revision_count"] == 1
    assert revised["review_round_count"] == 1

    restricted = fixtures.read_project(api, project["id"])
    assert_counters(restricted, open_revision_count=1, posture=Posture.RESTRICTED)

    response = api.create_review_round(
        package["id"],
        factories.review_round_payload(
            panel_roles=FOUR_ROLE_PANEL, decision_deadline_at=LATEST_DEADLINE
        ),
        PM,
    )
    second = get_success_data(response, 201)
    assert second["round_number"] == 2
    assert second["required_vote_count"] == 3
    assert second["status"] == RoundStatus.OPEN

    back_in_review = get_success_data(api.get_design_package(package["id"], PM), 200)
    assert back_in_review["status"] == PackageStatus.IN_REVIEW
    assert back_in_review["review_round_count"] == 2


def test_a_specified_station_cannot_be_marked_built_before_its_prototype_is_approved(api):
    """The loop has one entry point, so the build flag cannot short-circuit it.

    "Marking a station built is the `FabricationLead`'s, requires status exactly
    `PROTOTYPE_APPROVED` — anything else, including a station still `SPECIFIED`,
    answers `ERR_PROTOTYPE_NOT_APPROVED` — requires the project to be in
    `FABRICATION` or `INSTALLATION` and not frozen, and lands it at
    `FABRICATED`."

    Design: Corner/state_machines/the_interactive_prototype_loop_re_enters_after_a_rejection_and_re_derives_the_tier
    """
    ctx = _fabrication_project_with_interactive(
        api,
        expected_daily_uses=150,
        duty_hours_per_day=6.0,
        mtbf_cycles=1200000,
        parts_availability_years=10,
    )
    interactive_id = ctx["interactive"]["id"]
    assert ctx["interactive"]["status"] == InteractiveStatus.SPECIFIED
    assert ctx["interactive"]["prototype_iteration"] == 0

    response = api.mark_fabricated(interactive_id, FABRICATION)
    validate_error(response, ERR_PROTOTYPE_NOT_APPROVED)

    unchanged = get_success_data(api.get_interactive(interactive_id, FABRICATION), 200)
    assert unchanged["status"] == InteractiveStatus.SPECIFIED
    assert unchanged["prototype_iteration"] == 0
    assert unchanged["durability_index_verified"] is None


def test_the_prototype_loop_counts_its_iterations_and_scores_only_on_an_approval(api):
    """A rejection leaves the verified index null; the approval re-derives the tier.

    "`REJECT` lands the station at `PROTOTYPE_REJECTED` and deliberately leaves
    `measured_daily_uses`, `measured_mtbf_cycles` and
    `durability_index_verified` untouched, so the `maintenance_tier` keeps
    deriving from `durability_index_spec` — a rejected bench test never earns
    the credit."

    "The **verified** variant uses the bench-measured `measured_daily_uses` and
    `measured_mtbf_cycles` with a prototype credit of 8 points — the reward for
    having actually built and tested the thing — and writes
    `durability_index_verified`; because the credit can push a strong station
    past a perfect score, this variant is where the cap at 100.0 bites."

    "The `maintenance_tier` is then derived from `durability_index_verified`
    when that field is non-null and from `durability_index_spec` otherwise, with
    inclusive lower boundaries: at least 80 is `LOW`, at least 60 is `MEDIUM`,
    at least 40 is `HIGH`, and anything below 40 is `CRITICAL`."

    Design: Corner/state_machines/the_interactive_prototype_loop_re_enters_after_a_rejection_and_re_derives_the_tier
    """
    ctx = _fabrication_project_with_interactive(
        api,
        expected_daily_uses=150,
        duty_hours_per_day=6.0,
        mtbf_cycles=1200000,
        parts_availability_years=10,
    )
    interactive_id = ctx["interactive"]["id"]
    assert_index(ctx["interactive"]["durability_index_spec"], 70.60)
    assert ctx["interactive"]["maintenance_tier"] == MaintenanceTier.MEDIUM

    submitted = get_success_data(
        api.submit_prototype(
            interactive_id, factories.prototype_payload(400, 500000), FABRICATION
        ),
        200,
    )
    assert submitted["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert submitted["prototype_iteration"] == 1
    assert submitted["durability_index_verified"] is None
    assert_index(submitted["durability_index_spec"], 70.60)
    assert submitted["maintenance_tier"] == MaintenanceTier.MEDIUM

    rejected = get_success_data(
        api.prototype_decision(
            interactive_id,
            factories.prototype_decision_payload(
                PrototypeDecision.REJECT,
                note="Bezel deflection out of tolerance at 400 uses per day.",
            ),
            PM,
        ),
        200,
    )
    assert rejected["status"] == InteractiveStatus.PROTOTYPE_REJECTED
    assert rejected["prototype_iteration"] == 1
    assert rejected["durability_index_verified"] is None
    assert rejected["maintenance_tier"] == MaintenanceTier.MEDIUM

    resubmitted = get_success_data(
        api.submit_prototype(
            interactive_id, factories.prototype_payload(60, 1500000), FABRICATION
        ),
        200,
    )
    assert resubmitted["status"] == InteractiveStatus.PROTOTYPE_SUBMITTED
    assert resubmitted["prototype_iteration"] == 2
    assert resubmitted["durability_index_verified"] is None
    assert resubmitted["measured_daily_uses"] == 60
    assert resubmitted["measured_mtbf_cycles"] == 1500000

    approved = get_success_data(
        api.prototype_decision(
            interactive_id,
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            PM,
        ),
        200,
    )
    assert approved["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    assert approved["prototype_iteration"] == 2
    assert_index(approved["durability_index_verified"], 87.58)
    assert approved["maintenance_tier"] == MaintenanceTier.LOW
    assert_index(approved["durability_index_spec"], 70.60)


def test_a_built_station_can_no_longer_re_enter_the_prototype_loop(api):
    """FABRICATED sits outside the loop, so a further bench submission is refused.

    "A `FabricationLead` submits a prototype from `SPECIFIED` or from
    `PROTOTYPE_REJECTED` — the rejected branch is the rework loop and may be
    walked any number of times — while the project is in `DESIGN_DEV` or
    `FABRICATION` and not frozen."

    "Any other starting status answers `ERR_INVALID_INTERACTIVE_STATE`."

    Design: Corner/state_machines/the_interactive_prototype_loop_re_enters_after_a_rejection_and_re_derives_the_tier
    """
    ctx = _fabrication_project_with_interactive(
        api,
        expected_daily_uses=150,
        duty_hours_per_day=6.0,
        mtbf_cycles=1200000,
        parts_availability_years=10,
    )
    interactive_id = ctx["interactive"]["id"]
    get_success_data(
        api.submit_prototype(
            interactive_id, factories.prototype_payload(60, 1500000), FABRICATION
        ),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive_id,
            factories.prototype_decision_payload(PrototypeDecision.APPROVE),
            PM,
        ),
        200,
    )
    built = get_success_data(api.mark_fabricated(interactive_id, FABRICATION), 200)
    assert built["status"] == InteractiveStatus.FABRICATED
    assert built["maintenance_tier"] == MaintenanceTier.LOW

    response = api.submit_prototype(
        interactive_id, factories.prototype_payload(10, 9000000), FABRICATION
    )
    validate_error(response, ERR_INVALID_INTERACTIVE_STATE)

    unchanged = get_success_data(api.get_interactive(interactive_id, FABRICATION), 200)
    assert unchanged["status"] == InteractiveStatus.FABRICATED
    assert unchanged["prototype_iteration"] == 1
    assert_index(unchanged["durability_index_verified"], 87.58)
    assert unchanged["measured_daily_uses"] == 60
    assert unchanged["measured_mtbf_cycles"] == 1500000


def test_a_material_awaiting_conservation_blocks_the_installation_advance_twice(api):
    """A spec in SUBMITTED and the same spec in review both restrict the commission.

    "`pending_material_count`, the number of its material specifications whose
    status is `SUBMITTED` or `CONSERVATOR_REVIEW`"

    "Otherwise, if `open_revision_count` is greater than zero, or
    `conditional_case_count` is greater than zero, or `pending_material_count`
    is greater than zero, posture is `RESTRICTED`."

    "`RESTRICTED` is the softer gate, and only two operations demand a fully
    settled project: advancing the phase to `INSTALLATION`, and closeout."

    Design: Corner/state_machines/advancing_to_installation_is_refused_while_one_pending_material_review_restricts_the_posture
    """
    ctx = _project_ready_for_the_installation_advance(api)
    project_id = ctx["project_id"]

    settled = fixtures.read_project(api, project_id)
    assert settled["phase"] == Phase.FABRICATION
    assert_counters(settled, posture=Posture.OPEN, pending_material_count=0)

    material = fixtures.create_material(
        api,
        project_id,
        material_name="Reclaimed oak plinth cap",
        used_in=UsedIn.CASE_EXTERIOR,
        oddy_test_result=OddyResult.PASS,
        voc_mg_per_m2_day=0.44,
        formaldehyde_ppm=0.06,
        cure_days=9,
    )
    assert material["status"] == MaterialStatus.SUBMITTED
    assert material["verdict"] == Verdict.CONSERVATION_SAFE

    restricted = fixtures.read_project(api, project_id)
    assert_counters(restricted, pending_material_count=1, posture=Posture.RESTRICTED)

    refused = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.INSTALLATION), PM
    )
    validate_error(refused, ERR_PROJECT_POSTURE_RESTRICTED)

    in_review = get_success_data(
        api.submit_material_for_conservation(material["id"], FABRICATION), 200
    )
    assert in_review["status"] == MaterialStatus.CONSERVATOR_REVIEW

    still_restricted = fixtures.read_project(api, project_id)
    assert_counters(
        still_restricted, pending_material_count=1, posture=Posture.RESTRICTED
    )

    refused_again = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.INSTALLATION), PM
    )
    validate_error(refused_again, ERR_PROJECT_POSTURE_RESTRICTED)
    assert fixtures.read_project(api, project_id)["phase"] == Phase.FABRICATION


def test_a_conditionally_cleared_material_leaves_the_pending_set_and_opens_the_gate(api):
    """CONDITIONAL is outside the pending set, so the identical advance now runs.

    "Both set `decided_at` to the logical-clock instant, drop the material out
    of `pending_material_count`, and recompute posture — so clearing the last
    pending material is what returns a project to `OPEN`."

    "`conditional_case_count`, the number of its artifact cases in
    `CONDITIONALLY_APPROVED`"

    "`FABRICATION → INSTALLATION` is one of the two gates that demands posture
    exactly `OPEN`; it further requires that the project has at least one
    artifact case and that every one of its cases is `APPROVED`, and that at
    least one shop drawing of the project stands at `APPROVED` or
    `APPROVED_AS_NOTED`."

    Design: Corner/state_machines/advancing_to_installation_is_refused_while_one_pending_material_review_restricts_the_posture
    """
    ctx = _project_ready_for_the_installation_advance(api)
    project_id = ctx["project_id"]

    material = fixtures.create_material(
        api,
        project_id,
        material_name="Reclaimed oak plinth cap",
        used_in=UsedIn.CASE_EXTERIOR,
        oddy_test_result=OddyResult.PASS,
        voc_mg_per_m2_day=0.44,
        formaldehyde_ppm=0.06,
        cure_days=9,
    )
    refused = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.INSTALLATION), PM
    )
    validate_error(refused, ERR_PROJECT_POSTURE_RESTRICTED)

    cleared = fixtures.approve_material(
        api,
        material["id"],
        MaterialDecision.APPROVE_WITH_CONDITIONS,
        conditions="Seal all six faces and re-test after a 21 day cure.",
    )
    assert cleared["status"] == MaterialStatus.CONDITIONAL
    assert cleared["conditions"] == "Seal all six faces and re-test after a 21 day cure."
    assert cleared["decided_at"].startswith("2026-08-01T00:00:00")

    reopened = fixtures.read_project(api, project_id)
    assert_counters(
        reopened,
        pending_material_count=0,
        conditional_case_count=0,
        posture=Posture.OPEN,
    )

    advanced = fixtures.advance(api, project_id, Phase.INSTALLATION)
    assert advanced["phase"] == Phase.INSTALLATION


def test_a_half_carried_objective_list_fails_the_fabrication_advance(api):
    """One code carried by a case and one carried by nothing still fails.

    "`DESIGN_DEV → FABRICATION` requires an `APPROVED` package at the
    `DESIGN_DEV` stage, and additionally requires that every code in
    `objective_codes` is carried by something buildable: each code must appear
    as the `objective_code` of at least one artifact case or at least one
    interactive belonging to the project, and a code carried by nothing fails
    the advance with `ERR_OBJECTIVE_NOT_ADDRESSED`."

    Design: Corner/state_machines/advance_to_fabrication_requires_every_objective_code_to_be_carried_by_a_case_or_an_interactive
    """
    ctx = _design_dev_project_with_one_carried_objective(api)
    project_id = ctx["project_id"]
    assert ctx["case"]["objective_code"] == OBJECTIVE_PRIMARY

    package = get_success_data(api.get_design_package(ctx["package"]["id"], PM), 200)
    assert package["stage"] == PackageStage.DESIGN_DEV
    assert package["status"] == PackageStatus.APPROVED

    response = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.FABRICATION), PM
    )
    validate_error(response, ERR_OBJECTIVE_NOT_ADDRESSED)

    stalled = fixtures.read_project(api, project_id)
    assert stalled["phase"] == Phase.DESIGN_DEV
    assert stalled["objective_codes"] == [OBJECTIVE_PRIMARY, OBJECTIVE_SECONDARY]


def test_coverage_split_across_a_case_and_an_interactive_opens_the_fabrication_step(api):
    """The two entity types may share the coverage of the objective list.

    "`DESIGN_DEV → FABRICATION` requires an `APPROVED` package at the
    `DESIGN_DEV` stage, and additionally requires that every code in
    `objective_codes` is carried by something buildable: each code must appear
    as the `objective_code` of at least one artifact case or at least one
    interactive belonging to the project, and a code carried by nothing fails
    the advance with `ERR_OBJECTIVE_NOT_ADDRESSED`."

    Design: Corner/state_machines/advance_to_fabrication_requires_every_objective_code_to_be_carried_by_a_case_or_an_interactive
    """
    ctx = _design_dev_project_with_one_carried_objective(api)
    project_id = ctx["project_id"]

    refused = api.advance_phase(
        project_id, factories.advance_phase_payload(Phase.FABRICATION), PM
    )
    validate_error(refused, ERR_OBJECTIVE_NOT_ADDRESSED)

    interactive = fixtures.create_interactive(api, project_id)
    assert interactive["objective_code"] == OBJECTIVE_SECONDARY

    advanced = fixtures.advance(api, project_id, Phase.FABRICATION)
    assert advanced["phase"] == Phase.FABRICATION
    assert ctx["case"]["objective_code"] == OBJECTIVE_PRIMARY
