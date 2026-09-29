"""One write, several hops, each caused by the hop before it.

Applying a content edit, tallying an adoption and advancing a phase each walk a
chain of records the client never names in the request.
"""

from test_helpers import (
    ADOPTION_MODEL_ADOPTION_LIST,
    COMMENT_STATUS_ESCALATED,
    CONTENT_EDIT_STATUS_APPLIED,
    CYCLE_STATUS_CLOSED_FOR_SUBMISSION,
    PROPOSAL_STATUS_APPROVED,
    REVIEW_STATUS_ADOPTED,
    REVIEW_STATUS_FILED,
    SEVERITY_CRITICAL,
    SLOT_STATUS_CANCELLED,
    SLOT_STATUS_TALLIED,
    TALLY_OUTCOME_RECOMMEND,
    VOTE_RECOMMEND,
    assert_page_budget_conserved,
    fixtures,
    get_success_data,
    validate_paginated,
    validate_success,
)


def test_applying_an_edit_rewrites_the_edition_and_stales_the_filed_submission(api):
    """Hops one and two: the edition gains forty pages and the pin goes stale.

    PRD 3.3: "**Hop one** rewrites the edition. `page_count` increases by
    `pages_delta` and `page_budget_remaining` decreases by the same `pages_delta`,
    so the signature identity of Section 2.10 still holds; `content_revision`
    increases by 1; and `content_tags` changes according to `edit_type` — for
    `ADD_REQUIRED_TOPIC` the `topic_code` is added to `content_tags`, for
    `REMOVE_PROHIBITED_TAG` the `topic_code` is removed from `content_tags`, and
    for `REGIONAL_SUBSTITUTION` `content_tags` is left exactly as it was."

    Design: Difficulty/transitive_cascade/content_edit_apply_four_hop_staleness_cascade
    """
    world = fixtures.seed_scheduled_submission(
        api,
        "MI",
        panel_overrides={"quorum_required": 2},
        title_overrides={"page_count": 400, "signature_page_capacity": 480},
    )
    edit_id = fixtures.propose_content_edit(
        api, world, topic_code="DATA_LITERACY", pages_delta=40
    )
    fixtures.approve_content_edit(api, world, edit_id)

    applied = validate_success(api.apply_content_edit(edit_id, fixtures.DIRECTOR))
    assert applied["status"] == CONTENT_EDIT_STATUS_APPLIED

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["content_revision"] == 2
    assert edition["page_count"] == 440
    assert edition["page_budget_remaining"] == 40
    assert "DATA_LITERACY" in edition["content_tags"]
    assert_page_budget_conserved(edition)

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["content_pin_stale"] is True
    assert submission["adoption_blocked"] is True


def test_the_stale_pin_cancels_the_slot_and_walks_the_submission_back(api):
    """Hops three and four: the panel gets its minutes back and the hearing is off.

    PRD 3.3: "**Hop four** is caused by hop three's cancellations. Each affected
    submission that now keeps no slot in `RESERVED`, `PRESENTED` or `TALLIED` moves
    its `review_status` from `SCHEDULED` back to `FILED`, and its cycle's
    `scheduled_submission_count` decreases by 1."

    Design: Difficulty/transitive_cascade/content_edit_apply_four_hop_staleness_cascade
    """
    world = fixtures.seed_scheduled_submission(
        api,
        "MI",
        panel_overrides={"quorum_required": 2},
        title_overrides={"page_count": 400, "signature_page_capacity": 480},
    )
    edit_id = fixtures.propose_content_edit(
        api, world, topic_code="DATA_LITERACY", pages_delta=40
    )
    fixtures.approve_content_edit(api, world, edit_id)

    get_success_data(api.apply_content_edit(edit_id, fixtures.DIRECTOR))

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_CANCELLED

    panel = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert panel["reserved_minutes"] == 0

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_FILED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 0


def test_a_recommending_tally_adopts_the_submission(api):
    """The tally itself lands the slot and the submission in their adopted states.

    PRD 3.8: "A `tally_outcome` of `RECOMMEND` moves the submission's
    `review_status` from `PRESENTED` to `ADOPTED` **provided every adoption gate is
    met**; a `tally_outcome` of `RECOMMEND_WITH_CONDITIONS` does the same but lands
    on `ADOPTED_WITH_CONDITIONS`."

    Design: Difficulty/transitive_cascade/tally_adoption_three_hop_contract_lock_cascade
    """
    world = fixtures.seed_presented_slot(
        api,
        "GA",
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        panel_overrides={"quorum_required": 3},
        proposal_overrides={
            "base_price_cents": 9200,
            "term_years": 4,
            "annual_escalator_bps": 100,
            "projected_adoption_units": 6000,
        },
    )
    fixtures.cast_ballots(api, world.slot_id, [VOTE_RECOMMEND] * 3)

    tallied = validate_success(api.tally_slot(world.slot_id, world.officer))
    assert tallied["status"] == SLOT_STATUS_TALLIED
    assert tallied["tally_outcome"] == TALLY_OUTCOME_RECOMMEND

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_ADOPTED


