"""Lifecycles that are not a single line: parallel dimensions, loops and branches.

A submission carries two independent status dimensions, a rejected content edit
loops back a bounded number of times, and one panel tallies two slots into
opposite outcomes.
"""

from test_helpers import (
    ADOPTION_MODEL_ADOPTION_LIST,
    CONTENT_EDIT_STATUS_PROPOSED,
    CONTENT_EDIT_STATUS_REJECTED,
    PRICING_STATUS_PRICE_APPROVED,
    PROPOSAL_STATUS_APPROVED,
    REVIEW_STATUS_ADOPTED,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_FILED,
    REVIEW_STATUS_NOT_ADOPTED,
    SLOT_STATUS_TALLIED,
    TALLY_OUTCOME_RECOMMEND,
    TALLY_OUTCOME_REJECT,
    VOTE_RECOMMEND,
    VOTE_REJECT,
    WITHDRAW_REASON_REVISE,
    ApiErrorId,
    assert_decimal_equals,
    factories,
    fixtures,
    get_success_data,
    make_review_committee_member_headers,
    validate_error,
    validate_success,
)


def test_review_and_pricing_dimensions_stand_at_independent_states(api):
    """A filed submission can carry an approved price without either gating the other.

    PRD 3.4: "The new record is born with `review_status` `DRAFT` and
    `pricing_status` `UNPRICED` — the two dimensions of the submission lifecycle
    advance independently of each other, and neither gates the other's
    transitions."

    Design: Difficulty/non_linear_state_machine/submission_parallel_review_and_pricing_dimensions
    """
    world = fixtures.seed_priced_submission(
        api, "OK", proposal_overrides={"term_years": 2}
    )

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_FILED
    assert submission["pricing_status"] == PRICING_STATUS_PRICE_APPROVED
    assert submission["pinned_content_revision"] == 1
    assert submission["content_pin_stale"] is False

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 1


def test_a_revise_withdrawal_walks_review_back_and_leaves_pricing_untouched(api):
    """Backing the content out to DRAFT does not undo the state's price approval.

    PRD 3.5: "A `reason` of `REVISE` walks a filed submission back to `DRAFT` so
    the publisher can rework it: the cycle's `submission_count` decreases by 1,
    `pinned_content_revision` is reset to null and `content_pin_stale` is reset to
    false."

    Design: Difficulty/non_linear_state_machine/submission_parallel_review_and_pricing_dimensions
    """
    world = fixtures.seed_priced_submission(
        api, "OK", proposal_overrides={"term_years": 2}
    )

    withdrawn = validate_success(
        api.withdraw_submission(
            world.submission_id, {"reason": WITHDRAW_REASON_REVISE}, fixtures.EDITOR
        )
    )
    assert withdrawn["review_status"] == REVIEW_STATUS_DRAFT
    assert withdrawn["pricing_status"] == PRICING_STATUS_PRICE_APPROVED
    assert withdrawn["pinned_content_revision"] is None
    assert withdrawn["content_pin_stale"] is False

    proposal = validate_success(
        api.get_pricing_proposal(world.proposal_id, fixtures.PRICING)
    )
    assert proposal["status"] == PROPOSAL_STATUS_APPROVED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 0


def test_the_reject_resubmit_loop_overwrites_the_edit_on_each_round(api):
    """A second resubmission lands on round three and replaces the page delta.

    PRD 3.3: "The `PublisherEditor` resubmits it, moving it from `REJECTED` back to
    `PROPOSED`, incrementing `revision_round` by 1, overwriting
    `proposed_by_user_id` with the resubmitting `X-User-ID`, and overwriting the
    stored `topic_code`, `pages_delta` and `rationale` with whichever of those
    three the resubmission supplies."

    Design: Difficulty/non_linear_state_machine/content_edit_reject_resubmit_cycle_hits_revision_ceiling
    """
    world = fixtures.seed_state(api, "ID", required_topics=["FINANCIAL_LITERACY"])
    fixtures.seed_title(api, world, release=False, isbn_base="9780000001001")

    edit_id = fixtures.propose_content_edit(
        api, world, topic_code="FINANCIAL_LITERACY", pages_delta=24
    )
    fixtures.reject_content_edit(api, world, edit_id=edit_id)
    fixtures.resubmit_content_edit(api, world, edit_id=edit_id)
    fixtures.reject_content_edit(api, world, edit_id=edit_id)

    resubmitted = validate_success(
        api.resubmit_content_edit(
            edit_id,
            {
                "pages_delta": 16,
                "rationale": "Compressed the inserted strand into one signature.",
            },
            fixtures.EDITOR,
        )
    )
    assert resubmitted["status"] == CONTENT_EDIT_STATUS_PROPOSED
    assert resubmitted["revision_round"] == 3
    assert resubmitted["pages_delta"] == 16


