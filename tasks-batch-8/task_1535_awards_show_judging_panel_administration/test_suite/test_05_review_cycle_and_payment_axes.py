"""The entry revision loop (INELIGIBLE ↔ UNDER_REVIEW) and the parallel
lifecycle/payment state dimensions (PRD §3.3, §3.4).
"""
from test_helpers import (
    ApiErrorId,
    make_entrant_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestRevisionCycleLoop:
    def test_recheck_loop_increments_revision_count(self, api):
        """PRD §3.4: "The entrant may answer an ineligibility ruling by
        requesting a recheck, which returns the entry from `INELIGIBLE` to
        `UNDER_REVIEW`, increments `revision_count` by one, and re-uses the
        settled payment so `payment_status` remains `PAID`."

        Design: Difficulty/non_linear_state_machine/entry_revision_cycle_loop
        """
        bundle = fx.setup_under_review_entry("GALA-CYC")
        entry, entrant = bundle["entry"], bundle["entrant"]
        entrant_headers = make_entrant_headers(entrant["id"])

        for expected_revision in (1, 2):
            fx.mark_ineligible(entry["id"])
            rechecked = validate_success(
                api.request_recheck(entry["id"], entrant_headers)
            )
            assert rechecked["status"] == "UNDER_REVIEW"
            assert rechecked["revision_count"] == expected_revision
            assert rechecked["payment_status"] == "PAID"

    def test_third_recheck_rejected_and_payment_retained(self, api):
        """PRD §3.4: "The loop is capped: a recheck is accepted only while
        `revision_count` is below two — an entry may cycle at most twice — and
        only while the season is `OPEN` or `SUBMISSION_CLOSED`."
        PRD §3.8: "any action whose source state does not permit the transition
        is refused with `ERR_INVALID_STATE`."
        PRD §3.4: "An ineligibility ruling is deliberately not a refund event:
        the settled invoice stays `PAID`, no refund fires while the revision
        loop is open (refunds fire only on withdrawal or terminal disposition)"

        Design: Difficulty/non_linear_state_machine/entry_revision_cycle_loop
        """
        bundle = fx.setup_under_review_entry("GALA-CYC2")
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        entrant_headers = make_entrant_headers(entrant["id"])

        for _ in range(2):
            fx.mark_ineligible(entry["id"])
            validate_success(api.request_recheck(entry["id"], entrant_headers))

        fx.mark_ineligible(entry["id"])
        resp = api.request_recheck(entry["id"], entrant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = fx.get_entry(entry["id"])
        assert fetched["status"] == "INELIGIBLE"
        assert fetched["revision_count"] == 2
        assert fetched["payment_status"] == "PAID"
        invoice_now = fx.get_invoice(invoice["id"])
        assert invoice_now["status"] == "PAID"
        season = fx.get_season(bundle["season"]["id"])
        assert season["active_entries_count"] == 1, (
            "an INELIGIBLE entry still counts as active (PRD §3.4)"
        )


class TestParallelPaymentDimension:
    def test_submit_decouples_lifecycle_and_payment_status(self, api):
        """PRD §3.3: "an entry's `payment_status` is a parallel dimension that
        evolves independently of its lifecycle `status` across the values
        `UNPAID`, `INVOICED`, `PAID`, `REFUNDED`, and `WAIVED`."
        PRD §3.3: "the entry moves to `SUBMITTED`, its `payment_status` becomes
        `INVOICED`"

        Design: Difficulty/non_linear_state_machine/entry_parallel_payment_dimension
        """
        bundle = fx.setup_submitted_entry("GALA-PAR", submit=False)
        entry, entrant = bundle["entry"], bundle["entrant"]
        submitted = validate_success(
            api.submit_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["payment_status"] == "INVOICED"
        # Marking eligible from SUBMITTED is not a permitted transition:
        resp = api.mark_eligible(entry["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_payment_unlocks_under_review_then_eligible(self, api):
        """PRD §3.3: "Payment stamps `paid_at`, moves the invoice to `PAID`,
        sets the entry's `payment_status` to `PAID`, and cascades a `SUBMITTED`
        entry into `UNDER_REVIEW`"
        PRD §3.4: "Marking an entry eligible moves it to `ELIGIBLE` and appends
        `ENTRY_MARK_ELIGIBLE`"

        Design: Difficulty/non_linear_state_machine/entry_parallel_payment_dimension
        """
        bundle = fx.setup_submitted_entry("GALA-PAR2")
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        paid = validate_success(
            api.pay_invoice(invoice["id"], make_entrant_headers(entrant["id"]))
        )
        assert paid["status"] == "PAID"
        under_review = fx.get_entry(entry["id"])
        assert under_review["status"] == "UNDER_REVIEW"
        assert under_review["payment_status"] == "PAID"
        eligible = validate_success(api.mark_eligible(entry["id"], ADMIN))
        assert eligible["status"] == "ELIGIBLE"
        assert eligible["payment_status"] == "PAID"
