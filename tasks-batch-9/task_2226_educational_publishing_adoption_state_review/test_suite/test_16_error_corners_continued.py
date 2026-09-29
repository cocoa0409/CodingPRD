"""Refusals that guard already-settled adoption records.

Each test drives the workflow to the point where one further write would rewrite
history the state has already relied on — a price the officer has already ruled
on, a comment the publisher has already answered, a hearing whose edition has
moved on, a revision year a live submission still occupies, a price filing a
signed district contract has frozen, and a content revision an adopted
submission rests on.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    COMMENT_CATEGORY_BIAS_CONCERN,
    COMMENT_STATUS_RESPONDED,
    CONTENT_EDIT_STATUS_APPLIED,
    EDIT_TYPE_REGIONAL_SUBSTITUTION,
    ORDER_STATUS_CONFIRMED,
    PANEL_STATUS_SCHEDULED,
    PRICING_STATUS_PRICE_APPROVED,
    PROPOSAL_STATUS_APPROVED,
    REVIEW_STATUS_ADOPTED,
    REVIEW_STATUS_FILED,
    REVISION_PLAN_PLAN,
    SEVERITY_MAJOR,
    SLOT_STATUS_TALLIED,
    TITLE_STATUS_REVISION_PLANNED,
    VOTE_RECOMMEND,
    factories,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CLOCK_AT_PANEL_SESSION_START,
    DIRECTOR,
    EDITOR,
    PRICING,
    CONFIRMING_REP,
    accept_correlations,
    advance_to_in_review,
    approve_content_edit,
    approve_price_proposal,
    cast_ballots,
    file_price_proposal,
    file_submission,
    open_session,
    present_slot,
    propose_content_edit,
    quote_order,
    reserve_slot,
    seed_draft_submission,
    seed_filed_submission,
    seed_open_cycle,
    seed_panel,
    seed_priced_submission,
    set_clock,
    stack_public_comments,
    tally_slot,
)


def _read_comment(api, submission_id, comment_id):
    """Read one public comment back off the submission's comment listing."""
    comments, _ = validate_paginated(api.list_public_comments(submission_id, EDITOR))
    return next(comment for comment in comments if comment["id"] == comment_id)


def test_second_decision_on_an_approved_price_filing_is_refused(api):
    """PRD 3.6: "A decision on a proposal that is not `FILED` is refused with `ERR_PRICING_PROPOSAL_STATE_INVALID`."

    PRD 3.6: "A `verdict` of `APPROVE` moves the proposal's `status` from `FILED` to `APPROVED` and the submission's `pricing_status` to `PRICE_APPROVED`; a `verdict` of `REJECT` moves the `status` from `FILED` to `REJECTED` and the `pricing_status` to `PRICE_REJECTED`."

    The officer has already approved the filing, so the proposal is no longer
    `FILED` and the board cannot change its mind by rejecting it afterwards. The
    approved price and the submission's pricing dimension both stand.

    Design: Corner/errors/a_decided_proposal_cannot_be_decided_again
    """
    world = seed_priced_submission(api, "RI", subject="MATH", grade=4)

    refused = api.decide_pricing_proposal(
        world.proposal_id,
        {"verdict": "REJECT", "reason": "The board changed its mind after the vote."},
        world.officer,
    )
    validate_error(refused, ApiErrorId.ERR_PRICING_PROPOSAL_STATE_INVALID, 409)

    proposal = validate_success(api.get_pricing_proposal(world.proposal_id, PRICING))
    assert proposal["status"] == PROPOSAL_STATUS_APPROVED
    assert proposal["contract_locked"] is False

    submission = validate_success(api.get_submission(world.submission_id, PRICING))
    assert submission["pricing_status"] == PRICING_STATUS_PRICE_APPROVED


def test_second_response_to_an_answered_comment_is_refused(api):
    """PRD 3.7: "The response is accepted from either `OPEN` or `ESCALATED`, moves the comment's `status` to `RESPONDED` — the terminal state — and sets `responded_at` to the logical clock. It requires the submission's `review_status` to be `FILED`, `SCHEDULED` or `PRESENTED`, else `ERR_SUBMISSION_STATE_INVALID`, and it requires the comment not to have been answered already, else `ERR_PUBLIC_COMMENT_STATE_INVALID`."

    PRD 3.7: "`unresolved_critical_count` is the number of the submission's comments whose `severity` is `CRITICAL` and whose `status` is `OPEN` or `ESCALATED`."

    `RESPONDED` is terminal, so the first answer is the answer of record: a
    second, contradictory answer neither replaces the published `response_body`
    nor moves `responded_at`.

    Design: Corner/errors/an_answered_comment_cannot_be_answered_twice
    """
    world = seed_filed_submission(api, "CT", subject="ELA", grade=5)
    comment_id = stack_public_comments(
        api,
        world,
        [SEVERITY_MAJOR],
        categories=[COMMENT_CATEGORY_BIAS_CONCERN],
    )[0]

    get_success_data(
        api.respond_to_public_comment(
            comment_id,
            {"response_body": "Two additional perspectives were added to the unit 4 list."},
            EDITOR,
        )
    )
    answered = _read_comment(api, world.submission_id, comment_id)
    assert answered["status"] == COMMENT_STATUS_RESPONDED
    # The publisher answered ten days ahead of the response deadline.
    assert answered["was_overdue_at_response"] is False
    assert answered["responded_at"].startswith("2026-09-15T00:00:00")

    refused = api.respond_to_public_comment(
        comment_id,
        {"response_body": "A second, contradictory answer to the same comment."},
        EDITOR,
    )
    validate_error(refused, ApiErrorId.ERR_PUBLIC_COMMENT_STATE_INVALID, 409)

    stored = _read_comment(api, world.submission_id, comment_id)
    assert stored["status"] == COMMENT_STATUS_RESPONDED
    assert stored["response_body"] == (
        "Two additional perspectives were added to the unit 4 list."
    )
    assert stored["responded_at"] == answered["responded_at"]
    assert stored["was_overdue_at_response"] is False

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["unresolved_critical_count"] == 0


