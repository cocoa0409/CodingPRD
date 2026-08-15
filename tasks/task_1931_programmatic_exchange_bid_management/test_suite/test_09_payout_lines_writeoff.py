"""Payout line holds, the release-hold branch, write-offs, and the make-good
period-overlap filter."""
from test_helpers import (
    ApiErrorId,
    approve_batch,
    assert_payout_line,
    confirm_record,
    create_batch,
    create_report,
    fill_auction,
    get_publisher,
    list_lines,
    make_finance_officer_headers,
    release_batch,
    resolve_report,
    setup_active_deal,
    submit_batch,
    validate_error,
    validate_success,
    write_off_payload,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _settled_batch_with_pending_line(api):
    """SL publisher with one UNCONFIRMED fill; batch submitted, approved, and
    released to SETTLED with the line still PENDING (payable basis 0)."""
    sc = setup_active_deal(payment_terms="SEQUENTIAL_LIABILITY")
    fill_auction(sc["pub"]["id"])
    batch = create_batch()
    submit_batch(batch["id"])
    approve_batch(batch["id"])
    settled = release_batch(batch["id"])
    assert settled["status"] == "SETTLED"
    line = list_lines(batch["id"])[0]
    return sc, batch, line


class TestHoldGatedByBatchState:
    def test_hold_on_settled_batch_rejected(self, api):
        """PRD §3.8: "Holding moves a `PENDING` line to `HELD` — allowed only
        while the parent batch is in `PENDING_APPROVAL` or `APPROVED`, and
        rejected with `ERR_LINE_NOT_PENDING` on any other line state"
        PRD §2.8: "any other state-precondition failure surfaces as
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/payout_line_hold_gated_by_batch_state
        """
        _sc, batch, line = _settled_batch_with_pending_line(api)
        assert line["status"] == "PENDING", (
            "An unconfirmed SEQUENTIAL_LIABILITY line has a zero payable basis "
            "and stays PENDING through release")
        assert line["payable_micros"] == 0

        resp = api.hold_payout_line(batch["id"], line["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_hold_leaves_line_pending(self, api):
        """PRD §3.8: "Lines still `PENDING` or `HELD` pass through untouched."
        PRD §3.8: "Holding moves a `PENDING` line to `HELD` — allowed only while
        the parent batch is in `PENDING_APPROVAL` or `APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/payout_line_hold_gated_by_batch_state
        """
        _sc, batch, line = _settled_batch_with_pending_line(api)
        resp = api.hold_payout_line(batch["id"], line["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = list_lines(batch["id"])[0]
        assert after["status"] == "PENDING", (
            "The failed hold mutates neither the line nor the settled batch")
        assert validate_success(
            api.get_payout_batch(batch["id"], ADMIN))["status"] == "SETTLED"


class TestReleaseHoldBranch:
    def test_release_hold_branches_to_pending_on_zero_payable(self, api):
        """PRD §3.8: "Releasing the hold returns a `HELD` line to circulation,
        rejected with `ERR_LINE_NOT_HELD` on anything not held: a guaranteed
        publisher's line, or any line whose `payable_micros` is above zero, goes
        back to `ELIGIBLE`, while a sequential-liability line with nothing
        payable falls back to `PENDING` instead."

        Design: Corner/state_machines/payout_line_release_hold_branches_to_pending_on_zero_payable
        """
        sc = setup_active_deal(payment_terms="SEQUENTIAL_LIABILITY")
        fill_auction(sc["pub"]["id"])  # unconfirmed
        batch = create_batch()
        submit_batch(batch["id"])
        line = list_lines(batch["id"])[0]
        assert line["status"] == "PENDING"
        assert line["payable_micros"] == 0

        held = validate_success(
            api.hold_payout_line(batch["id"], line["id"], FINANCE))
        assert_payout_line(held)
        assert held["status"] == "HELD"

        released = validate_success(
            api.release_hold_payout_line(batch["id"], line["id"], FINANCE))
        assert released["status"] == "PENDING", (
            "payable_micros == 0 on a sequential line: the branch lands on "
            "PENDING, not ELIGIBLE")
        assert released["payable_micros"] == 0


class TestWriteOff:
    def test_write_off_held_line_after_settlement(self, api):
        """PRD §3.8: "After the batch has settled, the unpaid remainder is
        closed out by write-off: the batch must be `SETTLED` — otherwise
        `ERR_BATCH_NOT_SETTLED` — the line must be `PENDING` or `HELD` ... The
        write-off snapshots the line's `payable_micros` into
        `written_off_amount_micros` — zero when nothing was payable — moves the
        line to `WRITTEN_OFF`, adds the amount to the publisher's
        `written_off_micros`, and recomputes `accrued_open_micros`"
        PRD §3.8: "Lines still `PENDING` or `HELD` pass through untouched."

        Design: Corner/state_machines/write_off_held_line_after_settlement
        """
        sc = setup_active_deal(payment_terms="SEQUENTIAL_LIABILITY")
        rec = fill_auction(sc["pub"]["id"])
        confirm_record(rec["id"])
        batch = create_batch()
        submit_batch(batch["id"])
        line = list_lines(batch["id"])[0]
        assert line["payable_micros"] == 850000
        validate_success(api.hold_payout_line(batch["id"], line["id"], FINANCE))
        approve_batch(batch["id"])
        settled = release_batch(batch["id"])
        assert settled["status"] == "SETTLED"
        publisher = get_publisher(sc["pub"]["id"])
        assert publisher["paid_out_micros"] == 0, (
            "The HELD line survived release unpaid")

        written = validate_success(api.write_off_payout_line(
            batch["id"], line["id"],
            write_off_payload("DSP never paid; excluded from release"), FINANCE))
        assert written["status"] == "WRITTEN_OFF"
        assert written["written_off_amount_micros"] == 850000, (
            "The write-off snapshots the payable amount")

        publisher = get_publisher(sc["pub"]["id"])
        assert publisher["written_off_micros"] == 850000
        assert publisher["paid_out_micros"] == 0
        assert publisher["accrued_open_micros"] == 0, (
            "850,000 lifetime net - 850,000 written off: conservation holds "
            "across the reversal")

    def test_write_off_before_settlement_rejected(self, api):
        """PRD §3.8: "the batch must be `SETTLED` — otherwise
        `ERR_BATCH_NOT_SETTLED`"

        Design: Corner/state_machines/write_off_before_settlement_rejected
        """
        sc = setup_active_deal(payment_terms="SEQUENTIAL_LIABILITY")
        fill_auction(sc["pub"]["id"])  # unconfirmed -> line PENDING, payable 0
        batch = create_batch()
        submitted = submit_batch(batch["id"])
        assert submitted["status"] == "PENDING_APPROVAL"
        line = list_lines(batch["id"])[0]

        resp = api.write_off_payout_line(batch["id"], line["id"],
                                         write_off_payload("too early"), FINANCE)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_SETTLED)
        after = list_lines(batch["id"])[0]
        assert after["status"] == "PENDING"


class TestMakeGoodPeriodOverlap:
    def test_makegood_adjustment_requires_period_overlap_with_batch(self, api):
        """PRD §3.8: "`adjustment_micros` sums the `adjustment_micros` of the
        publisher's `RESOLVED` make-good reports whose own windows overlap the
        batch window"
        PRD §3.7: "A make-good's `adjustment_micros` is immediately added to the
        publisher's `accrued_open_micros` and flows forward into the next payout
        line that covers that publisher and an overlapping period"

        Design: Corner/calculations/makegood_adjustment_requires_period_overlap_with_batch
        """
        sc = setup_active_deal(payment_terms="SEQUENTIAL_LIABILITY")
        rec = fill_auction(sc["pub"]["id"])
        confirm_record(rec["id"])
        # The report window [2026-09-15, 2026-09-30) contains no records:
        # ssp 0 vs dsp 0 -> discrepancy 0.000 -> OPEN, not auto-flagged.
        report = create_report(sc["deal"]["id"], "2026-09-15", "2026-09-30")
        assert report["status"] == "OPEN"
        assert report["auto_flagged"] is False
        resolved = resolve_report(report["id"], "MAKE_GOOD",
                                  adjustment_micros=50000)
        assert resolved["status"] == "RESOLVED"

        batch = create_batch("2026-08-01", "2026-09-01")
        submit_batch(batch["id"])
        line = list_lines(batch["id"])[0]
        assert line["adjustment_micros"] == 0, (
            "Report window [09-15, 09-30) does not overlap batch [08-01, 09-01)")
        assert line["payable_micros"] == 850000, (
            "SEQUENTIAL_LIABILITY: confirmed net only, no adjustment")

        publisher = get_publisher(sc["pub"]["id"])
        assert publisher["accrued_open_micros"] == 900000, (
            "The publisher-level accrual still carries the 50,000 make-good — "
            "line composition and publisher accrual deliberately diverge")