def test_a_third_round_edit_cannot_go_round_again(api):
    """The fourth proposal of the same edit is refused at the revision ceiling.

    PRD 3.3: "The loop `PROPOSED → REJECTED → PROPOSED` is bounded: resubmission
    is permitted only while `revision_round` is strictly less than 3, so an edit
    that has already been proposed three times cannot go round again and the
    attempt is refused with `ERR_EDIT_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/content_edit_reject_resubmit_cycle_hits_revision_ceiling
    """
    world = fixtures.seed_state(api, "ID", required_topics=["FINANCIAL_LITERACY"])
    fixtures.seed_title(api, world, release=False, isbn_base="9780000001001")

    edit_id = fixtures.propose_content_edit(
        api, world, topic_code="FINANCIAL_LITERACY", pages_delta=24
    )
    fixtures.reject_content_edit(api, world, edit_id=edit_id)
    fixtures.resubmit_content_edit(api, world, edit_id=edit_id)
    fixtures.reject_content_edit(api, world, edit_id=edit_id)
    fixtures.resubmit_content_edit(
        api,
        world,
        edit_id=edit_id,
        pages_delta=16,
        rationale="Compressed the inserted strand into one signature.",
    )
    fixtures.reject_content_edit(api, world, edit_id=edit_id)

    validate_error(
        api.resubmit_content_edit(
            edit_id,
            {"rationale": "One more pass at the sequencing of the new lessons."},
            fixtures.EDITOR,
        ),
        ApiErrorId.ERR_EDIT_REVISION_LIMIT_REACHED,
        409,
    )

    edit = validate_success(api.get_content_edit(edit_id, fixtures.EDITOR))
    assert edit["status"] == CONTENT_EDIT_STATUS_REJECTED
    assert edit["revision_round"] == 3
    assert edit["pages_delta"] == 16


def test_a_unanimous_recommendation_adopts_the_first_slot_of_the_panel(api):
    """Slot A tallies at 1.0000 and carries its submission all the way to ADOPTED.

    PRD 3.8: "When adoption succeeds, the edition's `adopted_state_codes` gains
    the state's `state_code`, the edition's `status` moves from `DRAFT` to `ACTIVE`
    if it happened still to be `DRAFT`, the submission's `APPROVED` pricing
    proposal sets `contract_locked` to true, the cycle's `adopted_count` increases
    by 1 and its `submission_count` decreases by 1."

    Design: Difficulty/non_linear_state_machine/slot_tally_branches_diverge_on_same_panel
    """
    world = fixtures.seed_open_cycle(
        api,
        "FL",
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        title_overrides={"isbn_base": "9780000001101"},
    )
    standard_code = world.standard_codes[0]
    title_a = world.title_id
    title_b = get_success_data(
        api.create_title(
            factories.title_payload(
                subject="MATH", grade_low=5, grade_high=5, isbn_base="9780000001102"
            ),
            fixtures.EDITOR,
        )
    )["id"]
    get_success_data(api.release_title(title_b, fixtures.EDITOR))

    prepared = []
    for title_id in (title_a, title_b):
        submission_id = get_success_data(
            api.create_submission(
                factories.submission_payload(world.cycle_id, title_id), fixtures.EDITOR
            )
        )["id"]
        entry_id = get_success_data(
            api.create_correlation(
                submission_id,
                factories.correlation_payload(standard_code),
                fixtures.EDITOR,
            )
        )["id"]
        get_success_data(
            api.record_correlation_verdict(
                submission_id,
                entry_id,
                {"verdict": "ACCEPT"},
                make_review_committee_member_headers("cm-1"),
            )
        )
        get_success_data(api.file_submission(submission_id, fixtures.EDITOR))
        version = api.read_submission_version(submission_id, fixtures.PRICING)
        proposal_id = get_success_data(
            api.create_pricing_proposal(
                factories.pricing_proposal_payload(submission_id, version),
                fixtures.PRICING,
            )
        )["id"]
        get_success_data(
            api.decide_pricing_proposal(
                proposal_id, {"verdict": "APPROVE"}, world.officer
            )
        )
        prepared.append((submission_id, proposal_id))

    fixtures.seed_panel(api, world, member_count=3, quorum_required=3)
    slot_a = fixtures.reserve_slot(
        api,
        world,
        submission_id=prepared[0][0],
        start_at="2026-10-20T14:00:00Z",
        end_at="2026-10-20T14:30:00Z",
    )
    slot_b = fixtures.reserve_slot(
        api,
        world,
        submission_id=prepared[1][0],
        start_at="2026-10-20T15:00:00Z",
        end_at="2026-10-20T15:30:00Z",
    )

    fixtures.advance_to_in_review(api, world)
    fixtures.set_clock(api, "2026-10-20T15:00:00Z")
    fixtures.open_session(api, world)
    get_success_data(api.present_slot(slot_a, world.officer))
    get_success_data(api.present_slot(slot_b, world.officer))

    fixtures.cast_ballots(api, slot_a, [VOTE_RECOMMEND] * 3)
    fixtures.cast_ballots(api, slot_b, [VOTE_REJECT] * 3)

    tallied_a = validate_success(api.tally_slot(slot_a, world.officer))
    get_success_data(api.tally_slot(slot_b, world.officer))

    assert tallied_a["status"] == SLOT_STATUS_TALLIED
    assert tallied_a["tally_outcome"] == TALLY_OUTCOME_RECOMMEND
    assert_decimal_equals(tallied_a["recommend_ratio"], "1.0000", "recommend_ratio")

    submission_a = validate_success(
        api.get_submission(prepared[0][0], fixtures.EDITOR)
    )
    assert submission_a["review_status"] == REVIEW_STATUS_ADOPTED

    edition_a = validate_success(api.get_title(title_a, fixtures.EDITOR))
    assert edition_a["adopted_state_codes"] == ["FL"]

    proposal_a = validate_success(
        api.get_pricing_proposal(prepared[0][1], fixtures.PRICING)
    )
    assert proposal_a["contract_locked"] is True


