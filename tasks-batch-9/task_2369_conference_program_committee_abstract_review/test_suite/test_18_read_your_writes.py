"""Every write is already visible in its own response body and in the very next
read of the same resource, with no second attempt allowed: the review submission
that tips an abstract into the scored state, the acceptance decision that spends
an oral slot out of the conference capacity read, the slot placement that moves
the abstract into the running order and advances the session's packing ledger,
and the withdrawal that hands the slot and the format capacity straight back.
"""

import pytest

from test_helpers import (
    HIGH_REVIEW,
    api_client,
    assert_version_incremented,
    close_review_phase,
    create_session,
    create_session_slot_payload,
    decision_payload,
    get_conference_version,
    make_reviewer_headers,
    setup_abstract_under_review,
    setup_confirmed_abstract,
    setup_scheduled_slot,
    setup_scored_abstract,
    status_transition_payload,
    submit_review_as,
    submit_review_payload,
    validate_success,
)

CAPACITY_2_2_1 = {
    "oral_slot_capacity": 2,
    "poster_slot_capacity": 2,
    "workshop_slot_capacity": 1,
    "cme_minutes_pool_total": 600,
}
ORAL_ONLY_CATEGORY = {
    "allowed_formats": ["ORAL"],
    "min_reviews_required": 2,
    "discrepancy_threshold": 4.00,
}
ORAL_SESSION = {
    "room_code": "R1",
    "end_utc": "2026-09-01T11:00:00Z",
    "capacity_slots": 2,
}


def test_review_submission_response_and_the_next_abstract_read_agree_on_scored():
    """PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD: "The submission then stamps `submitted_at` from the logical clock, lowers the reviewer's `current_review_load` by one, raises the abstract's `submitted_review_count`, and refreshes the abstract's `provisional_score` and `score_spread`."
    PRD: "When `submitted_review_count` reaches the category's `min_reviews_required`, the abstract advances from `UNDER_REVIEW` to `SCORED`."
    PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_next_read
    """
    world = setup_abstract_under_review(
        conference_overrides=dict(CAPACITY_2_2_1),
        category_overrides=dict(ORAL_ONLY_CATEGORY),
    )
    abstract = world["abstracts"][0]
    first, second = world["reviews"][abstract["id"]]
    submit_review_as(world, first, "rui", **HIGH_REVIEW)

    filed = validate_success(
        api_client.submit_review(
            second["id"],
            submit_review_payload(**HIGH_REVIEW),
            make_reviewer_headers(world["members"]["mei"]["id"]),
        )
    )
    assert filed["status"] == "SUBMITTED"
    assert float(filed["weighted_score"]) == pytest.approx(4.00, abs=0.005)

    # The very first read after that submission already shows the advance.
    live = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live["status"] == "SCORED"
    assert live["submitted_review_count"] == 2
    assert float(live["provisional_score"]) == pytest.approx(4.00, abs=0.005)


def test_decision_response_and_the_next_capacity_read_agree_on_the_spent_slot():
    """PRD: "A committed decision moves the abstract from `SCORED` to `ACCEPTED`, writes the waterfall-resolved format into `decision`, sets `decision_downgraded` to true exactly when that resolved format differs from the format the chair asked for, records `decided_by_member_id`, raises the matching accepted count on the conference and advances the conference's `version`."
    PRD: "For each format, remaining capacity is that format's declared slot capacity minus the conference's accepted count for that format."
    PRD: "A conference's `accepted_oral_count`, `accepted_poster_count` and `accepted_workshop_count` each equal the number of that conference's abstracts whose `decision` is the matching format and whose `status` is one of `ACCEPTED`, `CONFIRMED`, `SCHEDULED`, `PRESENTED` or `NO_SHOW`."
    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_next_read
    """
    world = setup_scored_abstract(
        conference_overrides=dict(CAPACITY_2_2_1),
        category_overrides=dict(ORAL_ONLY_CATEGORY),
        first_review=dict(HIGH_REVIEW),
        second_review=dict(HIGH_REVIEW),
    )
    close_review_phase(world)
    conference_id = world["conference"]["id"]
    abstract_id = world["abstracts"][0]["id"]

    observed_version = get_conference_version(conference_id, world["chair_headers"])
    decided = validate_success(
        api_client.decide_abstract(
            abstract_id,
            decision_payload("ORAL", observed_version),
            world["chair_headers"],
        )
    )
    assert decided["decision"] == "ORAL"
    assert decided["status"] == "ACCEPTED"
    assert decided["decision_downgraded"] is False

    # First capacity read after the commit: two declared oral slots, one spent.
    summary = validate_success(
        api_client.get_capacity_summary(conference_id, world["chair_headers"])
    )
    assert summary["oral_remaining"] == 1
    assert summary["poster_remaining"] == 2
    assert summary["workshop_remaining"] == 1
    assert summary["waitlisted_count"] == 0

    live_conference = validate_success(
        api_client.get_conference(conference_id, world["chair_headers"])
    )
    assert live_conference["accepted_oral_count"] == 1
    assert_version_incremented(live_conference["version"], observed_version)


