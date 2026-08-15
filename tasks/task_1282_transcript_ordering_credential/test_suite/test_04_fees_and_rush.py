"""Fee quotation pipeline: per-line rounding, volume tiers, rush multiplier,
provisional-vs-final divergence, boundary precision."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_captured_payment,
    create_fee_schedule,
    create_recipient,
    create_student,
    create_submitted_order,
    create_verified_identity,
    get_success_data,
    make_student_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
)


def _operator():
    return TEST_USERS["operator_headers"]


def _student_and_recipient(student_number, name, email, kind="EMAIL_PDF", **recipient_overrides):
    student = create_student(
        student_number=student_number, full_name=name,
        date_of_birth="2000-01-01", email=email,
    )
    recipient = create_recipient(kind=kind, display_name=name, **recipient_overrides)
    return student, recipient


class TestPerLineRounding:
    def test_fee_quote_per_line_rounding_then_sum_unit_prices(self, api):
        """PRD §3.5: "Then, for each line item, the server computes that line's
        unit price by starting from the base per copy, adding
        `paper_surcharge_cents` if the line's `delivery_kind` is `PAPER_MAIL`,
        adding `pickup_surcharge_cents` if the kind is `PICKUP`, and rounding the
        result half-up to integer cents; that per-line rounded figure is stored
        on the line as `unit_price_cents`."

        Design: Difficulty/combinatorial_formula/fee_quote_per_line_rounding_then_sum
        """
        reset_clock()
        create_fee_schedule(
            code="FS-ROUND",
            official_base_cents=999,
            unofficial_base_cents=499,
            paper_surcharge_cents=201,
            volume_tiers=[],
        )
        student, recipient = _student_and_recipient(
            "S3000001", "Dave Lee", "dave@example.edu",
            kind="PAPER_MAIL", postal_address="1 Main St, Springfield",
        )
        student_headers = make_student_headers(student["id"])
        set_clock("2026-08-10T10:00:00Z")
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        line_a = get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "PAPER_MAIL",
                    "quantity": 1,
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        order = get_success_data(api.get_order(order["id"], student_headers))
        line_b = get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "PAPER_MAIL",
                    "quantity": 1,
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        # Per-line: 999 + 201 = 1200 exactly, rounded before summing.
        assert line_a["unit_price_cents"] == 1200
        assert line_b["unit_price_cents"] == 1200

    def test_fee_quote_per_line_rounding_then_sum_total(self, api):
        """PRD §3.5: "The order subtotal is the sum, over all line items, of each
        line's `unit_price_cents` multiplied by its `quantity`."

        Design: Difficulty/combinatorial_formula/fee_quote_per_line_rounding_then_sum
        """
        reset_clock()
        create_fee_schedule(
            code="FS-ROUND2",
            official_base_cents=999,
            unofficial_base_cents=499,
            paper_surcharge_cents=201,
            volume_tiers=[],
        )
        student, recipient = _student_and_recipient(
            "S3000101", "Dave Lee B", "daveb@example.edu",
            kind="PAPER_MAIL", postal_address="1 Main St, Springfield",
        )
        set_clock("2026-08-10T10:00:00Z")
        order = create_submitted_order(
            student["id"],
            lines=[
                {"recipient_id": recipient["id"], "delivery_kind": "PAPER_MAIL", "quantity": 1},
                {"recipient_id": recipient["id"], "delivery_kind": "PAPER_MAIL", "quantity": 1},
            ],
        )
        assert order["quoted_fee_cents"] == 2400, (
            f"expected per-line-rounded sum 2400, got {order['quoted_fee_cents']}"
        )
        assert order["final_fee_cents"] == 2400


class TestRushTierCombination:
    def test_fee_quote_rush_cutoff_volume_tier_and_rush_multiplier_combined(self, api):
        """PRD §3.5: "The chosen tier's `discount_bp` is applied to the whole
        subtotal by multiplying the subtotal by the difference between 10000 and
        `discount_bp` and dividing by 10000, rounding half-up to integer cents."
        PRD §3.5: "if the order is rush-qualified, the discounted subtotal is
        multiplied by `rush_multiplier_bp` and divided by 10000 with
        round-half-up, and `rush_flat_cents` is added on top — multiplicative
        first, additive second, in that order."

        Design: Difficulty/combinatorial_formula/fee_quote_rush_cutoff_volume_tier_and_rush_multiplier_combined
        """
        reset_clock()
        create_fee_schedule(
            code="FS-COMB",
            volume_tiers=[{"min_copies": 5, "discount_bp": 1000}],
        )
        student, recipient = _student_and_recipient(
            "S3000002", "Eve Park", "eve@example.edu",
            kind="ELECTRONIC_NETWORK", network_code="NET-STATE-U",
        )
        # 2026-08-10 is a Monday; 10:00 is before the 14:00 rush cutoff.
        set_clock("2026-08-10T10:00:00Z")
        order = create_submitted_order(
            student["id"],
            lines=[
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "ELECTRONIC_NETWORK",
                    "quantity": 5,
                }
            ],
            rush_requested=True,
        )
        assert order["rush_qualified"] is True
        # subtotal 5000 -> tier discount 10% -> 4500 -> x1.5 -> 6750 -> +1500 -> 8250
        assert order["quoted_fee_cents"] == 8250, (
            f"expected 8250, got {order['quoted_fee_cents']}"
        )

    def test_fee_quote_rush_flat_added_after_multiplier(self, api):
        """PRD §3.5: "if the order is rush-qualified, the discounted subtotal is
        multiplied by `rush_multiplier_bp` and divided by 10000 with
        round-half-up, and `rush_flat_cents` is added on top — multiplicative
        first, additive second, in that order."

        Design: Difficulty/combinatorial_formula/fee_quote_rush_cutoff_volume_tier_and_rush_multiplier_combined
        """
        reset_clock()
        # rush_flat_cents=0 isolates the multiplicative step; with the flat fee
        # zero, the total is exactly subtotal * 1.5.
        create_fee_schedule(code="FS-COMB2", rush_flat_cents=0, volume_tiers=[])
        student, recipient = _student_and_recipient(
            "S3000202", "Eve Park B", "eveb@example.edu",
            kind="ELECTRONIC_NETWORK", network_code="NET-STATE-U",
        )
        set_clock("2026-08-10T10:00:00Z")
        order = create_submitted_order(
            student["id"],
            lines=[
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "ELECTRONIC_NETWORK",
                    "quantity": 5,
                }
            ],
            rush_requested=True,
        )
        assert order["rush_qualified"] is True
        # 5000 * 1.5 + 0 = 7500
        assert order["quoted_fee_cents"] == 7500, (
            f"expected 7500, got {order['quoted_fee_cents']}"
        )

    def test_fee_quote_volume_tier_exactly_at_min_copies(self, api):
        """PRD §3.5: "Volume discounting looks at the total copy count across all
        lines and picks the highest-`min_copies` tier in `volume_tiers` whose
        threshold the total meets or exceeds; if two tiers tie on `min_copies`,
        the one listed first wins."

        Design: Difficulty/boundary_precision_check/volume_tier_boundary_at_exactly_min_copies_qualifies
        """
        reset_clock()
        create_fee_schedule(
            code="FS-BND2",
            volume_tiers=[{"min_copies": 5, "discount_bp": 1000}],
        )
        student, recipient = _student_and_recipient(
            "S7000002", "Mike Tan", "mike@example.edu"
        )
        set_clock("2026-08-10T10:00:00Z")
        order_a = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 5}],
        )
        # At the boundary: 5 * 1000 * 0.9 = 4500
        assert order_a["quoted_fee_cents"] == 4500

    def test_fee_quote_volume_tier_one_below_min_copies(self, api):
        """PRD §3.5: "Volume discounting looks at the total copy count across all
        lines and picks the highest-`min_copies` tier in `volume_tiers` whose
        threshold the total meets or exceeds; if two tiers tie on `min_copies`,
        the one listed first wins."

        Design: Difficulty/boundary_precision_check/volume_tier_boundary_at_exactly_min_copies_qualifies
        """
        reset_clock()
        create_fee_schedule(
            code="FS-BND2B",
            volume_tiers=[{"min_copies": 5, "discount_bp": 1000}],
        )
        student, recipient = _student_and_recipient(
            "S7000102", "Mike Tan B", "mikeb@example.edu"
        )
        set_clock("2026-08-10T10:00:00Z")
        order_b = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 4}],
        )
        # One below the boundary: 4 * 1000, no discount.
        assert order_b["quoted_fee_cents"] == 4000


class TestRushCutoffBoundary:
    def test_rush_cutoff_one_second_before_qualifies(self, api):
        """PRD §3.3: "The local registrar time of `submitted_at` must be strictly
        earlier than 14:00 — a submission landing at exactly 14:00:00 is not
        rush-qualified."

        Design: Difficulty/boundary_precision_check/rush_cutoff_at_exactly_1400_local_not_qualified
        """
        reset_clock()
        create_fee_schedule(code="FS-BND1")
        student, recipient = _student_and_recipient(
            "S7000001", "Lisa Xu", "lisa@example.edu",
            kind="ELECTRONIC_NETWORK", network_code="NET-STATE-U",
        )
        set_clock("2026-08-10T13:59:59Z")
        order = create_submitted_order(
            student["id"],
            lines=[
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "ELECTRONIC_NETWORK",
                    "quantity": 1,
                }
            ],
            rush_requested=True,
        )
        assert order["rush_qualified"] is True
        # 1000 * 1.5 + 1500 = 3000
        assert order["quoted_fee_cents"] == 3000

    def test_rush_cutoff_at_exactly_1400_not_qualified(self, api):
        """PRD §3.3: "The local registrar time of `submitted_at` must be strictly
        earlier than 14:00 — a submission landing at exactly 14:00:00 is not
        rush-qualified."

        Design: Difficulty/boundary_precision_check/rush_cutoff_at_exactly_1400_local_not_qualified
        """
        reset_clock()
        create_fee_schedule(code="FS-BND1C")
        student, recipient = _student_and_recipient(
            "S7000201", "Lisa Xu C", "lisac@example.edu",
            kind="ELECTRONIC_NETWORK", network_code="NET-STATE-U",
        )
        set_clock("2026-08-10T14:00:00Z")
        order = create_submitted_order(
            student["id"],
            lines=[
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "ELECTRONIC_NETWORK",
                    "quantity": 1,
                }
            ],
            rush_requested=True,
        )
        assert order["rush_qualified"] is False
        # No rush components: base only.
        assert order["quoted_fee_cents"] == 1000


class TestRushMultiplierConstant:
    def test_rush_multiplier_constant_applied(self, api):
        """PRD §2.7: "a basis-point denominator of 10000 (so a
        `rush_multiplier_bp` of 15000 means multiply by 1.5, and a `discount_bp`
        of 500 means a 5 percent reduction)".

        Design: Corner/calculations/rush_multiplier_constant_applied
        """
        reset_clock()
        create_fee_schedule(code="FS-CONST", rush_flat_cents=0)
        student, recipient = _student_and_recipient(
            "SC001201", "Const T", "c@x.edu"
        )
        set_clock("2026-08-10T10:00:00Z")
        order = create_submitted_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 2}],
            rush_requested=True,
        )
        assert order["rush_qualified"] is True
        # 2000 * 1.5 + 0 = 3000
        assert order["quoted_fee_cents"] == 3000


class TestProvisionalVsFinalDivergence:
    def test_order_fee_provisional_vs_final_diverge_when_schedule_window_rolls(self, api):
        """PRD §3.5: "The result becomes `quoted_fee_cents` and never changes
        after submit."
        PRD §3.6: "Capture recomputes `final_fee_cents` using the same shape as
        the provisional pipeline but against the `FeeSchedule` effective at
        capture time".

        Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_diverge_when_schedule_window_rolls
        """
        set_clock("2026-07-01T00:00:00Z")
        create_fee_schedule(
            code="FS-2026A",
            official_base_cents=1000,
            volume_tiers=[{"min_copies": 5, "discount_bp": 1000}],
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-08-15T00:00:00Z",
        )
        fs_b = create_fee_schedule(
            code="FS-2026B",
            official_base_cents=1200,
            unofficial_base_cents=600,
            volume_tiers=[{"min_copies": 5, "discount_bp": 1000}],
            effective_from="2026-08-15T00:00:00Z",
        )
        student = create_student(
            student_number="S1000001", full_name="Alice Zhang",
            date_of_birth="2000-01-15", email="alice@example.edu",
        )
        recipient = create_recipient(
            kind="ELECTRONIC_NETWORK",
            display_name="State U Admissions",
            network_code="NET-STATE-U",
        )
        set_clock("2026-08-10T10:00:00Z")
        student_headers = make_student_headers(student["id"])
        order = create_submitted_order(
            student["id"],
            lines=[
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "ELECTRONIC_NETWORK",
                    "quantity": 1,
                }
            ],
        )
        assert order["quoted_fee_cents"] == 1000
        payment = get_success_data(
            api.create_payment(
                {"order_id": order["id"], "idempotency_key": "pay-key-001"}, student_headers
            )
        )
        # Roll the clock into the FS-2026B window before capture.
        set_clock("2026-08-16T10:00:00Z")
        captured = get_success_data(api.capture_payment(payment["id"], _operator()))
        # PRD §3.6: "The captured amount is the smaller of the authorized
        # `amount_cents` and that target" — authorized was 1000, the capture-time
        # recompute yields 1200, so the capture is capped at the authorization
        # and the shortfall is recorded but not auto-charged.
        assert captured["captured_cents"] == 1000
        assert captured["amount_cents"] == 1200, (
            "capture reconciles amount_cents to the recomputed final_fee_cents"
        )
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["quoted_fee_cents"] == 1000, "quoted_fee_cents never changes"
        assert order_after["final_fee_cents"] == 1200
        assert order_after["quoted_fee_cents"] != order_after["final_fee_cents"]

    def test_capture_reconciles_amount_cents_to_final_fee(self, api):
        """PRD §3.6: "A successful capture writes the captured amount into
        `captured_cents`, reconciles `amount_cents` to the recomputed
        `final_fee_cents`, moves `Payment.status` to `CAPTURED`, mirrors the
        order's `payment_status` to `CAPTURED`, and increments the order's
        `version`."

        Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_diverge_when_schedule_window_rolls
        """
        set_clock("2026-07-01T00:00:00Z")
        create_fee_schedule(
            code="FS-2026C",
            official_base_cents=1000,
            volume_tiers=[],
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-08-15T00:00:00Z",
        )
        create_fee_schedule(
            code="FS-2026D",
            official_base_cents=1200,
            unofficial_base_cents=600,
            volume_tiers=[],
            effective_from="2026-08-15T00:00:00Z",
        )
        student = create_student(
            student_number="S1000101", full_name="Alice Zhang B",
            date_of_birth="2000-01-15", email="aliceb@example.edu",
        )
        recipient = create_recipient(
            kind="ELECTRONIC_NETWORK",
            display_name="State U Admissions",
            network_code="NET-STATE-U",
        )
        set_clock("2026-08-10T10:00:00Z")
        student_headers = make_student_headers(student["id"])
        order = create_submitted_order(
            student["id"],
            lines=[
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "ELECTRONIC_NETWORK",
                    "quantity": 1,
                }
            ],
        )
        payment = get_success_data(
            api.create_payment(
                {"order_id": order["id"], "idempotency_key": "pay-key-002"}, student_headers
            )
        )
        assert payment["amount_cents"] == 1000
        set_clock("2026-08-16T10:00:00Z")
        captured = get_success_data(api.capture_payment(payment["id"], _operator()))
        assert captured["amount_cents"] == 1200, "amount_cents reconciled to final_fee_cents"
        assert captured["status"] == "CAPTURED"


class TestQuotePreview:
    def test_quote_preview_returns_provisional_estimate(self, api):
        """PRD §3.3: "The preview runs the same tiered-pricing pipeline as
        submit-time quoting but against the current logical clock and the
        currently active `FeeSchedule`; the result is advisory only, is not
        persisted, and may diverge from the eventual `quoted_fee_cents` if the
        clock crosses a schedule boundary between preview and submit."

        Design: Corner/endpoints/quote_preview_returns_provisional_estimate
        """
        reset_clock()
        create_fee_schedule(code="FS-QP")
        student, recipient = _student_and_recipient(
            "SC003001", "QP T", "qp@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        get_success_data(
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
        # Per PRD §3.3 the line-item add already recomputed and stored the
        # provisional quoted_fee_cents; the preview itself must not persist.
        order_before = get_success_data(api.get_order(order["id"], student_headers))
        resp = api.get_quote_preview(order["id"], student_headers)
        preview = validate_success(resp, expected_status=200)
        assert preview["quoted_fee_cents"] == 1000
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "DRAFT"
        assert order_after["quoted_fee_cents"] == order_before["quoted_fee_cents"], (
            "preview must not persist the quote"
        )
        assert order_after["version"] == order_before["version"], (
            "preview must not mutate the order"
        )
