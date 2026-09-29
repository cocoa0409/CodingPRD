"""Non-linear lifecycle movement across three entities of the program pipeline.

Three shapes of movement are exercised here, none of them a straight chain:

* the **bounded call-for-abstracts reopen loop** — a closed call may cycle back
  to open exactly once as a deadline extension, rewriting the submission
  cut-off, after which a second extension is refused and the conference simply
  stays closed;
* the **two independent dimensions of an abstract** — its review-and-decision
  status advances under the author while its press embargo dimension advances
  under communications staff, and neither move rewrites the other;
* the **discrepancy third-review fork rejoining a resolved case** — arbitration
  forks out of ARBITER_ASSIGNED into a commissioned tie-breaking review, and the
  branch joins back when that review lands and the trimmed spread clears the
  category threshold.
"""

import pytest

from test_helpers import (
    ADMIN,
    PRESS,
    api_client,
    assign_arbiter,
    confirm_abstract,
    create_active_member,
    create_category,
    create_conference,
    get_success_data,
    make_reviewer_headers,
    press_action_payload,
    release_decisions,
    resolve_case,
    reviews_of,
    set_clock,
    setup_discrepancy_case,
    setup_embargoed_abstract,
    status_transition_payload,
    submit_review_payload,
    transition_conference,
    validate_error,
    validate_success,
)

# ─── The bounded call-for-abstracts reopen loop ───────────────────────────

FIRST_EXTENDED_DEADLINE = "2026-03-20T23:59:00Z"
SECOND_EXTENSION_ATTEMPT = "2026-04-01T23:59:00Z"
ORIGINAL_DEADLINE = "2026-03-01T23:59:00Z"


def _closed_call() -> dict:
    """A conference driven DRAFT -> CFA_OPEN -> CFA_CLOSED with no extension yet."""
    set_clock("2026-01-05T00:00:00Z")
    conference = create_conference()
    create_category(conference["id"])
    transition_conference(conference["id"], "CFA_OPEN")
    return transition_conference(conference["id"], "CFA_CLOSED")


def test_closed_call_reopens_once_and_rewrites_the_submission_deadline():
    """A closed call may be re-opened exactly once, as a deadline extension. That
    back-edge from `CFA_CLOSED` to `CFA_OPEN` requires `cfa_extension_count` to be
    zero and a `new_abstract_deadline_utc` that is present, later than the logical
    clock, later than the current `abstract_deadline_utc`, and earlier than
    `review_deadline_utc`. On success the conference's `abstract_deadline_utc` is
    replaced by that instant, `cfa_extension_count` rises to one, and `version`
    advances.

    Design: Difficulty/non_linear_state_machine/conference_cfa_reopen_cycle_is_bounded_at_one_extension
    """
    closed = _closed_call()
    assert closed["status"] == "CFA_CLOSED"
    assert closed["cfa_extension_count"] == 0
    version_before = closed["version"]

    res = api_client.transition_conference(
        closed["id"],
        status_transition_payload(
            "CFA_OPEN", new_abstract_deadline_utc=FIRST_EXTENDED_DEADLINE
        ),
        ADMIN,
    )
    reopened = validate_success(res)

    assert reopened["status"] == "CFA_OPEN"
    assert reopened["cfa_extension_count"] == 1
    assert reopened["abstract_deadline_utc"] == FIRST_EXTENDED_DEADLINE
    assert reopened["version"] == version_before + 1


def test_second_call_extension_is_refused_and_leaves_the_call_closed():
    """A closed call may be re-opened exactly once, as a deadline extension. That
    back-edge from `CFA_CLOSED` to `CFA_OPEN` requires `cfa_extension_count` to be
    zero and a `new_abstract_deadline_utc` that is present, later than the logical
    clock, later than the current `abstract_deadline_utc`, and earlier than
    `review_deadline_utc`. A second extension attempt is rejected with
    `ERR_CFA_EXTENSION_LIMIT`.

    Closing the call — `CFA_OPEN` to `CFA_CLOSED` — has no preconditions at all, and
    it is worth being explicit about the corollary: passing `abstract_deadline_utc`
    does **not** close the call by itself.

    Design: Difficulty/non_linear_state_machine/conference_cfa_reopen_cycle_is_bounded_at_one_extension
    """
    closed = _closed_call()

    first = validate_success(
        api_client.transition_conference(
            closed["id"],
            status_transition_payload(
                "CFA_OPEN", new_abstract_deadline_utc=FIRST_EXTENDED_DEADLINE
            ),
            ADMIN,
        )
    )
    assert first["cfa_extension_count"] == 1

    transition_conference(closed["id"], "CFA_CLOSED")

    res = api_client.transition_conference(
        closed["id"],
        status_transition_payload(
            "CFA_OPEN", new_abstract_deadline_utc=SECOND_EXTENSION_ATTEMPT
        ),
        ADMIN,
    )
    validate_error(res, "ERR_CFA_EXTENSION_LIMIT")

    after = get_success_data(api_client.get_conference(closed["id"], ADMIN))
    assert after["status"] == "CFA_CLOSED"
    assert after["cfa_extension_count"] == 1
    assert after["abstract_deadline_utc"] == FIRST_EXTENDED_DEADLINE