def test_slot_creation_response_and_the_next_session_read_agree_on_the_packing():
    """PRD: "A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`, raises the session's `slot_count` by one, recomputes `committed_minutes`, `accredited_credit_total` and `accreditation_posture`, and advances the session's `version`."
    PRD: "The slot itself starts in `SCHEDULED` status with `swapped_with_slot_id` null."
    PRD: "A session's `committed_minutes` is the sum of `duration_minutes` over its counted slots plus a five-minute changeover allowance for each gap between consecutive counted slots — that is, five minutes multiplied by one less than the number of counted slots, and zero when there are no slots at all."
    PRD: "All resources except conflict declarations additionally carry: - `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations that only touch derived counters. - `version` — an integer that starts at 1 on creation and increases by exactly one on every mutation of that row."
    PRD: "Recomputation of a derived field is a mutation for this purpose: when a slot is added to a session, that session's `version` advances even though no client-supplied field of the session changed."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_next_read
    """
    world = setup_confirmed_abstract(
        decision="ORAL",
        conference_overrides=dict(CAPACITY_2_2_1),
        category_overrides=dict(ORAL_ONLY_CATEGORY),
        first_review=dict(HIGH_REVIEW),
        second_review=dict(HIGH_REVIEW),
    )
    abstract_id = world["abstracts"][0]["id"]
    presenter_id = world["authors"]["ada"]["id"]
    session = create_session(world, **ORAL_SESSION)
    assert session["slot_count"] == 0
    assert session["committed_minutes"] == 0

    slot = validate_success(
        api_client.create_session_slot(
            session["id"],
            create_session_slot_payload(
                abstract_id, presenter_id, 1, 30, session["version"]
            ),
            world["chair_headers"],
        ),
        201,
    )
    assert slot["status"] == "SCHEDULED"
    assert slot["swapped_with_slot_id"] is None
    assert slot["duration_minutes"] == 30

    # First read of the abstract after the placement already carries the cascade.
    live_abstract = validate_success(
        api_client.get_abstract(abstract_id, world["chair_headers"])
    )
    assert live_abstract["status"] == "SCHEDULED"

    # First read of the session already carries the recomputed packing ledger:
    # one 30-minute slot means no changeover gap yet, so 30 committed minutes.
    live_session = validate_success(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert live_session["slot_count"] == 1
    assert live_session["committed_minutes"] == 30
    assert_version_incremented(live_session["version"], session["version"])


def test_withdrawal_response_and_the_next_reads_agree_on_the_released_slot():
    """PRD: "Withdrawal is available to the submitting author or to a chair of the conference from any of `SUBMITTED`, `UNDER_REVIEW`, `SCORED`, `WAITLISTED`, `ACCEPTED`, `CONFIRMED` and `SCHEDULED`."
    PRD: "**Cascade B** starts when an abstract is withdrawn. Each of its slots whose `status` is `SCHEDULED` becomes `WITHDRAWN`; each affected session's `slot_count` drops by one, its `committed_minutes`, `accredited_credit_total` and `accreditation_posture` are recomputed and its `version` advances; and any affected session whose `slot_count` has reached zero while `PUBLISHED` drops back to `PLANNED`, because an empty session cannot remain published."
    PRD: "In parallel, if the withdrawn abstract carried a non-null `decision`, the conference's matching accepted count drops by one and its `version` advances, and the freed capacity immediately runs waitlist promotion for that format, which re-increments the same counter if a promotable abstract exists."
    PRD: "When the eligible pool is empty the slot simply stays free and no error is raised."
    PRD: "Each link of a cascade is a real mutation of the row it touches: `updated_at` is refreshed and `version` advances on every entity the cascade writes, and the whole cascade is committed together with the request that triggered it."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_next_read
    """
    world = setup_scheduled_slot(
        conference_overrides=dict(CAPACITY_2_2_1),
        category_overrides=dict(ORAL_ONLY_CATEGORY),
        session_overrides=dict(ORAL_SESSION),
        duration_minutes=30,
        first_review=dict(HIGH_REVIEW),
        second_review=dict(HIGH_REVIEW),
    )
    conference_id = world["conference"]["id"]
    abstract_id = world["abstracts"][0]["id"]
    session = world["sessions"][0]
    slot = world["slots"][0]

    withdrawn = validate_success(
        api_client.transition_abstract(
            abstract_id,
            status_transition_payload(
                "WITHDRAWN", reason="author withdraws before the freeze"
            ),
            world["author_headers"],
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    # First capacity read after the withdrawal: both oral slots free again, and
    # with no waitlisted abstract to promote the released slot simply stays free.
    summary = validate_success(
        api_client.get_capacity_summary(conference_id, world["chair_headers"])
    )
    assert summary["oral_remaining"] == 2
    assert summary["waitlisted_count"] == 0

    live_session = validate_success(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert live_session["slot_count"] == 0
    assert live_session["committed_minutes"] == 0
    assert_version_incremented(live_session["version"], session["version"])

    live_slot = validate_success(
        api_client.get_session_slot(slot["id"], world["chair_headers"])
    )
    assert live_slot["status"] == "WITHDRAWN"
