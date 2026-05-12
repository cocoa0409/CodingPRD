"""Settlement run creation, finalize, and the post-refund REVERSED cascade."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    SettlementRunStatus,
    TEST_USERS,
    add_minutes,
    advance_clock_to,
    assert_settlement_payout_invariant,
    assert_settlement_run,
    create_settlement_run_around_slot,
    create_settlement_run_payload,
    finalize_settlement_run,
    get_settlement_run,
    refund_booking,
    setup_finalized_settlement_around_slot,
    setup_settled_booking_with_split,
    setup_slot_at_completed,
    unique_chain_id,
    validate_error,
    validate_success,
)


# ─── §3.10 Empty-set sweep boundary ───────────────────────────────────────

def test_empty_period_settlement_run_finalizes_at_zero(api):
    """PRD §3.10: "the server freezes `included_session_ids` to those `SessionSlot` rows whose `schedule_status` is `COMPLETED` and whose `ends_at` falls within the closed-open period bound by `period_starts_at` and `period_ends_at`."

    Claim: a SettlementRun whose period covers no completed sessions has included_session_ids=[]; gross_total_cents=0; all payouts=0; finalize succeeds.
    """
    admin = TEST_USERS["platform_admin_headers"]
    chain_id = unique_chain_id()
    payload = create_settlement_run_payload(chain_id, "2030-01-01T00:00:00.000Z", "2030-01-02T00:00:00.000Z")
    run = validate_success(api.create_settlement_run(payload, admin), expected_status=201)
    assert_settlement_run(run)
    assert run["included_session_ids"] == []
    for f in ("gross_total_cents", "author_payout_cents", "host_payout_cents", "venue_payout_cents", "platform_fee_cents"):
        assert run[f] == 0
    finalized = validate_success(api.finalize_settlement_run(run["id"], admin))
    assert finalized["status"] == SettlementRunStatus.FINALIZED.value


# ─── §3.10 Per-session allocation invariant ───────────────────────────────

def test_settlement_payout_sum_invariant(api):
    """PRD §3.10: "The invariant `gross_total_cents` equals `author_payout_cents` plus `host_payout_cents` plus `venue_payout_cents` plus `platform_fee_cents` is enforced after the sums."

    Claim: after finalizing a run that sweeps a single SETTLED booking, payouts sum exactly to gross_total_cents.
    """
    state = setup_settled_booking_with_split(
        paid_amount_cents_per_seat=5000, seat_count=2,
        revenue_share_bps=4500, author_royalty_bps=2000,
        host_commission_bps=1500, platform_fee_bps=2000,
    )
    state = setup_finalized_settlement_around_slot(state)
    run = state["run"]
    assert run["status"] == SettlementRunStatus.FINALIZED.value
    assert_settlement_payout_invariant(run)


# ─── §3.10 Per-session floor-then-sum (mode b) ────────────────────────────

def test_settlement_per_session_floor_then_sum(api):
    """PRD §3.10: "The pinned arithmetic is **floor-then-sum**, never sum-then-floor: at one thousand sessions, the difference can amount to several hundred dropped cents."

    Claim: with two slots, each producing net=333 cents and author_bps=3333, per-session-floor yields author_payout = floor(333*3333/10000) + floor(333*3333/10000) = 110 + 110 = 220 (NOT floor(666*3333/10000)=221).
    """
    chain_id = unique_chain_id()
    # author_royalty_bps=3333, host_commission_bps=0 (no HOST assignment, redistributes to platform),
    # revenue_share_bps=3333, platform_fee_bps=3334 — sums to 10000.
    state1 = setup_settled_booking_with_split(
        paid_amount_cents_per_seat=333, seat_count=1,
        revenue_share_bps=3333, author_royalty_bps=3333,
        host_commission_bps=0, platform_fee_bps=3334,
        chain_id=chain_id,
    )
    state2 = setup_settled_booking_with_split(
        paid_amount_cents_per_seat=333, seat_count=1,
        revenue_share_bps=3333, author_royalty_bps=3333,
        host_commission_bps=0, platform_fee_bps=3334,
        chain_id=chain_id,
    )
    # Single settlement run covering both slots.
    admin = TEST_USERS["platform_admin_headers"]
    early = state1["slot"]["starts_at"] if state1["slot"]["starts_at"] < state2["slot"]["starts_at"] else state2["slot"]["starts_at"]
    late = state2["slot"]["ends_at"] if state2["slot"]["ends_at"] > state1["slot"]["ends_at"] else state1["slot"]["ends_at"]
    payload = create_settlement_run_payload(chain_id, add_minutes(early, -1), add_minutes(late, 60 * 24))
    run = validate_success(api.create_settlement_run(payload, admin), expected_status=201)
    finalized = finalize_settlement_run(run)
    # gross_total = 333 + 333 = 666 (PRD §3.10: gross_total aggregates per-session NET).
    assert finalized["gross_total_cents"] == 666
    # author = floor(333*3333/10000) + floor(333*3333/10000) = 110 + 110 = 220.
    assert finalized["author_payout_cents"] == 220
    # venue = floor(333*3333/10000) * 2 = 220.
    assert finalized["venue_payout_cents"] == 220
    # No HOST assignment ⇒ host_bps = 0; host payout = 0.
    assert finalized["host_payout_cents"] == 0
    # platform = sum( per-session ( net - author - host - venue ) ) = sum(333-110-0-110) * 2 = 113 * 2 = 226.
    assert finalized["platform_fee_cents"] == 226
    assert_settlement_payout_invariant(finalized)


# ─── §3.10 Theme override beats venue default (mode a) ────────────────────

def test_author_royalty_theme_override_used(api):
    """PRD §3.10: "The author basis points for `S` is `S.theme.author_royalty_bps_override` if that field is non-null, otherwise the venue's `author_royalty_bps`."

    Claim: a theme with author_royalty_bps_override=2000 used against a venue whose author_royalty_bps=1000 yields author_payout = floor(net*2000/10000), not floor(net*1000/10000).
    """
    # venue: revenue_share=4500, author_royalty=1000 (the venue default), host_commission=1500, platform_fee=3000 → 10000.
    # theme override: 2000 — this should win.
    state = setup_settled_booking_with_split(
        paid_amount_cents_per_seat=10000, seat_count=1,
        revenue_share_bps=4500, author_royalty_bps=1000,
        host_commission_bps=1500, platform_fee_bps=3000,
        author_royalty_bps_override=2000,
    )
    state = setup_finalized_settlement_around_slot(state)
    run = state["run"]
    # net = 10000; author_bps = override 2000 → author_payout = 2000.
    assert run["author_payout_cents"] == 2000
    assert_settlement_payout_invariant(run)


# ─── §3.10 Refund cascades FINALIZED -> REVERSED ──────────────────────────

def test_refund_after_finalize_reverses_run(api):
    """PRD §3.6: "If a `SettlementRun` in `FINALIZED` status already covers the slot, the run is automatically flipped to `REVERSED` — no error is raised — and its payout fields are recomputed proportionally per §3.10."
    PRD §3.10: "A finalised run is reversed automatically — moving from `FINALIZED` to `REVERSED` — when any booking under any included session transitions from `SETTLED` to `REFUNDED`."

    Claim: after a refund hits a SETTLED booking under a FINALIZED run, the run flips to REVERSED with payouts recomputed.
    """
    state = setup_settled_booking_with_split(
        paid_amount_cents_per_seat=5000, seat_count=2,
        revenue_share_bps=4500, author_royalty_bps=2000,
        host_commission_bps=1500, platform_fee_bps=2000,
    )
    state = setup_finalized_settlement_around_slot(state)
    run = state["run"]
    initial_gross = run["gross_total_cents"]
    booking, venue = state["booking"], state["venue"]
    refund_amount = 4000
    refund_booking(booking, venue, refund_amount)
    refreshed_run = get_settlement_run(run["id"])
    assert refreshed_run["status"] == SettlementRunStatus.REVERSED.value
    assert refreshed_run["gross_total_cents"] == initial_gross - refund_amount
    assert_settlement_payout_invariant(refreshed_run)


# ─── §3.10 ERR_SETTLEMENT_HAS_OPEN_SESSIONS on finalize with non-completed ─

# Note: per PRD §3.10 included_session_ids is frozen to COMPLETED slots at sweep time.
# A settlement created strictly after every slot is COMPLETED therefore can ONLY include
# COMPLETED sessions, and ERR_SETTLEMENT_HAS_OPEN_SESSIONS would only fire if the slot
# regressed (which the PRD never permits). The error is exercised via the silence
# bucket; no dedicated test is generated here.


# ─── §3.10 ERR_SETTLEMENT_ALREADY_FINALIZED on double-finalize ────────────

def test_double_finalize_rejected(api):
    """PRD §2.11: "The losing finalize attempt returns `ERR_SETTLEMENT_ALREADY_FINALIZED` at HTTP 409."

    Claim: re-finalizing an already-FINALIZED run yields ERR_SETTLEMENT_ALREADY_FINALIZED.
    """
    state = setup_settled_booking_with_split()
    state = setup_finalized_settlement_around_slot(state)
    admin = TEST_USERS["platform_admin_headers"]
    resp = api.finalize_settlement_run(state["run"]["id"], admin)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_ALREADY_FINALIZED.value)
