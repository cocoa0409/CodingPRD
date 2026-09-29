"""Conserved ledgers of the program committee, walked out and back again.

Three counters in this domain are supposed to survive a full round trip. A
reviewer's live workload returns to the value it started at once an assignment
has been declined, reassigned elsewhere and finally scored. The conference's
format capacity ledger survives a rescinded acceptance, because the slot the
rescission releases is handed straight to the top of the waitlist rather than
lost or counted twice. And the accredited-minute pool balances back to the
minutes the accrediting body granted once a validated accreditation is revoked,
with the awarded credits going back to nothing.

Each test builds its own conference, committee, submissions and paperwork from
scratch, then reads the counters at the interesting moment: mid-cycle, when the
quantity is out on loan, and after the compensating operation, when the ledger
must reconstruct its starting balance.
"""

import pytest

from test_helpers import (
    ADMIN,
    HIGH_REVIEW,
    MEDIUM_REVIEW,
    accreditation_validation_payload,
    api_client,
    assert_cme_pool_conserved,
    assert_format_capacity_within_bounds,
    assert_reviewer_load_within_ceiling,
    assign_review,
    close_review_phase,
    decide_abstract,
    decline_review_payload,
    make_program_chair_headers,
    make_reviewer_headers,
    open_call_for_abstracts,
    open_review_phase,
    review_assignment_payload,
    setup_conference_with_committee,
    setup_validated_accreditation,
    status_transition_payload,
    submit_abstract,
    submit_review_as,
    submit_review_payload,
    validate_paginated,
    validate_success,
)

# ─── Local setup: the three worlds these ledgers live in ─────────────────


def _world_with_an_unassigned_abstract() -> dict:
    """Conference at REVIEW_OPEN holding one abstract with no reviews yet.

    Rui's expertise is [oncology, imaging] against abstract keywords
    [oncology, immunotherapy], a Dice fit of 0.5000; Mei's expertise is
    [oncology, immunotherapy], a Dice fit of 1.0000. Both reviewers are ACTIVE
    with a conflict declaration on file and a load of zero.
    """
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    submit_abstract(world, title="Immunotherapy response imaging")
    open_review_phase(world)
    return world


def _world_with_one_accepted_and_one_waitlisted_oral() -> dict:
    """One oral slot, two scored abstracts, both decided ORAL by the chair.

    Ada's abstract scores 4.00 and 3.00 (provisional 3.50) and Ben's scores
    3.00 and 2.00 (provisional 2.50), so Ada outranks Ben. Ada takes the single
    oral slot; Ben, decided ORAL with downgrade allowed against zero poster
    capacity, lands on the waitlist.
    """
    world = setup_conference_with_committee(
        conference_overrides={
            "oral_slot_capacity": 1,
            "poster_slot_capacity": 0,
            "workshop_slot_capacity": 0,
        }
    )
    open_call_for_abstracts(world)
    submit_abstract(world, author_key="ada", title="Immunotherapy response imaging")
    submit_abstract(
        world,
        author_key="ben",
        title="Adjuvant sequencing in early disease",
        body_word_count=260,
    )
    open_review_phase(world)
    ada_abstract, ben_abstract = world["abstracts"]
    rui_id = world["members"]["rui"]["id"]
    mei_id = world["members"]["mei"]["id"]
    ada_first = assign_review(world, ada_abstract["id"], rui_id)
    ada_second = assign_review(world, ada_abstract["id"], mei_id)
    ben_first = assign_review(world, ben_abstract["id"], rui_id)
    ben_second = assign_review(world, ben_abstract["id"], mei_id)
    submit_review_as(world, ada_first, "rui", **HIGH_REVIEW)
    submit_review_as(world, ada_second, "mei", **MEDIUM_REVIEW)
    submit_review_as(
        world,
        ben_first,
        "rui",
        score_originality=3,
        score_methodology=3,
        score_relevance=3,
        score_clarity=3,
        confidence="HIGH",
        recommended_format="ORAL",
    )
    submit_review_as(
        world,
        ben_second,
        "mei",
        score_originality=2,
        score_methodology=2,
        score_relevance=2,
        score_clarity=2,
        confidence="MEDIUM",
        recommended_format="ORAL",
    )
    close_review_phase(world)
    world["abstracts"][0] = decide_abstract(
        world, ada_abstract["id"], "ORAL", allow_format_downgrade=False
    )
    world["abstracts"][1] = decide_abstract(
        world, ben_abstract["id"], "ORAL", allow_format_downgrade=True
    )
    return world


