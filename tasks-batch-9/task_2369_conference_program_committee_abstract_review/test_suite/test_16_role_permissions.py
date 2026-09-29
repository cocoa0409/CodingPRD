"""Who may invoke each operation, and whose row an identity-scoped write may touch.

The committee platform hands out five capacities and keeps them apart. Operations
staff own conference and category setup, committee recruitment, author records
and the committee-member maintenance patch. A program chair owns review
assignment, arbitration, decisions and session construction. A reviewer holds no
operation of its own at all — it is proved authorized only through the review
work assigned to it, its own conflict declaration and its own membership move. An
author submits, revises, confirms and withdraws its own work. Communications
staff alone hold the embargo dimension. Nothing is hierarchical: the most
privileged setup operator still cannot set an embargo, and the chair who runs a
meeting still cannot create one.

Holding the right capacity is only half the gate. On the operations that are
scoped to a single identity — submitting the rubric of a review, moving the
status of an abstract — the caller must additionally be the holder that the row
names. A second reviewer of the same panel presenting the reviewer capacity, or a
second author of the same conference presenting the author capacity, clears the
capacity check and is then refused as the wrong holder; the rightful holder
running the identical call succeeds, so the refusal is an ownership test rather
than a blanket one. Both families of refusal leave the underlying rows, the
reviewer load ledger and the conference counters exactly as they were.
"""

import pytest

from test_helpers import (
    ADMIN,
    PRESS,
    api_client,
    assign_review,
    create_abstract_payload,
    create_accreditation_payload,
    create_active_member,
    create_author,
    create_category,
    create_category_payload,
    create_committee_member_payload,
    create_conference,
    create_conference_payload,
    create_conflict_declaration_payload,
    create_session_payload,
    decision_payload,
    get_conference_version,
    get_success_data,
    make_author_headers,
    make_program_chair_headers,
    make_reviewer_headers,
    member_of,
    open_call_for_abstracts,
    open_review_phase,
    press_action_payload,
    review_assignment_payload,
    set_clock,
    setup_conference_with_committee,
    status_transition_payload,
    submit_abstract,
    submit_review_payload,
    transition_conference,
    update_committee_member_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

EMBARGO_INSTANT = "2026-08-01T00:00:00Z"
SHADOW_CONFERENCE = {
    "name": "Shadow Summit",
    "code": "SHADOW",
    "event_start_utc": "2026-10-01T08:00:00Z",
    "event_end_utc": "2026-10-02T18:00:00Z",
    "abstract_deadline_utc": "2026-04-01T23:59:00Z",
    "review_deadline_utc": "2026-06-01T23:59:00Z",
    "program_freeze_utc": "2026-09-15T00:00:00Z",
    "oral_slot_capacity": 1,
    "poster_slot_capacity": 1,
    "workshop_slot_capacity": 1,
}


def _open_call_with_one_newsworthy_abstract() -> dict:
    """Conference in CFA_OPEN with one category, two authors, two chairs, two
    reviewers, and one newsworthy abstract still in SUBMITTED."""
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    submit_abstract(world, keywords=["oncology"], is_newsworthy=True)
    return world


def _abstract_under_review_with_one_assigned_review() -> dict:
    """The same world driven to REVIEW_OPEN with a single review assigned to Rui,
    so the abstract is UNDER_REVIEW and Mei owns nothing."""
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    abstract = submit_abstract(world, keywords=["oncology"], is_newsworthy=True)
    open_review_phase(world)
    assign_review(world, abstract["id"], world["members"]["rui"]["id"])
    return world


# ─── Exclusive operations refused for every other capacity ───────────────


@pytest.mark.parametrize(
    "probe",
    [
        "press_officer_commits_a_decision",
        "author_assigns_a_reviewer",
        "reviewer_builds_a_session",
    ],
)
def test_chair_only_operations_are_refused_for_every_other_role(probe):
    """A syntactically valid role that is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (403), a decision made from the endpoint table alone with no database reads.
    2. **Role authorization** — the presented role appears among the endpoint's authorized roles. Otherwise `ERR_UNAUTHORIZED` (403). Applies to all endpoints.
    `ProgramChair` owns review assignment, arbitration, decisions, session construction, accreditation validation, disclosure adjudication and change-request approval.
    | POST | `/abstracts/{abstractId}/decision` | Commit an acceptance decision through the capacity waterfall under conference OCC | ProgramChair |
    | POST | `/abstracts/{abstractId}/review-assignments` | Assign a blinded reviewer, explicitly or through the expertise selector | ProgramChair |
    | POST | `/sessions` | Build a themed session and assign its chair | ProgramChair |

    Design: Corner/rbac/exclusive_operations_are_rejected_for_every_other_role
    """
    world = _open_call_with_one_newsworthy_abstract()
    abstract = world["abstracts"][0]
    conference_id = world["conference"]["id"]

    if probe == "press_officer_commits_a_decision":
        response = api_client.decide_abstract(
            abstract["id"],
            decision_payload("ORAL", get_conference_version(conference_id)),
            PRESS,
        )
    elif probe == "author_assigns_a_reviewer":
        response = api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(
                reviewer_member_id=world["members"]["rui"]["id"]
            ),
            make_author_headers(world["authors"]["ada"]["id"]),
        )
    else:
        response = api_client.create_session(
            create_session_payload(conference_id, world["members"]["cho"]["id"]),
            make_reviewer_headers(world["members"]["rui"]["id"]),
        )

    validate_error(response, "ERR_UNAUTHORIZED")