def test_first_call_extension_replaces_the_original_deadline_instant():
    """On success the conference's `abstract_deadline_utc` is replaced by that
    instant, `cfa_extension_count` rises to one, and `version` advances.

    Design: Difficulty/non_linear_state_machine/conference_cfa_reopen_cycle_is_bounded_at_one_extension
    """
    closed = _closed_call()
    assert closed["abstract_deadline_utc"] == ORIGINAL_DEADLINE

    validate_success(
        api_client.transition_conference(
            closed["id"],
            status_transition_payload(
                "CFA_OPEN", new_abstract_deadline_utc=FIRST_EXTENDED_DEADLINE
            ),
            ADMIN,
        )
    )

    after = get_success_data(api_client.get_conference(closed["id"], ADMIN))
    assert after["abstract_deadline_utc"] == FIRST_EXTENDED_DEADLINE
    assert after["cfa_extension_count"] == 1


# ─── The two independent dimensions of one abstract ───────────────────────

EMBARGO_UNTIL = "2026-09-02T12:00:00Z"
OUTLET = "Northline Daily"


def _embargoed_acceptance_ready_to_confirm() -> dict:
    """An accepted, newsworthy abstract under embargo with decisions released."""
    world = setup_embargoed_abstract(embargo_until_utc=EMBARGO_UNTIL)
    release_decisions(world)
    return world