def _rescind_the_acceptance(world: dict, abstract_id: str):
    return api_client.transition_abstract(
        abstract_id,
        status_transition_payload(
            "SCORED", reason="presenter conflict discovered, decision rescinded"
        ),
        world["chair_headers"],
    )


def _world_with_a_pending_forty_five_minute_accreditation() -> dict:
    """A decided ORAL abstract carrying a PENDING accreditation of 45 content
    minutes with its single disclosure already VALIDATED. Chair Cho issued the
    decision, so chair Dana is the validator."""
    return setup_validated_accreditation(content_minutes=45, validate=False)


def _validate(world: dict):
    return api_client.validate_accreditation(
        world["accreditation"]["id"],
        accreditation_validation_payload("VALIDATE"),
        world["second_chair_headers"],
    )


def _revoke(world: dict):
    return api_client.validate_accreditation(
        world["accreditation"]["id"],
        accreditation_validation_payload("REVOKE"),
        world["second_chair_headers"],
    )


# ─── The reviewer load ledger ────────────────────────────────────────────


def test_reviewer_load_rises_by_one_when_the_chair_assigns_the_first_review():
    """A committee member's `current_review_load` always equals the number of that
    member's review rows whose `status` is `ASSIGNED`, and it must never be negative
    nor exceed that member's `max_review_load`. Every assignment raises it by
    exactly one; every submission, every decline and every system-driven void
    lowers it by exactly one.

    A successful assignment creates a review row with `status` `ASSIGNED`, an
    `assigned_round` frozen to the abstract's current `revision_round`,
    `is_third_review` false, a computed `expertise_match_score`, and null values for
    every rubric field, `confidence`, `recommended_format`, `comments_to_authors`,
    `weighted_score`, `submitted_at` and `decline_reason`. The reviewer's
    `current_review_load` rises by one. When this is the first non-terminal review
    of the current round, the abstract moves from `SUBMITTED` to `UNDER_REVIEW`.

    The score is twice the number of keywords the two sets share, divided by the sum
    of the two set sizes, rounded half up to four decimal places.

    Design: Difficulty/compensating_invariant/reviewer_load_returns_to_zero_after_assign_decline_reassign_submit
    """
    world = _world_with_an_unassigned_abstract()
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    mei = world["members"]["mei"]

    review = validate_success(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=rui["id"]),
            world["chair_headers"],
        ),
        201,
    )

    assert review["status"] == "ASSIGNED"
    assert float(review["expertise_match_score"]) == pytest.approx(0.5000, abs=0.01)

    loaded_rui = validate_success(
        api_client.get_committee_member(rui["id"], world["chair_headers"])
    )
    idle_mei = validate_success(
        api_client.get_committee_member(mei["id"], world["chair_headers"])
    )
    assert loaded_rui["current_review_load"] == 1
    assert idle_mei["current_review_load"] == 0
    assert_reviewer_load_within_ceiling(loaded_rui)
    assert_reviewer_load_within_ceiling(idle_mei)

    assigned_rows, _meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"],
            params={"abstract_id": abstract["id"], "status": "ASSIGNED"},
        )
    )
    assert len(assigned_rows) == 1

    live_abstract = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["status"] == "UNDER_REVIEW"