def test_slot_reservation_is_refused_while_the_content_pin_is_stale(api):
    """PRD 3.8: "The submission must be `FILED`, else `ERR_SUBMISSION_STATE_INVALID`, and its `content_pin_stale` must be false, else `ERR_CONTENT_PIN_STALE`."

    PRD 3.3: "Every submission whose `title_id` is this edition, whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`, and whose `pinned_content_revision` is strictly less than the edition's new `content_revision`, sets `content_pin_stale` to true, recomputes `prohibited_hit_count`, `missing_required_topic_count` and `compliance_score`, and sets `adoption_blocked` to true."

    The state was asked to review revision 1; applying an edit afterwards lifts
    the edition to revision 2, and a submission pinned to the older revision
    cannot be seated for a hearing. The panel's minute budget is untouched.

    Design: Corner/errors/stale_content_pin_blocks_slot_reservation
    """
    world = seed_filed_submission(api, "NM", subject="MATH", grade=5)
    seed_panel(api, world, panel_label="NM MATH Panel A")

    edit_id = propose_content_edit(
        api,
        world,
        topic_code="NM_PUEBLO_GEOMETRY",
        pages_delta=0,
        edit_type=EDIT_TYPE_REGIONAL_SUBSTITUTION,
        rationale="Swaps two worked examples for Pueblo pottery geometry.",
    )
    approve_content_edit(api, world, edit_id)
    get_success_data(api.apply_content_edit(edit_id, DIRECTOR))

    panel_version = api.read_panel_version(world.panel_id, world.officer)
    refused = api.reserve_slot(
        world.panel_id,
        factories.slot_payload(world.submission_id, panel_version),
        world.officer,
    )
    validate_error(refused, ApiErrorId.ERR_CONTENT_PIN_STALE, 409)

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["content_pin_stale"] is True
    assert submission["pinned_content_revision"] == 1
    assert submission["adoption_blocked"] is True
    assert submission["review_status"] == REVIEW_STATUS_FILED

    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["content_revision"] == 2

    panel = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert panel["reserved_minutes"] == 0
    assert panel["status"] == PANEL_STATUS_SCHEDULED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 0


def test_revision_plan_targeting_the_year_of_a_live_submission_is_refused(api):
    """PRD 3.2: "Because a publisher must not plan a replacement edition into a year where the current edition is still competing, `PLAN` is refused with `ERR_REVISION_CONFLICTS_WITH_OPEN_ADOPTION` when any submission of this title has a `review_status` of `FILED`, `SCHEDULED` or `PRESENTED` inside a cycle whose `cycle_year` is at or after the requested `revision_target_cycle_year`."

    PRD 3.2: "`PLAN` moves the edition from `ACTIVE` to `REVISION_PLANNED` and records `revision_target_cycle_year`, the adoption year the next edition is being planned against; the field is required for this action and its absence is an `ERR_INVALID_REQUEST`."

    The edition is competing in the 2027 cycle, so 2027 is closed to a
    replacement while 2029 — a year no live submission occupies — is open. The
    refusal leaves the submission filed and still in the running.

    Design: Corner/errors/revision_plan_cannot_target_a_year_with_a_live_submission
    """
    world = seed_filed_submission(api, "DE", subject="SCIENCE", grade=4)

    refused = api.revision_plan(
        world.title_id,
        {"action": REVISION_PLAN_PLAN, "revision_target_cycle_year": 2027},
        DIRECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_REVISION_CONFLICTS_WITH_OPEN_ADOPTION, 409)

    planned = validate_success(
        api.revision_plan(
            world.title_id,
            {"action": REVISION_PLAN_PLAN, "revision_target_cycle_year": 2029},
            DIRECTOR,
        )
    )
    assert planned["status"] == TITLE_STATUS_REVISION_PLANNED
    assert planned["revision_target_cycle_year"] == 2029

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_FILED


