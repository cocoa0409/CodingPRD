"""Three availability windows guard the running order, and they disagree with
each other on purpose.

A physical room empties the instant its session ends, so back-to-back sessions
in the same hall are perfectly legal and only a genuine overlap of the two
windows is refused. A chair, by contrast, has to walk out, hand over and settle
the next panel, so every one of a chair's sessions carries a mandatory
fifteen-minute turnaround on its end before the windows are compared: a
quarter-hour gap is enough, a fourteen-minute gap is not. A presenter is the
strictest resource of the three, because a person cannot stand in two halls at
the single instant one session ends and the next begins, so touching endpoints
that a room happily accepts are a conflict for the human being on stage.

Each window is probed from both sides of its own boundary, so a room rule cannot
masquerade as a presenter rule and a padded chair window cannot be mistaken for
an unpadded one.
"""

from test_helpers import (
    api_client,
    close_review_phase,
    create_session,
    create_session_payload,
    create_session_slot_payload,
    decide_abstract,
    get_success_data,
    make_program_chair_headers,
    member_of,
    open_call_for_abstracts,
    open_review_phase,
    register_author,
    release_decisions,
    setup_conference_with_committee,
    setup_scored_abstracts,
    status_transition_payload,
    submit_abstract,
    validate_error,
    validate_paginated,
    validate_success,
)

# Event day one runs 08:00 to 18:00 inside the fixture calendar, so every window
# below sits comfortably inside the conference's own event bounds.
DAY_ONE = "2026-09-01"


def _at(hhmm: str) -> str:
    """An instant on event day one, so the windows below read like a timetable."""
    return f"{DAY_ONE}T{hhmm}:00Z"


def _conference_ready_for_session_building() -> dict:
    """A conference at REVIEW_CLOSED with two active chairs, which is the
    earliest phase in which sessions may be built."""
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    submit_abstract(world)
    open_review_phase(world)
    close_review_phase(world)
    return world


def _two_confirmed_oral_abstracts_of_one_presenter() -> dict:
    """Two of Ada's abstracts carried all the way to CONFIRMED as ORAL work, so
    the same person can be offered two overlapping stages."""
    world = setup_scored_abstracts(2)
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")
    release_decisions(world)
    register_author(world["authors"]["ada"]["id"], True)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = get_success_data(
            api_client.transition_abstract(
                abstract["id"],
                status_transition_payload("CONFIRMED"),
                world["author_headers"],
            )
        )
    return world


def _place_slot(world, session, abstract, chair_key, position=1, duration_minutes=30):
    """Post one slot and hand back the raw response, so both the accepted and the
    refused placement are judged by the same call."""
    chair = world["members"][chair_key]
    headers = make_program_chair_headers(chair["id"])
    live = get_success_data(api_client.get_session(session["id"], headers))
    return api_client.create_session_slot(
        session["id"],
        create_session_slot_payload(
            abstract["id"],
            world["authors"]["ada"]["id"],
            position,
            duration_minutes,
            live["version"],
        ),
        headers,
    )


def _sessions_in_room(world, room_code: str):
    """total_count of the conference's sessions standing in one room."""
    _, meta = validate_paginated(
        api_client.list_sessions(
            world["chair_headers"],
            params={"conference_id": world["conference"]["id"], "room_code": room_code},
        )
    )
    return meta["total_count"]


# ─── The room window: half-open, so touching is legal ────────────────────


def test_room_admits_a_session_beginning_at_the_instant_the_previous_one_ends():
    """PRD: "Two exclusivity tests then run, room before chair, and they deliberately use different interval semantics."
    PRD: "**Rooms use half-open intervals.** Comparing against every other session of the same conference in the same `room_code` whose `status` is not `CANCELLED`, a conflict exists when the new session's `start_utc` is strictly earlier than the peer's `end_utc` and the peer's `start_utc` is strictly earlier than the new session's `end_utc`; a session that begins at the exact instant another ends is therefore legal, because the room empties instantaneously."
    PRD: "A new session starts `PLANNED`, with `slot_count` zero, `committed_minutes` zero, `accredited_credit_total` 0.00, and `accreditation_posture` `NOT_APPLICABLE` when `cme_designated` is false or `NON_COMPLIANT` when it is true."
    PRD: "Sessions accept `conference_id`, `chair_member_id`, `status`, `format`, `theme_code` and `room_code`."

    Design: Difficulty/resource_temporal_overlap/room_intervals_are_half_open_so_touching_is_legal
    """
    world = _conference_ready_for_session_building()
    # Hall A is occupied from 09:00 to 10:00 by a session Cho chairs.
    create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )

    # Dana takes the very same hall from the instant Cho's session releases it.
    # A different chair runs it, so the chair turnaround cannot be the verdict.
    dana = world["members"]["dana"]
    response = api_client.create_session(
        create_session_payload(
            world["conference"]["id"],
            dana["id"],
            room_code="HALL-A",
            start_utc=_at("10:00"),
            end_utc=_at("11:00"),
        ),
        make_program_chair_headers(dana["id"]),
    )

    session_b = validate_success(response, 201)
    assert session_b["status"] == "PLANNED"
    assert session_b["room_code"] == "HALL-A"
    assert session_b["start_utc"].startswith(f"{DAY_ONE}T10:00:00")
    assert _sessions_in_room(world, "HALL-A") == 2


