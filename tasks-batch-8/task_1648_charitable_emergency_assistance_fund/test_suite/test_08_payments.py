"""Direct-to-vendor disbursement: payment lifecycle (issue, clear, fail,
reissue, void), the allocation-remainder boundary, the half-open payment
window, and the cross-entity cascade on clear."""
from test_helpers import (
    ApiErrorId,
    clear_payment,
    create_vendor,
    get_application,
    get_award,
    issue_payment,
    list_award_allocations,
    setup_approved,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

PM1 = TEST_USERS["program_manager_headers"]
FIN1 = TEST_USERS["finance_officer_headers"]


class TestPaymentLifecycleCycle:
    def _issued_full_payment(self):
        ctx = setup_approved(requested_amount_cents=30000)
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 30000
        )
        return ctx, payment

    def test_payment_fail_then_reissue_returns_to_issued(self, api):
        """PRD §3.7: "A bounced check is marked by failing the payment, moving
        `ISSUED → FAILED`. A failed payment can be reissued — `FAILED → ISSUED` —
        which re-validates the two issuance constraints against current state:
        the amount must still fit the allocation remainder
        (`ERR_PAYMENT_EXCEEDS_ALLOCATION`) and the `payment_date` must still sit
        inside the source's period (`ERR_SOURCE_PERIOD_CLOSED`)."

        Design: Difficulty/non_linear_state_machine/payment_reissue_cycle
        """
        ctx, payment = self._issued_full_payment()
        failed = validate_success(api.fail_payment(payment["id"], FIN1), 200)
        assert failed["status"] == "FAILED"
        reissued = validate_success(api.reissue_payment(payment["id"], FIN1), 200)
        assert reissued["status"] == "ISSUED"
        assert reissued["version"] == payment["version"] + 2, (
            "create 1, fail 2, reissue 3"
        )
        assert reissued.get("cleared_at") in (None, ""), "cleared_at stays empty until clear"

    def test_payment_reissue_cycle_leaves_source_balances_undisturbed(self, api):
        """PRD §3.7: "Note that payment failure and voidance do not return
        reserved funds by themselves — the reservation unwinds only through award
        adjustment or voidance, keeping the source's
        committed-plus-reserved-plus-available invariant intact at all times."

        Design: Difficulty/non_linear_state_machine/payment_reissue_cycle
        """
        ctx, payment = self._issued_full_payment()
        validate_success(api.fail_payment(payment["id"], FIN1), 200)
        validate_success(api.reissue_payment(payment["id"], FIN1), 200)
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["reserved_cents"] == 30000
        assert source["committed_cents"] == 0
        assert source["available_cents"] == 70000


