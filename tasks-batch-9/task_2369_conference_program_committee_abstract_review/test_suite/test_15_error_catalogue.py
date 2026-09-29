"""How the platform reports the refusals a conference office actually meets.

Every rejection in this system is a named, specific answer rather than a generic
failure, and the name is part of the contract. A read aimed at an identifier that
was never minted answers in the vocabulary of the resource family that owns the
address, so a missing session and a missing slot are never confused for one
another. A calendar whose five instants do not run in order is refused before a
conference is ever created. Presenting a reviewer's badge with a chair's row
identifier, submitting somebody else's review, assigning a panellist who has not
yet been activated, arbitrating a dispute the arbiter already scored, sending an
abstract back for rework a third time, publishing an empty session, placing an
abstract into a session of the wrong theme or format, cancelling a running order
after the freeze instant, validating one's own accredited content, releasing a
finding before an embargo was ever set — each of these has its own identifier,
and the tests below arrange one such refusal at a time and pin the answer the
platform is required to give. Where two refusals are arranged at once, the
ranking of the checks decides which one is reported.
"""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    PRESS,
    accreditation_validation_payload,
    add_slot,
    api_client,
    assign_arbiter,
    assign_arbiter_payload,
    assign_review,
    close_review_phase,
    create_accreditation_payload,
    create_category_payload,
    create_committee_member_payload,
    create_conference_payload,
    create_disclosure_statement_payload,
    create_program_change_request_payload,
    create_session,
    create_session_slot_payload,
    decide_abstract,
    decision_payload,
    disclosure_adjudication_payload,
    get_conference_version,
    get_success_data,
    make_author_headers,
    make_program_chair_headers,
    make_reviewer_headers,
    press_action_payload,
    register_author,
    release_decisions,
    resolution_payload,
    review_assignment_payload,
    set_clock,
    setup_abstract_under_review,
    setup_change_request,
    setup_confirmed_abstract,
    setup_decided_abstract,
    setup_discrepancy_case,
    setup_scheduled_slot,
    setup_scored_abstract,
    setup_scored_abstracts,
    setup_validated_accreditation,
    status_transition_payload,
    submit_review_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# Two rubrics four points apart, so the spread reaches twice a 1.00 threshold.
_WIDE_HIGH = {
    "score_originality": 5,
    "score_methodology": 5,
    "score_relevance": 5,
    "score_clarity": 5,
    "confidence": "HIGH",
    "recommended_format": "ORAL",
}
_WIDE_LOW = {
    "score_originality": 2,
    "score_methodology": 2,
    "score_relevance": 2,
    "score_clarity": 2,
    "confidence": "HIGH",
    "recommended_format": "POSTER",
}


def _wide_spread_case() -> dict:
    """A dispute whose recorded spread is 3.00 against a threshold of 1.00."""
    return setup_discrepancy_case(
        discrepancy_threshold=1.00,
        first_review=_WIDE_HIGH,
        second_review=_WIDE_LOW,
    )


def _confirmed_program(count: int, session_overrides=None) -> dict:
    """``count`` confirmed oral abstracts plus one empty planned session."""
    world = setup_scored_abstracts(count)
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
    create_session(world, **(session_overrides or {}))
    return world


def _slot_attempt(
    world: dict,
    session: dict,
    abstract_id: str,
    presenter_author_id: str,
    position: int = 1,
    duration_minutes: int = 20,
):
    """Attempt one slot placement against the session's live version."""
    headers = world["chair_headers"]
    live = get_success_data(api_client.get_session(session["id"], headers))
    return api_client.create_session_slot(
        session["id"],
        create_session_slot_payload(
            abstract_id,
            presenter_author_id,
            position,
            duration_minutes,
            live["version"],
        ),
        headers,
    )


# ─── Reads aimed at identifiers that were never minted ───────────────────


def test_every_resource_family_reports_its_own_missing_resource_identifier():
    """Requests are resolved outside-in. When a path contains an identifier, that identifier is checked first, and when a path contains more than one, they are checked strictly left to right; the first identifier that does not resolve decides the 404.
    The 404 vocabulary is per resource type: `ERR_CONFERENCE_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_AUTHOR_NOT_FOUND`, `ERR_ABSTRACT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_DISCREPANCY_CASE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ACCREDITATION_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND` and `ERR_CHANGE_REQUEST_NOT_FOUND`.
    **Body foreign-key existence** — in request-body field order and always after every path identifier, yielding the matching 404.

    Design: Corner/errors/every_resource_family_reports_its_own_not_found_code
    """
    set_clock()

    validate_error(
        api_client.get_conference(NON_EXISTENT_UUID, ADMIN),
        "ERR_CONFERENCE_NOT_FOUND",
    )
    validate_error(
        api_client.get_category(NON_EXISTENT_UUID, ADMIN), "ERR_CATEGORY_NOT_FOUND"
    )
    validate_error(
        api_client.get_author(NON_EXISTENT_UUID, ADMIN), "ERR_AUTHOR_NOT_FOUND"
    )
    validate_error(
        api_client.get_abstract(NON_EXISTENT_UUID, ADMIN), "ERR_ABSTRACT_NOT_FOUND"
    )
    validate_error(
        api_client.get_committee_member(NON_EXISTENT_UUID, ADMIN),
        "ERR_MEMBER_NOT_FOUND",
    )
    validate_error(
        api_client.get_conflict_declaration(NON_EXISTENT_UUID, ADMIN),
        "ERR_DECLARATION_NOT_FOUND",
    )
    validate_error(
        api_client.get_review(NON_EXISTENT_UUID, ADMIN), "ERR_REVIEW_NOT_FOUND"
    )
    validate_error(
        api_client.get_discrepancy_case(NON_EXISTENT_UUID, ADMIN),
        "ERR_DISCREPANCY_CASE_NOT_FOUND",
    )
    validate_error(
        api_client.get_session(NON_EXISTENT_UUID, ADMIN), "ERR_SESSION_NOT_FOUND"
    )
    validate_error(
        api_client.get_session_slot(NON_EXISTENT_UUID, ADMIN), "ERR_SLOT_NOT_FOUND"
    )
    validate_error(
        api_client.get_accreditation(NON_EXISTENT_UUID, ADMIN),
        "ERR_ACCREDITATION_NOT_FOUND",
    )
    validate_error(
        api_client.get_disclosure_statement(NON_EXISTENT_UUID, ADMIN),
        "ERR_DISCLOSURE_NOT_FOUND",
    )
    validate_error(
        api_client.get_program_change_request(NON_EXISTENT_UUID, ADMIN),
        "ERR_CHANGE_REQUEST_NOT_FOUND",
    )

    # A body-borne parent identifier answers in the same vocabulary.
    validate_error(
        api_client.create_category(create_category_payload(NON_EXISTENT_UUID), ADMIN),
        "ERR_CONFERENCE_NOT_FOUND",
    )


