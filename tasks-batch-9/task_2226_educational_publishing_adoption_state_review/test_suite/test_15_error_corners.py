"""Refusal paths of the adoption-review contract.

Each test drives one operation into exactly one of the contract's refusals and
then proves the refusal changed nothing: the addressed record keeps its status,
the counters it feeds keep their values, and the collection the write would have
joined stays empty.
"""

import pytest

from test_helpers import (
    ACCESSIBILITY_WCAG_2_1_AA,
    ACCESSIBILITY_WCAG_2_2_AA,
    CONTENT_EDIT_STATUS_APPROVED,
    CYCLE_STATUS_IN_REVIEW,
    CYCLE_STATUS_OPEN,
    CYCLE_STATUS_SCHEDULED,
    DEPTH_MENTION,
    EDIT_TYPE_REGIONAL_SUBSTITUTION,
    NON_EXISTENT_UUID,
    ORDER_STATUS_QUOTED,
    PANEL_STATUS_SCHEDULED,
    PRICING_STATUS_UNPRICED,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_PRESENTED,
    ROSTERING_ONEROSTER_1_1,
    ROSTERING_ONEROSTER_1_2,
    SLOT_STATUS_PRESENTED,
    SLOT_STATUS_RESERVED,
    TALLY_OUTCOME_PENDING,
    TITLE_STATUS_DRAFT,
    VOTE_ABSTAIN,
    VOTE_RECOMMEND,
    ApiErrorId,
    assert_decimal_equals,
    assert_page_budget_conserved,
    assert_print_unit_ledger_balances,
    factories,
    get_success_data,
    make_review_committee_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLOCK_INSIDE_SUBMISSION_WINDOW,
    DIRECTOR,
    EDITOR,
    PRICING,
    QUOTING_REP,
    advance_phase,
    advance_to_in_review,
    approve_content_edit,
    cast_ballots,
    open_session,
    propose_content_edit,
    quote_order,
    reserve_slot,
    seed_bundle,
    seed_cycle,
    seed_draft_submission,
    seed_filed_submission,
    seed_open_cycle,
    seed_panel,
    seed_presented_slot,
    seed_standard,
    seed_state,
    seed_title,
    set_clock,
)

#: An identifier that resolves to nothing, whichever family addresses it.
UNKNOWN_ID = NON_EXISTENT_UUID

MEMBER_ONE = make_review_committee_member_headers("cm-1")


# ---------------------------------------------------------------------------
# Unknown identifiers
# ---------------------------------------------------------------------------


