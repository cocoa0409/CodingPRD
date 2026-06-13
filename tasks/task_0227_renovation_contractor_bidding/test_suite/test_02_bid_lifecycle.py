"""Bid lifecycle: the cyclic SUBMITTED<->REVISING loop, submit-time precondition
precedence (state vs temporal, qualification vs scope-coverage), the project-open
gate, the rating floor, scope coverage, the deadline gate, and withdraw.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    create_homeowner,
    create_contractor,
    create_qualified_contractor,
    create_draft_project,
    open_project,
    create_submitted_bid,
    create_draft_bid_with_lines,
    award_bid,
    make_homeowner_headers,
    make_contractor_headers,
    create_bid_payload,
    create_bid_line_item_payload,
    AFTER_DEADLINE_ISO,
)
from test_helpers import TEST_USERS


# ───────────────────────── Cyclic revise loop ──────────────────────────────
def test_bid_revise_then_resubmit_completes_cycle(api):
    """PRD §3.3: "A submitted bid can be pulled back for editing, moving its
    `status` from `SUBMITTED` to `REVISING`; this is permitted only while the
    project is still `OPEN_FOR_BIDS` and the current clock is before the
    `bid_deadline`."
    PRD §3.3: "Re-submitting a revised bid moves it from `REVISING` back to
    `SUBMITTED` under the same open-project, before-deadline, and complete-scope-
    coverage conditions, and recomputes `total_cents` from the current set of bid
    line items."

    Design: Difficulty/non_linear_state_machine/bid_cyclic_submitted_revising_submitted_loop
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    c_headers = make_contractor_headers(contractor["id"])

    revising = validate_success(api.revise_bid(bid["id"], c_headers), 200)
    assert revising["status"] == "REVISING", revising

    resubmitted = validate_success(api.submit_bid(bid["id"], c_headers), 200)
    assert resubmitted["status"] == "SUBMITTED", resubmitted


def test_bid_total_recomputed_on_resubmit(api):
    """PRD §3.3: "Re-submitting a revised bid moves it from `REVISING` back to
    `SUBMITTED` under the same open-project, before-deadline, and complete-scope-
    coverage conditions, and recomputes `total_cents` from the current set of bid
    line items."

    The single existing line (1 * 600000) is unchanged, so the recomputed total
    stays 600000.

    Design: Difficulty/non_linear_state_machine/bid_cyclic_submitted_revising_submitted_loop
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    c_headers = make_contractor_headers(contractor["id"])

    api.revise_bid(bid["id"], c_headers)
    resubmitted = validate_success(api.submit_bid(bid["id"], c_headers), 200)
    assert resubmitted["total_cents"] == 600_000, resubmitted


# ───────────────────────── Project-open gate (Bid->Project) ────────────────
def test_submit_against_draft_project_invalid_state(api):
    """PRD §3.3: "Submitting a bid moves it from `DRAFT` to `SUBMITTED`.
    Submission is allowed only while the project is still `OPEN_FOR_BIDS` and the
    current clock is strictly before the project's `bid_deadline`."
    PRD §3.3: "then the project-state requirement that the project be
    `OPEN_FOR_BIDS` (a violation here being an invalid-state condition)."

    Design: Difficulty/cross_entity_state_dependency/bid_submit_requires_project_open_for_bids
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    # Project left in DRAFT (never opened); a complete bid line set is built.
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    bid = create_draft_bid_with_lines(project, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    c_headers = make_contractor_headers(contractor["id"])
    res = api.submit_bid(bid["id"], c_headers)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_bid(bid["id"], c_headers), 200)
    assert fetched["status"] == "DRAFT", fetched