@pytest.mark.parametrize(
    "probe",
    ["reviewer_patches_its_own_member_row", "chair_creates_a_conference"],
)
def test_admin_only_operations_are_refused_for_committee_roles(probe):
    """A syntactically valid role that is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (403), a decision made from the endpoint table alone with no database reads.
    `ConferenceAdmin` owns conference and category setup, committee recruitment, author records and event registration, the logical clock, and the committee-member maintenance patch — and is deliberately excluded from review content, decisions and arbitration.
    | POST | `/conferences` | Create a conference in `DRAFT` | ConferenceAdmin |
    | PATCH | `/committee-members/{memberId}` | Maintain expertise keywords, load ceiling and calibration bias | ConferenceAdmin |

    Design: Corner/rbac/exclusive_operations_are_rejected_for_every_other_role
    """
    world = _open_call_with_one_newsworthy_abstract()
    reviewer = world["members"]["rui"]

    if probe == "reviewer_patches_its_own_member_row":
        response = api_client.update_committee_member(
            reviewer["id"],
            update_committee_member_payload(max_review_load=9),
            make_reviewer_headers(reviewer["id"]),
        )
        validate_error(response, "ERR_UNAUTHORIZED")
        live = get_success_data(
            api_client.get_committee_member(reviewer["id"], ADMIN)
        )
        assert live["max_review_load"] == 4
    else:
        response = api_client.create_conference(
            create_conference_payload(**SHADOW_CONFERENCE),
            make_program_chair_headers(world["members"]["cho"]["id"]),
        )
        validate_error(response, "ERR_UNAUTHORIZED")
        conferences, meta = validate_paginated(api_client.list_conferences(ADMIN))
        assert meta["total_count"] == 1
        assert [row["code"] for row in conferences] == ["GOS26"]


