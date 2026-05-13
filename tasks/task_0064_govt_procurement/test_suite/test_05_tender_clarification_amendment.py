"""Tender clarification and amendment cycles, plus version increment
and bid-withdrawal cascade. Covers PRD §3.5.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    clarify_tender_payload,
    register_verified_supplier,
    set_credit_score,
    setup_project_bidding_open,
    setup_project_prescreen_open,
    submit_bid,
    validate_error,
    validate_success,
)


def test_clarify_publishes_back_without_version_change(api, officer_headers):
    """PRD §3.5: "Finalising the clarification transitions
    CLARIFYING → PUBLISHED; this refreshes pinned_at but does not
    change the document's version."
    """
    ctx = setup_project_prescreen_open()
    tender = ctx["tender"]
    v_before = tender["version"]
    pinned_before = tender["pinned_at"]
    api.clarify_tender_document(
        tender["id"], clarify_tender_payload(), officer_headers,
    )
    # Refresh clock so pinned_at can differ.
    advance_clock("2026-01-20T00:00:00.000Z")
    res = api.finalize_clarification(tender["id"], officer_headers)
    after = validate_success(res)
    assert after["doc_status"] == "PUBLISHED"
    assert after["version"] == v_before, (
        f"clarification finalize must NOT change version "
        f"(before={v_before}, after={after['version']})"
    )
    # pinned_at refreshed.
    assert after.get("pinned_at") is not None
    assert after["pinned_at"] != pinned_before


def test_clarify_requires_clock_before_query_window_close_at(
    api, officer_headers,
):
    """PRD §3.5: "During PRESCREEN_OPEN or BIDDING_OPEN, the
    procurement officer can move the tender from PUBLISHED → CLARIFYING,
    supplying a clarification_note payload, provided the current clock
    is strictly before the project's query_window_close_at."
    """
    ctx = setup_project_prescreen_open(
        query_window_close_at="2026-02-15T00:00:00.000Z",
    )
    # Advance clock to AT query_window_close_at (boundary fails per
    # "strictly before").
    advance_clock("2026-02-15T00:00:00.000Z")
    res = api.clarify_tender_document(
        ctx["tender"]["id"], clarify_tender_payload(), officer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_begin_amendment_increments_version_on_republish(
    api, officer_headers,
):
    """PRD §3.5: "Republishing — transitioning AMENDING → PUBLISHED —
    requires the project to be in PRESCREEN_OPEN, increments the
    document's version by one, and resets pinned_at to the current
    clock."
    """
    ctx = setup_project_prescreen_open()
    tender = ctx["tender"]
    v_before = tender["version"]  # should be 1
    advance_clock("2026-01-20T00:00:00.000Z")
    r1 = api.begin_tender_amendment(tender["id"], officer_headers)
    after_begin = validate_success(r1)
    assert after_begin["doc_status"] == "AMENDING"
    advance_clock("2026-01-25T00:00:00.000Z")
    r2 = api.publish_tender_document(tender["id"], officer_headers)
    after = validate_success(r2)
    assert after["doc_status"] == "PUBLISHED"
    assert after["version"] == v_before + 1, (
        f"amendment-cycle republish must increment version by 1: "
        f"before={v_before}, after={after['version']}"
    )


def test_begin_amendment_forces_submitted_bids_to_withdrawn(
    api, officer_headers,
):
    """PRD §3.5: "A heavier-weight amendment ... moves the tender from
    PUBLISHED → AMENDING ... Every bid on the project whose bid_status
    is SUBMITTED is forced to WITHDRAWN so that suppliers may re-submit
    against the amended version."
    """
    ctx = setup_project_bidding_open(required_qualifications=["Q1"])
    advance_clock(ctx["clock_t0"])
    # Submit one bid by a verified supplier.
    sup = register_verified_supplier(qualifications=["Q1"])
    set_credit_score(sup["id"], 700)
    bid = submit_bid(
        ctx["project"]["id"], sup["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    # Trigger amendment.
    api.begin_tender_amendment(ctx["tender"]["id"], officer_headers)
    # Re-read the bid via project bid list.
    from test_helpers import validate_paginated
    listed = api.list_project_bids(
        ctx["project"]["id"], officer_headers, params={"limit": 100},
    )
    data, _meta = validate_paginated(listed)
    found = [b for b in data if b["id"] == bid["id"]]
    assert found, "submitted bid must be visible in the list"
    assert found[0]["bid_status"] == "WITHDRAWN", (
        f"PRD §3.5 cascade: SUBMITTED bid must become WITHDRAWN on "
        f"tender begin-amendment, got {found[0]['bid_status']}"
    )


def test_begin_amendment_from_bidding_open_reverts_project(
    api, officer_headers,
):
    """PRD §3.5: "If the project was in BIDDING_OPEN, it is reverted to
    PRESCREEN_OPEN."
    """
    ctx = setup_project_bidding_open()
    api.begin_tender_amendment(ctx["tender"]["id"], officer_headers)
    proj = validate_success(
        api.get_project(ctx["project"]["id"], officer_headers),
    )
    assert proj["project_status"] == "PRESCREEN_OPEN", (
        f"Project must revert BIDDING_OPEN → PRESCREEN_OPEN, "
        f"got {proj['project_status']}"
    )


def test_begin_amendment_requires_clock_before_deadline(
    api, officer_headers,
):
    """PRD §3.5: "A heavier-weight amendment — beginning a new
    amendment cycle — moves the tender from PUBLISHED → AMENDING,
    provided the current clock is strictly before the bid submission
    deadline."
    """
    ctx = setup_project_bidding_open(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
    )
    advance_clock("2026-03-01T00:00:00.000Z")  # at deadline → fails
    res = api.begin_tender_amendment(
        ctx["tender"]["id"], officer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")