def test_reviewer_load_moves_to_the_replacement_reviewer_when_the_first_declines():
    """The review moves from `ASSIGNED` to `DECLINED` and the reviewer's
    `current_review_load` falls by one. An optional `auto_reassign` flag defaults to
    true, in which case a replacement review is created by the selector with the
    declining member in the exclusion set; when `auto_reassign` is false, or when
    the candidate pool is empty, no replacement appears and the decline still
    returns success.

    A committee member's `current_review_load` always equals the number of that
    member's review rows whose `status` is `ASSIGNED`, and it must never be negative
    nor exceed that member's `max_review_load`.

    Design: Difficulty/compensating_invariant/reviewer_load_returns_to_zero_after_assign_decline_reassign_submit
    """
    world = _world_with_an_unassigned_abstract()
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    mei = world["members"]["mei"]

    review = validate_success(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=rui["id"]),
            world["chair_headers"],
        ),
        201,
    )
    declined = validate_success(
        api_client.decline_review(
            review["id"],
            decline_review_payload("outside my subspecialty", auto_reassign=True),
            make_reviewer_headers(rui["id"]),
        )
    )

    assert declined["status"] == "DECLINED"

    after_rui = validate_success(
        api_client.get_committee_member(rui["id"], world["chair_headers"])
    )
    after_mei = validate_success(
        api_client.get_committee_member(mei["id"], world["chair_headers"])
    )
    assert after_rui["current_review_load"] == 0
    assert after_mei["current_review_load"] == 1
    assert_reviewer_load_within_ceiling(after_rui)
    assert_reviewer_load_within_ceiling(after_mei)

    replacement_rows, _meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"],
            params={"abstract_id": abstract["id"], "reviewer_member_id": mei["id"]},
        )
    )
    assert len(replacement_rows) == 1
    replacement = replacement_rows[0]
    assert replacement["status"] == "ASSIGNED"
    assert float(replacement["expertise_match_score"]) == pytest.approx(
        1.0000, abs=0.01
    )


def test_reviewer_load_returns_to_its_starting_value_after_a_full_round_trip():
    """Every assignment raises it by exactly one; every submission, every decline and
    every system-driven void lowers it by exactly one. A full round trip — assign,
    decline, reassign elsewhere, submit — must leave the counter of each involved
    member exactly where it started.

    The submission then stamps `submitted_at` from the logical clock, lowers the
    reviewer's `current_review_load` by one, raises the abstract's
    `submitted_review_count`, and refreshes the abstract's `provisional_score` and
    `score_spread`.

    With fewer than two submitted reviews the spread is null and no dispute can
    open.

    Design: Difficulty/compensating_invariant/reviewer_load_returns_to_zero_after_assign_decline_reassign_submit
    """
    world = _world_with_an_unassigned_abstract()
    abstract = world["abstracts"][0]
    rui = world["members"]["rui"]
    mei = world["members"]["mei"]

    review = validate_success(
        api_client.create_review_assignment(
            abstract["id"],
            review_assignment_payload(reviewer_member_id=rui["id"]),
            world["chair_headers"],
        ),
        201,
    )
    validate_success(
        api_client.decline_review(
            review["id"],
            decline_review_payload("outside my subspecialty", auto_reassign=True),
            make_reviewer_headers(rui["id"]),
        )
    )
    replacement_rows, _meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"],
            params={"abstract_id": abstract["id"], "reviewer_member_id": mei["id"]},
        )
    )
    replacement = replacement_rows[0]

    submitted = validate_success(
        api_client.submit_review(
            replacement["id"], submit_review_payload(), make_reviewer_headers(mei["id"])
        )
    )

    assert submitted["status"] == "SUBMITTED"
    assert float(submitted["weighted_score"]) == pytest.approx(4.00, abs=0.01)

    final_rui = validate_success(
        api_client.get_committee_member(rui["id"], world["chair_headers"])
    )
    final_mei = validate_success(
        api_client.get_committee_member(mei["id"], world["chair_headers"])
    )
    assert final_rui["current_review_load"] == 0
    assert final_mei["current_review_load"] == 0
    assert final_rui["current_review_load"] + final_mei["current_review_load"] == 0
    assert_reviewer_load_within_ceiling(final_rui)
    assert_reviewer_load_within_ceiling(final_mei)

    still_assigned, _meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"],
            params={"abstract_id": abstract["id"], "status": "ASSIGNED"},
        )
    )
    assert still_assigned == []

    declined_row = validate_success(
        api_client.get_review(review["id"], world["chair_headers"])
    )
    assert declined_row["status"] == "DECLINED"

    live_abstract = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live_abstract["status"] == "UNDER_REVIEW"
    assert live_abstract["submitted_review_count"] == 1
    assert float(live_abstract["provisional_score"]) == pytest.approx(4.00, abs=0.01)
    assert live_abstract["score_spread"] is None


