"""Project creation, time-window invariants, and tender-document
publish cascade. Covers PRD §3.4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    comprehensive_scoring_evaluation_criteria,
    create_project,
    create_project_payload,
    create_published_plan_with_items,
    create_tender_document,
    create_tender_document_payload,
    lowest_price_evaluation_criteria,
    publish_tender_document,
    validate_error,
    validate_success,
)


# ===========================================================================
# Project creation requires PUBLISHED plan_item
# ===========================================================================
def test_create_project_against_unpublished_plan_item_rejected(
    api, officer_headers,
):
    """PRD §3.4: "A project is created against a PlanItem whose
    item_status is PUBLISHED; an attempt to create against any other
    item status yields ERR_PLAN_ITEM_NOT_PUBLISHED."
    """
    from test_helpers import (
        add_plan_item, create_draft_plan, submit_plan_for_review,
    )
    plan = create_draft_plan()
    item = add_plan_item(plan["id"])  # status = PROPOSED
    submit_plan_for_review(plan["id"])  # still PROPOSED
    res = api.create_project(
        create_project_payload(plan_item_id=item["id"]),
        officer_headers,
    )
    validate_error(res, "ERR_PLAN_ITEM_NOT_PUBLISHED")


def test_create_project_against_published_plan_item_succeeds(
    api, officer_headers,
):
    """PRD §3.4: same sentence — PUBLISHED plan_item enables creation.
    PRD §3.4: "The project enters its DRAFT status."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    res = api.create_project(
        create_project_payload(plan_item_id=items[0]["id"]),
        officer_headers,
    )
    data = validate_success(res, 201)
    assert data["project_status"] == "DRAFT"


# ===========================================================================
# Project time-window invariant (priority 11)
# ===========================================================================
@pytest.mark.parametrize(
    "qwc,bsd,bo,label",
    [
        # query_window_close_at NOT strictly before bid_submission_deadline
        ("2026-02-15T00:00:00.000Z", "2026-02-15T00:00:00.000Z",
         "2026-02-16T00:00:00.000Z", "qwc == bsd"),
        ("2026-02-16T00:00:00.000Z", "2026-02-15T00:00:00.000Z",
         "2026-02-17T00:00:00.000Z", "qwc > bsd"),
        # bid_opening_at NOT strictly after bid_submission_deadline
        ("2026-02-14T00:00:00.000Z", "2026-02-15T00:00:00.000Z",
         "2026-02-15T00:00:00.000Z", "bo == bsd"),
        ("2026-02-14T00:00:00.000Z", "2026-02-15T00:00:00.000Z",
         "2026-02-14T00:00:00.000Z", "bo < bsd"),
    ],
)
def test_project_time_window_invariant_rejects_bad_orderings(
    api, officer_headers, qwc, bsd, bo, label,
):
    """PRD §3.4: "query_window_close_at must lie strictly before
    bid_submission_deadline, and bid_opening_at must lie strictly after
    bid_submission_deadline. A project create or update that violates
    this invariant is rejected with ERR_INVALID_TIME_WINDOW."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    res = api.create_project(
        create_project_payload(
            plan_item_id=items[0]["id"],
            bid_submission_deadline=bsd,
            query_window_close_at=qwc,
            bid_opening_at=bo,
        ),
        officer_headers,
    )
    validate_error(res, "ERR_INVALID_TIME_WINDOW")


def test_project_time_window_invariant_accepts_strict_ordering(
    api, officer_headers,
):
    """PRD §3.4: "query_window_close_at must lie strictly before
    bid_submission_deadline, and bid_opening_at must lie strictly after
    bid_submission_deadline."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    res = api.create_project(
        create_project_payload(
            plan_item_id=items[0]["id"],
            query_window_close_at="2026-02-14T00:00:00.000Z",
            bid_submission_deadline="2026-02-15T00:00:00.000Z",
            bid_opening_at="2026-02-16T00:00:00.000Z",
        ),
        officer_headers,
    )
    validate_success(res, 201)


