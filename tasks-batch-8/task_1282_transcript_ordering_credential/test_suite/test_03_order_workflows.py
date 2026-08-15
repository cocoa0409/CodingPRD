"""Order lifecycle: draft, submit, dispatch, delivery, cancellation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_order_line_item,
    assert_transcript_order,
    create_captured_payment,
    create_delivered_order,
    create_fee_schedule,
    create_order_payload,
    create_recipient,
    create_student,
    create_submitted_order,
    create_verified_identity,
    get_success_data,
    make_student_headers,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _operator_headers():
    return TEST_USERS["operator_headers"]


def _list_lines(api, order_id, headers):
    resp = api.list_order_line_items(order_id, headers, params={"limit": 100})
    data, meta = validate_paginated(resp)
    return data, meta


def _setup_student_and_recipient(student_number, name, email):
    student = create_student(
        student_number=student_number, full_name=name,
        date_of_birth="2000-01-01", email=email,
    )
    recipient = create_recipient(kind="EMAIL_PDF", display_name="Self", email_address=email)
    return student, recipient


class TestOrderSubmission:
    def test_order_draft_to_submitted_valid_transition(self, api):
        """PRD §3.5: "On success the server stamps `submitted_at`, recomputes
        `rush_qualified` per §3.3, computes the provisional `quoted_fee_cents`
        per the pipeline below, initializes `final_fee_cents` equal to
        `quoted_fee_cents`, increments the order's `version`, emits
        `ORDER_SUBMIT`, and advances `fulfillment_status` from `DRAFT` to
        `SUBMITTED`."
        PRD §3.5: "otherwise it advances directly to `READY_TO_FULFILL`".

        Design: Corner/state_machines/order_draft_to_submitted_valid_transition
        """
        reset_clock()
        create_fee_schedule(code="FS-SM1")
        student, recipient = _setup_student_and_recipient(
            "SC000001", "SM One", "sm1@x.edu"
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert_transcript_order(order)
        assert order["fulfillment_status"] == "READY_TO_FULFILL"
        assert order["submitted_at"] is not None
        assert order["quoted_fee_cents"] == 1000
        assert order["final_fee_cents"] == 1000

    def test_immediate_consistency_on_order_submit_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_on_order_submit_response
        """
        reset_clock()
        create_fee_schedule(code="FS-IMM")
        student, recipient = _setup_student_and_recipient(
            "SC007001", "IM T", "im@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        line = get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "EMAIL_PDF",
                    "quantity": 1,
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        create_verified_identity(student["id"], order["id"])
        order = get_success_data(api.get_order(order["id"], student_headers))
        resp = api.submit_order(
            order["id"], {"expected_order_version": order["version"]}, student_headers
        )
        data = validate_success(resp, expected_status=200)
        # The post-submit state and fee are visible in the submit response itself.
        assert data["fulfillment_status"] != "DRAFT"
        assert data["quoted_fee_cents"] == 1000

    def test_order_submit_from_submitted_returns_invalid_state(self, api):
        """PRD §3.5: "The preconditions are: the order is in `DRAFT`; the order
        carries at least one `OrderLineItem`; an `IdentityVerification` bound to
        this order exists with `status` equal to `VERIFIED` — if none does, the
        submit is rejected with `ERR_IDENTITY_NOT_VERIFIED` (HTTP 422); and
        `expected_order_version` equals the order's current `version`, else
        `ERR_STALE_VERSION`."
        PRD §2.5: "Only after existence checks does the server evaluate whether
        the target resource sits in a state that admits the requested transition
        (`ERR_INVALID_STATE`, 409)".

        Design: Corner/state_machines/order_submit_from_submitted_returns_invalid_state
        """
        reset_clock()
        create_fee_schedule(code="FS-SM2")
        student, recipient = _setup_student_and_recipient(
            "SC000002", "SM Two", "sm2@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        resp = api.submit_order(
            order["id"], {"expected_order_version": order["version"]}, student_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOrderDispatch:
    def test_dispatch_side_effect_flips_order_to_in_transit(self, api):
        """PRD §3.7: "A successful dispatch stamps `tracking_ref`, increments the
        line's `version`, and — if this is the first line on the order to reach
        `SENT` — flips the order's `fulfillment_status` from `READY_TO_FULFILL`
        to `IN_TRANSIT`."

        Design: Corner/state_machines/dispatch_side_effect_flips_order_to_in_transit
        """
        reset_clock()
        create_fee_schedule(code="FS-SM4")
        student, recipient = _setup_student_and_recipient(
            "SC000202", "SM Four", "sm4@x.edu"
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "READY_TO_FULFILL"
        create_captured_payment(order["id"], student["id"])
        student_headers = make_student_headers(student["id"])
        lines, _ = _list_lines(api, order["id"], student_headers)
        resp = api.dispatch_line_item(lines[0]["id"], _operator_headers())
        line_after = validate_success(resp, expected_status=200)
        assert_order_line_item(line_after)
        assert line_after["line_status"] == "SENT"
        order_after = validate_success(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "IN_TRANSIT"


class TestOrderTerminalLockdown:
    def test_order_terminal_delivered_lockdown(self, api):
        """PRD §3.7: "Cancellation by the student is available while
        `fulfillment_status` is `HOLD_CHECK`, `READY_TO_FULFILL`, or
        `IDENTITY_PENDING`, and while `payment_status` is `UNPAID` or
        `AUTHORIZED`. ... An attempt to cancel from any other state is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/order_terminal_delivered_lockdown
        """
        reset_clock()
        create_fee_schedule(code="FS-SM3")
        student, recipient = _setup_student_and_recipient(
            "SC000003", "SM Three", "sm3@x.edu"
        )
        order, _payment, _lines = create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        resp = api.cancel_order(
            order["id"],
            {"cancelled_reason": "too late"},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_captured_order_fires_state_error_not_fiscal(self, api):
        """PRD §2.5: "Incoming requests are validated against a fixed priority
        ladder, and a failure at any rung prevents evaluation of every later
        rung."
        PRD §3.7: "An attempt to cancel from any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_cancel_captured_order
        """
        reset_clock()
        create_fee_schedule(code="FS-PRIO1")
        student, recipient = _setup_student_and_recipient(
            "SC600001", "Jane Kim", "jane@example.edu"
        )
        order, payment, _lines = create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert payment["captured_cents"] == 1000
        # Order is terminal (DELIVERED); even an over-refund-sized cancel attempt
        # hits the state rung first.
        resp = api.cancel_order(
            order["id"],
            {"cancelled_reason": "want a refund"},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_from_ready_to_fulfill_is_allowed(self, api):
        """PRD §3.7: "Cancellation by the student is available while
        `fulfillment_status` is `HOLD_CHECK`, `READY_TO_FULFILL`, or
        `IDENTITY_PENDING`, and while `payment_status` is `UNPAID` or
        `AUTHORIZED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_cancel_captured_order
        """
        reset_clock()
        create_fee_schedule(code="FS-PRIO1B")
        student, recipient = _setup_student_and_recipient(
            "SC600011", "Jane Kim B", "janeb@example.edu"
        )
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        assert order["fulfillment_status"] == "READY_TO_FULFILL"
        resp = api.cancel_order(
            order["id"],
            {"cancelled_reason": "changed my mind"},
            make_student_headers(student["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["fulfillment_status"] == "CANCELLED"


class TestOrderFiltering:
    def test_list_orders_filtered_by_fulfillment_status(self, api, admin_headers):
        """PRD §4: GET /registrar/orders lists orders with a
        `fulfillment_status?` filter parameter.

        Design: Corner/endpoints/list_orders_filtered_by_fulfillment_status
        """
        reset_clock()
        create_fee_schedule(code="FS-FLT")
        student, recipient = _setup_student_and_recipient(
            "SC003101", "F T", "f@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        resp = api.list_orders(admin_headers, params={"fulfillment_status": "DRAFT"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        for order in data:
            assert order["fulfillment_status"] == "DRAFT"
