"""RemittanceBatch intake: cutoff rollover, the capture/out-of-balance cycle,
the balance invariant, and close preconditions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_batch_balance_invariant,
    accept_item,
    balance_batch,
    begin_capture,
    capture_item,
    create_batch,
    get_batch,
    make_lockbox_operator_headers,
    run_close_business_day,
    set_clock,
    setup_live_lockbox,
    validate_error,
    validate_success,
)

LOCK_OP = TEST_USERS["lockbox_op_headers"]


def _lock_headers(user_id="lock-op-1"):
    return make_lockbox_operator_headers(user_id)


class TestCutoffRollover:
    def test_cutoff_exactly_at_boundary_rolls_to_next_day(self, api):
        """PRD §3.4: "if the resulting local time of day is strictly before
        `daily_cutoff_time_local`, the batch books to the bank's
        `current_business_date`; otherwise it rolls forward one business day.
        Arrival exactly at the cutoff rolls forward — the same-day window
        closes on the stroke of `daily_cutoff_time_local`."

        Design: Difficulty/boundary_precision_check/cutoff_exactly_at_boundary_rolls_to_next_day
        """
        # 2026-08-01T19:00:00Z is exactly 14:00:00 in America/Chicago (CDT).
        set_clock("2026-08-01T19:00:00Z")
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B-AT",
                             received_at="2026-08-01T19:00:00Z",
                             declared_item_count=0, declared_total_cents=0)
        # At-cutoff (>=) rolls; the next business day after Saturday
        # 2026-08-01 is Monday 2026-08-03.
        assert batch["business_date"] == "2026-08-03", (
            f"At-cutoff arrival must roll forward one business day, got "
            f"{batch['business_date']}"
        )

    def test_one_minute_before_cutoff_books_to_current_business_date(self, api):
        """PRD §3.4: "if the resulting local time of day is strictly before
        `daily_cutoff_time_local`, the batch books to the bank's
        `current_business_date`; otherwise it rolls forward one business day."

        Design: Difficulty/boundary_precision_check/cutoff_exactly_at_boundary_rolls_to_next_day
        """
        # 2026-08-01T18:59:00Z is 13:59:00 in America/Chicago — one minute
        # before the 14:00 cutoff.
        set_clock("2026-08-01T18:59:00Z")
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B-PRE",
                             received_at="2026-08-01T18:59:00Z",
                             declared_item_count=0, declared_total_cents=0)
        assert batch["business_date"] == "2026-08-01", (
            f"Strictly-before-cutoff arrival must book to the current business "
            f"date, got {batch['business_date']}"
        )

    def test_remittance_batch_computes_business_date_via_rollover(self, api):
        """PRD §3.4: "if the resulting local time of day is strictly before
        `daily_cutoff_time_local`, the batch books to the bank's
        `current_business_date`; otherwise it rolls forward one business day."
        PRD §3.1: the business-day close "advances `current_business_date` by
        one business day".

        Design: Corner/entities/remittance_batch_computes_business_date_via_rollover
        """
        ws = setup_live_lockbox()
        # Advance the logical business date to Monday 2026-08-03.
        run_close_business_day(ws)
        # 2026-08-03T10:00:00Z is 05:00 in America/Chicago — before cutoff.
        set_clock("2026-08-03T10:00:00Z")
        batch = create_batch(ws, batch_reference="B-PRE",
                             received_at="2026-08-03T10:00:00Z",
                             declared_item_count=0, declared_total_cents=0)
        assert batch["business_date"] == "2026-08-03"


class TestOutOfBalanceCycle:
    def test_force_out_of_balance_then_resume_capture(self, api):
        """PRD §3.4: "An operator may also force a batch from `CAPTURING` to
        `OUT_OF_BALANCE` directly, and from `OUT_OF_BALANCE` the operator
        resumes capture — `OUT_OF_BALANCE → CAPTURING` — to post corrections
        before balancing again."

        Design: Difficulty/non_linear_state_machine/remittance_batch_capture_out_of_balance_cycle
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        forced = validate_success(
            api.force_out_of_balance(
                ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
                ws["site"]["id"], batch["id"], LOCK_OP))
        assert forced["capture_status"] == "OUT_OF_BALANCE"
        resumed = validate_success(
            api.resume_capture(
                ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
                ws["site"]["id"], batch["id"], LOCK_OP))
        assert resumed["capture_status"] == "CAPTURING", (
            "The OUT_OF_BALANCE → CAPTURING leg completes the cycle"
        )

    def test_full_cycle_out_of_balance_resume_then_balanced(self, api):
        """PRD §3.4: "An operator may also force a batch from `CAPTURING` to
        `OUT_OF_BALANCE` directly, and from `OUT_OF_BALANCE` the operator
        resumes capture — `OUT_OF_BALANCE → CAPTURING` — to post corrections
        before balancing again."
        PRD §3.4: "When both agree, the batch advances `CAPTURING → BALANCED`."

        Design: Difficulty/non_linear_state_machine/remittance_batch_capture_out_of_balance_cycle
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        # First pass through the cycle: force out, resume, correct, balance.
        validate_success(api.force_out_of_balance(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], batch["id"], _lock_headers()))
        validate_success(api.resume_capture(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], batch["id"], _lock_headers()))
        item = capture_item(ws, batch["id"], check_number="1",
                            amount_cents=1000)
        accept_item(ws, batch["id"], item["id"])
        balanced = validate_success(balance_batch(ws, batch["id"]))
        assert balanced["capture_status"] == "BALANCED"
        assert_batch_balance_invariant(balanced)


class TestBatchBalanceInvariant:
    def test_balance_rejected_when_captured_differs_from_declared(self, api):
        """PRD §3.4: "Balancing is the reconciliation between capture and the
        courier manifest: `captured_item_count` must equal
        `declared_item_count` and `captured_total_cents` must equal
        `declared_total_cents`. When both agree, the batch advances `CAPTURING
        → BALANCED`. When either differs, the balance attempt moves the batch
        to `OUT_OF_BALANCE` and the failed invariant is reported as
        `ERR_BATCH_OUT_OF_BALANCE`."

        Design: Difficulty/compensating_invariant/batch_balance_invariant_captured_equals_declared
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=2,
                             declared_total_cents=3000)
        begin_capture(ws, batch["id"])
        capture_item(ws, batch["id"], check_number="1", amount_cents=1000)
        resp = balance_batch(ws, batch["id"])
        validate_error(resp, ApiErrorId.ERR_BATCH_OUT_OF_BALANCE)
        after = get_batch(ws, batch["id"])
        assert after["capture_status"] == "OUT_OF_BALANCE"

    def test_compensating_capture_restores_the_invariant(self, api):
        """PRD §3.4: "When both agree, the batch advances `CAPTURING →
        BALANCED`. When either differs, the balance attempt moves the batch to
        `OUT_OF_BALANCE` and the failed invariant is reported as
        `ERR_BATCH_OUT_OF_BALANCE`."
        PRD §3.4: "from `OUT_OF_BALANCE` the operator resumes capture —
        `OUT_OF_BALANCE → CAPTURING` — to post corrections before balancing
        again."

        Design: Difficulty/compensating_invariant/batch_balance_invariant_captured_equals_declared
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=2,
                             declared_total_cents=3000)
        begin_capture(ws, batch["id"])
        capture_item(ws, batch["id"], check_number="1", amount_cents=1000)
        validate_error(balance_batch(ws, batch["id"]),
                       ApiErrorId.ERR_BATCH_OUT_OF_BALANCE)
        # Compensating action: resume capture and post the missing item.
        validate_success(api.resume_capture(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], batch["id"], _lock_headers()))
        capture_item(ws, batch["id"], check_number="2", amount_cents=2000)
        balanced = validate_success(balance_batch(ws, batch["id"]))
        assert balanced["capture_status"] == "BALANCED"
        assert_batch_balance_invariant(balanced)


class TestBatchClosePreconditions:
    def test_batch_close_with_pending_items_rejected(self, api):
        """PRD §3.4: "Closing moves `BALANCED → CLOSED`. It requires that every
        item on the batch has reached `ACCEPTED`, `RETURNED`, `DECISIONED_PAY`,
        or `DECISIONED_RETURN`, and that the closer's `X-User-ID` differs from
        the operator who began capture (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.9: "5. The target resource is in a lifecycle state from which
        the requested transition is defined (`ERR_INVALID_STATE_TRANSITION`,
        409)."

        Design: Corner/state_machines/batch_close_with_pending_items_rejected
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        # The item is captured (tallies match) but never disposed of.
        capture_item(ws, batch["id"], check_number="1", amount_cents=1000)
        balanced = validate_success(balance_batch(ws, batch["id"]))
        assert balanced["capture_status"] == "BALANCED"
        resp = api.close_batch(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], batch["id"], _lock_headers("lock-op-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
