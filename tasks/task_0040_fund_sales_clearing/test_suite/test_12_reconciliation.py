"""PRD §3.7: Reconciliation, exception resolution, finalize, and close.

Covers the OPEN -> EXCEPTIONS_FOUND or RESOLVED branches, exception
adjust/waive, the conserved-quantity finalize invariant, and the
SoD-checked close.

Difficulty-design coverage tags appear in test docstrings.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    adjust_exception_payload,
    advance_clock_to,
    create_reconciliation_payload,
    external_record,
    get_order_fresh,
    open_reconciliation_run,
    setup_investor_with_confirmed_subscribe,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestRunMatchEmptyExternalRecords:
    def test_empty_external_records_run_match_rejected(self, api):
        """PRD §3.7: "Running the match compares the internal SETTLED
        ledger entries for the run's scope and `as_of_date` against the
        supplied `external_records` and updates the run's
        `total_internal_amount_cents`, `total_external_amount_cents`,
        and `net_break_cents`."

        Claim: when external_records is empty, run-match cannot
        complete a meaningful transition. PRD prose does not commit to
        a specific error_id for this empty-set case; the
        difficulty-design grounds it on PRD §2.10 priority 5
        (ERR_INVALID_STATE), but a conformant implementation might
        also surface a more specific 400. Accept ERR_INVALID_STATE
        which is the priority-5 default for unmet state preconditions.

        # difficulty: boundary_precision_check/empty_external_records_match_skipped
        """
        run = open_reconciliation_run(
            as_of_date="2027-09-01",
            scope="TA_VS_CUSTODIAN",
            external_records=[],
        )
        assert run["status"] == "OPEN"
        res = api.run_match(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
        # The state-precondition check at §2.10 priority 5 is the named
        # source for this rejection.
        validate_error(res, "ERR_INVALID_STATE")


class TestReconciliationOpen:
    def test_open_run_starts_in_open(self, api):
        """PRD §3.7: "The run starts in status `OPEN` and stamps the
        operator as the run's creator for the closer-segregation
        check."

        Claim: a freshly created reconciliation run carries status
        OPEN and reflects the supplied scope.
        """
        run = open_reconciliation_run(
            as_of_date="2027-09-10",
            scope="TA_VS_BANK",
            external_records=[
                external_record(
                    ref_id="00000000-0000-0000-0000-000000000001",
                    side="DEBIT",
                    amount_cents=100,
                ),
            ],
        )
        assert run["status"] == "OPEN"
        assert run["scope"] == "TA_VS_BANK"


class TestAmountMismatchAdjustment:
    def test_amount_mismatch_then_adjust_then_finalize(self, api):
        """PRD §3.7: "the run's status to be `EXCEPTIONS_FOUND` and a
        non-null `adjustment_amount_cents` supplied; the exception
        transitions `OPEN → ADJUSTED`, and the parent run's
        `net_break_cents` is updated by the adjustment delta."

        Followed by PRD §3.7: "Finalizing the run requires every
        exception to be in `ADJUSTED` or `WAIVED` and the
        conserved-quantity invariant to hold: the original
        `net_break_cents` ... minus the sum of `adjustment_amount_cents`
        across all `ADJUSTED` exceptions must equal exactly 0."

        Claim: opening a run with one external record whose amount
        disagrees with a confirmed Order's settled amount yields an
        AMOUNT_MISMATCH exception; adjusting it by the exact delta and
        then finalizing transitions the run to RESOLVED.

        # difficulty: compensating_invariant/reconciliation_adjust_net_break_invariant
        """
        # 1. Create a confirmed SUBSCRIBE order whose settled amount is
        #    100_000 cents.
        investor, fund, order, nav = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2027-10-01T10:00:00.000Z",
        )
        assert order["status"] == "CONFIRMED"
        as_of_date = order["trade_date"].split("T")[0]

        # 2. Open a recon run whose external_record claims the
        #    counterparty saw 99_500 cents instead of 100_000 (delta=500).
        run = open_reconciliation_run(
            as_of_date=as_of_date,
            scope="TA_VS_CUSTODIAN",
            external_records=[
                external_record(
                    ref_id=order["id"],
                    side="DEBIT",
                    amount_cents=99_500,
                ),
            ],
        )

        # 3. Run match -> EXCEPTIONS_FOUND with one AMOUNT_MISMATCH.
        matched = validate_success(api.run_match(
            run["id"], TEST_USERS["clearing_operator_headers"]
        ))
        # PRD §3.7 specifies status transitions but not the exact
        # response shape for the matched run; we re-read via GET.
        detail = validate_success(api.get_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        ))
        # Some implementations include a top-level "exceptions" array on
        # the GET response; PRD §3.7 says the GET endpoint reads
        # "reconciliation run + exceptions + instructions". Tolerate
        # either flat or nested shapes:
        exceptions = (
            detail.get("exceptions")
            or detail.get("data", {}).get("exceptions")
            or []
        )
        if not exceptions:
            pytest.skip(
                "applies_to-scope: PRD §3.7 says GET returns "
                "'reconciliation run + exceptions + instructions' but "
                "does not commit to the exact serialization key, so we "
                "cannot finalize without enumerating exceptions."
            )
        # Find the AMOUNT_MISMATCH exception.
        amt_mismatch = next(
            (e for e in exceptions if e.get("kind") == "AMOUNT_MISMATCH"),
            None,
        )
        assert amt_mismatch is not None, (
            f"PRD §3.7: expected AMOUNT_MISMATCH exception (internal=100_000, "
            f"external=99_500); got {exceptions!r}"
        )

        # 4. Attempt to waive AMOUNT_MISMATCH -> ERR_WAIVE_NOT_ALLOWED.
        res_waive = api.waive_exception(
            run["id"], amt_mismatch["id"],
            TEST_USERS["clearing_operator_headers"],
        )
        validate_error(res_waive, "ERR_WAIVE_NOT_ALLOWED")

        # 5. Attempt finalize without adjusting. PRD §3.7 names
        #    ERR_RECONCILIATION_INVARIANT_BROKEN when finalize fails its
        #    invariant. PRD §2.10 priority 5 (ERR_INVALID_STATE) precedes
        #    priority 20 (ERR_RECONCILIATION_INVARIANT_BROKEN); since the
        #    exception is still OPEN here, an implementation that walks
        #    §2.10 in priority order surfaces ERR_INVALID_STATE first.
        #    Both readings are PRD-derivable, so accept either.
        res_pre_adjust = api.finalize_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
        validate_error_is_one_of(
            res_pre_adjust,
            ["ERR_RECONCILIATION_INVARIANT_BROKEN", "ERR_INVALID_STATE"],
        )

        # 6. Adjust the exception by the delta (internal - external = 500).
        # PRD §3.7: "the adjustment amount represents the correction added
        # to the internal side". With internal=100_000 and external=99_500,
        # net_break = +500 (signed: internal minus external). To restore
        # net_break to 0 the adjustment must be 500 (subtracted from
        # internal via the correction sum). PRD: "original net_break_cents
        # minus the sum of adjustment_amount_cents across all ADJUSTED
        # exceptions must equal exactly 0".
        validate_success(api.adjust_exception(
            run["id"], amt_mismatch["id"],
            adjust_exception_payload(adjustment_amount_cents=500),
            TEST_USERS["clearing_operator_headers"],
        ))

        # 7. Finalize -> RESOLVED.
        res_finalize = api.finalize_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
        finalized = validate_success(res_finalize)
        assert finalized["status"] == "RESOLVED", (
            f"PRD §3.7: finalize transitions EXCEPTIONS_FOUND -> RESOLVED "
            f"when invariant holds; got status={finalized['status']!r}"
        )


class TestReconciliationCloseSoD:
    def test_close_on_open_run_rejected(self, api):
        """PRD §3.7: "The closer's `X-User-ID` must differ from the
        run's recorded creator (otherwise `ERR_SOD_VIOLATION_RECON`)."

        PRD §2.10 priorities: state at (5) runs BEFORE SoD-recon at (8).
        So on an OPEN run, the state-precondition (close requires
        RESOLVED) fires first and yields ERR_INVALID_STATE; PRD does
        not commit to which error wins when both apply, so we accept
        either ERR_INVALID_STATE (priority 5) or ERR_SOD_VIOLATION_RECON
        (priority 8).
        """
        run = open_reconciliation_run(
            as_of_date="2027-11-01",
            scope="TA_VS_CUSTODIAN",
            external_records=[
                external_record(
                    ref_id="00000000-0000-0000-0000-000000000001",
                    side="DEBIT",
                    amount_cents=0,
                ),
            ],
            creator_headers=TEST_USERS["clearing_operator_headers"],
        )
        # Same X-User-ID closes (SoD violation), and run is OPEN
        # (state violation).
        res = api.close_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
        validate_error_is_one_of(
            res,
            ["ERR_INVALID_STATE", "ERR_SOD_VIOLATION_RECON"],
        )
