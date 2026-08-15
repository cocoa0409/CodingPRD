"""Cash collection: overpayment, payability, idempotency, derived collected_cents,
immutable payment rows, immediate visibility (PRD §2.4, §2.9, §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, is_iso8601_timestamp,
    setup_book, create_draft_order, submit_site_check, file_report,
    get_order, record_order_payment, create_payment_payload,
    drive_order_to_completed,
    DEPOSIT_10X12_WINDOW, QUOTED_10X12_WINDOW_CASH,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def _site_review_cash_order(api, width=8, depth=8, options=None, purchase_type="CASH",
                            **extra):
    jur, model, cust = setup_book()
    order = create_draft_order(
        cust["id"], model["id"], jur["id"], width_ft=width, depth_ft=depth,
        options=options or [], purchase_type=purchase_type, **extra,
    )
    submit_site_check(order["id"])
    return order


def test_overpayment_rejected(api):
    """PRD §3.6: "After the state gate, three checks run in order: first, the amount must
    not exceed the order's outstanding balance — its quoted total, or its final total
    once completed, net of what has already been collected — with any excess rejected as
    `ERR_OVERPAYMENT`"

    Design: Corner/validations/overpayment_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
    completed = drive_order_to_completed(order, deposit_cents=DEPOSIT_10X12_WINDOW)
    assert completed["final_total_cents"] == QUOTED_10X12_WINDOW_CASH
    # Remaining due: 601490 - 120298 = 481192; one cent over must fail.
    res = api.record_order_payment(
        order["id"], create_payment_payload(481193, "bal-1"), FINANCE
    )
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)
    assert get_order(order["id"])["collected_cents"] == DEPOSIT_10X12_WINDOW


def test_cash_payment_on_rto_order_rejected(api):
    """PRD §3.6: "second, because rent-to-own balances live on the contract, an
    order-level payment on an `RTO` order is rejected with `ERR_ORDER_NOT_PAYABLE`"

    Design: Corner/validations/cash_payment_on_rto_order_rejected
    """
    order = _site_review_cash_order(
        api, width=10, depth=12, purchase_type="RTO", rto_term_months=24
    )
    res = api.record_order_payment(
        order["id"], create_payment_payload(50000, "mis-1"), FINANCE
    )
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_PAYABLE, expected_status=409)


def test_idempotency_conflict_rejected(api):
    """PRD §2.9: "Reusing a key with a different amount or method is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

    Design: Corner/validations/idempotency_conflict_rejected
    """
    order = _site_review_cash_order(api)
    record_order_payment(order["id"], 50000, "key-77")
    res = api.record_order_payment(
        order["id"], create_payment_payload(75000, "key-77"), FINANCE
    )
    validate_error(res, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT, expected_status=409)
    assert get_order(order["id"])["collected_cents"] == 50000


def test_idempotent_replay_returns_same_payment(api):
    """PRD §2.9: "Replaying a key with an identical payload — the same `amount_cents`
    and `method` on the same order or contract — returns the originally recorded payment
    row without creating a duplicate."

    Design: Corner/validations/idempotent_replay_returns_same_payment
    """
    order = _site_review_cash_order(api)
    first = record_order_payment(order["id"], 50000, "key-88")
    replay = get_success_data(
        api.record_order_payment(
            order["id"], create_payment_payload(50000, "key-88"), FINANCE
        )
    )
    assert replay["id"] == first["id"], "replay returns the original payment row"
    rows, meta = validate_paginated(api.list_order_payments(order["id"], FINANCE))
    assert meta["total_count"] == 1, "no duplicate row created"
    assert get_order(order["id"])["collected_cents"] == 50000, "no double-apply"


def test_collected_cents_reconciles(api):
    """PRD §3.2: "`collected_cents`, the sum of every `DEPOSIT` and `BALANCE` payment
    recorded against the order"
    PRD §3.6: "The first payment recorded against an order takes a `kind` of `DEPOSIT`;
    every later one takes a `kind` of `BALANCE`."
    PRD §3.6: "Each posting recomputes `collected_cents`"

    Design: Corner/complexity_layers/derived_field_collected_reconciles
    """
    order = _site_review_cash_order(api)
    p1 = record_order_payment(order["id"], 50000, "agg-1")
    p2 = record_order_payment(order["id"], 70000, "agg-2", method="CASH")
    assert p1["kind"] == "DEPOSIT", "first cash payment is the DEPOSIT"
    assert p2["kind"] == "BALANCE", "subsequent cash payments are BALANCE"
    refreshed = validate_success(api.get_order(order["id"], FINANCE), 200)
    assert refreshed["collected_cents"] == 120000


