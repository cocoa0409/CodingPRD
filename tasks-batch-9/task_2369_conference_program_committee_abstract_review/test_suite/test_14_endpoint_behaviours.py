"""Endpoint behaviours around three touch points of the program committee's day:
the administrative patch that keeps a committee member's selector inputs current
without rescoring the reviews that member has already filed, the conference
capacity read that counts committed decisions rather than inbound submissions,
and the author's resubmission that returns a reworked abstract to the submission
queue while wiping the scoring block the previous round produced.
"""

import pytest

from test_helpers import (
    ADMIN,
    HIGH_REVIEW,
    TEST_DEFAULTS,
    api_client,
    assert_abstract,
    assert_committee_member,
    assert_version_incremented,
    close_review_phase,
    decide_abstract,
    open_call_for_abstracts,
    open_review_phase,
    revise_abstract_payload,
    setup_conference_with_committee,
    setup_scored_abstract,
    setup_scored_abstracts,
    status_transition_payload,
    submit_abstract,
    submit_review_payload,
    submit_review_as,
    update_committee_member_payload,
    validate_paginated,
    validate_success,
    assign_review,
    make_reviewer_headers,
)

CAPACITY_3_2_1 = {
    "oral_slot_capacity": 3,
    "poster_slot_capacity": 2,
    "workshop_slot_capacity": 1,
    "cme_minutes_pool_total": 600,
}
TWO_REVIEWS_NO_DISPUTE = {"min_reviews_required": 2, "discrepancy_threshold": 4.00}


# ─── Maintaining a committee member's selector inputs ────────────────────


def _reviewer_with_one_filed_review() -> dict:
    """Rui holds two assigned reviews on two abstracts and has filed the first."""
    world = setup_conference_with_committee(
        category_overrides=dict(TWO_REVIEWS_NO_DISPUTE),
        reviewer_keywords=["oncology"],
    )
    open_call_for_abstracts(world)
    ada_abstract = submit_abstract(
        world, "ada", title="Ada submission", keywords=["oncology"]
    )
    ben_abstract = submit_abstract(
        world, "ben", title="Ben submission", keywords=["oncology"]
    )
    open_review_phase(world)
    rui = world["members"]["rui"]
    filed = assign_review(world, ada_abstract["id"], rui["id"])
    pending = assign_review(world, ben_abstract["id"], rui["id"])
    submit_review_as(world, filed, "rui", **HIGH_REVIEW)
    world["filed_review"] = filed
    world["pending_review"] = pending
    world["ada_abstract"] = ada_abstract
    return world


def test_committee_member_patch_replaces_only_the_named_selector_inputs():
    """PRD: "Selector inputs stay maintainable: an administrator may later revise a member's `expertise_keywords`, `max_review_load` and `calibration_bias`."
    PRD: "`ConferenceAdmin` owns conference and category setup, committee recruitment, author records and event registration, the logical clock, and the committee-member maintenance patch — and is deliberately excluded from review content, decisions and arbitration."
    PRD: "Operations that modify an existing resource — status transitions, adjudications, submissions, declines, registrations, patches and the clock capability — return `200 OK`."
    PRD: "All resources except conflict declarations additionally carry: - `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations that only touch derived counters. - `version` — an integer that starts at 1 on creation and increases by exactly one on every mutation of that row."

    Design: Corner/endpoints/committee_member_patch_updates_selector_inputs_without_rescoring
    """
    world = _reviewer_with_one_filed_review()
    rui_id = world["members"]["rui"]["id"]

    before = validate_success(api_client.get_committee_member(rui_id, ADMIN))
    assert before["max_review_load"] == 4
    assert float(before["calibration_bias"]) == pytest.approx(0.00, abs=0.005)

    patched = validate_success(
        api_client.update_committee_member(
            rui_id,
            update_committee_member_payload(
                calibration_bias=-0.50,
                expertise_keywords=["oncology", "immunotherapy"],
            ),
            ADMIN,
        )
    )
    assert_committee_member(patched)
    assert float(patched["calibration_bias"]) == pytest.approx(-0.50, abs=0.005)
    assert sorted(patched["expertise_keywords"]) == ["immunotherapy", "oncology"]
    # max_review_load was omitted from the patch body, so it is left alone.
    assert patched["max_review_load"] == 4
    assert_version_incremented(patched["version"], before["version"])

    # The patch is visible on the next read of the same member.
    live = validate_success(api_client.get_committee_member(rui_id, ADMIN))
    assert float(live["calibration_bias"]) == pytest.approx(-0.50, abs=0.005)
    assert sorted(live["expertise_keywords"]) == ["immunotherapy", "oncology"]
    assert live["max_review_load"] == 4
    assert live["version"] == patched["version"]