def test_each_addressed_resource_family_returns_its_own_not_found_code(api):
    """PRD 2.6: "A `/state-profiles` path identifier resolves to a `StateProfile`, else `ERR_STATE_PROFILE_NOT_FOUND` (404) — on reading a state profile, and on adding to or listing its standards."

    PRD 2.6: "An `/adoption-cycles` path identifier resolves to an `AdoptionCycle`, else `ERR_ADOPTION_CYCLE_NOT_FOUND` (404) — on reading a cycle, advancing its phase, and listing its panels."
    PRD 2.6: "A `/content-edits` path identifier resolves to a `ContentEdit`, else `ERR_CONTENT_EDIT_NOT_FOUND` (404) — on reading, reviewing, resubmitting, applying and reverting an edit."
    PRD 2.6: "A `/committee-panels` path identifier resolves to a `CommitteePanel`, else `ERR_COMMITTEE_PANEL_NOT_FOUND` (404) — on reading a panel, reserving a slot on it, and opening or closing its session."
    PRD 2.6: "A `/presentation-slots` path identifier resolves to a `PresentationSlot`, else `ERR_PRESENTATION_SLOT_NOT_FOUND` (404) — on reading a slot, presenting it, casting or listing its ballots, and tallying it."
    PRD 2.6: "A `/pricing-proposals` path identifier resolves to a `PricingProposal`, else `ERR_PRICING_PROPOSAL_NOT_FOUND` (404) — on reading a proposal and deciding it."
    PRD 2.6: "A `/district-orders` path identifier resolves to a `DistrictOrder`, else `ERR_DISTRICT_ORDER_NOT_FOUND` (404) — on reading, confirming, fulfilling and cancelling an order."
    PRD 2.6: "A `/public-comments` path identifier resolves to a `PublicComment`, else `ERR_PUBLIC_COMMENT_NOT_FOUND` (404) — on publishing a response to a comment."

    Every family answers an unknown identifier with the code minted for that
    family, never with a generic one.

    Design: Corner/errors/every_not_found_code_is_reachable_with_an_unknown_id
    """
    validate_error(
        api.get_state_profile(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_STATE_PROFILE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_adoption_cycle(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_ADOPTION_CYCLE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_content_edit(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_CONTENT_EDIT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_committee_panel(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_COMMITTEE_PANEL_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_presentation_slot(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_PRESENTATION_SLOT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_pricing_proposal(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_PRICING_PROPOSAL_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_district_order(UNKNOWN_ID, ADMIN),
        ApiErrorId.ERR_DISTRICT_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.respond_to_public_comment(
            UNKNOWN_ID, factories.comment_response_payload(), EDITOR
        ),
        ApiErrorId.ERR_PUBLIC_COMMENT_NOT_FOUND,
        404,
    )


def test_unknown_correlation_entry_under_a_real_submission_is_absent(api):
    """PRD 2.6: "The correlation-entry identifier resolves to a `CorrelationEntry` belonging to the submission in the path, else `ERR_CORRELATION_ENTRY_NOT_FOUND` (404) — on recording an entry verdict."

    The submission in the path resolves, so the 404 the committee member sees
    names the correlation entry rather than the submission.

    Design: Corner/errors/every_not_found_code_is_reachable_with_an_unknown_id
    """
    world = seed_state(api, "ND")
    seed_cycle(api, world, subject="MATH")
    seed_title(api, world, release=False, subject="MATH", grade_low=2, grade_high=2)
    submission = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), EDITOR
        )
    )

    validate_error(
        api.record_correlation_verdict(
            submission["id"], UNKNOWN_ID, {"verdict": "ACCEPT"}, MEMBER_ONE
        ),
        ApiErrorId.ERR_CORRELATION_ENTRY_NOT_FOUND,
        404,
    )


def test_unknown_title_in_a_quote_body_is_a_referenced_resource_failure(api):
    """PRD 2.6: "Every foreign key supplied in a request body — `state_id`, `cycle_id`, `title_id`, `submission_id`, `bundle_id`, `pricing_proposal_id` — resolves to an existing record, else `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404). Applies to creating a cycle, a content edit, a submission, a panel, a slot, a pricing proposal and a district order."

    A `title_id` that names nothing is a body foreign key, so the quote is
    refused with the referenced-resource code and not with the addressed-title
    code.

    Design: Corner/errors/every_not_found_code_is_reachable_with_an_unknown_id
    """
    world = seed_state(api, "ND")

    validate_error(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id, UNKNOWN_ID, print_units=10, digital_seats=0
            ),
            QUOTING_REP,
        ),
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND,
        404,
    )


# ---------------------------------------------------------------------------
# The logical clock gates the calendar
# ---------------------------------------------------------------------------


def test_phase_advance_before_the_window_opens_is_not_due(api):
    """PRD 3.1: "A run whose clock test fails changes nothing and is rejected with `ERR_PHASE_NOT_DUE`."

    PRD 2.6: "The logical clock has reached the timestamp of the phase being entered, else `ERR_PHASE_NOT_DUE` (409), on advancing a phase."

    The clock still reads its origin while the window opens on 2026-09-01, so
    the cycle keeps its `SCHEDULED` phase and its `phase_epoch` of 0.

    Design: Corner/errors/logical_clock_gates_both_calendar_advances
    """
    world = seed_state(api, "SD")
    seed_cycle(api, world, subject="ELA")

    validate_error(
        api.advance_cycle_phase(world.cycle_id, world.officer),
        ApiErrorId.ERR_PHASE_NOT_DUE,
        409,
    )

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["status"] == CYCLE_STATUS_SCHEDULED
    assert cycle["phase_epoch"] == 0


def test_opening_a_panel_session_before_its_start_is_not_due(api):
    """PRD 3.8: "Opening a panel session moves the panel from `SCHEDULED` to `IN_SESSION` and requires three things of the acting officer's state: the cycle must be `IN_REVIEW`, else `ERR_ADOPTION_CYCLE_STATE_INVALID`, and the logical clock must have reached `session_start_at`, else `ERR_PANEL_SESSION_NOT_DUE`."

    The cycle has reached `IN_REVIEW`, so the only unmet condition is the clock,
    and the panel stays `SCHEDULED` with no minutes reserved.

    Design: Corner/errors/logical_clock_gates_both_calendar_advances
    """
    world = seed_state(api, "SD")
    seed_cycle(api, world, subject="ELA")
    set_clock(api, CLOCK_INSIDE_SUBMISSION_WINDOW)
    advance_phase(api, world)
    panel_id = seed_panel(
        api,
        world,
        panel_label="SD ELA Panel A",
        session_start_at="2026-10-20T14:00:00Z",
        session_end_at="2026-10-20T18:00:00Z",
    )
    advance_to_in_review(api, world)

    validate_error(
        api.open_panel_session(panel_id, world.officer),
        ApiErrorId.ERR_PANEL_SESSION_NOT_DUE,
        409,
    )

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["status"] == CYCLE_STATUS_IN_REVIEW
    panel = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert panel["status"] == PANEL_STATUS_SCHEDULED
    assert panel["reserved_minutes"] == 0


# ---------------------------------------------------------------------------
# The presentation slot lifecycle
# ---------------------------------------------------------------------------


def _panel_in_session_with_a_later_slot(api):
    """A filed submission holding a 15:00 slot on a panel sitting from 14:00."""
    world = seed_filed_submission(api, "ME", subject="SCIENCE", grade=7)
    seed_panel(api, world, panel_label="ME SCIENCE Panel A")
    reserve_slot(
        api,
        world,
        start_at="2026-10-20T15:00:00Z",
        end_at="2026-10-20T15:30:00Z",
    )
    advance_to_in_review(api, world)
    set_clock(api, "2026-10-20T14:00:00Z")
    open_session(api, world)
    return world


def test_ballot_on_a_reserved_slot_is_refused_before_the_presentation(api):
    """PRD 3.8: "Balloting is the `ReviewCommitteeMember`'s act, permitted only while the slot is `PRESENTED`."

    PRD 2.6: "The addressed slot's `status` admits the operation, else `ERR_PRESENTATION_SLOT_STATE_INVALID` (409) — presenting requires `RESERVED`, casting a ballot requires `PRESENTED`, tallying requires `PRESENTED`, and closing a session requires that no slot of the panel is `PRESENTED`."

    The panel is in session but the slot has not been presented, so the ballot
    log stays empty.

    Design: Corner/errors/slot_lifecycle_order_is_enforced_before_and_at_start
    """
    world = _panel_in_session_with_a_later_slot(api)

    validate_error(
        api.cast_vote(world.slot_id, factories.vote_payload(VOTE_RECOMMEND), MEMBER_ONE),
        ApiErrorId.ERR_PRESENTATION_SLOT_STATE_INVALID,
        409,
    )

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_RESERVED
    ballots, meta = validate_paginated(api.list_votes(world.slot_id, world.officer))
    assert meta["total_count"] == 0
    assert ballots == []


def test_presenting_before_the_slot_start_instant_is_refused(api):
    """PRD 3.8: "Presenting a slot moves it from `RESERVED` to `PRESENTED` and simultaneously moves its submission's `review_status` from `SCHEDULED` to `PRESENTED`."

    PRD 3.8: "Three preconditions apply: the panel must be `IN_SESSION`, else `ERR_COMMITTEE_PANEL_STATE_INVALID`; the logical clock must have reached the slot's `start_at`, else `ERR_SLOT_NOT_STARTED`; and the submission's `content_pin_stale` must be false, else `ERR_CONTENT_PIN_STALE` — a submission whose edition changed between reservation and hearing cannot be heard."

    At 14:00 the 15:00 slot has not started; the identical call succeeds once
    the clock stands on the slot's own `start_at`.

    Design: Corner/errors/slot_lifecycle_order_is_enforced_before_and_at_start
    """
    world = _panel_in_session_with_a_later_slot(api)

    validate_error(
        api.present_slot(world.slot_id, world.officer),
        ApiErrorId.ERR_SLOT_NOT_STARTED,
        409,
    )
    early = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert early["status"] == SLOT_STATUS_RESERVED

    set_clock(api, "2026-10-20T15:00:00Z")
    presented = validate_success(api.present_slot(world.slot_id, world.officer))
    assert presented["status"] == SLOT_STATUS_PRESENTED

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_PRESENTED


# ---------------------------------------------------------------------------
# Entering and filing a submission
# ---------------------------------------------------------------------------


def test_second_live_submission_for_the_same_cycle_and_title_is_duplicate(api):
    """PRD 3.4: "Only one submission may be live for a given pair of `cycle_id` and `title_id` at a time; a second attempt is refused with `ERR_DUPLICATE_SUBMISSION` unless every existing submission for that pair has a `review_status` of `WITHDRAWN` or `NOT_ADOPTED`."

    The first submission is still `DRAFT`, hence still live, so the cycle keeps
    exactly one submission.

    Design: Corner/errors/submission_entry_gates_reject_duplicate_and_late_filing
    """
    world = seed_open_cycle(
        api, "IA", subject="MATH", grade=2, standard_code="IA.M.2.1"
    )
    seed_draft_submission(api, world)

    validate_error(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id), EDITOR
        ),
        ApiErrorId.ERR_DUPLICATE_SUBMISSION,
        409,
    )

    submissions, meta = validate_paginated(
        api.list_submissions(EDITOR, {"cycle_id": world.cycle_id})
    )
    assert meta["total_count"] == 1
    assert submissions[0]["id"] == world.submission_id


