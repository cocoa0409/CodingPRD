"""Temporal-window overlap (closed vs half-open) and compensating value-conservation invariants.

Queue A (Difficulty) rules resource_temporal_overlap and compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_program, create_active_card, create_campaign,
    setup_program_and_active_card, setup_dormancy_waiver,
    setup_open_replacement, setup_full_refund_on_settled_redemption,
    create_dormancy_waiver_payload, create_campaign_payload,
    assert_program,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]
_FRAUD = TEST_USERS["fraud_analyst_headers"]


# ── resource_temporal_overlap ──────────────────────────────────────────────

def test_dormancy_waiver_touching_endpoint_overlaps_closed_interval(api):
    """PRD §3.8: "a ProgramAdmin or FraudAnalyst creates a DormancyWaiver on a card_id
    spanning a closed interval from window_start (inclusive) to window_end (inclusive) ... A
    new waiver may not overlap an existing ACTIVE waiver on the same card; an overlapping
    waiver is rejected with ERR_WAIVER_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/dormancy_waiver_closed_interval_overlap_rejected
    """
    program, card = setup_program_and_active_card(settled_cents=4000)
    setup_dormancy_waiver(card["id"], "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z")
    # Second waiver starts exactly where the first ends; closed-interval adjacency overlaps.
    res = api.create_dormancy_waiver(
        create_dormancy_waiver_payload(card["id"], "2026-06-01T00:00:00Z",
                                       "2026-09-01T00:00:00Z"),
        _ADMIN)
    validate_error(res, "ERR_WAIVER_OVERLAP", expected_status=409)


def test_dormancy_waiver_disjoint_window_allowed(api):
    """PRD §3.8: "A new waiver may not overlap an existing ACTIVE waiver on the same card; an
    overlapping waiver is rejected with ERR_WAIVER_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/dormancy_waiver_closed_interval_overlap_rejected
    """
    program, card = setup_program_and_active_card(settled_cents=4000)
    setup_dormancy_waiver(card["id"], "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z")
    # A strictly-later, non-touching window does not overlap.
    res = api.create_dormancy_waiver(
        create_dormancy_waiver_payload(card["id"], "2026-06-02T00:00:00Z",
                                       "2026-09-01T00:00:00Z"),
        _ADMIN)
    waiver = validate_success(res, 201)
    assert waiver["status"] == "ACTIVE"


def test_campaign_overlapping_window_rejected_half_open(api):
    """PRD §3.1: "A new campaign window may not overlap any existing campaign in the same
    program; an overlapping window is rejected with ERR_CAMPAIGN_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/promo_campaign_half_open_adjacent_allowed_overlap_rejected
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    create_campaign(program["id"], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z",
                    name="Winter", bonus_pct=0.10)
    create_campaign(program["id"], "2026-03-01T00:00:00Z", "2026-05-01T00:00:00Z",
                    name="Spring", bonus_pct=0.05)
    # A window starting strictly before an existing window_end overlaps.
    res = api.create_campaign(
        create_campaign_payload(program["id"], "2026-02-15T00:00:00Z",
                                "2026-04-01T00:00:00Z", name="Overlap", bonus_pct=0.08),
        _ADMIN)
    validate_error(res, "ERR_CAMPAIGN_OVERLAP", expected_status=409)


def test_campaign_adjacent_half_open_window_allowed(api):
    """PRD §3.1: "a half-open active window defined by window_start (inclusive) and
    window_end (exclusive)."
    PRD §3.1: "A new campaign window may not overlap any existing campaign in the same
    program; an overlapping window is rejected with ERR_CAMPAIGN_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/promo_campaign_half_open_adjacent_allowed_overlap_rejected
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    create_campaign(program["id"], "2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z",
                    name="Winter", bonus_pct=0.10)
    # A campaign starting exactly at the first's exclusive window_end does NOT overlap.
    res = api.create_campaign(
        create_campaign_payload(program["id"], "2026-03-01T00:00:00Z",
                                "2026-05-01T00:00:00Z", name="Spring", bonus_pct=0.05),
        _ADMIN)
    spring = validate_success(res, 201)
    assert spring["status"] == "SCHEDULED"


# ── compensating_invariant ─────────────────────────────────────────────────

def test_replacement_transfer_conserves_program_liability(api):
    """PRD §3.7: "so that the old card's post-transfer settled balance plus the new card's
    post-transfer settled balance equals the old card's pre-transfer balance — value is
    conserved across the pair, and the program's outstanding_liability_cents therefore does
    not change because the value merely moves between two cards in the same program."

    Design: Difficulty/compensating_invariant/replacement_transfer_conserves_program_liability
    """
    program, old_card, replacement = setup_open_replacement(
        settled_cents=3000, reason="DAMAGED")
    approved = get_success_data(
        api.approve_replacement(replacement["id"],
                                {"expected_old_card_version": old_card["version"]}, _FRAUD))
    new_card_id = approved["new_card_id"]
    old_after = validate_success(api.get_card(old_card["id"], _FRAUD), 200)
    new_after = validate_success(api.get_card(new_card_id, _FRAUD), 200)
    assert old_after["settled_balance_cents"] == 0
    assert new_after["settled_balance_cents"] == 3000
    prog = validate_success(api.get_program(program["id"], _ADMIN), 200)
    assert_program(prog)
    # Only one pair of cards exists; liability unchanged at the pre-transfer value 3000.
    assert prog["outstanding_liability_cents"] == 3000


def test_full_refund_reversal_drives_redemption_voided(api):
    """PRD §3.6: "if a redemption_id is set and the approved requested_refund_cents exactly
    equals that redemption's allocated_amount_cents, the referenced redemption is driven
    SETTLED to VOIDED."
    PRD §3.6: "Or they may approve it (PENDING to APPLIED)."

    Design: Difficulty/compensating_invariant/full_refund_reversal_restores_card_balances

    NOTE: the per-card restored settled balance is NOT asserted here. The PRD is
    self-contradictory on the post-reversal settled balance: §2.5 mandates that
    "entries whose status is REVERSED are excluded from this sum," while §3.6 directs
    the reversal to BOTH mark the original REDEEM debit REVERSED AND post a new
    REVERSAL credit, and separately states the net effect is "restored by its leg's
    leg_amount_cents." Excluding the REVERSED debit (§2.5) and adding the REVERSAL
    credit (§3.6) nets +2x the leg amount, contradicting §3.6's stated +1x restore.
    Two faithful PRD-only readings therefore yield divergent balances, so the balance
    assertion is not uniquely derivable and is dropped (only the state transitions,
    which the PRD does uniquely determine, are asserted).
    """
    program, customer, cards, settled, refund = setup_full_refund_on_settled_redemption(
        balances=(3000, 1500), requested_amount_cents=4500)
    applied = validate_success(api.approve_refund(refund["id"], _ADMIN), 200)
    assert applied["status"] == "APPLIED"
    red_after = validate_success(api.get_redemption(settled["id"], _ADMIN), 200)
    assert red_after["status"] == "VOIDED"