# ─── The format slot ledger ──────────────────────────────────────────────


def test_accepted_and_waitlisted_counts_hold_the_single_oral_slot_before_rescission():
    """A conference's `accepted_oral_count`, `accepted_poster_count` and
    `accepted_workshop_count` each equal the number of that conference's abstracts
    whose `decision` is the matching format and whose `status` is one of `ACCEPTED`,
    `CONFIRMED`, `SCHEDULED`, `PRESENTED` or `NO_SHOW`. Its `waitlisted_count`
    equals the number of its abstracts whose `status` is `WAITLISTED`.

    A committed decision moves the abstract from `SCORED` to `ACCEPTED`, writes the
    waterfall-resolved format into `decision`, sets `decision_downgraded` to true
    exactly when that resolved format differs from the format the chair asked for,
    records `decided_by_member_id`, raises the matching accepted count on the
    conference and advances the conference's `version`. A waitlisted outcome moves
    the abstract from `SCORED` to `WAITLISTED`, leaves `decision` null, still records
    `decided_by_member_id`, raises the conference's `waitlisted_count` by one and
    advances the conference's `version`.

    Design: Difficulty/compensating_invariant/format_capacity_ledger_is_conserved_across_rescission_and_promotion
    """
    world = _world_with_one_accepted_and_one_waitlisted_oral()
    ada_abstract, ben_abstract = world["abstracts"]

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert conference["accepted_oral_count"] == 1
    assert conference["waitlisted_count"] == 1
    assert conference["accepted_oral_count"] + conference["waitlisted_count"] == 2
    assert_format_capacity_within_bounds(conference)

    ada_live = validate_success(
        api_client.get_abstract(ada_abstract["id"], world["chair_headers"])
    )
    ben_live = validate_success(
        api_client.get_abstract(ben_abstract["id"], world["chair_headers"])
    )
    assert ada_live["status"] == "ACCEPTED"
    assert ada_live["decision"] == "ORAL"
    assert float(ada_live["provisional_score"]) == pytest.approx(3.50, abs=0.01)
    assert ben_live["status"] == "WAITLISTED"
    assert ben_live["decision"] is None
    assert float(ben_live["provisional_score"]) == pytest.approx(2.50, abs=0.01)


def test_format_capacity_ledger_is_conserved_when_rescission_promotes_the_waitlist():
    """Every commit raises one counter; every rescission, withdrawal and promotion
    adjusts them so the identity holds exactly.

    The rescission lowers the conference's accepted count for the abstract's former
    `decision` by one, clears `decision` and `decided_by_member_id` to null and
    `decision_downgraded` to false, runs waitlist promotion for the released format,
    and advances the conference's `version`. This is the compensating action for a
    commit, and the slot-conservation identity of §2.9 must hold exactly once it
    completes.

    The top-ranked abstract moves from `WAITLISTED` to `ACCEPTED` with `decision`
    set to the released format, `decision_downgraded` set to true when that format
    differs from its `requested_format`, and `decided_by_member_id` copied from the
    abstract whose slot was released; the conference's matching accepted count rises
    by one, its `waitlisted_count` falls by one, and its `version` advances.

    Design: Difficulty/compensating_invariant/format_capacity_ledger_is_conserved_across_rescission_and_promotion
    """
    world = _world_with_one_accepted_and_one_waitlisted_oral()
    ada_abstract, ben_abstract = world["abstracts"]

    rescinded = validate_success(_rescind_the_acceptance(world, ada_abstract["id"]))

    assert rescinded["status"] == "SCORED"
    assert rescinded["decision"] is None
    assert rescinded["decided_by_member_id"] is None
    assert rescinded["decision_downgraded"] is False

    promoted = validate_success(
        api_client.get_abstract(ben_abstract["id"], world["chair_headers"])
    )
    assert promoted["status"] == "ACCEPTED"
    assert promoted["decision"] == "ORAL"
    assert promoted["decision_downgraded"] is False

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert conference["accepted_oral_count"] == 1
    assert conference["waitlisted_count"] == 0
    assert conference["accepted_oral_count"] + conference["waitlisted_count"] == 1
    assert conference["oral_slot_capacity"] == 1
    assert_format_capacity_within_bounds(conference)


