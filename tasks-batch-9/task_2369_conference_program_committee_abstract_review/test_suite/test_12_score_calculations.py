"""Score arithmetic across the review pipeline.

Five figures are exercised here. A single review's rubric roll-up, where the
four axes are weighted forty / thirty / fifteen / fifteen and the reviewing
member's own calibration bias is added to the weighted total afterwards rather
than to the individual axes. The legal band that total is clamped into, so a
generous bias on a perfect rubric stops at the score ceiling instead of running
past it. Which review rows feed the abstract's consensus figures — an
assignment the reviewer declined contributes nothing at all and is not read as a
zero. The keyword-overlap selector that picks a reviewer when the chair names
none, ranking candidates by the share of keywords they have in common with the
abstract. And the moment the confidence-weighted consensus figure is written:
while the call for reviews is still open only the plain mean is published, and
the confidence-weighted figure appears when the review phase closes.
"""

import pytest

from test_helpers import (
    ADMIN,
    api_client,
    assert_four_decimal_places,
    assert_two_decimal_places,
    assign_review,
    create_active_member,
    decline_review_payload,
    make_program_chair_headers,
    make_reviewer_headers,
    open_call_for_abstracts,
    open_review_phase,
    review_assignment_payload,
    setup_abstract_under_review,
    setup_conference_with_committee,
    setup_scored_abstract,
    status_transition_payload,
    submit_abstract,
    submit_review_payload,
    validate_success,
)

CATEGORY_POLICY = {"min_reviews_required": 2, "discrepancy_threshold": 4.00}

# The logical clock every composite fixture pins before building state.
PINNED_CLOCK_PREFIX = "2026-01-05T00:00:00"


def _abstract_with_three_assigned_reviews() -> dict:
    """One abstract carrying three ASSIGNED reviews — Rui, Mei and Nadia — each
    reviewer on a zero calibration bias."""
    world = setup_conference_with_committee(category_overrides=CATEGORY_POLICY)
    world["members"]["nadia"] = create_active_member(
        world["conference"]["id"],
        "Nadia Lund",
        "nadia@panel.example",
        member_role="REVIEWER",
        expertise_keywords=["oncology", "immunotherapy"],
        max_review_load=4,
    )
    open_call_for_abstracts(world)
    abstract = submit_abstract(world)
    open_review_phase(world)
    for reviewer_key in ("rui", "mei", "nadia"):
        assign_review(world, abstract["id"], world["members"][reviewer_key]["id"])
    return world


def _selector_world() -> dict:
    """A REVIEW_OPEN conference whose two reviewers share a different number of
    keywords with the abstract: Rui two-and-two sharing one, Mei three-and-two
    sharing two."""
    world = setup_conference_with_committee(
        category_overrides=CATEGORY_POLICY,
        reviewer_keywords=["oncology", "imaging"],
        second_reviewer_keywords=["oncology", "immunotherapy", "genomics"],
    )
    open_call_for_abstracts(world)
    submit_abstract(world, keywords=["oncology", "immunotherapy"])
    open_review_phase(world)
    return world


# ─── The rubric roll-up and the reviewer's calibration bias ──────────────