def test_payment_is_immutable_record(api):
    """PRD §2.4: "One exception exists: a recorded payment is immutable, so it carries
    only `id` and `created_at` — both `updated_at` and `version` are absent from payment
    resources."
    PRD §3.6: "The first payment recorded against an order takes a `kind` of `DEPOSIT`"

    Design: Corner/entities/payment_immutable_record
    """
    order = _site_review_cash_order(api)
    payment = record_order_payment(order["id"], 50000, "imm-1")
    fetched = validate_success(api.get_payment(payment["id"], FINANCE), 200)
    assert fetched["amount_cents"] == 50000
    assert fetched["kind"] == "DEPOSIT"
    assert isinstance(fetched["id"], str) and fetched["id"]
    assert is_iso8601_timestamp(fetched["created_at"])
    assert "version" not in fetched, "payments carry no version"
    assert "updated_at" not in fetched, "payments carry no updated_at"


def test_immediate_visibility_after_write(api):
    """PRD §3.6: "Each posting recomputes `collected_cents`, and when a payment pushes a
    `COMPLETED` cash order to the point where collected-minus-refunded covers
    `final_total_cents`, the order closes itself as described in §3.5."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_visibility_after_write
    """
    order = _site_review_cash_order(api)
    payment = record_order_payment(order["id"], 50000, "vis-1")
    assert payment["amount_cents"] == 50000, "created row returned in the same request"
    refreshed = validate_success(api.get_order(order["id"], SALES), 200)
    assert refreshed["collected_cents"] == 50000, "same-instant read reflects the posting"


class TestCancelledOrderPaymentStateBeatsOverpayment:
    def _cancelled_with_collection(self, api):
        jur, model, cust = setup_book()
        order = create_draft_order(
            cust["id"], model["id"], jur["id"], options=["WINDOW"]
        )
        submit_site_check(order["id"])
        record_order_payment(order["id"], 50000, "pay-1")
        cancelled = validate_success(
            api.cancel_order(order["id"], {"reason": "customer changed mind"}, SALES), 200
        )
        return cancelled

    def test_state_gate_precedes_overpayment(self, api):
        """PRD §3.6: "Order-level collection is open only while the order's status is one
        of `SITE_REVIEW`, `PERMIT_REVIEW`, `READY_TO_SCHEDULE`, `SCHEDULED`,
        `IN_PROGRESS`, or `COMPLETED`; attempts on a `DRAFT`, `CANCELLED`, or `CLOSED`
        order are rejected with `ERR_INVALID_STATE`. After the state gate, three checks
        run in order: first, the amount must not exceed the order's outstanding balance"

        Design: Difficulty/priority_pair_validation_conflict/cancelled_order_payment_state_beats_overpayment
        """
        cancelled = self._cancelled_with_collection(api)
        # 999999 would also overpay; the state gate fires first.
        res = api.record_order_payment(
            cancelled["id"], create_payment_payload(999999, "pay-2"), FINANCE
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rejected_payment_changes_nothing(self, api):
        """PRD §3.6: "First, a $50.00 administrative fee is always retained."
        PRD §3.6: "The amount retained, stored as `retained_cents`, is the smaller of the
        collected amount and the sum of the three buckets; the remainder of
        `collected_cents` is the refund, so refund plus retained always equals the
        collected amount exactly. When the refund is positive, the system records a
        payment with a `kind` of `REFUND` and `refunded_cents` is updated accordingly."

        Design: Difficulty/priority_pair_validation_conflict/cancelled_order_payment_state_beats_overpayment
        """
        cancelled = self._cancelled_with_collection(api)
        res = api.record_order_payment(
            cancelled["id"], create_payment_payload(999999, "pay-2"), FINANCE
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        refreshed = validate_success(api.get_order(cancelled["id"], FINANCE), 200)
        # Cancel from SITE_REVIEW: admin fee only -> retained 5000, refund 45000.
        assert refreshed["collected_cents"] == 50000
        assert refreshed["retained_cents"] == 5000
        assert refreshed["refunded_cents"] == 45000
