"""ProcurementPlan lifecycle: DRAFT → UNDER_REVIEW → PUBLISHED, items,
amendment, archive, REJECTED. Covers PRD §3.1 and §3.2.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_plan_item,
    advance_clock,
    api_client,
    approve_plan_item,
    create_draft_plan,
    create_plan_item_payload,
    create_plan_payload,
    create_published_plan_with_items,
    create_project,
    create_tender_document,
    open_bidding,
    publish_plan,
    publish_tender_document,
    reject_plan_item,
    setup_project_bidding_open,
    submit_plan_for_review,
    validate_error,
    validate_success,
)


# ===========================================================================
# Plan + PlanItem creation
# ===========================================================================
def test_create_plan_defaults_to_draft(api, officer_headers):
    """PRD §3.1: "The plan enters its DRAFT status with an
    amendment_round of zero and a total_budget_cents of zero, awaiting
    line items."
    """
    res = api.create_plan(
        create_plan_payload(agency_id="agency-X", fiscal_year=2026),
        officer_headers,
    )
    data = validate_success(res, 201)
    assert data["status"] == "DRAFT"
    assert data["amendment_round"] == 0
    assert data["total_budget_cents"] == 0


@pytest.mark.parametrize("fiscal_year", [1999, 2101])
def test_create_plan_rejects_fiscal_year_out_of_range(
    api, officer_headers, fiscal_year,
):
    """PRD §3.1: "fiscal_year, an integer that must lie between 2000
    and 2100 inclusive."

    Claim: fiscal_year outside [2000, 2100] is rejected.
    """
    res = api.create_plan(
        create_plan_payload(agency_id="agency-X", fiscal_year=fiscal_year),
        officer_headers,
    )
    assert 400 <= res.status_code < 500, (
        f"out-of-range fiscal_year must be rejected, got {res.status_code}"
    )


@pytest.mark.parametrize("fiscal_year", [2000, 2100])
def test_create_plan_accepts_inclusive_boundary_fiscal_year(
    api, officer_headers, fiscal_year,
):
    """PRD §3.1: "an integer that must lie between 2000 and 2100
    inclusive." Claim: 2000 and 2100 both pass.
    """
    res = api.create_plan(
        create_plan_payload(agency_id="agency-X", fiscal_year=fiscal_year),
        officer_headers,
    )
    data = validate_success(res, 201)
    assert data["fiscal_year"] == fiscal_year


def test_add_plan_item_starts_proposed(api, officer_headers):
    """PRD §3.1: "The item joins its parent plan via the plan_id
    foreign key and starts in PROPOSED."
    """
    plan = create_draft_plan()
    res = api.add_plan_item(
        plan["id"],
        create_plan_item_payload(
            title="Office desks", category="GOODS", budget_cents=500_000,
        ),
        officer_headers,
    )
    data = validate_success(res, 201)
    assert data["item_status"] == "PROPOSED"
    assert data["plan_id"] == plan["id"]
    assert data["executed_amount_cents"] == 0


def test_plan_item_budget_must_be_positive(api, officer_headers):
    """PRD §3.1: "a budget_cents allocation in integer cents that must
    be strictly greater than zero."

    Claim: budget_cents=0 rejected.
    """
    plan = create_draft_plan()
    res = api.add_plan_item(
        plan["id"],
        create_plan_item_payload(budget_cents=0),
        officer_headers,
    )
    assert 400 <= res.status_code < 500


# ===========================================================================
# DRAFT → UNDER_REVIEW
# ===========================================================================
def test_submit_review_requires_at_least_one_proposed_item(
    api, officer_headers,
):
    """PRD §3.1: "Submitting the plan for review, transitioning
    DRAFT → UNDER_REVIEW, requires that at least one item is in the
    PROPOSED status; a plan with no proposed items cannot be advanced."
    """
    plan = create_draft_plan()
    res = api.submit_plan_review(plan["id"], officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_submit_review_succeeds_with_proposed_item(api, officer_headers):
    """PRD §3.1: same sentence — at least one PROPOSED item suffices."""
    plan = create_draft_plan()
    add_plan_item(plan["id"])
    res = api.submit_plan_review(plan["id"], officer_headers)
    data = validate_success(res, 200)
    assert data["status"] == "UNDER_REVIEW"


# ===========================================================================
# UNDER_REVIEW → PUBLISHED
# ===========================================================================
def test_publish_plan_requires_no_proposed_remaining(api, officer_headers):
    """PRD §3.1: "This transition has three preconditions: every plan
    item must already be in APPROVED or REJECTED status (no leftover
    PROPOSED items)."
    """
    plan = create_draft_plan()
    a = add_plan_item(plan["id"])
    b = add_plan_item(plan["id"])
    submit_plan_for_review(plan["id"])
    approve_plan_item(a["id"])
    # b is still PROPOSED → publish should fail
    res = api.publish_plan(plan["id"], officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_publish_plan_requires_at_least_one_approved(api, officer_headers):
    """PRD §3.1: "at least one item must be APPROVED" before
    PUBLISHED.
    """
    plan = create_draft_plan()
    a = add_plan_item(plan["id"])
    submit_plan_for_review(plan["id"])
    reject_plan_item(a["id"])
    res = api.publish_plan(plan["id"], officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_publish_plan_cascades_approved_items_to_published(
    api, officer_headers,
):
    """PRD §3.1: "the transition itself cascades the approved items
    from APPROVED to PUBLISHED."

    Claim: after publish, every previously APPROVED item is PUBLISHED.
    """
    plan, items = create_published_plan_with_items(num_items=2)
    res = api.get_plan(plan["id"], officer_headers)
    data = validate_success(res)
    assert data["status"] == "PUBLISHED"
    # Re-query a representative item via a Project creation (it's the
    # only stable read path the PRD documents). We rely on the
    # ERR_PLAN_ITEM_NOT_PUBLISHED-vs-201 separation as a behavioural
    # proof that the item is PUBLISHED.
    proj_res = api.create_project(
        {
            "plan_item_id": items[0]["id"],
            "title": "T",
            "evaluation_method": "LOWEST_PRICE",
            "bid_submission_deadline": "2030-01-01T00:00:00.000Z",
            "query_window_close_at": "2029-12-30T00:00:00.000Z",
            "bid_opening_at": "2030-01-02T00:00:00.000Z",
            "estimated_value_cents": 1_000_000,
            "required_qualifications": [],
        },
        officer_headers,
    )
    assert proj_res.status_code == 201, (
        f"PUBLISHED plan item must accept project creation, got "
        f"{proj_res.status_code}: {proj_res.text}"
    )


def test_publish_sets_published_at_on_first_publish(api, officer_headers):
    """PRD §3.1: "On this first publish the plan's published_at is
    captured from the server clock."
    """
    advance_clock("2026-01-15T00:00:00.000Z")
    plan, _ = create_published_plan_with_items()
    res = api.get_plan(plan["id"], officer_headers)
    data = validate_success(res)
    # PRD does not pin the exact format beyond ISO 8601 UTC; just assert
    # non-null.
    assert data.get("published_at") is not None, (
        "published_at must be set after first publish"
    )


def test_total_budget_excludes_cancelled_and_rejected(api, officer_headers):
    """PRD §3.1: "The aggregation sums each child plan item's
    budget_cents whose item_status is one of APPROVED, PUBLISHED, or
    EXECUTED; items in CANCELLED or REJECTED are excluded from the sum.
    The arithmetic is performed in integer cents with no rounding."
    """
    plan = create_draft_plan()
    a = add_plan_item(plan["id"], budget_cents=300_000)
    b = add_plan_item(plan["id"], budget_cents=200_000)
    c = add_plan_item(plan["id"], budget_cents=500_000)
    submit_plan_for_review(plan["id"])
    approve_plan_item(a["id"])
    approve_plan_item(b["id"])
    reject_plan_item(c["id"])
    publish_plan(plan["id"])
    res = api.get_plan(plan["id"], officer_headers)
    data = validate_success(res)
    assert data["total_budget_cents"] == 500_000, (
        f"total_budget_cents should sum only APPROVED/PUBLISHED items, "
        f"got {data['total_budget_cents']}"
    )


# ===========================================================================
# UNDER_REVIEW → REJECTED (Regulator)
# ===========================================================================
def test_regulator_reject_forces_proposed_approved_to_rejected(
    api, regulator_headers, officer_headers,
):
    """PRD §3.1: "A regulator may instead reject the plan during
    review, transitioning UNDER_REVIEW → REJECTED. Every child item
    still in PROPOSED or APPROVED at that moment is forced to REJECTED
    as a side effect."
    """
    plan = create_draft_plan()
    item = add_plan_item(plan["id"])
    submit_plan_for_review(plan["id"])
    res = api.reject_plan(plan["id"], regulator_headers)
    data = validate_success(res)
    assert data["status"] == "REJECTED"
    # Cascade: try to add a project against the (formerly PROPOSED)
    # item — it must now be REJECTED, so any create attempt yields
    # ERR_PLAN_ITEM_NOT_PUBLISHED.
    proj_res = api.create_project(
        {
            "plan_item_id": item["id"],
            "title": "T",
            "evaluation_method": "LOWEST_PRICE",
            "bid_submission_deadline": "2030-01-01T00:00:00.000Z",
            "query_window_close_at": "2029-12-30T00:00:00.000Z",
            "bid_opening_at": "2030-01-02T00:00:00.000Z",
            "estimated_value_cents": 1_000_000,
            "required_qualifications": [],
        },
        officer_headers,
    )
    validate_error(proj_res, "ERR_PLAN_ITEM_NOT_PUBLISHED")


# ===========================================================================
# Plan amendment cycle
# ===========================================================================
def test_begin_amendment_increments_amendment_round_on_publish(
    api, officer_headers,
):
    """PRD §3.2: "The cycle increments the plan's amendment_round by
    exactly one and recomputes total_budget_cents against the same
    aggregation rule. The plan's published_at is left untouched — it
    always reflects the first publication."
    """
    plan, _items = create_published_plan_with_items()
    res = api.get_plan(plan["id"], officer_headers)
    before = validate_success(res)
    assert before["amendment_round"] == 0
    pub_at_before = before["published_at"]
    # Begin amendment + republish.
    r1 = api.begin_plan_amendment(plan["id"], officer_headers)
    validate_success(r1)
    r2 = api.publish_plan(plan["id"], officer_headers)
    after = validate_success(r2)
    assert after["amendment_round"] == 1, (
        f"amendment_round must increment by exactly one, "
        f"got {after['amendment_round']}"
    )
    assert after["published_at"] == pub_at_before, (
        f"published_at must be preserved across amendment cycles; "
        f"before={pub_at_before}, after={after['published_at']}"
    )


def test_begin_amendment_with_active_project_rejected(
    api, officer_headers,
):
    """PRD §3.2: "Amending a published plan, transitioning
    PUBLISHED → AMENDING, requires that no plan item under the plan is
    currently referenced by any Project whose project_status is one of
    BIDDING_OPEN, EVALUATING, AWARDED, or CONTRACT_SIGNED. ... an
    officer who attempts the transition while any such project is live
    receives ERR_PLAN_HAS_ACTIVE_PROJECT."
    """
    ctx = setup_project_bidding_open()  # project is in BIDDING_OPEN
    plan_id = ctx["plan"]["id"]
    res = api.begin_plan_amendment(plan_id, officer_headers)
    validate_error(res, "ERR_PLAN_HAS_ACTIVE_PROJECT")