def test_estimated_value_must_be_positive(api, officer_headers):
    """PRD §3.4: "a strictly positive estimated_value_cents (the price
    ceiling)."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    res = api.create_project(
        create_project_payload(
            plan_item_id=items[0]["id"],
            estimated_value_cents=0,
        ),
        officer_headers,
    )
    assert 400 <= res.status_code < 500


# ===========================================================================
# Tender document creation
# ===========================================================================
def test_create_tender_document_starts_draft_at_version_1(
    api, officer_headers,
):
    """PRD §3.4: "The document enters DRAFT with a domain-level
    version of 1."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    proj = create_project(plan_item_id=items[0]["id"])
    res = api.create_tender_document(
        proj["id"],
        create_tender_document_payload(),
        officer_headers,
    )
    data = validate_success(res, 201)
    assert data["doc_status"] == "DRAFT"
    assert data["version"] == 1


@pytest.mark.parametrize(
    "weights,label",
    [
        ({"weight_price": 0.50, "weight_technical": 0.40,
          "weight_qualification": 0.20, "max_technical_score": 100,
          "max_qualification_score": 100}, "sum > 1"),
        ({"weight_price": 0.30, "weight_technical": 0.30,
          "weight_qualification": 0.30, "max_technical_score": 100,
          "max_qualification_score": 100}, "sum < 1"),
        ({"weight_price": 0.0, "weight_technical": 0.50,
          "weight_qualification": 0.50, "max_technical_score": 100,
          "max_qualification_score": 100}, "weight=0 (closed left)"),
        ({"weight_price": 1.0, "weight_technical": 0.0,
          "weight_qualification": 0.0, "max_technical_score": 100,
          "max_qualification_score": 100}, "weight=1 (closed right)"),
    ],
)
def test_weights_invalid_at_create_tender_document(
    api, officer_headers, weights, label,
):
    """PRD §3.4: "three weights — weight_price, weight_technical,
    weight_qualification — each strictly between 0 and 1, exclusive on
    both ends, and summing to one within a tolerance of EPSILON (1e-9)
    ... A weight set that fails either the sum-tolerance or the
    per-weight range check is rejected with ERR_WEIGHTS_INVALID both at
    tender create time and at the document's later publish step."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    proj = create_project(
        plan_item_id=items[0]["id"],
        evaluation_method="COMPREHENSIVE_SCORING",
    )
    res = api.create_tender_document(
        proj["id"],
        create_tender_document_payload(evaluation_criteria=weights),
        officer_headers,
    )
    validate_error(res, "ERR_WEIGHTS_INVALID")


def test_publish_tender_cascades_project_to_prescreen_open(
    api, officer_headers,
):
    """PRD §3.4: "Publishing the document, transitioning the tender from
    DRAFT → PUBLISHED, has three side effects: pinned_at is set to the
    server clock's current_time; qualification_requirements is
    snapshotted from the project's required_qualifications and pinned
    onto the document; and the project advances from
    DRAFT → PRESCREEN_OPEN."
    """
    _plan, items = create_published_plan_with_items(num_items=1)
    proj = create_project(
        plan_item_id=items[0]["id"],
        required_qualifications=["Q1", "Q2"],
    )
    tender = create_tender_document(proj["id"])
    advance_clock("2026-01-15T00:00:00.000Z")
    res = api.publish_tender_document(tender["id"], officer_headers)
    td = validate_success(res)
    assert td["doc_status"] == "PUBLISHED"
    assert td.get("pinned_at") is not None
    assert sorted(td.get("qualification_requirements", [])) == ["Q1", "Q2"]
    # Verify the project advanced.
    proj_res = api.get_project(proj["id"], officer_headers)
    proj_data = validate_success(proj_res)
    assert proj_data["project_status"] == "PRESCREEN_OPEN"
