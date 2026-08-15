"""Dues invoicing dual variants, payment waterfall, refunds, consistency."""
from test_helpers import (
    ApiErrorId,
    apply_grant,
    approve_grant,
    assert_dues_payment,
    create_grant,
    create_open_season_with_section,
    create_payment_payload,
    enroll_member,
    issue_invoice,
    pay_dues,
    set_clock,
    validate_error,
    validate_success,
)


class TestDualVariantDuesAmount:
    def test_dues_invoice_provisional_vs_final_after_cutoff(
            self, api, treasurer_headers):
        """PRD §3.4: "The provisional amount, fixed at issuance, keys the
        early-bird discount on the invoice itself: when `issued_at` falls at or
        before the season's `early_bird_cutoff`, the provisional amount is the
        `base_dues_cents` discounted by `early_bird_pct` and rounded half up to
        integer cents; after the cutoff it is simply `base_dues_cents`. The
        final amount is revealed later, at the first payment or first
        scholarship application against the invoice, and keys the discount on
        money actually received: the discount is earned only when the payment's
        `received_at` falls at or before `early_bird_cutoff`, yielding the same
        discounted formula when earned and `base_dues_cents` when not. The
        variants diverge exactly when an invoice issued before the cutoff is
        first paid after it — the provisional assumes the discount and the
        final removes it, so `final_amount_cents` can exceed
        `provisional_amount_cents`."

        Design: Difficulty/dual_variant_calc/dues_invoice_provisional_vs_final_after_cutoff
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])
        assert invoice["provisional_amount_cents"] == 18000
        assert invoice["status"] == "ISSUED"

        # Pay after the early-bird cutoff: the discount is NOT earned.
        set_clock("2026-08-20T00:00:00Z")
        first = pay_dues(member["id"], 18000)
        assert first["status"] == "POSTED"
        # The revealed final removes the discount: balance 2000 remains.
        second = pay_dues(member["id"], 2000)

        data = validate_success(api.get_invoice(invoice["id"],
                                                treasurer_headers))
        assert data["provisional_amount_cents"] == 18000, \
            "provisional keys the discount on issued_at (2026-08-01 <= cutoff)"
        assert data["final_amount_cents"] == 20000, \
            "final keys the discount on received_at (2026-08-20 > cutoff)"
        assert data["paid_cents"] == 20000
        assert data["balance_cents"] == 0
        assert data["status"] == "PAID"
        assert_dues_payment(second)

    def test_dues_invoice_variants_agree_when_paid_before_cutoff(
            self, api, treasurer_headers):
        """PRD §3.4: "the discount is earned only when the payment's
        `received_at` falls at or before `early_bird_cutoff`, yielding the same
        discounted formula when earned and `base_dues_cents` when not. The
        variants diverge exactly when an invoice issued before the cutoff is
        first paid after it" — payment at startup (2026-08-01, at or before the
        2026-08-15 cutoff) earns the discount, so final equals provisional.

        Design: Difficulty/dual_variant_calc/dues_invoice_provisional_vs_final_after_cutoff
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])
        assert invoice["provisional_amount_cents"] == 18000

        pay_dues(member["id"], 18000)  # received_at 2026-08-01 <= cutoff
        data = validate_success(api.get_invoice(invoice["id"],
                                                treasurer_headers))
        assert data["final_amount_cents"] == 18000, \
            "discount earned: final uses the same discounted formula"
        assert data["paid_cents"] == 18000
        assert data["balance_cents"] == 0
        assert data["status"] == "PAID"


