"""Declared transitions fire their side effects; undeclared ones change nothing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_scene,
    create_design_package_payload,
    open_project,
    place_cue,
    project_version,
    propose_segment,
    read_project,
    register_ride_system,
    setup_program_at_schematic,
    validate_error,
    validate_success,
    verify_cue,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
PROGRAMMER = TEST_USERS["show_programmer_headers"]

SWITCHBACK = {"segment_label": "Switchback A", "length_meters": 120,
              "width_meters": 2.4, "routing_type": "STANDARD", "position_index": 1}


def test_accepting_a_proposed_run_lifts_the_running_queue_total(api):
    """Acceptance is the owner's act and moves a segment from `PROPOSED` to `ACCEPTED`. It requires the posture not to be `FROZEN`, a matching `expected_project_version`, and the programme's `virtual_queue_share_pct` to be at most forty percent as a precondition — a programme carrying a higher share cannot accept queue at all. On success the segment's `capacity_guests` is added to the programme's `queue_capacity_total_guests` and the programme's `version` advances.

    Segments are created `PROPOSED` and their capacity is not yet part of any
    programme total.

    The proposed switchback holds 443 guests and none of them counted; one
    acceptance moves the run to ACCEPTED, carries the programme total from 0 to
    exactly 443 and advances the programme to revision 2.

    Design: Corner/state_machines/queue_segment_accept_moves_proposed_to_accepted_and_lifts_the_running_total
    """
    project = open_project(project_code="TAD-SM1")
    segment = propose_segment(project["id"], **SWITCHBACK)
    assert project["queue_capacity_total_guests"] == 0

    accepted = validate_success(
        api.accept_queue_segment(segment["id"],
                                 {"expected_project_version": project["version"]},
                                 OWNER),
        200,
    )

    programme = read_project(project["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["capacity_guests"] == 443
    assert programme["queue_capacity_total_guests"] == 443
    assert programme["version"] == 2


def test_blue_sky_cannot_be_left_until_one_scene_exists(api):
    """Four rungs have content gates that carry no dedicated error of their own; when the requested rung is the correct successor but one of these is unmet, the advance is rejected with `ERR_PHASE_PRECONDITION_UNMET` (HTTP 409). Moving from `BLUE_SKY` to `CONCEPT` requires at least one scene to exist for the programme, in any status.

    A new scene lands in `DRAFT` with `scene_quality_score`,
    `validating_rehearsal_run_id`, `held_from_status`, `hold_reason` and the four
    discipline scores all null.

    Concept is the correct next rung, so the refusal comes from the content gate
    rather than the sequence check; writing a single draft scene flips the identical
    request — same pinned revision and all — into a successful advance.

    Design: Corner/state_machines/advance_to_concept_without_any_show_scene_is_rejected
    """
    project = open_project(project_code="TAD-SM2")

    refused = api.advance_phase(
        project["id"],
        {"to_phase": "CONCEPT", "expected_project_version": project["version"]},
        OWNER,
    )

    validate_error(refused, ApiErrorId.ERR_PHASE_PRECONDITION_UNMET.value, 409)
    blocked = read_project(project["id"])
    assert blocked["design_phase"] == "BLUE_SKY"
    assert blocked["version"] == project["version"]

    scene = add_scene(project["id"])
    advanced = validate_success(
        api.advance_phase(
            project["id"],
            {"to_phase": "CONCEPT", "expected_project_version": project["version"]},
            OWNER,
        )
    )

    assert scene["status"] == "DRAFT"
    assert advanced["design_phase"] == "CONCEPT"
    assert advanced["version"] == 2


def test_the_ladder_refuses_both_a_skipped_rung_and_a_step_backwards(api):
    """Any `to_phase` that is not the immediate successor of the current `design_phase` is rejected with `ERR_PHASE_SEQUENCE_INVALID` (HTTP 409). That covers skipping a rung, repeating the current rung, and moving backwards. The sequence check is evaluated before any of the destination rung's content gates, so a request that is both out of sequence and short of content reports the sequence failure.

    A programme's `design_phase` moves forward only, one rung at a time, along this
    ladder: `BLUE_SKY`, `CONCEPT`, `SCHEMATIC`, `DESIGN_DEVELOPMENT`, `PRODUCTION`,
    `INSTALLATION`, `TECHNICAL_REHEARSAL`, `SOFT_OPEN`, `OPERATIONS_HANDOVER`.

    A schematic programme asked for production skips design development and is
    answered by the sequencing error, not by the missing-approved-package gate that
    production would otherwise raise; asking for blue sky again is refused for the
    same reason, and neither refusal moves the programme.

    Design: Corner/state_machines/advance_to_production_skipping_design_development_is_rejected
    """
    ctx = setup_program_at_schematic()
    project_id = ctx["project"]["id"]
    pinned = project_version(project_id)

    skipped = api.advance_phase(
        project_id, {"to_phase": "PRODUCTION", "expected_project_version": pinned}, OWNER)
    backwards = api.advance_phase(
        project_id, {"to_phase": "BLUE_SKY", "expected_project_version": pinned}, OWNER)

    validate_error(skipped, ApiErrorId.ERR_PHASE_SEQUENCE_INVALID.value, 409)
    validate_error(backwards, ApiErrorId.ERR_PHASE_SEQUENCE_INVALID.value, 409)
    programme = read_project(project_id)
    assert programme["design_phase"] == "SCHEMATIC"
    assert programme["version"] == pinned


def test_a_proposed_run_cannot_be_retired_before_it_is_accepted(api):
    """A segment in the wrong source status for either action is refused with `ERR_QUEUE_SEGMENT_STATE_INVALID`.

    Retirement is the compensating action: an `ACCEPTED` segment moves to the
    terminal `RETIRED`, again requiring an unfrozen posture and a matching
    `expected_project_version`, and its `capacity_guests` is subtracted from
    `queue_capacity_total_guests`, with the programme's `version` advancing.

    Retirement subtracts a capacity that acceptance had added, so retiring a run
    that was never accepted is refused outright — the programme total stays at 0
    instead of going negative, and the programme's revision does not move.

    Design: Corner/state_machines/queue_segment_retire_before_accept_returns_state_invalid
    """
    project = open_project(project_code="TAD-SM4")
    segment = propose_segment(project["id"], **SWITCHBACK)

    response = api.retire_queue_segment(
        segment["id"], {"expected_project_version": project["version"]}, OWNER)

    validate_error(response, ApiErrorId.ERR_QUEUE_SEGMENT_STATE_INVALID.value, 409)
    stored = validate_success(api.get_queue_segment(segment["id"], DESIGNER))
    programme = read_project(project["id"])
    assert stored["status"] == "PROPOSED"
    assert stored["capacity_guests"] == 443
    assert programme["queue_capacity_total_guests"] == 0
    assert programme["version"] == 1


def test_a_new_package_is_a_draft_at_revision_round_zero_with_final_pricing(api):
    """Either a `CreativeDirector` or an `OwnerRep` may submit, moving the package from `DRAFT` to `SUBMITTED`, provided the posture is not `FROZEN`.

    Submitting again moves `REVISION_REQUESTED` back to `SUBMITTED`, and this time
    the package's `revision_round` is incremented by one, counting the completed
    loop; `revision_round` starts at 0 and a first submission out of `DRAFT` does not
    touch it.

    It records `submitted_by_user_id` as the submitting caller's `X-User-ID`, and it
    captures `pinned_ride_system_version` as the current `version` of the ride system
    named by `ride_system_id` — the revision the drawing set was coordinated against.

    It records `approved_by_user_id` as the approving caller's `X-User-ID` and sets
    the package's `status` to `APPROVED`.

    Fourth, `total_cost_of_work_cents` is `base_construction_cost_cents` plus
    `design_fee_cents` plus `contingency_cents`, and it is never re-rounded.

    Creation prices the drawing set in full — 400000000 of construction carries a
    48000000 fee and a 67200000 contingency for a 515200000 total — while every
    field that belongs to a later act of the workflow is still empty and nothing is
    committed against the programme.

    Design: Corner/state_machines/design_package_starts_in_draft_with_zero_revision_round
    """
    project = open_project(project_code="TAD-SM5")
    ride = register_ride_system(project["id"])

    package = validate_success(
        api.create_design_package(
            create_design_package_payload(
                project["id"], ride["id"], project["version"],
                package_label="Show Set Release 1", discipline_scope="SHOW_SET",
                base_construction_cost_cents=400000000),
            DESIGNER,
        ),
        201,
    )

    assert package["status"] == "DRAFT"
    assert package["revision_round"] == 0
    assert package["pinned_ride_system_version"] is None
    assert package["submitted_by_user_id"] is None
    assert package["approved_by_user_id"] is None
    assert package["design_fee_cents"] == 48000000
    assert package["contingency_cents"] == 67200000
    assert package["total_cost_of_work_cents"] == 515200000
    assert package["version"] == 1
    assert read_project(project["id"])["committed_cost_cents"] == 0


def test_a_verified_cue_admits_no_second_verification(api):
    """A cue is created `PLANNED`; verifying it on the console advances it to the terminal `VERIFIED` and increments its `version` by one.

    The target resource is in the state its action requires —
    `ERR_RIDE_SYSTEM_STATE_INVALID`, `ERR_QUEUE_SEGMENT_STATE_INVALID`,
    `ERR_SCENE_STATE_INVALID`, `ERR_CUE_STATE_INVALID`,
    `ERR_PACKAGE_STATE_INVALID`, `ERR_REVIEW_STATE_INVALID`,
    `ERR_FINDING_STATE_INVALID`, `ERR_VE_ITEM_STATE_INVALID`,
    `ERR_REHEARSAL_STATE_INVALID` or `ERR_MAINTENANCE_STATE_INVALID` (409).

    Verification is the cue's last act, so replaying it is not answered
    idempotently: the second call is refused and the cue stays at the revision the
    first one left it on.

    Design: Corner/state_machines/verified_effect_cue_is_terminal_and_admits_no_second_verify
    """
    project = open_project(project_code="TAD-SM6")
    scene = add_scene(project["id"])
    cue = place_cue(scene["id"], cue_label="Prologue Wash",
                    discipline_channel="LIGHTING", offset_ms=0, duration_ms=2000)
    verified = verify_cue(cue["id"])
    assert verified["version"] == 2

    response = api.verify_effect_cue(cue["id"], {}, PROGRAMMER)

    validate_error(response, ApiErrorId.ERR_CUE_STATE_INVALID.value, 409)
    stored = validate_success(api.get_effect_cue(cue["id"], PROGRAMMER))
    assert stored["status"] == "VERIFIED"
    assert stored["version"] == 2


def test_replaying_accept_on_a_fresh_revision_still_does_not_double_count(api):
    """A segment in the wrong source status for either action is refused with `ERR_QUEUE_SEGMENT_STATE_INVALID`.

    `queue_capacity_total_guests` is the sum of `capacity_guests` over the
    programme's `ACCEPTED` segments.

    The replay carries a freshly re-read, perfectly valid revision token, so nothing
    about version pinning saves the programme here — the source-state check is what
    refuses it, and the running total stays 443 rather than doubling to 886.

    Design: Corner/state_machines/queue_segment_second_accept_returns_state_invalid_and_does_not_double_count
    """
    project = open_project(project_code="TAD-SM7")
    segment = propose_segment(project["id"], **SWITCHBACK)
    validate_success(
        api.accept_queue_segment(segment["id"],
                                 {"expected_project_version": project["version"]},
                                 OWNER)
    )
    after_first = read_project(project["id"])
    assert after_first["queue_capacity_total_guests"] == 443

    response = api.accept_queue_segment(
        segment["id"], {"expected_project_version": after_first["version"]}, OWNER)

    validate_error(response, ApiErrorId.ERR_QUEUE_SEGMENT_STATE_INVALID.value, 409)
    programme = read_project(project["id"])
    assert programme["queue_capacity_total_guests"] == 443
    assert programme["version"] == after_first["version"]