def test_room_rejects_a_session_overlapping_the_previous_one_by_a_single_minute():
    """PRD: "**Rooms use half-open intervals.** Comparing against every other session of the same conference in the same `room_code` whose `status` is not `CANCELLED`, a conflict exists when the new session's `start_utc` is strictly earlier than the peer's `end_utc` and the peer's `start_utc` is strictly earlier than the new session's `end_utc`; a session that begins at the exact instant another ends is therefore legal, because the room empties instantaneously."
    PRD: "Any conflict is `ERR_ROOM_TIME_CONFLICT`."
    PRD: "Later violations are never reported, and no partial write ever survives a rejection."

    Design: Difficulty/resource_temporal_overlap/room_intervals_are_half_open_so_touching_is_legal
    """
    world = _conference_ready_for_session_building()
    create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("10:00"),
        end_utc=_at("11:00"),
    )

    # 10:59 is strictly earlier than the peer's 11:00 end, so the two windows
    # genuinely share a minute of hall time.
    dana = world["members"]["dana"]
    response = api_client.create_session(
        create_session_payload(
            world["conference"]["id"],
            dana["id"],
            room_code="HALL-A",
            start_utc=_at("10:59"),
            end_utc=_at("11:30"),
        ),
        make_program_chair_headers(dana["id"]),
    )

    validate_error(response, "ERR_ROOM_TIME_CONFLICT")
    assert _sessions_in_room(world, "HALL-A") == 1


# ─── The chair window: inflated by a fifteen-minute turnaround ───────────


def test_chair_rejects_a_session_fourteen_minutes_after_their_previous_one():
    """PRD: "**Chairs use inflated intervals.** Comparing against every other session with the same `chair_member_id` whose `status` is not `CANCELLED`, each peer's end and the new session's end are both extended by a mandatory fifteen-minute turnaround before the same comparison is made: a conflict exists when the new session's `start_utc` is earlier than fifteen minutes after the peer's `end_utc` and the peer's `start_utc` is earlier than fifteen minutes after the new session's `end_utc`."
    PRD: "A gap of exactly fifteen minutes between two of a chair's sessions is legal; a gap of fourteen minutes conflicts."
    PRD: "Any conflict is `ERR_CHAIR_TIME_CONFLICT`."
    PRD: "Later violations are never reported, and no partial write ever survives a rejection."
    PRD: "Its chair's `chaired_session_count` rises by one; that counter always equals the number of sessions chaired by the member whose `status` is `PLANNED`, `PUBLISHED` or `LOCKED`."

    Design: Difficulty/resource_temporal_overlap/chair_intervals_are_padded_by_a_fifteen_minute_turnaround
    """
    world = _conference_ready_for_session_building()
    cho = world["members"]["cho"]
    create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )

    # Hall B is untouched all day, so only the chair's turnaround is in play —
    # and a 14-minute gap would be perfectly legal for a room.
    response = api_client.create_session(
        create_session_payload(
            world["conference"]["id"],
            cho["id"],
            room_code="HALL-B",
            start_utc=_at("10:14"),
            end_utc=_at("11:00"),
        ),
        make_program_chair_headers(cho["id"]),
    )

    validate_error(response, "ERR_CHAIR_TIME_CONFLICT")
    assert _sessions_in_room(world, "HALL-B") == 0
    assert member_of(world, "cho")["chaired_session_count"] == 1


