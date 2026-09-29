"""An action and its compensating action, checked for the invariant they conserve."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.assertions import assert_append_only_fields, assert_ledger_running_balance
from test_helpers.factories import reverse_reserve_transaction_payload
from test_helpers.fixtures import (
    ADMIN,
    ALPHA,
    GAMMA,
    add_reserve_transaction,
    issue_deduction_event,
    list_deduction_events_for_period,
    list_enforcement_rows,
    list_reserve_rows,
    refresh_concession,
    refresh_service_period,
    reverse_reserve_transaction,
    setup_concession_in_construction,
    setup_verified_period,
    withdraw_deduction_event,
)


class TestReserveWithdrawalThenReversal:
    def test_the_reversal_returns_the_ledger_to_the_balance_that_stood_before(self):
        """A 3,000,000 cent withdrawal and its reversal leave the seeded 8,000,000.

        PRD: "The new entry carries `txn_type` `REVERSAL`, its `reverses_txn_id`
        pointing at the target entry, an `amount_cents` copied from the target rather
        than taken from the request, and a `signed_amount_cents` that is the target's
        signed amount negated."

        Design: Difficulty/compensating_invariant/reserve_withdrawal_then_reversal_conserves_the_ledger_balance
        """
        ctx = setup_concession_in_construction()
        withdrawal = add_reserve_transaction(
            ctx, "WITHDRAWAL", 3000000, "carriageway resurfacing tranche 1"
        )
        assert withdrawal["sequence_no"] == 2
        assert withdrawal["signed_amount_cents"] == -3000000
        assert withdrawal["resulting_balance_cents"] == 5000000
        assert refresh_concession(ctx)["lifecycle_reserve_balance_cents"] == 5000000

        reversal = reverse_reserve_transaction(
            ctx, withdrawal["id"], "tranche 1 invoice cancelled by the contractor"
        )

        assert reversal["sequence_no"] == 3
        assert reversal["txn_type"] == "REVERSAL"
        assert reversal["reverses_txn_id"] == withdrawal["id"]
        assert reversal["amount_cents"] == 3000000
        assert reversal["signed_amount_cents"] == 3000000
        assert reversal["resulting_balance_cents"] == 8000000
        assert refresh_concession(ctx)["lifecycle_reserve_balance_cents"] == 8000000
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 3
        assert_ledger_running_balance(rows)
        for row in rows:
            assert_append_only_fields(row)

    def test_neither_a_second_reversal_nor_a_reversal_of_the_reversal_is_admitted(self):
        """The conserved balance cannot be disturbed by repeating the correction.

        PRD: "Three refusals apply: a target that already has a reversal pointing at
        it gives `ERR_TRANSACTION_ALREADY_REVERSED` (HTTP 409), a target that is itself
        a `REVERSAL` gives `ERR_CANNOT_REVERSE_REVERSAL` (HTTP 409), and a target that
        does not belong to the concession whose ledger is being corrected gives
        `ERR_CROSS_ENTITY_MISMATCH` (HTTP 409)."

        Design: Difficulty/compensating_invariant/reserve_withdrawal_then_reversal_conserves_the_ledger_balance
        """
        ctx = setup_concession_in_construction()
        withdrawal = add_reserve_transaction(
            ctx, "WITHDRAWAL", 3000000, "carriageway resurfacing tranche 1"
        )
        reversal = reverse_reserve_transaction(
            ctx, withdrawal["id"], "tranche 1 invoice cancelled by the contractor"
        )

        already_reversed = api_client.reverse_reserve_transaction(
            withdrawal["id"],
            reverse_reserve_transaction_payload("a second correction of the same entry"),
            ADMIN,
        )
        reversal_of_a_reversal = api_client.reverse_reserve_transaction(
            reversal["id"],
            reverse_reserve_transaction_payload("undoing the correction itself"),
            ADMIN,
        )

        validate_error(already_reversed, "ERR_TRANSACTION_ALREADY_REVERSED", 409)
        validate_error(reversal_of_a_reversal, "ERR_CANNOT_REVERSE_REVERSAL", 409)
        untouched = validate_success(
            api_client.get_reserve_transaction(withdrawal["id"], ALPHA)
        )
        assert untouched["signed_amount_cents"] == -3000000
        assert untouched["resulting_balance_cents"] == 5000000
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 3
        assert refresh_concession(ctx)["lifecycle_reserve_balance_cents"] == 8000000


class TestDeductionIssueThenWithdrawal:
    def test_issuing_a_deduction_moves_the_period_and_the_year_to_date_position(self):
        """A 400-point unavailability deduction is 500,000 cents off the net payment.

        PRD: "Its `raw_amount_cents` is its point count multiplied by the contractual
        point value of 1,250 cents — twelve dollars fifty a point — as exact integer
        arithmetic with no rounding."

        Design: Difficulty/compensating_invariant/deduction_issue_then_withdraw_conserves_the_period_payment_identity
        """
        ctx = setup_verified_period()

        event = issue_deduction_event(ctx, 400, "UNAVAILABILITY")

        assert event["sequence_no"] == 1
        assert event["status"] == "ISSUED"
        assert event["raw_amount_cents"] == 500000
        assert event["allowed_amount_cents"] == 500000
        assert event["pro_rata_amount_cents"] == 500000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 500000
        assert period["net_payment_cents"] == 8104167
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 500000
        assert concession["deduction_points_ytd"] == 400
        assert concession["persistent_breach_flag"] is False

    def test_withdrawing_it_restores_the_payment_identity_without_deleting_the_row(self):
        """The withdrawn event keeps its 400 points but contributes nothing to the money.

        PRD: "Withdrawal is the compensating action for issue and is admitted from
        either `ISSUED` or `DISPUTED`; the event lands in `WITHDRAWN` with both
        `allowed_amount_cents` and `pro_rata_amount_cents` set to zero, and it thereby
        leaves the allocation input set."

        Design: Difficulty/compensating_invariant/deduction_issue_then_withdraw_conserves_the_period_payment_identity
        """
        ctx = setup_verified_period()
        event = issue_deduction_event(ctx, 400, "UNAVAILABILITY")

        withdrawn = withdraw_deduction_event(
            ctx,
            event["id"],
            "the March log was double counted against the wrong asset",
            GAMMA,
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["allowed_amount_cents"] == 0
        assert withdrawn["pro_rata_amount_cents"] == 0
        assert withdrawn["points"] == 400
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 0
        assert period["net_payment_cents"] == 8604167
        assert period["payment_status"] == "UNBILLED"
        assert period["reporting_status"] == "VERIFIED"
        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 0
        assert concession["deduction_points_ytd"] == 0
        assert concession["persistent_breach_flag"] is False
        rows, meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == event["id"]
        _, withdrawn_meta = list_deduction_events_for_period(
            ctx["service_period_id"], status="WITHDRAWN"
        )
        assert withdrawn_meta["total_count"] == 1
        _, enforcement_meta = list_enforcement_rows(ctx["concession_id"])
        assert enforcement_meta["total_count"] == 0