def test_accepted_oral_count_still_matches_its_abstract_rows_after_the_promotion():
    """Three quantities in this system are conserved, meaning that after any sequence
    of operations the stored counter must equal the count implied by the underlying
    rows.

    A conference's `accepted_oral_count`, `accepted_poster_count` and
    `accepted_workshop_count` each equal the number of that conference's abstracts
    whose `decision` is the matching format and whose `status` is one of `ACCEPTED`,
    `CONFIRMED`, `SCHEDULED`, `PRESENTED` or `NO_SHOW`. Its `waitlisted_count`
    equals the number of its abstracts whose `status` is `WAITLISTED`.

    Design: Difficulty/compensating_invariant/format_capacity_ledger_is_conserved_across_rescission_and_promotion
    """
    world = _world_with_one_accepted_and_one_waitlisted_oral()
    conference_id = world["conference"]["id"]
    ada_abstract = world["abstracts"][0]

    validate_success(_rescind_the_acceptance(world, ada_abstract["id"]))

    accepted_orals, _accepted_meta = validate_paginated(
        api_client.list_abstracts(
            ADMIN,
            params={
                "conference_id": conference_id,
                "decision": "ORAL",
                "status": "ACCEPTED",
            },
        )
    )
    waitlisted, _waitlisted_meta = validate_paginated(
        api_client.list_abstracts(
            ADMIN, params={"conference_id": conference_id, "status": "WAITLISTED"}
        )
    )

    conference = validate_success(api_client.get_conference(conference_id, ADMIN))
    assert conference["accepted_oral_count"] == len(accepted_orals) == 1
    assert conference["waitlisted_count"] == len(waitlisted) == 0
    assert conference["accepted_poster_count"] == 0
    assert conference["accepted_workshop_count"] == 0
    assert_format_capacity_within_bounds(conference)


# ─── The continuing-education minute pool ────────────────────────────────


