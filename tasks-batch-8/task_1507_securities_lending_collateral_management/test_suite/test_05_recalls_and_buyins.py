"""Recalls: issuance guards, extension, cancel, fail fees, buy-ins."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_loan,
    get_recall,
    issue_recall,
    list_ledger_entries,
    make_borrower_rep_headers,
    make_owner_rep_headers,
    return_shares,
    run_mtm,
    set_clock,
    setup_booked_loan,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
OPS = TEST_USERS["ops_settler_headers"]


def _recall_setup(api, symbol, quantity=1000, reason="SALE",
                  deadline="2026-08-10"):
    """BOOKED loan plus one ISSUED full recall. Returns (ctx, recall)."""
    ctx = setup_booked_loan(security_symbol=symbol, loan_quantity=quantity)
    recall = issue_recall(ctx["loan"], ctx["owner"], quantity,
                          reason=reason, deadline_date=deadline)
    return ctx, recall


class TestRecallIssuance:
    def test_deadline_must_be_strictly_after_issue(self, api):
        """PRD §3.7: "a `deadline_date` that must be strictly after the
        current date (`ERR_RECALL_WINDOW_INVALID`)"

        Design: Corner/errors/recall_deadline_must_be_strictly_after_issue
        """
        ctx = setup_booked_loan(security_symbol="RW1", loan_quantity=1000)
        # Clock date is 2026-08-01: same-day deadline rejected.
        resp = api.create_recall(
            ctx["loan"]["id"],
            {"quantity": 1000, "reason": "SALE", "deadline_date": "2026-08-01"},
            make_owner_rep_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RECALL_WINDOW_INVALID)
        # Earliest legal deadline is the next calendar day.
        ok = validate_success(api.create_recall(
            ctx["loan"]["id"],
            {"quantity": 1000, "reason": "SALE", "deadline_date": "2026-08-02"},
            make_owner_rep_headers(ctx["owner"]["id"])), expected_status=201)
        assert ok["status"] == "ISSUED"
        assert get_loan(ctx["loan"]["id"])["status"] == "RECALLED"

    def test_second_recall_on_same_loan_rejected(self, api):
        """PRD §3.7: "A loan may carry at most one recall in a non-terminal
        state — `ISSUED`, `EXTENDED`, or `FAILED` — and issuing a second
        while one is open is rejected with `ERR_RECALL_ALREADY_OPEN`."

        Design: Corner/state_machines/second_recall_on_same_loan_rejected
        """
        ctx, recall = _recall_setup(api, "SMB", reason="VOTE",
                                    deadline="2026-08-10")
        resp = api.create_recall(
            ctx["loan"]["id"],
            {"quantity": 1000, "reason": "SALE", "deadline_date": "2026-08-12"},
            make_owner_rep_headers(ctx["owner"]["id"]))
        # PRD §2.7: state check (6) precedes structural rule (8) — a
        # faithful reader may report ERR_INVALID_STATE (loan not BOOKED)
        # or ERR_RECALL_ALREADY_OPEN (loan already has a non-terminal recall).
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_RECALL_ALREADY_OPEN,
                   ApiErrorId.ERR_INVALID_STATE])
        recalls = validate_success(api.list_recalls(
            TRADER, params={"loan_id": ctx["loan"]["id"]}))
        assert len(recalls) == 1


class TestRecallExtend:
    def test_recall_extend_only_once(self, api):
        """PRD §3.7: "An owner may extend an `ISSUED` recall exactly once,
        supplying a `new_deadline_date` that must push the deadline strictly
        later (`ERR_RECALL_WINDOW_INVALID`); the extension moves the recall
        to `EXTENDED`, writes the new `deadline_date`, and flips
        `extended_once` to true, and a second extension attempt is rejected
        with `ERR_RECALL_ALREADY_EXTENDED`."

        Design: Corner/state_machines/recall_extend_only_once
        """
        ctx, recall = _recall_setup(api, "SM5", deadline="2026-08-03")
        owner_headers = make_owner_rep_headers(ctx["owner"]["id"])
        extended = validate_success(api.extend_recall(
            recall["id"], {"new_deadline_date": "2026-08-05"},
            owner_headers))
        assert extended["status"] == "EXTENDED"
        assert extended["extended_once"] is True
        assert extended["deadline_date"] == "2026-08-05"
        resp = api.extend_recall(
            recall["id"], {"new_deadline_date": "2026-08-07"}, owner_headers)
        # PRD §2.7: state check (6) precedes structural rule (8) — a faithful
        # reader may report ERR_INVALID_STATE (recall not ISSUED) or
        # ERR_RECALL_ALREADY_EXTENDED (extended_once already true).
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_RECALL_ALREADY_EXTENDED,
                   ApiErrorId.ERR_INVALID_STATE])

    def test_extension_must_raise_deadline(self, api):
        """PRD §3.7: "supplying a `new_deadline_date` that must push the
        deadline strictly later (`ERR_RECALL_WINDOW_INVALID`)"

        Design: Corner/state_machines/recall_extend_only_once
        """
        ctx, recall = _recall_setup(api, "SM5B", deadline="2026-08-05")
        resp = api.extend_recall(
            recall["id"], {"new_deadline_date": "2026-08-05"},
            make_owner_rep_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RECALL_WINDOW_INVALID)


class TestRecallCancel:
    def test_cancel_rejected_after_partial_delivery(self, api):
        """PRD §3.7: "An owner may instead cancel a recall — from `ISSUED` or
        `EXTENDED` — but only while nothing has been delivered against it: a
        `delivered_quantity` greater than zero rejects the cancel with
        `ERR_RECALL_PARTIALLY_DELIVERED`."
        PRD §3.7: "While a recall is open, every return of shares against the
        loan is absorbed by the recall first: `delivered_quantity` climbs
        with each return until it reaches the recalled `quantity`, at which
        point the recall completes."

        Design: Corner/state_machines/recall_cancel_rejected_after_partial_delivery
        """
        ctx, recall = _recall_setup(api, "SM6", reason="VOTE",
                                    deadline="2026-08-10")
        return_shares(ctx["loan"], ctx["borrower"], 400)
        resp = api.cancel_recall(
            recall["id"], make_owner_rep_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RECALL_PARTIALLY_DELIVERED)
        r = get_recall(recall["id"], make_owner_rep_headers(ctx["owner"]["id"]))
        assert r["delivered_quantity"] == 400
        assert r["status"] == "ISSUED"
        loan = get_loan(ctx["loan"]["id"])
        assert loan["status"] == "RECALLED"
        assert loan["outstanding_quantity"] == 600

    def test_cancel_with_zero_deliveries_returns_loan_to_booked(self, api):
        """PRD §3.7: "Cancelling moves the recall to `CANCELLED` and returns
        the loan from `RECALLED` to `BOOKED`, again incrementing the loan's
        `version`."

        Design: Corner/state_machines/recall_cancel_rejected_after_partial_delivery
        """
        ctx, recall = _recall_setup(api, "SM6C", reason="VOTE",
                                    deadline="2026-08-10")
        cancelled = validate_success(api.cancel_recall(
            recall["id"], make_owner_rep_headers(ctx["owner"]["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert get_loan(ctx["loan"]["id"])["status"] == "BOOKED"


class TestBuyInGate:
    def test_buy_in_rejected_unless_recall_failed(self, api):
        """PRD §3.7: "A `DeskTrader` executes it with a `buy_in_price_cents`,
        and only against a recall in `FAILED` status — from any other state
        the call is rejected with `ERR_BUY_IN_NOT_ALLOWED`."

        Design: Corner/state_machines/buy_in_rejected_unless_recall_failed
        """
        ctx, recall = _recall_setup(api, "SM7", deadline="2026-08-10")
        resp = api.buy_in_recall(recall["id"], {"buy_in_price_cents": 1200},
                                 TRADER)
        validate_error(resp, ApiErrorId.ERR_BUY_IN_NOT_ALLOWED)


class TestRecallFailAndBuyInChain:
    def test_recall_fail_and_buy_in_full_chain(self, api):
        """PRD §3.7: "A recall still `ISSUED` or `EXTENDED` whose
        `deadline_date` has passed with `delivered_quantity` short of
        `quantity` moves to `FAILED`, and the run snapshots the security's
        current `price_cents` into the recall's `fail_price_cents`."
        PRD §3.7: "for shares delivered — or bought in — on a given date, the
        chargeable days are the calendar days from the `deadline_date` to
        that date, floored at zero so that the deadline day itself is free;
        the window is deadline-exclusive and delivery-inclusive. Each
        tranche's fee is those days multiplied by the tranche's shares times
        the `fail_price_cents` times 100 basis points divided by 10000, the
        per-tranche product rounded half-up to whole cents before the
        day-count multiplication"
        PRD §3.7: "The buy-in finalizes the fail fee for the undelivered
        remainder, accruing from the day after the deadline through the
        buy-in date inclusive, posts a `FAIL_FEE` entry if the total fee is
        greater than zero, and posts a `BUY_IN_CHARGE` equal to the
        undelivered shares — `quantity` minus `delivered_quantity` —
        multiplied by `buy_in_price_cents`; both entries are charged to the
        borrower as negative amounts. The loan then moves to `SETTLED` as its
        economic close"

        Design: Corner/state_machines/recall_fail_and_buy_in_full_chain
        """
        ctx = setup_booked_loan(security_symbol="SM8", loan_quantity=1000,
                                rate_bps=25)
        recall = issue_recall(ctx["loan"], ctx["owner"], 1000, reason="SALE",
                              deadline_date="2026-08-03")
        set_clock("2026-08-05T00:00:00Z")
        return_shares(ctx["loan"], ctx["borrower"], 400)
        set_clock("2026-08-06T00:00:00Z")
        summary = run_mtm()
        assert summary["recalls_failed"] == 1

        r = get_recall(recall["id"])
        assert r["status"] == "FAILED"
        assert r["fail_price_cents"] == 1000

        set_clock("2026-08-08T00:00:00Z")
        bought = validate_success(api.buy_in_recall(
            recall["id"], {"buy_in_price_cents": 1200}, TRADER))
        assert bought["status"] == "BOUGHT_IN"
        # 400 sh x 2 days x round_half_up(400 x 1000 x 100/10000)=4000 -> 8000
        # 600 sh x 5 days x round_half_up(600 x 1000 x 100/10000)=6000 -> 30000
        assert bought["fail_fee_cents"] == 38000

        fees = list_ledger_entries(TRADER, loan_id=ctx["loan"]["id"],
                                   entry_type="FAIL_FEE")
        # PRD §3.7: "both entries are charged to the borrower as negative
        # amounts" — the fail fee posts negative.
        assert sum(e["amount_cents"] for e in fees) == -38000

        charges = list_ledger_entries(TRADER, loan_id=ctx["loan"]["id"],
                                      entry_type="BUY_IN_CHARGE")
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == -720000  # 600 x 1200

        assert get_loan(ctx["loan"]["id"])["status"] == "SETTLED"


class TestOnTimeDelivery:
    def test_on_time_recall_delivery_accrues_zero_fail_fee(self, api):
        """PRD §3.7: "the chargeable days are the calendar days from the
        `deadline_date` to that date, floored at zero so that the deadline
        day itself is free"
        PRD §3.7: "Completion, from `ISSUED` or `EXTENDED`, lands in
        `COMPLETED` and finalizes the recall's `fail_fee_cents`, posting a
        `FAIL_FEE` ledger entry when the fee is greater than zero."

        Design: Corner/calculations/on_time_recall_delivery_accrues_zero_fail_fee
        """
        ctx, recall = _recall_setup(api, "CL2", reason="CORPORATE_ACTION",
                                    deadline="2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        settled = return_shares(ctx["loan"], ctx["borrower"], 1000)
        assert settled["status"] == "SETTLED"
        r = get_recall(recall["id"])
        assert r["status"] == "COMPLETED"
        assert r["fail_fee_cents"] == 0
        fees = list_ledger_entries(TRADER, loan_id=ctx["loan"]["id"],
                                   entry_type="FAIL_FEE")
        assert fees == []