# ─── The five calendar instants and their ordering ───────────────────────


def test_conference_calendar_rejects_instants_that_break_the_ordering_chain():
    """These instants must satisfy a strict chain: `event_end_utc` must be later than `event_start_utc`; `abstract_deadline_utc` must be earlier than `event_start_utc`; `review_deadline_utc` must be later than `abstract_deadline_utc`; and `program_freeze_utc` must be later than `review_deadline_utc` and earlier than `event_start_utc`. Any violation of that chain is rejected with `ERR_INVALID_DATE_RANGE`.
    A newly created conference starts in `DRAFT`, with `accepted_oral_count`, `accepted_poster_count`, `accepted_workshop_count`, `waitlisted_count`, `cme_minutes_allocated`, `cfa_extension_count`, `review_reopen_count` and `abstract_sequence` all at zero, and `cme_minutes_available` equal to `cme_minutes_pool_total`.

    Design: Corner/errors/conference_datetime_ordering_violations_are_rejected
    """
    set_clock()

    ended_before_it_started = create_conference_payload(
        code="INVA",
        event_start_utc="2026-09-01T08:00:00Z",
        event_end_utc="2026-08-31T08:00:00Z",
    )
    validate_error(
        api_client.create_conference(ended_before_it_started, ADMIN),
        "ERR_INVALID_DATE_RANGE",
    )

    submission_cutoff_after_the_event_opens = create_conference_payload(
        code="INVB",
        abstract_deadline_utc="2026-09-02T00:00:00Z",
        review_deadline_utc="2026-09-02T12:00:00Z",
    )
    validate_error(
        api_client.create_conference(submission_cutoff_after_the_event_opens, ADMIN),
        "ERR_INVALID_DATE_RANGE",
    )

    reviews_due_before_submissions_close = create_conference_payload(
        code="INVC",
        review_deadline_utc="2026-02-01T23:59:00Z",
    )
    validate_error(
        api_client.create_conference(reviews_due_before_submissions_close, ADMIN),
        "ERR_INVALID_DATE_RANGE",
    )

    freeze_after_the_event_opens = create_conference_payload(
        code="INVD",
        program_freeze_utc="2026-09-02T00:00:00Z",
    )
    validate_error(
        api_client.create_conference(freeze_after_the_event_opens, ADMIN),
        "ERR_INVALID_DATE_RANGE",
    )

    _, meta = validate_paginated(api_client.list_conferences(ADMIN))
    assert meta["total_count"] == 0, "no conference survives a rejected calendar"

    # The same five instants in order are accepted, so the refusals above are
    # about the ordering and nothing else.
    conference = validate_success(
        api_client.create_conference(create_conference_payload(), ADMIN), 201
    )
    assert conference["status"] == "DRAFT"
    _, meta = validate_paginated(api_client.list_conferences(ADMIN))
    assert meta["total_count"] == 1


# ─── Identity, ownership and assignment guards ───────────────────────────


def test_badge_that_contradicts_its_committee_row_is_refused():
    """An `X-User-ID` that is syntactically well formed but does not resolve to the entity backing the claimed role is rejected with `ERR_IDENTITY_NOT_FOUND` (403). The same error covers the contradiction case: a `CommitteeMember` whose `member_role` is `REVIEWER` presenting `X-User-Role: ProgramChair` is rejected here, as is a chair presenting itself as a `Reviewer`.

    Design: Corner/errors/identity_ownership_and_assignment_guards_are_rejected
    """
    world = setup_abstract_under_review()
    abstract = world["abstracts"][0]
    review = world["reviews"][abstract["id"]][0]

    chair_wearing_a_reviewer_badge = make_reviewer_headers(world["members"]["cho"]["id"])
    validate_error(
        api_client.get_review(review["id"], chair_wearing_a_reviewer_badge),
        "ERR_IDENTITY_NOT_FOUND",
    )

    unknown_author = make_author_headers(NON_EXISTENT_UUID)
    validate_error(
        api_client.get_abstract(abstract["id"], unknown_author),
        "ERR_IDENTITY_NOT_FOUND",
    )


def test_assignment_refuses_an_unactivated_panellist_and_a_second_helping():
    """The nominated reviewer must belong to the same conference, be `ACTIVE`, and have `coi_declaration_status` of `SUBMITTED`; otherwise the request fails with `ERR_MEMBER_STATE_INVALID`.
    The same reviewer must not already hold a review on this abstract in `ASSIGNED` or `SUBMITTED` status, or the request fails with `ERR_DUPLICATE_REVIEW_ASSIGNMENT`.

    Design: Corner/errors/identity_ownership_and_assignment_guards_are_rejected
    """
    world = setup_abstract_under_review()
    abstract = world["abstracts"][0]
    invited_only = get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(
                world["conference"]["id"],
                member_role="REVIEWER",
                full_name="Nadia Lund",
                email="nadia@panel.example",
            ),
            ADMIN,
        )
    )
    assert invited_only["status"] == "INVITED"

    validate_error(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=invited_only["id"]),
            world["chair_headers"],
        ),
        "ERR_MEMBER_STATE_INVALID",
    )

    validate_error(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(
                reviewer_member_id=world["members"]["rui"]["id"]
            ),
            world["chair_headers"],
        ),
        "ERR_DUPLICATE_REVIEW_ASSIGNMENT",
    )


