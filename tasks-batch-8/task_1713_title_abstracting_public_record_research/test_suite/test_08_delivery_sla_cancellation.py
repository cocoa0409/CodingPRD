"""Delivery cascade, turnaround SLA, cancellation, and terminal lockdown (PRD §2.5, §2.9, §3.10)."""
from test_helpers import (
    ApiErrorId,
    assert_order_fee_invariants,
    create_document,
    create_document_payload,
    create_retrieval,
    deliver_order,
    drive_order_ready_for_delivery,
    get_assignment,
    get_order,
    get_retrieval,
    get_success_data,
    make_abstracter_headers,
    make_client_headers,
    make_ops_headers,
    post_fee,
    set_clock,
    setup_delivered_order,
    setup_order_with_assignment,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalVariants:
    def _setup_rush_ready_with_two_posted_fees(self, api):
        return drive_order_ready_for_delivery(
            "client_701",
            "abs_701",
            "ex_701",
            retrieval_specs=[
                {"fee_mode": "PER_PAGE", "page_count": 10},
                {"fee_mode": "PER_DOCUMENT"},
            ],
            sla_tier="RUSH",
        )

    def test_provisional_quote_diverges_from_final_actuals_at_delivery(self, api):
        """PRD §3.1: "The provisional fee `provisional_fee_cents` is the sum of a
        40000-cent base fee and an estimated retrieval allowance — eight projected
        county documents at 2500 cents each, i.e. 20000 cents — plus, when the tier
        is `RUSH`, a premium of twenty-five percent of that subtotal rounded half
        up; for a `STANDARD` order the premium is zero and the quote is exactly
        60000 cents."
        PRD §3.1: "The running ledger `accrued_fees_cents` initializes differently:
        it contains the base fee plus, for `RUSH` only, twenty-five percent of the
        base fee alone rounded half up — the estimated allowance is a projection
        for quoting, not yet a charge, and it is discarded entirely at
        finalization, which uses only actually posted, non-reversed retrieval fees."

        Design: Difficulty/dual_variant_calc/order_fee_provisional_estimate_vs_final_actuals
        """
        ctx = self._setup_rush_ready_with_two_posted_fees(api)
        # creation snapshot is captured before any retrieval exists
        prov = ctx["order_at_creation"]["provisional_fee_cents"]
        assert prov == 75000, (
            f"provisional variant = 60000 + 25%*60000 = 75000, got {prov}"
        )
        fees = [r["fee_cents"] for r in ctx["retrievals"]]
        assert sorted(fees) == [1250, 2500], f"posted actual fees 1250/2500, got {fees}"

        delivered = deliver_order(ctx["order"]["id"])
        assert delivered["final_fee_cents"] == 54688, (
            f"final variant = 43750 + round_half_up(43750*0.25)=10938, got {delivered['final_fee_cents']}"
        )
        assert delivered["final_fee_cents"] != prov, (
            "provisional projection and final actuals must diverge on identical order data"
        )

    def test_delivery_finalizes_billed_credit_and_cap_from_actuals(self, api):
        """PRD §3.10: "The final fee `final_fee_cents` is set to the running
        `accrued_fees_cents` as it stands at that instant. The late credit is then
        evaluated against the logical clock: when `delivered_at` is strictly later
        than `due_at`, `late_credit_cents` is ten percent of `final_fee_cents`
        rounded half up; a delivery exactly at `due_at` is on time and earns a
        credit of 0. The billed amount `billed_fee_cents` is the final fee minus
        the late credit. Finally the liability cap is recomputed with
        `final_fee_cents` as its fee basis per §2.7, and the order's `version`
        increments by one."

        Design: Difficulty/dual_variant_calc/order_fee_provisional_estimate_vs_final_actuals
        """
        ctx = self._setup_rush_ready_with_two_posted_fees(api)
        delivered = deliver_order(ctx["order"]["id"])
        assert delivered["status"] == "DELIVERED"
        assert delivered["final_fee_cents"] == 54688
        assert delivered["late_credit_cents"] == 0, (
            "delivered at the clock default, before the RUSH due_at"
        )
        assert delivered["billed_fee_cents"] == 54688
        assert delivered["liability_cap_cents"] == 164064, (
            f"min(3*54688, 200000), got {delivered['liability_cap_cents']}"
        )
        assert_order_fee_invariants(delivered)


class TestDeliverCascade:
    def _setup_standard_ready_with_one_posted_fee(self, api):
        return drive_order_ready_for_delivery(
            "client_731",
            "abs_731",
            "ex_731",
            retrieval_specs=[{"fee_mode": "PER_DOCUMENT"}],
        )

    def test_deliver_cascades_statuses_through_report_to_retrievals(self, api):
        """PRD §2.9: "Delivery cascades in the opposite direction of finalization:
        delivering the order moves its `APPROVED` report to `DELIVERED`, which in
        turn moves every retrieval still in `FEE_POSTED` to `INVOICED`, which in
        turn triggers the final fee, late-credit, billed-fee, and liability-cap
        recomputation on the order."

        Design: Difficulty/transitive_cascade/deliver_cascade_finalizes_report_retrievals_and_fees
        """
        ctx = self._setup_standard_ready_with_one_posted_fee(api)
        delivered = deliver_order(ctx["order"]["id"])
        assert delivered["status"] == "DELIVERED", "link 0: the triggered transition"

        report = get_success_data(api.get_abstract_report(ctx["report"]["id"], make_ops_headers()))
        assert report["status"] == "DELIVERED", "link 1: report mutated by order delivery"

        retrieval = get_retrieval(ctx["retrievals"][0]["id"])
        assert retrieval["status"] == "INVOICED", "link 2: retrieval mutated by report delivery"

    def test_deliver_finalizes_fee_ledger_and_liability_cap(self, api):
        """PRD §3.10: "The final fee `final_fee_cents` is set to the running
        `accrued_fees_cents` as it stands at that instant. The late credit is then
        evaluated against the logical clock: when `delivered_at` is strictly later
        than `due_at`, `late_credit_cents` is ten percent of `final_fee_cents`
        rounded half up; a delivery exactly at `due_at` is on time and earns a
        credit of 0. The billed amount `billed_fee_cents` is the final fee minus
        the late credit. Finally the liability cap is recomputed with
        `final_fee_cents` as its fee basis per §2.7, and the order's `version`
        increments by one."
        PRD §3.10: "Delivery stamps `delivered_at` from the logical clock and then
        runs the three-link cascade of §2.9: the order's `APPROVED` report moves to
        `DELIVERED`; that report delivery moves every retrieval of the order still
        in `FEE_POSTED` to `INVOICED`; and the invoicing triggers the closing
        computations on the order."

        Design: Difficulty/transitive_cascade/deliver_cascade_finalizes_report_retrievals_and_fees
        """
        ctx = self._setup_standard_ready_with_one_posted_fee(api)
        delivered = deliver_order(ctx["order"]["id"])
        assert delivered["final_fee_cents"] == 42500, (
            f"link 3: final fee = 40000 + 2500, no STANDARD premium, got {delivered['final_fee_cents']}"
        )
        assert delivered["late_credit_cents"] == 0
        assert delivered["billed_fee_cents"] == 42500
        assert delivered["liability_cap_cents"] == 127500, (
            f"min(3*42500, 200000), got {delivered['liability_cap_cents']}"
        )
        assert delivered["delivered_at"] == "2026-08-01T00:00:00Z", (
            "delivered_at stamped from the logical clock default"
        )

    def test_deliver_response_reflects_full_cascade_immediately(self, api):
        """PRD §3.10: "Delivery stamps `delivered_at` from the logical clock and
        then runs the three-link cascade of §2.9: the order's `APPROVED` report
        moves to `DELIVERED`; that report delivery moves every retrieval of the
        order still in `FEE_POSTED` to `INVOICED`; and the invoicing triggers the
        closing computations on the order."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/deliver_response_reflects_full_cascade_immediately
        """
        ctx = drive_order_ready_for_delivery("client_881", "abs_881", "ex_881")
        delivered = deliver_order(ctx["order"]["id"])
        assert delivered["status"] == "DELIVERED"
        assert delivered["final_fee_cents"] == 40000, "STANDARD base, no retrievals"
        assert delivered["billed_fee_cents"] == 40000, "no late credit under the default clock"
        assert delivered["delivered_at"] == "2026-08-01T00:00:00Z", (
            "all own-row cascade effects ride on the deliver response itself"
        )


class TestSlaBoundary:
    def _setup_two_rush_ready_orders(self, api):
        first = drive_order_ready_for_delivery(
            "client_752", "abs_752a", "ex_752a",
            property_address="1 Boundary Ln", sla_tier="RUSH",
        )
        second = drive_order_ready_for_delivery(
            "client_752", "abs_752b", "ex_752b",
            property_address="2 Boundary Ln", sla_tier="RUSH",
        )
        return first, second

    def test_delivery_exactly_at_due_at_earns_no_late_credit(self, api):
        """PRD §3.10: "The late credit is then evaluated against the logical clock:
        when `delivered_at` is strictly later than `due_at`, `late_credit_cents` is
        ten percent of `final_fee_cents` rounded half up; a delivery exactly at
        `due_at` is on time and earns a credit of 0."
        PRD §2.5: "The due instant `due_at` is derived at creation as `received_at`
        plus seventy-two hours for a `STANDARD` order, or plus twenty-four hours
        for a `RUSH` order."

        Design: Difficulty/boundary_precision_check/sla_delivery_exactly_at_due_at_vs_one_second_late
        """
        first, _ = self._setup_two_rush_ready_orders(api)
        order_now = get_order(first["order"]["id"])
        assert order_now["due_at"] == "2026-08-02T00:00:00Z", (
            f"RUSH due_at = received + 24h, got {order_now['due_at']}"
        )

        set_clock("2026-08-02T00:00:00Z")
        delivered = deliver_order(first["order"]["id"])
        assert delivered["delivered_at"] == "2026-08-02T00:00:00Z"
        assert delivered["late_credit_cents"] == 0, "delivery exactly AT due_at is NOT late"
        assert delivered["final_fee_cents"] == 50000, "RUSH base with no retrievals"
        assert delivered["billed_fee_cents"] == 50000

    def test_delivery_one_second_past_due_at_earns_ten_percent_credit(self, api):
        """PRD §3.10: "The late credit is then evaluated against the logical clock:
        when `delivered_at` is strictly later than `due_at`, `late_credit_cents` is
        ten percent of `final_fee_cents` rounded half up; a delivery exactly at
        `due_at` is on time and earns a credit of 0."

        Design: Difficulty/boundary_precision_check/sla_delivery_exactly_at_due_at_vs_one_second_late
        """
        first, second = self._setup_two_rush_ready_orders(api)
        set_clock("2026-08-02T00:00:00Z")
        on_time = deliver_order(first["order"]["id"])
        assert on_time["late_credit_cents"] == 0

        set_clock("2026-08-02T00:00:01Z")
        late = deliver_order(second["order"]["id"])
        assert late["delivered_at"] == "2026-08-02T00:00:01Z"
        assert late["final_fee_cents"] == 50000
        assert late["late_credit_cents"] == 5000, (
            f"round_half_up(50000*0.10) = 5000, got {late['late_credit_cents']}"
        )
        assert late["billed_fee_cents"] == 45000
        assert late["late_credit_cents"] != on_time["late_credit_cents"], (
            "a single-second boundary flips the outcome — strict > comparison"
        )


class TestLogicalClockOverdue:
    def test_scheduled_clock_drives_is_overdue(self, api):
        """PRD §2.5: "At server startup, before any administrative adjustment, the
        logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §2.5: "An order reads as overdue — its computed `is_overdue` flag is
        true — precisely when the logical clock has advanced past `due_at` while
        the order's `status` is neither `DELIVERED` nor `CANCELLED`; once the order
        reaches either terminal state the flag is false regardless of the clock."

        Design: Corner/cross_cutting_layers/scheduled_clock_drives_is_overdue
        """
        ctx = setup_order_with_assignment("client_873", "abs_873", sla_tier="RUSH")
        assert ctx["order"]["received_at"] == "2026-08-01T00:00:00Z", (
            "server startup default, no wall clock"
        )

        before = get_order(ctx["order"]["id"])
        assert before["is_overdue"] is False

        set_clock("2026-08-03T00:00:00Z")
        after = get_order(ctx["order"]["id"])
        assert after["is_overdue"] is True, (
            "24h past the RUSH due_at with the order still non-terminal"
        )


class TestCancellation:
    def test_order_cancel_cascades_and_reverses_posted_fees(self, api):
        """PRD §2.9: "When an order is cancelled, every assignment still in
        `IN_PROGRESS`, `SUBMITTED`, or `RETURNED_FOR_CORRECTION` moves to
        `CANCELLED`; any report in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or
        `REVISION_REQUIRED` moves to `CANCELLED`; and every county retrieval with a
        posted-but-not-invoiced fee moves from `FEE_POSTED` to `FEE_REVERSED`, with
        the order's running fee recomputed afterward."
        PRD §3.10: "An order may be cancelled from any non-terminal state —
        `RECEIVED`, `SEARCH_IN_PROGRESS`, `SEARCH_COMPLETE`, `REPORT_DRAFTING`,
        `REPORT_UNDER_REVIEW`, or `READY_FOR_DELIVERY` — by the `Client` who owns
        it (the order's `client_ref` must equal the caller's `X-User-ID`, else
        `ERR_FORBIDDEN`) or by an `OperationsManager`, with an optional `reason`."

        Design: Corner/state_machines/order_cancel_cascades_and_reverses_posted_fees
        """
        ctx = setup_order_with_assignment("client_817", "abs_817")
        doc = create_document(
            ctx["order"]["id"], ctx["assignment"]["id"], "abs_817",
            instrument_number="INST-817-A", recording_date="2001-01-01",
        )
        retrieval = create_retrieval(
            ctx["order"]["id"], doc["id"], "abs_817", fee_mode="PER_DOCUMENT"
        )
        post_fee(retrieval["id"])
        assert get_order(ctx["order"]["id"])["accrued_fees_cents"] == 42500

        cancelled = api.cancel_abstract_order(
            ctx["order"]["id"], {"reason": "client withdrew"},
            make_client_headers("client_817"),
        )
        order = validate_success(cancelled, 200)
        assert order["status"] == "CANCELLED"

        assert get_assignment(ctx["assignment"]["id"])["status"] == "CANCELLED", (
            "cascade down to the in-flight assignment"
        )
        assert get_retrieval(retrieval["id"])["status"] == "FEE_REVERSED", (
            "compensation of the posted fee"
        )
        assert get_order(ctx["order"]["id"])["accrued_fees_cents"] == 40000, (
            "cancel-time reversal restores the running fee to the base"
        )

    def test_cancel_delivered_order_returns_409(self, api):
        """PRD §3.10: "An order already `DELIVERED` or `CANCELLED` cannot be
        cancelled again — the transition does not exist from a terminal state, so
        the attempt surfaces `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_delivered_order_returns_409
        """
        ctx = setup_delivered_order("client_812", "abs_812", "ex_812")
        assert ctx["order"]["status"] == "DELIVERED"

        resp = api.cancel_abstract_order(ctx["order"]["id"], {}, make_ops_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        order = get_order(ctx["order"]["id"])
        assert order["status"] == "DELIVERED"
        assert order["final_fee_cents"] == 40000, "nothing is refunded or cascaded"

    def test_document_create_on_terminal_order_blocked(self, api):
        """PRD §2.9: "once an order reaches `DELIVERED` or `CANCELLED`, any attempt
        to mutate a child — a document, curative requirement, retrieval, legal
        description check, report, or assignment — is refused with
        `ERR_ORDER_TERMINAL`."

        Design: Corner/validations/document_create_on_terminal_order_blocked
        """
        ctx = setup_order_with_assignment("client_831", "abs_831")
        cancelled = api.cancel_abstract_order(
            ctx["order"]["id"], {}, make_client_headers("client_831")
        )
        validate_success(cancelled, 200)

        resp = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_number="INST-831-A",
                recording_date="2001-01-01",
            ),
            make_abstracter_headers("abs_831"),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_TERMINAL)
