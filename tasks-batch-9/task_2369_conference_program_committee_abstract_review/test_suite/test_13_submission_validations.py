"""Submission-side validation rules of the abstract pipeline.

These tests walk the gates an incoming request has to clear before it becomes a
stored row: the two identity headers every caller must present, the per-category
word ceiling that caps a declared body length, the structured-body requirement
that only some categories declare, the call-for-abstracts deadline measured
against the logical clock, the aggregate reviewer load ceiling that spans
separate abstracts, the conflict declarations a committee member files before
activation, and the relationship between a malformed payload and a conference
that is in the wrong phase for the operation.

Each test builds its own conference, category, committee and authors from an
empty database, and asserts both the reported error identifier and the absence
of any partial write behind it — a rejected submission must not consume a blind
code, a rejected assignment must not move the load ledger, and a rejected
decision must not advance the conference version.
"""

from test_helpers import (
    ADMIN,
    TEST_DEFAULTS,
    api_client,
    create_abstract_payload,
    create_active_member,
    create_category,
    create_conference_payload,
    decision_payload,
    make_author_headers,
    make_reviewer_headers,
    open_call_for_abstracts,
    open_review_phase,
    review_assignment_payload,
    set_clock,
    setup_conference_with_committee,
    setup_reviewer_at_load_ceiling,
    submit_abstract,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Identity headers ────────────────────────────────────────────────────


def test_conference_creation_without_identity_headers_is_rejected():
    """All requests must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capacity in which that principal
    is acting.

    If either header is absent or empty, or if `X-User-Role` is not one of those
    five strings, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (401) —
    and this check runs before any routing-level existence check, so an
    unauthenticated request aimed at a non-existent abstract still returns 401
    rather than 404.

    1. **Header presence and role validity** — both `X-User-ID` and
    `X-User-Role` present and non-empty, and `X-User-Role` one of the five
    declared roles. Otherwise `ERR_MISSING_AUTH_HEADERS` (401). Applies to all
    endpoints, ahead of any existence check.

    Design: Corner/validations/request_without_identity_headers_is_rejected_at_priority_one
    """
    set_clock()

    res = api_client.create_conference(create_conference_payload(), {})
    validate_error(res, "ERR_MISSING_AUTH_HEADERS")

    _, meta = validate_paginated(api_client.list_conferences(ADMIN))
    assert meta["total_count"] == 0, (
        "the rejected creation must not have persisted a conference row"
    )


def test_conference_creation_with_an_undeclared_role_string_is_rejected():
    """Five roles exist, spelled exactly as follows: `ConferenceAdmin`,
    `ProgramChair`, `Reviewer`, `Author`, and `PressOfficer`. If either header is
    absent or empty, or if `X-User-Role` is not one of those five strings, the
    request is rejected with `ERR_MISSING_AUTH_HEADERS` (401) — and this check
    runs before any routing-level existence check, so an unauthenticated request
    aimed at a non-existent abstract still returns 401 rather than 404.

    A syntactically valid role that is not listed among an endpoint's authorized
    roles is rejected with `ERR_UNAUTHORIZED` (403), a decision made from the
    endpoint table alone with no database reads.

    Design: Corner/validations/request_without_identity_headers_is_rejected_at_priority_one
    """
    set_clock()

    undeclared_role_headers = {
        "X-User-ID": "test-conference-admin-1",
        "X-User-Role": "Registrar",
        "Content-Type": "application/json",
    }
    res = api_client.create_conference(
        create_conference_payload(), undeclared_role_headers
    )
    validate_error(res, "ERR_MISSING_AUTH_HEADERS")

    _, meta = validate_paginated(api_client.list_conferences(ADMIN))
    assert meta["total_count"] == 0, (
        "an undeclared role string must not have persisted a conference row"
    )


# ─── The category word limit ─────────────────────────────────────────────


def test_abstract_at_exactly_the_category_word_limit_is_accepted():
    """The category's formatting rules are then applied: `body_word_count` must
    be less than or equal to the category's `max_word_count`, and when the
    category has `requires_structured_body` set, `body_structured` must be true;
    either failure yields `ERR_ABSTRACT_FORMAT_INVALID`.

    On acceptance of the submission the conference's `abstract_sequence` counter
    is incremented and the abstract's `blind_code` is minted deterministically as
    the conference `code`, a hyphen, the letter `B`, and the post-increment
    sequence value zero-padded to four digits — the first abstract of a
    conference whose `code` is `NEURO26` therefore carries the blind code
    `NEURO26-B0001`.

    The new abstract starts with `status` `SUBMITTED`, `embargo_status` `NONE`,
    `revision_round` zero, `submitted_review_count` zero, and
    `provisional_score`, `final_score`, `score_spread`, `decision`,
    `decided_by_member_id`, `embargo_until_utc` and `press_outlet_name` all null,
    with `decision_downgraded` false.

    Design: Corner/validations/abstract_at_exactly_the_category_word_limit_is_accepted
    """
    world = setup_conference_with_committee(
        category_overrides={"max_word_count": 300, "requires_structured_body": False}
    )
    open_call_for_abstracts(world)
    ada = world["authors"]["ada"]

    res = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            world["category"]["id"],
            ada["id"],
            body_word_count=300,
            body_structured=False,
        ),
        make_author_headers(ada["id"]),
    )
    abstract = validate_success(res, 201)

    assert abstract["status"] == "SUBMITTED"
    assert abstract["body_word_count"] == 300
    assert abstract["blind_code"] == "GOS26-B0001"
    assert abstract["revision_round"] == 0