class TestPaymentClearCascade:
    def _two_payment_setup(self):
        ctx = setup_approved(requested_amount_cents=30000)
        pay1 = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 12000,
            payment_date="2026-08-02T00:00:00Z",
        )
        pay2 = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 18000,
            payment_date="2026-08-03T00:00:00Z",
        )
        return ctx, pay1, pay2

    def test_clear_bubbles_allocation_award_application(self, api):
        """PRD §3.7: "the allocation's `consumed_cents` increases by the payment
        amount, and when consumed reaches allocated the allocation transitions
        `RESERVED → CONSUMED`; the source's `reserved_cents` decreases and its
        `committed_cents` increases by the amount; `cleared_at` is stamped from
        the logical clock; and the award bubbles up — when every allocation of
        the award is now `CONSUMED`, the award becomes `DISBURSED` and its
        application moves `APPROVED → PAID`, while an `ACTIVE` award with
        allocations still open becomes `PARTIALLY_DISBURSED` (a
        `PARTIALLY_DISBURSED` award with allocations still open simply stays
        where it is)."

        Design: Difficulty/transitive_cascade/payment_clear_bubble_up_cascade
        """
        ctx, pay1, pay2 = self._two_payment_setup()
        clear_payment(pay1["id"])
        cleared2 = clear_payment(pay2["id"])
        assert cleared2["status"] == "CLEARED"
        assert cleared2.get("cleared_at") not in (None, ""), "cleared_at stamped on clear"
        allocation = list_award_allocations(ctx["award"]["id"])[0]
        assert allocation["consumed_cents"] == 30000
        assert allocation["status"] == "CONSUMED"
        assert get_award(ctx["award"]["id"])["status"] == "DISBURSED"
        assert get_application(ctx["application"]["id"])["status"] == "PAID"

    def test_clear_moves_source_balances_reserved_to_committed(self, api):
        """PRD §3.7: "the source's `reserved_cents` decreases and its
        `committed_cents` increases by the amount"
        PRD §3.1: "the invariant that committed plus reserved plus available
        always equals `total_budget_cents` holds at all times."

        Design: Difficulty/transitive_cascade/payment_clear_bubble_up_cascade
        """
        ctx, pay1, pay2 = self._two_payment_setup()
        clear_payment(pay1["id"])
        mid = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert mid["reserved_cents"] == 18000
        assert mid["committed_cents"] == 12000
        assert get_award(ctx["award"]["id"])["status"] == "PARTIALLY_DISBURSED"
        clear_payment(pay2["id"])
        final = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert final["reserved_cents"] == 0
        assert final["committed_cents"] == 30000
        assert final["available_cents"] == 70000

    def test_partial_disbursement_intermediate_states(self, api):
        """PRD §3.7: "when every allocation of the award is now `CONSUMED`, the
        award becomes `DISBURSED` and its application moves `APPROVED → PAID`,
        while an `ACTIVE` award with allocations still open becomes
        `PARTIALLY_DISBURSED` (a `PARTIALLY_DISBURSED` award with allocations
        still open simply stays where it is)."

        Design: Corner/state_machines/partial_disbursement_intermediate_states
        """
        ctx, pay1, _ = self._two_payment_setup()
        clear_payment(pay1["id"])
        assert get_award(ctx["award"]["id"])["status"] == "PARTIALLY_DISBURSED"
        assert get_application(ctx["application"]["id"])["status"] == "APPROVED", (
            "PAID only when every allocation is fully consumed"
        )
        source = validate_success(api.get_funding_source(ctx["source"]["id"], PM1), 200)
        assert source["committed_cents"] == 12000
        assert source["reserved_cents"] == 18000


class TestPaymentAmountBoundary:
    def test_payment_of_exact_allocation_remainder_succeeds(self, api):
        """PRD §3.7: "The amount must be greater than zero and no more than the
        allocation's remainder — its `allocated_cents` minus its `consumed_cents`
        minus the sum of other `ISSUED` payments drawn on the same allocation —
        else `ERR_PAYMENT_EXCEEDS_ALLOCATION`."

        Design: Difficulty/boundary_precision_check/payment_consumes_allocation_exactly_then_one_cent_over
        """
        ctx = setup_approved(requested_amount_cents=30000)
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 30000
        )
        assert payment["status"] == "ISSUED", "amount == remainder uses the inclusive boundary"
        # While that payment is ISSUED the remainder is 30000 - 0 - 30000 == 0.
        resp = api.create_payment(
            ctx["award"]["id"],
            {
                "vendor_id": ctx["vendor"]["id"],
                "funding_source_id": ctx["source"]["id"],
                "amount_cents": 1,
                "payment_date": "2026-08-03T00:00:00Z",
            },
            FIN1,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_ALLOCATION)

    def test_exact_remainder_payment_clears_to_full_consumption(self, api):
        """PRD §3.7: "the allocation's `consumed_cents` increases by the payment
        amount, and when consumed reaches allocated the allocation transitions
        `RESERVED → CONSUMED`"
        PRD §3.7: "when every allocation of the award is now `CONSUMED`, the
        award becomes `DISBURSED` and its application moves `APPROVED → PAID`"

        Design: Difficulty/boundary_precision_check/payment_consumes_allocation_exactly_then_one_cent_over
        """
        ctx = setup_approved(requested_amount_cents=30000)
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 30000
        )
        cleared = clear_payment(payment["id"])
        assert cleared["status"] == "CLEARED"
        allocation = list_award_allocations(ctx["award"]["id"])[0]
        assert allocation["consumed_cents"] == allocation["allocated_cents"] == 30000
        assert allocation["status"] == "CONSUMED"
        assert get_award(ctx["award"]["id"])["status"] == "DISBURSED"
        assert get_application(ctx["application"]["id"])["status"] == "PAID"


