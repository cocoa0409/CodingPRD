"""Contended session ledgers and the order in which the panel is picked.

Two chairs building the same running order can each read a session, and the
second one to write is working from a picture the first one already invalidated.
A slot write therefore has to carry the session version its author last saw: a
write that names the version the chair just read lands, a write that replays a
version an earlier slot already superseded is refused outright, and the refusal
leaves the running order exactly as it was, so re-reading the session and trying
again succeeds. The refusal also speaks first — a slot that would never have fit
inside the session's minute budget is still told to refresh rather than told it
is too long.

The second half of the file watches the committee selector choose a reviewer on
its own. Every candidate is measured by how well its declared expertise overlaps
the abstract's keywords; equal fit is settled by who has the most room left in
their workload, and reviewers who are equally well matched and equally free are
taken in the order they joined the committee. A reviewer whose expertise barely
touches the subject is not merely ranked last, they are not a candidate at all.
"""

import pytest

from test_helpers import (
    CLOCK_BEFORE_DEADLINES,
    api_client,
    close_review_phase,
    create_abstract_payload,
    create_active_member,
    create_author,
    create_category,
    create_conference,
    create_session,
    create_session_slot_payload,
    decide_abstract,
    get_success_data,
    make_author_headers,
    make_program_chair_headers,
    register_author,
    release_decisions,
    review_assignment_payload,
    set_clock,
    setup_scored_abstracts,
    status_transition_payload,
    transition_conference,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── The contended session: two confirmed oral talks and one two-hour room ──

SESSION_START = "2026-09-01T09:00:00Z"
SESSION_END = "2026-09-01T11:00:00Z"


def _world_with_two_confirmed_oral_abstracts() -> dict:
    """Two abstracts scored, decided ORAL and confirmed by their author, plus a
    PLANNED session in HALL-A holding room for two slots.

    The session window runs 09:00 to 11:00, so a hundred and twenty minutes are
    available to the ten-minute buffer, the slot durations and the five-minute
    changeover between consecutive slots.
    """
    world = setup_scored_abstracts(
        2,
        conference_overrides={
            "oral_slot_capacity": 2,
            "poster_slot_capacity": 2,
            "workshop_slot_capacity": 1,
        },
        category_overrides={
            "allowed_formats": ["ORAL"],
            "min_reviews_required": 2,
            "discrepancy_threshold": 4.00,
        },
    )
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
    create_session(
        world,
        theme_code="oncology",
        format="ORAL",
        room_code="HALL-A",
        start_utc=SESSION_START,
        end_utc=SESSION_END,
        capacity_slots=2,
    )
    return world


def _slot_request(world: dict, abstract_index: int, position: int, duration: int,
                  expected_session_version: int):
    """One slot-creation call for the named abstract, presented by its author."""
    return api_client.create_session_slot(
        world["sessions"][0]["id"],
        create_session_slot_payload(
            world["abstracts"][abstract_index]["id"],
            world["authors"]["ada"]["id"],
            position,
            duration,
            expected_session_version,
        ),
        make_program_chair_headers(world["members"]["cho"]["id"]),
    )


def _read_session(world: dict) -> dict:
    return get_success_data(
        api_client.get_session(
            world["sessions"][0]["id"],
            make_program_chair_headers(world["members"]["cho"]["id"]),
        )
    )


def test_slot_creation_accepts_the_session_version_the_chair_just_read():
    """`POST /sessions/{sessionId}/slots` requires `expected_session_version` as
    a non-optional integer input carrying the client's last observed `version` of
    the target `Session`.

    A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`,
    raises the session's `slot_count` by one, recomputes `committed_minutes`,
    `accredited_credit_total` and `accreditation_posture`, and advances the
    session's `version`.

    All resources except conflict declarations additionally carry:
    - `updated_at` — an ISO 8601 UTC timestamp with three fractional digits,
      refreshed on every mutation of the row, including mutations that only touch
      derived counters.
    - `version` — an integer that starts at 1 on creation and increases by exactly
      one on every mutation of that row.

    Design: Corner/cross_cutting_complexity_layers/slot_creation_rejects_a_stale_session_version
    """
    world = _world_with_two_confirmed_oral_abstracts()
    observed = _read_session(world)

    slot = validate_success(_slot_request(world, 0, 1, 30, observed["version"]), 201)

    assert slot["position"] == 1
    assert slot["status"] == "SCHEDULED"

    after = _read_session(world)
    assert after["version"] == observed["version"] + 1
    assert after["slot_count"] == 1


def test_slot_creation_rejects_a_session_version_an_earlier_slot_superseded():
    """If `expected_session_version` does not equal the session's current
    `version`, the request is rejected with `ERR_STALE_SESSION_VERSION` (412) and
    nothing is written.

    Its counted slots are those whose `status` is `SCHEDULED`, `PRESENTED` or
    `NO_SHOW_RECORDED`, and `slot_count` is their number.

    Design: Corner/cross_cutting_complexity_layers/slot_creation_rejects_a_stale_session_version
    """
    world = _world_with_two_confirmed_oral_abstracts()
    observed = _read_session(world)
    validate_success(_slot_request(world, 0, 1, 30, observed["version"]), 201)
    after_first = _read_session(world)

    replayed = _slot_request(world, 1, 2, 30, observed["version"])
    validate_error(replayed, "ERR_STALE_SESSION_VERSION")

    unchanged = _read_session(world)
    assert unchanged["version"] == after_first["version"]
    assert unchanged["slot_count"] == 1

    chair_headers = make_program_chair_headers(world["members"]["cho"]["id"])
    slots, meta = validate_paginated(
        api_client.list_session_slots(
            chair_headers, params={"session_id": world["sessions"][0]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["position"] for row in slots] == [1]

    second_abstract = get_success_data(
        api_client.get_abstract(world["abstracts"][1]["id"], chair_headers)
    )
    assert second_abstract["status"] == "CONFIRMED"


def test_slot_creation_succeeds_when_the_chair_re_reads_the_session_and_retries():
    """If `expected_session_version` does not equal the session's current
    `version`, the request is rejected with `ERR_STALE_SESSION_VERSION` (412) and
    nothing is written.

    A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`,
    raises the session's `slot_count` by one, recomputes `committed_minutes`,
    `accredited_credit_total` and `accreditation_posture`, and advances the
    session's `version`.

    Design: Corner/cross_cutting_complexity_layers/slot_creation_rejects_a_stale_session_version
    """
    world = _world_with_two_confirmed_oral_abstracts()
    observed = _read_session(world)
    validate_success(_slot_request(world, 0, 1, 30, observed["version"]), 201)

    validate_error(
        _slot_request(world, 1, 2, 30, observed["version"]), "ERR_STALE_SESSION_VERSION"
    )

    refreshed = _read_session(world)
    retried = validate_success(
        _slot_request(world, 1, 2, 30, refreshed["version"]), 201
    )

    assert retried["position"] == 2
    assert retried["status"] == "SCHEDULED"

    final = _read_session(world)
    assert final["slot_count"] == 2
    assert final["version"] == refreshed["version"] + 1

    scheduled = get_success_data(
        api_client.get_abstract(
            world["abstracts"][1]["id"],
            make_program_chair_headers(world["members"]["cho"]["id"]),
        )
    )
    assert scheduled["status"] == "SCHEDULED"


def test_stale_session_version_is_reported_ahead_of_the_session_minute_budget():
    """The stale-version comparison happens after schema validation — the
    supplied value must be a well-formed integer before it can be compared — and
    before every business rule, so a stale version masks state, referential,
    capacity and packing errors that the same request would otherwise have
    produced.

    A new slot is admissible only when a ten-minute session buffer, plus the
    durations of all existing counted slots, plus the new slot's
    `duration_minutes`, plus five minutes for every gap in the resulting
    arrangement — five multiplied by one less than the post-addition slot count —
    is less than or equal to the window in minutes.

    Design: Corner/cross_cutting_complexity_layers/slot_creation_rejects_a_stale_session_version
    """
    world = _world_with_two_confirmed_oral_abstracts()
    observed = _read_session(world)
    validate_success(_slot_request(world, 0, 1, 30, observed["version"]), 201)
    refreshed = _read_session(world)

    # A hundred-and-twenty-minute talk cannot fit the remaining budget of the
    # two-hour window: the fresh-version attempt is refused for the budget.
    validate_error(
        _slot_request(world, 1, 2, 120, refreshed["version"]),
        "ERR_SESSION_DURATION_EXCEEDED",
    )

    # The very same over-long slot, offered with the superseded version, is
    # refused for the version instead.
    validate_error(
        _slot_request(world, 1, 2, 120, observed["version"]),
        "ERR_STALE_SESSION_VERSION",
    )

    unchanged = _read_session(world)
    assert unchanged["version"] == refreshed["version"]
    assert unchanged["slot_count"] == 1


# ─── The selector: a panel built in a known order ────────────────────────────

PANEL_CLOCKS = (
    "2026-01-05T00:00:00Z",
    "2026-01-06T00:00:00Z",
    "2026-01-07T00:00:00Z",
    "2026-01-08T00:00:00Z",
)


def _selector_world(panel, abstract_titles=("A1 selector probe",)) -> dict:
    """Conference at REVIEW_OPEN with one chair, the named reviewers recruited in
    the order given — one calendar day apart, so their creation order is
    unambiguous — and one abstract per title, each keyed only on ``oncology``.

    ``panel`` is an ordered list of (full_name, email, expertise_keywords); every
    reviewer is ACTIVE with a conflict declaration on file and a
    ``max_review_load`` of 4, so all of them start with a spare capacity of 4.
    """
    set_clock(CLOCK_BEFORE_DEADLINES)
    conference = create_conference(
        oral_slot_capacity=3, poster_slot_capacity=2, workshop_slot_capacity=1
    )
    category = create_category(
        conference["id"],
        allowed_formats=["ORAL"],
        min_reviews_required=2,
        discrepancy_threshold=4.00,
    )
    ada = create_author("Ada Rivera", "ada@lab.example")
    chair = create_active_member(
        conference["id"],
        "Cho Bekele",
        "cho@panel.example",
        member_role="CHAIR",
        expertise_keywords=["oncology"],
    )
    reviewers = []
    for index, (full_name, email, keywords) in enumerate(panel):
        set_clock(PANEL_CLOCKS[index])
        reviewers.append(
            create_active_member(
                conference["id"],
                full_name,
                email,
                member_role="REVIEWER",
                expertise_keywords=keywords,
                max_review_load=4,
            )
        )
    transition_conference(conference["id"], "CFA_OPEN")
    author_headers = make_author_headers(ada["id"])
    abstracts = [
        get_success_data(
            api_client.create_abstract(
                create_abstract_payload(
                    conference["id"],
                    category["id"],
                    ada["id"],
                    title=title,
                    keywords=["oncology"],
                ),
                author_headers,
            )
        )
        for title in abstract_titles
    ]
    transition_conference(conference["id"], "CFA_CLOSED")
    transition_conference(conference["id"], "REVIEW_OPEN")
    return {
        "conference": conference,
        "category": category,
        "author": ada,
        "chair": chair,
        "chair_headers": make_program_chair_headers(chair["id"]),
        "reviewers": reviewers,
        "abstracts": abstracts,
    }


def _auto_assign(world: dict, abstract_index: int = 0):
    """Let the selector choose: no `reviewer_member_id` is supplied."""
    return api_client.create_review_assignment(
        world["abstracts"][abstract_index]["id"],
        review_assignment_payload(),
        world["chair_headers"],
    )


def _member(world: dict, reviewer_index: int) -> dict:
    return get_success_data(
        api_client.get_committee_member(
            world["reviewers"][reviewer_index]["id"], world["chair_headers"]
        )
    )


def test_reviewer_selector_prefers_the_strongest_expertise_match():
    """A chair assigns a reviewer to an abstract either explicitly, by naming a
    `reviewer_member_id`, or implicitly, by omitting it and letting the selector
    choose.

    The score is twice the number of keywords the two sets share, divided by the
    sum of the two set sizes, rounded half up to four decimal places.

    Surviving candidates are ranked by match score from highest to lowest; ties
    are broken by spare capacity, meaning `max_review_load` minus
    `current_review_load`, from largest to smallest; any remaining tie is broken
    by `created_at` from earliest to latest.

    Design: Corner/cross_cutting_complexity_layers/reviewer_selector_orders_by_score_then_spare_capacity_then_created_at
    """
    world = _selector_world(
        [
            # Recruited first, and a genuine candidate, but a broader panellist:
            # only one of four declared keywords touches the abstract.
            ("Bo Ferreira", "bo@panel.example", ["oncology", "astronomy", "botany", "chemistry"]),
            # Recruited second, and an exact keyword match.
            ("Rui Alvarez", "rui@panel.example", ["oncology"]),
        ]
    )

    review = validate_success(_auto_assign(world), 201)

    assert review["reviewer_member_id"] == world["reviewers"][1]["id"]
    assert review["expertise_match_score"] == pytest.approx(1.0000, abs=0.0001)
    assert _member(world, 0)["current_review_load"] == 0
    assert _member(world, 1)["current_review_load"] == 1


def test_reviewer_selector_breaks_a_match_score_tie_by_the_largest_spare_capacity():
    """Surviving candidates are ranked by match score from highest to lowest;
    ties are broken by spare capacity, meaning `max_review_load` minus
    `current_review_load`, from largest to smallest; any remaining tie is broken
    by `created_at` from earliest to latest.

    The reviewer's `current_review_load` rises by one.

    Design: Corner/cross_cutting_complexity_layers/reviewer_selector_orders_by_score_then_spare_capacity_then_created_at
    """
    world = _selector_world(
        [
            ("Rui Alvarez", "rui@panel.example", ["oncology"]),
            ("Mei Osei", "mei@panel.example", ["oncology"]),
            ("Nadia Farr", "nadia@panel.example", ["oncology"]),
        ],
        abstract_titles=("A1 selector probe", "A2 selector probe"),
    )
    rui, mei, nadia = world["reviewers"]

    # The two oldest reviewers are put to work on the first abstract by name, so
    # each of them carries a spare capacity of 3 while Nadia still has 4.
    for member in (rui, mei):
        validate_success(
            api_client.create_review_assignment(
                world["abstracts"][0]["id"],
                review_assignment_payload(reviewer_member_id=member["id"]),
                world["chair_headers"],
            ),
            201,
        )
    assert _member(world, 0)["current_review_load"] == 1
    assert _member(world, 1)["current_review_load"] == 1
    assert _member(world, 2)["current_review_load"] == 0

    review = validate_success(_auto_assign(world, 1), 201)

    # All three declare the same single keyword, so the match score is tied at
    # 1.0000 and spare capacity, not creation order, settles it.
    assert review["expertise_match_score"] == pytest.approx(1.0000, abs=0.0001)
    assert review["reviewer_member_id"] == nadia["id"]
    assert _member(world, 2)["current_review_load"] == 1


def test_reviewer_selector_breaks_a_spare_capacity_tie_by_the_earliest_recruited():
    """Surviving candidates are ranked by match score from highest to lowest;
    ties are broken by spare capacity, meaning `max_review_load` minus
    `current_review_load`, from largest to smallest; any remaining tie is broken
    by `created_at` from earliest to latest.

    The identifier is never used as a tiebreaker. The single highest-ranked
    candidate is assigned.

    Design: Corner/cross_cutting_complexity_layers/reviewer_selector_orders_by_score_then_spare_capacity_then_created_at
    """
    world = _selector_world(
        [
            ("Rui Alvarez", "rui@panel.example", ["oncology"]),
            ("Mei Osei", "mei@panel.example", ["oncology"]),
            ("Nadia Farr", "nadia@panel.example", ["oncology"]),
        ]
    )
    rui, mei, _nadia = world["reviewers"]

    # Three identical candidates: same keyword, same load ceiling, no load yet.
    first = validate_success(_auto_assign(world), 201)
    assert first["expertise_match_score"] == pytest.approx(1.0000, abs=0.0001)
    assert first["reviewer_member_id"] == rui["id"]

    # Rui now holds an ASSIGNED review on this abstract; Mei and Nadia are still
    # tied on both higher keys, so the earlier of the two is taken.
    second = validate_success(_auto_assign(world), 201)
    assert second["reviewer_member_id"] == mei["id"]

    reviews, meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"], params={"abstract_id": world["abstracts"][0]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["reviewer_member_id"] for row in reviews) == sorted(
        [rui["id"], mei["id"]]
    )


def test_reviewer_selector_never_picks_a_candidate_below_the_minimum_match():
    """A candidate is eligible only when every one of the following holds: the
    candidate belongs to the abstract's conference; the candidate's `member_role`
    is `REVIEWER`; the candidate's `status` is `ACTIVE`; the candidate's
    `coi_declaration_status` is `SUBMITTED`; the candidate's `current_review_load`
    is strictly less than their `max_review_load`; no conflict declaration of the
    candidate matches the abstract's author set; the candidate's `email` is not in
    that author set; the candidate holds no review on this abstract in `ASSIGNED`
    or `SUBMITTED` status; the candidate is not in the explicit exclusion set for
    this selection; and the candidate's match score is at least 0.2500.

    When the selector was invoked by an explicit selector-driven assignment or by
    the third-review branch of a discrepancy resolution, an empty pool aborts the
    whole request with `ERR_NO_ELIGIBLE_REVIEWER` and nothing is written.

    Design: Corner/cross_cutting_complexity_layers/reviewer_selector_orders_by_score_then_spare_capacity_then_created_at
    """
    world = _selector_world(
        [("Zed Kwan", "zed@panel.example", ["astronomy"])]
    )

    validate_error(_auto_assign(world), "ERR_NO_ELIGIBLE_REVIEWER")

    # The astronomer shares no keyword with the abstract, so he is not a
    # candidate at all and his workload is untouched.
    assert _member(world, 0)["current_review_load"] == 0
    _reviews, meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"], params={"abstract_id": world["abstracts"][0]["id"]}
        )
    )
    assert meta["total_count"] == 0
