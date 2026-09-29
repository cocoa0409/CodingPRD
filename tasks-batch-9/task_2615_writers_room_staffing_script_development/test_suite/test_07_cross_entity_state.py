"""Writes whose legality is decided on entities the request never names.

Creating an assignment reads a seat and that seat's room; locking an episode
reads a clearance review hanging off the assignment and the items under it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import LEGAL_COUNSEL_HEADERS, STUDIO_EXECUTIVE_HEADERS

WAIVER_MEMO = "Business affairs accepts the residual risk; E&O carrier notified."


def _offered_seat_and_episode(api):
    """A STAFFING room with one unanswered offer, and an episode waiting for a script."""
    world = X.build_staffing_room_world(api)
    episode = X.seed_episode(api, world["season_id"], 1)
    world["ep1_id"] = episode["id"]
    world["ep1_version"] = episode["version"]
    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
    )
    world["s1_id"] = seat["id"]
    return world


def _teleplay_payload(world, expected_episode_version):
    """The identical assignment request used at all three points of the table."""
    return F.build_script_assignment(
        world["w1_id"], expected_episode_version, assignment_type="TELEPLAY"
    )


def _assignments_of(api, episode_id):
    """Every script assignment recorded against one episode."""
    rows, _ = validate_paginated(
        api.list_script_assignments(
            STUDIO_EXECUTIVE_HEADERS, {"episode_id": episode_id, "limit": 100}
        )
    )
    return rows


def _conditional_review_world(api):
    """A ready episode whose approved teleplay carries one conditional depiction."""
    world = X.build_clearance_world(api)
    item = X.seed_clearance_item(
        api,
        world["review_id"],
        "DEPICTION",
        "Real hospital shown mid-malpractice",
        "3B",
    )
    world["item1_id"] = item["id"]
    X.decide_item(
        api,
        item["id"],
        "CONDITIONAL",
        "Signage must be redressed before the location day.",
    )
    world["review"] = X.read_review(api, world["review_id"])
    return world


def test_a_confirmed_seat_in_a_staffing_room_is_still_not_a_staffed_writer(api):
    """The same body is refused with the seat OFFERED and again once it is CONFIRMED.

    PRD: "The system resolves the assignment's `room_seat_id` by filtering to seats of the named writer whose status is `CONFIRMED` in a writers room belonging to this episode's season whose own status is `ACTIVE`; candidates are ranked by the seat's `confirmed_at` ascending with the seat's `created_at` breaking ties, and the first candidate is stored on the assignment."

    PRD: "There is no freelance path in this system: an empty candidate set is rejected with `ERR_WRITER_NOT_STAFFED`."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_requires_confirmed_seat_and_active_room_together
    """
    world = _offered_seat_and_episode(api)
    payload = _teleplay_payload(world, world["ep1_version"])

    validate_error(
        api.create_script_assignment(world["ep1_id"], payload, world["sr_headers"]),
        ApiErrorId.WRITER_NOT_STAFFED,
    )

    A.assert_field_values(
        X.accept_seat(api, world["s1_id"], world["w1_id"]), status="CONFIRMED"
    )
    A.assert_field_values(X.read_room(api, world["room_id"]), status="STAFFING")

    validate_error(
        api.create_script_assignment(world["ep1_id"], payload, world["sr_headers"]),
        ApiErrorId.WRITER_NOT_STAFFED,
    )

    assert _assignments_of(api, world["ep1_id"]) == [], (
        "Neither refusal may leave an assignment behind"
    )
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="NOT_STARTED"
    )


def test_activating_the_room_makes_the_identical_request_succeed(api):
    """Only when both the seat and its room qualify does the selector find a candidate.

    PRD: "An episode at `NOT_STARTED` advances to `IN_PROGRESS` on its first non-void assignment."

    PRD: "An assignment inside the allocated prefix has `guarantee_slot_applied` set true, and its `guarantee_offset_cents` becomes its gross fee multiplied by the agreement's guarantee offset fraction for the level recorded on the seat's `level_at_hire`, rounded half up to whole cents; an assignment outside the prefix has the flag false and an offset of 0."

    PRD: "Each milestone is numbered by `sequence_index` starting at 1 in that chain order, copies the matching due-date field into its own `due_date`, and starts `PENDING` — or `LATE` immediately, if the logical clock has already passed that deadline at the moment the assignment is created."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_requires_confirmed_seat_and_active_room_together
    """
    world = _offered_seat_and_episode(api)
    X.accept_seat(api, world["s1_id"], world["w1_id"])
    A.assert_field_values(X.activate_room(api, world["room_id"]), status="ACTIVE")

    live_version = X.current_episode_version(api, world["ep1_id"])
    assignment = validate_success(
        api.create_script_assignment(
            world["ep1_id"],
            _teleplay_payload(world, live_version),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(
        assignment,
        status="DRAFTING",
        room_seat_id=world["s1_id"],
        guarantee_slot_applied=True,
        revision_round=0,
    )
    A.assert_assignment_settlement(assignment, 3500000, True, 1750000, 1750000)
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), script_readiness="IN_PROGRESS"
    )

    milestones = X.milestones_of(api, assignment["id"])
    assert [m["milestone_type"] for m in milestones] == [
        "OUTLINE",
        "FIRST_DRAFT",
        "SECOND_DRAFT",
    ], f"A teleplay synthesizes three milestones: {milestones}"
    A.assert_field_values(milestones[0], due_date=K.DUE_DATES_NOV_02["OUTLINE"])
    A.assert_field_values(milestones[1], due_date=K.DUE_DATES_NOV_02["FIRST_DRAFT"])
    A.assert_field_values(milestones[2], due_date=K.DUE_DATES_NOV_02["SECOND_DRAFT"])
    A.assert_field_values(
        X.read_seat(api, world["s1_id"]),
        guarantee_slots_consumed=1,
        guarantee_slots_remaining=0,
    )


def test_a_conditional_review_two_levels_away_blocks_a_ready_episode(api):
    """Nothing on the episode row changed, yet the lock is refused on the item decision.

    PRD: "Second the clearance gate: the episode's `clearance_posture` must be `CLEARED` or `CONDITIONAL_WAIVED`, and a failure is reported as `ERR_CLEARANCE_BLOCKED` when the posture is `BLOCKED` and as `ERR_CLEARANCE_NOT_CLEARED` for `PENDING`, `CONDITIONAL` or `ESCALATED` — two distinct codes for one gate, so the caller can tell a fatal exposure from an unfinished one."

    PRD: "Every later posture change is mirrored onto the episode's `clearance_posture` only when the review's `assignment_id` is the episode's `approved_teleplay_assignment_id` — clearance on a story or a superseded draft moves the review but leaves the episode's mirror alone, which is why a rewrite retains `approved_teleplay_assignment_id` even as readiness reopens."

    Design: Difficulty/cross_entity_state_dependency/episode_lock_depends_on_clearance_review_posture_of_a_different_entity
    """
    world = _conditional_review_world(api)
    A.assert_field_values(world["review"], risk_score=25, posture="CONDITIONAL")
    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        script_readiness="READY",
        clearance_posture="CONDITIONAL",
        approved_teleplay_assignment_id=world["a1_id"],
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]), ready_script_count=0, coverage_gap=1
    )

    validate_error(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.CLEARANCE_NOT_CLEARED,
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        script_readiness="READY",
        locked_at=None,
    )


def test_a_waiver_granted_on_the_review_unblocks_the_episode(api):
    """The release valve is applied to the review, and the episode inherits it.

    PRD: "The waiver moves `posture` to `CONDITIONAL_WAIVED`, sets `legal_waiver_granted` true, stores the `waiver_memo`, mirrors `CONDITIONAL_WAIVED` onto the episode's `clearance_posture`, recomputes the season's coverage figures — the episode now counts as a ready script — and increments the review's `version`."

    PRD: "a waiver on a `PENDING`, `CLEARED`, `ESCALATED` or `BLOCKED` review — or on one already waived — is rejected with `ERR_WAIVER_NOT_APPLICABLE`."

    Design: Difficulty/cross_entity_state_dependency/episode_lock_depends_on_clearance_review_posture_of_a_different_entity
    """
    world = _conditional_review_world(api)

    waived = validate_success(
        api.grant_clearance_waiver(
            world["review_id"], F.build_waiver(WAIVER_MEMO), LEGAL_COUNSEL_HEADERS
        )
    )
    A.assert_field_values(
        waived,
        posture="CONDITIONAL_WAIVED",
        legal_waiver_granted=True,
        waiver_memo=WAIVER_MEMO,
        risk_score=25,
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]), clearance_posture="CONDITIONAL_WAIVED"
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=1,
        coverage_gap=0,
        coverage_posture="COVERED",
    )

    locked = validate_success(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(locked, script_readiness="LOCKED")
    A.assert_instant(locked["locked_at"], K.CLOCK_EPOCH, "locked_at")

    validate_error(
        api.grant_clearance_waiver(
            world["review_id"], F.build_waiver(WAIVER_MEMO), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.WAIVER_NOT_APPLICABLE,
    )