class TestPaymentGuardsAndWindow:
    def test_payment_clear_from_failed_rejected(self, api):
        """PRD §3.7: "A `FinanceOfficer` clears an `ISSUED` payment — any other
        state draws `ERR_INVALID_PAYMENT_STATE` — and the effects ripple outward"
        PRD §3.7: "Failing, reissuing, or voiding from a state where that
        transition does not exist fails with `ERR_INVALID_PAYMENT_STATE`."

        Design: Corner/state_machines/payment_clear_from_failed_rejected
        """
        ctx = setup_approved(requested_amount_cents=20000)
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 20000
        )
        validate_success(api.fail_payment(payment["id"], FIN1), 200)
        resp = api.clear_payment(payment["id"], FIN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_PAYMENT_STATE)
        stayed = validate_success(api.get_payment(payment["id"], FIN1), 200)
        assert stayed["status"] == "FAILED"

    def test_payment_date_period_boundary_inclusive_start_exclusive_end(self, api):
        """PRD §3.7: "And the `payment_date` must fall inside the source's
        half-open funding period: at or after `period_start` and strictly before
        `period_end`, with a date exactly on `period_end` falling outside, else
        `ERR_SOURCE_PERIOD_CLOSED`."

        Design: Corner/validations/payment_date_period_boundary_inclusive_start_exclusive_end
        """
        ctx = setup_approved(requested_amount_cents=20000)
        # period_start boundary is inclusive.
        at_start = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 5000,
            payment_date="2026-01-01T00:00:00Z",
        )
        assert at_start["status"] == "ISSUED"
        # period_end boundary is exclusive.
        resp = api.create_payment(
            ctx["award"]["id"],
            {
                "vendor_id": ctx["vendor"]["id"],
                "funding_source_id": ctx["source"]["id"],
                "amount_cents": 5000,
                "payment_date": "2027-01-01T00:00:00Z",
            },
            FIN1,
        )
        validate_error(resp, ApiErrorId.ERR_SOURCE_PERIOD_CLOSED)

    def test_wrong_vendor_beats_out_of_period_date(self, api):
        """PRD §2.9: "8. Cross-reference compatibility —
        `ERR_VENDOR_CATEGORY_MISMATCH` at application creation;
        `ERR_VENDOR_MISMATCH` and `ERR_NO_RESERVED_ALLOCATION` at payment
        issuance."
        PRD §2.9: "9. Temporal windows — `ERR_SOURCE_PERIOD_CLOSED` at payment
        issuance or reissue; `ERR_APPEAL_WINDOW_CLOSED` on appeal;
        `ERR_SOURCE_PERIOD_OVERLAP` at funding-source creation."
        PRD §3.7: "The payee must equal the vendor on the application behind the
        award, else `ERR_VENDOR_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_payment
        """
        ctx = setup_approved(requested_amount_cents=20000)
        other_vendor = create_vendor(vendor_type="UTILITY", name="City Power & Light")
        resp = api.create_payment(
            ctx["award"]["id"],
            {
                "vendor_id": other_vendor["id"],  # wrong vendor AND bad date
                "funding_source_id": ctx["source"]["id"],
                "amount_cents": 5000,
                "payment_date": "2028-06-01T00:00:00Z",
            },
            FIN1,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_MISMATCH)

    def test_out_of_period_date_alone_yields_source_period_closed(self, api):
        """PRD §3.7: "And the `payment_date` must fall inside the source's
        half-open funding period: at or after `period_start` and strictly before
        `period_end`, with a date exactly on `period_end` falling outside, else
        `ERR_SOURCE_PERIOD_CLOSED`."
        PRD §2.9: "8. Cross-reference compatibility —
        `ERR_VENDOR_CATEGORY_MISMATCH` at application creation;
        `ERR_VENDOR_MISMATCH` and `ERR_NO_RESERVED_ALLOCATION` at payment
        issuance."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_payment
        """
        ctx = setup_approved(requested_amount_cents=20000)
        resp = api.create_payment(
            ctx["award"]["id"],
            {
                "vendor_id": ctx["vendor"]["id"],  # correct vendor, bad date only
                "funding_source_id": ctx["source"]["id"],
                "amount_cents": 5000,
                "payment_date": "2028-06-01T00:00:00Z",
            },
            FIN1,
        )
        validate_error(resp, ApiErrorId.ERR_SOURCE_PERIOD_CLOSED)
