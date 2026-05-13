"""Concurrency / race outcomes that PRD §3.12 explicitly nominates.

Only PRD-stated outcomes are tested:
- Two refund attempts on the same card serialise; loser sees
  ERR_INVALID_STATE.
- Two members racing for the last seat in a TrainerSlot: exactly one
  wins; loser sees ERR_SLOT_ALREADY_RESERVED.
- Two simultaneous PATCHes on the same entity with the same prior
  version: exactly one wins; loser sees ERR_VERSION_CONFLICT.

PRD §3.12.
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    PA, SO,
    assert_exactly_one_succeeds,
    create_funded_member,
    create_pt_booking_payload,
    create_trainer,
    create_trainer_slot,
    iso_z, parse_iso,
    make_member_headers,
    make_trainer_headers,
    reset_clock_to,
    run_race,
    setup_annual_card_at_remaining_days,
    validate_error,
    validate_error_is_one_of,
)


# ===========================================================================
# Refund-vs-refund race (PRD §3.12)
# ===========================================================================
class TestConcurrentRefundOnSameCard:

    def test_loser_sees_invalid_state(self, api):
        """PRD §3.12: 'Two simultaneous refund attempts on the same
        card serialise on the card's status flip: exactly one wins and
        moves the card ACTIVE → REFUNDED; the loser receives
        ERR_INVALID_STATE because the card is no longer ACTIVE.'"""
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=100,
            refund_eligibility_days=0,
            max_freeze_days=0,
        )
        results = run_race(
            lambda: api.refund_card(card["id"], SO),
            lambda: api.refund_card(card["id"], SO),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser should carry ERR_INVALID_STATE.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Slot-claim race (PRD §3.12)
# ===========================================================================
class TestConcurrentSlotClaim:

    def test_loser_sees_slot_already_reserved(self, api):
        """PRD §3.12: 'Two members simultaneously booking the last
        open slot of a TrainerSlot will serialise on the slot's
        status flip: exactly one becomes CONFIRMED and the slot
        transitions OPEN → RESERVED atomically with that booking row;
        the other receives ERR_SLOT_ALREADY_RESERVED.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        s = parse_iso("2026-01-05T10:00:00.000Z")
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
        )
        m1 = create_funded_member(wallet_balance_cents=200_000)
        m2 = create_funded_member(wallet_balance_cents=200_000)
        h1 = make_member_headers(m1["id"])
        h2 = make_member_headers(m2["id"])
        results = run_race(
            lambda: api.create_pt_booking(
                create_pt_booking_payload(
                    member_id=m1["id"], slot_id=slot["id"],
                    billing_mode="SINGLE",
                ),
                h1,
            ),
            lambda: api.create_pt_booking(
                create_pt_booking_payload(
                    member_id=m2["id"], slot_id=slot["id"],
                    billing_mode="SINGLE",
                ),
                h2,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_SLOT_ALREADY_RESERVED.value)


# ===========================================================================
# OCC version race (PRD §2.5, §3.12)
# ===========================================================================
class TestConcurrentVersionConflict:

    def test_loser_sees_version_conflict(self, api):
        """PRD §3.12: 'Two simultaneous patches against the same
        entity carrying the same prior version serialise on the OCC
        check (see §2.5): exactly one wins; the loser receives
        ERR_VERSION_CONFLICT.'"""
        member = create_funded_member(wallet_balance_cents=10_000)
        # Both racers patch with version == member['version'].
        prior_version = member["version"]
        h = make_member_headers(member["id"])
        results = run_race(
            lambda: api.patch_member(
                member["id"],
                {"version": prior_version,
                 "notification_channels": ["SMS"]},
                h,
            ),
            lambda: api.patch_member(
                member["id"],
                {"version": prior_version,
                 "notification_channels": ["EMAIL"]},
                h,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_VERSION_CONFLICT.value)
