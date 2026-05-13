"""Card freeze episodes: request, approve, settle, cancel, and the
freeze budget guard.

PRD §3.5.
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    PA, SO,
    advance_clock,
    freeze_card,
    get_card,
    iso_z, parse_iso,
    make_member_headers,
    setup_card_with_confirmed_pt_booking_in_freeze_window,
    setup_member_with_active_card,
    unfreeze_card,
    validate_error,
    validate_error_is_one_of,
)


# ===========================================================================
# Freeze cascades card to FROZEN (PRD §3.5)
# ===========================================================================
class TestFreezeApproveCascade:

    def test_freeze_cascades_card_to_frozen(self, api):
        """PRD §3.5: 'The owning card cascades from ACTIVE to FROZEN,
        its cumulative_freeze_days rises by the episode's actual_days,
        and an access-control revoke event is emitted carrying the
        card id and the episode's ends_at.'"""
        _, _, card = setup_member_with_active_card(
            category="MONTHLY",
            card_type_overrides={"max_freeze_days": 14},
        )
        episode = freeze_card(card["id"], requested_days=5)
        assert episode["status"] == "APPROVED"
        assert episode["actual_days"] == 5
        after = get_card(card["id"])
        assert after["status"] == "FROZEN"
        assert after["cumulative_freeze_days"] == 5


# ===========================================================================
# Freeze budget exhaustion (PRD §3.5)
# ===========================================================================
class TestFreezeBudgetExhaustion:

    def test_zero_budget_rejected(self, api):
        """PRD §3.5: 'The remaining freeze budget —
        CardType.max_freeze_days minus Card.cumulative_freeze_days —
        must be strictly greater than zero; when it is exactly zero,
        the system creates a FreezeEpisode in REQUESTED status and
        immediately moves it to REJECTED, returning
        ERR_FREEZE_BUDGET_EXHAUSTED.'"""
        _, _, card = setup_member_with_active_card(
            category="ANNUAL",
            card_type_overrides={"max_freeze_days": 0},
        )
        res = api.freeze_card(
            card["id"], {"reason": "ILLNESS", "requested_days": 3}, SO,
        )
        validate_error(res, ApiErrorId.ERR_FREEZE_BUDGET_EXHAUSTED.value)


# ===========================================================================
# Freeze conflicts with booking (PRD §3.5)
# ===========================================================================
class TestFreezeConflictWithPTBooking:

    def test_freeze_blocked_by_confirmed_pt_booking_in_window(self, api):
        """PRD §3.5: 'it must have no PTBooking in CONFIRMED status
        whose scheduled_starts_at falls inside the proposed freeze
        window — that cross-entity guard is rejected with
        ERR_FREEZE_CONFLICTS_WITH_BOOKING.'"""
        _, _, card, _ = (
            setup_card_with_confirmed_pt_booking_in_freeze_window(
                booking_offset_days=3,
            )
        )
        res = api.freeze_card(
            card["id"], {"reason": "ILLNESS", "requested_days": 7}, SO,
        )
        validate_error(res, ApiErrorId.ERR_FREEZE_CONFLICTS_WITH_BOOKING.value)
        # Card status must remain ACTIVE.
        after = get_card(card["id"])
        assert after["status"] == "ACTIVE", (
            "PRD §3.5: cross-entity guard rejects without transitioning "
            "the card."
        )


# ===========================================================================
# Freeze in progress (PRD §3.5)
# ===========================================================================
class TestFreezeInProgressBlocksNewFreeze:

    def test_second_concurrent_freeze_rejected(self, api):
        """PRD §3.5: 'The card must additionally have no concurrent
        freeze already in APPROVED status (rejected with
        ERR_FREEZE_IN_PROGRESS).'"""
        _, _, card = setup_member_with_active_card(
            category="ANNUAL",
            card_type_overrides={"max_freeze_days": 30},
        )
        freeze_card(card["id"], requested_days=5)
        # Second freeze while first is APPROVED → ERR_FREEZE_IN_PROGRESS.
        # PRD §3.5 names ERR_FREEZE_IN_PROGRESS for the concurrent-freeze
        # guard, but the card cascades to FROZEN after the first freeze,
        # so an implementer applying preconditions in prose order may
        # surface ERR_INVALID_STATE first. Both readings are PRD-faithful.
        res = api.freeze_card(
            card["id"], {"reason": "ILLNESS", "requested_days": 5}, SO,
        )
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_FREEZE_IN_PROGRESS.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ===========================================================================
# Freeze settles on clock cross (PRD §3.5)
# ===========================================================================
class TestFreezeSettlesOnClockCross:

    def test_clock_cross_settles_freeze(self, api):
        """PRD §3.5: 'When the clock crosses ends_at, the system settles
        the episode (APPROVED → SETTLED) and brings the card back from
        FROZEN to ACTIVE.'"""
        _, _, card = setup_member_with_active_card(
            category="ANNUAL",
            card_type_overrides={"max_freeze_days": 14},
        )
        ep = freeze_card(card["id"], requested_days=3)
        # Advance past ep.ends_at.
        target = parse_iso(ep["ends_at"]) + timedelta(minutes=1)
        advance_clock(iso_z(target))
        after = get_card(card["id"])
        assert after["status"] == "ACTIVE", (
            "PRD §3.5: clock cross brings the card back from FROZEN to "
            "ACTIVE."
        )


# ===========================================================================
# Early unfreeze (PRD §3.5)
# ===========================================================================
class TestEarlyUnfreeze:

    def test_unfreeze_returns_card_to_active(self, api):
        """PRD §3.5: 'When a member or operator invokes the
        early-unfreeze capability before ends_at ..., the episode
        transitions APPROVED → CANCELED ... the card transitions back
        to ACTIVE.'"""
        _, _, card = setup_member_with_active_card(
            category="ANNUAL",
            card_type_overrides={"max_freeze_days": 14},
        )
        ep = freeze_card(card["id"], requested_days=5)
        # Move a small bump but stay inside the freeze window.
        target = parse_iso(ep["starts_at"]) + timedelta(hours=2)
        advance_clock(iso_z(target))
        unfreeze_card(card["id"], ep["id"])
        after = get_card(card["id"])
        assert after["status"] == "ACTIVE"
