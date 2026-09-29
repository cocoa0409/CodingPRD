"""Ordering of the checks that guard an acceptance decision.

Committing a decision on an abstract is the single most heavily guarded write in
the platform: the caller's role must be allowed on the endpoint at all, the
abstract named in the path must exist, the chair's view of the conference must
still be current, the chair must not have scored the work themselves, and only
then may the conference's format slot ledger be consulted. These checks are
ranked, not simultaneous — role authorization is settled from the endpoint's own
role list before any row is read, a stale conference version pre-empts every
business rule behind it, and the separation that stops a scoring chair from
deciding their own abstract outranks the capacity arithmetic that would
otherwise refuse the same request. The tests below arrange two failures at once
on the decision endpoint and pin the identifier the platform is required to
report, and arrange each losing check on its own so that its identifier is
demonstrably reachable.
"""

from test_helpers import (
    ADMIN,
    HIGH_REVIEW,
    MEDIUM_REVIEW,
    NON_EXISTENT_UUID,
    api_client,
    assign_review,
    close_review_phase,
    create_active_member,
    create_author,
    create_conference,
    decide_abstract,
    decision_payload,
    get_conference_version,
    get_success_data,
    make_author_headers,
    make_program_chair_headers,
    open_call_for_abstracts,
    open_review_phase,
    set_clock,
    setup_capacity_exhausted_conference,
    setup_conference_with_committee,
    setup_scored_abstracts,
    submit_abstract,
    submit_review_as,
    validate_error,
)


# ─── Role authorization ahead of path-identifier existence ───────────────


def test_decision_by_author_role_on_missing_abstract_reports_role_authorization():
    """When a single request violates more than one rule, exactly one error is reported: the one belonging to the highest band in the following ordering. Later violations are never reported, and no partial write ever survives a rejection. The bands are strictly ordered from 1 to 21.
    2. **Role authorization** — the presented role appears among the endpoint's authorized roles. Otherwise `ERR_UNAUTHORIZED` (403). Applies to all endpoints.
    4. **Path identifier existence** — left to right, as described in §2.6, yielding the matching 404.
    A syntactically valid role that is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (403), a decision made from the endpoint table alone with no database reads.

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_abstract_on_decision_negative
    """
    set_clock()
    conference = create_conference()
    author = create_author("Ada Rivera", "ada@lab.example")
    version = get_conference_version(conference["id"])

    response = api_client.decide_abstract(
        NON_EXISTENT_UUID,
        decision_payload("ORAL", version),
        make_author_headers(author["id"]),
    )

    error = validate_error(response, "ERR_UNAUTHORIZED")
    assert error["error_id"] != "ERR_ABSTRACT_NOT_FOUND"
    assert response.status_code == 403

    live = get_success_data(api_client.get_conference(conference["id"], ADMIN))
    assert live["accepted_oral_count"] == 0
    assert live["version"] == version


def test_decision_by_authorized_chair_on_missing_abstract_reports_abstract_not_found():
    """4. **Path identifier existence** — left to right, as described in §2.6, yielding the matching 404.
    Requests are resolved outside-in. When a path contains an identifier, that identifier is checked first, and when a path contains more than one, they are checked strictly left to right; the first identifier that does not resolve decides the 404.

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_abstract_on_decision_negative
    """
    set_clock()
    conference = create_conference()
    chair = create_active_member(
        conference["id"],
        "Cho Bekele",
        "cho@panel.example",
        member_role="CHAIR",
        expertise_keywords=["oncology", "immunotherapy"],
    )
    version = get_conference_version(conference["id"])

    response = api_client.decide_abstract(
        NON_EXISTENT_UUID,
        decision_payload("ORAL", version),
        make_program_chair_headers(chair["id"]),
    )

    validate_error(response, "ERR_ABSTRACT_NOT_FOUND")
    assert response.status_code == 404

    live = get_success_data(api_client.get_conference(conference["id"], ADMIN))
    assert live["accepted_oral_count"] == 0


# ─── Stale conference version ahead of the format slot ledger ────────────


