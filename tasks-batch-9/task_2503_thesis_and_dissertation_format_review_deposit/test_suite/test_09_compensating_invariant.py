"""Action pairs that must leave the derived counters exactly where they started.

Seating a co-chair and releasing that seat are exact inverses on chair load, and
scheduling a defense then cancelling it is an exact inverse on room minutes.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_chair_load_conserved
from test_helpers.test_users import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]


def _cochair_seated_then_released() -> dict:
    """A co-chair joins a submitted composition and is then released again."""
    world = fx.setup_submitted_committee()
    world["cochair"] = fx.add_faculty_member(
        world,
        full_name="Gia Park",
        email="gia@u.edu",
        appointment_type="TENURE_TRACK",
        graduate_faculty_certified=True,
    )
    world["cochair_seat"] = fx.seat_member(world, world["cochair"], "CO_CHAIR")
    world["load_while_seated"] = get_success_data(
        fx.api_client.get_faculty_member(world["cochair"]["id"], REGISTRAR)
    )["active_chair_load"]
    world["cochair_seat"] = get_success_data(
        fx.api_client.release_committee_member(
            world["cochair_seat"]["id"],
            world["student_headers"],
            {"withdrawal_reason": "Co-chair took sabbatical leave"},
        )
    )
    return world


def test_releasing_the_cochair_seat_restores_every_chair_load(api: ApiClient) -> None:
    """The co-chair's load rises to one and falls back to zero, chair untouched.

    PRD §2.10: "Summing `active_chair_load` over every faculty member must always equal the number of `CONFIRMED` chair-or-co-chair seats whose committee is `SUBMITTED` or `APPROVED`; seating a chair and releasing that seat are exact inverses."

    Design: Difficulty/compensating_invariant/chair_load_restored_after_add_then_withdraw_cochair
    """
    world = _cochair_seated_then_released()

    assert world["load_while_seated"] == 1

    cochair = get_success_data(api.get_faculty_member(world["cochair"]["id"], REGISTRAR))
    assert cochair["active_chair_load"] == 0
    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 1

    faculty_rows = [
        get_success_data(api.get_faculty_member(member["id"], REGISTRAR))
        for member in world["faculty"]
    ]
    assert_chair_load_conserved(faculty_rows, 1)


def test_released_seat_stays_queryable_and_leaves_the_composition_submitted(
    api: ApiClient,
) -> None:
    """The withdrawn row keeps its reason while the counted seats fall back to three.

    PRD §3.3: "Seats are soft-deleted rather than destroyed: releasing a seat sets its `status` to `WITHDRAWN`, records the supplied `withdrawal_reason`, and leaves the row queryable forever."

    Design: Difficulty/compensating_invariant/chair_load_restored_after_add_then_withdraw_cochair
    """
    world = _cochair_seated_then_released()

    seat = get_success_data(
        api.get_committee_member(world["cochair_seat"]["id"], REGISTRAR)
    )
    assert seat["status"] == "WITHDRAWN"
    assert seat["withdrawal_reason"] == "Co-chair took sabbatical leave"

    chair_seat = get_success_data(
        api.get_committee_member(world["seats"]["CHAIR"]["id"], REGISTRAR)
    )
    assert chair_seat["status"] == "CONFIRMED"

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["status"] == "SUBMITTED"
    assert committee["approved_by_user_id"] is None
    assert committee["member_count"] == 3
    assert committee["external_member_count"] == 0

    seats = get_success_data(
        api.list_committee_members(
            REGISTRAR, params={"committee_id": world["committee"]["id"]}
        )
    )
    assert len(seats) == 3

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "COMMITTEE_PENDING"


def _second_defense_scheduled_then_cancelled() -> dict:
    """A second candidate books the same room after 16:30 and then cancels."""
    world = fx.setup_announced_defense(thesis_overrides={"title": "Kept Occupation"})
    other = fx.add_second_candidate_pipeline(world, title="Cancelled Occupation")
    world["minutes_before"] = get_success_data(
        fx.api_client.get_defense_room(world["room"]["id"], REGISTRAR)
    )["booked_minutes_total"]
    other["defense_event"] = fx.schedule_defense(
        world,
        thesis=other["thesis"],
        scheduled_start="2026-09-25T16:30:00Z",
        scheduled_end="2026-09-25T18:30:00Z",
        headers=other["student_headers"],
    )
    world["minutes_while_booked"] = get_success_data(
        fx.api_client.get_defense_room(world["room"]["id"], REGISTRAR)
    )["booked_minutes_total"]
    other["defense_event"] = get_success_data(
        fx.api_client.cancel_defense_event(
            other["defense_event"]["id"],
            {"cancellation_reason": "Candidate illness"},
            ANALYST_ONE,
        )
    )
    world["other"] = other
    return world


def test_cancelling_restores_the_room_minutes_to_the_prior_value(
    api: ApiClient,
) -> None:
    """The room counter returns to precisely the 120 minutes it held before.

    PRD §2.10: "Likewise, a room's `booked_minutes_total` after a schedule-then-cancel pair must equal what it was before the schedule."

    Design: Difficulty/compensating_invariant/room_minutes_restored_after_schedule_then_cancel
    """
    world = _second_defense_scheduled_then_cancelled()

    assert world["minutes_before"] == 120
    assert world["minutes_while_booked"] == 240

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == world["minutes_before"]

    first_event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert first_event["status"] == "ANNOUNCED"


def test_cancelling_returns_the_document_to_its_approved_committee(
    api: ApiClient,
) -> None:
    """The cancelled event stores its reason and the document falls back one step.

    PRD §3.4: "Either source pair produces the same result: the event moves to `CANCELLED` with the supplied reason stored, the document falls back to `COMMITTEE_APPROVED`, the room's `booked_minutes_total` is recomputed now that the occupation has left the counted set, and clearance is recomputed."

    Design: Difficulty/compensating_invariant/room_minutes_restored_after_schedule_then_cancel
    """
    world = _second_defense_scheduled_then_cancelled()
    other = world["other"]

    assert other["defense_event"]["status"] == "CANCELLED"
    assert other["defense_event"]["cancellation_reason"] == "Candidate illness"

    thesis = get_success_data(api.get_thesis(other["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "COMMITTEE_APPROVED"

    committee = get_success_data(
        api.get_thesis_committee(other["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["status"] == "APPROVED"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 2

    clearance = get_success_data(
        api.list_student_graduation_clearances(other["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "PENDING_ITEMS"