@pytest.mark.parametrize(
    "probe", ["admin_sets_an_embargo", "author_opens_an_accreditation"]
)
def test_press_and_accreditation_operations_are_refused_for_unlisted_roles(probe):
    """A syntactically valid role that is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (403), a decision made from the endpoint table alone with no database reads.
    `PressOfficer` is the sole holder of the embargo dimension.
    `Author` submits and revises abstracts, registers for the event, confirms or withdraws its own accepted work, files disclosures and requests late program changes.
    | POST | `/abstracts/{abstractId}/press-actions` | Set an embargo or record an outlet release | PressOfficer |
    | POST | `/accreditations` | Open a continuing-education accreditation on eligible content | ConferenceAdmin, ProgramChair |

    Design: Corner/rbac/exclusive_operations_are_rejected_for_every_other_role
    """
    world = _open_call_with_one_newsworthy_abstract()
    abstract = world["abstracts"][0]

    if probe == "admin_sets_an_embargo":
        response = api_client.press_action(
            abstract["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc=EMBARGO_INSTANT),
            ADMIN,
        )
        validate_error(response, "ERR_UNAUTHORIZED")
        live = get_success_data(api_client.get_abstract(abstract["id"], ADMIN))
        assert live["embargo_status"] == "NONE"
        assert live["embargo_until_utc"] is None
    else:
        response = api_client.create_accreditation(
            create_accreditation_payload(abstract["id"], 30),
            make_author_headers(world["authors"]["ada"]["id"]),
        )
        validate_error(response, "ERR_UNAUTHORIZED")
        _, meta = validate_paginated(
            api_client.list_accreditations(ADMIN, params={"abstract_id": abstract["id"]})
        )
        assert meta["total_count"] == 0


def test_role_refusals_leave_the_abstract_and_its_conference_untouched():
    """When a single request violates more than one rule, exactly one error is reported: the one belonging to the highest band in the following ordering. Later violations are never reported, and no partial write ever survives a rejection.
    2. **Role authorization** — the presented role appears among the endpoint's authorized roles. Otherwise `ERR_UNAUTHORIZED` (403). Applies to all endpoints.
    A syntactically valid role that is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (403), a decision made from the endpoint table alone with no database reads.

    Design: Corner/rbac/exclusive_operations_are_rejected_for_every_other_role
    """
    world = _open_call_with_one_newsworthy_abstract()
    abstract = world["abstracts"][0]
    conference_id = world["conference"]["id"]
    version_before = get_conference_version(conference_id)

    validate_error(
        api_client.decide_abstract(
            abstract["id"], decision_payload("ORAL", version_before), PRESS
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api_client.press_action(
            abstract["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc=EMBARGO_INSTANT),
            ADMIN,
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=world["members"]["rui"]["id"]),
            make_author_headers(world["authors"]["ada"]["id"]),
        ),
        "ERR_UNAUTHORIZED",
    )

    live_abstract = get_success_data(api_client.get_abstract(abstract["id"], ADMIN))
    assert live_abstract["status"] == "SUBMITTED"
    assert live_abstract["embargo_status"] == "NONE"
    assert live_abstract["decision"] is None
    assert live_abstract["decided_by_member_id"] is None

    live_conference = get_success_data(api_client.get_conference(conference_id, ADMIN))
    assert live_conference["version"] == version_before
    assert live_conference["accepted_oral_count"] == 0

    reviewer = member_of(world, "rui", ADMIN)
    assert reviewer["current_review_load"] == 0


# ─── Each capacity exercising its own declared operations ────────────────


def test_admin_author_and_chair_each_run_their_own_declared_operations():
    """Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — status transitions, adjudications, submissions, declines, registrations, patches and the clock capability — return `200 OK`.
    On acceptance of the submission the conference's `abstract_sequence` counter is incremented and the abstract's `blind_code` is minted deterministically as the conference `code`, a hyphen, the letter `B`, and the post-increment sequence value zero-padded to four digits — the first abstract of a conference whose `code` is `NEURO26` therefore carries the blind code `NEURO26-B0001`.
    A successful assignment creates a review row with `status` `ASSIGNED`, an `assigned_round` frozen to the abstract's current `revision_round`, `is_third_review` false, a computed `expertise_match_score`, and null values for every rubric field, `confidence`, `recommended_format`, `comments_to_authors`, `weighted_score`, `submitted_at` and `decline_reason`.
    When this is the first non-terminal review of the current round, the abstract moves from `SUBMITTED` to `UNDER_REVIEW`.
    | POST | `/categories` | Declare a submission category with its formatting, review and CME policy | ConferenceAdmin |
    | POST | `/conferences/{conferenceId}/status-transitions` | Drive the conference lifecycle, including the extension and reopen back-edges | ConferenceAdmin |
    | POST | `/abstracts` | Submit an abstract to an open call and mint its blind code | Author |
    | POST | `/abstracts/{abstractId}/review-assignments` | Assign a blinded reviewer, explicitly or through the expertise selector | ProgramChair |

    Design: Corner/rbac/each_role_exercises_its_own_declared_operations
    """
    set_clock()
    conference = create_conference()

    category = validate_success(
        api_client.create_category(
            create_category_payload(
                conference["id"],
                code="GEN",
                name="General Oncology",
                min_reviews_required=2,
                discrepancy_threshold=4.00,
            ),
            ADMIN,
        ),
        201,
    )

    opened = validate_success(
        api_client.transition_conference(
            conference["id"], status_transition_payload("CFA_OPEN"), ADMIN
        ),
        200,
    )
    assert opened["status"] == "CFA_OPEN"

    author = create_author("Ada Rivera", "ada@lab.example")
    abstract = validate_success(
        api_client.create_abstract(
            create_abstract_payload(
                conference["id"],
                category["id"],
                author["id"],
                title="A1 permitted path",
                keywords=["oncology"],
                is_newsworthy=True,
            ),
            make_author_headers(author["id"]),
        ),
        201,
    )
    assert abstract["status"] == "SUBMITTED"
    assert abstract["blind_code"] == "GOS26-B0001"

    chair = create_active_member(
        conference["id"],
        "Cho Bekele",
        "cho@panel.example",
        member_role="CHAIR",
        expertise_keywords=["oncology"],
    )
    reviewer = create_active_member(
        conference["id"],
        "Rui Alvarez",
        "rui@panel.example",
        member_role="REVIEWER",
        expertise_keywords=["oncology"],
    )
    transition_conference(conference["id"], "CFA_CLOSED")
    transition_conference(conference["id"], "REVIEW_OPEN")

    chair_headers = make_program_chair_headers(chair["id"])
    review = validate_success(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=reviewer["id"]),
            chair_headers,
        ),
        201,
    )
    assert review["status"] == "ASSIGNED"

    live_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], chair_headers)
    )
    assert live_abstract["status"] == "UNDER_REVIEW"