def test_chair_admits_a_session_exactly_fifteen_minutes_after_their_previous_one():
    """PRD: "**Chairs use inflated intervals.** Comparing against every other session with the same `chair_member_id` whose `status` is not `CANCELLED`, each peer's end and the new session's end are both extended by a mandatory fifteen-minute turnaround before the same comparison is made: a conflict exists when the new session's `start_utc` is earlier than fifteen minutes after the peer's `end_utc` and the peer's `start_utc` is earlier than fifteen minutes after the new session's `end_utc`."
    PRD: "A gap of exactly fifteen minutes between two of a chair's sessions is legal; a gap of fourteen minutes conflicts."
    PRD: "Its chair's `chaired_session_count` rises by one; that counter always equals the number of sessions chaired by the member whose `status` is `PLANNED`, `PUBLISHED` or `LOCKED`."

    Design: Difficulty/resource_temporal_overlap/chair_intervals_are_padded_by_a_fifteen_minute_turnaround
    """
    world = _conference_ready_for_session_building()
    cho = world["members"]["cho"]
    create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )

    # 10:15 is exactly the turnaround after the 10:00 end, which the padded
    # comparison treats as clear rather than as an overlap.
    response = api_client.create_session(
        create_session_payload(
            world["conference"]["id"],
            cho["id"],
            room_code="HALL-B",
            start_utc=_at("10:15"),
            end_utc=_at("11:00"),
        ),
        make_program_chair_headers(cho["id"]),
    )

    session_b = validate_success(response, 201)
    assert session_b["status"] == "PLANNED"
    assert session_b["room_code"] == "HALL-B"
    assert session_b["chair_member_id"] == cho["id"]
    assert member_of(world, "cho")["chaired_session_count"] == 2

    _, meta = validate_paginated(
        api_client.list_sessions(
            world["chair_headers"],
            params={
                "conference_id": world["conference"]["id"],
                "chair_member_id": cho["id"],
            },
        )
    )
    assert meta["total_count"] == 2


def test_chair_rejects_a_session_ending_fourteen_minutes_before_their_next_one():
    """PRD: "**Chairs use inflated intervals.** Comparing against every other session with the same `chair_member_id` whose `status` is not `CANCELLED`, each peer's end and the new session's end are both extended by a mandatory fifteen-minute turnaround before the same comparison is made: a conflict exists when the new session's `start_utc` is earlier than fifteen minutes after the peer's `end_utc` and the peer's `start_utc` is earlier than fifteen minutes after the new session's `end_utc`."
    PRD: "A gap of exactly fifteen minutes between two of a chair's sessions is legal; a gap of fourteen minutes conflicts."
    PRD: "Any conflict is `ERR_CHAIR_TIME_CONFLICT`."
    PRD: "Later violations are never reported, and no partial write ever survives a rejection."
    PRD: "Its chair's `chaired_session_count` rises by one; that counter always equals the number of sessions chaired by the member whose `status` is `PLANNED`, `PUBLISHED` or `LOCKED`."

    Design: Difficulty/resource_temporal_overlap/chair_intervals_are_padded_by_a_fifteen_minute_turnaround
    """
    world = _conference_ready_for_session_building()
    cho = world["members"]["cho"]
    create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )

    # The turnaround inflates the new session's own end too: an 08:46 finish
    # leaves Cho only fourteen minutes before the 09:00 panel she already runs.
    response = api_client.create_session(
        create_session_payload(
            world["conference"]["id"],
            cho["id"],
            room_code="HALL-B",
            start_utc=_at("08:00"),
            end_utc=_at("08:46"),
        ),
        make_program_chair_headers(cho["id"]),
    )

    validate_error(response, "ERR_CHAIR_TIME_CONFLICT")
    assert _sessions_in_room(world, "HALL-B") == 0
    assert member_of(world, "cho")["chaired_session_count"] == 1


# ─── The presenter window: fully closed, so touching conflicts ───────────


def test_presenter_cannot_take_a_session_starting_when_their_own_session_ends():
    """PRD: "**Presenters use fully closed intervals** — the third and strictest of the three interval rules. Comparing against every slot of the same presenter whose `status` is `SCHEDULED`, that belongs to a different session, and whose session is not `CANCELLED`, a conflict exists when the new session's `start_utc` is at or before the peer session's `end_utc` and the peer session's `start_utc` is at or before the new session's `end_utc`."
    PRD: "Touching endpoints therefore **do** conflict for a presenter, the opposite verdict from a room on the same instants, because a person cannot be in two rooms at the instant one session ends and the next begins."
    PRD: "Any conflict is `ERR_PRESENTER_TIME_CONFLICT`."
    PRD: "Later violations are never reported, and no partial write ever survives a rejection."

    Design: Difficulty/resource_temporal_overlap/presenter_intervals_are_closed_so_touching_conflicts
    """
    world = _two_confirmed_oral_abstracts_of_one_presenter()
    session_a = create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )
    validate_success(
        _place_slot(world, session_a, world["abstracts"][0], "cho"), 201
    )

    # Hall B under a second chair, opening at the instant hall A closes: legal
    # for the room, legal for the chair, impossible for Ada herself.
    session_b = create_session(
        world,
        chair_key="dana",
        room_code="HALL-B",
        start_utc=_at("10:00"),
        end_utc=_at("11:00"),
    )
    response = _place_slot(world, session_b, world["abstracts"][1], "dana")

    validate_error(response, "ERR_PRESENTER_TIME_CONFLICT")
    refreshed = get_success_data(
        api_client.get_session(session_b["id"], world["chair_headers"])
    )
    assert refreshed["slot_count"] == 0
    assert refreshed["committed_minutes"] == 0


