"""Index-segment crediting arithmetic and temporal-overlap semantics.

Difficulty-queue (depth) instances: each instance is covered by >=2 tests.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_crediting_event_payload, create_index_segment_payload,
    setup_indexed_with_open_segment,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]


# ─── combinatorial_formula / index_segment_credit_nested_cap_floor_participation ─
def test_index_credit_clamps_to_cap(api):
    """PRD §3.3: "the server first scales the raw return by the segment's
    participation, taking `raw_index_return_bps` multiplied by the segment's
    `participation_bps` divided by 10000, then caps that participated return at
    the segment's `cap_bps` by taking the smaller of the two, then floors the
    result at the segment's `floor_bps` ... and finally multiplies the segment's
    `segment_premium_cents` by that bounded rate divided by 10000, rounded half
    up."

    Design: Difficulty/combinatorial_formula/index_segment_credit_nested_cap_floor_participation
    """
    product, contract, segment = setup_indexed_with_open_segment(
        segment_premium_cents=1_000_000, cap_bps=800, floor_bps=0, participation_bps=10000)
    event = validate_success(api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", source_segment_id=segment["id"],
        raw_index_return_bps=1200, credit_period_start="2026-01-01T00:00:00Z",
        credit_period_end="2026-07-01T00:00:00Z"), CREDITING), 201)
    # raw 1200 * participation 100% = 1200, capped at 800 -> 8.00% of 1,000,000 = 80,000.
    assert event["credit_cents"] == 80000


def test_index_segment_marked_credited_after_post(api):
    """PRD §3.3: "When an `INDEX_SEGMENT` crediting event posts against an `OPEN`
    segment, that segment moves from `OPEN` to `CREDITED`, and a `CREDITED`
    segment rejects any further index-segment crediting."

    Design: Difficulty/combinatorial_formula/index_segment_credit_nested_cap_floor_participation
    """
    product, contract, segment = setup_indexed_with_open_segment(
        segment_premium_cents=1_000_000, cap_bps=800, floor_bps=0, participation_bps=10000)
    assert segment["status"] == "OPEN"
    validate_success(api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", source_segment_id=segment["id"],
        raw_index_return_bps=1200, credit_period_start="2026-01-01T00:00:00Z",
        credit_period_end="2026-07-01T00:00:00Z"), CREDITING), 201)
    after = validate_success(api.get_index_segment(segment["id"], ADMIN), 200)
    assert after["status"] == "CREDITED"


# ─── resource_temporal_overlap / index_segment_term_overlap_half_open_adjacency_ok ─
def test_index_segment_overlapping_term_rejected(api):
    """PRD §3.3: "The overlap test rejects a new segment when its start falls
    before an existing segment's end and that existing segment's start falls
    before the new segment's end; such a collision is rejected with
    `ERR_SEGMENT_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/index_segment_term_overlap_half_open_adjacency_ok
    """
    product, contract, segment = setup_indexed_with_open_segment(
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-01T00:00:00Z",
        segment_premium_cents=1_000_000, cap_bps=800)
    res = api.create_index_segment(create_index_segment_payload(
        contract["id"], index_name="SP500",
        term_start_date="2026-06-01T00:00:00Z", term_end_date="2027-01-01T00:00:00Z",
        segment_premium_cents=500_000, cap_bps=800), ADMIN)
    validate_error(res, "ERR_SEGMENT_TERM_OVERLAP", expected_status=409)


def test_index_segment_adjacent_term_allowed(api):
    """PRD §3.3: "Two `OPEN` segments on the same contract and `index_name` may
    not overlap, but they may abut: adjacency where one term's `term_end_date`
    exactly equals the next term's `term_start_date` (a zero-length gap) is
    allowed."

    Design: Difficulty/resource_temporal_overlap/index_segment_term_overlap_half_open_adjacency_ok
    """
    product, contract, segment = setup_indexed_with_open_segment(
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-12-01T00:00:00Z",
        segment_premium_cents=1_000_000, cap_bps=800)
    res = api.create_index_segment(create_index_segment_payload(
        contract["id"], index_name="SP500",
        term_start_date="2026-12-01T00:00:00Z", term_end_date="2027-06-01T00:00:00Z",
        segment_premium_cents=500_000, cap_bps=800), ADMIN)
    created = validate_success(res, 201)
    assert created["status"] == "OPEN"


# ─── resource_temporal_overlap / crediting_period_touch_rejected_closed_buffer ─
def test_crediting_period_touching_prior_end_rejected(api):
    """PRD §3.3: "Unlike segment terms, adjacency is forbidden here: a new
    crediting period whose start exactly equals a prior period's end, or whose
    end exactly equals a prior period's start, is rejected ... Any of these
    collisions, or a period that falls outside the segment's term window, is
    rejected with `ERR_CREDIT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crediting_period_touch_rejected_closed_buffer
    """
    product, contract, segment = setup_indexed_with_open_segment(
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2027-01-01T00:00:00Z",
        segment_premium_cents=1_000_000, cap_bps=800)
    validate_success(api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", source_segment_id=segment["id"],
        raw_index_return_bps=300, credit_period_start="2026-01-01T00:00:00Z",
        credit_period_end="2026-06-01T00:00:00Z"), CREDITING), 201)
    # A CREDITED segment additionally rejects further crediting, but the touching
    # period boundary is the asserted rule; the API rejects with the overlap error.
    res = api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", source_segment_id=segment["id"],
        raw_index_return_bps=300, credit_period_start="2026-06-01T00:00:00Z",
        credit_period_end="2026-09-01T00:00:00Z"), CREDITING)
    validate_error(res, "ERR_CREDIT_PERIOD_OVERLAP", expected_status=409)


def test_crediting_period_outside_segment_term_rejected(api):
    """PRD §3.3: "The `credit_period_start` (inclusive) and `credit_period_end`
    (exclusive) of an `INDEX_SEGMENT` event must lie inside the source segment's
    term window".
    PRD §3.3: "Any of these collisions, or a period that falls outside the
    segment's term window, is rejected with `ERR_CREDIT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/crediting_period_touch_rejected_closed_buffer
    """
    product, contract, segment = setup_indexed_with_open_segment(
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2026-06-01T00:00:00Z",
        segment_premium_cents=1_000_000, cap_bps=800)
    res = api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", source_segment_id=segment["id"],
        raw_index_return_bps=300, credit_period_start="2026-07-01T00:00:00Z",
        credit_period_end="2026-09-01T00:00:00Z"), CREDITING)
    validate_error(res, "ERR_CREDIT_PERIOD_OVERLAP", expected_status=409)