def test_filing_after_the_submission_deadline_closes_the_window(api):
    """PRD 3.5: "The logical clock must sit inside the cycle's half-open submission window — at or after `submission_open_at` and strictly before `submission_deadline_at` — else `ERR_SUBMISSION_WINDOW_CLOSED`."

    The cycle has not been advanced, so it is still `OPEN` and the refusal comes
    from the clock standing past the deadline rather than from the phase.

    Design: Corner/errors/submission_entry_gates_reject_duplicate_and_late_filing
    """
    world = seed_open_cycle(
        api, "IA", subject="MATH", grade=2, standard_code="IA.M.2.1"
    )
    seed_draft_submission(api, world)
    set_clock(api, "2026-10-02T00:00:00Z")

    validate_error(
        api.file_submission(world.submission_id, EDITOR),
        ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED,
        422,
    )

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["status"] == CYCLE_STATUS_OPEN
    assert cycle["submission_count"] == 0
    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_DRAFT
    assert submission["pinned_content_revision"] is None


def test_citing_a_code_outside_the_state_framework_is_refused(api):
    """PRD 3.4: "The cited `standard_code` must exist in the framework of the cycle's state and subject, else `ERR_STANDARD_NOT_IN_FRAMEWORK`."

    The framework of this state and subject declares one code; a second,
    unknown code cannot be documented against it.

    Design: Corner/errors/filing_gate_stack_peels_off_topic_then_focus_coverage
    """
    world = seed_open_cycle(
        api,
        "GA",
        subject="SOCIAL_STUDIES",
        grade=9,
        standard_code="GA.SS.9.1",
    )
    seed_draft_submission(api, world)

    validate_error(
        api.create_correlation(
            world.submission_id, factories.correlation_payload("GA.SS.11.9"), EDITOR
        ),
        ApiErrorId.ERR_STANDARD_NOT_IN_FRAMEWORK,
        422,
    )

    entries, meta = validate_paginated(
        api.list_correlations(world.submission_id, EDITOR)
    )
    assert meta["total_count"] == 1
    assert len(entries) == 1