def test_presenter_accepts_a_session_starting_one_minute_after_their_own_ends():
    """PRD: "**Presenters use fully closed intervals** — the third and strictest of the three interval rules. Comparing against every slot of the same presenter whose `status` is `SCHEDULED`, that belongs to a different session, and whose session is not `CANCELLED`, a conflict exists when the new session's `start_utc` is at or before the peer session's `end_utc` and the peer session's `start_utc` is at or before the new session's `end_utc`."
    PRD: "A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`, raises the session's `slot_count` by one, recomputes `committed_minutes`, `accredited_credit_total` and `accreditation_posture`, and advances the session's `version`."
    PRD: "The slot itself starts in `SCHEDULED` status with `swapped_with_slot_id` null."
    PRD: "A session's `committed_minutes` is the sum of `duration_minutes` over its counted slots plus a five-minute changeover allowance for each gap between consecutive counted slots — that is, five minutes multiplied by one less than the number of counted slots, and zero when there are no slots at all."

    Design: Difficulty/resource_temporal_overlap/presenter_intervals_are_closed_so_touching_conflicts
    """
    world = _two_confirmed_oral_abstracts_of_one_presenter()
    session_a = create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )
    validate_success(
        _place_slot(world, session_a, world["abstracts"][0], "cho"), 201
    )

    # One minute of daylight after the 10:00 end is enough for the closed rule.
    session_c = create_session(
        world,
        chair_key="dana",
        room_code="HALL-C",
        start_utc=_at("10:01"),
        end_utc=_at("11:00"),
    )
    response = _place_slot(world, session_c, world["abstracts"][1], "dana")

    slot = validate_success(response, 201)
    assert slot["status"] == "SCHEDULED"
    assert slot["presenter_author_id"] == world["authors"]["ada"]["id"]
    assert slot["swapped_with_slot_id"] is None

    refreshed = get_success_data(
        api_client.get_session(session_c["id"], world["chair_headers"])
    )
    assert refreshed["slot_count"] == 1
    assert refreshed["committed_minutes"] == 30

    abstract = get_success_data(
        api_client.get_abstract(world["abstracts"][1]["id"], world["chair_headers"])
    )
    assert abstract["status"] == "SCHEDULED"


def test_presenter_cannot_take_a_session_ending_when_their_own_session_starts():
    """PRD: "**Presenters use fully closed intervals** — the third and strictest of the three interval rules. Comparing against every slot of the same presenter whose `status` is `SCHEDULED`, that belongs to a different session, and whose session is not `CANCELLED`, a conflict exists when the new session's `start_utc` is at or before the peer session's `end_utc` and the peer session's `start_utc` is at or before the new session's `end_utc`."
    PRD: "Touching endpoints therefore **do** conflict for a presenter, the opposite verdict from a room on the same instants, because a person cannot be in two rooms at the instant one session ends and the next begins."
    PRD: "Any conflict is `ERR_PRESENTER_TIME_CONFLICT`."
    PRD: "Later violations are never reported, and no partial write ever survives a rejection."

    Design: Difficulty/resource_temporal_overlap/presenter_intervals_are_closed_so_touching_conflicts
    """
    world = _two_confirmed_oral_abstracts_of_one_presenter()
    session_a = create_session(
        world,
        chair_key="cho",
        room_code="HALL-A",
        start_utc=_at("10:00"),
        end_utc=_at("11:00"),
    )
    validate_success(
        _place_slot(world, session_a, world["abstracts"][0], "cho"), 201
    )

    # The closed rule bites at both ends: an earlier session that finishes at the
    # very instant Ada's booked panel opens is still a clash for her.
    session_d = create_session(
        world,
        chair_key="dana",
        room_code="HALL-B",
        start_utc=_at("09:00"),
        end_utc=_at("10:00"),
    )
    response = _place_slot(world, session_d, world["abstracts"][1], "dana")

    validate_error(response, "ERR_PRESENTER_TIME_CONFLICT")
    refreshed = get_success_data(
        api_client.get_session(session_d["id"], world["chair_headers"])
    )
    assert refreshed["slot_count"] == 0
    assert refreshed["committed_minutes"] == 0