def test_review_submission_refuses_a_stranger_and_a_late_rubric():
    """When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `CommitteeMember`, and that member's `member_role` must be `REVIEWER`; a review may only be submitted or declined by the member recorded in its `reviewer_member_id`.
    Once identity resolves, a further ownership gate applies to the operations listed in §2.11 band 6; a principal acting on somebody else's abstract, review, discrepancy case or slot is rejected with `ERR_NOT_RESOURCE_OWNER` (403).
    Submission requires that the acting member be the review's own `reviewer_member_id`, that the conference be `REVIEW_OPEN`, that the review's `assigned_round` still equal the abstract's `revision_round` — a mismatch is `ERR_REVIEW_STATE_INVALID` — and that the logical clock be at or before the review's `due_utc`, with a clock strictly after the due instant rejected as `ERR_REVIEW_PAST_DUE`.

    Design: Corner/errors/identity_ownership_and_assignment_guards_are_rejected
    """
    world = setup_abstract_under_review()
    abstract = world["abstracts"][0]
    review_of_rui = world["reviews"][abstract["id"]][0]

    validate_error(
        api_client.submit_review(
            review_of_rui["id"],
            submit_review_payload(),
            make_reviewer_headers(world["members"]["mei"]["id"]),
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )

    set_clock("2026-05-02T00:00:00Z")
    validate_error(
        api_client.submit_review(
            review_of_rui["id"],
            submit_review_payload(),
            make_reviewer_headers(world["members"]["rui"]["id"]),
        ),
        "ERR_REVIEW_PAST_DUE",
    )


# ─── Gates around a live dispute ─────────────────────────────────────────


def test_open_dispute_blocks_closing_review_and_requesting_rework():
    """The move from `REVIEW_OPEN` to `REVIEW_CLOSED` is refused while any discrepancy case belonging to an abstract of this conference is `OPEN`, `ARBITER_ASSIGNED`, `THIRD_REVIEW_PENDING` or `ESCALATED`, in which case the response is `ERR_OPEN_DISCREPANCY`.
    A chair may send a scored abstract back for rework, moving it from `SCORED` to `REVISION_REQUESTED`, provided the conference is `REVIEW_OPEN`, the abstract's `revision_round` is currently less than 2, and no discrepancy case for that abstract is in a non-terminal state — `OPEN`, `ARBITER_ASSIGNED`, `THIRD_REVIEW_PENDING` or `ESCALATED` — which would otherwise yield `ERR_OPEN_DISCREPANCY`.

    Design: Corner/errors/discrepancy_case_guards_are_rejected_at_each_gate
    """
    world = _wide_spread_case()
    assert world["case"]["status"] == "OPEN"

    validate_error(
        api_client.transition_conference(
            world["conference"]["id"],
            status_transition_payload("REVIEW_CLOSED"),
            ADMIN,
        ),
        "ERR_OPEN_DISCREPANCY",
    )

    validate_error(
        api_client.transition_abstract(
            world["abstracts"][0]["id"],
            status_transition_payload("REVISION_REQUESTED"),
            world["chair_headers"],
        ),
        "ERR_OPEN_DISCREPANCY",
    )


def test_arbiter_who_already_scored_the_work_is_refused():
    """A dispute is arbitrated by a chair who has not already taken a position on the work. Assigning the arbiter moves the case from `OPEN` to `ARBITER_ASSIGNED` and requires that the nominated `arbiter_member_id` identify a member whose `member_role` is `CHAIR`, whose `status` is `ACTIVE`, and whose conference matches the abstract's conference. That member must hold no review on the abstract in `SUBMITTED` status and no conflict declaration matching the abstract's author set; either failure is `ERR_ARBITER_CONFLICT`.
    An explicitly named reviewer may have a `member_role` of either `REVIEWER` or `CHAIR` — chairs are permitted to carry review load, which is exactly what later makes the decision-time segregation check reachable — whereas the automatic selector considers only members whose `member_role` is `REVIEWER`.

    Design: Corner/errors/discrepancy_case_guards_are_rejected_at_each_gate
    """
    world = setup_abstract_under_review(
        category_overrides={"discrepancy_threshold": 0.50, "min_reviews_required": 2}
    )
    abstract = world["abstracts"][0]
    second_chair = world["members"]["dana"]
    review_of_the_second_chair = assign_review(world, abstract["id"], second_chair["id"])

    # The second chair files a rubric of her own, then a panellist scores the
    # same work a point higher, so the spread opens a case with that chair
    # already on the record.
    get_success_data(
        api_client.submit_review(
            review_of_the_second_chair["id"],
            submit_review_payload(),
            make_program_chair_headers(second_chair["id"]),
        )
    )
    get_success_data(
        api_client.submit_review(
            world["reviews"][abstract["id"]][0]["id"],
            submit_review_payload(**_WIDE_HIGH),
            make_reviewer_headers(world["members"]["rui"]["id"]),
        )
    )
    cases, _ = validate_paginated(
        api_client.list_discrepancy_cases(
            world["chair_headers"], params={"abstract_id": abstract["id"]}
        )
    )
    case = cases[0]
    assert case["status"] == "OPEN"

    validate_error(
        api_client.assign_arbiter(
            case["id"],
            assign_arbiter_payload(second_chair["id"]),
            world["chair_headers"],
        ),
        "ERR_ARBITER_CONFLICT",
    )


def test_settled_arbitration_refuses_a_second_arbiter_a_wide_override_and_an_empty_pool():
    """Posting an arbiter assignment to a case that is not `OPEN`, or a resolution to a case that is neither `ARBITER_ASSIGNED` nor `ESCALATED`, is rejected with `ERR_CASE_STATE_INVALID`.
    It requires an `override_score` between 1.00 and 5.50, and it is permitted only while the case's recorded `spread_at_open` is strictly less than twice the category's `discrepancy_threshold`; at or above that ceiling a third review is mandatory and the override is rejected with `ERR_OVERRIDE_NOT_PERMITTED`.
    The selector must find at least one eligible candidate with every existing reviewer of the abstract and the arbiter excluded; an empty pool aborts the resolution with `ERR_NO_ELIGIBLE_REVIEWER`.

    Design: Corner/errors/discrepancy_case_guards_are_rejected_at_each_gate
    """
    world = _wide_spread_case()
    case = assign_arbiter(world, world["case"]["id"], world["members"]["cho"]["id"])
    assert case["status"] == "ARBITER_ASSIGNED"
    assert float(case["spread_at_open"]) == 3.00

    validate_error(
        api_client.assign_arbiter(
            case["id"],
            assign_arbiter_payload(world["members"]["dana"]["id"]),
            world["chair_headers"],
        ),
        "ERR_CASE_STATE_INVALID",
    )

    validate_error(
        api_client.resolve_discrepancy_case(
            case["id"],
            resolution_payload("CHAIR_OVERRIDE", override_score=3.50),
            world["chair_headers"],
        ),
        "ERR_OVERRIDE_NOT_PERMITTED",
    )

    validate_error(
        api_client.resolve_discrepancy_case(
            case["id"],
            resolution_payload("THIRD_REVIEW"),
            world["chair_headers"],
        ),
        "ERR_NO_ELIGIBLE_REVIEWER",
    )


# ─── Conference phase and decision bounds ────────────────────────────────


def test_releasing_decisions_while_a_scored_abstract_waits_is_refused():
    """The move from `REVIEW_CLOSED` to `DECISIONS_RELEASED` is the presenter-notification gate, and it requires that no abstract of the conference still be `SCORED` — every scored abstract must carry a decision or be waitlisted — with `ERR_UNDECIDED_ABSTRACTS_REMAIN` otherwise.

    Design: Corner/errors/conference_phase_and_revision_bounds_are_rejected
    """
    world = setup_scored_abstract()
    close_review_phase(world)
    scored = get_success_data(
        api_client.get_abstract(world["abstracts"][0]["id"], world["chair_headers"])
    )
    assert scored["status"] == "SCORED"

    validate_error(
        api_client.transition_conference(
            world["conference"]["id"],
            status_transition_payload("DECISIONS_RELEASED"),
            ADMIN,
        ),
        "ERR_UNDECIDED_ABSTRACTS_REMAIN",
    )


def test_decision_in_a_format_the_category_forbids_is_refused():
    """A category is declared with a `conference_id`, a `code` of 2 to 16 characters that is unique within the conference, a human-readable `name`, and its policy bundle: `max_word_count` between 100 and 600 caps the declared body length; `requires_structured_body`, a boolean, demands the Background/Methods/Results/Conclusion layout; `allowed_formats` is a non-empty subset of `ORAL`, `POSTER` and `WORKSHOP` and constrains both what authors may request and what the committee may decide; `min_reviews_required`, defaulting to 3 and constrained to between 2 and 5, is how many submitted reviews an abstract needs before it is considered scored; `discrepancy_threshold`, defaulting to 2.50 and constrained to between 0.50 and 4.00 at two decimals, is the score spread at which a dispute is opened; and `cme_eligible`, defaulting to false, decides whether abstracts in the category may carry a continuing-education accreditation.
    Five gates precede the capacity arithmetic: the version must match, or the response is `ERR_STALE_CONFERENCE_VERSION`; the abstract's `submitted_review_count` must be at least its category's `min_reviews_required`, or the response is `ERR_INSUFFICIENT_REVIEWS`; no discrepancy case of the abstract may be in a non-terminal state, or the response is `ERR_OPEN_DISCREPANCY`; the acting chair must hold no review on this abstract in `SUBMITTED` status, or the response is `ERR_SEGREGATION_VIOLATION`; and for any non-rejection outcome the requested format must be among the category's `allowed_formats`, or the response is `ERR_FORMAT_NOT_ALLOWED`.

    Design: Corner/errors/conference_phase_and_revision_bounds_are_rejected
    """
    world = setup_scored_abstract()
    close_review_phase(world)
    assert world["category"]["allowed_formats"] == ["ORAL", "POSTER"]
    version = get_conference_version(world["conference"]["id"], world["chair_headers"])

    validate_error(
        api_client.decide_abstract(
            world["abstracts"][0]["id"],
            decision_payload("WORKSHOP", version),
            world["chair_headers"],
        ),
        "ERR_FORMAT_NOT_ALLOWED",
    )


def test_review_cannot_be_reopened_a_second_time():
    """Review may be re-opened exactly once. That back-edge from `REVIEW_CLOSED` to `REVIEW_OPEN` requires `review_reopen_count` to be zero and a present, non-empty `reopen_reason`. On success `review_reopen_count` rises to one, the `final_score` of every abstract that is `SCORED` with a null `decision` is cleared back to null — the final variant is invalidated until review closes again — and the conference's `version` advances. A second reopen attempt is rejected with `ERR_REVIEW_REOPEN_LIMIT`.

    Design: Corner/errors/conference_phase_and_revision_bounds_are_rejected
    """
    world = setup_scored_abstract()
    close_review_phase(world)

    reopened = get_success_data(
        api_client.transition_conference(
            world["conference"]["id"],
            status_transition_payload(
                "REVIEW_OPEN", reopen_reason="a panellist withdrew their rubric"
            ),
            ADMIN,
        )
    )
    assert reopened["review_reopen_count"] == 1
    get_success_data(
        api_client.transition_conference(
            world["conference"]["id"],
            status_transition_payload("REVIEW_CLOSED"),
            ADMIN,
        )
    )

    validate_error(
        api_client.transition_conference(
            world["conference"]["id"],
            status_transition_payload(
                "REVIEW_OPEN", reopen_reason="one more look at the panel"
            ),
            ADMIN,
        ),
        "ERR_REVIEW_REOPEN_LIMIT",
    )


# ─── Program construction, running order and on-site outcomes ────────────


def test_empty_session_cannot_be_published_and_its_chair_cannot_resign():
    """The session must hold at least one counted slot, or the response is `ERR_EMPTY_SESSION`; every counted slot's abstract must be in `SCHEDULED` status; and the session's `accreditation_posture` must not be `NON_COMPLIANT`, or the response is `ERR_SESSION_NOT_ACCREDITED`.
    Resignation is reachable from `INVITED`, `ACTIVE` or `SUSPENDED`, but only while the member chairs nothing: if any session with this member as its chair is in `PLANNED`, `PUBLISHED` or `LOCKED` status, the attempt fails with `ERR_MEMBER_STILL_CHAIRING`.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = setup_confirmed_abstract()
    session = create_session(world)
    assert session["slot_count"] == 0

    validate_error(
        api_client.transition_session(
            session["id"], status_transition_payload("PUBLISHED"), world["chair_headers"]
        ),
        "ERR_EMPTY_SESSION",
    )

    validate_error(
        api_client.transition_committee_member(
            world["members"]["cho"]["id"], status_transition_payload("RESIGNED"), ADMIN
        ),
        "ERR_MEMBER_STILL_CHAIRING",
    )


def test_slot_whose_abstract_does_not_carry_the_session_theme_is_refused():
    """The abstract's `decision` must equal the session's `format`, with `ERR_SESSION_FORMAT_MISMATCH` otherwise, and the session's `theme_code` must be one of the abstract's `keywords`, with `ERR_SESSION_THEME_MISMATCH` otherwise.
    A chair constructs a themed session while the conference is `REVIEW_CLOSED` or `DECISIONS_RELEASED`, naming the `conference_id`, the `chair_member_id` who will run it, a `theme_code` of 2 to 16 characters that every slot in the session must share, a `format` of `ORAL`, `POSTER` or `WORKSHOP`, a `room_code` of 1 to 16 characters identifying the physical room, a `start_utc` and `end_utc` window, a `capacity_slots` ceiling between 1 and 20 that defaults to 6, and an optional `cme_designated` boolean defaulting to false.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = setup_confirmed_abstract(abstract_overrides={"keywords": ["immunotherapy"]})
    session = create_session(world, theme_code="oncology")

    response = _slot_attempt(
        world,
        session,
        world["abstracts"][0]["id"],
        world["authors"]["ada"]["id"],
    )

    validate_error(response, "ERR_SESSION_THEME_MISMATCH")


def test_slot_whose_abstract_was_decided_in_another_format_is_refused():
    """The abstract's `decision` must equal the session's `format`, with `ERR_SESSION_FORMAT_MISMATCH` otherwise, and the session's `theme_code` must be one of the abstract's `keywords`, with `ERR_SESSION_THEME_MISMATCH` otherwise.
    A chair constructs a themed session while the conference is `REVIEW_CLOSED` or `DECISIONS_RELEASED`, naming the `conference_id`, the `chair_member_id` who will run it, a `theme_code` of 2 to 16 characters that every slot in the session must share, a `format` of `ORAL`, `POSTER` or `WORKSHOP`

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = setup_confirmed_abstract(decision="POSTER")
    session = create_session(world, format="ORAL", theme_code="oncology")

    response = _slot_attempt(
        world,
        session,
        world["abstracts"][0]["id"],
        world["authors"]["ada"]["id"],
    )

    validate_error(response, "ERR_SESSION_FORMAT_MISMATCH")


def test_slot_refuses_an_off_abstract_presenter_and_a_reused_running_order_position():
    """The nominated presenter must be either the abstract's submitting author or an author whose `email` appears in the abstract's `coauthor_emails`, with `ERR_PRESENTER_NOT_ON_ABSTRACT` otherwise, and must not be `BARRED`.
    The three packing checks run in a fixed order: the count must be strictly less than `capacity_slots`, or the response is `ERR_SESSION_SLOT_CAPACITY_REACHED`; the requested `position` must not already be occupied by a counted slot of the session, or the response is `ERR_DUPLICATE_SLOT_POSITION`; and the minute budget must admit the new duration, or the response is `ERR_SESSION_DURATION_EXCEEDED`.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = _confirmed_program(2)
    session = world["sessions"][0]
    assert world["abstracts"][0]["coauthor_emails"] == []

    validate_error(
        _slot_attempt(
            world,
            session,
            world["abstracts"][0]["id"],
            world["authors"]["ben"]["id"],
        ),
        "ERR_PRESENTER_NOT_ON_ABSTRACT",
    )

    add_slot(
        world,
        session,
        world["abstracts"][0]["id"],
        world["authors"]["ada"]["id"],
        position=1,
        duration_minutes=20,
    )
    validate_error(
        _slot_attempt(
            world,
            session,
            world["abstracts"][1]["id"],
            world["authors"]["ada"]["id"],
            position=1,
        ),
        "ERR_DUPLICATE_SLOT_POSITION",
    )


def test_slot_refuses_a_full_running_order_and_a_session_already_published():
    """The three packing checks run in a fixed order: the count must be strictly less than `capacity_slots`, or the response is `ERR_SESSION_SLOT_CAPACITY_REACHED`; the requested `position` must not already be occupied by a counted slot of the session, or the response is `ERR_DUPLICATE_SLOT_POSITION`; and the minute budget must admit the new duration, or the response is `ERR_SESSION_DURATION_EXCEEDED`.
    The session must be `PLANNED`, or the request fails with `ERR_SESSION_STATE_INVALID`, and the logical clock must still be earlier than the conference's `program_freeze_utc`, or it fails with `ERR_PROGRAM_FROZEN`.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = _confirmed_program(2, session_overrides={"capacity_slots": 1})
    session = world["sessions"][0]
    add_slot(
        world,
        session,
        world["abstracts"][0]["id"],
        world["authors"]["ada"]["id"],
        position=1,
        duration_minutes=20,
    )

    validate_error(
        _slot_attempt(
            world,
            session,
            world["abstracts"][1]["id"],
            world["authors"]["ada"]["id"],
            position=2,
        ),
        "ERR_SESSION_SLOT_CAPACITY_REACHED",
    )

    published = get_success_data(
        api_client.transition_session(
            session["id"], status_transition_payload("PUBLISHED"), world["chair_headers"]
        )
    )
    assert published["status"] == "PUBLISHED"
    validate_error(
        _slot_attempt(
            world,
            session,
            world["abstracts"][1]["id"],
            world["authors"]["ada"]["id"],
            position=2,
        ),
        "ERR_SESSION_STATE_INVALID",
    )


def test_cancelling_after_the_freeze_and_recording_a_slot_outcome_twice_are_refused():
    """Cancelling a session is available from `PLANNED` or `PUBLISHED` and requires the logical clock to still be earlier than `program_freeze_utc`, with `ERR_PROGRAM_FROZEN` otherwise.
    Marking a slot `PRESENTED` additionally requires the logical clock to be at or after the session's `start_utc`, and it moves the slot's abstract from `SCHEDULED` to `PRESENTED`.
    `PRESENTED`, `NO_SHOW_RECORDED`, `WITHDRAWN` and `MOVED` are all terminal for a slot.
    This band also covers terminal-state lockdown and the second attempt at an operation that already succeeded.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = setup_scheduled_slot()
    session = world["sessions"][0]
    slot = world["slots"][0]
    get_success_data(
        api_client.transition_session(
            session["id"], status_transition_payload("PUBLISHED"), world["chair_headers"]
        )
    )

    set_clock("2026-08-20T00:00:00Z")
    validate_error(
        api_client.transition_session(
            session["id"], status_transition_payload("CANCELLED"), world["chair_headers"]
        ),
        "ERR_PROGRAM_FROZEN",
    )

    set_clock("2026-09-01T09:30:00Z")
    presented = get_success_data(
        api_client.transition_session_slot(
            slot["id"], status_transition_payload("PRESENTED"), world["chair_headers"]
        )
    )
    assert presented["status"] == "PRESENTED"
    validate_error(
        api_client.transition_session_slot(
            slot["id"], status_transition_payload("PRESENTED"), world["chair_headers"]
        ),
        "ERR_SLOT_STATE_INVALID",
    )


def test_second_pending_change_request_for_the_same_slot_is_refused():
    """The conference must be `DECISIONS_RELEASED` or `PROGRAM_PUBLISHED`; the referenced slot must still be `SCHEDULED`; the logical clock must be earlier than `event_end_utc`; the caller must be a chair of the conference or an author who is either the slot's `presenter_author_id` or the abstract's submitting author, with `ERR_NOT_RESOURCE_OWNER` otherwise; a `MOVE` or `SWAP` must supply `target_session_id` and a `SUBSTITUTE_PRESENTER` must supply a `substitute_presenter_author_id` whose email is among the abstract's `coauthor_emails`; and no other request for the same slot may already be `PENDING`, with `ERR_CHANGE_REQUEST_STATE_INVALID` otherwise.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = setup_change_request(change_type="WITHDRAW")
    assert world["change_request"]["status"] == "PENDING"

    validate_error(
        api_client.create_program_change_request(
            create_program_change_request_payload(
                world["slots"][0]["id"],
                "WITHDRAW",
                requested_by_author_id=world["authors"]["ada"]["id"],
                reason="the presenter cannot travel after all",
            ),
            world["chair_headers"],
        ),
        "ERR_CHANGE_REQUEST_STATE_INVALID",
    )


def test_barred_author_cannot_confirm_an_acceptance():
    """The `sanction_status` ladder is derived from their sum: a combined count of zero leaves the author at `NONE`, a combined count of exactly one moves them to `WARNED`, and a combined count of two or more moves them to `BARRED`.
    A `BARRED` author cannot submit a new abstract and cannot confirm an acceptance — both attempts fail with `ERR_AUTHOR_BARRED` — and cannot be named as the presenter of a slot.
    Only the submitting author may do so; the conference must be `DECISIONS_RELEASED` or `PROGRAM_PUBLISHED`; the author's `is_registered` must be true, or the request fails with `ERR_AUTHOR_NOT_REGISTERED`; and the author's `sanction_status` must not be `BARRED`, or it fails with `ERR_AUTHOR_BARRED`.

    Design: Corner/errors/program_phase_session_and_slot_guards_are_rejected
    """
    world = setup_scored_abstracts(
        3,
        abstract_overrides=[{"is_newsworthy": True}, {"is_newsworthy": True}, {}],
    )
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")
    release_decisions(world)
    register_author(world["authors"]["ada"]["id"], True)

    for abstract in world["abstracts"][:2]:
        get_success_data(
            api_client.press_action(
                abstract["id"],
                press_action_payload(
                    "SET_EMBARGO", embargo_until_utc="2026-09-02T12:00:00Z"
                ),
                PRESS,
            )
        )
        breached = get_success_data(
            api_client.press_action(
                abstract["id"],
                press_action_payload("RELEASE", outlet_name="Northline Daily"),
                PRESS,
            )
        )
        assert breached["embargo_status"] == "BREACHED"
    author = get_success_data(
        api_client.get_author(world["authors"]["ada"]["id"], ADMIN)
    )
    assert author["sanction_status"] == "BARRED"

    validate_error(
        api_client.transition_abstract(
            world["abstracts"][2]["id"],
            status_transition_payload("CONFIRMED"),
            world["author_headers"],
        ),
        "ERR_AUTHOR_BARRED",
    )


# ─── Accredited content, disclosures and the press dimension ─────────────


def test_accreditation_on_content_outside_an_eligible_category_is_refused():
    """The abstract's category must have `cme_eligible` true, or the request fails with `ERR_CATEGORY_NOT_CME_ELIGIBLE`; the abstract's `status` must be `ACCEPTED`, `CONFIRMED` or `SCHEDULED`; and no other accreditation for the same abstract may be in `PENDING` or `VALIDATED` status, with `ERR_ACCREDITATION_STATE_INVALID` otherwise.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_decided_abstract(
        category_overrides={"cme_eligible": False, "min_reviews_required": 2}
    )

    validate_error(
        api_client.create_accreditation(
            create_accreditation_payload(world["abstracts"][0]["id"], 30), ADMIN
        ),
        "ERR_CATEGORY_NOT_CME_ELIGIBLE",
    )


def test_settled_accreditation_paperwork_refuses_repeat_postings():
    """The abstract's category must have `cme_eligible` true, or the request fails with `ERR_CATEGORY_NOT_CME_ELIGIBLE`; the abstract's `status` must be `ACCEPTED`, `CONFIRMED` or `SCHEDULED`; and no other accreditation for the same abstract may be in `PENDING` or `VALIDATED` status, with `ERR_ACCREDITATION_STATE_INVALID` otherwise.
    10. **Acted-on resource state** — a transition to the requested target exists from the resource's current state, and dependent operations find their prerequisites in the required state. Otherwise one of `ERR_ABSTRACT_STATE_INVALID`, `ERR_REVIEW_STATE_INVALID`, `ERR_MEMBER_STATE_INVALID`, `ERR_CASE_STATE_INVALID`, `ERR_SESSION_STATE_INVALID`, `ERR_SLOT_STATE_INVALID`, `ERR_ACCREDITATION_STATE_INVALID`, `ERR_DISCLOSURE_STATE_INVALID` or `ERR_CHANGE_REQUEST_STATE_INVALID` (409).
    Revoking one moves it from `VALIDATED` to `REVOKED`, has no preconditions, returns `awarded_credits` to 0.00, lowers the conference's `cme_minutes_allocated` by exactly the same `content_minutes` the validation debited with `cme_minutes_available` recomputed and the conference's `version` advanced, recomputes the owning session's `accredited_credit_total` and `accreditation_posture` with that session's `version` advanced, and — when that session is `cme_designated`, its recomputed posture is `NON_COMPLIANT` and it is currently `PUBLISHED` — drops the session back to `PLANNED`.
    `REJECTED` is terminal for a disclosure, and posting a `VALIDATED` outcome to an already-validated row is rejected with `ERR_DISCLOSURE_STATE_INVALID`.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_validated_accreditation(validate=False)
    accreditation = world["accreditation"]
    assert accreditation["validation_status"] == "PENDING"

    validate_error(
        api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("REVOKE"),
            world["second_chair_headers"],
        ),
        "ERR_ACCREDITATION_STATE_INVALID",
    )

    validate_error(
        api_client.create_accreditation(
            create_accreditation_payload(world["abstracts"][0]["id"], 20), ADMIN
        ),
        "ERR_ACCREDITATION_STATE_INVALID",
    )

    validate_error(
        api_client.adjudicate_disclosure_statement(
            world["disclosure"]["id"],
            disclosure_adjudication_payload("VALIDATED"),
            world["second_chair_headers"],
        ),
        "ERR_DISCLOSURE_STATE_INVALID",
    )


def test_disclosure_filed_against_another_abstract_is_refused():
    """The accreditation must still be `PENDING`; its own abstract must match the `abstract_id` in the payload, or the response is `ERR_DISCLOSURE_ABSTRACT_MISMATCH`; and the disclosing author must be the abstract's submitting author or the holder of one of its `coauthor_emails`.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_scored_abstracts(
        2, category_overrides={"cme_eligible": True, "min_reviews_required": 2}
    )
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")
    accreditation = get_success_data(
        api_client.create_accreditation(
            create_accreditation_payload(world["abstracts"][0]["id"], 30), ADMIN
        )
    )

    validate_error(
        api_client.create_disclosure_statement(
            create_disclosure_statement_payload(
                world["abstracts"][1]["id"],
                accreditation["id"],
                world["authors"]["ada"]["id"],
            ),
            world["author_headers"],
        ),
        "ERR_DISCLOSURE_ABSTRACT_MISMATCH",
    )


