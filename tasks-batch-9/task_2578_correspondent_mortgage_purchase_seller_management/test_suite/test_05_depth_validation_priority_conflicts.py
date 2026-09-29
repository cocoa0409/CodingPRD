"""Requests that break two rules at once, and which rule has to answer."""

from test_helpers import (
    REVIEWER,
    TRADER,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


class TestPairedOffLineBeatsCapacity:
    """A terminal line answers on its state, never on its exhausted capacity."""

    @staticmethod
    def _paired_off_line() -> dict:
        staged = fixtures.setup_locked_commitment(
            commitment_overrides={"notional_amount_cents": 40000000}
        )
        staged["commitment"] = fixtures.pair_off_commitment(
            staged["commitment_id"], 100.500
        )
        return staged

    def test_delivery_into_a_paired_off_line_is_refused_on_the_line_state(self):
        """The line is closed out and also has no room; the state answers.

        A 50,000,000 delivery into a paired-off 40,000,000 line breaks both the
        state precondition and the capacity ceiling, since the residual is zero.
        The closed-out state is what the caller is told about.

        PRD: "`FULFILLED`, `PAIRED_OFF`, `EXPIRED` and `CANCELLED` are all
        terminal — a commitment in any of them accepts nothing further, and an
        attempt to deliver against one or pair one off is refused with
        `ERR_COMMITMENT_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/paired_off_commitment_state_beats_capacity_exceeded_on_delivery
        """
        staged = self._paired_off_line()
        commitment = staged["commitment"]
        assert commitment["status"] == "PAIRED_OFF"
        assert commitment["available_amount_cents"] == 0
        assert commitment["pair_off_fee_cents"] == 173960

        response = api_client.deliver_loan(
            staged["commitment_id"],
            factories.loan_payload(
                commitment["version"],
                seller_loan_number="HP-7001",
                note_amount_cents=50000000,
                servicing_election="RELEASED",
                escrow_balance_cents=320000,
                closing_date="2026-07-20",
            ),
            staged["seller_headers"],
        )

        error = validate_error(response, ApiErrorId.ERR_COMMITMENT_NOT_OPEN, 409)
        assert error["error_id"] != ApiErrorId.ERR_COMMITMENT_CAPACITY_EXCEEDED.value

    def test_the_rejected_delivery_leaves_no_loan_and_no_amount_movement(self):
        """Losing on the state check means the capacity check never runs.

        Capacity is the very last gate on a delivery, so the request dies well
        before it, no loan is created, and the paired-off line keeps the amounts
        and the fee it took when it was closed out.

        PRD: "And last of all, the delivered `note_amount_cents` must not exceed
        the commitment's `available_amount_cents`, else
        `ERR_COMMITMENT_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/paired_off_commitment_state_beats_capacity_exceeded_on_delivery
        """
        staged = self._paired_off_line()

        api_client.deliver_loan(
            staged["commitment_id"],
            factories.loan_payload(
                staged["commitment"]["version"],
                seller_loan_number="HP-7001",
                note_amount_cents=50000000,
                servicing_election="RELEASED",
                escrow_balance_cents=320000,
                closing_date="2026-07-20",
            ),
            staged["seller_headers"],
        )

        loans, meta = validate_paginated(
            api_client.list_loans(REVIEWER, {"commitment_id": staged["commitment_id"]})
        )
        assert loans == []
        assert meta["total_count"] == 0

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "PAIRED_OFF"
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["paired_off_amount_cents"] == 40000000
        assert commitment["pair_off_fee_cents"] == 173960


class TestSuspendedSellerBeatsExpiredWindow:
    """The counterparty gate answers before the calendar does."""

    @staticmethod
    def _suspended_seller_past_the_window() -> dict:
        staged = fixtures.setup_locked_commitment(
            commitment_overrides={
                "notional_amount_cents": 40000000,
                "delivery_expiry_date": "2026-08-15",
            }
        )
        staged["locked_version"] = staged["commitment"]["version"]
        fixtures.apply_standing_action(staged["seller_id"], "SUSPEND")
        fixtures.setup_clock("2026-08-20T00:00:00Z")
        return staged

    def test_a_suspended_seller_is_told_about_its_standing_not_the_window(self):
        """Standing and calendar both bar the delivery; standing answers.

        At the 2026-08-20 clock the line's window closed on 2026-08-15, and the
        seller has been manually suspended on top of that. The counterparty gate
        is the one that refuses the file.

        PRD: "The owning seller's `delivery_standing` must be `GOOD_STANDING` or
        `WATCH`, else `ERR_SELLER_DELIVERY_SUSPENDED` — a seller suspended after
        locking may not deliver into its surviving lines."

        Design: Difficulty/priority_pair_validation_conflict/suspended_seller_beats_expired_commitment_on_delivery
        """
        staged = self._suspended_seller_past_the_window()

        response = api_client.deliver_loan(
            staged["commitment_id"],
            factories.loan_payload(
                staged["locked_version"],
                seller_loan_number="HP-7101",
                note_amount_cents=40000000,
                servicing_election="RELEASED",
                escrow_balance_cents=320000,
                closing_date="2026-07-20",
            ),
            staged["seller_headers"],
        )

        error = validate_error(response, ApiErrorId.ERR_SELLER_DELIVERY_SUSPENDED, 409)
        assert error["error_id"] != ApiErrorId.ERR_COMMITMENT_EXPIRED.value

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["delivery_standing"] == "SUSPENDED"
        assert seller["suspension_reason"] == "MANUAL_COUNTERPARTY_ACTION"

    def test_the_line_is_still_open_and_untouched_after_the_refusal(self):
        """No sweep has run, so the stale window has not moved the line at all.

        The commitment is still locked with its full capacity available even
        though the clock is five days past its expiry date, because expiry only
        bites through the sweep, and the refused delivery creates nothing.

        PRD: "The logical clock must fall inside the commitment's half-open
        delivery window, from `delivery_window_start` at midnight UTC up to but
        not including `delivery_expiry_date` at midnight UTC — a delivery
        attempted on the expiry date itself is already too late and is refused
        with `ERR_COMMITMENT_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_seller_beats_expired_commitment_on_delivery
        """
        staged = self._suspended_seller_past_the_window()

        api_client.deliver_loan(
            staged["commitment_id"],
            factories.loan_payload(
                staged["locked_version"],
                seller_loan_number="HP-7101",
                note_amount_cents=40000000,
                servicing_election="RELEASED",
                escrow_balance_cents=320000,
                closing_date="2026-07-20",
            ),
            staged["seller_headers"],
        )

        commitment = fixtures.read_commitment(staged["commitment_id"], TRADER)
        assert commitment["status"] == "LOCKED"
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["available_amount_cents"] == 40000000

        loans, meta = validate_paginated(
            api_client.list_loans(REVIEWER, {"commitment_id": staged["commitment_id"]})
        )
        assert loans == []
        assert meta["total_count"] == 0
