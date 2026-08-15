"""Hold-release depth-3 cascade, parallel order dimensions, clearinghouse
sweep cycles and membership conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_batch,
    create_captured_payment,
    create_delivered_order,
    create_fee_schedule,
    create_hold,
    create_order_payload,
    create_recipient,
    create_student,
    create_submitted_order,
    create_verified_identity,
    get_success_data,
    make_student_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _operator():
    return TEST_USERS["operator_headers"]


def _bursar():
    return TEST_USERS["bursar_headers"]


def _student_and_recipient(student_number, name, email):
    student = create_student(
        student_number=student_number, full_name=name,
        date_of_birth="2000-01-01", email=email,
    )
    recipient = create_recipient(kind="EMAIL_PDF", display_name="Self", email_address=email)
    return student, recipient


def _list_lines(api, order_id, headers):
    resp = api.list_order_line_items(order_id, headers, params={"limit": 100})
    data, _meta = validate_paginated(resp)
    return data


class TestHoldBlockedSubmit:
    def test_order_submit_blocked_by_active_hold_on_student(self, api):
        """PRD §3.5: "From `SUBMITTED` the order immediately routes onward: if
        the order is `OFFICIAL` and any `Hold` on the student is `ACTIVE` with a
        `blocking_scope` of `ALL` or `OFFICIAL`, the order moves into
        `HOLD_CHECK` and the student is notified; otherwise it advances directly
        to `READY_TO_FULFILL`."

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_by_active_hold_on_student
        """
        reset_clock()
        create_fee_schedule(code="FS-XDEP1")
        student, recipient = _student_and_recipient(
            "S8000001", "Nina Park", "nina@example.edu"
        )
        create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=10000,
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "HOLD_CHECK", (
            f"expected HOLD_CHECK, got {order['fulfillment_status']}"
        )

    def test_order_submit_without_holds_goes_ready_to_fulfill(self, api):
        """PRD §3.5: "otherwise it advances directly to `READY_TO_FULFILL`".

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_by_active_hold_on_student
        """
        reset_clock()
        create_fee_schedule(code="FS-XDEP1B")
        student, recipient = _student_and_recipient(
            "S8000101", "Nina Park B", "ninab@example.edu"
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "READY_TO_FULFILL"


class TestHoldReleaseCascade:
    def test_hold_release_to_order_advance_to_line_items_queued_depth3(self, api):
        """PRD §3.2: "A successful release moves the hold from `ACTIVE` to
        `RELEASED`, stamps `released_at`, increments the hold's `version`, emits
        a `HOLD_RELEASED` audit event, and then cascades: every order on the same
        student currently sitting in `HOLD_CHECK` is re-evaluated, and if no
        other active blocking hold remains, each such order advances to
        `READY_TO_FULFILL` (emitting a `HOLD_CLEARED` audit event), which itself
        fans every `PENDING` line item on that order out to `QUEUED`."

        Design: Difficulty/transitive_cascade/hold_release_to_order_advance_to_line_items_queued_depth3
        """
        reset_clock()
        create_fee_schedule(code="FS-CASC1")
        student, recipient = _student_and_recipient(
            "S5000001", "Hank Yu", "hank@example.edu"
        )
        hold = create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=5000,
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "HOLD_CHECK"

        # Hop 1: Hold ACTIVE -> RELEASED.
        released = get_success_data(api.release_hold(hold["id"], _bursar()))
        assert released["status"] == "RELEASED"

        # Hop 2: order HOLD_CHECK -> READY_TO_FULFILL.
        student_headers = make_student_headers(student["id"])
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "READY_TO_FULFILL"

        # Hop 3: line items PENDING -> QUEUED.
        lines = _list_lines(api, order["id"], student_headers)
        assert len(lines) == 1
        assert lines[0]["line_status"] == "QUEUED"

    def test_hold_release_with_remaining_blocking_hold_keeps_order_in_hold_check(self, api):
        """PRD §3.2: "every order on the same student currently sitting in
        `HOLD_CHECK` is re-evaluated, and if no other active blocking hold
        remains, each such order advances to `READY_TO_FULFILL`".

        Design: Difficulty/transitive_cascade/hold_release_to_order_advance_to_line_items_queued_depth3
        """
        reset_clock()
        create_fee_schedule(code="FS-CASC1B")
        student, recipient = _student_and_recipient(
            "S5000101", "Hank Yu B", "hankb@example.edu"
        )
        hold_a = create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=5000,
        )
        hold_b = create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=2000,
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "HOLD_CHECK"

        # Release only the first hold; the second still blocks.
        get_success_data(api.release_hold(hold_a["id"], _bursar()))
        student_headers = make_student_headers(student["id"])
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "HOLD_CHECK"
        lines = _list_lines(api, order["id"], student_headers)
        assert lines[0]["line_status"] == "PENDING"

        # Releasing the last blocking hold completes the cascade.
        get_success_data(api.release_hold(hold_b["id"], _bursar()))
        order_final = get_success_data(api.get_order(order["id"], student_headers))
        assert order_final["fulfillment_status"] == "READY_TO_FULFILL"
        lines = _list_lines(api, order["id"], student_headers)
        assert lines[0]["line_status"] == "QUEUED"


class TestParallelDimensions:
    def test_dispatch_requires_captured_or_waived_payment(self, api):
        """PRD §3.7: "Dispatching a queued line item — the act that moves it from
        `QUEUED` to `SENT` — is performed by a `RegistrarOperator` and is gated
        on three conditions: the line is currently `QUEUED`; the order's
        `payment_status` is `CAPTURED` or `WAIVED`; and, when the line's
        `delivery_kind` is `ELECTRONIC_NETWORK`, the recipient's `active` flag is
        still true."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
        """
        reset_clock()
        create_fee_schedule(code="FS-PAR")
        student, recipient = _student_and_recipient(
            "S4000001", "Frank White", "frank@example.edu"
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "READY_TO_FULFILL"
        assert order["payment_status"] == "UNPAID"
        student_headers = make_student_headers(student["id"])
        lines = _list_lines(api, order["id"], student_headers)
        resp = api.dispatch_line_item(lines[0]["id"], _operator())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Both dimensions unchanged by the rejected dispatch.
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "READY_TO_FULFILL"
        assert order_after["payment_status"] == "UNPAID"

    def test_fulfillment_and_payment_dimensions_advance_independently(self, api):
        """PRD §3.3: "The new order lands in `DRAFT` on the fulfillment dimension
        and `UNPAID` on the payment dimension, and the server emits an
        `ORDER_CREATED` audit event. The two dimensions evolve independently from
        this point onward."
        PRD §3.6: "Authorization is permitted only while the order's
        `fulfillment_status` is `SUBMITTED`, `HOLD_CHECK`, or `READY_TO_FULFILL`".

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
        """
        reset_clock()
        create_fee_schedule(code="FS-PARB")
        student, recipient = _student_and_recipient(
            "S4000101", "Frank White B", "frankb@example.edu"
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        # Fulfillment advances while payment stays UNPAID...
        assert order["fulfillment_status"] == "READY_TO_FULFILL"
        assert order["payment_status"] == "UNPAID"
        # ...then payment advances while fulfillment holds at READY_TO_FULFILL.
        payment = create_captured_payment(order["id"], student["id"])
        assert payment["status"] == "CAPTURED"
        student_headers = make_student_headers(student["id"])
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "READY_TO_FULFILL"
        assert order_after["payment_status"] == "CAPTURED"


class TestClearinghouseSweepFiltering:
    def test_clearinghouse_sweep_excludes_orders_outside_period(self, api):
        """PRD §3.11: "a `TranscriptOrder` is swept in when its
        `fulfillment_status` is `DELIVERED`, its `submitted_at` falls within the
        reporting period (at or after the start and strictly before the end), and
        it is not already a member of any batch in `OPEN`, `LOCKED`,
        `TRANSMITTED`, or `ACKED`".

        Design: Corner/calculations/clearinghouse_sweep_excludes_orders_outside_period
        """
        set_clock("2026-07-01T00:00:00Z")
        create_fee_schedule(code="FS-SWEEP", effective_from="2026-07-01T00:00:00Z")
        student, recipient = _student_and_recipient(
            "SC001101", "Sweep T", "sw@x.edu"
        )
        # Old order: submitted 2026-07-15, outside [2026-08-01, 2026-09-01).
        set_clock("2026-07-15T10:00:00Z")
        create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        # In-window order: submitted 2026-08-10.
        set_clock("2026-08-10T10:00:00Z")
        create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        resp = api.create_clearinghouse_batch(
            {
                "report_period_start": "2026-08-01T00:00:00Z",
                "report_period_end": "2026-09-01T00:00:00Z",
            },
            _operator(),
        )
        batch = validate_success(resp, expected_status=201)
        assert batch["order_count"] == 1, (
            f"only the in-window DELIVERED order may be swept, got {batch['order_count']}"
        )


class TestClearinghouseFailureCycle:
    def test_clearinghouse_batch_failed_to_open_resweep_cycle(self, api):
        """PRD §3.11: "If transmission failed, marking the batch failed moves it
        from `TRANSMITTED` to `FAILED` and unlocks membership so the next sweep
        re-includes the same items — the compensating action that keeps reporting
        eventual."

        Design: Difficulty/non_linear_state_machine/clearinghouse_batch_failed_to_open_resweep_cycle
        """
        reset_clock()
        create_fee_schedule(code="FS-CH")
        student, recipient = _student_and_recipient(
            "S4000002", "Gina Hall", "gina@example.edu"
        )
        create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        batch1 = create_batch()
        assert batch1["order_count"] == 1
        get_success_data(api.lock_clearinghouse_batch(batch1["id"], _operator()))
        get_success_data(api.transmit_clearinghouse_batch(batch1["id"], _operator()))
        failed = get_success_data(api.fail_clearinghouse_batch(batch1["id"], _operator()))
        assert failed["status"] == "FAILED"

        resp = api.create_clearinghouse_batch(
            {
                "report_period_start": "2026-08-01T00:00:00Z",
                "report_period_end": "2026-09-01T00:00:00Z",
            },
            _operator(),
        )
        batch2 = validate_success(resp, expected_status=201)
        assert batch2["id"] != batch1["id"]
        assert batch2["order_count"] == 1, "released membership must be re-swept"

    def test_clearinghouse_transmitted_batch_excluded_from_resweep(self, api):
        """PRD §3.11: "it is not already a member of any batch in `OPEN`,
        `LOCKED`, `TRANSMITTED`, or `ACKED`".

        Design: Difficulty/non_linear_state_machine/clearinghouse_batch_failed_to_open_resweep_cycle
        """
        reset_clock()
        create_fee_schedule(code="FS-CHB")
        student, recipient = _student_and_recipient(
            "S4000102", "Gina Hall B", "ginab@example.edu"
        )
        create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        batch1 = create_batch()
        assert batch1["order_count"] == 1
        get_success_data(api.lock_clearinghouse_batch(batch1["id"], _operator()))
        transmitted = get_success_data(
            api.transmit_clearinghouse_batch(batch1["id"], _operator())
        )
        assert transmitted["status"] == "TRANSMITTED"

        # A second batch over the same period sweeps nothing: membership is held.
        batch2 = create_batch()
        assert batch2["order_count"] == 0


class TestClearinghouseMembershipConservation:
    def test_clearinghouse_membership_conserved_across_failed_batch(self, api):
        """PRD §3.11: "If transmission failed, marking the batch failed moves it
        from `TRANSMITTED` to `FAILED` and unlocks membership so the next sweep
        re-includes the same items — the compensating action that keeps reporting
        eventual."
        PRD §3.11: "The batch's `order_count` and `verification_count` record how
        many of each were swept in."

        Design: Difficulty/compensating_invariant/clearinghouse_membership_conserved_across_failed_batch
        """
        reset_clock()
        create_fee_schedule(code="FS-INV2")
        student, recipient = _student_and_recipient(
            "SA000002", "Rita Su", "rita@example.edu"
        )
        for _ in range(2):
            create_delivered_order(
                student["id"],
                lines=[
                    {"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}
                ],
            )
        batch1 = create_batch()
        assert batch1["order_count"] == 2
        get_success_data(api.lock_clearinghouse_batch(batch1["id"], _operator()))
        get_success_data(api.transmit_clearinghouse_batch(batch1["id"], _operator()))

        # Compensating action releases membership.
        get_success_data(api.fail_clearinghouse_batch(batch1["id"], _operator()))
        batch2 = create_batch()
        assert batch2["order_count"] == 2, (
            "membership conserved: the same two orders must be re-swept"
        )

    def test_clearinghouse_failed_batch_membership_not_double_counted(self, api):
        """PRD §3.11: "a `TranscriptOrder` is swept in when its
        `fulfillment_status` is `DELIVERED`, its `submitted_at` falls within the
        reporting period (at or after the start and strictly before the end), and
        it is not already a member of any batch in `OPEN`, `LOCKED`,
        `TRANSMITTED`, or `ACKED`".

        Design: Difficulty/compensating_invariant/clearinghouse_membership_conserved_across_failed_batch
        """
        reset_clock()
        create_fee_schedule(code="FS-INV2B")
        student, recipient = _student_and_recipient(
            "SA000012", "Rita Su B", "ritab@example.edu"
        )
        for _ in range(2):
            create_delivered_order(
                student["id"],
                lines=[
                    {"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}
                ],
            )
        batch1 = create_batch()
        get_success_data(api.lock_clearinghouse_batch(batch1["id"], _operator()))
        get_success_data(api.transmit_clearinghouse_batch(batch1["id"], _operator()))
        get_success_data(api.fail_clearinghouse_batch(batch1["id"], _operator()))

        # Re-swept into batch2; while batch2 is OPEN a third batch sweeps nothing.
        batch2 = create_batch()
        assert batch2["order_count"] == 2
        batch3 = create_batch()
        assert batch3["order_count"] == 0, "an order in a non-failed batch is not re-swept"