def test_the_adoption_locks_the_price_filing_and_lists_the_state(api):
    """The hops beyond the submission: the edition, the proposal and the counters.

    PRD 3.6: "It becomes true in exactly two situations: when a district order is
    confirmed against this proposal while the proposal is `APPROVED`, and when the
    submission reaches `ADOPTED` or `ADOPTED_WITH_CONDITIONS` with this proposal
    `APPROVED`."

    Design: Difficulty/transitive_cascade/tally_adoption_three_hop_contract_lock_cascade
    """
    world = fixtures.seed_presented_slot(
        api,
        "GA",
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        panel_overrides={"quorum_required": 3},
        proposal_overrides={
            "base_price_cents": 9200,
            "term_years": 4,
            "annual_escalator_bps": 100,
            "projected_adoption_units": 6000,
        },
    )
    fixtures.cast_ballots(api, world.slot_id, [VOTE_RECOMMEND] * 3)
    get_success_data(api.tally_slot(world.slot_id, world.officer))

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["adopted_state_codes"] == ["GA"]

    proposal = validate_success(
        api.get_pricing_proposal(world.proposal_id, fixtures.PRICING)
    )
    assert proposal["status"] == PROPOSAL_STATUS_APPROVED
    assert proposal["contract_locked"] is True

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["adopted_count"] == 1
    assert cycle["submission_count"] == 0


def test_a_phase_advance_escalates_overdue_comments_and_rescores_compliance(api):
    """Sweep steps one and two: three criticals escalate and the score falls to 40.

    PRD 3.1: "Step one: each public comment on a submission of this cycle whose
    `status` is `OPEN` and whose `response_due_at` is at or before the current
    logical clock moves to `ESCALATED`, with `was_overdue_at_response` set to true."

    Design: Difficulty/transitive_cascade/phase_advance_escalation_four_hop_cascade
    """
    world = fixtures.seed_scheduled_submission(
        api, "CO", state_overrides={"comment_response_days": 10}
    )
    fixtures.stack_public_comments(api, world, [SEVERITY_CRITICAL] * 3)

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    cycle = validate_success(api.advance_cycle_phase(world.cycle_id, world.officer))
    assert cycle["status"] == CYCLE_STATUS_CLOSED_FOR_SUBMISSION

    comments, _ = validate_paginated(
        api.list_public_comments(world.submission_id, fixtures.EDITOR)
    )
    assert [comment["status"] for comment in comments] == [COMMENT_STATUS_ESCALATED] * 3
    assert all(comment["was_overdue_at_response"] is True for comment in comments)

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    # 100 - 15(3) - 5(3) = 40, below the blocking threshold of 70.
    assert submission["unresolved_critical_count"] == 3
    assert submission["overdue_response_count"] == 3
    assert submission["compliance_score"] == 40
    assert submission["adoption_blocked"] is True


def test_the_same_sweep_cancels_the_blocked_submissions_reserved_slot(api):
    """Sweep step three follows step two's blocking decision into the panel record.

    PRD 3.1: "Step three: for each submission that is now blocked from adoption,
    every one of its presentation slots whose `status` is `RESERVED` moves to
    `CANCELLED` and that slot's panel has its `reserved_minutes` reduced by the
    slot's `duration_minutes`; then, if the submission keeps no slot in `RESERVED`,
    `PRESENTED` or `TALLIED`, its `review_status` steps back from `SCHEDULED` to
    `FILED` and its cycle's `scheduled_submission_count` decreases by 1."

    Design: Difficulty/transitive_cascade/phase_advance_escalation_four_hop_cascade
    """
    world = fixtures.seed_scheduled_submission(
        api, "CO", state_overrides={"comment_response_days": 10}
    )
    fixtures.stack_public_comments(api, world, [SEVERITY_CRITICAL] * 3)

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    get_success_data(api.advance_cycle_phase(world.cycle_id, world.officer))

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_CANCELLED
    assert slot["duration_minutes"] == 30

    panel = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert panel["reserved_minutes"] == 0

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["review_status"] == REVIEW_STATUS_FILED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 0