def _submission_with_a_mention_only_focus_standard(api, **state_overrides):
    """A DRAFT submission citing the state's focus standard at MENTION depth."""
    world = seed_state(api, "GA", min_verified_coverage_pct=20.00, **state_overrides)
    seed_standard(
        api,
        world,
        "GA.SS.9.1",
        subject="SOCIAL_STUDIES",
        grade_low=9,
        grade_high=9,
        weight=3,
        is_focus=True,
    )
    seed_cycle(api, world, subject="SOCIAL_STUDIES")
    seed_title(
        api,
        world,
        subject="SOCIAL_STUDIES",
        grade_low=9,
        grade_high=9,
        content_tags=["PRIMARY_SOURCES"],
    )
    set_clock(api, CLOCK_INSIDE_SUBMISSION_WINDOW)
    advance_phase(api, world)
    seed_draft_submission(api, world, depth_levels=(DEPTH_MENTION,))
    return world


def test_missing_required_topic_outranks_the_uncovered_focus_standard(api):
    """PRD 2.6: "More broadly, when several checks could reject one request, they are evaluated in a fixed order and the **first** failing check supplies the response."

    PRD 2.6: "Every required topic of the state is supplied, else `ERR_REQUIRED_TOPIC_MISSING` (422), on filing."
    PRD 2.6: "Every focus standard in the coverage input set is cited deeply enough, else `ERR_FOCUS_STANDARD_UNCOVERED` (422), on filing."

    The edition both omits the state's required topic and treats the focus
    standard at MENTION depth only; the required topic is checked first, so that
    is the code the filing returns.

    Design: Corner/errors/filing_gate_stack_peels_off_topic_then_focus_coverage
    """
    world = _submission_with_a_mention_only_focus_standard(
        api, required_topics=["FINANCIAL_LITERACY"]
    )

    validate_error(
        api.file_submission(world.submission_id, EDITOR),
        ApiErrorId.ERR_REQUIRED_TOPIC_MISSING,
        422,
    )

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_DRAFT
    assert submission["missing_required_topic_count"] == 1
    assert_decimal_equals(
        submission["self_reported_coverage_pct"], "40.00", "self_reported_coverage_pct"
    )


