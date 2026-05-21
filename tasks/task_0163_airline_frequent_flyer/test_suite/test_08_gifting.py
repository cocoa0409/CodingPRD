"""Gifting points — round-then-subtract fee, daily cap, idempotency."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GIFT_MAX_PER_DAY_PER_SENDER,
    GIFT_MIN,
    create_gift_payload,
    create_member,
    create_member_with_balance,
    filter_transactions_by_kind,
    get_member,
    list_points_transactions,
    make_member_headers,
    validate_error,
    validate_success,
)


class TestGiftMinimum:

    def test_amount_below_minimum_rejected(self, api):
        """PRD §3.6: "The amount must be at least 1 000 — a smaller gift
        is rejected with ERR_GIFT_BELOW_MINIMUM."
        """
        sender = create_member_with_balance(20_000)
        recipient = create_member()
        resp = api.send_gift(
            sender["id"],
            create_gift_payload(recipient["id"], amount=999),
            make_member_headers(sender["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GIFT_BELOW_MINIMUM.value)

    def test_amount_at_minimum_accepted(self, api):
        """PRD §3.6: "The amount must be at least 1 000" — boundary
        at exactly the minimum is accepted.
        """
        sender = create_member_with_balance(20_000)
        recipient = create_member()
        validate_success(
            api.send_gift(
                sender["id"],
                create_gift_payload(recipient["id"], amount=GIFT_MIN),
                make_member_headers(sender["id"]),
            ),
            expected_status=201,
        )


class TestGiftDailyCap:

    def test_daily_cap_exceeded_rejected(self, api):
        """PRD §3.6: "The same sender cannot gift more than 50 000
        points across all gift requests within a single UTC calendar
        day; the cumulative cap is evaluated against the proposed
        amount, and any gift that would push the day's total over the
        cap is rejected with ERR_GIFT_DAILY_CAP_EXCEEDED."
        """
        sender = create_member_with_balance(200_000)
        recipient = create_member()
        # First gift at the cap.
        validate_success(
            api.send_gift(
                sender["id"],
                create_gift_payload(
                    recipient["id"], amount=GIFT_MAX_PER_DAY_PER_SENDER,
                ),
                make_member_headers(sender["id"]),
            ),
            expected_status=201,
        )
        # Second gift on the same day — pushes total over the cap.
        resp = api.send_gift(
            sender["id"],
            create_gift_payload(recipient["id"], amount=1_000),
            make_member_headers(sender["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GIFT_DAILY_CAP_EXCEEDED.value)


class TestGiftFeeRoundingOrder:

    def test_round_then_subtract_at_2505_yields_2254(self, api):
        """PRD §3.6: "an amount of 2 505 produces a raw fee of 250.5;
        rounded half-up that becomes 251; delivered_points is then
        2 505 minus 251, which equals 2 254. A 'subtract-then-round'
        implementation would yield 2 255 — which is the wrong answer."

        # difficulty: combinatorial_formula/gift_transfer_nested_rounding_mode_b
        Claim: at amount=2505 the recipient ledger row has
        points_delta=+2254, NOT +2255.
        """
        sender = create_member_with_balance(10_000)
        recipient = create_member_with_balance(0)
        validate_success(
            api.send_gift(
                sender["id"],
                create_gift_payload(recipient["id"], amount=2_505),
                make_member_headers(sender["id"]),
            ),
            expected_status=201,
        )
        # Recipient balance.
        rec_after = get_member(recipient["id"])
        assert rec_after["points_balance"] == 2_254, (
            "PRD §3.6: delivered_points = amount - round_half_up(amount * "
            "0.10) = 2505 - 251 = 2254 (NOT 2255)."
        )
        # Sender balance: 10000 - 2505 = 7495.
        snd_after = get_member(sender["id"])
        assert snd_after["points_balance"] == 7_495, (
            "PRD §3.6: GIFT_OUT debits the full amount (2505) on the "
            "sender; the fee is informational."
        )

    def test_three_row_atomic_ledger(self, api):
        """PRD §3.6: "A successful gift appends exactly three rows to
        the ledger, in this fixed order, sharing a single transaction:
        first a GIFT_OUT on the sender with points_delta equal to
        -amount and counterparty_member_id set to the recipient; second
        a GIFT_FEE on the sender with points_delta equal to 0 (the fee
        is informational because the sent amount already includes it);
        third a GIFT_IN on the recipient with points_delta equal to
        +delivered_points and counterparty_member_id set to the sender."
        """
        sender = create_member_with_balance(10_000)
        recipient = create_member_with_balance(0)
        validate_success(
            api.send_gift(
                sender["id"],
                create_gift_payload(recipient["id"], amount=2_505),
                make_member_headers(sender["id"]),
            ),
            expected_status=201,
        )
        # Sender ledger has GIFT_OUT(-2505) and GIFT_FEE(0).
        snd_ledger = list_points_transactions(sender["id"])
        gift_outs = filter_transactions_by_kind(snd_ledger, "GIFT_OUT")
        gift_fees = filter_transactions_by_kind(snd_ledger, "GIFT_FEE")
        assert len(gift_outs) == 1
        assert gift_outs[0]["points_delta"] == -2_505
        assert gift_outs[0].get("counterparty_member_id") == recipient["id"]
        assert len(gift_fees) == 1
        assert gift_fees[0]["points_delta"] == 0
        # Recipient ledger has GIFT_IN(+2254).
        rec_ledger = list_points_transactions(recipient["id"])
        gift_ins = filter_transactions_by_kind(rec_ledger, "GIFT_IN")
        assert len(gift_ins) == 1
        assert gift_ins[0]["points_delta"] == 2_254
        assert gift_ins[0].get("counterparty_member_id") == sender["id"]


class TestGiftInsufficientPoints:

    def test_insufficient_balance_rejected(self, api):
        """PRD §3.6: "The sender's points_balance must be at least
        amount; otherwise the gift is rejected with
        ERR_INSUFFICIENT_POINTS."
        """
        sender = create_member_with_balance(500)
        recipient = create_member()
        resp = api.send_gift(
            sender["id"],
            create_gift_payload(recipient["id"], amount=GIFT_MIN),
            make_member_headers(sender["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


class TestIdempotency:

    def test_same_key_different_payload_rejected(self, api):
        """PRD §3.6: "A repeat with the same (member_id,
        idempotency_key) but a different payload is the conflict case
        and is rejected with ERR_IDEMPOTENCY_CONFLICT."
        """
        sender = create_member_with_balance(20_000)
        recipient_a = create_member()
        recipient_b = create_member()
        validate_success(
            api.send_gift(
                sender["id"],
                create_gift_payload(
                    recipient_a["id"], amount=1_000,
                    idempotency_key="dupe-key-1",
                ),
                make_member_headers(sender["id"]),
            ),
            expected_status=201,
        )
        # Same key, different recipient — conflict.
        resp = api.send_gift(
            sender["id"],
            create_gift_payload(
                recipient_b["id"], amount=1_000,
                idempotency_key="dupe-key-1",
            ),
            make_member_headers(sender["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value)