def test_weighted_score_adds_a_negative_calibration_bias_after_the_weighting():
    """PRD: "The review's `weighted_score` is built by taking forty percent of `score_originality`, thirty percent of `score_methodology`, fifteen percent of `score_clarity` and fifteen percent of `score_relevance`, and adding those four contributions together. The reviewer's `calibration_bias` is then added to that total. The result is rounded half up to two decimal places and finally clamped into the legal band: anything below 1.00 becomes 1.00 and anything above 5.50 becomes 5.50."
    PRD: "Rubric scores of 5, 4, 3 and 3 for originality, methodology, clarity and relevance respectively therefore contribute 2.00, 1.20, 0.45 and 0.45, for a total of 4.10, which with a zero bias is a `weighted_score` of 4.10; the same rubric from a reviewer whose `calibration_bias` is minus 0.35 gives 3.75."
    PRD: "Two optional inputs tune the member's behaviour: `max_review_load`, defaulting to 4 and constrained to between 1 and 20, is the ceiling on concurrently assigned reviews, and `calibration_bias`, defaulting to 0.00 and constrained to between minus 1.00 and plus 1.00 at two decimals, is the offset carried over from prior conferences that is added to every rubric total this member produces."
    PRD: "The submission then stamps `submitted_at` from the logical clock, lowers the reviewer's `current_review_load` by one, raises the abstract's `submitted_review_count`, and refreshes the abstract's `provisional_score` and `score_spread`."
    PRD: "A review's `weighted_score`, an abstract's `provisional_score`, `final_score` and `score_spread`, a case's `spread_at_open` and `resolved_score`, a session's `accredited_credit_total` and an accreditation's `awarded_credits` are all carried at **two decimal places**, rounded half up."

    Design: Corner/calculations/weighted_score_applies_the_reviewers_negative_calibration_bias
    """
    world = setup_abstract_under_review(
        category_overrides=CATEGORY_POLICY, calibration_bias=-0.35
    )
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    review = world["reviews"][abstract["id"]][0]

    response = api_client.submit_review(
        review["id"],
        submit_review_payload(
            score_originality=5,
            score_methodology=4,
            score_relevance=3,
            score_clarity=3,
            confidence="HIGH",
            recommended_format="ORAL",
        ),
        make_reviewer_headers(rui["id"]),
    )
    validate_success(response)
    submitted = response.json()["data"]

    assert submitted["weighted_score"] == pytest.approx(3.75, abs=0.01)
    assert_two_decimal_places(submitted["weighted_score"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"].startswith(PINNED_CLOCK_PREFIX)


def test_provisional_score_mirrors_a_single_biased_review_with_a_null_spread():
    """PRD: "Rubric scores of 5, 4, 3 and 3 for originality, methodology, clarity and relevance respectively therefore contribute 2.00, 1.20, 0.45 and 0.45, for a total of 4.10, which with a zero bias is a `weighted_score` of 4.10; the same rubric from a reviewer whose `calibration_bias` is minus 0.35 gives 3.75."
    PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places. It is written to `provisional_score` on every review submission and is the only consensus figure available while review is still open."
    PRD: "With fewer than two submitted reviews the spread is null and no dispute can open."
    PRD: "The submission then stamps `submitted_at` from the logical clock, lowers the reviewer's `current_review_load` by one, raises the abstract's `submitted_review_count`, and refreshes the abstract's `provisional_score` and `score_spread`. When `submitted_review_count` reaches the category's `min_reviews_required`, the abstract advances from `UNDER_REVIEW` to `SCORED`."
    PRD: "A committee member's `current_review_load` always equals the number of that member's review rows whose `status` is `ASSIGNED`, and it must never be negative nor exceed that member's `max_review_load`. Every assignment raises it by exactly one; every submission, every decline and every system-driven void lowers it by exactly one."

    Design: Corner/calculations/weighted_score_applies_the_reviewers_negative_calibration_bias
    """
    world = setup_abstract_under_review(
        category_overrides=CATEGORY_POLICY, calibration_bias=-0.35
    )
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    review = world["reviews"][abstract["id"]][0]

    validate_success(
        api_client.submit_review(
            review["id"],
            submit_review_payload(
                score_originality=5,
                score_methodology=4,
                score_relevance=3,
                score_clarity=3,
                confidence="HIGH",
                recommended_format="ORAL",
            ),
            make_reviewer_headers(rui["id"]),
        )
    )

    read = api_client.get_abstract(abstract["id"], world["chair_headers"])
    validate_success(read)
    scored = read.json()["data"]
    assert scored["submitted_review_count"] == 1
    assert scored["provisional_score"] == pytest.approx(3.75, abs=0.01)
    assert_two_decimal_places(scored["provisional_score"])
    assert scored["score_spread"] is None
    assert scored["status"] == "UNDER_REVIEW"

    member_read = api_client.get_committee_member(rui["id"], world["chair_headers"])
    validate_success(member_read)
    assert member_read.json()["data"]["current_review_load"] == 0


def test_weighted_score_clamps_at_the_ceiling_when_a_positive_bias_overshoots():
    """PRD: "The review's `weighted_score` is built by taking forty percent of `score_originality`, thirty percent of `score_methodology`, fifteen percent of `score_clarity` and fifteen percent of `score_relevance`, and adding those four contributions together. The reviewer's `calibration_bias` is then added to that total. The result is rounded half up to two decimal places and finally clamped into the legal band: anything below 1.00 becomes 1.00 and anything above 5.50 becomes 5.50."
    PRD: "Two optional inputs tune the member's behaviour: `max_review_load`, defaulting to 4 and constrained to between 1 and 20, is the ceiling on concurrently assigned reviews, and `calibration_bias`, defaulting to 0.00 and constrained to between minus 1.00 and plus 1.00 at two decimals, is the offset carried over from prior conferences that is added to every rubric total this member produces."

    Design: Corner/calculations/weighted_score_clamps_at_the_five_point_five_ceiling
    """
    world = setup_abstract_under_review(
        category_overrides=CATEGORY_POLICY, calibration_bias=1.00
    )
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    review = world["reviews"][abstract["id"]][0]

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
        make_reviewer_headers(rui["id"]),
    )
    validate_success(response)
    submitted = response.json()["data"]

    assert submitted["weighted_score"] == pytest.approx(5.50, abs=0.01)
    assert_two_decimal_places(submitted["weighted_score"])


def test_provisional_score_inherits_the_clamped_weighted_score():
    """PRD: "The result is rounded half up to two decimal places and finally clamped into the legal band: anything below 1.00 becomes 1.00 and anything above 5.50 becomes 5.50."
    PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places. It is written to `provisional_score` on every review submission and is the only consensus figure available while review is still open."
    PRD: "The submission then stamps `submitted_at` from the logical clock, lowers the reviewer's `current_review_load` by one, raises the abstract's `submitted_review_count`, and refreshes the abstract's `provisional_score` and `score_spread`."

    Design: Corner/calculations/weighted_score_clamps_at_the_five_point_five_ceiling
    """
    world = setup_abstract_under_review(
        category_overrides=CATEGORY_POLICY, calibration_bias=1.00
    )
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    review = world["reviews"][abstract["id"]][0]

    validate_success(
        api_client.submit_review(
            review["id"],
            submit_review_payload(
                score_originality=5,
                score_methodology=5,
                score_relevance=5,
                score_clarity=5,
                confidence="HIGH",
                recommended_format="ORAL",
            ),
            make_reviewer_headers(rui["id"]),
        )
    )

    read = api_client.get_abstract(abstract["id"], world["chair_headers"])
    validate_success(read)
    scored = read.json()["data"]
    assert scored["provisional_score"] == pytest.approx(5.50, abs=0.01)
    assert_two_decimal_places(scored["provisional_score"])
    assert scored["submitted_review_count"] == 1


# ─── Which review rows feed the consensus figures ────────────────────────


def test_provisional_score_averages_only_the_submitted_reviews_of_the_round():
    """PRD: "Both consensus scores read exactly the same rows: every review of the abstract whose `status` is `SUBMITTED` and whose `assigned_round` equals the abstract's current `revision_round`. When that set is empty, both scores are null."
    PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places."
    PRD: "The review moves from `ASSIGNED` to `DECLINED` and the reviewer's `current_review_load` falls by one. An optional `auto_reassign` flag defaults to true, in which case a replacement review is created by the selector with the declining member in the exclusion set; when `auto_reassign` is false, or when the candidate pool is empty, no replacement appears and the decline still returns success."
    PRD: "A successful assignment creates a review row with `status` `ASSIGNED`, an `assigned_round` frozen to the abstract's current `revision_round`, `is_third_review` false, a computed `expertise_match_score`, and null values for every rubric field, `confidence`, `recommended_format`, `comments_to_authors`, `weighted_score`, `submitted_at` and `decline_reason`."
    PRD: "Note that `submitted_review_count` counts only reviews whose `assigned_round` equals the abstract's current `revision_round`, so a revision resets the count without deleting anything."

    Design: Corner/calculations/declined_reviews_are_excluded_from_the_consensus_input_set
    """
    world = _abstract_with_three_assigned_reviews()
    abstract = world["abstracts"][0]
    rui_review, mei_review, nadia_review = world["reviews"][abstract["id"]]

    declined = api_client.decline_review(
        rui_review["id"],
        decline_review_payload(
            decline_reason="outside my subspecialty", auto_reassign=False
        ),
        make_reviewer_headers(world["members"]["rui"]["id"]),
    )
    validate_success(declined)
    assert declined.json()["data"]["status"] == "DECLINED"
    assert declined.json()["data"]["weighted_score"] is None

    high = api_client.submit_review(
        mei_review["id"],
        submit_review_payload(
            score_originality=4,
            score_methodology=4,
            score_relevance=4,
            score_clarity=4,
            confidence="HIGH",
            recommended_format="ORAL",
        ),
        make_reviewer_headers(world["members"]["mei"]["id"]),
    )
    validate_success(high)
    assert high.json()["data"]["weighted_score"] == pytest.approx(4.00, abs=0.01)

    medium = api_client.submit_review(
        nadia_review["id"],
        submit_review_payload(
            score_originality=3,
            score_methodology=3,
            score_relevance=3,
            score_clarity=3,
            confidence="MEDIUM",
            recommended_format="ORAL",
        ),
        make_reviewer_headers(world["members"]["nadia"]["id"]),
    )
    validate_success(medium)
    assert medium.json()["data"]["weighted_score"] == pytest.approx(3.00, abs=0.01)

    read = api_client.get_abstract(abstract["id"], world["chair_headers"])
    validate_success(read)
    scored = read.json()["data"]
    assert scored["submitted_review_count"] == 2
    assert scored["provisional_score"] == pytest.approx(3.50, abs=0.01)
    assert_two_decimal_places(scored["provisional_score"])


def test_score_spread_reads_the_two_submitted_reviews_and_opens_no_dispute():
    """PRD: "Both consensus scores read exactly the same rows: every review of the abstract whose `status` is `SUBMITTED` and whose `assigned_round` equals the abstract's current `revision_round`. When that set is empty, both scores are null."
    PRD: "With exactly two, the spread is the absolute difference between the two `weighted_score` values, rounded half up to two decimal places."
    PRD: "A discrepancy case is opened whenever the recomputed spread is greater than or equal to the category's `discrepancy_threshold` and no non-terminal case already exists for that abstract; the boundary is inclusive, so with a threshold of 1.50 a spread of exactly 1.50 opens a case while 1.49 does not."
    PRD: "When `submitted_review_count` reaches the category's `min_reviews_required`, the abstract advances from `UNDER_REVIEW` to `SCORED`."

    Design: Corner/calculations/declined_reviews_are_excluded_from_the_consensus_input_set
    """
    world = _abstract_with_three_assigned_reviews()
    abstract = world["abstracts"][0]
    rui_review, mei_review, nadia_review = world["reviews"][abstract["id"]]

    validate_success(
        api_client.decline_review(
            rui_review["id"],
            decline_review_payload(
                decline_reason="outside my subspecialty", auto_reassign=False
            ),
            make_reviewer_headers(world["members"]["rui"]["id"]),
        )
    )
    validate_success(
        api_client.submit_review(
            mei_review["id"],
            submit_review_payload(
                score_originality=4,
                score_methodology=4,
                score_relevance=4,
                score_clarity=4,
                confidence="HIGH",
                recommended_format="ORAL",
            ),
            make_reviewer_headers(world["members"]["mei"]["id"]),
        )
    )
    validate_success(
        api_client.submit_review(
            nadia_review["id"],
            submit_review_payload(
                score_originality=3,
                score_methodology=3,
                score_relevance=3,
                score_clarity=3,
                confidence="MEDIUM",
                recommended_format="ORAL",
            ),
            make_reviewer_headers(world["members"]["nadia"]["id"]),
        )
    )

    read = api_client.get_abstract(abstract["id"], world["chair_headers"])
    validate_success(read)
    scored = read.json()["data"]
    assert scored["score_spread"] == pytest.approx(1.00, abs=0.01)
    assert_two_decimal_places(scored["score_spread"])
    assert scored["status"] == "SCORED"

    cases = api_client.list_discrepancy_cases(
        world["chair_headers"], params={"abstract_id": abstract["id"]}
    )
    validate_success(cases)
    assert cases.json()["data"] == []


# ─── The expertise-match reviewer selector ──────────────────────────────


def test_auto_assignment_picks_the_reviewer_with_the_higher_keyword_overlap():
    """PRD: "The expertise fit between a candidate and an abstract is the Dice coefficient over their keyword sets. Both sets are lowercased and de-duplicated first: the candidate's `expertise_keywords` on one side, the abstract's `keywords` on the other. The score is twice the number of keywords the two sets share, divided by the sum of the two set sizes, rounded half up to four decimal places."
    PRD: "Surviving candidates are ranked by match score from highest to lowest; ties are broken by spare capacity, meaning `max_review_load` minus `current_review_load`, from largest to smallest; any remaining tie is broken by `created_at` from earliest to latest. The identifier is never used as a tiebreaker. The single highest-ranked candidate is assigned."
    PRD: "An explicitly named reviewer may have a `member_role` of either `REVIEWER` or `CHAIR` — chairs are permitted to carry review load, which is exactly what later makes the decision-time segregation check reachable — whereas the automatic selector considers only members whose `member_role` is `REVIEWER`."
    PRD: "A successful assignment creates a review row with `status` `ASSIGNED`, an `assigned_round` frozen to the abstract's current `revision_round`, `is_third_review` false, a computed `expertise_match_score`, and null values for every rubric field, `confidence`, `recommended_format`, `comments_to_authors`, `weighted_score`, `submitted_at` and `decline_reason`."
    PRD: "An optional `due_utc` overrides the review's deadline; when it is omitted, the review inherits the conference's `review_deadline_utc`."
    PRD: "A review's `expertise_match_score` is carried at **four decimal places**, rounded half up."

    Design: Corner/calculations/auto_assignment_selects_the_highest_dice_match_reviewer
    """
    world = _selector_world()
    abstract = world["abstracts"][0]
    chair_headers = make_program_chair_headers(world["members"]["cho"]["id"])

    response = api_client.create_review_assignment(
        abstract["id"],
        review_assignment_payload(due_utc="2026-04-15T23:59:00Z"),
        chair_headers,
    )
    validate_success(response, 201)
    review = response.json()["data"]

    assert review["reviewer_member_id"] == world["members"]["mei"]["id"]
    assert review["expertise_match_score"] == pytest.approx(0.8000, abs=0.0001)
    assert_four_decimal_places(review["expertise_match_score"])
    assert review["status"] == "ASSIGNED"
    assert review["assigned_round"] == 0
    assert review["is_third_review"] is False
    assert review["due_utc"].startswith("2026-04-15T23:59:00")


def test_auto_assignment_charges_review_load_only_to_the_selected_reviewer():
    """PRD: "Surviving candidates are ranked by match score from highest to lowest; ties are broken by spare capacity, meaning `max_review_load` minus `current_review_load`, from largest to smallest; any remaining tie is broken by `created_at` from earliest to latest. The identifier is never used as a tiebreaker. The single highest-ranked candidate is assigned."
    PRD: "The reviewer's `current_review_load` rises by one. When this is the first non-terminal review of the current round, the abstract moves from `SUBMITTED` to `UNDER_REVIEW`."
    PRD: "A committee member's `current_review_load` always equals the number of that member's review rows whose `status` is `ASSIGNED`, and it must never be negative nor exceed that member's `max_review_load`."

    Design: Corner/calculations/auto_assignment_selects_the_highest_dice_match_reviewer
    """
    world = _selector_world()
    abstract = world["abstracts"][0]
    chair_headers = make_program_chair_headers(world["members"]["cho"]["id"])

    validate_success(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(due_utc="2026-04-15T23:59:00Z"),
            chair_headers,
        ),
        201,
    )

    chosen = api_client.get_committee_member(
        world["members"]["mei"]["id"], chair_headers
    )
    validate_success(chosen)
    assert chosen.json()["data"]["current_review_load"] == 1

    passed_over = api_client.get_committee_member(
        world["members"]["rui"]["id"], chair_headers
    )
    validate_success(passed_over)
    assert passed_over.json()["data"]["current_review_load"] == 0

    read = api_client.get_abstract(abstract["id"], chair_headers)
    validate_success(read)
    assert read.json()["data"]["status"] == "UNDER_REVIEW"