def test_focus_standard_cited_only_at_mention_depth_blocks_filing(api):
    """PRD 3.5: "Every standard in the coverage denominator set whose `is_focus` is true must be cited by at least one correlation entry whose `depth_level` is `PRACTICE` or `MASTERY` and whose `reviewer_verdict` is `PENDING` or `ACCEPTED`, else `ERR_FOCUS_STANDARD_UNCOVERED` — a state's focus standards cannot be discharged by a passing mention."

    This state demands no topic, so the focus standard is the only unmet
    condition and the passing mention cannot discharge it.

    Design: Corner/errors/filing_gate_stack_peels_off_topic_then_focus_coverage
    """
    world = _submission_with_a_mention_only_focus_standard(api)

    validate_error(
        api.file_submission(world.submission_id, EDITOR),
        ApiErrorId.ERR_FOCUS_STANDARD_UNCOVERED,
        422,
    )

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_DRAFT
    assert submission["missing_required_topic_count"] == 0
    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 0


# ---------------------------------------------------------------------------
# The catalog and the district order lifecycle
# ---------------------------------------------------------------------------


def test_quoting_an_unreleased_edition_is_refused(api):
    """PRD 3.9: "Quoting requires the edition to have been released, else `ERR_TITLE_NOT_RELEASED`, and requires it not to be `SUNSET`, else `ERR_TITLE_SUNSET`."

    PRD 3.2: "Only after release may the edition be submitted to a state, priced, or ordered by a district."

    The edition exists, so the refusal is a conflict on its `DRAFT` status
    rather than a 404, and no order is recorded.

    Design: Corner/errors/unreleased_title_cannot_be_ordered
    """
    world = seed_state(api, "NE")
    title_id = seed_title(
        api, world, release=False, subject="MATH", grade_low=3, grade_high=3
    )

    validate_error(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id, title_id, print_units=25, digital_seats=5
            ),
            QUOTING_REP,
        ),
        ApiErrorId.ERR_TITLE_NOT_RELEASED,
        409,
    )

    title = validate_success(api.get_title(title_id, EDITOR))
    assert title["status"] == TITLE_STATUS_DRAFT
    orders, meta = validate_paginated(
        api.list_district_orders(QUOTING_REP, {"title_id": title_id})
    )
    assert meta["total_count"] == 0
    assert orders == []


def test_fulfilling_a_quoted_order_before_confirmation_is_refused(api):
    """PRD 2.6: "The addressed order's `status` admits the operation, else `ERR_DISTRICT_ORDER_STATE_INVALID` (409) — confirm requires `QUOTED`, fulfil requires `CONFIRMED`, cancel requires `QUOTED` or `CONFIRMED`; the same code also refuses a revision-plan sunset while any order of the title is `CONFIRMED`."

    PRD 3.9: "Fulfilment moves a `CONFIRMED` order to `FULFILLED`, its terminal state, decreasing the edition's `committed_units` by `allocated_units` and increasing its `fulfilled_units` by the same amount."

    Nothing was ever committed, so the shelf keeps all hundred units and the
    order keeps its quote.

    Design: Corner/errors/quoted_order_cannot_be_fulfilled_before_confirmation
    """
    world = seed_state(api, "AZ")
    seed_title(
        api,
        world,
        receipt_units=100,
        subject="ELA",
        grade_low=6,
        grade_high=6,
        content_tags=["CLOSE_READING"],
    )
    order_id = quote_order(api, world, print_units=30, digital_seats=0)

    validate_error(
        api.fulfill_district_order(order_id, QUOTING_REP),
        ApiErrorId.ERR_DISTRICT_ORDER_STATE_INVALID,
        409,
    )

    order = validate_success(api.get_district_order(order_id, QUOTING_REP))
    assert order["status"] == ORDER_STATUS_QUOTED
    assert order["allocated_units"] == 0
    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["on_hand_units"] == 100
    assert title["committed_units"] == 0
    assert title["fulfilled_units"] == 0
    assert_print_unit_ledger_balances(title)


