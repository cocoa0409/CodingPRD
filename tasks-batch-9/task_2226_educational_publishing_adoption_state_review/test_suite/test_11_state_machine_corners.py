"""State-machine corners of the adoption-review contract.

Each test here walks one lifecycle transition of the contract - a panel's birth,
an edition's release, a content edit's terminal revert, a draft submission's
abandonment, a hearing's close-out, a revision plan's cancellation and a public
comment's late answer - and pins the observable record the PRD promises.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    factories,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    COMMENT_CATEGORY_ERROR_OF_FACT,
    COMMENT_STATUS_RESPONDED,
    CONTENT_EDIT_STATUS_REVERTED,
    CYCLE_STATUS_CLOSED_FOR_SUBMISSION,
    EDIT_TYPE_REGIONAL_SUBSTITUTION,
    PANEL_STATUS_CLOSED,
    PANEL_STATUS_SCHEDULED,
    REVIEW_STATUS_FILED,
    REVIEW_STATUS_WITHDRAWN,
    SEVERITY_CRITICAL,
    SLOT_STATUS_NO_SHOW,
    TALLY_OUTCOME_PENDING,
    TITLE_STATUS_ACTIVE,
    TITLE_STATUS_DRAFT,
    WITHDRAW_REASON_ABANDON,
)
from test_helpers.assertions import (
    assert_page_budget_conserved,
    assert_print_unit_ledger_balances,
)
from test_helpers.fixtures import (
    CLOCK_AT_PANEL_SESSION_START,
    DIRECTOR,
    EDITOR,
    advance_phase,
    advance_to_in_review,
    approve_content_edit,
    open_session,
    propose_content_edit,
    seed_cycle,
    seed_draft_submission,
    seed_filed_submission,
    seed_scheduled_submission,
    seed_standard,
    seed_state,
    seed_title,
    set_clock,
    stack_public_comments,
)


# ---------------------------------------------------------------------------
# Committee panels
# ---------------------------------------------------------------------------


def test_a_panel_seated_without_a_buffer_or_a_capacity_starts_on_the_stated_defaults(api):
    """PRD 3.8: "The panel names its `cycle_id`, a `panel_label` of 1 to 60 characters, a `session_start_at` and a `session_end_at` that must be strictly after it, a `buffer_minutes` between 0 and 60 inclusive that defaults to 10 and states the mandatory turnover gap between two consecutive presentations, a `member_count` between 1 and 25 inclusive giving the number of seated members, and a `quorum_required` between 1 and `member_count` inclusive giving the minimum counted votes needed before a slot may be tallied."

    PRD 3.8: "When the field is omitted it defaults to the whole number of minutes between `session_start_at` and `session_end_at`; when supplied it must be at least 1 and at most that same whole-minute session length, and a value above the session length is refused with `ERR_INVALID_REQUEST`."

    PRD 3.8: "Panels are born `SCHEDULED` with `reserved_minutes` at 0."

    PRD 2.4: "Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record — and `version`, an integer that starts at 1 on creation and increments by 1 on every mutation."

    PRD 4: "Operations that mint a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`."

    Design: Corner/state_machines/panel_initial_state_defaults_buffer_and_capacity
    """
    world = seed_state(api, "WY")
    cycle_id = seed_cycle(api, world, subject="MATH", cycle_year=2027)

    response = api.create_committee_panel(
        factories.committee_panel_payload(
            cycle_id,
            panel_label="WY MATH Panel A",
            session_start_at="2026-10-20T14:00:00Z",
            session_end_at="2026-10-20T18:00:00Z",
            member_count=3,
            quorum_required=2,
            buffer_minutes=None,
        ),
        world.officer,
    )
    panel = validate_success(response, expected_status=201)

    assert panel["status"] == PANEL_STATUS_SCHEDULED
    assert panel["buffer_minutes"] == 10
    # The four-hour sitting is 240 whole minutes long.
    assert panel["slot_minutes_capacity"] == 240
    assert panel["reserved_minutes"] == 0
    assert panel["version"] == 1

    panels, meta = validate_paginated(api.list_cycle_panels(cycle_id, world.officer))
    assert meta["total_count"] == 1
    assert [record["id"] for record in panels] == [panel["id"]]


def test_closing_a_session_marks_a_still_reserved_slot_a_no_show(api):
    """PRD 3.8: "Closing a panel session moves the panel from `IN_SESSION` to `CLOSED`, its terminal state, and is refused with `ERR_PRESENTATION_SLOT_STATE_INVALID` while any slot of the panel is still `PRESENTED` — a submission that was heard must be tallied before the hearing can be closed out. On close, every slot still `RESERVED` moves to `NO_SHOW`, and each affected submission whose remaining slots include none in `RESERVED`, `PRESENTED` or `TALLIED` moves its `review_status` from `SCHEDULED` back to `FILED`, decrementing its cycle's `scheduled_submission_count`. Unlike a cancellation, a no-show leaves the panel's `reserved_minutes` **unchanged**: the minutes were spent whether or not the publisher showed up."

    PRD 3.8: "The slot's `panel_id` comes from the path, its `status` starts at `RESERVED`, its `tally_outcome` starts at `PENDING`, its `recommend_ratio` starts null, its `counted_vote_count` starts at 0, and its `duration_minutes` is computed as the whole number of minutes between `start_at` and `end_at`."

    PRD 3.1: "`submission_count` is the number of the cycle's submissions whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`."

    Design: Corner/state_machines/panel_close_session_marks_reserved_slot_no_show
    """
    world = seed_scheduled_submission(api, "OK", subject="MATH", grade=7)
    advance_to_in_review(api, world)
    set_clock(api, CLOCK_AT_PANEL_SESSION_START)
    open_session(api, world)

    panel = validate_success(api.close_panel_session(world.panel_id, world.officer))

    assert panel["status"] == PANEL_STATUS_CLOSED
    # The half-hour window was never presented, so its minutes stay spent.
    assert panel["reserved_minutes"] == 30

    slot = validate_success(api.get_presentation_slot(world.slot_id, world.officer))
    assert slot["status"] == SLOT_STATUS_NO_SHOW
    assert slot["tally_outcome"] == TALLY_OUTCOME_PENDING

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_FILED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 0
    assert cycle["submission_count"] == 1


# ---------------------------------------------------------------------------
# The catalog: releasing and re-planning an edition
# ---------------------------------------------------------------------------


def test_releasing_an_edition_that_is_already_active_is_refused(api):
    """PRD 3.2: "A `PublisherEditor` releases a `DRAFT` edition, moving `status` from `DRAFT` to `ACTIVE` and optionally recording a `note` for the catalog record."

    PRD 2.6: "The addressed title's `status` admits the operation, else `ERR_TITLE_STATE_INVALID` (409) — release requires `DRAFT`; revision-plan actions require `ACTIVE` or `REVISION_PLANNED`."

    PRD 3.2: "On creation, `page_budget_remaining` is set to `signature_page_capacity` minus `page_count`, `content_revision` is set to 1, every inventory counter is set to 0, and `status` is `DRAFT`."

    Design: Corner/state_machines/release_an_already_active_title_is_not_idempotent
    """
    title = get_success_data(
        api.create_title(
            factories.title_payload(
                subject="MATH",
                grade_low=6,
                grade_high=6,
                content_tags=["RATIO_REASONING"],
                page_count=300,
                signature_page_capacity=384,
                list_price_cents=8900,
            ),
            EDITOR,
        )
    )
    title_id = title["id"]
    released = get_success_data(
        api.release_title(title_id, EDITOR, {"note": "First release."})
    )
    assert released["status"] == TITLE_STATUS_ACTIVE

    response = api.release_title(
        title_id, EDITOR, {"note": "Duplicate release attempt."}
    )
    validate_error(response, ApiErrorId.ERR_TITLE_STATE_INVALID)

    after = validate_success(api.get_title(title_id, EDITOR))
    assert after["status"] == TITLE_STATUS_ACTIVE
    # The refused second release re-ran no side effect of the first one.
    assert after["content_revision"] == 1


def test_releasing_an_edition_that_declares_no_content_is_refused(api):
    """PRD 3.2: "Release is refused with `ERR_TITLE_NOT_RELEASABLE` when `content_tags` is empty, since an edition with no declared content cannot be correlated to any framework, and refused with `ERR_PAGE_BUDGET_EXCEEDED` when `page_count` exceeds `signature_page_capacity`."

    PRD 3.2: "On creation, `page_budget_remaining` is set to `signature_page_capacity` minus `page_count`, `content_revision` is set to 1, every inventory counter is set to 0, and `status` is `DRAFT`."

    Design: Corner/state_machines/release_title_without_content_tags_rejected
    """
    title = get_success_data(
        api.create_title(
            factories.title_payload(
                subject="SCIENCE",
                grade_low=8,
                grade_high=8,
                content_tags=None,
                page_count=320,
                signature_page_capacity=384,
                list_price_cents=9200,
            ),
            EDITOR,
        )
    )
    title_id = title["id"]
    assert title["content_tags"] == []

    response = api.release_title(title_id, EDITOR)
    validate_error(response, ApiErrorId.ERR_TITLE_NOT_RELEASABLE)

    after = validate_success(api.get_title(title_id, EDITOR))
    assert after["status"] == TITLE_STATUS_DRAFT
    assert after["content_tags"] == []


def test_cancelling_a_revision_plan_returns_the_edition_to_active(api):
    """PRD 3.2: "`PLAN` moves the edition from `ACTIVE` to `REVISION_PLANNED` and records `revision_target_cycle_year`, the adoption year the next edition is being planned against; the field is required for this action and its absence is an `ERR_INVALID_REQUEST`."

    PRD 3.2: "`CANCEL_PLAN` moves the edition from `REVISION_PLANNED` back to `ACTIVE` and resets `revision_target_cycle_year` to null; the cycle `ACTIVE → REVISION_PLANNED → ACTIVE` may be walked any number of times."

    PRD 3.2: "An `adjustment_type` of `RECEIPT` adds the units to both `total_received_units` and `on_hand_units`; an `adjustment_type` of `WRITE_OFF` subtracts them from `on_hand_units` and adds them to `written_off_units`, and is refused with `ERR_INSUFFICIENT_PRINT_INVENTORY` when `on_hand_units` is below the requested `units`."

    PRD 2.10: "The **print-unit ledger** of a title states that `total_received_units` always equals the sum of `on_hand_units`, `committed_units`, `sample_reserved_units`, `fulfilled_units` and `written_off_units`."

    Design: Corner/state_machines/revision_plan_cancel_returns_title_to_active
    """
    world = seed_state(api, "NH")
    title_id = seed_title(
        api,
        world,
        release=True,
        receipt_units=300,
        subject="SCIENCE",
        grade_low=5,
        grade_high=5,
        copyright_year=2025,
        content_tags=["LAB_SAFETY"],
        page_count=300,
        signature_page_capacity=384,
        list_price_cents=8900,
    )

    planned = get_success_data(
        api.revision_plan(
            title_id,
            {"action": "PLAN", "revision_target_cycle_year": 2029},
            DIRECTOR,
        )
    )
    assert planned["revision_target_cycle_year"] == 2029

    cancelled = validate_success(
        api.revision_plan(title_id, {"action": "CANCEL_PLAN"}, DIRECTOR)
    )

    assert cancelled["status"] == TITLE_STATUS_ACTIVE
    assert cancelled["revision_target_cycle_year"] is None
    # Walking the plan out and back again moves no print units.
    assert cancelled["total_received_units"] == 300
    assert cancelled["on_hand_units"] == 300
    assert cancelled["written_off_units"] == 0
    assert_print_unit_ledger_balances(cancelled)


# ---------------------------------------------------------------------------
# Content edits
# ---------------------------------------------------------------------------


def test_a_reverted_content_edit_can_never_be_applied_again(api):
    """PRD 3.3: "An accepted revert moves the edit from `APPLIED` to `REVERTED`, its terminal state, decreases `page_count` by `pages_delta` and increases `page_budget_remaining` by `pages_delta`, restoring the signature identity, and undoes the `content_tags` change the apply made."

    PRD 3.3: "Crucially, the revert **also** increases `content_revision` by 1 rather than restoring the previous number: revision numbers are strictly monotonic, so a revert never un-stales a submission that pinned a revision before the apply."

    PRD 2.6: "The addressed content edit's `status` admits the operation, else `ERR_CONTENT_EDIT_STATE_INVALID` (409) — review requires `PROPOSED`, resubmit requires `REJECTED`, apply requires `APPROVED`, revert requires `APPLIED`."

    Design: Corner/state_machines/apply_a_reverted_content_edit_is_locked_out
    """
    world = seed_state(api, "LA")
    title_id = seed_title(
        api,
        world,
        release=True,
        subject="MATH",
        grade_low=4,
        grade_high=4,
        content_tags=["NUMBER_SENSE"],
        page_count=300,
        signature_page_capacity=384,
        list_price_cents=8800,
    )
    edit_id = propose_content_edit(
        api,
        world,
        topic_code="GULF_COAST_CASE_STUDY",
        pages_delta=20,
        edit_type=EDIT_TYPE_REGIONAL_SUBSTITUTION,
        rationale="Swaps the regional case study for a Gulf Coast example.",
    )
    approve_content_edit(api, world, edit_id)
    get_success_data(api.apply_content_edit(edit_id, DIRECTOR))
    reverted = get_success_data(
        api.revert_content_edit(
            edit_id,
            {"reason": "The substitution ships in the next edition instead."},
            DIRECTOR,
        )
    )
    assert reverted["status"] == CONTENT_EDIT_STATUS_REVERTED

    response = api.apply_content_edit(edit_id, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_CONTENT_EDIT_STATE_INVALID)

    edit = validate_success(api.get_content_edit(edit_id, DIRECTOR))
    assert edit["status"] == CONTENT_EDIT_STATUS_REVERTED

    title = validate_success(api.get_title(title_id, EDITOR))
    assert title["page_count"] == 300
    assert title["page_budget_remaining"] == 84
    # One apply and one revert, each monotonically bumping the revision number.
    assert title["content_revision"] == 3
    assert_page_budget_conserved(title)


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def test_abandoning_a_draft_submission_makes_it_read_only(api):
    """PRD 3.5: "A `reason` of `ABANDON` is available only while the submission is `DRAFT`, else `ERR_SUBMISSION_STATE_INVALID`, and moves `review_status` to `WITHDRAWN`, a terminal state: a withdrawn submission is read-only, and subsequent attempts to add correlations, ship samples or file against it are all refused with `ERR_SUBMISSION_STATE_INVALID`."

    PRD 3.1: "`submission_count` is the number of the cycle's submissions whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`."

    Design: Corner/state_machines/withdraw_abandon_makes_draft_submission_read_only
    """
    world = seed_state(api, "AR")
    seed_standard(
        api, world, "AR.E.3.1", subject="ELA", grade_low=3, grade_high=3, weight=2
    )
    seed_cycle(api, world, subject="ELA", cycle_year=2027)
    seed_title(
        api,
        world,
        release=True,
        subject="ELA",
        grade_low=3,
        grade_high=3,
        content_tags=["PHONICS"],
        page_count=280,
        signature_page_capacity=384,
        list_price_cents=8500,
    )
    submission_id = seed_draft_submission(api, world)

    withdrawn = validate_success(
        api.withdraw_submission(
            submission_id, {"reason": WITHDRAW_REASON_ABANDON}, EDITOR
        )
    )
    assert withdrawn["review_status"] == REVIEW_STATUS_WITHDRAWN

    response = api.create_correlation(
        submission_id,
        factories.correlation_payload(
            "AR.E.3.1",
            depth_level="PRACTICE",
            page_reference="pp. 41-44",
            evidence_citation=(
                "An additional practice set was located after withdrawal."
            ),
        ),
        EDITOR,
    )
    validate_error(response, ApiErrorId.ERR_SUBMISSION_STATE_INVALID)

    entries, meta = validate_paginated(api.list_correlations(submission_id, EDITOR))
    assert meta["total_count"] == 1
    assert len(entries) == 1

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 0


# ---------------------------------------------------------------------------
# Public comment
# ---------------------------------------------------------------------------


def test_answering_an_escalated_comment_clears_the_critical_count_but_keeps_the_overdue_one(
    api,
):
    """PRD 3.7: "The response is accepted from either `OPEN` or `ESCALATED`, moves the comment's `status` to `RESPONDED` — the terminal state — and sets `responded_at` to the logical clock."

    PRD 3.7: "Answering from `OPEN` sets `was_overdue_at_response` to true when the comment had already escalated or when the logical clock stands at or after `response_due_at`, and to false otherwise; answering from `ESCALATED` leaves `was_overdue_at_response` true, since the lateness is already a matter of record."

    PRD 3.7: "Answering an `OPEN` comment recomputes `unresolved_critical_count`, `overdue_response_count`, `compliance_score` and `adoption_blocked`; answering an `ESCALATED` comment decrements `unresolved_critical_count` when the comment's `severity` is `CRITICAL`, leaves `overdue_response_count` unchanged — the escalation is already counted there — and recomputes `compliance_score` and `adoption_blocked`."

    PRD 3.7: "`overdue_response_count` is the number whose `status` is `ESCALATED`, plus the number whose `status` is `RESPONDED` and whose `was_overdue_at_response` is true."

    PRD 3.7: "The score itself starts at 100 and is docked for each defect: 25 points for every prohibited-tag hit, 10 points for every missing required topic, 15 points for every unresolved critical comment, and 5 points for every overdue response."

    PRD 3.7: "Finally, `adoption_blocked` is true when any of three conditions holds: `compliance_score` is strictly below 70, or `prohibited_hit_count` is greater than 0, or `content_pin_stale` is true."

    Design: Corner/state_machines/escalated_comment_response_clears_critical_count_but_keeps_overdue
    """
    world = seed_filed_submission(
        api,
        "NC",
        subject="SOCIAL_STUDIES",
        grade=5,
        state_overrides={"comment_response_days": 10},
        title_overrides={"content_tags": ["PRIMARY_SOURCES"]},
    )
    # Filed at 2026-09-15, so the critical comment falls due 2026-09-25.
    comment_id = stack_public_comments(
        api,
        world,
        [SEVERITY_CRITICAL],
        categories=[COMMENT_CATEGORY_ERROR_OF_FACT],
    )[0]

    # The first advance past the deadline escalates the unanswered comment.
    set_clock(api, "2026-10-01T00:00:00Z")
    advance_phase(api, world)

    comment = validate_success(
        api.respond_to_public_comment(
            comment_id, factories.comment_response_payload(), EDITOR
        )
    )

    assert comment["status"] == COMMENT_STATUS_RESPONDED
    assert comment["responded_at"][:19] == "2026-10-01T00:00:00"
    assert comment["was_overdue_at_response"] is True

    submission = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert submission["unresolved_critical_count"] == 0
    # The escalation is already counted, so the overdue tally holds at one.
    assert submission["overdue_response_count"] == 1
    assert submission["compliance_score"] == 95
    assert submission["adoption_blocked"] is False

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["status"] == CYCLE_STATUS_CLOSED_FOR_SUBMISSION