def test_abstract_confirmation_leaves_the_embargo_dimension_untouched():
    """An abstract carries **two independent state dimensions**. Its `status` tracks
    the review and decision lifecycle across `SUBMITTED`, `UNDER_REVIEW`, `SCORED`,
    `REVISION_REQUESTED`, `ACCEPTED`, `WAITLISTED`, `REJECTED`, `CONFIRMED`,
    `SCHEDULED`, `PRESENTED`, `NO_SHOW` and `WITHDRAWN`, of which `REJECTED`,
    `PRESENTED`, `NO_SHOW` and `WITHDRAWN` are terminal. Its `embargo_status` tracks
    press handling across `NONE`, `EMBARGOED`, `RELEASED` and `BREACHED`. The two
    dimensions evolve independently: an abstract whose embargo has been breached
    keeps whatever review or decision status it had, and a breach never blocks a
    scheduling operation on its own.

    Setting an embargo moves the abstract's `embargo_status` from `NONE` to
    `EMBARGOED` and requires that the abstract's `is_newsworthy` be true —
    otherwise the attempt fails with `ERR_NOT_NEWSWORTHY` — that the abstract's
    `status` be `ACCEPTED`, `CONFIRMED` or `SCHEDULED`, and that the supplied
    `embargo_until_utc` be present, strictly later than the logical clock, and at or
    before the conference's `event_end_utc`; a missing or out-of-window instant is
    `ERR_EMBARGO_WINDOW_INVALID`. The instant is stored on the abstract as
    `embargo_until_utc`.

    Design: Difficulty/non_linear_state_machine/abstract_status_and_embargo_dimensions_advance_independently
    """
    world = _embargoed_acceptance_ready_to_confirm()
    abstract = world["abstracts"][0]
    assert abstract["status"] == "ACCEPTED"
    assert abstract["embargo_status"] == "EMBARGOED"

    confirmed = confirm_abstract(world, abstract["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["embargo_status"] == "EMBARGOED"
    assert confirmed["embargo_until_utc"] == EMBARGO_UNTIL
    assert confirmed["decision"] == "ORAL"


def test_embargo_breach_leaves_the_confirmed_review_status_untouched():
    """The two dimensions evolve independently: an abstract whose embargo has been
    breached keeps whatever review or decision status it had, and a breach never
    blocks a scheduling operation on its own.

    When the logical clock is strictly earlier than `embargo_until_utc`, the very
    same request instead records `press_outlet_name` and lands in `BREACHED`, running
    Cascade E: the submitting author's `embargo_breach_count` is recomputed and their
    `sanction_status` is re-derived, which can bar an author who has also missed a
    presentation.

    Design: Difficulty/non_linear_state_machine/abstract_status_and_embargo_dimensions_advance_independently
    """
    world = _embargoed_acceptance_ready_to_confirm()
    abstract = world["abstracts"][0]
    confirm_abstract(world, abstract["id"])

    res = api_client.press_action(
        abstract["id"], press_action_payload("RELEASE", outlet_name=OUTLET), PRESS
    )
    breached = validate_success(res)

    assert breached["embargo_status"] == "BREACHED"
    assert breached["press_outlet_name"] == OUTLET
    assert breached["status"] == "CONFIRMED"
    assert breached["decision"] == "ORAL"
    assert breached["embargo_until_utc"] == EMBARGO_UNTIL


def test_confirmed_abstract_keeps_its_closing_final_score_across_both_dimensions():
    """The **final** variant is a confidence-weighted mean. Each review is given a
    weight from its `confidence` — 1 for `LOW`, 2 for `MEDIUM`, 3 for `HIGH` — and
    the score is the sum of each review's weight multiplied by its `weighted_score`,
    divided by the sum of those weights, rounded half up to two decimal places.

    When it succeeds, it fans out across the conference: every abstract that is
    `UNDER_REVIEW` with a `submitted_review_count` of at least its category's
    `min_reviews_required` advances to `SCORED`; every abstract that is
    `UNDER_REVIEW` or `SCORED` with at least one submitted review gets its
    `final_score` written from the final consensus variant; every review of the
    conference still in `ASSIGNED` status becomes `VOIDED`, with each affected
    reviewer's `current_review_load` lowered by one so the load ledger stays exact;
    and the conference's `version` advances.

    Design: Difficulty/non_linear_state_machine/abstract_status_and_embargo_dimensions_advance_independently
    """
    world = _embargoed_acceptance_ready_to_confirm()
    abstract = world["abstracts"][0]
    confirm_abstract(world, abstract["id"])
    validate_success(
        api_client.press_action(
            abstract["id"], press_action_payload("RELEASE", outlet_name=OUTLET), PRESS
        )
    )

    live = get_success_data(api_client.get_abstract(abstract["id"], ADMIN))
    assert live["status"] == "CONFIRMED"
    assert live["embargo_status"] == "BREACHED"
    assert float(live["final_score"]) == pytest.approx(3.60, abs=0.01)


def test_embargo_breach_walks_the_author_sanction_ladder_to_warned():
    """Two kinds of misconduct accumulate against an author. `no_show_strikes` is
    the number of session slots recorded as `NO_SHOW_RECORDED` whose presenter is
    this author; `embargo_breach_count` is the number of this author's abstracts
    whose embargo dimension reached `BREACHED`. The `sanction_status` ladder is
    derived from their sum: a combined count of zero leaves the author at `NONE`, a
    combined count of exactly one moves them to `WARNED`, and a combined count of
    two or more moves them to `BARRED`.

    Design: Difficulty/non_linear_state_machine/abstract_status_and_embargo_dimensions_advance_independently
    """
    world = _embargoed_acceptance_ready_to_confirm()
    abstract = world["abstracts"][0]
    author_id = world["authors"]["ada"]["id"]
    confirm_abstract(world, abstract["id"])

    validate_success(
        api_client.press_action(
            abstract["id"], press_action_payload("RELEASE", outlet_name=OUTLET), PRESS
        )
    )

    author = get_success_data(api_client.get_author(author_id, ADMIN))
    assert author["embargo_breach_count"] == 1
    assert author["no_show_strikes"] == 0
    assert author["sanction_status"] == "WARNED"


# ─── The discrepancy third-review fork and its join ───────────────────────

HIGH_ARBITRATION_REVIEW = {
    "score_originality": 5,
    "score_methodology": 4,
    "score_relevance": 3,
    "score_clarity": 4,
    "confidence": "HIGH",
    "recommended_format": "ORAL",
}
LOW_ARBITRATION_REVIEW = {
    "score_originality": 2,
    "score_methodology": 3,
    "score_relevance": 3,
    "score_clarity": 3,
    "confidence": "LOW",
    "recommended_format": "POSTER",
}


def _disputed_abstract_with_spare_reviewer() -> dict:
    """A spread of 1.65 against a threshold of 1.50 opens a case; one further
    reviewer with a Dice fit of 0.8000 is the only third-review candidate."""
    world = setup_discrepancy_case(
        discrepancy_threshold=1.50,
        first_review=HIGH_ARBITRATION_REVIEW,
        second_review=LOW_ARBITRATION_REVIEW,
        abstract_overrides={"keywords": ["oncology", "immunotherapy", "imaging"]},
        reviewer_keywords=["oncology", "imaging"],
        second_reviewer_keywords=["oncology", "genomics"],
    )
    world["members"]["nadia"] = create_active_member(
        world["conference"]["id"],
        "Nadia Lund",
        "nadia@panel.example",
        member_role="REVIEWER",
        expertise_keywords=["oncology", "immunotherapy"],
    )
    return world


def _third_review_of(world: dict, abstract_id: str) -> dict:
    third = [r for r in reviews_of(world, abstract_id) if r["is_third_review"]]
    assert len(third) == 1, "the third-review branch commissions exactly one review"
    return third[0]


def test_discrepancy_case_opens_on_the_two_review_spread():
    """With exactly two, the spread is the absolute difference between the two
    `weighted_score` values, rounded half up to two decimal places.

    A discrepancy case is opened whenever the recomputed spread is greater than or
    equal to the category's `discrepancy_threshold` and no non-terminal case already
    exists for that abstract; the boundary is inclusive, so with a threshold of 1.50
    a spread of exactly 1.50 opens a case while 1.49 does not. The case is created
    with `status` `OPEN`, its
    `spread_at_open` frozen to the abstract's spread at that instant, and
    `arbiter_member_id`, `third_review_id`, `resolution_method` and `resolved_score`
    all null.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_third_review_fork_joins_back_to_resolved
    """
    world = _disputed_abstract_with_spare_reviewer()
    abstract = world["abstracts"][0]
    scored = reviews_of(world, abstract["id"])

    weighted = sorted(float(r["weighted_score"]) for r in scored)
    assert weighted[1] == pytest.approx(4.25, abs=0.01)
    assert weighted[0] == pytest.approx(2.60, abs=0.01)

    case = world["case"]
    assert case is not None, "a spread of 1.65 against a threshold of 1.50 opens a case"
    assert case["status"] == "OPEN"
    assert float(case["spread_at_open"]) == pytest.approx(1.65, abs=0.01)
    assert case["arbiter_member_id"] is None
    assert case["third_review_id"] is None
    assert case["resolution_method"] is None
    assert case["resolved_score"] is None


def test_arbitration_forks_into_a_commissioned_third_review():
    """Assigning the arbiter moves the case from `OPEN` to `ARBITER_ASSIGNED` and
    requires that the nominated `arbiter_member_id` identify a member whose
    `member_role` is `CHAIR`, whose `status` is `ACTIVE`, and whose conference matches
    the abstract's conference.

    **Third review.** Choosing `THIRD_REVIEW` moves the case to
    `THIRD_REVIEW_PENDING` and commissions a tie-breaking review. On success the case
    records `resolution_method` `THIRD_REVIEW`, a review is created in `ASSIGNED`
    status with `is_third_review` true and chosen by the selector's match-score
    ranking, the chosen reviewer's `current_review_load` rises by one, and the new
    review's identifier is stored on the case as `third_review_id`.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_third_review_fork_joins_back_to_resolved
    """
    world = _disputed_abstract_with_spare_reviewer()
    abstract = world["abstracts"][0]
    chair = world["members"]["cho"]
    nadia = world["members"]["nadia"]

    assigned = assign_arbiter(world, world["case"]["id"], chair["id"])
    assert assigned["status"] == "ARBITER_ASSIGNED"
    assert assigned["arbiter_member_id"] == chair["id"]

    forked = resolve_case(world, world["case"]["id"], "THIRD_REVIEW")
    assert forked["status"] == "THIRD_REVIEW_PENDING"
    assert forked["resolution_method"] == "THIRD_REVIEW"
    assert forked["resolved_score"] is None

    third = _third_review_of(world, abstract["id"])
    assert forked["third_review_id"] == third["id"]
    assert third["status"] == "ASSIGNED"
    assert third["reviewer_member_id"] == nadia["id"]

    live_nadia = get_success_data(
        api_client.get_committee_member(nadia["id"], world["chair_headers"])
    )
    assert live_nadia["current_review_load"] == 1


def test_third_review_selection_scores_the_dice_expertise_fit():
    """The expertise fit between a candidate and an abstract is the Dice coefficient
    over their keyword sets. Both sets are lowercased and de-duplicated first: the
    candidate's `expertise_keywords` on one side, the abstract's `keywords` on the
    other. The score is twice the number of keywords the two sets share, divided by
    the sum of the two set sizes, rounded half up to four decimal places.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_third_review_fork_joins_back_to_resolved
    """
    world = _disputed_abstract_with_spare_reviewer()
    abstract = world["abstracts"][0]
    assign_arbiter(world, world["case"]["id"], world["members"]["cho"]["id"])
    resolve_case(world, world["case"]["id"], "THIRD_REVIEW")

    third = _third_review_of(world, abstract["id"])
    assert float(third["expertise_match_score"]) == pytest.approx(0.8000, abs=0.0001)


def test_third_review_submission_trims_the_spread_and_joins_at_resolved():
    """With three or more, the spread is the value that survives discarding a single
    outlier: for each review in turn, remove it, take the difference between the
    largest and the smallest `weighted_score` among the remaining reviews, and let the
    spread be the smallest of those differences, rounded half up to two decimal
    places.

    The two branches rejoin when that third review is submitted. Its submission
    recomputes the abstract's spread as usual, and the case then resolves on the
    comparison: if the recomputed `score_spread` is strictly less than the category's
    `discrepancy_threshold`, the case moves from `THIRD_REVIEW_PENDING` to `RESOLVED`,
    its `resolved_score` is set to the final consensus variant computed over the
    round's submitted reviews, and the abstract's `final_score` is set to that same
    value.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_third_review_fork_joins_back_to_resolved
    """
    world = _disputed_abstract_with_spare_reviewer()
    abstract = world["abstracts"][0]
    nadia = world["members"]["nadia"]
    assign_arbiter(world, world["case"]["id"], world["members"]["cho"]["id"])
    resolve_case(world, world["case"]["id"], "THIRD_REVIEW")
    third = _third_review_of(world, abstract["id"])

    res = api_client.submit_review(
        third["id"],
        submit_review_payload(
            score_originality=3,
            score_methodology=3,
            score_relevance=4,
            score_clarity=4,
            confidence="MEDIUM",
            recommended_format="ORAL",
        ),
        make_reviewer_headers(nadia["id"]),
    )
    submitted = validate_success(res)
    assert float(submitted["weighted_score"]) == pytest.approx(3.30, abs=0.01)

    live_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert float(live_abstract["score_spread"]) == pytest.approx(0.70, abs=0.01)

    joined = get_success_data(
        api_client.get_discrepancy_case(world["case"]["id"], world["chair_headers"])
    )
    assert joined["status"] == "RESOLVED"
    assert joined["resolution_method"] == "THIRD_REVIEW"
    assert float(joined["resolved_score"]) == pytest.approx(3.66, abs=0.01)
    assert float(live_abstract["final_score"]) == pytest.approx(3.66, abs=0.01)


def test_joined_case_leaves_the_abstract_with_three_counted_reviews():
    """The submission then stamps `submitted_at` from the logical clock, lowers the
    reviewer's `current_review_load` by one, raises the abstract's
    `submitted_review_count`, and refreshes the abstract's `provisional_score` and
    `score_spread`.

    The **provisional** variant is the plain arithmetic mean: the sum of the
    `weighted_score` values divided by the number of reviews in the set, rounded half
    up to two decimal places.

    Design: Difficulty/non_linear_state_machine/discrepancy_case_third_review_fork_joins_back_to_resolved
    """
    world = _disputed_abstract_with_spare_reviewer()
    abstract = world["abstracts"][0]
    nadia = world["members"]["nadia"]
    assign_arbiter(world, world["case"]["id"], world["members"]["cho"]["id"])
    resolve_case(world, world["case"]["id"], "THIRD_REVIEW")
    third = _third_review_of(world, abstract["id"])

    validate_success(
        api_client.submit_review(
            third["id"],
            submit_review_payload(
                score_originality=3,
                score_methodology=3,
                score_relevance=4,
                score_clarity=4,
                confidence="MEDIUM",
                recommended_format="ORAL",
            ),
            make_reviewer_headers(nadia["id"]),
        )
    )

    live_abstract = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["submitted_review_count"] == 3
    assert float(live_abstract["provisional_score"]) == pytest.approx(3.38, abs=0.01)

    live_nadia = get_success_data(
        api_client.get_committee_member(nadia["id"], world["chair_headers"])
    )
    assert live_nadia["current_review_load"] == 0