def test_accreditation_without_complete_disclosure_paperwork_is_refused():
    """Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`; at least one disclosure must exist for the accreditation and every one of them must be `VALIDATED`, or the response is `ERR_DISCLOSURE_INCOMPLETE`; the accreditation's `commercial_bias_flag` must be false, which is the second trigger for that same error; and `content_minutes` must be less than or equal to the conference's `cme_minutes_available`, or the response is `ERR_CME_POOL_EXHAUSTED`.
    An outcome of `VALIDATED` moves the row from `SUBMITTED` to `VALIDATED` and requires either that `mitigation_required` be false or that `mitigation_completed` be true; a disclosure that needs mitigation and has not completed it cannot be validated, and the attempt returns `ERR_DISCLOSURE_INCOMPLETE`.
    On creation the row's `status` is `SUBMITTED`, its `mitigation_required` is set to exactly the value of `has_financial_relationship`, its `mitigation_completed` defaults to false, its `rejection_reason` is null, and the parent accreditation's `commercial_bias_flag` is recomputed.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_decided_abstract(
        category_overrides={"cme_eligible": True, "min_reviews_required": 2}
    )
    abstract = world["abstracts"][0]
    accreditation = get_success_data(
        api_client.create_accreditation(
            create_accreditation_payload(abstract["id"], 30), ADMIN
        )
    )

    validate_error(
        api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        ),
        "ERR_DISCLOSURE_INCOMPLETE",
    )

    disclosure = get_success_data(
        api_client.create_disclosure_statement(
            create_disclosure_statement_payload(
                abstract["id"],
                accreditation["id"],
                world["authors"]["ada"]["id"],
                has_financial_relationship=True,
                relationship_entity="Helix Biopharma",
            ),
            world["author_headers"],
        )
    )
    assert disclosure["mitigation_required"] is True
    validate_error(
        api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        ),
        "ERR_DISCLOSURE_INCOMPLETE",
    )

    validate_error(
        api_client.adjudicate_disclosure_statement(
            disclosure["id"],
            disclosure_adjudication_payload("VALIDATED"),
            world["second_chair_headers"],
        ),
        "ERR_DISCLOSURE_INCOMPLETE",
    )


def test_deciding_chair_cannot_validate_the_credit_for_their_own_decision():
    """A committee member may not review an abstract they authored or co-authored, may not review an abstract whose author set matches one of their own filed conflict declarations, may not arbitrate a dispute over an abstract they have already scored, may not issue the decision on an abstract they have already scored, and may not validate the continuing-education accreditation of an abstract whose decision they themselves issued.
    Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_validated_accreditation(validate=False)
    accreditation = world["accreditation"]
    assert world["abstracts"][0]["decided_by_member_id"] == world["members"]["cho"]["id"]

    validate_error(
        api_client.validate_accreditation(
            accreditation["id"],
            accreditation_validation_payload("VALIDATE"),
            world["chair_headers"],
        ),
        "ERR_ACCREDITATION_SELF_VALIDATION",
    )

    still_pending = get_success_data(
        api_client.get_accreditation(accreditation["id"], ADMIN)
    )
    assert still_pending["validation_status"] == "PENDING"