def test_price_filing_frozen_by_a_confirmed_district_order_cannot_be_superseded(api):
    """PRD 3.9: "And when the order names a proposal whose `status` is `APPROVED`, that proposal sets `contract_locked` to true — the signed district contract freezes the price filing, which is why no later filing can supersede it and why a later cancellation does not release it."

    PRD 3.6: "A prior proposal whose `contract_locked` is true, however, can never be superseded, and the attempt to file over it is refused outright with `ERR_CONTRACT_LOCKED`."

    The lock arrives from the sales side while the submission is still merely
    filed, and from that moment the cheaper re-filing is refused outright rather
    than superseding the approved price the district signed against.

    Design: Corner/errors/a_signed_district_contract_freezes_the_price_filing
    """
    world = seed_priced_submission(api, "MD", subject="MATH", grade=6, receipt_units=100)
    quote_order(api, world, print_units=20, digital_seats=0, with_proposal=True)

    confirmed = validate_success(
        api.confirm_district_order(world.order_id, CONFIRMING_REP)
    )
    assert confirmed["status"] == ORDER_STATUS_CONFIRMED

    locked = validate_success(api.get_pricing_proposal(world.proposal_id, PRICING))
    assert locked["contract_locked"] is True

    version = api.read_submission_version(world.submission_id, PRICING)
    refused = api.create_pricing_proposal(
        factories.pricing_proposal_payload(
            world.submission_id, version, base_price_cents=8500
        ),
        PRICING,
    )
    validate_error(refused, ApiErrorId.ERR_CONTRACT_LOCKED, 409)

    proposal = validate_success(api.get_pricing_proposal(world.proposal_id, PRICING))
    assert proposal["status"] == PROPOSAL_STATUS_APPROVED
    assert proposal["contract_locked"] is True

    submission = validate_success(api.get_submission(world.submission_id, PRICING))
    assert submission["pricing_status"] == PRICING_STATUS_PRICE_APPROVED
    assert submission["review_status"] == REVIEW_STATUS_FILED

    proposals, meta = validate_paginated(
        api.list_pricing_proposals(PRICING, {"submission_id": world.submission_id})
    )
    assert meta["total_count"] == 1
    assert [proposal["id"] for proposal in proposals] == [world.proposal_id]


def test_revert_is_refused_when_an_adopted_submission_pinned_the_edits_revision(api):
    """PRD 3.3: "A revert is refused with `ERR_EDIT_REVERT_BLOCKED` when any submission of this edition has a `review_status` of `ADOPTED` or `ADOPTED_WITH_CONDITIONS` and a `pinned_content_revision` at or above the revision that this edit's apply produced: once a state has adopted a revision, the publisher may not retroactively unmake it."

    PRD 3.8: "When adoption succeeds, the edition's `adopted_state_codes` gains the state's `state_code`, the edition's `status` moves from `DRAFT` to `ACTIVE` if it happened still to be `DRAFT`, the submission's `APPROVED` pricing proposal sets `contract_locked` to true, the cycle's `adopted_count` increases by 1 and its `submission_count` decreases by 1."

    The state adopted revision 2 — the revision this edit's apply produced — so
    the compensating arc is closed off and the edition keeps the ten pages the
    edit added.

    Design: Corner/errors/adopted_pin_blocks_reverting_the_edit_it_rests_on
    """
    world = seed_open_cycle(api, "OH", subject="MATH", grade=8)

    edit_id = propose_content_edit(
        api,
        world,
        topic_code="OHIO_MANUFACTURING_DATA",
        pages_delta=10,
        edit_type=EDIT_TYPE_REGIONAL_SUBSTITUTION,
        rationale="Replaces the national data set with Ohio manufacturing data.",
    )
    approve_content_edit(api, world, edit_id)
    get_success_data(api.apply_content_edit(edit_id, DIRECTOR))

    seed_draft_submission(api, world)
    accept_correlations(api, world)
    file_submission(api, world)
    file_price_proposal(api, world, base_price_cents=9200)
    approve_price_proposal(api, world)

    seed_panel(api, world, panel_label="OH MATH Panel A")
    reserve_slot(api, world)
    advance_to_in_review(api, world)
    set_clock(api, CLOCK_AT_PANEL_SESSION_START)
    open_session(api, world)
    present_slot(api, world)
    cast_ballots(api, world.slot_id, [VOTE_RECOMMEND, VOTE_RECOMMEND])
    tally_slot(api, world)
    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_TALLIED

    refused = api.revert_content_edit(
        edit_id,
        {"reason": "The publisher would rather ship the national data set after all."},
        DIRECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_EDIT_REVERT_BLOCKED, 409)

    edit = validate_success(api.get_content_edit(edit_id, DIRECTOR))
    assert edit["status"] == CONTENT_EDIT_STATUS_APPLIED

    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["page_count"] == 310
    assert title["content_revision"] == 2

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_ADOPTED
    assert submission["pinned_content_revision"] == 2

    proposal = validate_success(api.get_pricing_proposal(world.proposal_id, PRICING))
    assert proposal["contract_locked"] is True