class TestPaymentWaterfall:
    def test_payment_waterfall_splits_oldest_first(self, api,
                                                   treasurer_headers,
                                                   director_headers):
        """PRD §3.4: "It then walks the member's open invoices — those in
        `ISSUED`, `PARTIAL`, or `OVERDUE` — ordered by `issued_at` ascending
        with ties broken by `created_at` ascending, taking from each the lesser
        of the remaining payment and that invoice's `balance_cents`, and
        appending each take to the payment's `allocations` as an `invoice_id` /
        `amount_cents` pair."
        PRD §3.4: "an allocation covering only part of the balance moves
        `ISSUED` to `PARTIAL`, while one that zeroes the balance moves the
        invoice to `PAID`."

        Design: Corner/calculations/payment_waterfall_splits_oldest_first
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        inv1 = issue_invoice(member["id"])
        inv2 = issue_invoice(member["id"])

        payment = validate_success(api.create_payment(
            create_payment_payload(member["id"], 20000, "CHECK"),
            treasurer_headers), 201)
        assert_dues_payment(payment)
        assert payment["allocations"] == [
            {"invoice_id": inv1["id"], "amount_cents": 18000},
            {"invoice_id": inv2["id"], "amount_cents": 2000},
        ], "oldest invoice is satisfied first, remainder flows to the newer"

        inv1_data = validate_success(
            api.get_invoice(inv1["id"], treasurer_headers))
        assert inv1_data["status"] == "PAID"
        assert inv1_data["balance_cents"] == 0
        inv2_data = validate_success(
            api.get_invoice(inv2["id"], treasurer_headers))
        assert inv2_data["status"] == "PARTIAL"
        assert inv2_data["balance_cents"] == 16000

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "ENROLLED", \
            "a positive remaining dues balance blocks the ACTIVE bubble-up"
        assert member_data["dues_balance_cents"] == 16000

    def test_overpayment_rejected_without_partial_write(
            self, api, treasurer_headers):
        """PRD §3.4: "If anything remains after every open invoice is
        satisfied, the entire payment is rejected with `ERR_OVERPAYMENT` and
        nothing is written — no partial allocation survives."

        Design: Corner/calculations/overpayment_rejected_without_partial_write
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])

        resp = api.create_payment(
            create_payment_payload(member["id"], 18001, "CARD"),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        data = validate_success(api.get_invoice(invoice["id"],
                                                treasurer_headers))
        assert data["paid_cents"] == 0, "no partial allocation survives"
        assert data["status"] == "ISSUED"
        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["treasury_balance_cents"] == 0

    def test_payment_invalid_method_enum_rejected(self, api,
                                                  treasurer_headers):
        """PRD §3.4: "The Treasurer records a payment with `member_id`,
        `amount_cents`, and a `method` of `CASH`, `CHECK`, or `CARD`"
        PRD §2.8: "an enum field carrying an undeclared value is rejected with
        `ERR_INVALID_ENUM`."

        Design: Corner/validations/payment_invalid_method_enum_rejected
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        issue_invoice(member["id"])
        resp = api.create_payment(
            create_payment_payload(member["id"], 18000, "GOLD"),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


class TestRefundCompensation:
    def test_payment_refund_reopens_invoice_and_demotes_member(
            self, api, treasurer_headers, director_headers):
        """PRD §3.4: "Refunds unwind symmetrically. Refunding a `POSTED`
        payment requires the treasury to cover the payment's `amount_cents`,
        else `ERR_INSUFFICIENT_TREASURY`; the treasury is debited, every
        allocated invoice's `paid_cents` is reduced, and any invoice that was
        `PAID` reopens to `ISSUED`. If a refunded invoice reopens, a member who
        had risen to `ACTIVE` is demoted back to `ENROLLED` as compensation,
        and `performance_eligible` is recomputed."

        Design: Corner/state_machines/payment_refund_reopens_invoice_and_demotes_member
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])
        payment = pay_dues(member["id"], 18000)

        before = validate_success(api.get_member(member["id"], director_headers))
        assert before["status"] == "ACTIVE"

        refunded = validate_success(
            api.refund_payment(payment["id"], treasurer_headers))
        assert refunded["status"] == "REFUNDED"

        invoice_data = validate_success(
            api.get_invoice(invoice["id"], treasurer_headers))
        assert invoice_data["status"] == "ISSUED", "PAID invoice reopens"
        assert invoice_data["paid_cents"] == 0
        assert invoice_data["balance_cents"] == 18000

        member_data = validate_success(
            api.get_member(member["id"], director_headers))
        assert member_data["status"] == "ENROLLED", \
            "refund demotes the member back to ENROLLED as compensation"
        assert member_data["performance_eligible"] is False

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["treasury_balance_cents"] == 0


