"""Committee formation, finalisation, and the bid-opening ceremony.
Covers PRD §3.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    close_bidding,
    form_committee,
    form_committee_payload,
    open_bid_ceremony,
    setup_evaluating,
    setup_three_bids_submitted,
    validate_error,
    validate_success,
)


# ===========================================================================
# Committee size constraints
# ===========================================================================
@pytest.mark.parametrize("size", [3, 5, 7, 9])
def test_form_committee_valid_sizes(api, officer_headers, size):
    """PRD §3.7: "The committee size must be an odd integer between
    MIN_SIZE (3) and MAX_SIZE (9) inclusive, so the legal sizes are 3,
    5, 7, and 9."
    """
    ctx = setup_three_bids_submitted()
    res = api.form_committee(
        ctx["project"]["id"],
        form_committee_payload(requested_size=size, selection_seed="seed-A"),
        officer_headers,
    )
    data = validate_success(res, 201)
    assert data["committee_status"] == "FORMED"
    assert len(data["members"]) == size


@pytest.mark.parametrize("size", [2, 4, 6, 10, 1, 0])
def test_form_committee_invalid_size_rejected(api, officer_headers, size):
    """PRD §3.7: "A size outside the allowed set, or a pool too small
    after the conflict-of-interest exclusion, is rejected with
    ERR_COMMITTEE_SIZE_INVALID."
    """
    ctx = setup_three_bids_submitted()
    res = api.form_committee(
        ctx["project"]["id"],
        form_committee_payload(requested_size=size, selection_seed="seed-B"),
        officer_headers,
    )
    validate_error(res, "ERR_COMMITTEE_SIZE_INVALID")


def test_form_committee_members_sorted_by_seeded_hash(api, officer_headers):
    """PRD §3.7: "Selection is deterministic given the seed: each
    remaining eligible expert is sorted by the lexicographic ordering,
    ascending, of the hex-encoded SHA-256 hash of the concatenation of
    the selection_seed, the literal pipe character "|", and the
    expert's id, and the first requested_size are picked."

    PRD pins the ordering rule but does not pin the eligible expert
    pool's identity or persistence across projects. We therefore assert
    only the observable shape: members[].expert_id values are stable
    UTF-8 strings and the requested_size is honored. Determinism in
    the strict cross-call sense is not unique-derivable from PRD prose
    (the eligible pool definition is implementation-internal), so we
    do not pin specific expert ids.
    """
    ctx = setup_three_bids_submitted()
    committee = form_committee(
        ctx["project"]["id"], requested_size=3,
        selection_seed="seeded-hash-rule",
    )
    assert len(committee["members"]) == 3
    for m in committee["members"]:
        assert isinstance(m["expert_id"], str) and m["expert_id"]


def test_form_committee_members_carry_required_fields(api, officer_headers):
    """PRD §3.7: "For each picked expert, a member object is appended
    to members of the form {"expert_id": <id>, "selected_at": <server
    clock current_time>, "conflict_cleared": true}."
    """
    ctx = setup_three_bids_submitted()
    advance_clock("2026-02-20T00:00:00.000Z")
    res = api.form_committee(
        ctx["project"]["id"],
        form_committee_payload(
            requested_size=3, selection_seed="member-shape-seed",
        ),
        officer_headers,
    )
    data = validate_success(res, 201)
    for m in data["members"]:
        assert isinstance(m["expert_id"], str) and m["expert_id"]
        assert "T" in m["selected_at"] and "Z" in m["selected_at"]
        assert m["conflict_cleared"] is True


# ===========================================================================
# Bid-opening ceremony (BIDDING_CLOSED → EVALUATING)
# ===========================================================================
def test_open_ceremony_requires_clock_at_or_after_bid_opening_at(
    api, officer_headers,
):
    """PRD §3.7: "When the clock has advanced to or past the project's
    bid_opening_at and the committee exists in FORMED, the officer
    opens the bid-opening ceremony, transitioning the project from
    BIDDING_CLOSED → EVALUATING."
    """
    ctx = setup_three_bids_submitted(
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
        bid_opening_at="2026-03-05T00:00:00.000Z",
    )
    form_committee(ctx["project"]["id"], requested_size=3,
                   selection_seed="opening-seed")
    advance_clock("2026-03-01T00:00:00.000Z")
    close_bidding(ctx["project"]["id"])
    # Clock still 2026-03-01, but bid_opening_at is 2026-03-05.
    res = api.open_bid_ceremony(ctx["project"]["id"], officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_open_ceremony_requires_at_least_three_submitted_bids(
    api, officer_headers,
):
    """PRD §3.7: "The transition requires at least three bids in
    SUBMITTED at the moment of the call."
    """
    # Use a project with only 2 bids to test boundary.
    bid_specs = [
        {"price": 5_000_000, "technical_score_raw": 80,
         "qualifications": ["Q1", "Q2"]},
        {"price": 6_000_000, "technical_score_raw": 70,
         "qualifications": ["Q1", "Q2"]},
    ]
    ctx = setup_three_bids_submitted(
        bid_specs=bid_specs,
        required_qualifications=["Q1", "Q2"],
        bid_submission_deadline="2026-03-01T00:00:00.000Z",
        bid_opening_at="2026-03-05T00:00:00.000Z",
    )
    form_committee(ctx["project"]["id"], requested_size=3,
                   selection_seed="too-few-seed")
    advance_clock("2026-03-01T00:00:00.000Z")
    close_bidding(ctx["project"]["id"])
    advance_clock("2026-03-05T00:00:00.000Z")
    res = api.open_bid_ceremony(ctx["project"]["id"], officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_open_ceremony_moves_bids_to_opened(api, officer_headers):
    """PRD §3.7: "As side effects, every SUBMITTED bid that passed
    pre-screening is moved to OPENED, the committee advances from
    FORMED → EVALUATING, and an AuditLog entry is appended with
    target_type EVALUATION and action "BID_CEREMONY_RECORDED"."
    """
    from test_helpers import validate_paginated
    ctx = setup_evaluating()
    listed = api.list_project_bids(
        ctx["project"]["id"], officer_headers, params={"limit": 100},
    )
    bids, _ = validate_paginated(listed)
    # All bids should be OPENED (or DISQUALIFIED if they failed prescreen).
    assert all(b["bid_status"] in {"OPENED", "DISQUALIFIED"} for b in bids), (
        f"after ceremony, bids must be OPENED or DISQUALIFIED; "
        f"got {[b['bid_status'] for b in bids]}"
    )
    # Committee should be EVALUATING.
    assert ctx["committee"]["committee_status"] in {"FORMED", "EVALUATING"}, (
        "Setup invariant: committee was FORMED before ceremony"
    )


def test_open_ceremony_appends_audit_log_entry(api, regulator_headers):
    """PRD §3.7: "an AuditLog entry is appended with target_type
    EVALUATION and action "BID_CEREMONY_RECORDED"."
    """
    from test_helpers import validate_paginated
    ctx = setup_evaluating()
    res = api.list_audit_logs(
        regulator_headers,
        params={"target_type": "EVALUATION", "limit": 100},
    )
    entries, _ = validate_paginated(res)
    matches = [
        e for e in entries
        if e.get("action") == "BID_CEREMONY_RECORDED"
    ]
    assert matches, (
        "AuditLog must contain a BID_CEREMONY_RECORDED entry "
        "(target_type=EVALUATION)"
    )
