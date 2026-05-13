"""Payout cycles, trainer tier recompute, and tier-bonus rows.

PRD §3.11.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA, SO,
    advance_clock,
    create_funded_member,
    create_pt_booking,
    create_trainer,
    create_trainer_slot,
    complete_pt_booking,
    iso_z, parse_iso,
    open_payout,
    close_payout,
    reset_clock_to,
    validate_error,
    validate_success,
)


# ===========================================================================
# Payout close requires now() >= cycle_end (PRD §3.11)
# ===========================================================================
class TestPayoutCloseWindow:

    def test_close_before_cycle_end_rejected(self, api):
        """PRD §3.11: 'Closing the cycle requires the current instant
        to be at or after cycle_end (otherwise
        ERR_PAYOUT_CYCLE_OPEN).'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        cycle = open_payout(
            cycle_start="2026-01-01T00:00:00.000Z",
            cycle_end="2026-04-01T00:00:00.000Z",
        )
        res = api.close_payout(cycle["id"], PA)
        validate_error(res, ApiErrorId.ERR_PAYOUT_CYCLE_OPEN.value)

    def test_close_at_or_after_cycle_end_succeeds(self, api):
        """PRD §3.11: 'requires the current instant to be at or after
        cycle_end.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        cycle = open_payout(
            cycle_start="2026-01-01T00:00:00.000Z",
            cycle_end="2026-04-01T00:00:00.000Z",
        )
        advance_clock("2026-04-01T00:00:00.000Z")
        closed = close_payout(cycle["id"])
        assert closed["status"] == "CLOSED"
        assert closed.get("closed_at") is not None