def test_abstract_one_word_over_the_category_word_limit_is_rejected():
    """The category's formatting rules are then applied: `body_word_count` must be
    less than or equal to the category's `max_word_count`, and when the category has
    `requires_structured_body` set, `body_structured` must be true; either failure
    yields `ERR_ABSTRACT_FORMAT_INVALID`.

    16. **Abstract formatting** — `ERR_ABSTRACT_FORMAT_INVALID` (422) on
    `POST /abstracts` and `POST /abstracts/{abstractId}/revisions`.

    When a single request violates more than one rule, exactly one error is
    reported: the one belonging to the highest band in the following ordering.
    Later violations are never reported, and no partial write ever survives a
    rejection.

    Design: Corner/validations/abstract_one_word_over_the_category_limit_is_rejected
    """
    world = setup_conference_with_committee(
        category_overrides={"max_word_count": 300, "requires_structured_body": False}
    )
    open_call_for_abstracts(world)
    ada = world["authors"]["ada"]
    author_headers = make_author_headers(ada["id"])

    over_limit = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            world["category"]["id"],
            ada["id"],
            body_word_count=301,
        ),
        author_headers,
    )
    validate_error(over_limit, "ERR_ABSTRACT_FORMAT_INVALID")

    under_limit = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            world["category"]["id"],
            ada["id"],
            body_word_count=299,
        ),
        author_headers,
    )
    accepted = validate_success(under_limit, 201)
    assert accepted["blind_code"] == "GOS26-B0001", (
        "the rejected oversized attempt must not have consumed a blind code"
    )

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert conference["abstract_sequence"] == 1


# ─── The structured-body requirement ─────────────────────────────────────


def test_unstructured_body_is_accepted_where_the_category_does_not_require_structure():
    """The category's formatting rules are then applied: `body_word_count` must
    be less than or equal to the category's `max_word_count`, and when the
    category has `requires_structured_body` set, `body_structured` must be true;
    either failure yields `ERR_ABSTRACT_FORMAT_INVALID`.

    16. **Abstract formatting** — `ERR_ABSTRACT_FORMAT_INVALID` (422) on
    `POST /abstracts` and `POST /abstracts/{abstractId}/revisions`. This is a
    category-conditional rule that fires only for categories that declare the
    requirement.

    Design: Corner/validations/structured_body_requirement_applies_only_where_configured
    """
    world = setup_conference_with_committee(
        category_overrides={
            "code": "GEN",
            "name": "General Oncology",
            "max_word_count": 300,
            "requires_structured_body": False,
        }
    )
    open_call_for_abstracts(world)
    ada = world["authors"]["ada"]

    res = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            world["category"]["id"],
            ada["id"],
            title="Unstructured narrative",
            body_word_count=280,
            keywords=["oncology"],
            body_structured=False,
        ),
        make_author_headers(ada["id"]),
    )
    abstract = validate_success(res, 201)
    assert abstract["status"] == "SUBMITTED"
    assert abstract["blind_code"] == "GOS26-B0001"