def test_revised_calibration_bias_never_rescores_an_already_filed_review():
    """PRD: "Revising the bias is explicitly **not** retroactive — review scores already computed are never rescored, and the new bias affects only submissions that happen afterwards."
    PRD: "The review's `weighted_score` is built by taking forty percent of `score_originality`, thirty percent of `score_methodology`, fifteen percent of `score_clarity` and fifteen percent of `score_relevance`, and adding those four contributions together."
    PRD: "The reviewer's `calibration_bias` is then added to that total."
    PRD: "It is written to `provisional_score` on every review submission and is the only consensus figure available while review is still open."

    Design: Corner/endpoints/committee_member_patch_updates_selector_inputs_without_rescoring
    """
    world = _reviewer_with_one_filed_review()
    rui_id = world["members"]["rui"]["id"]
    filed = world["filed_review"]
    pending = world["pending_review"]

    validate_success(
        api_client.update_committee_member(
            rui_id,
            update_committee_member_payload(calibration_bias=-0.50),
            ADMIN,
        )
    )

    # 4/4/4/4 rolled up to 1.60 + 1.20 + 0.60 + 0.60 = 4.00 under the old bias.
    already_filed = validate_success(
        api_client.get_review(filed["id"], world["chair_headers"])
    )
    assert float(already_filed["weighted_score"]) == pytest.approx(4.00, abs=0.005)

    # The same rubric filed after the patch carries 4.00 - 0.50 = 3.50.
    later = validate_success(
        api_client.submit_review(
            pending["id"],
            submit_review_payload(**HIGH_REVIEW),
            make_reviewer_headers(rui_id),
        )
    )
    assert float(later["weighted_score"]) == pytest.approx(3.50, abs=0.005)

    # The consensus of the untouched abstract still reads its single 4.00 review.
    untouched = validate_success(
        api_client.get_abstract(world["ada_abstract"]["id"], world["chair_headers"])
    )
    assert float(untouched["provisional_score"]) == pytest.approx(4.00, abs=0.005)


# ─── What the conference capacity read counts ────────────────────────────