def test_submit_succeeds_once_project_opened(api):
    """PRD §3.3: "Submitting a bid moves it from `DRAFT` to `SUBMITTED`.
    Submission is allowed only while the project is still `OPEN_FOR_BIDS` and the
    current clock is strictly before the project's `bid_deadline`."

    Positive companion: the same complete bid submits successfully once the
    project is OPEN_FOR_BIDS.

    Design: Difficulty/cross_entity_state_dependency/bid_submit_requires_project_open_for_bids
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_draft_bid_with_lines(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    c_headers = make_contractor_headers(contractor["id"])
    submitted = validate_success(api.submit_bid(bid["id"], c_headers), 200)
    assert submitted["status"] == "SUBMITTED", submitted


# ───────────────────────── Precedence: state vs temporal ───────────────────
def test_submit_awarded_bid_after_deadline_reports_invalid_state(api):
    """PRD §3.3: "These submit-time checks are evaluated in a fixed precedence so
    that the reported error is deterministic. The existence of every referenced
    resource is confirmed first, then the project-state requirement that the
    project be `OPEN_FOR_BIDS` (a violation here being an invalid-state condition),
    then the deadline check yielding `ERR_BID_DEADLINE_PASSED`."

    The bid is AWARDED and the clock is past the deadline: both the state check
    (p5) and the deadline check (p7) would fire, but the earlier state check wins.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_bid_submit
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    award_bid(opened, homeowner, bid, opened["version"])
    # Advance the clock past the bid deadline.
    set_clock(AFTER_DEADLINE_ISO)

    res = api.submit_bid(bid["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_submit_after_deadline_only_reports_deadline_passed(api):
    """PRD §3.3: "a submission attempted at or after the deadline is rejected with
    `ERR_BID_DEADLINE_PASSED`."

    Isolated temporal failure: the project is still OPEN_FOR_BIDS and the bid is a
    valid DRAFT, but the clock is past the deadline, so the deadline check fires
    on its own.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_bid_submit
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_draft_bid_with_lines(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    set_clock(AFTER_DEADLINE_ISO)

    res = api.submit_bid(bid["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_BID_DEADLINE_PASSED")


# ───────────────────────── Precedence: qualification vs scope ──────────────
def test_submit_suspended_with_incomplete_scope_reports_not_qualified(api):
    """PRD §3.3: "then the qualification check yielding
    `ERR_CONTRACTOR_NOT_QUALIFIED`, then the rating-floor check yielding
    `ERR_RATING_BELOW_MINIMUM`, and finally the scope-coverage check yielding
    `ERR_INCOMPLETE_SCOPE_COVERAGE`."
    PRD §3.3: "the contractor's `qualification_status` must be `QUALIFIED`...
    any of these three failing is reported as `ERR_CONTRACTOR_NOT_QUALIFIED`."

    A SUSPENDED contractor whose bid also fails to price every scope line: the
    earlier qualification check (p8) wins over the scope-coverage check (p10).

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_bid_submit
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[
            {"description": "Floor", "quantity": 100, "unit": "SQFT", "estimated_unit_cost_cents": 1000},
            {"description": "Cabinets", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 500_000},
        ],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    # Bid prices only one of two scope lines (incomplete).
    bid = create_draft_bid_with_lines(opened, contractor, line_specs=[(scope[0]["id"], 100, 1200)])
    # Suspend the contractor so both p8 and p10 are violated.
    get_success_data(api.suspend_contractor(contractor["id"], TEST_USERS["platform_admin_headers"]))

    res = api.submit_bid(bid["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_CONTRACTOR_NOT_QUALIFIED")


def test_submit_qualified_incomplete_scope_only_reports_scope_coverage(api):
    """PRD §3.3: "the bid must be complete: at least one bid line item must exist,
    and every scope line item of the project must be priced by exactly one bid
    line item — no scope line left unpriced and no scope line priced more than
    once. A bid that does not cover the scope exactly once is rejected with
    `ERR_INCOMPLETE_SCOPE_COVERAGE`."

    Isolated referential failure: the contractor is QUALIFIED, so the
    scope-coverage check is reached and fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_bid_submit
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[
            {"description": "A", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 300_000},
            {"description": "B", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 300_000},
        ],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_draft_bid_with_lines(opened, contractor, line_specs=[(scope[0]["id"], 1, 300_000)])

    res = api.submit_bid(bid["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_INCOMPLETE_SCOPE_COVERAGE")


# ───────────────────────── Rating floor (queue B) ──────────────────────────
def test_rating_below_minimum_blocks_submit(api):
    """PRD §3.3: "The contractor's `average_rating` must also be at least the
    project's `min_rating`, failing which submission is rejected with
    `ERR_RATING_BELOW_MINIMUM`."

    Project min_rating 4.5; a freshly qualified contractor has average_rating 0.

    Design: Corner/validations/rating_below_minimum_blocks_bid_submit
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
        min_rating=4.5,
    )
    opened = open_project(project, homeowner)
    bid = create_draft_bid_with_lines(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])

    res = api.submit_bid(bid["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_RATING_BELOW_MINIMUM")


# ───────────────────────── Scope coverage (queue B) ────────────────────────
def test_incomplete_scope_coverage_blocks_submit(api):
    """PRD §3.3: "every scope line item of the project must be priced by exactly
    one bid line item — no scope line left unpriced and no scope line priced more
    than once. A bid that does not cover the scope exactly once is rejected with
    `ERR_INCOMPLETE_SCOPE_COVERAGE`."

    Two scope lines, the bid prices only one; the contractor is QUALIFIED so the
    referential check is reached.

    Design: Corner/validations/incomplete_scope_coverage_blocks_submit
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[
            {"description": "A", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 300_000},
            {"description": "B", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 300_000},
        ],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_draft_bid_with_lines(opened, contractor, line_specs=[(scope[0]["id"], 1, 300_000)])

    res = api.submit_bid(bid["id"], make_contractor_headers(contractor["id"]))
    validate_error(res, "ERR_INCOMPLETE_SCOPE_COVERAGE")


# ───────────────────────── Withdraw then award (queue B) ───────────────────
def test_award_withdrawn_bid_invalid_state(api):
    """PRD §3.3: "A contractor may instead withdraw a submitted bid, moving its
    `status` from `SUBMITTED` to the terminal `WITHDRAWN` state, which is allowed
    as long as the project has not yet been awarded."
    PRD §3.4: "the named bid must belong to this project and be in `SUBMITTED`
    status."

    Awarding a WITHDRAWN bid is rejected because award requires SUBMITTED.

    Design: Corner/state_machines/withdraw_then_award_withdrawn_bid_invalid_state
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 500_000)])
    c_headers = make_contractor_headers(contractor["id"])
    withdrawn = validate_success(api.withdraw_bid(bid["id"], c_headers), 200)
    assert withdrawn["status"] == "WITHDRAWN", withdrawn

    res = api.award_project(
        opened["id"],
        {"bid_id": bid["id"], "expected_project_version": opened["version"]},
        make_homeowner_headers(homeowner["id"]))
    validate_error(res, "ERR_INVALID_STATE")