def test_unstructured_body_is_rejected_where_the_category_requires_structure():
    """The category's formatting rules are then applied: `body_word_count` must
    be less than or equal to the category's `max_word_count`, and when the
    category has `requires_structured_body` set, `body_structured` must be true;
    either failure yields `ERR_ABSTRACT_FORMAT_INVALID`.

    16. **Abstract formatting** — `ERR_ABSTRACT_FORMAT_INVALID` (422) on
    `POST /abstracts` and `POST /abstracts/{abstractId}/revisions`. This is a
    category-conditional rule that fires only for categories that declare the
    requirement.

    Later violations are never reported, and no partial write ever survives a
    rejection.

    Design: Corner/validations/structured_body_requirement_applies_only_where_configured
    """
    world = setup_conference_with_committee(
        category_overrides={
            "code": "GEN",
            "name": "General Oncology",
            "max_word_count": 300,
            "requires_structured_body": False,
        }
    )
    structured_category = create_category(
        world["conference"]["id"],
        code="STR",
        name="Structured Trials",
        max_word_count=300,
        allowed_formats=["ORAL", "POSTER"],
        requires_structured_body=True,
    )
    open_call_for_abstracts(world)
    ada = world["authors"]["ada"]
    author_headers = make_author_headers(ada["id"])

    # The first submission lands under the flag-off category and takes B0001.
    submit_abstract(
        world,
        title="Unstructured narrative",
        body_word_count=280,
        keywords=["oncology"],
        body_structured=False,
    )

    rejected = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            structured_category["id"],
            ada["id"],
            title="Trial without structure",
            body_word_count=280,
            keywords=["oncology"],
            body_structured=False,
        ),
        author_headers,
    )
    validate_error(rejected, "ERR_ABSTRACT_FORMAT_INVALID")

    accepted = validate_success(
        api_client.create_abstract(
            create_abstract_payload(
                world["conference"]["id"],
                structured_category["id"],
                ada["id"],
                title="Trial with structure",
                body_word_count=280,
                keywords=["oncology"],
                body_structured=True,
            ),
            author_headers,
        ),
        201,
    )
    assert accepted["blind_code"] == "GOS26-B0002", (
        "the rejected unstructured attempt must not have consumed a blind code"
    )


# ─── The submission deadline ─────────────────────────────────────────────


def test_abstract_submitted_at_exactly_the_call_deadline_is_accepted():
    """Submission is admitted only when the conference is `CFA_OPEN` and the
    logical clock is at or before `abstract_deadline_utc`; a clock past the
    deadline yields `ERR_CFA_DEADLINE_PASSED`.

    Design: Corner/validations/abstract_submitted_after_the_call_deadline_is_rejected
    """
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    set_clock("2026-03-01T23:59:00Z")
    ada = world["authors"]["ada"]

    res = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            world["category"]["id"],
            ada["id"],
            title="On the deadline instant",
            body_word_count=280,
            keywords=["oncology"],
        ),
        make_author_headers(ada["id"]),
    )
    abstract = validate_success(res, 201)
    assert abstract["status"] == "SUBMITTED"
    assert abstract["blind_code"] == "GOS26-B0001"