def test_applying_an_edit_beyond_the_signature_capacity_is_refused(api):
    """PRD 3.3: "Two preconditions guard the apply beyond the edit's own status. The edition must not be `SUNSET`, else `ERR_TITLE_SUNSET`; and the resulting page count — the edition's current `page_count` plus the edit's `pages_delta` — must be at most `signature_page_capacity` and at least 1, else `ERR_PAGE_BUDGET_EXCEEDED` in either direction."

    PRD 2.10: "Any apply that would drive `page_count` above `signature_page_capacity` or below 1 is refused with `ERR_PAGE_BUDGET_EXCEEDED`."

    Ten more pages against 380 of 384 overruns the press signature budget, so
    the edition is untouched and the edit stays `APPROVED`.

    Design: Corner/errors/applying_an_edit_past_the_signature_capacity_is_refused
    """
    world = seed_state(api, "CO")
    seed_title(
        api,
        world,
        subject="SCIENCE",
        grade_low=10,
        grade_high=10,
        page_count=380,
        signature_page_capacity=384,
        content_tags=["EARTH_SYSTEMS"],
    )
    edit_id = propose_content_edit(
        api,
        world,
        topic_code="COLORADO_WATERSHED",
        pages_delta=10,
        edit_type=EDIT_TYPE_REGIONAL_SUBSTITUTION,
    )
    approve_content_edit(api, world, edit_id)

    validate_error(
        api.apply_content_edit(edit_id, DIRECTOR),
        ApiErrorId.ERR_PAGE_BUDGET_EXCEEDED,
        409,
    )

    edit = validate_success(api.get_content_edit(edit_id, DIRECTOR))
    assert edit["status"] == CONTENT_EDIT_STATUS_APPROVED
    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["page_count"] == 380
    assert title["page_budget_remaining"] == 4
    assert title["content_revision"] == 1
    assert_page_budget_conserved(title)


# ---------------------------------------------------------------------------
# Digital platform commitments and the fiscal ceilings of a price filing
# ---------------------------------------------------------------------------


def _filed_submission_of_a_demanding_state(api):
    """A FILED submission of a state demanding the strongest commitments."""
    return seed_filed_submission(
        api,
        "PA",
        subject="MATH",
        grade=6,
        standard_code="PA.M.6.1",
        state_overrides={
            "accessibility_standard": ACCESSIBILITY_WCAG_2_2_AA,
            "rostering_standard": ROSTERING_ONEROSTER_1_2,
            "data_privacy_addendum_required": True,
        },
        title_overrides={"content_tags": ["RATIO_REASONING"]},
    )


def _assert_no_price_was_filed(api, world, expected_version):
    """The submission keeps its version and carries no proposal."""
    submission = validate_success(api.get_submission(world.submission_id, PRICING))
    assert submission["pricing_status"] == PRICING_STATUS_UNPRICED
    assert submission["version"] == expected_version
    proposals, meta = validate_paginated(
        api.list_pricing_proposals(PRICING, {"submission_id": world.submission_id})
    )
    assert meta["total_count"] == 0
    assert proposals == []


def test_bundle_below_the_states_accessibility_level_is_refused(api):
    """PRD 2.11: "Accessibility is a **ranked** comparison in which `WCAG_2_2_AA` is stronger than `WCAG_2_1_AA`: a bundle conforming to `WCAG_2_2_AA` satisfies a state demanding either level, a bundle conforming to `WCAG_2_1_AA` satisfies only a state demanding `WCAG_2_1_AA`, and a bundle conforming to `NONE` satisfies no state at all."

    PRD 2.6: "When a bundle is named, its accessibility conformance meets the state's demand, else `ERR_ACCESSIBILITY_COMMITMENT_MISSING` (422), on filing a price proposal."

    Design: Corner/errors/bundle_commitment_checks_each_fire_on_their_own_defect
    """
    world = _filed_submission_of_a_demanding_state(api)
    bundle_id = seed_bundle(
        api,
        world,
        component_count=3,
        accessibility_conformance=ACCESSIBILITY_WCAG_2_1_AA,
        rostering_standard=ROSTERING_ONEROSTER_1_2,
        privacy_addendum_signed=True,
    )
    version = api.read_submission_version(world.submission_id, PRICING)

    validate_error(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id, version, bundle_id=bundle_id
            ),
            PRICING,
        ),
        ApiErrorId.ERR_ACCESSIBILITY_COMMITMENT_MISSING,
        422,
    )

    _assert_no_price_was_filed(api, world, version)


