"""Loops that re-enter a state they already left: reschedule, review, retraining."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    validate_error,
)
from test_helpers import api_client as api
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]


# ---------------------------------------------------------------------------
# The reschedule cycle
# ---------------------------------------------------------------------------


def _booking_ready_to_reschedule():
    fx.pin_clock(CLOCK_START)
    return fx.setup_tour_scene(rep_count=1)


def test_reschedule_cycle_runs_twice_and_returns_to_scheduled_each_time():
    """Two full cycles land back on SCHEDULED with the count at 1 and then 2.

    The PRD states: "The second leg takes the booking `RESCHEDULE_PENDING →
    SCHEDULED` by committing a `new_scheduled_start_utc`."

    Design: Difficulty/non_linear_state_machine/booking_reschedule_cycle_twice_then_third_request_blocked
    """
    scene = _booking_ready_to_reschedule()
    booking_id = scene["booking"]["id"]

    pending = fx.get_success_data(
        api.open_reschedule_request(
            booking_id,
            fx.factories.reschedule_request_payload("Prospect flight delayed"),
            MARKETING,
        )
    )
    assert pending["status"] == "RESCHEDULE_PENDING"
    assert pending["reschedule_count"] == 0

    first = fx.get_success_data(
        api.commit_reschedule(
            booking_id,
            fx.factories.reschedule_commit_payload("2026-08-15T07:00:00Z"),
            MARKETING,
        )
    )
    assert first["status"] == "SCHEDULED"
    assert first["reschedule_count"] == 1

    fx.get_success_data(
        api.open_reschedule_request(
            booking_id,
            fx.factories.reschedule_request_payload("Rental car unavailable"),
            MARKETING,
        )
    )
    second = fx.get_success_data(
        api.commit_reschedule(
            booking_id,
            fx.factories.reschedule_commit_payload("2026-08-16T07:00:00Z"),
            MARKETING,
        )
    )
    assert second["status"] == "SCHEDULED"
    assert second["reschedule_count"] == 2
    assert_instant_equals(
        second["scheduled_start_utc"], "2026-08-16T07:00:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        second["scheduled_end_utc"], "2026-08-16T09:00:00Z", "scheduled_end_utc"
    )
    assert second["reschedule_reason"] == "Rental car unavailable"


def test_third_reschedule_request_is_refused_and_changes_nothing():
    """The loop terminates on its own count, leaving the booking untouched.

    The PRD states: "The first leg takes the booking `SCHEDULED →
    RESCHEDULE_PENDING` and records the supplied `reason` as `reschedule_reason`;
    it requires `reschedule_count` to be strictly below 2, otherwise it is
    rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/booking_reschedule_cycle_twice_then_third_request_blocked
    """
    scene = _booking_ready_to_reschedule()
    booking_id = scene["booking"]["id"]
    gallery_id = scene["gallery"]["id"]

    assert fx.read_gallery(gallery_id)["booked_slot_count"] == 1

    for reason, new_start in (
        ("Prospect flight delayed", "2026-08-15T07:00:00Z"),
        ("Rental car unavailable", "2026-08-16T07:00:00Z"),
    ):
        fx.get_success_data(
            api.open_reschedule_request(
                booking_id, fx.factories.reschedule_request_payload(reason), MARKETING
            )
        )
        assert fx.read_gallery(gallery_id)["booked_slot_count"] == 1
        fx.get_success_data(
            api.commit_reschedule(
                booking_id,
                fx.factories.reschedule_commit_payload(new_start),
                MARKETING,
            )
        )

    refused = api.open_reschedule_request(
        booking_id,
        fx.factories.reschedule_request_payload("Third attempt must be refused"),
        MARKETING,
    )
    validate_error(refused, ApiErrorId.ERR_RESCHEDULE_LIMIT_EXCEEDED.value)

    unchanged = fx.read_booking(booking_id)
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["reschedule_count"] == 2
    assert unchanged["qualification_score"] == 80
    assert fx.read_gallery(gallery_id)["booked_slot_count"] == 1


# ---------------------------------------------------------------------------
# The review cycle
# ---------------------------------------------------------------------------


def _fully_disclosed_presentation_on_a_two_rep_gallery():
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(rep_count=2, issue_incentive_gift=False)
    fx.acknowledge_required_disclosures(
        scene["presentation"]["id"], scene["assigned_rep_id"]
    )
    return scene


def test_review_status_reenters_flagged_after_it_has_been_cleared():
    """FLAGGED to CLEARED and back to FLAGGED drives flag_count to 2.

    The PRD states: "When the auto-flag condition holds after the append,
    `review_status` moves to `FLAGGED` — from `UNREVIEWED` or from `CLEARED`,
    since a previously cleared presentation can be re-flagged when new findings
    land — and `flag_count` rises by one."

    Design: Difficulty/non_linear_state_machine/presentation_review_flagged_cleared_flagged_loop
    """
    scene = _fully_disclosed_presentation_on_a_two_rep_gallery()
    presentation_id = scene["presentation"]["id"]

    flagged = fx.review_presentation(presentation_id, "FLAG", OFFICER_ALPHA)
    assert flagged["review_status"] == "FLAGGED"
    assert flagged["flag_count"] == 1
    assert flagged["disclosure_status"] == "COMPLETE"

    cleared = fx.review_presentation(presentation_id, "CLEAR", OFFICER_ALPHA)
    assert cleared["review_status"] == "CLEARED"
    assert cleared["flag_count"] == 1
    assert cleared["disclosure_status"] == "COMPLETE"

    fx.file_claim_finding(
        presentation_id,
        "EGREGIOUS",
        cleared["version"],
        claim_code="GUARANTEED_RESALE",
        headers=OFFICER_BRAVO,
    )

    reflagged = fx.read_presentation(presentation_id)
    assert reflagged["review_status"] == "FLAGGED"
    assert reflagged["flag_count"] == 2
    assert reflagged["disclosure_status"] == "COMPLETE"
    assert reflagged["prohibited_claim_points"] == 40
    assert reflagged["compliance_score"] == 60


def test_clearing_never_gives_back_a_strike_so_the_second_flag_suspends():
    """The loop is asymmetric: strikes accumulate across both entries into FLAGGED.

    The PRD states: "Clearing a presentation does *not* decrement the
    representative's `compliance_strike_count`; strikes are reset only by a
    completed retraining."

    Design: Difficulty/non_linear_state_machine/presentation_review_flagged_cleared_flagged_loop
    """
    scene = _fully_disclosed_presentation_on_a_two_rep_gallery()
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]

    fx.review_presentation(presentation_id, "FLAG", OFFICER_ALPHA)
    assert fx.read_representative(rep_id)["compliance_strike_count"] == 1

    cleared = fx.review_presentation(presentation_id, "CLEAR", OFFICER_ALPHA)
    assert fx.read_representative(rep_id)["compliance_strike_count"] == 1

    finding = fx.file_claim_finding(
        presentation_id,
        "EGREGIOUS",
        cleared["version"],
        claim_code="GUARANTEED_RESALE",
        headers=OFFICER_BRAVO,
    )
    assert finding["penalty_points"] == 40

    representative = fx.read_representative(rep_id)
    assert representative["compliance_strike_count"] == 2
    assert representative["status"] == "SUSPENDED"
    assert fx.read_gallery(scene["gallery"]["id"])["status"] == "OPEN"


# ---------------------------------------------------------------------------
# The retraining cycle
# ---------------------------------------------------------------------------


def _assigned_retraining_on_a_two_rep_gallery():
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    reps = fx.create_representatives(gallery["id"], 2)
    assignment = fx.assign_retraining(
        reps[0]["id"],
        reps[0]["version"],
        "DISCLOSURE_GAP",
        required_module_count=3,
    )
    return {"gallery": gallery, "reps": reps, "assignment": assignment}


def test_failed_retraining_reopens_for_a_second_cycle():
    """FAILED is not terminal: reassignment raises the cycle and resets progress.

    The PRD states: "It raises `cycle_index` by one, re-stamps `assigned_at` from
    the logical clock, resets `modules_completed` to 0, and resets both
    `started_at` and `closed_at` to null."

    Design: Difficulty/non_linear_state_machine/retraining_assignment_failed_reassign_cycle
    """
    scene = _assigned_retraining_on_a_two_rep_gallery()
    assignment_id = scene["assignment"]["id"]
    rep_id = scene["reps"][0]["id"]

    started = fx.start_retraining(assignment_id)
    assert started["status"] == "IN_PROGRESS"
    assert fx.read_representative(rep_id)["status"] == "RETRAINING"

    failed = fx.close_retraining(assignment_id, "FAIL", 1)
    assert failed["status"] == "FAILED"
    assert failed["modules_completed"] == 1
    assert fx.read_representative(rep_id)["status"] == "RETRAINING"

    reassigned = fx.reassign_retraining(assignment_id)
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["cycle_index"] == 2
    assert reassigned["modules_completed"] == 0
    assert reassigned["started_at"] is None
    assert reassigned["closed_at"] is None
    assert fx.read_gallery(scene["gallery"]["id"])["status"] == "OPEN"


def test_completing_the_second_cycle_restores_the_representative():
    """The exit from the loop resets strikes and returns the rep to the rotation.

    The PRD states: "the representative's `compliance_strike_count` is reset to 0
    — the only mechanism in the system that resets strikes; the representative
    returns to `ACTIVE`, but only when no other assignment for them still sits in
    `ASSIGNED` or `IN_PROGRESS`; and the gallery's `available_rep_count` is
    recomputed, so a `RESTRICTED` gallery whose count has reached at least 1
    returns to `OPEN`."

    Design: Difficulty/non_linear_state_machine/retraining_assignment_failed_reassign_cycle
    """
    scene = _assigned_retraining_on_a_two_rep_gallery()
    assignment_id = scene["assignment"]["id"]
    rep_id = scene["reps"][0]["id"]

    fx.start_retraining(assignment_id)
    fx.close_retraining(assignment_id, "FAIL", 1)
    fx.reassign_retraining(assignment_id)
    fx.start_retraining(assignment_id)
    completed = fx.close_retraining(assignment_id, "COMPLETE", 3)

    assert completed["status"] == "COMPLETED"
    assert completed["cycle_index"] == 2
    assert completed["modules_completed"] == 3
    assert completed["strike_count_at_assignment"] == 0

    representative = fx.read_representative(rep_id)
    assert representative["status"] == "ACTIVE"
    assert representative["compliance_strike_count"] == 0
    assert fx.read_gallery(scene["gallery"]["id"])["status"] == "OPEN"