def test_capacity_read_ignores_abstracts_that_are_merely_submitted():
    """PRD: "Both figures are visible side by side on the conference capacity read, which reports the conference's identifier, remaining oral, poster and workshop capacity, the `waitlisted_count`, `cme_minutes_available`, the bundle figure as `cme_bundle_credits`, the plain sum of per-abstract `awarded_credits` as `awarded_credits_sum`, and the count of accredited sessions as `accredited_session_count`."
    PRD: "For each format, remaining capacity is that format's declared slot capacity minus the conference's accepted count for that format."
    PRD: "A conference's `accepted_oral_count`, `accepted_poster_count` and `accepted_workshop_count` each equal the number of that conference's abstracts whose `decision` is the matching format and whose `status` is one of `ACCEPTED`, `CONFIRMED`, `SCHEDULED`, `PRESENTED` or `NO_SHOW`."
    PRD: "Its `waitlisted_count` equals the number of its abstracts whose `status` is `WAITLISTED`."
    PRD: "A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`."

    Design: Corner/endpoints/capacity_summary_reflects_decisions_not_submissions
    """
    world = setup_conference_with_committee(
        conference_overrides=dict(CAPACITY_3_2_1),
        category_overrides=dict(TWO_REVIEWS_NO_DISPUTE),
    )
    open_call_for_abstracts(world)
    submit_abstract(world, "ada", title="Ada one", requested_format="ORAL")
    submit_abstract(world, "ada", title="Ada two", requested_format="POSTER")
    submit_abstract(world, "ben", title="Ben one", requested_format="ORAL")

    for abstract in world["abstracts"]:
        assert abstract["status"] == "SUBMITTED"
        assert abstract["decision"] is None

    summary = validate_success(
        api_client.get_capacity_summary(world["conference"]["id"], ADMIN)
    )
    assert summary["conference_id"] == world["conference"]["id"]
    # No decision has been committed, so every declared slot is still free.
    assert summary["oral_remaining"] == 3
    assert summary["poster_remaining"] == 2
    assert summary["workshop_remaining"] == 1
    assert summary["waitlisted_count"] == 0
    assert summary["cme_minutes_available"] == 600
    assert float(summary["cme_bundle_credits"]) == pytest.approx(0.00, abs=0.005)
    assert float(summary["awarded_credits_sum"]) == pytest.approx(0.00, abs=0.005)


def test_capacity_read_drops_the_format_it_counts_once_a_decision_commits():
    """PRD: "For each format, remaining capacity is that format's declared slot capacity minus the conference's accepted count for that format."
    PRD: "A committed decision moves the abstract from `SCORED` to `ACCEPTED`, writes the waterfall-resolved format into `decision`, sets `decision_downgraded` to true exactly when that resolved format differs from the format the chair asked for, records `decided_by_member_id`, raises the matching accepted count on the conference and advances the conference's `version`."
    PRD: "Its `waitlisted_count` equals the number of its abstracts whose `status` is `WAITLISTED`."

    Design: Corner/endpoints/capacity_summary_reflects_decisions_not_submissions
    """
    world = setup_scored_abstracts(
        1,
        conference_overrides=dict(CAPACITY_3_2_1),
        category_overrides=dict(TWO_REVIEWS_NO_DISPUTE),
    )
    close_review_phase(world)
    decided = decide_abstract(world, world["abstracts"][0]["id"], "ORAL")
    assert decided["status"] == "ACCEPTED"
    assert decided["decision"] == "ORAL"

    summary = validate_success(
        api_client.get_capacity_summary(
            world["conference"]["id"], world["chair_headers"]
        )
    )
    # One committed oral acceptance out of three declared oral slots.
    assert summary["oral_remaining"] == 2
    assert summary["poster_remaining"] == 2
    assert summary["workshop_remaining"] == 1
    assert summary["waitlisted_count"] == 0


# ─── What a resubmitted revision resets ──────────────────────────────────


def _abstract_sent_back_for_revision() -> tuple:
    """One scored abstract that the chair has moved to REVISION_REQUESTED."""
    world = setup_scored_abstract(category_overrides=dict(TWO_REVIEWS_NO_DISPUTE))
    abstract = world["abstracts"][0]
    sent_back = validate_success(
        api_client.transition_abstract(
            abstract["id"],
            status_transition_payload(
                "REVISION_REQUESTED", reason="clarify the endpoint definition"
            ),
            world["chair_headers"],
        )
    )
    assert sent_back["status"] == "REVISION_REQUESTED"
    return world, sent_back