def test_decision_with_stale_conference_version_and_no_oral_capacity_reports_stale_version():
    """If `expected_conference_version` does not equal the conference's current `version`, the request is rejected with `ERR_STALE_CONFERENCE_VERSION` (412) and nothing is written.
    The stale-version comparison happens after schema validation — the supplied value must be a well-formed integer before it can be compared — and before every business rule, so a stale version masks state, referential, capacity and packing errors that the same request would otherwise have produced.
    Five gates precede the capacity arithmetic: the version must match, or the response is `ERR_STALE_CONFERENCE_VERSION`; the abstract's `submitted_review_count` must be at least its category's `min_reviews_required`, or the response is `ERR_INSUFFICIENT_REVIEWS`; no discrepancy case of the abstract may be in a non-terminal state, or the response is `ERR_OPEN_DISCREPANCY`; the acting chair must hold no review on this abstract in `SUBMITTED` status, or the response is `ERR_SEGREGATION_VIOLATION`; and for any non-rejection outcome the requested format must be among the category's `allowed_formats`, or the response is `ERR_FORMAT_NOT_ALLOWED`.
    21. **Quota and pool ceilings** — the lowest band, so a conference that is out of capacity still reports authentication, state, conflict and workflow problems first.

    Design: Difficulty/priority_pair_validation_conflict/stale_conference_version_outranks_exhausted_oral_capacity_negative
    """
    world = setup_scored_abstracts(
        1,
        conference_overrides={
            "oral_slot_capacity": 0,
            "poster_slot_capacity": 0,
            "workshop_slot_capacity": 0,
        },
    )
    abstract = world["abstracts"][0]
    assert abstract["status"] == "SCORED"

    # Read the version while review is still open, then close review so the
    # captured value is one behind the conference's live version.
    stale_version = get_conference_version(
        world["conference"]["id"], world["chair_headers"]
    )
    close_review_phase(world)

    response = api_client.decide_abstract(
        abstract["id"],
        decision_payload("ORAL", stale_version, allow_format_downgrade=False),
        world["chair_headers"],
    )

    error = validate_error(response, "ERR_STALE_CONFERENCE_VERSION")
    assert error["error_id"] != "ERR_FORMAT_CAPACITY_EXHAUSTED"
    assert response.status_code == 412

    live_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["status"] == "SCORED"
    assert live_abstract["decision"] is None
    live_conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert live_conference["accepted_oral_count"] == 0


def test_decision_with_current_conference_version_and_exhausted_oral_capacity_reports_capacity():
    """An `ORAL` decision commits to `ORAL` when remaining oral capacity is at least one. When it is zero and `allow_format_downgrade` is false, the request fails with `ERR_FORMAT_CAPACITY_EXHAUSTED`.
    8. **Optimistic concurrency** — `expected_conference_version` or `expected_session_version` equal to the parent's current `version`. Otherwise `ERR_STALE_CONFERENCE_VERSION` or `ERR_STALE_SESSION_VERSION` (412). Applies to `POST /abstracts/{abstractId}/decision` and `POST /sessions/{sessionId}/slots`.

    Design: Difficulty/priority_pair_validation_conflict/stale_conference_version_outranks_exhausted_oral_capacity_negative
    """
    world = setup_capacity_exhausted_conference(
        oral_slot_capacity=1,
        poster_slot_capacity=0,
        workshop_slot_capacity=0,
        abstract_count=2,
    )
    undecided = world["abstracts"][1]
    assert undecided["status"] == "SCORED"
    assert world["conference"]["accepted_oral_count"] == 1

    current_version = get_conference_version(
        world["conference"]["id"], world["chair_headers"]
    )

    response = api_client.decide_abstract(
        undecided["id"],
        decision_payload("ORAL", current_version, allow_format_downgrade=False),
        world["chair_headers"],
    )

    validate_error(response, "ERR_FORMAT_CAPACITY_EXHAUSTED")
    assert response.status_code == 422

    live_abstract = get_success_data(
        api_client.get_abstract(undecided["id"], world["chair_headers"])
    )
    assert live_abstract["status"] == "SCORED"
    assert live_abstract["decision"] is None
    live_conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert live_conference["accepted_oral_count"] == 1
    assert live_conference["version"] == current_version


# ─── Separation of duties ahead of the format slot ledger ────────────────


def _world_with_scoring_chair(**conference_overrides) -> dict:
    """One SCORED abstract whose reviews were written by chair Dana and reviewer
    Rui, with the conference at REVIEW_CLOSED. Dana therefore holds a SUBMITTED
    review on the very abstract she is about to decide."""
    world = setup_conference_with_committee(
        conference_overrides=conference_overrides or None
    )
    open_call_for_abstracts(world)
    abstract = submit_abstract(world)
    open_review_phase(world)
    chair_review = assign_review(world, abstract["id"], world["members"]["dana"]["id"])
    reviewer_review = assign_review(world, abstract["id"], world["members"]["rui"]["id"])
    submit_review_as(world, chair_review, "dana", **HIGH_REVIEW)
    submit_review_as(world, reviewer_review, "rui", **MEDIUM_REVIEW)
    close_review_phase(world)
    world["abstracts"][0] = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    return world