def test_abstract_submitted_after_the_call_deadline_is_rejected():
    """Submission is admitted only when the conference is `CFA_OPEN` and the
    logical clock is at or before `abstract_deadline_utc`; a clock past the
    deadline yields `ERR_CFA_DEADLINE_PASSED`.

    Closing the call — `CFA_OPEN` to `CFA_CLOSED` — has no preconditions at all,
    and it is worth being explicit about the corollary: passing
    `abstract_deadline_utc` does **not** close the call by itself. The call stays
    `CFA_OPEN` until an administrator closes it; what the deadline does is make
    further submissions fail with `ERR_CFA_DEADLINE_PASSED`.

    Design: Corner/validations/abstract_submitted_after_the_call_deadline_is_rejected
    """
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    set_clock("2026-03-02T00:00:00Z")
    ada = world["authors"]["ada"]

    res = api_client.create_abstract(
        create_abstract_payload(
            world["conference"]["id"],
            world["category"]["id"],
            ada["id"],
            title="One minute late",
            body_word_count=280,
            keywords=["oncology"],
        ),
        make_author_headers(ada["id"]),
    )
    validate_error(res, "ERR_CFA_DEADLINE_PASSED")

    _, meta = validate_paginated(
        api_client.list_abstracts(
            ADMIN, params={"conference_id": world["conference"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the late submission must not have been stored"

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert conference["status"] == "CFA_OPEN", (
        "passing the deadline does not close the call by itself"
    )


# ─── The reviewer load ceiling ───────────────────────────────────────────


def test_review_assignment_raises_the_reviewer_load_to_its_ceiling():
    """A successful assignment creates a review row with `status` `ASSIGNED`, an
    `assigned_round` frozen to the abstract's current `revision_round`,
    `is_third_review` false, a computed `expertise_match_score`, and null values
    for every rubric field, `confidence`, `recommended_format`,
    `comments_to_authors`, `weighted_score`, `submitted_at` and `decline_reason`.
    The reviewer's `current_review_load` rises by one.

    A committee member's `current_review_load` always equals the number of that
    member's review rows whose `status` is `ASSIGNED`, and it must never be
    negative nor exceed that member's `max_review_load`.

    Design: Corner/validations/reviewer_load_ceiling_is_enforced_across_separate_abstracts
    """
    world = setup_conference_with_committee(reviewer_load=1)
    open_call_for_abstracts(world)
    first = submit_abstract(world, title="Ada submission", keywords=["oncology"])
    open_review_phase(world)
    rui = world["members"]["rui"]

    res = api_client.create_review_assignment(
        first["id"],
        review_assignment_payload(reviewer_member_id=rui["id"]),
        world["chair_headers"],
    )
    review = validate_success(res, 201)
    assert review["status"] == "ASSIGNED"
    assert review["reviewer_member_id"] == rui["id"]

    member = validate_success(
        api_client.get_committee_member(rui["id"], world["chair_headers"])
    )
    assert member["current_review_load"] == 1
    assert member["max_review_load"] == 1


def test_second_review_assignment_to_a_reviewer_at_the_load_ceiling_is_rejected():
    """And the reviewer's `current_review_load` must be strictly less than their
    `max_review_load`, or the request fails with `ERR_REVIEWER_LOAD_EXCEEDED`.

    21. **Quota and pool ceilings** — the lowest band, so a conference that is
    out of capacity still reports authentication, state, conflict and workflow
    problems first. Yields `ERR_FORMAT_CAPACITY_EXHAUSTED` on
    `POST /abstracts/{abstractId}/decision`, `ERR_CME_POOL_EXHAUSTED` on
    `POST /accreditations/{accreditationId}/validation`, and
    `ERR_REVIEWER_LOAD_EXCEEDED` on
    `POST /abstracts/{abstractId}/review-assignments`, all at 422.

    When this is the first non-terminal review of the current round, the abstract
    moves from `SUBMITTED` to `UNDER_REVIEW`.

    Design: Corner/validations/reviewer_load_ceiling_is_enforced_across_separate_abstracts
    """
    world = setup_reviewer_at_load_ceiling(max_review_load=1, abstract_count=2)
    rui = world["members"]["rui"]
    assert rui["current_review_load"] == 1, "fixture must leave the reviewer at ceiling"
    second_abstract = world["abstracts"][1]

    res = api_client.create_review_assignment(
        second_abstract["id"],
        review_assignment_payload(reviewer_member_id=rui["id"]),
        world["chair_headers"],
    )
    validate_error(res, "ERR_REVIEWER_LOAD_EXCEEDED")

    member = validate_success(
        api_client.get_committee_member(rui["id"], world["chair_headers"])
    )
    assert member["current_review_load"] == 1, (
        "a rejected assignment must not move the load ledger"
    )

    abstract = validate_success(
        api_client.get_abstract(second_abstract["id"], world["chair_headers"])
    )
    assert abstract["status"] == "SUBMITTED", (
        "no review was created, so the abstract never reached UNDER_REVIEW"
    )


# ─── Declared conflicts ──────────────────────────────────────────────────


def test_review_assignment_to_a_reviewer_with_a_declared_author_conflict_is_rejected():
    """No conflict declaration of the reviewer may match the abstract's author
    set, and the reviewer's own `email` must not be the submitting author's email
    nor appear in `coauthor_emails`; either failure is `ERR_REVIEWER_CONFLICT`.

    An abstract's author set is the email of the author identified by
    `submitting_author_id` together with every address in `coauthor_emails`.

    A declaration whose `conflict_subject_type` is `AUTHOR_EMAIL` matches when
    its `conflict_subject_value` is in that set; a declaration whose
    `conflict_subject_type` is `AFFILIATION` matches when its
    `conflict_subject_value` equals the `affiliation` string of any author in
    that set; a declaration whose `conflict_subject_type` is `NONE` never matches
    anything and exists purely to record that the member has considered the
    question.

    Design: Corner/validations/declared_author_conflict_blocks_that_reviewers_assignment
    """
    world = setup_conference_with_committee()
    conflicted = create_active_member(
        world["conference"]["id"],
        "Rui Alvarez",
        "rui.conflicted@panel.example",
        member_role="REVIEWER",
        expertise_keywords=["oncology"],
        max_review_load=4,
        conflict_overrides={
            "conflict_subject_type": "AUTHOR_EMAIL",
            "conflict_subject_value": "ada@lab.example",
            "conflict_type": "COAUTHOR",
        },
    )
    open_call_for_abstracts(world)
    abstract = submit_abstract(world, title="Ada submission", keywords=["oncology"])
    open_review_phase(world)

    res = api_client.create_review_assignment(
        abstract["id"],
        review_assignment_payload(reviewer_member_id=conflicted["id"]),
        world["chair_headers"],
    )
    validate_error(res, "ERR_REVIEWER_CONFLICT")

    member = validate_success(
        api_client.get_committee_member(conflicted["id"], world["chair_headers"])
    )
    assert member["current_review_load"] == 0, (
        "a conflicted assignment must not move the load ledger"
    )


def test_review_assignment_to_a_reviewer_who_declared_no_conflict_is_accepted():
    """A declaration whose `conflict_subject_type` is `AUTHOR_EMAIL` matches when
    its `conflict_subject_value` is in that set; a declaration whose
    `conflict_subject_type` is `AFFILIATION` matches when its
    `conflict_subject_value` equals the `affiliation` string of any author in
    that set; a declaration whose `conflict_subject_type` is `NONE` never matches
    anything and exists purely to record that the member has considered the
    question.

    The nominated reviewer must belong to the same conference, be `ACTIVE`, and
    have `coi_declaration_status` of `SUBMITTED`; otherwise the request fails
    with `ERR_MEMBER_STATE_INVALID`.

    The reviewer's `current_review_load` rises by one. When this is the first
    non-terminal review of the current round, the abstract moves from
    `SUBMITTED` to `UNDER_REVIEW`.

    Design: Corner/validations/declared_author_conflict_blocks_that_reviewers_assignment
    """
    world = setup_conference_with_committee()
    create_active_member(
        world["conference"]["id"],
        "Rui Alvarez",
        "rui.conflicted@panel.example",
        member_role="REVIEWER",
        expertise_keywords=["oncology"],
        conflict_overrides={
            "conflict_subject_type": "AUTHOR_EMAIL",
            "conflict_subject_value": "ada@lab.example",
            "conflict_type": "COAUTHOR",
        },
    )
    open_call_for_abstracts(world)
    abstract = submit_abstract(world, title="Ada submission", keywords=["oncology"])
    open_review_phase(world)
    mei = world["members"]["mei"]

    res = api_client.create_review_assignment(
        abstract["id"],
        review_assignment_payload(reviewer_member_id=mei["id"]),
        world["chair_headers"],
    )
    review = validate_success(res, 201)
    assert review["reviewer_member_id"] == mei["id"]
    assert review["status"] == "ASSIGNED"

    member = validate_success(
        api_client.get_committee_member(mei["id"], make_reviewer_headers(mei["id"]))
    )
    assert member["current_review_load"] == 1

    live_abstract = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["status"] == "UNDER_REVIEW"


# ─── Schema checks against conference-state checks ───────────────────────


def test_undeclared_decision_enum_is_rejected_ahead_of_the_conference_state_gate():
    """When a single request violates more than one rule, exactly one error is
    reported: the one belonging to the highest band in the following ordering.
    Later violations are never reported, and no partial write ever survives a
    rejection. The bands are strictly ordered from 1 to 21.

    7. **Schema** — required fields present; correct types; enum members
    recognized; string lengths, numeric ranges and ISO 8601 datetime syntax
    valid; unknown fields ignored. Otherwise `ERR_VALIDATION` (400).

    9. **Conference status gate** — the owning conference is in a status that
    permits the operation. Otherwise `ERR_CONFERENCE_STATE_INVALID` (409).

    Design: Corner/validations/schema_validation_outranks_conference_state_and_is_rejected
    """
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    abstract = submit_abstract(world, title="Ada submission", keywords=["oncology"])
    open_review_phase(world)

    before = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )

    res = api_client.decide_abstract(
        abstract["id"],
        decision_payload("MAYBE", before["version"]),
        world["chair_headers"],
    )
    validate_error(res, "ERR_VALIDATION")

    live_abstract = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["decision"] is None
    assert live_abstract["status"] == "SUBMITTED"

    after = validate_success(api_client.get_conference(world["conference"]["id"], ADMIN))
    assert after["version"] == before["version"], (
        "a rejected decision must not advance the conference version"
    )


def test_decision_while_the_conference_is_still_review_open_is_rejected():
    """Decisions are issued one abstract at a time by a chair, from the `SCORED`
    state, while the conference is `REVIEW_CLOSED`.

    9. **Conference status gate** — the owning conference is in a status that
    permits the operation. Otherwise `ERR_CONFERENCE_STATE_INVALID` (409). This
    conference-level gate outranks the acted-on resource's own state: submitting
    a review while the conference is `REVIEW_CLOSED` returns
    `ERR_CONFERENCE_STATE_INVALID` even though the review itself is still
    `ASSIGNED`.

    Design: Corner/validations/schema_validation_outranks_conference_state_and_is_rejected
    """
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    abstract = submit_abstract(world, title="Ada submission", keywords=["oncology"])
    open_review_phase(world)

    before = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert before["status"] == "REVIEW_OPEN"
    assert before["code"] == TEST_DEFAULTS["CONFERENCE_CODE"]

    res = api_client.decide_abstract(
        abstract["id"],
        decision_payload("ORAL", before["version"]),
        world["chair_headers"],
    )
    validate_error(res, "ERR_CONFERENCE_STATE_INVALID")

    live_abstract = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["decision"] is None
    assert live_abstract["status"] == "SUBMITTED"

    after = validate_success(api_client.get_conference(world["conference"]["id"], ADMIN))
    assert after["version"] == before["version"]
    assert after["accepted_oral_count"] == 0