def test_resubmission_returns_the_abstract_to_submitted_and_clears_its_scores():
    """PRD: "The author closes the loop by resubmitting, which returns the abstract from `REVISION_REQUESTED` to `SUBMITTED`."
    PRD: "On success `revision_round` rises by one; `body_word_count`, `body_structured` and `keywords` are replaced, as is `title` when supplied; `provisional_score`, `final_score` and `score_spread` all return to null; and `submitted_review_count` recomputes to zero, because reviews from the previous round keep the old value in their `assigned_round` and thereby leave the consensus input set for good."
    PRD: "On acceptance of the submission the conference's `abstract_sequence` counter is incremented and the abstract's `blind_code` is minted deterministically as the conference `code`, a hyphen, the letter `B`, and the post-increment sequence value zero-padded to four digits — the first abstract of a conference whose `code` is `NEURO26` therefore carries the blind code `NEURO26-B0001`."
    PRD: "All resources except conflict declarations additionally carry: - `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations that only touch derived counters. - `version` — an integer that starts at 1 on creation and increases by exactly one on every mutation of that row."

    Design: Corner/endpoints/revision_resubmission_resets_the_scoring_fields
    """
    world, sent_back = _abstract_sent_back_for_revision()
    assert sent_back["revision_round"] == 0
    assert float(sent_back["provisional_score"]) == pytest.approx(3.50, abs=0.005)
    assert float(sent_back["score_spread"]) == pytest.approx(1.00, abs=0.005)
    assert sent_back["submitted_review_count"] == 2

    resubmitted = validate_success(
        api_client.revise_abstract(
            sent_back["id"],
            revise_abstract_payload(
                290,
                title="Immunotherapy response imaging, revised",
                keywords=["oncology", "immunotherapy"],
            ),
            world["author_headers"],
        )
    )
    assert_abstract(resubmitted)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["provisional_score"] is None
    assert resubmitted["final_score"] is None
    assert resubmitted["score_spread"] is None
    assert resubmitted["submitted_review_count"] == 0
    assert resubmitted["body_word_count"] == 290
    assert resubmitted["title"] == "Immunotherapy response imaging, revised"
    assert sorted(resubmitted["keywords"]) == ["immunotherapy", "oncology"]
    # The blind label was minted at first submission and a revision never re-mints it.
    assert resubmitted["blind_code"] == sent_back["blind_code"]
    assert resubmitted["blind_code"] == f"{TEST_DEFAULTS['CONFERENCE_CODE']}-B0001"
    assert_version_incremented(resubmitted["version"], sent_back["version"])

    live = validate_success(
        api_client.get_abstract(sent_back["id"], world["chair_headers"])
    )
    assert live["status"] == "SUBMITTED"
    assert live["revision_round"] == 1
    assert live["provisional_score"] is None
    assert live["score_spread"] is None
    assert live["submitted_review_count"] == 0


def test_reviews_of_the_previous_round_survive_a_resubmission():
    """PRD: "Note that `submitted_review_count` counts only reviews whose `assigned_round` equals the abstract's current `revision_round`, so a revision resets the count without deleting anything."
    PRD: "On success `revision_round` rises by one; `body_word_count`, `body_structured` and `keywords` are replaced, as is `title` when supplied; `provisional_score`, `final_score` and `score_spread` all return to null; and `submitted_review_count` recomputes to zero, because reviews from the previous round keep the old value in their `assigned_round` and thereby leave the consensus input set for good."
    PRD: "Reviews accept `abstract_id`, `reviewer_member_id`, `status`, `assigned_round` and `is_third_review`."

    Design: Corner/endpoints/revision_resubmission_resets_the_scoring_fields
    """
    world, sent_back = _abstract_sent_back_for_revision()

    resubmitted = validate_success(
        api_client.revise_abstract(
            sent_back["id"],
            revise_abstract_payload(290),
            world["author_headers"],
        )
    )
    assert resubmitted["revision_round"] == 1
    assert resubmitted["submitted_review_count"] == 0

    rows, meta = validate_paginated(
        api_client.list_reviews(
            world["chair_headers"],
            params={"abstract_id": sent_back["id"], "assigned_round": 0},
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    for row in rows:
        assert row["assigned_round"] == 0
        assert row["status"] == "SUBMITTED"
