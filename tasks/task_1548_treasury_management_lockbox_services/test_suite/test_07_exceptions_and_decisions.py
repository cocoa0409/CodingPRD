"""Exception raising cascades, decision segregation of duties, the decision
window, and auto-decision at the business-day close."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_item,
    assert_exception_item,
    begin_capture,
    capture_item,
    create_batch,
    decide_exception,
    decide_exception_ok,
    get_batch,
    get_exception,
    raise_exception,
    run_close_business_day,
    setup_live_lockbox,
    validate_error,
    validate_paginated,
)

AUDITOR = TEST_USERS["auditor_headers"]


class TestExceptionRaiseCascade:
    def _setup_capturing_batch_with_item(self):
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=2,
                             declared_total_cents=2000)
        begin_capture(ws, batch["id"])
        item1 = capture_item(ws, batch["id"], check_number="1",
                             amount_cents=1000)
        item2 = capture_item(ws, batch["id"], check_number="2",
                             amount_cents=1000)
        return ws, batch, item1, item2

    def test_raise_exception_creates_pending_and_moves_batch(self, api):
        """PRD §3.4: "Raising creates a `PENDING` ExceptionItem whose
        `auto_decision_at` sits two business days after the current business
        date at that day's site cutoff, and pushes the batch from `OPEN` to
        `DECISIONS_PENDING` if it is not already there."

        Design: Difficulty/transitive_cascade/exception_raise_cascades_to_batch_decision_pending_depth2
        """
        ws, batch, item1, _item2 = self._setup_capturing_batch_with_item()
        exception = raise_exception(ws, batch["id"], item1["id"],
                                    default_decision="RETURN")
        assert_exception_item(exception)
        assert exception["status"] == "PENDING"
        assert exception["item_id"] == item1["id"]
        after = get_batch(ws, batch["id"])
        assert after["batch_status"] == "DECISIONS_PENDING", (
            "The raise must push the batch OPEN → DECISIONS_PENDING"
        )

    def test_second_raise_keeps_batch_in_decisions_pending(self, api):
        """PRD §3.4: "Raising creates a `PENDING` ExceptionItem whose
        `auto_decision_at` sits two business days after the current business
        date at that day's site cutoff, and pushes the batch from `OPEN` to
        `DECISIONS_PENDING` if it is not already there."

        Design: Difficulty/transitive_cascade/exception_raise_cascades_to_batch_decision_pending_depth2
        """
        ws, batch, item1, item2 = self._setup_capturing_batch_with_item()
        raise_exception(ws, batch["id"], item1["id"], default_decision="PAY")
        raise_exception(ws, batch["id"], item2["id"], default_decision="RETURN")
        after = get_batch(ws, batch["id"])
        assert after["batch_status"] == "DECISIONS_PENDING"
        exceptions, _meta = validate_paginated(
            api.list_exception_items(ws["bank"]["id"], ws["customer"]["id"],
                                     AUDITOR))
        assert len(exceptions) == 2
        assert all(e["status"] == "PENDING" for e in exceptions)


class TestExceptionDecisionGates:
    def test_decider_must_differ_from_raiser(self, api):
        """PRD §3.5: "The decide is accepted only while the exception is
        `PENDING` or `ESCALATED` — anything else is
        `ERR_EXCEPTION_ALREADY_DECIDED` — only when the decider's `X-User-ID`
        differs from the operator who raised the exception
        (`ERR_SEGREGATION_OF_DUTIES`)".
        PRD §2.8: "the CustomerOperator who decides an exception must differ
        from the operator who raised it".

        Design: Difficulty/cross_entity_state_dependency/exception_decide_requires_pending_and_decider_not_raiser
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        item = capture_item(ws, batch["id"], check_number="1",
                            amount_cents=1000)
        # The raising LockboxOperator's opaque X-User-ID happens to equal the
        # customer's id; a CustomerOperator decide carries that same id.
        customer_id = ws["customer"]["id"]
        exception = raise_exception(ws, batch["id"], item["id"],
                                    operator_id=customer_id,
                                    default_decision="PAY")
        resp = decide_exception(ws, exception["id"], "PAY")
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_decide_after_decision_is_rejected(self, api):
        """PRD §3.5: "The decide is accepted only while the exception is
        `PENDING` or `ESCALATED` — anything else is
        `ERR_EXCEPTION_ALREADY_DECIDED`".

        Design: Difficulty/cross_entity_state_dependency/exception_decide_requires_pending_and_decider_not_raiser
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        item = capture_item(ws, batch["id"], check_number="1",
                            amount_cents=1000)
        exception = raise_exception(ws, batch["id"], item["id"],
                                    default_decision="PAY")
        decided = decide_exception_ok(ws, exception["id"], "PAY")
        assert decided["status"] == "DECIDED"
        resp = decide_exception(ws, exception["id"], "RETURN")
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_ALREADY_DECIDED)


class TestAutoDecisionCheckpoint:
    def test_close_business_day_auto_decides_overdue_exceptions(self, api):
        """PRD §3.5: "Auto-decision runs inside the business-day close: any
        exception still `PENDING` or `ESCALATED` on or after its auto-decision
        date becomes `AUTO_DECISIONED`, taking `decision` from
        `default_decision`, recording `decided_by_user_id` as the system,
        setting `decided_at` to `auto_decision_at`, and producing the same
        downstream item and batch effects as a manual decision."

        Design: Corner/cross_cutting_layers/close_business_day_auto_decides_overdue_exceptions
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        item = capture_item(ws, batch["id"], check_number="1",
                            amount_cents=1000)
        exception = raise_exception(ws, batch["id"], item["id"],
                                    default_decision="RETURN")
        # Raised on business date 2026-08-01; auto-decision is due two business
        # days later (Tuesday 2026-08-04 at the site cutoff). Three closes
        # advance the date past that point.
        run_close_business_day(ws)
        run_close_business_day(ws)
        run_close_business_day(ws)
        after = get_exception(ws, exception["id"])
        assert after["status"] == "AUTO_DECISIONED"
        assert after["decision"] == "RETURN", "default_decision must be applied"
        assert after["decided_by_user_id"] == "system"
