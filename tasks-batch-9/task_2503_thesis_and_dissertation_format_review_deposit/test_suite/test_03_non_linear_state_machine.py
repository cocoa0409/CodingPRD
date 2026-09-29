"""Lifecycles that loop and lifecycles that fork into unequal branches.

The format review cycle re-enters itself with a strictly increasing cycle number
and a shrinking window, and the defense outcome forks into branches whose side
effects on the committee and on chair load genuinely differ.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.test_users import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]


def _three_cycle_revision_loop() -> dict:
    """Three format cycles: returned, returned again, and returned a third time."""
    world = fx.setup_open_format_cycle(cycle_clock="2026-10-05T09:00:00Z")
    world["cycle_one"] = fx.decide_format_review(
        world,
        world["format_review"],
        decision="RETURN_REVISIONS",
        critical_defect_count=1,
        major_defect_count=1,
        minor_defect_count=1,
        clock="2026-10-12T09:00:00Z",
        review_note="First pass: margins and pagination",
    )
    world["cycle_two"] = fx.open_format_cycle(world, clock="2026-10-14T09:00:00Z")
    world["cycle_two"] = fx.decide_format_review(
        world,
        world["cycle_two"],
        decision="RETURN_REVISIONS",
        minor_defect_count=1,
        review_note="Second pass: one caption",
    )
    world["cycle_three"] = fx.open_format_cycle(world, clock="2026-10-16T09:00:00Z")
    world["cycle_three"] = fx.decide_format_review(
        world,
        world["cycle_three"],
        decision="RETURN_REVISIONS",
        minor_defect_count=1,
        review_note="Third pass: one running head",
    )
    return world


def test_third_turn_of_the_loop_carries_cycle_number_three_and_a_five_day_window(
    api: ApiClient,
) -> None:
    """Each resubmission raises the cycle number and shortens the window.

    PRD §3.5: "A resubmission after that instant is refused with `ERR_REVISION_WINDOW_EXPIRED` (HTTP 409), which is what makes the `UNDER_FORMAT_REVIEW → FORMAT_REVISIONS_REQUIRED → UNDER_FORMAT_REVIEW` loop bounded rather than infinite; `cycle_number` strictly increases with every turn of it, so the loop is always observable in the record."

    Design: Difficulty/non_linear_state_machine/format_review_cycle_loops_and_increments_cycle_number
    """
    world = _three_cycle_revision_loop()
    cycle_three = world["cycle_three"]

    assert cycle_three["cycle_number"] == 3
    assert cycle_three["status"] == "REVISIONS_REQUIRED"
    assert cycle_three["severity_weighted_defect_score"] == pytest.approx(
        0.35, abs=0.001
    )
    assert cycle_three["turnaround_bdays"] == 0
    assert_instant(
        cycle_three["revision_due_at"], "2026-10-23T09:00:00Z", "revision_due_at"
    )

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["format_cycle_count"] == 3
    assert thesis["workflow_state"] == "FORMAT_REVISIONS_REQUIRED"

    cycles = get_success_data(
        api.list_thesis_format_reviews(world["thesis"]["id"], REGISTRAR)
    )
    assert [row["cycle_number"] for row in cycles] == [1, 2, 3]


def test_superseded_cycles_keep_the_score_and_turnaround_they_were_decided_with(
    api: ApiClient,
) -> None:
    """Reopening the loop supersedes the earlier cycles without erasing them.

    PRD §3.5: "Any existing `FormatReview` for the same document whose `status` is `REVISIONS_REQUIRED` is moved to `SUPERSEDED`, keeping its recorded score and turnaround for audit."

    Design: Difficulty/non_linear_state_machine/format_review_cycle_loops_and_increments_cycle_number
    """
    world = _three_cycle_revision_loop()

    cycle_one = get_success_data(
        api.get_format_review(world["cycle_one"]["id"], REGISTRAR)
    )
    assert cycle_one["status"] == "SUPERSEDED"
    assert cycle_one["severity_weighted_defect_score"] == pytest.approx(5.45, abs=0.001)
    assert cycle_one["turnaround_bdays"] == 5
    assert_instant(
        cycle_one["revision_due_at"], "2026-10-26T09:00:00Z", "revision_due_at"
    )

    cycle_two = get_success_data(
        api.get_format_review(world["cycle_two"]["id"], REGISTRAR)
    )
    assert cycle_two["status"] == "SUPERSEDED"
    assert cycle_two["severity_weighted_defect_score"] == pytest.approx(0.35, abs=0.001)
    assert cycle_two["turnaround_bdays"] == 0
    assert_instant(
        cycle_two["revision_due_at"], "2026-10-23T09:00:00Z", "revision_due_at"
    )

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["analyst_turnaround_bdays_total"] == 5


def _two_defenses_with_opposite_outcomes() -> dict:
    """Two candidates sharing one chair and one room, one passing and one failing."""
    world = fx.setup_announced_defense(thesis_overrides={"title": "Passing Document"})
    other = fx.add_second_candidate_pipeline(world, title="Failing Document")
    other["defense_event"] = fx.schedule_defense(
        world,
        thesis=other["thesis"],
        scheduled_start="2026-09-28T14:00:00Z",
        scheduled_end="2026-09-28T16:00:00Z",
        headers=other["student_headers"],
    )
    other["defense_event"] = get_success_data(
        fx.api_client.announce_defense_event(other["defense_event"]["id"], ANALYST_ONE)
    )

    fx.set_clock("2026-09-28T16:30:00Z")
    world["defense_event"] = get_success_data(
        fx.api_client.record_defense_outcome(
            world["defense_event"]["id"], {"outcome": "PASS"}, world["chair_headers"]
        )
    )
    other["defense_event"] = get_success_data(
        fx.api_client.record_defense_outcome(
            other["defense_event"]["id"],
            {
                "outcome": "FAIL",
                "outcome_note": "Committee vote failed on chapters 3 and 5",
            },
            world["chair_headers"],
        )
    )
    world["other"] = other
    return world


def test_fail_branch_dissolves_the_committee_and_drops_its_chair_load(
    api: ApiClient,
) -> None:
    """The failing document dissolves its committee, so its chair seat stops counting.

    PRD §3.4: "This is the only branch that touches two further entities: the committee is moved from `APPROVED` to `DISSOLVED`, and because a dissolved committee has left the counted status set, `active_chair_load` is recomputed for every `CONFIRMED` chair and co-chair seat on it."

    Design: Difficulty/non_linear_state_machine/defense_fail_branch_dissolves_committee_unlike_pass_branches
    """
    world = _two_defenses_with_opposite_outcomes()
    other = world["other"]

    assert other["defense_event"]["status"] == "HELD_FAIL"
    assert (
        other["defense_event"]["outcome_note"]
        == "Committee vote failed on chapters 3 and 5"
    )

    failing_thesis = get_success_data(api.get_thesis(other["thesis"]["id"], REGISTRAR))
    assert failing_thesis["workflow_state"] == "DEFENSE_FAILED"

    dissolved = get_success_data(
        api.get_thesis_committee(other["thesis"]["id"], REGISTRAR)
    )[0]
    assert dissolved["status"] == "DISSOLVED"
    assert dissolved["member_count"] == 3

    chair_seat = get_success_data(
        api.get_committee_member(other["seats"]["CHAIR"]["id"], REGISTRAR)
    )
    assert chair_seat["status"] == "CONFIRMED"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 1

    clearance = get_success_data(
        api.list_student_graduation_clearances(other["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "PENDING_ITEMS"


def test_pass_branch_leaves_the_committee_approved_and_the_room_minutes_counted(
    api: ApiClient,
) -> None:
    """The passing document keeps its approved committee and its counted occupation.

    PRD §3.4: "The committee stays `APPROVED`, no chair load changes, and clearance is recomputed with the defense-outcome item now satisfied under both projection variants."

    Design: Difficulty/non_linear_state_machine/defense_fail_branch_dissolves_committee_unlike_pass_branches
    """
    world = _two_defenses_with_opposite_outcomes()

    assert world["defense_event"]["status"] == "HELD_PASS"

    passing_thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert passing_thesis["workflow_state"] == "DEFENSE_PASSED"

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["status"] == "APPROVED"
    assert committee["member_count"] == 3

    chair_seat = get_success_data(
        api.get_committee_member(world["seats"]["CHAIR"]["id"], REGISTRAR)
    )
    assert chair_seat["status"] == "CONFIRMED"

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == 240
