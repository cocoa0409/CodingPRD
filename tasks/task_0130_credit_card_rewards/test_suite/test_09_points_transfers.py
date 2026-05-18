"""Points transfers to partners — PRD §3.7.

Coverage:
- Successful transfer creates PENDING, debits balance, appends
  TRANSFER_DEBIT row.
- requested_partner_units zero -> ERR_INVALID_TRANSFER_INCREMENT.
- Not a multiple of min_transfer_increment ->
  ERR_INVALID_TRANSFER_INCREMENT.
- Exact-multiple boundaries succeed.
- Inactive partner -> ERR_PARTNER_INACTIVE.
- Insufficient points -> ERR_INSUFFICIENT_POINTS.
- Confirm advances PENDING -> COMPLETED with completed_at set.
- Reverse appends TRANSFER_REVERSE row and restores balance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    confirm_points_transfer,
    create_points_transfer_payload,
    find_ledger_entries,
    get_ledger,
    initiate_points_transfer,
    make_cardholder_headers,
    re_get_account,
    register_partner,
    reverse_points_transfer,
    setup_platinum_with_high_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful transfer — PRD §3.7
# ===========================================================================
class TestTransferCreation:

    def test_transfer_creates_pending_with_ledger_debit(self, api):
        """PRD §3.7: "On success the server creates the PointsTransfer
        in PENDING status, mints initiated_at and leaves completed_at
        null until acknowledgement, appends a TRANSFER_DEBIT ledger
        entry whose delta_points is the negation of points_debited,
        recomputes the account's points_balance, and sets
        last_qualifying_activity_at to the current clock instant."

        Claim: a transfer at conversion=10 of 1000 partner units debits
        10,000 points, returns PENDING with completed_at null, and a
        TRANSFER_DEBIT row appears with delta_points == -10000.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        before_balance = acc["points_balance"]
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        assert transfer["status"] == "PENDING"
        assert transfer["completed_at"] is None
        assert transfer["points_debited"] == 10_000
        ledger = get_ledger(acc["id"])
        debit_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_DEBIT",
            source_entity_id=transfer["id"],
        )
        assert len(debit_rows) == 1
        assert debit_rows[0]["delta_points"] == -10_000
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == before_balance - 10_000


# ===========================================================================
# Increment & shape validation — PRD §3.7
# ===========================================================================
class TestTransferIncrement:

    def test_zero_units_rejected(self, api):
        """PRD §3.7: "verifies that requested_partner_units is strictly
        greater than zero and that the remainder of
        requested_partner_units divided by the partner's
        min_transfer_increment is zero — that is, the requested units
        must be a positive integer multiple of the partner's minimum
        increment (otherwise ERR_INVALID_TRANSFER_INCREMENT)".

        Claim: requested_partner_units == 0 ->
        ERR_INVALID_TRANSFER_INCREMENT.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=acc["id"], partner_id=partner["id"],
                requested_partner_units=0,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_TRANSFER_INCREMENT.value,
        )

    def test_partial_multiple_rejected(self, api):
        """PRD §3.7: "the requested units must be a positive integer
        multiple of the partner's minimum increment (otherwise
        ERR_INVALID_TRANSFER_INCREMENT)".

        Claim: requested=1500 with min_increment=1000 ->
        ERR_INVALID_TRANSFER_INCREMENT.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=acc["id"], partner_id=partner["id"],
                requested_partner_units=1_500,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_TRANSFER_INCREMENT.value,
        )

    @pytest.mark.parametrize("units", [1_000, 2_000, 3_000])
    def test_exact_multiple_accepted(self, api, units):
        """PRD §3.7: "the requested units must be a positive integer
        multiple of the partner's minimum increment".

        Claim: exact-multiple values (1000, 2000, 3000 at increment=1000)
        succeed and produce points_debited == units * 10.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=units,
        )
        assert transfer["points_debited"] == units * 10


# ===========================================================================
# Inactive partner — PRD §3.7
# ===========================================================================
class TestInactivePartner:

    def test_inactive_partner_rejected(self, api):
        """PRD §3.7: "The server first verifies the partner's is_active
        is true (otherwise ERR_PARTNER_INACTIVE)".

        Claim: a transfer to a partner whose is_active==False is
        rejected with ERR_PARTNER_INACTIVE.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000, is_active=False,
        )
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=acc["id"], partner_id=partner["id"],
                requested_partner_units=1_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTNER_INACTIVE.value)


# ===========================================================================
# Insufficient balance — PRD §3.7
# ===========================================================================
class TestTransferInsufficient:

    def test_transfer_above_balance_rejected(self, api):
        """PRD §3.7: "If points_debited exceeds the account's
        points_balance, the request is rejected with
        ERR_INSUFFICIENT_POINTS."

        Claim: requesting points_debited > points_balance ->
        ERR_INSUFFICIENT_POINTS.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        # acc points_balance is ~172,500. Request units big enough that
        # points_debited > balance.
        units = (acc["points_balance"] // 10) + 1_000
        # Round up to next multiple of 1000.
        units = ((units + 999) // 1000) * 1000
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=acc["id"], partner_id=partner["id"],
                requested_partner_units=units,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ===========================================================================
# Confirm transition — PRD §3.7
# ===========================================================================
class TestTransferConfirm:

    def test_confirm_advances_to_completed_with_completed_at(self, api):
        """PRD §3.7: "A PlatformAdmin confirms the transfer by
        acknowledging on behalf of the simulated partner, requiring the
        account's lifecycle_state to be ACTIVE and the transfer's
        status to be PENDING; on success the status advances to
        COMPLETED, completed_at is minted, and
        last_qualifying_activity_at is refreshed once more."

        Claim: confirm on PENDING returns COMPLETED with completed_at
        populated.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        confirmed = confirm_points_transfer(transfer["id"])
        assert confirmed["status"] == "COMPLETED"
        assert confirmed.get("completed_at") is not None


# ===========================================================================
# Reverse transition — PRD §3.7
# ===========================================================================
class TestTransferReverse:

    def test_reverse_restores_balance_and_appends_ledger_row(self, api):
        """PRD §3.7: "A pending transfer may be reversed manually by
        either the cardholder themselves or a PlatformAdmin, or by
        cascade from the account moving to DELINQUENT or CLOSED;
        reversal appends a TRANSFER_REVERSE ledger entry whose
        delta_points is the positive points_debited, advances the
        transfer status to REVERSED, and recomputes the account's
        points_balance (the invariant is that the TRANSFER_DEBIT plus
        TRANSFER_REVERSE pair sums to a net delta of zero points)."

        Claim: a Cardholder-initiated reversal of a PENDING transfer
        restores points_balance to its pre-transfer value and emits
        TRANSFER_REVERSE with +points_debited.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        balance_before = acc["points_balance"]
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        # Reverse as Cardholder.
        reversed_xfer = reverse_points_transfer(
            transfer_id=transfer["id"], cardholder_id=ch["id"],
        )
        assert reversed_xfer["status"] == "REVERSED"
        ledger = get_ledger(acc["id"])
        rev_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_REVERSE",
            source_entity_id=transfer["id"],
        )
        assert len(rev_rows) == 1
        assert rev_rows[0]["delta_points"] == transfer["points_debited"]
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == balance_before