def test_validation_beyond_the_remaining_minute_pool_is_refused():
    """Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`; at least one disclosure must exist for the accreditation and every one of them must be `VALIDATED`, or the response is `ERR_DISCLOSURE_INCOMPLETE`; the accreditation's `commercial_bias_flag` must be false, which is the second trigger for that same error; and `content_minutes` must be less than or equal to the conference's `cme_minutes_available`, or the response is `ERR_CME_POOL_EXHAUSTED`.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_validated_accreditation(
        content_minutes=60,
        validate=False,
        conference_overrides={"cme_minutes_pool_total": 30},
    )
    assert world["conference"]["cme_minutes_available"] == 30

    validate_error(
        api_client.validate_accreditation(
            world["accreditation"]["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        ),
        "ERR_CME_POOL_EXHAUSTED",
    )


def test_accredited_session_without_credit_cannot_be_published():
    """A session's `accreditation_posture` follows from it: `NOT_APPLICABLE` whenever `cme_designated` is false, otherwise `COMPLIANT` when `accredited_credit_total` is at least 0.50 and `NON_COMPLIANT` when it is below that.
    The session must hold at least one counted slot, or the response is `ERR_EMPTY_SESSION`; every counted slot's abstract must be in `SCHEDULED` status; and the session's `accreditation_posture` must not be `NON_COMPLIANT`, or the response is `ERR_SESSION_NOT_ACCREDITED`.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_scheduled_slot(session_overrides={"cme_designated": True})
    session = get_success_data(
        api_client.get_session(world["sessions"][0]["id"], world["chair_headers"])
    )
    assert session["accreditation_posture"] == "NON_COMPLIANT"
    assert session["slot_count"] == 1

    validate_error(
        api_client.transition_session(
            session["id"], status_transition_payload("PUBLISHED"), world["chair_headers"]
        ),
        "ERR_SESSION_NOT_ACCREDITED",
    )