def test_bundle_without_the_signed_privacy_addendum_is_refused(api):
    """PRD 2.11: "Privacy is a simple conjunction: when the state's `data_privacy_addendum_required` is true, the bundle's `privacy_addendum_signed` must be true."

    PRD 2.6: "When a bundle is named and the state demands a signed privacy addendum, the bundle has one, else `ERR_PRIVACY_ADDENDUM_MISSING` (422), on filing a price proposal."

    Design: Corner/errors/bundle_commitment_checks_each_fire_on_their_own_defect
    """
    world = _filed_submission_of_a_demanding_state(api)
    bundle_id = seed_bundle(
        api,
        world,
        component_count=3,
        accessibility_conformance=ACCESSIBILITY_WCAG_2_2_AA,
        rostering_standard=ROSTERING_ONEROSTER_1_2,
        privacy_addendum_signed=False,
    )
    version = api.read_submission_version(world.submission_id, PRICING)

    validate_error(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id, version, bundle_id=bundle_id
            ),
            PRICING,
        ),
        ApiErrorId.ERR_PRIVACY_ADDENDUM_MISSING,
        422,
    )

    _assert_no_price_was_filed(api, world, version)


def test_bundle_speaking_another_rostering_standard_is_refused(api):
    """PRD 2.11: "Rostering, by contrast, is an **exact** comparison: the bundle's `rostering_standard` must equal the state's, and a stronger-looking standard does not substitute for the one the state's systems actually speak."

    PRD 2.6: "When a bundle is named, its rostering standard equals the state's, else `ERR_ROSTERING_STANDARD_UNSUPPORTED` (422), on filing a price proposal."

    Design: Corner/errors/bundle_commitment_checks_each_fire_on_their_own_defect
    """
    world = _filed_submission_of_a_demanding_state(api)
    bundle_id = seed_bundle(
        api,
        world,
        component_count=3,
        accessibility_conformance=ACCESSIBILITY_WCAG_2_2_AA,
        rostering_standard=ROSTERING_ONEROSTER_1_1,
        privacy_addendum_signed=True,
    )
    version = api.read_submission_version(world.submission_id, PRICING)

    validate_error(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id, version, bundle_id=bundle_id
            ),
            PRICING,
        ),
        ApiErrorId.ERR_ROSTERING_STANDARD_UNSUPPORTED,
        422,
    )

    _assert_no_price_was_filed(api, world, version)


def test_bundle_belonging_to_another_edition_is_refused(api):
    """PRD 3.6: "When a `bundle_id` is supplied, the referenced bundle must belong to the submission's own edition, else `ERR_BUNDLE_TITLE_MISMATCH`, and must satisfy the three platform commitments of Section 2.11."

    The named bundle satisfies every platform commitment the state demands, so
    the only defect left is that it wraps a different edition.

    Design: Corner/errors/bundle_commitment_checks_each_fire_on_their_own_defect
    """
    world = _filed_submission_of_a_demanding_state(api)
    other_title = get_success_data(
        api.create_title(
            factories.title_payload(
                subject="MATH",
                grade_low=7,
                grade_high=7,
                content_tags=["RATIO_REASONING"],
            ),
            EDITOR,
        )
    )
    other_bundle = get_success_data(
        api.create_ancillary_bundle(
            other_title["id"],
            factories.ancillary_bundle_payload(
                component_count=3,
                accessibility_conformance=ACCESSIBILITY_WCAG_2_2_AA,
                rostering_standard=ROSTERING_ONEROSTER_1_2,
                privacy_addendum_signed=True,
            ),
            PRICING,
        )
    )
    version = api.read_submission_version(world.submission_id, PRICING)

    validate_error(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id, version, bundle_id=other_bundle["id"]
            ),
            PRICING,
        ),
        ApiErrorId.ERR_BUNDLE_TITLE_MISMATCH,
        422,
    )

    _assert_no_price_was_filed(api, world, version)