class TestMemberActivationBubbleUp:
    def test_member_activation_requires_invoice_paid(self, api,
                                                     treasurer_headers,
                                                     director_headers):
        """PRD §3.3: "When a member's first dues invoice reaches `PAID` or
        `WAIVED` and their `dues_balance_cents` is zero, an `ENROLLED` member
        bubbles up to `ACTIVE`."
        PRD §3.3: "`performance_eligible` is true exactly when the member's
        status is `ACTIVE`, their `attendance_rate` is at least the season's
        `attendance_threshold`, and their `dues_balance_cents` is zero."

        Design: Difficulty/cross_entity_state_dependency/member_activation_requires_invoice_paid
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])

        before = validate_success(api.get_member(member["id"],
                                                 director_headers))
        assert before["status"] == "ENROLLED", \
            "no PAID or WAIVED invoice yet: no bubble-up"
        assert before["performance_eligible"] is False
        assert before["dues_balance_cents"] == 18000

        pay_dues(member["id"], 18000)

        invoice_data = validate_success(api.get_invoice(invoice["id"],
                                                        treasurer_headers))
        assert invoice_data["status"] == "PAID"
        after = validate_success(api.get_member(member["id"],
                                                director_headers))
        assert after["status"] == "ACTIVE", "PAID invoice bubbles ENROLLED up"
        assert after["performance_eligible"] is True
        assert after["dues_balance_cents"] == 0

    def test_member_activation_via_scholarship_waived_invoice(
            self, api, treasurer_headers, director_headers):
        """PRD §3.3: "When a member's first dues invoice reaches `PAID` or
        `WAIVED` and their `dues_balance_cents` is zero, an `ENROLLED` member
        bubbles up to `ACTIVE`."
        PRD §3.4: "A scholarship application that zeroes the invoice moves it
        to `WAIVED` rather than `PAID`, with the same member bubble-up"

        Design: Difficulty/cross_entity_state_dependency/member_activation_requires_invoice_paid
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])

        before = validate_success(api.get_member(member["id"],
                                                 director_headers))
        assert before["status"] == "ENROLLED"

        grant = create_grant(member["id"], 18000)
        approve_grant(grant["id"])
        apply_grant(grant["id"], invoice["id"])

        invoice_data = validate_success(api.get_invoice(invoice["id"],
                                                        treasurer_headers))
        assert invoice_data["status"] == "WAIVED"
        after = validate_success(api.get_member(member["id"],
                                                director_headers))
        assert after["status"] == "ACTIVE", \
            "WAIVED invoice runs the same ENROLLED -> ACTIVE bubble-up"
        assert after["performance_eligible"] is True
        assert after["dues_balance_cents"] == 0


class TestImmediateConsistency:
    def test_immediate_visibility_after_payment(self, api, treasurer_headers):
        """PRD §2.10: "Every fiscal event is reflected in this ledger
        immediately."
        PRD §3.4: "On success the payment is `POSTED`, the treasury is
        credited, and each allocated invoice moves: ... one that zeroes the
        balance moves the invoice to `PAID`."

        Design: Corner/consistency_model/immediate_visibility_after_payment
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])

        payment = pay_dues(member["id"], 18000)
        assert payment["status"] == "POSTED"

        # The read immediately after the write reflects every effect.
        data = validate_success(api.get_invoice(invoice["id"],
                                                treasurer_headers))
        assert data["status"] == "PAID"
        assert data["paid_cents"] == 18000
        assert data["final_amount_cents"] == 18000, \
            "received_at 2026-08-01 is at or before the 2026-08-15 cutoff"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["treasury_balance_cents"] == 18000