def test_press_embargo_refuses_unflagged_work_bad_windows_and_release_before_any_embargo():
    """Setting an embargo moves the abstract's `embargo_status` from `NONE` to `EMBARGOED` and requires that the abstract's `is_newsworthy` be true — otherwise the attempt fails with `ERR_NOT_NEWSWORTHY` — that the abstract's `status` be `ACCEPTED`, `CONFIRMED` or `SCHEDULED`, and that the supplied `embargo_until_utc` be present, strictly later than the logical clock, and at or before the conference's `event_end_utc`; a missing or out-of-window instant is `ERR_EMBARGO_WINDOW_INVALID`. The instant is stored on the abstract as `embargo_until_utc`. Attempting a release while `embargo_status` is still `NONE` is rejected with `ERR_EMBARGO_NOT_SET`.

    Design: Corner/errors/accreditation_disclosure_and_press_guards_are_rejected
    """
    world = setup_scored_abstracts(
        2, abstract_overrides=[{}, {"is_newsworthy": True}]
    )
    close_review_phase(world)
    for index, accepted in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, accepted["id"], "ORAL")

    quiet_abstract = world["abstracts"][0]
    assert quiet_abstract["is_newsworthy"] is False
    validate_error(
        api_client.press_action(
            quiet_abstract["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc="2026-08-01T00:00:00Z"),
            PRESS,
        ),
        "ERR_NOT_NEWSWORTHY",
    )

    abstract = world["abstracts"][1]
    assert abstract["embargo_status"] == "NONE"

    validate_error(
        api_client.press_action(
            abstract["id"],
            press_action_payload("RELEASE", outlet_name="Northline Daily"),
            PRESS,
        ),
        "ERR_EMBARGO_NOT_SET",
    )

    validate_error(
        api_client.press_action(
            abstract["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc="2025-12-01T00:00:00Z"),
            PRESS,
        ),
        "ERR_EMBARGO_WINDOW_INVALID",
    )
    validate_error(
        api_client.press_action(
            abstract["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc="2026-09-04T00:00:00Z"),
            PRESS,
        ),
        "ERR_EMBARGO_WINDOW_INVALID",
    )

    embargoed = get_success_data(
        api_client.press_action(
            abstract["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc="2026-08-01T00:00:00Z"),
            PRESS,
        )
    )
    assert embargoed["embargo_status"] == "EMBARGOED"


# ─── Which refusal wins when the work is not yet scored ──────────────────


def test_decision_on_an_unscored_abstract_reports_its_state_not_its_review_count():
    """When a single request violates more than one rule, exactly one error is reported: the one belonging to the highest band in the following ordering. Later violations are never reported, and no partial write ever survives a rejection. The bands are strictly ordered from 1 to 21.
    10. **Acted-on resource state** — a transition to the requested target exists from the resource's current state, and dependent operations find their prerequisites in the required state. Otherwise one of `ERR_ABSTRACT_STATE_INVALID`, `ERR_REVIEW_STATE_INVALID`, `ERR_MEMBER_STATE_INVALID`, `ERR_CASE_STATE_INVALID`, `ERR_SESSION_STATE_INVALID`, `ERR_SLOT_STATE_INVALID`, `ERR_ACCREDITATION_STATE_INVALID`, `ERR_DISCLOSURE_STATE_INVALID` or `ERR_CHANGE_REQUEST_STATE_INVALID` (409).
    Decisions are issued one abstract at a time by a chair, from the `SCORED` state, while the conference is `REVIEW_CLOSED`.
    Five gates precede the capacity arithmetic: the version must match, or the response is `ERR_STALE_CONFERENCE_VERSION`; the abstract's `submitted_review_count` must be at least its category's `min_reviews_required`, or the response is `ERR_INSUFFICIENT_REVIEWS`; no discrepancy case of the abstract may be in a non-terminal state, or the response is `ERR_OPEN_DISCREPANCY`; the acting chair must hold no review on this abstract in `SUBMITTED` status, or the response is `ERR_SEGREGATION_VIOLATION`; and for any non-rejection outcome the requested format must be among the category's `allowed_formats`, or the response is `ERR_FORMAT_NOT_ALLOWED`.

    Design: Corner/errors/insufficient_reviews_guard_is_shadowed_by_the_abstract_state_guard
    """
    world = setup_abstract_under_review()
    abstract = world["abstracts"][0]
    get_success_data(
        api_client.submit_review(
            world["reviews"][abstract["id"]][0]["id"],
            submit_review_payload(),
            make_reviewer_headers(world["members"]["rui"]["id"]),
        )
    )
    close_review_phase(world)
    still_under_review = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert still_under_review["status"] == "UNDER_REVIEW"
    assert still_under_review["submitted_review_count"] == 1
    assert world["category"]["min_reviews_required"] == 2
    version = get_conference_version(world["conference"]["id"], world["chair_headers"])

    response = api_client.decide_abstract(
        abstract["id"],
        decision_payload("ORAL", version),
        world["chair_headers"],
    )

    validate_error(response, "ERR_ABSTRACT_STATE_INVALID")
