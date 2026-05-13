"""Concurrency races. Covers PRD §2.9.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    make_expert_headers,
    make_supplier_headers,
    record_evaluation_payload,
    run_race,
    setup_evaluating,
    setup_project_bidding_open,
    submit_bid_payload,
    validate_error_is_one_of,
)
from test_helpers import (
    register_verified_supplier,
    set_credit_score,
)


def test_duplicate_bid_race_yields_one_winner(api):
    """PRD §2.9: "When two suppliers race to submit a bid for the same
    (project_id, supplier_id) pair while the deadline is approaching,
    at most one row exists at the level of (project_id, supplier_id,
    non-terminal bid_status). The first writer wins; the loser is
    rejected with ERR_DUPLICATE_BID."
    """
    ctx = setup_project_bidding_open(required_qualifications=[])
    sup = register_verified_supplier(qualifications=[])
    set_credit_score(sup["id"], 700)
    headers = make_supplier_headers(sup["id"])
    project_id = ctx["project"]["id"]
    payload_a = submit_bid_payload(
        supplier_id=sup["id"],
        tender_document_version=ctx["tender"]["version"],
        bid_price_cents=5_000_000,
    )
    payload_b = submit_bid_payload(
        supplier_id=sup["id"],
        tender_document_version=ctx["tender"]["version"],
        bid_price_cents=4_800_000,
    )
    results = run_race(
        lambda: api.submit_bid(project_id, payload_a, headers),
        lambda: api.submit_bid(project_id, payload_b, headers),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    validate_error_is_one_of(loser, ["ERR_DUPLICATE_BID"])


def test_same_bid_two_evaluators_race(api):
    """PRD §2.9: "When two evaluation experts race to record a score
    for the same bid, the bid's status compare-and-swap from OPENED to
    EVALUATED serialises both. Exactly one score is persisted; the
    loser sees ERR_BID_ALREADY_EVALUATED."
    """
    ctx = setup_evaluating()
    bid = ctx["bids"][0]
    members = ctx["committee"]["members"]
    # Use two distinct expert ids picked by the server.
    if len(members) < 2:
        pytest.skip(
            "concurrency test requires committee size >= 2; "
            "scaffold guarantees >= 3 so this should not trigger"
        )
    e1 = make_expert_headers(members[0]["expert_id"])
    e2 = make_expert_headers(members[1]["expert_id"])
    results = run_race(
        lambda: api.record_evaluation(bid["id"], record_evaluation_payload(), e1),
        lambda: api.record_evaluation(bid["id"], record_evaluation_payload(), e2),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    validate_error_is_one_of(loser, ["ERR_BID_ALREADY_EVALUATED"])