# ─── When each consensus variant is published ───────────────────────────


def test_final_score_stays_null_while_the_review_phase_is_open():
    """PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places. It is written to `provisional_score` on every review submission and is the only consensus figure available while review is still open."
    PRD: "It is written to `final_score` when review closes and when a discrepancy resolves, and it is the only score that may drive a decision or a waitlist promotion."
    PRD: "The new abstract starts with `status` `SUBMITTED`, `embargo_status` `NONE`, `revision_round` zero, `submitted_review_count` zero, and `provisional_score`, `final_score`, `score_spread`, `decision`, `decided_by_member_id`, `embargo_until_utc` and `press_outlet_name` all null, with `decision_downgraded` false."
    PRD: "When `submitted_review_count` reaches the category's `min_reviews_required`, the abstract advances from `UNDER_REVIEW` to `SCORED`."

    Design: Corner/calculations/final_score_is_written_only_when_the_review_phase_closes
    """
    world = setup_scored_abstract(category_overrides=CATEGORY_POLICY)
    abstract = world["abstracts"][0]

    read = api_client.get_abstract(abstract["id"], world["chair_headers"])
    validate_success(read)
    scored = read.json()["data"]
    assert scored["provisional_score"] == pytest.approx(3.50, abs=0.01)
    assert scored["final_score"] is None
    assert scored["status"] == "SCORED"

    conference = api_client.get_conference(world["conference"]["id"], ADMIN)
    validate_success(conference)
    assert conference.json()["data"]["status"] == "REVIEW_OPEN"


