"""Layered guards and the immediate-consistency model of the write path.

Each test builds its own commission from an empty database with the logical
clock at its documented default, then pins the exact token values, derived
counters, money buckets and derived envelopes the PRD computes at the instant of
each write.
"""

from test_helpers import (
    ACCESSIBILITY,
    CONSERVATOR,
    CURATOR,
    DEFAULT_CLOCK,
    ERR_STALE_PROJECT_VERSION,
    FABRICATION,
    OPERATIONS,
    PM,
    ROLE_CONSERVATOR,
    ROLE_CURATOR,
    ROLE_PROJECT_MANAGER,
    USER_CONSERVATOR,
    USER_CURATOR,
    CaseDecision,
    CaseStatus,
    ComplexityTier,
    DrawingDecision,
    DrawingStatus,
    FinishGrade,
    MaterialDecision,
    MaterialStatus,
    MountStatus,
    PackageStage,
    PackageStatus,
    Phase,
    PlacementStatus,
    Posture,
    RoundStatus,
    UsedIn,
    VoteDecision,
    assert_common_fields,
    assert_counters,
    assert_empty_envelope,
    assert_envelope,
    assert_geometry,
    assert_index,
    assert_ledger,
    assert_zone_slot_identity,
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


def _assert_page(response, total_count, has_more=False, limit=10, offset=0):
    """Pin the four pagination fields the PRD returns on every list response."""
    meta = response.json()["meta"]
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more
    assert meta["limit"] == limit
    assert meta["offset"] == offset


def _assert_at_clock(actual, instant):
    """Assert a stamped timestamp names the same UTC instant as the clock."""
    assert is_iso8601_timestamp(actual), actual
    assert actual[:19] == instant[:19], "%s does not stamp %s" % (actual, instant)


def test_the_project_token_is_consumed_by_every_write_and_a_stale_one_is_refused(api):
    """Every project write consumes the token, and a stale token is refused with 412.

    "Creating a design package under a project requires
    `expected_project_version` in the request body. It is not optional. Its value
    must equal the owning project's currently stored `version`; if the project's
    version has advanced since the client last read it, the create is rejected
    with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    "Resources that can be mutated after creation additionally carry an
    `updated_at` timestamp in the same format and an integer `version` that starts
    at 1 on creation and increments by exactly 1 on every mutation that touches the
    row — including mutations the caller did not ask for directly, such as a
    counter refreshed by a cascade."

    "Issuing a package **supersedes** the project's earlier package of the same
    stage. Every existing package of this project whose `stage` matches the new
    one and whose status is not already `SUPERSEDED` — that is, any package in
    `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED` or `APPROVED` — transitions to
    `SUPERSEDED`, processed in ascending `created_at` order, and has its
    `superseded_by_package_id` set to the new package's identifier."

    "Every review round still `OPEN` on a superseded package is closed as
    `CLOSED_SUPERSEDED` with its `decided_at` set to the current logical-clock
    instant."

    "`open_revision_count`, the number of the project's design packages sitting in
    `REVISION_REQUESTED`"

    Design: Corner/cross_cutting_complexity_layers/the_project_token_is_consumed_by_every_write_and_a_stale_one_is_refused_with_412
    """
    fixtures.set_clock(api)
    project_id = fixtures.create_project(api)["id"]
    fixtures.advance(api, project_id, Phase.SCHEMATIC)

    token_the_client_read = fixtures.read_project(api, project_id, PM)
    assert token_the_client_read["version"] == 2
    assert_counters(
        token_the_client_read, open_revision_count=0, posture=Posture.OPEN
    )
    stale_token = token_the_client_read["version"]

    first_package = get_success_data(
        api.create_design_package(
            project_id,
            factories.design_package_payload(stale_token, stage=PackageStage.SCHEMATIC),
            PM,
        ),
        201,
    )
    assert first_package["status"] == PackageStatus.DRAFT
    assert_index(first_package["flow_capacity_score"], 100.00)
    assert first_package["superseded_by_package_id"] is None
    assert_common_fields(first_package, expected_version=1)

    replay_of_the_consumed_token = api.create_design_package(
        project_id,
        factories.design_package_payload(stale_token, stage=PackageStage.SCHEMATIC),
        PM,
    )
    validate_error(replay_of_the_consumed_token, ERR_STALE_PROJECT_VERSION, 412)

    after_one_write = fixtures.read_project(api, project_id, PM)
    assert after_one_write["version"] == stale_token + 1 == 3

    live_round = fixtures.open_round(
        api,
        first_package["id"],
        headers=PM,
        panel_roles=[ROLE_CURATOR, ROLE_CONSERVATOR, ROLE_PROJECT_MANAGER],
        decision_deadline_at="2026-08-20T00:00:00Z",
    )
    assert live_round["status"] == RoundStatus.OPEN

    replay_two_writes_behind = api.create_design_package(
        project_id,
        factories.design_package_payload(stale_token, stage=PackageStage.SCHEMATIC),
        PM,
    )
    validate_error(replay_two_writes_behind, ERR_STALE_PROJECT_VERSION, 412)

    after_two_writes = fixtures.read_project(api, project_id, PM)
    assert after_two_writes["version"] == 4
    assert_counters(after_two_writes, open_revision_count=0, posture=Posture.OPEN)
    current_token = after_two_writes["version"]

    second_package = get_success_data(
        api.create_design_package(
            project_id,
            factories.design_package_payload(
                current_token, stage=PackageStage.SCHEMATIC
            ),
            PM,
        ),
        201,
    )
    assert second_package["status"] == PackageStatus.DRAFT
    assert second_package["superseded_by_package_id"] is None

    displaced = get_success_data(
        api.get_design_package(first_package["id"], ACCESSIBILITY), 200
    )
    assert displaced["status"] == PackageStatus.SUPERSEDED
    assert displaced["superseded_by_package_id"] == second_package["id"]
    assert displaced["version"] > first_package["version"]

    closed_round = get_success_data(api.get_review_round(live_round["id"], CURATOR), 200)
    assert closed_round["status"] == RoundStatus.CLOSED_SUPERSEDED
    _assert_at_clock(closed_round["decided_at"], DEFAULT_CLOCK)

    after_the_cascade = fixtures.read_project(api, project_id, PM)
    assert after_the_cascade["version"] == 5
    assert_counters(
        after_the_cascade, open_revision_count=0, posture=Posture.OPEN
    )


def test_every_derived_counter_is_recomputed_at_the_instant_its_source_row_changes(api):
    """Counters, slot ledger and money buckets agree with a recount after every write.

    "`pending_material_count`, the number of its material specifications whose
    status is `SUBMITTED` or `CONSERVATOR_REVIEW`"

    "Posture is then evaluated in this exact order, first match winning. If
    `conservation_block_count` is greater than zero, posture is
    `FROZEN_CONSERVATION`. Otherwise, if `open_revision_count` is greater than
    zero, or `conditional_case_count` is greater than zero, or
    `pending_material_count` is greater than zero, posture is `RESTRICTED`.
    Otherwise posture is `OPEN`."

    "The three results land in `estimate_labor_cents`, `estimate_material_cents`
    and `estimate_finishing_cents`, with `estimate_total_cents` as their sum, and
    **no money moves** — the estimate is advisory."

    "On success the amount moves out of `uncommitted_cents` and into
    `committed_fabrication_cents`, the project's `updated_at` and `version`
    advance, and the sheet's `version` advances."

    "On success the case becomes `APPROVED`, its `conditions` is set to null, and
    the zone reserves the slot: `reserved_case_slots` rises by one and
    `available_case_slots` falls by one, preserving the capacity identity, with the
    zone's own `updated_at` and `version` advancing."

    "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the
    setpoint: the already-rounded cubic-metre volume multiplied by
    `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily
    air exchange, rounded half up to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/every_derived_counter_is_recomputed_at_the_instant_its_source_row_changes
    """
    ctx = fixtures.project_in_phase(api, Phase.FABRICATION)
    project_id = ctx["project_id"]
    case_id = ctx["case_id"]
    zone_id = ctx["zone_id"]
    fixtures.place_artifact(api, case_id, ctx["artifact_id"])
    fixtures.approve_case(api, case_id)

    reconciled_at_zero = fixtures.read_project(api, project_id, PM)
    assert_counters(
        reconciled_at_zero,
        pending_material_count=0,
        conditional_case_count=0,
        conservation_block_count=0,
        blocking_punch_count=0,
        posture=Posture.OPEN,
    )
    assert_ledger(reconciled_at_zero, 0, 9000000)

    housing = fixtures.create_material(
        api,
        project_id,
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    assert housing["status"] == MaterialStatus.SUBMITTED

    on_the_child_create = fixtures.read_project(api, project_id, PM)
    assert_counters(
        on_the_child_create, pending_material_count=1, posture=Posture.RESTRICTED
    )

    pending_listing = api.list_material_specs(
        project_id, PM, {"status": MaterialStatus.SUBMITTED}
    )
    rows = _rows(pending_listing)
    assert [row["id"] for row in rows] == [housing["id"]]
    _assert_page(pending_listing, total_count=1)

    in_conservator_review = get_success_data(
        api.submit_material_for_conservation(housing["id"], FABRICATION), 200
    )
    assert in_conservator_review["status"] == MaterialStatus.CONSERVATOR_REVIEW

    within_the_pending_set = fixtures.read_project(api, project_id, PM)
    assert_counters(
        within_the_pending_set, pending_material_count=1, posture=Posture.RESTRICTED
    )

    approved_material = get_success_data(
        api.material_conservator_decision(
            housing["id"],
            factories.material_decision_payload(MaterialDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    assert approved_material["status"] == MaterialStatus.APPROVED

    counted_back_down = fixtures.read_project(api, project_id, PM)
    assert_counters(
        counted_back_down, pending_material_count=0, posture=Posture.OPEN
    )

    sheet = fixtures.create_drawing(
        api,
        project_id,
        housing["id"],
        drawing_number="SD-601",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=10.0,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
        subject_case_id=case_id,
    )
    assert sheet["status"] == DrawingStatus.SUBMITTED
    assert sheet["estimate_labor_cents"] == 109250
    assert sheet["estimate_material_cents"] == 57000
    assert sheet["estimate_finishing_cents"] == 0
    assert sheet["estimate_total_cents"] == 166250
    assert sheet["actual_cost_cents"] is None

    nothing_committed_by_an_estimate = fixtures.read_project(api, project_id, PM)
    assert_ledger(nothing_committed_by_an_estimate, 0, 9000000)

    get_success_data(api.start_drawing_review(sheet["id"], PM), 200)
    ruled = get_success_data(
        api.drawing_decision(
            sheet["id"],
            factories.drawing_decision_payload(
                DrawingDecision.APPROVE, actual_shop_hours=10.0, actual_waste_factor=1.0
            ),
            PM,
        ),
        200,
    )
    assert ruled["actual_labor_cents"] == 95000
    assert ruled["actual_material_cents"] == 47500
    assert ruled["actual_finishing_cents"] == 0
    assert ruled["actual_cost_cents"] == 142500

    money_at_the_instant_of_approval = fixtures.read_project(api, project_id, PM)
    assert_ledger(money_at_the_instant_of_approval, 142500, 8857500)

    slot_ledger = get_success_data(api.get_gallery_zone(zone_id, OPERATIONS), 200)
    assert slot_ledger["case_slot_capacity"] == 2
    assert_zone_slots(slot_ledger, 1, 1)
    assert_zone_slot_identity(slot_ledger)

    loaded_case = get_success_data(api.get_artifact_case(case_id, CURATOR), 200)
    assert_envelope(
        loaded_case,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
    )
    assert_geometry(loaded_case, 0.648, 0.91)

    single_source_row = api.list_artifacts(
        project_id, CURATOR, {"assigned_case_id": case_id}
    )
    contents = _rows(single_source_row)
    assert [row["accession_number"] for row in contents] == ["2019.14.3"]
    _assert_page(single_source_row, total_count=1)


def test_the_resolving_vote_returns_the_new_tally_and_the_resolution_together(api):
    """The vote answers with the updated round, and the cascade is visible at once.

    "An accepted vote is appended and the four tallies are recomputed:
    `cast_vote_count` rises by one, and exactly one of `approve_count`,
    `revise_count` or `veto_count` rises with it."

    "The response to a vote is the **updated round**, not the vote row, so the
    caller sees the new tally and the round's resolved status in the same reply;
    the individual votes are readable through the round's own vote list, oldest
    first."

    "A round that reaches quorum with every vote an approval, that is with
    `cast_vote_count` equal to `required_vote_count` and `approve_count` equal to
    `required_vote_count`, becomes `APPROVED`."

    "In all three cases `decided_at` is set to the current logical-clock instant
    and the round's `updated_at` and `version` are refreshed."

    "An `APPROVED` round drives its package `IN_REVIEW → APPROVED`, sets the
    package's `approved_at` to the logical-clock instant, and recomputes the
    project's `open_revision_count` and posture."

    Design: Corner/consistency_model/the_resolving_vote_returns_the_new_tally_and_the_resolution_in_one_response
    """
    ctx = fixtures.project_in_phase(api, Phase.DESIGN_DEV)
    project_id = ctx["project_id"]

    package = fixtures.create_package(
        api, project_id, stage=PackageStage.DESIGN_DEV, headers=PM
    )
    seated_round = fixtures.open_round(
        api,
        package["id"],
        headers=PM,
        panel_roles=[ROLE_CURATOR, ROLE_CONSERVATOR, ROLE_PROJECT_MANAGER],
        decision_deadline_at="2026-08-20T08:00:00Z",
    )
    assert seated_round["required_vote_count"] == 2
    assert seated_round["status"] == RoundStatus.OPEN

    first_vote_answer = get_success_data(
        api.cast_vote(
            seated_round["id"],
            factories.vote_payload(
                VoteDecision.APPROVE,
                comment="Storyline reads clearly at the schematic level.",
            ),
            CURATOR,
        ),
        201,
    )
    assert first_vote_answer["id"] == seated_round["id"]
    assert "voter_role" not in first_vote_answer
    assert first_vote_answer["cast_vote_count"] == 1
    assert first_vote_answer["approve_count"] == 1
    assert first_vote_answer["revise_count"] == 0
    assert first_vote_answer["veto_count"] == 0
    assert first_vote_answer["status"] == RoundStatus.OPEN
    assert first_vote_answer["decided_at"] is None

    package_moved_when_the_round_opened = get_success_data(
        api.get_design_package(package["id"], CURATOR), 200
    )
    assert package_moved_when_the_round_opened["status"] == PackageStatus.IN_REVIEW
    assert package_moved_when_the_round_opened["review_round_count"] == 1
    assert package_moved_when_the_round_opened["approved_at"] is None

    resolving_vote_answer = get_success_data(
        api.cast_vote(
            seated_round["id"], factories.vote_payload(VoteDecision.APPROVE), CONSERVATOR
        ),
        201,
    )
    assert resolving_vote_answer["id"] == seated_round["id"]
    assert resolving_vote_answer["cast_vote_count"] == 2
    assert (
        resolving_vote_answer["cast_vote_count"]
        == resolving_vote_answer["required_vote_count"]
    )
    assert resolving_vote_answer["approve_count"] == 2
    assert resolving_vote_answer["revise_count"] == 0
    assert resolving_vote_answer["veto_count"] == 0
    assert resolving_vote_answer["status"] == RoundStatus.APPROVED
    _assert_at_clock(resolving_vote_answer["decided_at"], DEFAULT_CLOCK)

    cascaded_package = get_success_data(
        api.get_design_package(package["id"], CONSERVATOR), 200
    )
    assert cascaded_package["status"] == PackageStatus.APPROVED
    assert cascaded_package["revision_count"] == 0
    _assert_at_clock(cascaded_package["approved_at"], DEFAULT_CLOCK)

    project_after_the_cascade = fixtures.read_project(api, project_id, PM)
    assert_counters(
        project_after_the_cascade, open_revision_count=0, posture=Posture.OPEN
    )
    assert project_after_the_cascade["phase"] == Phase.DESIGN_DEV

    ballots = api.list_votes(seated_round["id"], OPERATIONS)
    rows = _rows(ballots)
    assert len(rows) == 2
    _assert_page(ballots, total_count=2)
    assert rows[0]["voter_role"] == ROLE_CURATOR
    assert rows[0]["voter_user_id"] == USER_CURATOR
    assert rows[0]["comment"] == "Storyline reads clearly at the schematic level."
    assert rows[1]["voter_role"] == ROLE_CONSERVATOR
    assert rows[1]["voter_user_id"] == USER_CONSERVATOR
    assert rows[1]["decision"] == VoteDecision.APPROVE
    assert rows[1]["comment"] is None


def test_a_write_that_returns_a_different_entity_leaves_no_stale_read_behind(api):
    """The placement answers with the object while the case it rewrites is already current.

    "A successful placement sets the object's `assigned_case_id` to the case, moves
    its `placement_status` `UNPLACED → RESERVED`, increments the case's
    `placed_artifact_count`, and rewrites `required_rh_min_pct`,
    `required_rh_max_pct`, `allowed_lux`, `env_feasible` and `security_ok` from the
    new set."

    "The response is the updated object."

    "When it is not empty, `required_rh_min_pct` becomes the **largest** of the
    objects' individual humidity floors, `required_rh_max_pct` becomes the
    **smallest** of their humidity ceilings, and `allowed_lux` becomes the
    **smallest** of their `max_lux` values."

    "Because the case is empty, `required_rh_min_pct`, `required_rh_max_pct` and
    `allowed_lux` are all null while `env_feasible` and `security_ok` are both
    true."

    "Designing a case does **not** touch the zone's slot counters; a slot is only
    consumed when a conservator approves the case."

    "`case_volume_m3` is the product of the three interior dimensions in
    centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic
    metre — rounded half up to four decimal places."

    "On success the case becomes `APPROVED`, its `conditions` is set to null, and
    the zone reserves the slot: `reserved_case_slots` rises by one and
    `available_case_slots` falls by one, preserving the capacity identity, with the
    zone's own `updated_at` and `version` advancing."

    Design: Corner/consistency_model/a_write_that_returns_a_different_entity_still_leaves_no_stale_read_behind
    """
    ctx = fixtures.project_in_phase(api, Phase.DESIGN_DEV)
    project_id = ctx["project_id"]
    zone_id = ctx["zone_id"]
    artifact_id = ctx["artifact_id"]

    case_create_answer = get_success_data(
        api.create_artifact_case(
            project_id,
            factories.artifact_case_payload(
                zone_id,
                case_code="C-02",
                objective_code=factories.OBJECTIVE_SECONDARY,
            ),
            CURATOR,
        ),
        201,
    )
    case_id = case_create_answer["id"]
    assert_common_fields(case_create_answer, expected_version=1)
    assert case_create_answer["status"] == CaseStatus.DRAFT
    assert case_create_answer["mount_status"] == MountStatus.NOT_STARTED
    assert case_create_answer["conditions"] is None
    assert case_create_answer["decided_at"] is None
    assert_empty_envelope(case_create_answer)
    assert_geometry(case_create_answer, 0.648, 0.91)

    zone_before_any_approval = get_success_data(
        api.get_gallery_zone(zone_id, OPERATIONS), 200
    )
    assert_zone_slots(zone_before_any_approval, 0, 2)
    assert_zone_slot_identity(zone_before_any_approval)

    placement_answer = get_success_data(
        api.create_placement(
            case_id, factories.placement_payload(artifact_id, 1), CURATOR
        ),
        201,
    )
    assert placement_answer["id"] == artifact_id
    assert placement_answer["accession_number"] == "2019.14.3"
    assert placement_answer["placement_status"] == PlacementStatus.RESERVED
    assert placement_answer["assigned_case_id"] == case_id
    assert "placed_artifact_count" not in placement_answer

    case_the_write_did_not_return = get_success_data(
        api.get_artifact_case(case_id, CONSERVATOR), 200
    )
    assert case_the_write_did_not_return["version"] == 2
    assert case_the_write_did_not_return["status"] == CaseStatus.DRAFT
    assert_envelope(
        case_the_write_did_not_return,
        placed_artifact_count=1,
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )

    submitted = get_success_data(
        api.submit_case_for_conservation(case_id, CURATOR), 200
    )
    assert submitted["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert submitted["version"] == 3

    approved = get_success_data(
        api.case_conservator_decision(
            case_id, factories.case_decision_payload(CaseDecision.APPROVE), CONSERVATOR
        ),
        200,
    )
    assert approved["status"] == CaseStatus.APPROVED
    assert approved["version"] == 4
    assert approved["conditions"] is None
    assert approved["mount_status"] == MountStatus.NOT_STARTED
    _assert_at_clock(approved["decided_at"], DEFAULT_CLOCK)

    project_after_the_ruling = fixtures.read_project(api, project_id, PM)
    assert_counters(
        project_after_the_ruling,
        conditional_case_count=0,
        conservation_block_count=0,
        posture=Posture.OPEN,
    )

    zone_after_the_ruling = get_success_data(
        api.get_gallery_zone(zone_id, OPERATIONS), 200
    )
    assert_zone_slots(zone_after_the_ruling, 1, 1)
    assert_zone_slot_identity(zone_after_the_ruling)

    contents = api.list_artifacts(project_id, CURATOR, {"assigned_case_id": case_id})
    rows = _rows(contents)
    assert [row["placement_status"] for row in rows] == [PlacementStatus.RESERVED]
    _assert_page(contents, total_count=1)