def test_term_longer_than_the_states_maximum_is_refused(api):
    """PRD 3.6: "The committed `term_years` may not exceed either the state's `multi_year_max_years` or the cycle's `contract_term_years` — that is, it must be at most the smaller of the two — else `ERR_TERM_YEARS_EXCEED_STATE_MAX`."

    The cycle would allow six years and the state only four, so a five-year
    commitment is refused on the state's ceiling.

    Design: Corner/errors/fiscal_ceilings_reject_long_terms_and_capped_prices
    """
    world = seed_filed_submission(
        api,
        "OR",
        subject="ELA",
        grade=8,
        standard_code="OR.E.8.1",
        state_overrides={"multi_year_max_years": 4, "price_cap_cents": 100000},
        cycle_overrides={"contract_term_years": 6},
        title_overrides={"content_tags": ["CLOSE_READING"]},
    )
    version = api.read_submission_version(world.submission_id, PRICING)

    validate_error(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id, version, term_years=5
            ),
            PRICING,
        ),
        ApiErrorId.ERR_TERM_YEARS_EXCEED_STATE_MAX,
        422,
    )

    _assert_no_price_was_filed(api, world, version)


def test_net_state_price_above_the_states_cap_is_refused(api):
    """PRD 3.6: "Once the net price is known, the state's ceiling applies: when the state's `price_cap_cents` is not null and the computed `net_state_price_cents` exceeds it, the filing is refused with `ERR_PRICE_CAP_EXCEEDED`."

    A one-year term at 200,000 cents earns no discount tier, so the net state
    price is twice the state's cap of 100,000 cents.

    Design: Corner/errors/fiscal_ceilings_reject_long_terms_and_capped_prices
    """
    world = seed_filed_submission(
        api,
        "OR",
        subject="ELA",
        grade=8,
        standard_code="OR.E.8.1",
        state_overrides={"multi_year_max_years": 4, "price_cap_cents": 100000},
        cycle_overrides={"contract_term_years": 6},
        title_overrides={"content_tags": ["CLOSE_READING"]},
    )
    version = api.read_submission_version(world.submission_id, PRICING)

    validate_error(
        api.create_pricing_proposal(
            factories.pricing_proposal_payload(
                world.submission_id,
                version,
                base_price_cents=200000,
                term_years=1,
                annual_escalator_bps=0,
                projected_adoption_units=100,
            ),
            PRICING,
        ),
        ApiErrorId.ERR_PRICE_CAP_EXCEEDED,
        422,
    )

    _assert_no_price_was_filed(api, world, version)


# ---------------------------------------------------------------------------
# The committee tally
# ---------------------------------------------------------------------------


def test_tally_below_the_panels_quorum_is_refused(api):
    """PRD 3.8: "The number of surviving ballots, abstentions included, is `counted_vote_count`. If `counted_vote_count` is below the panel's `quorum_required`, the tally is refused with `ERR_QUORUM_NOT_MET`."

    One ballot on a panel whose `quorum_required` is 2 leaves the slot
    `PRESENTED` with no outcome.

    Design: Corner/errors/tally_needs_quorum_first_then_a_countable_ballot
    """
    world = seed_presented_slot(api, "HI", subject="SCIENCE", grade=3, priced=False)
    cast_ballots(api, world.slot_id, [VOTE_ABSTAIN])

    validate_error(
        api.tally_slot(world.slot_id, world.officer),
        ApiErrorId.ERR_QUORUM_NOT_MET,
        409,
    )

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_PRESENTED
    assert slot["tally_outcome"] == TALLY_OUTCOME_PENDING
    assert slot["recommend_ratio"] is None
    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_PRESENTED


def test_tally_of_nothing_but_abstentions_has_no_countable_votes(api):
    """PRD 3.8: "The counted ballots whose `vote` is not `ABSTAIN` form the ratio denominator; if there are none — every counted member abstained — the tally is refused with `ERR_NO_COUNTABLE_VOTES`."

    Two abstentions reach the quorum of 2 yet leave the recommendation ratio
    without a denominator.

    Design: Corner/errors/tally_needs_quorum_first_then_a_countable_ballot
    """
    world = seed_presented_slot(api, "HI", subject="SCIENCE", grade=3, priced=False)
    cast_ballots(api, world.slot_id, [VOTE_ABSTAIN, VOTE_ABSTAIN])

    validate_error(
        api.tally_slot(world.slot_id, world.officer),
        ApiErrorId.ERR_NO_COUNTABLE_VOTES,
        422,
    )

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_PRESENTED
    assert slot["tally_outcome"] == TALLY_OUTCOME_PENDING
    ballots, meta = validate_paginated(api.list_votes(world.slot_id, world.officer))
    assert meta["total_count"] == 2
    assert len(ballots) == 2