def test_final_score_is_the_confidence_weighted_mean_written_when_review_closes():
    """PRD: "The **final** variant is a confidence-weighted mean. Each review is given a weight from its `confidence` — 1 for `LOW`, 2 for `MEDIUM`, 3 for `HIGH` — and the score is the sum of each review's weight multiplied by its `weighted_score`, divided by the sum of those weights, rounded half up to two decimal places. A high-confidence review therefore counts three times as much as a low-confidence one. It is written to `final_score` when review closes and when a discrepancy resolves, and it is the only score that may drive a decision or a waitlist promotion."
    PRD: "When it succeeds, it fans out across the conference: every abstract that is `UNDER_REVIEW` with a `submitted_review_count` of at least its category's `min_reviews_required` advances to `SCORED`; every abstract that is `UNDER_REVIEW` or `SCORED` with at least one submitted review gets its `final_score` written from the final consensus variant; every review of the conference still in `ASSIGNED` status becomes `VOIDED`, with each affected reviewer's `current_review_load` lowered by one so the load ledger stays exact; and the conference's `version` advances."
    PRD: "A review's `weighted_score`, an abstract's `provisional_score`, `final_score` and `score_spread`, a case's `spread_at_open` and `resolved_score`, a session's `accredited_credit_total` and an accreditation's `awarded_credits` are all carried at **two decimal places**, rounded half up."

    Design: Corner/calculations/final_score_is_written_only_when_the_review_phase_closes
    """
    world = setup_scored_abstract(category_overrides=CATEGORY_POLICY)
    abstract = world["abstracts"][0]

    closed = api_client.transition_conference(
        world["conference"]["id"], status_transition_payload("REVIEW_CLOSED"), ADMIN
    )
    validate_success(closed)
    assert closed.json()["data"]["status"] == "REVIEW_CLOSED"

    read = api_client.get_abstract(abstract["id"], world["chair_headers"])
    validate_success(read)
    scored = read.json()["data"]
    assert scored["final_score"] == pytest.approx(3.60, abs=0.01)
    assert_two_decimal_places(scored["final_score"])
    assert scored["provisional_score"] == pytest.approx(3.50, abs=0.01)
    assert scored["status"] == "SCORED"
