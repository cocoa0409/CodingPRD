"""Non-linear state machines: the subscription's two independent axes, the
wash-batch rewash loop, the customer suspend/reinstate cycle, and the invoice
reissue loop (PRD 3.2, 3.5, 3.7, 3.9)."""
from test_helpers import (
    ApiErrorId,
    create_pause,
    customer_event,
    generate_invoice,
    invoice_event,
    read_batch,
    read_subscription,
    record_sanitization,
    set_clock,
    setup_active_subscription,
    setup_batch_in_washing,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import OPERATOR


class TestParallelDimensions:
    def _setup_issued_invoice(self):
        ctx = setup_active_subscription()
        invoice = generate_invoice(ctx["subscription"]["id"])
        invoice_event(invoice["id"], "ISSUE")  # issued_at = 2026-08-01T00:00:00Z
        ctx["invoice"] = invoice
        return ctx

    def test_billing_axis_moves_while_service_axis_stays(self, api):
        """PRD 3.9: "marking past due requires the current logical time to be at
        least 14 days after `issued_at` (`ERR_INVOICE_NOT_PAST_DUE` before then),
        moves `ISSUED` → `PAST_DUE`, and cascades the subscription's `billing_status`
        from `CURRENT` to `PAST_DUE`."
        PRD 3.7: "When the clock's date enters a `SCHEDULED` pause's window, the
        pause moves `SCHEDULED` → `ACTIVE`; the subscription moves `ACTIVE` →
        `PAUSED`"

        Design: Difficulty/non_linear_state_machine/subscription_parallel_dimensions_independent
        """
        ctx = self._setup_issued_invoice()
        sub_id = ctx["subscription"]["id"]

        set_clock("2026-08-15T00:00:00Z")  # exactly issued_at + 14 days
        past_due = invoice_event(ctx["invoice"]["id"], "MARK_PAST_DUE")
        assert past_due["status"] == "PAST_DUE"

        sub = read_subscription(sub_id)
        assert sub["service_status"] == "ACTIVE"
        assert sub["billing_status"] == "PAST_DUE", (
            "the billing axis moved while the service axis stayed ACTIVE"
        )

        pause = create_pause(
            sub_id, "2026-08-18", "2026-08-22",
            sub["version"], ctx["customer_headers"],
        )
        assert pause["status"] == "SCHEDULED"
        set_clock("2026-08-19T08:00:00Z")

        sub = read_subscription(sub_id)
        assert sub["service_status"] == "PAUSED"
        assert sub["billing_status"] == "PAST_DUE", (
            "PAUSED and PAST_DUE combine freely — the axes evolve independently"
        )

    def test_payment_restores_billing_without_touching_service(self, api):
        """PRD 3.9: "Paying a `PAST_DUE` invoice moves it to `PAID` and restores the
        subscription's `billing_status` to `CURRENT`."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_dimensions_independent
        """
        ctx = self._setup_issued_invoice()
        sub_id = ctx["subscription"]["id"]

        set_clock("2026-08-15T00:00:00Z")
        invoice_event(ctx["invoice"]["id"], "MARK_PAST_DUE")
        sub = read_subscription(sub_id)
        create_pause(
            sub_id, "2026-08-18", "2026-08-22", sub["version"], ctx["customer_headers"]
        )
        set_clock("2026-08-19T08:00:00Z")

        paid = invoice_event(ctx["invoice"]["id"], "PAY")
        assert paid["status"] == "PAID"

        sub = read_subscription(sub_id)
        assert sub["billing_status"] == "CURRENT", "PAY restores the billing axis"
        assert sub["service_status"] == "PAUSED", (
            "the service axis is untouched by the payment"
        )


class TestWashBatchRewashCycle:
    def test_rewash_loop_increments_and_resets_validation(self, api):
        """PRD 3.5: "A rewash moves `VALIDATING` → `WASHING`, requires
        `validation_passed` to be false (`ERR_INVALID_STATE` when it is true) and
        `rewash_count` still below the pinned formula's `max_rewash_count`
        (`ERR_REWASH_LIMIT_EXCEEDED` at the limit); it adds one to `rewash_count` and
        clears `validation_passed` and `validated_by` back to null for the new cycle."

        Design: Difficulty/non_linear_state_machine/washbatch_rewash_cycle
        """
        ctx = setup_batch_in_washing(batch_soil="HEAVY", water_hardness="HARD")
        batch_id = ctx["batch"]["id"]

        first = record_sanitization(batch_id, 71, 179, 100)
        assert first["validation_passed"] is False, "dwell 179 < 180 fails"

        rewash_1 = validate_success(
            _client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR)
        )
        assert rewash_1["status"] == "WASHING"
        assert rewash_1["rewash_count"] == 1
        assert rewash_1["validation_passed"] is None, (
            "the rewash clears validation_passed for the new cycle"
        )
        assert rewash_1["validated_by"] is None

        second = record_sanitization(batch_id, 70, 200, 100)
        assert second["validation_passed"] is False, "temp 70 < 71 fails"

        rewash_2 = validate_success(
            _client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR)
        )
        assert rewash_2["status"] == "WASHING"
        assert rewash_2["rewash_count"] == 2

    def test_rewash_beyond_limit_rejected(self, api):
        """PRD 3.5: "and `rewash_count` still below the pinned formula's
        `max_rewash_count` (`ERR_REWASH_LIMIT_EXCEEDED` at the limit)"

        Design: Difficulty/non_linear_state_machine/washbatch_rewash_cycle
        """
        ctx = setup_batch_in_washing(batch_soil="HEAVY", water_hardness="HARD")
        batch_id = ctx["batch"]["id"]
        assert ctx["formula"]["max_rewash_count"] == 2

        record_sanitization(batch_id, 71, 179, 100)
        validate_success(_client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR))
        record_sanitization(batch_id, 70, 200, 100)
        validate_success(_client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR))
        third = record_sanitization(batch_id, 71, 180, 201)
        assert third["validation_passed"] is False, "ppm 201 > 200 fails"

        response = _client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR)
        validate_error(response, ApiErrorId.ERR_REWASH_LIMIT_EXCEEDED.value)

        after = read_batch(batch_id)
        assert after["status"] == "VALIDATING"
        assert after["rewash_count"] == 2, "the rejected third rewash does not advance the count"