def test_a_rejecting_tally_on_the_same_panel_adopts_nothing(api):
    """Slot B tallies at 0.0000, leaving its edition and its price filing untouched.

    PRD 3.8: "In that case `adopted_state_codes` is left untouched, every pricing
    proposal of the submission keeps `contract_locked` false, and only the cycle's
    `submission_count` decreases by 1."

    Design: Difficulty/non_linear_state_machine/slot_tally_branches_diverge_on_same_panel
    """
    world = fixtures.seed_open_cycle(
        api,
        "FL",
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        title_overrides={"isbn_base": "9780000001101"},
    )
    standard_code = world.standard_codes[0]
    title_a = world.title_id
    title_b = get_success_data(
        api.create_title(
            factories.title_payload(
                subject="MATH", grade_low=5, grade_high=5, isbn_base="9780000001102"
            ),
            fixtures.EDITOR,
        )
    )["id"]
    get_success_data(api.release_title(title_b, fixtures.EDITOR))

    prepared = []
    for title_id in (title_a, title_b):
        submission_id = get_success_data(
            api.create_submission(
                factories.submission_payload(world.cycle_id, title_id), fixtures.EDITOR
            )
        )["id"]
        entry_id = get_success_data(
            api.create_correlation(
                submission_id,
                factories.correlation_payload(standard_code),
                fixtures.EDITOR,
            )
        )["id"]
        get_success_data(
            api.record_correlation_verdict(
                submission_id,
                entry_id,
                {"verdict": "ACCEPT"},
                make_review_committee_member_headers("cm-1"),
            )
        )
        get_success_data(api.file_submission(submission_id, fixtures.EDITOR))
        version = api.read_submission_version(submission_id, fixtures.PRICING)
        proposal_id = get_success_data(
            api.create_pricing_proposal(
                factories.pricing_proposal_payload(submission_id, version),
                fixtures.PRICING,
            )
        )["id"]
        get_success_data(
            api.decide_pricing_proposal(
                proposal_id, {"verdict": "APPROVE"}, world.officer
            )
        )
        prepared.append((submission_id, proposal_id))

    fixtures.seed_panel(api, world, member_count=3, quorum_required=3)
    slot_a = fixtures.reserve_slot(
        api,
        world,
        submission_id=prepared[0][0],
        start_at="2026-10-20T14:00:00Z",
        end_at="2026-10-20T14:30:00Z",
    )
    slot_b = fixtures.reserve_slot(
        api,
        world,
        submission_id=prepared[1][0],
        start_at="2026-10-20T15:00:00Z",
        end_at="2026-10-20T15:30:00Z",
    )

    fixtures.advance_to_in_review(api, world)
    fixtures.set_clock(api, "2026-10-20T15:00:00Z")
    fixtures.open_session(api, world)
    get_success_data(api.present_slot(slot_a, world.officer))
    get_success_data(api.present_slot(slot_b, world.officer))

    fixtures.cast_ballots(api, slot_a, [VOTE_RECOMMEND] * 3)
    fixtures.cast_ballots(api, slot_b, [VOTE_REJECT] * 3)

    get_success_data(api.tally_slot(slot_a, world.officer))
    tallied_b = validate_success(api.tally_slot(slot_b, world.officer))

    assert tallied_b["status"] == SLOT_STATUS_TALLIED
    assert tallied_b["tally_outcome"] == TALLY_OUTCOME_REJECT
    assert_decimal_equals(tallied_b["recommend_ratio"], "0.0000", "recommend_ratio")

    submission_b = validate_success(
        api.get_submission(prepared[1][0], fixtures.EDITOR)
    )
    assert submission_b["review_status"] == REVIEW_STATUS_NOT_ADOPTED

    edition_b = validate_success(api.get_title(title_b, fixtures.EDITOR))
    assert edition_b["adopted_state_codes"] == []

    proposal_b = validate_success(
        api.get_pricing_proposal(prepared[1][1], fixtures.PRICING)
    )
    assert proposal_b["contract_locked"] is False

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["adopted_count"] == 1
    assert cycle["submission_count"] == 0
