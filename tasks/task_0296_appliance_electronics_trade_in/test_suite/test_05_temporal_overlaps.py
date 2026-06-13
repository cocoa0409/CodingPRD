"""Temporal-overlap rules: half-open promo windows (no buffer, adjacency allowed)
vs closed inspection-slot intervals with a 30-minute buffer (touching conflicts).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_catalog,
    create_promotion,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AGENT = TEST_USERS["grading_agent_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / promo_window_halfopen_overlap_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_window_overlap_rejected_adjacency_allowed(api):
    """PRD §3.2: "the system rejects it with `ERR_PROMO_WINDOW_OVERLAP` (HTTP 409) if
    its half-open `[effective_from, effective_to)` interval overlaps that of any
    existing active campaign whose lane collides".
    PRD §3.2: "exact adjacency is permitted: one campaign's `effective_to` equal to
    another's `effective_from` does not conflict".

    P1 [Jan,Jun) exists; P3 [Jun,Sep) merely touches P1 and is allowed; P2 [May,Sep)
    overlaps P1 and is rejected.

    Design: Difficulty/resource_temporal_overlap/promo_window_halfopen_overlap_rejected
    """
    cat = create_catalog()
    create_promotion(
        cat["id"], code="P1", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=0, bonus_cap_cents=6000,
    )
    # adjacency allowed
    create_promotion(
        cat["id"], code="P3", category_scope="ALL",
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-09-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=0, bonus_cap_cents=6000,
    )

    # overlap rejected
    resp = api.create_promotion_campaign(
        cat["id"],
        {
            "code": "P2", "category_scope": "ALL",
            "effective_from": "2026-05-01T00:00:00Z", "effective_to": "2026-09-01T00:00:00Z",
            "bonus_pct": 0.10, "bonus_flat_cents": 0, "bonus_cap_cents": 6000,
        },
        ADMIN,
    )
    validate_error(resp, "ERR_PROMO_WINDOW_OVERLAP")

    listed, meta = validate_paginated(api.list_promotion_campaigns(cat["id"], ADMIN))
    codes = sorted(c["code"] for c in listed)
    assert codes == ["P1", "P3"], f"P2 must not have been created; got {codes}"


def test_promo_window_adjacent_touch_is_allowed(api):
    """PRD §3.2: "Because the intervals are half-open, exact adjacency is permitted: one
    campaign's `effective_to` equal to another's `effective_from` does not conflict,
    since neither instant lies in both intervals."

    A second active promo on the same ALL lane whose effective_from equals the first's
    effective_to is created successfully (adjacency, not overlap).

    Design: Difficulty/resource_temporal_overlap/promo_window_halfopen_overlap_rejected
    """
    cat = create_catalog()
    create_promotion(
        cat["id"], code="A1", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=0, bonus_cap_cents=6000,
    )
    resp = api.create_promotion_campaign(
        cat["id"],
        {
            "code": "A2", "category_scope": "ALL",
            "effective_from": "2026-06-01T00:00:00Z", "effective_to": "2026-09-01T00:00:00Z",
            "bonus_pct": 0.10, "bonus_flat_cents": 0, "bonus_cap_cents": 6000,
        },
        ADMIN,
    )
    created = validate_success(resp, expected_status=201)
    assert created["code"] == "A2"
    assert created["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / inspection_slot_buffered_closed_overlap_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_slot_buffered_closed_overlap_rejected(api):
    """PRD §3.8: "The booked window is a closed interval, and a 30-minute buffer is
    added on each side of it; the new slot is rejected with `ERR_SLOT_OVERLAP` (HTTP
    409) if this buffered interval overlaps any existing `BOOKED` slot on the same
    `lane_category`."

    A BOOKED SMARTPHONE slot [10:00,11:00]; a new [11:15,12:00] slot starts within the
    30-minute buffer and is rejected.

    Design: Difficulty/resource_temporal_overlap/inspection_slot_buffered_closed_overlap_rejected
    """
    cat = create_catalog()
    validate_success(
        api.create_inspection_slot(
            cat["id"],
            {"lane_category": "SMARTPHONE", "slot_start": "2026-06-10T10:00:00Z", "slot_end": "2026-06-10T11:00:00Z"},
            AGENT,
        ),
        expected_status=201,
    )

    resp = api.create_inspection_slot(
        cat["id"],
        {"lane_category": "SMARTPHONE", "slot_start": "2026-06-10T11:15:00Z", "slot_end": "2026-06-10T12:00:00Z"},
        AGENT,
    )
    validate_error(resp, "ERR_SLOT_OVERLAP")

    listed, meta = validate_paginated(api.list_inspection_slots(cat["id"], AGENT, params={"status": "BOOKED"}))
    booked = [s for s in listed if s["lane_category"] == "SMARTPHONE" and s["status"] == "BOOKED"]
    assert len(booked) == 1, f"only the first slot should be BOOKED; got {len(booked)}"


def test_slot_on_different_lane_does_not_conflict(api):
    """PRD §3.8: "the new slot is rejected with `ERR_SLOT_OVERLAP` (HTTP 409) if this
    buffered interval overlaps any existing `BOOKED` slot on the same `lane_category`."

    A slot booked on a DIFFERENT lane_category (LAPTOP) for the very same window as a
    BOOKED SMARTPHONE slot is accepted, because the overlap check is scoped per lane.

    Design: Difficulty/resource_temporal_overlap/inspection_slot_buffered_closed_overlap_rejected
    """
    cat = create_catalog()
    validate_success(
        api.create_inspection_slot(
            cat["id"],
            {"lane_category": "SMARTPHONE", "slot_start": "2026-06-10T10:00:00Z", "slot_end": "2026-06-10T11:00:00Z"},
            AGENT,
        ),
        expected_status=201,
    )
    other = validate_success(
        api.create_inspection_slot(
            cat["id"],
            {"lane_category": "LAPTOP", "slot_start": "2026-06-10T10:00:00Z", "slot_end": "2026-06-10T11:00:00Z"},
            AGENT,
        ),
        expected_status=201,
    )
    assert other["status"] == "BOOKED"
    assert other["lane_category"] == "LAPTOP"