class TestCustomerSuspendReinstateCycle:
    def test_suspend_reinstate_cycle_repeats_without_cap(self, api):
        """PRD 3.2: "A `PlatformAdmin` fires the customer event `SUSPEND`, moving the
        customer `ACTIVE` → `SUSPENDED`; every subscription of that customer whose
        `service_status` is `ACTIVE` cascades to `SUSPENDED`, every `PLANNED` stop of
        each such subscription cascades to `SKIPPED`, and each skip recomputes the
        parent route's manifest counters and increments the route's `version`.
        `REINSTATE` reverses the motion, moving the customer `SUSPENDED` → `ACTIVE`
        and each `SUSPENDED` subscription back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/customer_suspend_reinstate_cycle
        """
        ctx = setup_active_subscription()
        cust_id = ctx["customer"]["id"]

        first = customer_event(cust_id, "SUSPEND")
        assert first["status"] == "SUSPENDED"
        back = customer_event(cust_id, "REINSTATE")
        assert back["status"] == "ACTIVE", "the first cycle closes"

        again = customer_event(cust_id, "SUSPEND")
        assert again["status"] == "SUSPENDED", "no loop cap on the cycle"
        back_again = customer_event(cust_id, "REINSTATE")
        assert back_again["status"] == "ACTIVE"

    def test_reinstate_cascades_subscription_back_to_active(self, api):
        """PRD 3.2: "`REINSTATE` reverses the motion, moving the customer `SUSPENDED`
        → `ACTIVE` and each `SUSPENDED` subscription back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/customer_suspend_reinstate_cycle
        """
        ctx = setup_active_subscription()
        cust_id = ctx["customer"]["id"]
        sub_id = ctx["subscription"]["id"]

        customer_event(cust_id, "SUSPEND")
        suspended_sub = read_subscription(sub_id)
        assert suspended_sub["service_status"] == "SUSPENDED", (
            "the suspension cascade drags the subscription along"
        )

        customer_event(cust_id, "REINSTATE")
        customer_event(cust_id, "SUSPEND")
        customer_event(cust_id, "REINSTATE")
        final = read_subscription(sub_id)
        assert final["service_status"] == "ACTIVE", (
            "after the second REINSTATE the subscription is ACTIVE again"
        )


class TestInvoiceReissueCycle:
    def test_issue_stamps_issued_at_from_logical_clock(self, api):
        """PRD 3.9: "Issuing moves `DRAFT` → `ISSUED` and stamps `issued_at` with the
        current logical timestamp."
        PRD 2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never silently falls back to wall-clock time."

        Design: Difficulty/non_linear_state_machine/invoice_reissue_cycle
        """
        ctx = setup_active_subscription()
        invoice = generate_invoice(ctx["subscription"]["id"])
        assert invoice["status"] == "DRAFT"
        assert invoice["issued_at"] is None

        issued = invoice_event(invoice["id"], "ISSUE")
        assert issued["status"] == "ISSUED"
        assert isinstance(issued["issued_at"], str)
        assert issued["issued_at"].startswith("2026-08-01T00:00:00"), (
            f"issued_at is the current logical timestamp, got {issued['issued_at']}"
        )

    def test_reissue_clears_then_restamps_issued_at(self, api):
        """PRD 3.9: "An issued invoice can be pulled back: reissuing moves `ISSUED` →
        `DRAFT`, clears `issued_at` to null, and the line fields are recomputed on the
        next issue."

        Design: Difficulty/non_linear_state_machine/invoice_reissue_cycle
        """
        ctx = setup_active_subscription()
        invoice = generate_invoice(ctx["subscription"]["id"])
        invoice_event(invoice["id"], "ISSUE")

        reissued = invoice_event(invoice["id"], "REISSUE")
        assert reissued["status"] == "DRAFT", "REISSUE pulls the invoice back to DRAFT"
        assert reissued["issued_at"] is None, "REISSUE clears issued_at"

        reissued_again = invoice_event(invoice["id"], "ISSUE")
        assert reissued_again["status"] == "ISSUED"
        assert reissued_again["issued_at"].startswith("2026-08-01T00:00:00"), (
            "the second ISSUE re-stamps issued_at from the logical clock"
        )