def test_accredited_minute_pool_is_debited_when_content_is_validated():
    """A conference's `cme_minutes_allocated` equals the sum of `content_minutes`
    over its accreditations whose `validation_status` is `VALIDATED`, and
    `cme_minutes_available` is always `cme_minutes_pool_total` minus
    `cme_minutes_allocated`.

    On success the row's `awarded_credits` is computed, `validated_by_member_id` and
    `validated_at` are set, the conference's `cme_minutes_allocated` rises by
    `content_minutes` with `cme_minutes_available` recomputed and the conference's
    `version` advanced, and the session holding a counted slot for that abstract
    recomputes its `accredited_credit_total` and `accreditation_posture` with its own
    `version` advanced.

    The **per-abstract award** is what an accreditation actually earns and what feeds
    a session's ledger: for each validated accreditation, divide its
    `content_minutes` by fifteen, discard the remainder by rounding down to a whole
    number, and multiply by 0.25; the total over a set is the sum of those
    individually floored awards.

    Design: Difficulty/compensating_invariant/cme_minute_pool_is_conserved_across_validation_and_revocation
    """
    world = _world_with_a_pending_forty_five_minute_accreditation()

    before = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert before["cme_minutes_allocated"] == 0
    assert before["cme_minutes_available"] == 600
    assert_cme_pool_conserved(before)

    validated = validate_success(_validate(world))

    assert validated["validation_status"] == "VALIDATED"
    assert validated["content_minutes"] == 45
    assert float(validated["awarded_credits"]) == pytest.approx(0.75, abs=0.01)
    assert validated["validated_by_member_id"] == world["members"]["dana"]["id"]

    mid_cycle = validate_success(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    assert mid_cycle["cme_minutes_allocated"] == 45
    assert mid_cycle["cme_minutes_available"] == 555
    assert mid_cycle["cme_minutes_pool_total"] == 600
    assert_cme_pool_conserved(mid_cycle)


def test_accredited_minute_pool_returns_to_its_full_balance_after_revocation():
    """A revocation returns exactly the same minute count that the matching
    validation debited.

    Revoking one moves it from `VALIDATED` to `REVOKED`, has no preconditions,
    returns `awarded_credits` to 0.00, lowers the conference's
    `cme_minutes_allocated` by exactly the same `content_minutes` the validation
    debited with `cme_minutes_available` recomputed and the conference's `version`
    advanced, recomputes the owning session's `accredited_credit_total` and
    `accreditation_posture` with that session's `version` advanced, and — when that
    session is `cme_designated`, its recomputed posture is `NON_COMPLIANT` and it is
    currently `PUBLISHED` — drops the session back to `PLANNED`. Revocation is the
    compensating action for validation, and the minute-pool identity of §2.9 must
    hold exactly afterwards.

    Design: Difficulty/compensating_invariant/cme_minute_pool_is_conserved_across_validation_and_revocation
    """
    world = _world_with_a_pending_forty_five_minute_accreditation()

    validate_success(_validate(world))
    revoked = validate_success(_revoke(world))

    assert revoked["validation_status"] == "REVOKED"
    assert float(revoked["awarded_credits"]) == pytest.approx(0.00, abs=0.01)

    after = validate_success(api_client.get_conference(world["conference"]["id"], ADMIN))
    assert after["cme_minutes_allocated"] == 0
    assert after["cme_minutes_available"] == 600
    assert_cme_pool_conserved(after)

    abstract = validate_success(
        api_client.get_abstract(world["abstracts"][0]["id"], ADMIN)
    )
    assert abstract["status"] == "ACCEPTED"


def test_capacity_read_reports_no_accredited_credits_after_the_revocation():
    """Both figures are visible side by side on the conference capacity read, which
    reports the conference's identifier, remaining oral, poster and workshop
    capacity, the `waitlisted_count`, `cme_minutes_available`, the bundle figure as
    `cme_bundle_credits`, the plain sum of per-abstract `awarded_credits` as
    `awarded_credits_sum`, and the count of accredited sessions as
    `accredited_session_count`.

    The **session bundle estimate** is a conference-level planning figure: sum the
    `content_minutes` of the validated set first, then divide that single total by
    fifteen, round down to a whole number once, and multiply by 0.25.

    Design: Difficulty/compensating_invariant/cme_minute_pool_is_conserved_across_validation_and_revocation
    """
    world = _world_with_a_pending_forty_five_minute_accreditation()
    conference_id = world["conference"]["id"]

    validate_success(_validate(world))
    validate_success(_revoke(world))

    summary = validate_success(
        api_client.get_capacity_summary(conference_id, world["second_chair_headers"])
    )
    assert summary["cme_minutes_available"] == 600
    assert float(summary["awarded_credits_sum"]) == pytest.approx(0.00, abs=0.01)
    assert float(summary["cme_bundle_credits"]) == pytest.approx(0.00, abs=0.01)

    conference = validate_success(
        api_client.get_conference(conference_id, make_program_chair_headers(
            world["members"]["dana"]["id"]
        ))
    )
    assert conference["cme_minutes_allocated"] == 0
    assert_cme_pool_conserved(conference)
