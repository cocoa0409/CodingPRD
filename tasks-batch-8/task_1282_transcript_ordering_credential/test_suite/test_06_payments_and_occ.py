"""Payment lifecycle, refund waterfall invariant, idempotency, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_payment,
    assert_payment_invariants,
    create_captured_payment,
    create_delivered_order,
    create_fee_schedule,
    create_recipient,
    create_student,
    create_submitted_order,
    create_verified_identity,
    get_success_data,
    make_student_headers,
    reset_clock,
    validate_error,
    validate_success,
)


def _operator():
    return TEST_USERS["operator_headers"]


def _student_and_recipient(student_number, name, email):
    student = create_student(
        student_number=student_number, full_name=name,
        date_of_birth="2000-01-01", email=email,
    )
    recipient = create_recipient(kind="EMAIL_PDF", display_name="Self", email_address=email)
    return student, recipient


def _submitted_order(api, student, recipient):
    return create_submitted_order(
        student["id"],
        lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
    )


class TestRefundInvariant:
    def test_payment_refund_conserves_captured_minus_refunded(self, api):
        """PRD §3.6: "Any refund request whose cumulative total would exceed
        `captured_cents` is rejected with `ERR_REFUND_EXCEEDS_CAPTURED` (HTTP
        422)."
        PRD §3.7: "The refund never exceeds the captured total."

        Design: Difficulty/compensating_invariant/payment_refund_conserves_captured_minus_refunded
        """
        reset_clock()
        create_fee_schedule(code="FS-INV1")
        student, recipient = _student_and_recipient(
            "SA000001", "Quinn Lee", "quinn@example.edu"
        )
        order = _submitted_order(api, student, recipient)
        payment = create_captured_payment(order["id"], student["id"])
        assert payment["captured_cents"] == 1000
        assert payment["status"] == "CAPTURED"

        resp = api.refund_payment(payment["id"], {"refund_amount_cents": 1000}, _operator())
        refunded = validate_success(resp, expected_status=200)
        assert_payment(refunded)
        assert_payment_invariants(refunded)
        assert refunded["refunded_cents"] == 1000
        assert refunded["status"] == "REFUNDED"
        assert refunded["captured_cents"] - refunded["refunded_cents"] == 0

    def test_payment_partial_then_full_refund_reaches_refunded(self, api):
        """PRD §3.6: "While the `Payment` is `CAPTURED`, a refund whose amount is
        strictly less than the difference between `captured_cents` and the
        already-accumulated `refunded_cents` adds to `refunded_cents` and moves
        the payment to `PARTIALLY_REFUNDED`; when the cumulative refunded total
        reaches `captured_cents`, the payment moves to `REFUNDED`."

        Design: Difficulty/compensating_invariant/payment_refund_conserves_captured_minus_refunded
        """
        reset_clock()
        create_fee_schedule(code="FS-INV1B")
        student, recipient = _student_and_recipient(
            "SA000011", "Quinn Lee B", "quinnb@example.edu"
        )
        order = _submitted_order(api, student, recipient)
        payment = create_captured_payment(order["id"], student["id"])

        partial = validate_success(
            api.refund_payment(payment["id"], {"refund_amount_cents": 400}, _operator())
        )
        assert partial["refunded_cents"] == 400
        assert partial["status"] == "PARTIALLY_REFUNDED"
        assert_payment_invariants(partial)

        full = validate_success(
            api.refund_payment(payment["id"], {"refund_amount_cents": 600}, _operator())
        )
        assert full["refunded_cents"] == 1000
        assert full["status"] == "REFUNDED"
        assert full["captured_cents"] - full["refunded_cents"] == 0


class TestPaymentIdempotency:
    def test_idempotency_key_reuse_with_different_payload_returns_conflict(self, api):
        """PRD §3.6: "If a second authorize arrives carrying an
        `idempotency_key` already seen with a different payload, the request is
        rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409); the same key with
        the same payload returns the original `Payment` unchanged."

        Design: Corner/validations/idempotency_key_reuse_with_different_payload_returns_conflict
        """
        reset_clock()
        create_fee_schedule(code="FS-IDEM")
        student, recipient = _student_and_recipient(
            "SC002201", "Idem T", "idem@x.edu"
        )
        o1 = _submitted_order(api, student, recipient)
        o2 = _submitted_order(api, student, recipient)
        student_headers = make_student_headers(student["id"])
        p1 = get_success_data(
            api.create_payment(
                {"order_id": o1["id"], "idempotency_key": "shared-key"}, student_headers
            )
        )
        # Same key, different payload (different order_id).
        resp = api.create_payment(
            {"order_id": o2["id"], "idempotency_key": "shared-key"}, student_headers
        )
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)

    def test_idempotency_same_key_same_payload_returns_original(self, api):
        """PRD §3.6: "the same key with the same payload returns the original
        `Payment` unchanged".

        Design: Corner/cross_cutting_layers/idempotency_same_key_same_payload_returns_original
        """
        reset_clock()
        create_fee_schedule(code="FS-IDEM2")
        student, recipient = _student_and_recipient(
            "SC006401", "ID T", "id@x.edu"
        )
        order = _submitted_order(api, student, recipient)
        student_headers = make_student_headers(student["id"])
        p1 = get_success_data(
            api.create_payment(
                {"order_id": order["id"], "idempotency_key": "same-key"}, student_headers
            )
        )
        p2 = get_success_data(
            api.create_payment(
                {"order_id": order["id"], "idempotency_key": "same-key"}, student_headers
            )
        )
        assert p1["id"] == p2["id"], "same key + same payload must return the original Payment"


class TestOptimisticConcurrency:
    def test_err_stale_version_triggerable_on_submit(self, api):
        """PRD §2.6: "Submitting an order requires the caller to include
        `expected_order_version` carrying the order's `version` as last observed
        by the client; if another writer has advanced the order's version since
        that read — for example by adding a line item that changed the rush
        qualification or the provisional quote — the submission is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_version_triggerable
        """
        reset_clock()
        create_fee_schedule(code="FS-OCC")
        student, recipient = _student_and_recipient(
            "SC004001", "OCC T", "occ@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        stale_version = order["version"]
        get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "EMAIL_PDF",
                    "quantity": 1,
                    "expected_order_version": stale_version,
                },
                student_headers,
            )
        )
        create_verified_identity(student["id"], order["id"])
        # Submit with the version observed BEFORE the line-item add.
        resp = api.submit_order(
            order["id"], {"expected_order_version": stale_version}, student_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_optimistic_concurrency_stale_version_on_line_item_add(self, api):
        """PRD §2.6: "Adding a line item to a DRAFT order carries the same
        requirement: the request must include `expected_order_version` matching
        the order's current `version`, and a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_version_on_line_item_add
        """
        reset_clock()
        student, recipient = _student_and_recipient(
            "SC006001", "OCC L", "occl@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        stale_version = order["version"]
        get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "EMAIL_PDF",
                    "quantity": 1,
                    "expected_order_version": stale_version,
                },
                student_headers,
            )
        )
        # Second add with the stale pre-add version.
        resp = api.add_line_item(
            order["id"],
            {
                "recipient_id": recipient["id"],
                "delivery_kind": "EMAIL_PDF",
                "quantity": 1,
                "expected_order_version": stale_version,
            },
            student_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
