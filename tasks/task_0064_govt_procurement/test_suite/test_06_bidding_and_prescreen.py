"""Bid submission, withdrawal, pre-screening, deadline, blacklist,
ceiling and duplicate detection. Covers PRD §3.3 and §3.6.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    blacklist_supplier,
    make_supplier_headers,
    register_supplier,
    register_verified_supplier,
    set_credit_score,
    setup_project_bidding_open,
    submit_bid,
    submit_bid_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful submission + prescreen_passed snapshot
# ===========================================================================
def test_submit_bid_snapshots_prescreen_passed_true(api):
    """PRD §3.6: "At submission, the system snapshots the supplier's
    prescreen_passed flag onto the bid using the eligibility calculation
    described in §3.3. The new bid enters SUBMITTED."
    """
    ctx = setup_project_bidding_open(required_qualifications=["Q1", "Q2"])
    sup = register_verified_supplier(qualifications=["Q1", "Q2"])
    set_credit_score(sup["id"], 700)
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    data = validate_success(res, 201)
    assert data["bid_status"] == "SUBMITTED"
    assert data["prescreen_passed"] is True


def test_submit_bid_snapshots_prescreen_passed_false_when_missing_qual(api):
    """PRD §3.3: "the project's required_qualifications must be a subset
    of the supplier's qualifications." PRD §3.6 snapshot rule.
    """
    ctx = setup_project_bidding_open(required_qualifications=["Q1", "Q2"])
    sup = register_verified_supplier(qualifications=["Q1"])  # missing Q2
    set_credit_score(sup["id"], 700)
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    data = validate_success(res, 201)
    assert data["prescreen_passed"] is False


# ===========================================================================
# Deadline (priority 9)
# ===========================================================================
def test_submit_bid_at_deadline_returns_deadline_passed(api):
    """PRD §3.6: "The bid is rejected with ERR_DEADLINE_PASSED if the
    current clock is at or after bid_submission_deadline."
    """
    ctx = setup_project_bidding_open(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    advance_clock("2026-03-01T00:00:00.000Z")  # AT deadline
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_error(res, "ERR_DEADLINE_PASSED")


def test_submit_bid_after_deadline_returns_deadline_passed(api):
    """PRD §3.6: "at or after bid_submission_deadline." """
    ctx = setup_project_bidding_open(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    advance_clock("2026-03-02T00:00:00.000Z")
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_error(res, "ERR_DEADLINE_PASSED")


# ===========================================================================
# Blacklist (priority 8)
# ===========================================================================
def test_submit_bid_by_blacklisted_supplier_rejected(api):
    """PRD §3.6: "It is rejected with ERR_SUPPLIER_BLACKLISTED if the
    supplier is currently blacklisted (blacklist_until is greater than
    current_time)."
    """
    ctx = setup_project_bidding_open(required_qualifications=[])
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    advance_clock("2026-01-05T00:00:00.000Z")
    blacklist_supplier(sup["id"], "2030-01-01T00:00:00.000Z")
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_error(res, "ERR_SUPPLIER_BLACKLISTED")


# ===========================================================================
# Ceiling (priority 18)
# ===========================================================================
def test_submit_bid_above_ceiling_rejected(api):
    """PRD §3.6: "It is rejected with ERR_BID_EXCEEDS_CEILING if
    bid_price_cents exceeds the project's estimated_value_cents."
    """
    ctx = setup_project_bidding_open(
        required_qualifications=[],
        estimated_value_cents=5_000_000,
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_001,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_error(res, "ERR_BID_EXCEEDS_CEILING")


def test_submit_bid_at_ceiling_accepted(api):
    """PRD §3.6: "if bid_price_cents exceeds the project's
    estimated_value_cents." — equality must be allowed.
    """
    ctx = setup_project_bidding_open(
        required_qualifications=[],
        estimated_value_cents=5_000_000,
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_success(res, 201)


# ===========================================================================
# Tender version pin (priority 14)
# ===========================================================================
def test_submit_bid_with_wrong_tender_version_rejected(api):
    """PRD §3.5: "Bids submitted on a project must carry a
    tender_document_version matching the project's current PUBLISHED
    TenderDocument.version at submission time. A version mismatch
    yields ERR_TENDER_VERSION_MISMATCH."
    """
    ctx = setup_project_bidding_open(required_qualifications=[])
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    res = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"] + 1,
            bid_price_cents=5_000_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_error(res, "ERR_TENDER_VERSION_MISMATCH")


# ===========================================================================
# Duplicate bid (priority — concurrency rule + per-bid)
# ===========================================================================
def test_second_non_terminal_bid_by_same_supplier_rejected(api):
    """PRD §3.6: "The system enforces that exactly one non-terminal bid
    exists per (project_id, supplier_id) pair: a second submission by
    the same supplier while the first is still in SUBMITTED, OPENED,
    EVALUATED, or AWARDED is rejected with ERR_DUPLICATE_BID."
    """
    ctx = setup_project_bidding_open(required_qualifications=[])
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    submit_bid(
        ctx["project"]["id"], sup["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    res2 = api.submit_bid(
        ctx["project"]["id"],
        submit_bid_payload(
            supplier_id=sup["id"],
            tender_document_version=ctx["tender"]["version"],
            bid_price_cents=4_500_000,
        ),
        make_supplier_headers(sup["id"]),
    )
    validate_error(res2, "ERR_DUPLICATE_BID")


# ===========================================================================
# Withdraw bid: supplier identity gate
# ===========================================================================
def test_withdraw_bid_by_other_supplier_rejected(api):
    """PRD §3.6: "A supplier may withdraw their own bid, transitioning
    SUBMITTED → WITHDRAWN, but only while the clock is strictly before
    bid_submission_deadline; the supplier's identity (X-User-ID) must
    match the bid's supplier_id."

    Claim: another supplier attempting withdraw is rejected.
    """
    ctx = setup_project_bidding_open(required_qualifications=[])
    s1 = register_verified_supplier(qualifications=[])
    s2 = register_verified_supplier(qualifications=[])
    set_credit_score(s1["id"], 700)
    set_credit_score(s2["id"], 700)
    bid = submit_bid(
        ctx["project"]["id"], s1["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    res = api.withdraw_bid(bid["id"], make_supplier_headers(s2["id"]))
    # PRD §2.1: ownership mismatch on Supplier-role mutation is
    # rejected; PRD §5 does not pin a specific code for this case, so
    # we assert HTTP-level rejection.
    assert 400 <= res.status_code < 500, (
        f"withdraw by non-owner must be rejected, got {res.status_code}"
    )


def test_withdraw_own_bid_before_deadline_succeeds(api):
    """PRD §3.6: "A supplier may withdraw their own bid, transitioning
    SUBMITTED → WITHDRAWN, but only while the clock is strictly before
    bid_submission_deadline."
    """
    ctx = setup_project_bidding_open(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
        required_qualifications=[],
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    bid = submit_bid(
        ctx["project"]["id"], sup["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    # Clock still at 2026-01-01 (before deadline).
    res = api.withdraw_bid(bid["id"], make_supplier_headers(sup["id"]))
    data = validate_success(res)
    assert data["bid_status"] == "WITHDRAWN"


def test_withdraw_bid_at_or_after_deadline_rejected(api):
    """PRD §3.6: "only while the clock is strictly before
    bid_submission_deadline."
    """
    ctx = setup_project_bidding_open(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
        required_qualifications=[],
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    bid = submit_bid(
        ctx["project"]["id"], sup["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    advance_clock("2026-03-01T00:00:00.000Z")
    res = api.withdraw_bid(bid["id"], make_supplier_headers(sup["id"]))
    validate_error(res, "ERR_DEADLINE_PASSED")


# ===========================================================================
# Close-bidding side effect: re-prescreen disqualifies
# ===========================================================================
def test_close_bidding_disqualifies_blacklisted_after_submission(api, officer_headers):
    """PRD §3.3: "When the project's bidding is later closed, the
    eligibility check is re-run against the current clock — this
    catches suppliers blacklisted after they submitted — and any
    SUBMITTED bid that now fails is forced to DISQUALIFIED as a side
    effect of the close-bidding transition."
    """
    ctx = setup_project_bidding_open(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
        required_qualifications=[],
    )
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    bid = submit_bid(
        ctx["project"]["id"], sup["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    # Blacklist after submission, then close.
    blacklist_supplier(sup["id"], "2030-01-01T00:00:00.000Z")
    advance_clock("2026-03-01T00:00:00.000Z")
    from test_helpers import close_bidding, validate_paginated
    close_bidding(ctx["project"]["id"])
    listed = api.list_project_bids(
        ctx["project"]["id"], officer_headers, params={"limit": 100},
    )
    bids, _ = validate_paginated(listed)
    found = next(b for b in bids if b["id"] == bid["id"])
    assert found["bid_status"] == "DISQUALIFIED"


def test_blacklist_disqualifies_existing_submitted_bid(api, officer_headers):
    """PRD §3.3: "A regulator may at any point blacklist the supplier
    ... This action additionally disqualifies every SUBMITTED bid the
    supplier currently holds."
    """
    ctx = setup_project_bidding_open(required_qualifications=[])
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    bid = submit_bid(
        ctx["project"]["id"], sup["id"], bid_price_cents=5_000_000,
        tender_document_version=ctx["tender"]["version"],
    )
    blacklist_supplier(sup["id"], "2030-01-01T00:00:00.000Z")
    from test_helpers import validate_paginated
    listed = api.list_project_bids(
        ctx["project"]["id"], officer_headers, params={"limit": 100},
    )
    bids, _ = validate_paginated(listed)
    found = next(b for b in bids if b["id"] == bid["id"])
    assert found["bid_status"] == "DISQUALIFIED"