def test_decision_by_scoring_chair_with_no_oral_capacity_reports_segregation_violation():
    """A committee member may not review an abstract they authored or co-authored, may not review an abstract whose author set matches one of their own filed conflict declarations, may not arbitrate a dispute over an abstract they have already scored, may not issue the decision on an abstract they have already scored, and may not validate the continuing-education accreditation of an abstract whose decision they themselves issued.
    They sit above every remaining business rule in the ladder: a conflicted reviewer is rejected even when that same reviewer is simultaneously over their load ceiling.
    Five gates precede the capacity arithmetic: the version must match, or the response is `ERR_STALE_CONFERENCE_VERSION`; the abstract's `submitted_review_count` must be at least its category's `min_reviews_required`, or the response is `ERR_INSUFFICIENT_REVIEWS`; no discrepancy case of the abstract may be in a non-terminal state, or the response is `ERR_OPEN_DISCREPANCY`; the acting chair must hold no review on this abstract in `SUBMITTED` status, or the response is `ERR_SEGREGATION_VIOLATION`; and for any non-rejection outcome the requested format must be among the category's `allowed_formats`, or the response is `ERR_FORMAT_NOT_ALLOWED`.
    21. **Quota and pool ceilings** — the lowest band, so a conference that is out of capacity still reports authentication, state, conflict and workflow problems first. Yields `ERR_FORMAT_CAPACITY_EXHAUSTED` on `POST /abstracts/{abstractId}/decision`, `ERR_CME_POOL_EXHAUSTED` on `POST /accreditations/{accreditationId}/validation`, and `ERR_REVIEWER_LOAD_EXCEEDED` on `POST /abstracts/{abstractId}/review-assignments`, all at 422.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_exhausted_oral_capacity_negative
    """
    world = _world_with_scoring_chair(
        oral_slot_capacity=0, poster_slot_capacity=0, workshop_slot_capacity=0
    )
    abstract = world["abstracts"][0]
    assert abstract["status"] == "SCORED"
    assert abstract["submitted_review_count"] == 2

    # The version is re-read after the REVIEW_CLOSED transition, so the
    # concurrency band cannot mask the pair under test.
    current_version = get_conference_version(
        world["conference"]["id"], world["second_chair_headers"]
    )

    response = api_client.decide_abstract(
        abstract["id"],
        decision_payload("ORAL", current_version, allow_format_downgrade=False),
        world["second_chair_headers"],
    )

    error = validate_error(response, "ERR_SEGREGATION_VIOLATION")
    assert error["error_id"] != "ERR_FORMAT_CAPACITY_EXHAUSTED"
    assert response.status_code == 409

    live_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["status"] == "SCORED"
    assert live_abstract["decided_by_member_id"] is None
    assert live_abstract["submitted_review_count"] == 2
    live_conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert live_conference["accepted_oral_count"] == 0


def test_decision_by_scoring_chair_with_oral_capacity_available_still_reports_segregation():
    """A committee member may not review an abstract they authored or co-authored, may not review an abstract whose author set matches one of their own filed conflict declarations, may not arbitrate a dispute over an abstract they have already scored, may not issue the decision on an abstract they have already scored, and may not validate the continuing-education accreditation of an abstract whose decision they themselves issued.
    An explicitly named reviewer may have a `member_role` of either `REVIEWER` or `CHAIR` — chairs are permitted to carry review load, which is exactly what later makes the decision-time segregation check reachable — whereas the automatic selector considers only members whose `member_role` is `REVIEWER`.
    A committed decision moves the abstract from `SCORED` to `ACCEPTED`, writes the waterfall-resolved format into `decision`, sets `decision_downgraded` to true exactly when that resolved format differs from the format the chair asked for, records `decided_by_member_id`, raises the matching accepted count on the conference and advances the conference's `version`.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_exhausted_oral_capacity_negative
    """
    world = _world_with_scoring_chair(oral_slot_capacity=2)
    abstract = world["abstracts"][0]

    current_version = get_conference_version(
        world["conference"]["id"], world["second_chair_headers"]
    )
    response = api_client.decide_abstract(
        abstract["id"],
        decision_payload("ORAL", current_version, allow_format_downgrade=False),
        world["second_chair_headers"],
    )

    validate_error(response, "ERR_SEGREGATION_VIOLATION")
    assert response.status_code == 409

    # The oral ledger had room all along: a chair who never scored the work
    # commits the very same decision.
    committed = decide_abstract(world, abstract["id"], "ORAL")
    assert committed["status"] == "ACCEPTED"
    assert committed["decision"] == "ORAL"
    assert committed["decided_by_member_id"] == world["members"]["cho"]["id"]
    live_conference = get_success_data(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert live_conference["accepted_oral_count"] == 1