def test_committee_members_run_their_own_shared_operations():
    """`Reviewer` may act only on reviews assigned to it, file its own conflict declarations and move its own membership status.
    Activation requires at least one conflict declaration already on file for that member; without one the attempt fails with `ERR_COI_NOT_DECLARED`.
    Submission requires that the acting member be the review's own `reviewer_member_id`, that the conference be `REVIEW_OPEN`, that the review's `assigned_round` still equal the abstract's `revision_round` — a mismatch is `ERR_REVIEW_STATE_INVALID` — and that the logical clock be at or before the review's `due_utc`, with a clock strictly after the due instant rejected as `ERR_REVIEW_PAST_DUE`.
    | POST | `/conflict-declarations` | File an immutable conflict-of-interest declaration | ConferenceAdmin, ProgramChair, Reviewer |
    | POST | `/committee-members/{memberId}/status-transitions` | Activation, suspension, reinstatement and resignation | ConferenceAdmin, ProgramChair, Reviewer |
    | POST | `/reviews/{reviewId}/submission` | Submit the rubric and recompute the abstract's consensus and spread | Reviewer, ProgramChair |

    Design: Corner/rbac/each_role_exercises_its_own_declared_operations
    """
    set_clock()
    conference = create_conference()
    category = create_category(
        conference["id"], code="GEN", name="General Oncology", min_reviews_required=2
    )
    author = create_author("Ada Rivera", "ada@lab.example")

    chair = get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(
                conference["id"],
                member_role="CHAIR",
                full_name="Cho Bekele",
                email="cho@panel.example",
            ),
            ADMIN,
        )
    )
    chair_headers = make_program_chair_headers(chair["id"])
    validate_success(
        api_client.create_conflict_declaration(
            create_conflict_declaration_payload(chair["id"]), chair_headers
        ),
        201,
    )
    activated_chair = validate_success(
        api_client.transition_committee_member(
            chair["id"], status_transition_payload("ACTIVE"), chair_headers
        ),
        200,
    )
    assert activated_chair["status"] == "ACTIVE"

    reviewer = get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(
                conference["id"],
                member_role="REVIEWER",
                full_name="Rui Alvarez",
                email="rui@panel.example",
            ),
            ADMIN,
        )
    )
    reviewer_headers = make_reviewer_headers(reviewer["id"])
    validate_success(
        api_client.create_conflict_declaration(
            create_conflict_declaration_payload(reviewer["id"]), reviewer_headers
        ),
        201,
    )
    activated_reviewer = validate_success(
        api_client.transition_committee_member(
            reviewer["id"], status_transition_payload("ACTIVE"), reviewer_headers
        ),
        200,
    )
    assert activated_reviewer["status"] == "ACTIVE"
    assert activated_reviewer["coi_declaration_status"] == "SUBMITTED"

    transition_conference(conference["id"], "CFA_OPEN")
    abstract = get_success_data(
        api_client.create_abstract(
            create_abstract_payload(
                conference["id"],
                category["id"],
                author["id"],
                keywords=["oncology"],
            ),
            make_author_headers(author["id"]),
        )
    )
    transition_conference(conference["id"], "CFA_CLOSED")
    transition_conference(conference["id"], "REVIEW_OPEN")
    review = get_success_data(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=reviewer["id"]),
            chair_headers,
        )
    )

    submitted = validate_success(
        api_client.submit_review(
            review["id"], submit_review_payload(), reviewer_headers
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"


def test_press_embargo_on_an_unreleased_abstract_is_refused_by_state_not_by_role():
    """Setting an embargo moves the abstract's `embargo_status` from `NONE` to `EMBARGOED` and requires that the abstract's `is_newsworthy` be true — otherwise the attempt fails with `ERR_NOT_NEWSWORTHY` — that the abstract's `status` be `ACCEPTED`, `CONFIRMED` or `SCHEDULED`, and that the supplied `embargo_until_utc` be present, strictly later than the logical clock, and at or before the conference's `event_end_utc`; a missing or out-of-window instant is `ERR_EMBARGO_WINDOW_INVALID`.
    10. **Acted-on resource state** — a transition to the requested target exists from the resource's current state, and dependent operations find their prerequisites in the required state. Otherwise one of `ERR_ABSTRACT_STATE_INVALID`, `ERR_REVIEW_STATE_INVALID`, `ERR_MEMBER_STATE_INVALID`, `ERR_CASE_STATE_INVALID`, `ERR_SESSION_STATE_INVALID`, `ERR_SLOT_STATE_INVALID`, `ERR_ACCREDITATION_STATE_INVALID`, `ERR_DISCLOSURE_STATE_INVALID` or `ERR_CHANGE_REQUEST_STATE_INVALID` (409).
    | POST | `/abstracts/{abstractId}/press-actions` | Set an embargo or record an outlet release | PressOfficer |

    Design: Corner/rbac/each_role_exercises_its_own_declared_operations
    """
    world = _abstract_under_review_with_one_assigned_review()
    abstract = world["abstracts"][0]

    response = api_client.press_action(
        abstract["id"],
        press_action_payload("SET_EMBARGO", embargo_until_utc=EMBARGO_INSTANT),
        PRESS,
    )

    error = validate_error(response, "ERR_ABSTRACT_STATE_INVALID")
    assert error["error_id"] != "ERR_UNAUTHORIZED"

    live = get_success_data(api_client.get_abstract(abstract["id"], ADMIN))
    assert live["status"] == "UNDER_REVIEW"
    assert live["embargo_status"] == "NONE"
    assert live["embargo_until_utc"] is None


# ─── Identity-scoped writes and the wrong holder ─────────────────────────


def test_review_submission_by_a_different_reviewer_is_refused_as_not_the_owner():
    """When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `CommitteeMember`, and that member's `member_role` must be `REVIEWER`; a review may only be submitted or declined by the member recorded in its `reviewer_member_id`.
    Once identity resolves, a further ownership gate applies to the operations listed in §2.11 band 6; a principal acting on somebody else's abstract, review, discrepancy case or slot is rejected with `ERR_NOT_RESOURCE_OWNER` (403).
    6. **Ownership** — the resolved identity owns the resource it acts on. Otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to `POST /abstracts/{abstractId}/revisions`, `POST /abstracts/{abstractId}/status-transitions`, `POST /reviews/{reviewId}/submission`, `POST /reviews/{reviewId}/decline`, `POST /discrepancy-cases/{caseId}/resolution` and `POST /program-change-requests`. Ownership needs the row, so it follows existence, but it still precedes body schema validation.
    A committee member's `current_review_load` always equals the number of that member's review rows whose `status` is `ASSIGNED`, and it must never be negative nor exceed that member's `max_review_load`.

    Design: Corner/rbac/identity_scoped_writes_are_rejected_for_the_wrong_holder
    """
    world = _abstract_under_review_with_one_assigned_review()
    abstract = world["abstracts"][0]
    review = world["reviews"][abstract["id"]][0]
    rui = world["members"]["rui"]
    mei = world["members"]["mei"]

    response = api_client.submit_review(
        review["id"],
        submit_review_payload(
            score_originality=5,
            score_methodology=5,
            score_relevance=5,
            score_clarity=5,
            confidence="HIGH",
            recommended_format="ORAL",
        ),
        make_reviewer_headers(mei["id"]),
    )
    validate_error(response, "ERR_NOT_RESOURCE_OWNER")

    live_review = get_success_data(
        api_client.get_review(review["id"], world["chair_headers"])
    )
    assert live_review["status"] == "ASSIGNED"
    assert live_review["weighted_score"] is None
    assert live_review["submitted_at"] is None
    assert member_of(world, "mei", ADMIN)["current_review_load"] == 0

    accepted = validate_success(
        api_client.submit_review(
            review["id"], submit_review_payload(), make_reviewer_headers(rui["id"])
        ),
        200,
    )
    assert accepted["status"] == "SUBMITTED"
    assert member_of(world, "mei", ADMIN)["current_review_load"] == 0


def test_abstract_withdrawal_by_a_different_author_is_refused_as_not_the_owner():
    """When `X-User-Role` is `Author`, `X-User-ID` is the `id` of the acting `Author`; ownership checks compare an abstract's `submitting_author_id`, a slot's `presenter_author_id` or a disclosure's `author_id` to `X-User-ID`.
    Withdrawal is available to the submitting author or to a chair of the conference from any of `SUBMITTED`, `UNDER_REVIEW`, `SCORED`, `WAITLISTED`, `ACCEPTED`, `CONFIRMED` and `SCHEDULED`.
    6. **Ownership** — the resolved identity owns the resource it acts on. Otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to `POST /abstracts/{abstractId}/revisions`, `POST /abstracts/{abstractId}/status-transitions`, `POST /reviews/{reviewId}/submission`, `POST /reviews/{reviewId}/decline`, `POST /discrepancy-cases/{caseId}/resolution` and `POST /program-change-requests`. Ownership needs the row, so it follows existence, but it still precedes body schema validation.

    Design: Corner/rbac/identity_scoped_writes_are_rejected_for_the_wrong_holder
    """
    world = _abstract_under_review_with_one_assigned_review()
    abstract = world["abstracts"][0]

    response = api_client.transition_abstract(
        abstract["id"],
        status_transition_payload("WITHDRAWN", reason="not my paper"),
        make_author_headers(world["authors"]["ben"]["id"]),
    )
    validate_error(response, "ERR_NOT_RESOURCE_OWNER")

    live = get_success_data(api_client.get_abstract(abstract["id"], ADMIN))
    assert live["status"] == "UNDER_REVIEW"

    withdrawn = validate_success(
        api_client.transition_abstract(
            abstract["id"],
            status_transition_payload("WITHDRAWN", reason="author withdraws"),
            make_author_headers(world["authors"]["ada"]["id"]),
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
