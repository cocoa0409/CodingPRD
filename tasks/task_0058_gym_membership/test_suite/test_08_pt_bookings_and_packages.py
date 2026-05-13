"""PT slots, bookings (single + package), and package refunds.

PRD §3.8.
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    PA, SO,
    advance_clock,
    cancel_pt_booking,
    complete_pt_booking,
    create_funded_member,
    create_pt_booking,
    create_pt_package,
    create_trainer,
    create_trainer_slot,
    find_commission_rows,
    find_wallet_txn,
    get_card,
    iso_z, parse_iso,
    list_trainer_commissions,
    list_wallet_transactions,
    make_member_headers,
    make_trainer_headers,
    reset_clock_to,
    round_half_up,
    setup_inactive_trainer_with_published_slot,
    validate_error,
    validate_success,
)


# ===========================================================================
# Slot overlap (PRD §3.8)
# ===========================================================================
class TestSlotOverlap:

    def test_adjacent_endpoints_allowed_for_slots(self, api):
        """PRD §3.8: 'Slots that touch endpoint-to-endpoint (one slot's
        ends_at equals the next slot's starts_at) are explicitly
        allowed because the half-open semantics make them
        non-overlapping.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        a = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
        )
        # Adjacent: starts_at == a.ends_at.
        b = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at="2026-01-02T11:00:00.000Z",
            ends_at="2026-01-02T12:00:00.000Z",
        )
        assert b["id"] != a["id"]
        assert b["status"] == "OPEN"

    def test_overlapping_slot_rejected(self, api):
        """PRD §3.8: 'publishing a slot that overlaps any other slot of
        the same trainer whose status is OPEN or RESERVED is rejected
        with ERR_SLOT_OVERLAP.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at="2026-01-02T10:00:00.000Z",
            ends_at="2026-01-02T11:00:00.000Z",
        )
        res = api.create_trainer_slot(
            {"trainer_id": trainer["id"],
             "starts_at": "2026-01-02T10:30:00.000Z",
             "ends_at": "2026-01-02T11:30:00.000Z",
             "specialty_code": "STRENGTH"},
            make_trainer_headers(trainer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP.value)


# ===========================================================================
# Trainer-inactive guard (PRD §3.8)
# ===========================================================================
class TestTrainerInactiveGuard:

    def test_booking_inactive_trainer_rejected(self, api):
        """PRD §3.8: 'Inactive trainers cannot be booked or sold
        against, with rejection code ERR_TRAINER_INACTIVE.'"""
        trainer, member, slot = (
            setup_inactive_trainer_with_published_slot()
        )
        res = api.create_pt_booking(
            {"member_id": member["id"], "slot_id": slot["id"],
             "billing_mode": "SINGLE"},
            make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRAINER_INACTIVE.value)


# ===========================================================================
# PT booking single-session cycle (PRD §3.8)
# ===========================================================================
class TestPTBookingSingleSession:

    def test_complete_appends_session_commission(self, api):
        """PRD §3.8: 'A CommissionRecord of kind=SESSION is appended
        whose amount_cents is session_price_cents multiplied by the
        trainer's effective rate divided by 10,000, rounded half-up.'

        Trainer session_commission_pct_bp=1500, BRONZE (tier_modifier=0)
        → effective=1500bp. If session_price_cents=20000, commission =
        round_half_up(20000 * 1500 / 10000) = 3000.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(
            specialties=["STRENGTH"],
            session_commission_pct_bp=1_500,
        )
        # BRONZE is the default per PRD §3.8.
        assert trainer["tier"] == "BRONZE"

        s = parse_iso("2026-01-02T10:00:00.000Z")
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
        )
        member = create_funded_member(wallet_balance_cents=50_000)
        booking = create_pt_booking(
            member=member, slot=slot, billing_mode="SINGLE",
        )
        advance_clock(iso_z(s + timedelta(minutes=5)))
        completed = complete_pt_booking(booking["id"], trainer["id"])
        assert completed["status"] == "COMPLETED"

        commissions = list_trainer_commissions(trainer["id"])
        session_rows = find_commission_rows(commissions, kind="SESSION")
        assert len(session_rows) == 1
        # session_price_cents is implementation-supplied default; assert
        # only the formula structure: amount = price * 1500 / 10000,
        # half-up.  Cross-check with the price recorded on the booking.
        session_price = completed["session_price_cents"]
        expected = round_half_up(session_price * 1_500 / 10_000)
        assert session_rows[0]["amount_cents"] == expected, (
            f"PRD §3.8 session_commission: expected "
            f"round_half_up({session_price}*1500/10000) == {expected}, "
            f"got {session_rows[0]['amount_cents']}"
        )


# ===========================================================================
# Cancel windows (PRD §3.8)
# ===========================================================================
class TestPTCancellation:

    def test_cancel_at_or_after_starts_at_rejected(self, api):
        """PRD §3.8: 'Attempting to cancel at or after
        scheduled_starts_at is rejected with
        ERR_CANCEL_WINDOW_EXPIRED.'"""
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(specialties=["STRENGTH"])
        s = parse_iso("2026-01-02T10:00:00.000Z")
        e = s + timedelta(hours=1)
        slot = create_trainer_slot(
            trainer_id=trainer["id"],
            starts_at=iso_z(s), ends_at=iso_z(e),
        )
        member = create_funded_member(wallet_balance_cents=50_000)
        booking = create_pt_booking(
            member=member, slot=slot, billing_mode="SINGLE",
        )
        advance_clock(iso_z(s + timedelta(minutes=5)))
        res = api.cancel_pt_booking(
            booking["id"], make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CANCEL_WINDOW_EXPIRED.value)

# ===========================================================================
# Package sale commission (PRD §3.8)
# ===========================================================================
class TestPackageSaleCommission:

    def test_package_sale_appends_commission_row(self, api):
        """PRD §3.8: 'On successful creation, the wallet is debited for
        gross_price_cents (subject to bonus-first FIFO consumption) and
        a CommissionRecord of kind=PACKAGE_SALE is appended whose
        amount_cents equals gross_price_cents multiplied by
        Trainer.package_commission_pct_bp divided by 10,000, rounded
        half-up.'

        gross=100000, pkg_bp=800 → round_half_up(100000*800/10000)=8000.
        """
        reset_clock_to("2026-01-01T00:00:00.000Z")
        trainer = create_trainer(
            specialties=["STRENGTH"],
            package_commission_pct_bp=800,
        )
        member = create_funded_member(wallet_balance_cents=300_000)
        package = create_pt_package(
            member=member, trainer_id=trainer["id"],
            total_sessions=7, gross_price_cents=100_000,
        )
        assert package["status"] == "ACTIVE"

        commissions = list_trainer_commissions(trainer["id"])
        sale_rows = find_commission_rows(
            commissions, kind="PACKAGE_SALE",
            ref_startswith=f"PTPackage:{package['id']}",
        )
        assert len(sale_rows) == 1
        assert sale_rows[0]["amount_cents"] == 8_000, (
            "PRD §3.8 package_sale_commission: "
            "round_half_up(100000 * 800 / 10000) == 8000."
        )
