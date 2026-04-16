"""
Tests for FeeInvoice lifecycle, payment, refund, voiding, and fee calculations.
Claims from Tables 2, 3 (adoption_fee_calculation, boarding_fee_calculation), 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_fee_invoice,
    assert_invoice_invariants,
    assert_monetary_precision,
    assert_cost_precision,
    create_payment_payload,
    create_shelter_with_fee_schedules,
    create_available_animal,
    create_adopter_in_shelter,
    application_to_reviewed,
    approve_application,
    pay_invoice_fully,
    create_boarding_reservation,
    confirm_boarding,
    create_repeat_adopter,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    AGE_SENIOR_THRESHOLD,
    SENIOR_DISCOUNT_RATE,
    LOYALTY_THRESHOLD,
    LONG_STAY_THRESHOLD,
    LONG_STAY_DISCOUNT_RATE,
    DEFAULT_ADOPTION_BASE_FEE,
    DEFAULT_BOARDING_DAILY_RATE,
    DEFAULT_SPECIAL_NEEDS_SURCHARGE,
    DEFAULT_LOYALTY_DISCOUNT_RATE,
    DEFAULT_TAX_RATE,
)
from test_helpers.factories import _future_iso


class TestFeeInvoiceCRUD:
    """FeeInvoice retrieval and listing."""

    def test_get_nonexistent_invoice(self, api, caseworker_headers):
        """ERR_INVOICE_NOT_FOUND."""
        res = api.get_fee_invoice(NON_EXISTENT_UUID, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_FOUND)

    def test_list_invoices_with_filters(self, api, caseworker_headers, manager_headers):
        """GET /fee-invoices supports shelter_id, reference_type, status filters."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        data, meta = validate_paginated(
            api.list_fee_invoices(
                caseworker_headers,
                params={"shelter_id": shelter["id"], "reference_type": "ADOPTION"},
            )
        )
        assert meta["total_count"] >= 1


class TestAdoptionFeeCalculation:
    """Table 3: adoption_fee_calculation."""

    def test_basic_adoption_fee(self, api, caseworker_headers):
        """Standard adoption fee: base_fee + tax, no discounts."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(
            shelter["id"], species="CAT", age_months=24,
        )  # Not senior, no special needs
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        assert_fee_invoice(invoice)
        assert invoice["reference_type"] == "ADOPTION"

        # Expected: base=150, surcharge=0, discount=0, tax=150*0.08=12.00, total=162.00
        expected_subtotal = DEFAULT_ADOPTION_BASE_FEE
        expected_tax = round(expected_subtotal * DEFAULT_TAX_RATE, 2)
        expected_total = expected_subtotal + expected_tax

        assert invoice["subtotal"] == pytest.approx(expected_subtotal, abs=0.01)
        assert invoice["tax_amount"] == pytest.approx(expected_tax, abs=0.01)
        assert invoice["discount_amount"] == pytest.approx(0, abs=0.01)
        assert invoice["total_amount"] == pytest.approx(expected_total, abs=0.01)

    def test_senior_animal_discount(self, api, caseworker_headers):
        """Animal aged >= 84 months gets 50% off base fee."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(
            shelter["id"], species="CAT", age_months=AGE_SENIOR_THRESHOLD,
        )
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )

        expected_base = DEFAULT_ADOPTION_BASE_FEE * SENIOR_DISCOUNT_RATE  # 75
        expected_tax = round(expected_base * DEFAULT_TAX_RATE, 2)
        expected_total = expected_base + expected_tax

        assert invoice["subtotal"] == pytest.approx(expected_base, abs=0.01)
        assert invoice["total_amount"] == pytest.approx(expected_total, abs=0.01)

    def test_senior_boundary_at_83_months(self, api, caseworker_headers):
        """Animal aged 83 months does NOT get senior discount."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(
            shelter["id"], species="CAT", age_months=AGE_SENIOR_THRESHOLD - 1,
        )
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )

        # Full price, no senior discount
        assert invoice["subtotal"] == pytest.approx(DEFAULT_ADOPTION_BASE_FEE, abs=0.01)

    def test_special_needs_surcharge(self, api, caseworker_headers):
        """Each special need tag adds a surcharge."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(
            shelter["id"], species="CAT",
            special_needs=["MEDICATION_REQUIRED", "DIET_RESTRICTED"],
        )
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )

        expected_surcharge = 2 * DEFAULT_SPECIAL_NEEDS_SURCHARGE  # 50
        expected_subtotal = DEFAULT_ADOPTION_BASE_FEE + expected_surcharge  # 200
        assert invoice["subtotal"] == pytest.approx(expected_subtotal, abs=0.01)

    def test_loyalty_discount_for_repeat_adopter(self, api, caseworker_headers):
        """Adopter with >= 2 completed adoptions gets loyalty discount."""
        shelter = create_shelter_with_fee_schedules()
        adopter = create_repeat_adopter(shelter["id"], completed_adoptions=2, species="CAT")
        assert adopter["adoption_history_count"] >= LOYALTY_THRESHOLD

        animal = create_available_animal(shelter["id"], species="CAT")
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )

        base = DEFAULT_ADOPTION_BASE_FEE
        loyalty_discount = (base + 0) * DEFAULT_LOYALTY_DISCOUNT_RATE  # 15.0
        expected_subtotal = base  # 150
        expected_discount = loyalty_discount  # 15
        taxable = expected_subtotal - expected_discount  # 135
        expected_tax = round(taxable * DEFAULT_TAX_RATE, 2)
        expected_total = expected_subtotal - expected_discount + expected_tax

        assert invoice["discount_amount"] == pytest.approx(expected_discount, abs=0.01)
        assert invoice["total_amount"] == pytest.approx(expected_total, abs=0.01)


class TestBoardingFeeCalculation:
    """Table 3: boarding_fee_calculation."""

    def test_basic_boarding_fee(self, api, manager_headers, caseworker_headers):
        """Standard boarding fee: daily_rate * days + tax."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)

        # 7-day stay
        reservation = create_boarding_reservation(
            shelter["id"], animal["id"],
            check_in_date=_future_iso(days=3),
            check_out_date=_future_iso(days=10),
        )
        reservation = confirm_boarding(reservation["id"])

        invoice = validate_success(
            api.get_fee_invoice(reservation["fee_invoice_id"], caseworker_headers), 200,
        )
        assert_fee_invoice(invoice)
        assert invoice["reference_type"] == "BOARDING"

        planned_days = reservation["duration_days"]
        expected_subtotal = DEFAULT_BOARDING_DAILY_RATE * planned_days
        expected_tax = round(expected_subtotal * DEFAULT_TAX_RATE, 2)
        expected_total = expected_subtotal + expected_tax

        assert invoice["subtotal"] == pytest.approx(expected_subtotal, abs=0.01)
        assert invoice["total_amount"] == pytest.approx(expected_total, abs=0.01)

    def test_long_stay_discount(self, api, manager_headers, caseworker_headers):
        """Stay > 14 days gets 10% off effective daily rate."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)

        # 16-day stay (> 14)
        reservation = create_boarding_reservation(
            shelter["id"], animal["id"],
            check_in_date=_future_iso(days=3),
            check_out_date=_future_iso(days=19),
        )
        reservation = confirm_boarding(reservation["id"])

        invoice = validate_success(
            api.get_fee_invoice(reservation["fee_invoice_id"], caseworker_headers), 200,
        )

        planned_days = reservation["duration_days"]
        assert planned_days > LONG_STAY_THRESHOLD
        effective_daily = DEFAULT_BOARDING_DAILY_RATE * LONG_STAY_DISCOUNT_RATE
        expected_subtotal = effective_daily * planned_days
        expected_tax = round(expected_subtotal * DEFAULT_TAX_RATE, 2)
        expected_total = expected_subtotal + expected_tax

        assert invoice["subtotal"] == pytest.approx(expected_subtotal, abs=0.01)
        assert invoice["total_amount"] == pytest.approx(expected_total, abs=0.01)

    def test_long_stay_boundary_at_14_days(self, api, manager_headers, caseworker_headers):
        """Exactly 14 days -> no long-stay discount."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)

        reservation = create_boarding_reservation(
            shelter["id"], animal["id"],
            check_in_date=_future_iso(days=3),
            check_out_date=_future_iso(days=17),  # 14 days
        )
        reservation = confirm_boarding(reservation["id"])

        invoice = validate_success(
            api.get_fee_invoice(reservation["fee_invoice_id"], caseworker_headers), 200,
        )

        planned_days = reservation["duration_days"]
        # 14 days is NOT > 14, so no discount
        expected_subtotal = DEFAULT_BOARDING_DAILY_RATE * planned_days
        assert invoice["subtotal"] == pytest.approx(expected_subtotal, abs=0.01)

    def test_boarding_special_needs_surcharge(self, api, manager_headers, caseworker_headers):
        """Special needs add daily surcharge to boarding fee."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(
            shelter["id"], include_bordetella=True,
            special_needs=["MEDICATION_REQUIRED"],
        )

        reservation = create_boarding_reservation(
            shelter["id"], animal["id"],
            check_in_date=_future_iso(days=3),
            check_out_date=_future_iso(days=6),  # 3-day stay
        )
        reservation = confirm_boarding(reservation["id"])

        invoice = validate_success(
            api.get_fee_invoice(reservation["fee_invoice_id"], caseworker_headers), 200,
        )

        planned_days = reservation["duration_days"]
        daily_surcharge = 1 * DEFAULT_SPECIAL_NEEDS_SURCHARGE
        effective_daily = DEFAULT_BOARDING_DAILY_RATE + daily_surcharge
        expected_subtotal = effective_daily * planned_days

        assert invoice["subtotal"] == pytest.approx(expected_subtotal, abs=0.01)


class TestInvoicePayment:
    """FeeInvoice payment lifecycle."""

    def test_full_payment_moves_to_paid(self, api, caseworker_headers, manager_headers):
        """Pay full amount -> status PAID, shelter revenue_balance updated."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        res = api.pay_invoice(
            invoice["id"],
            create_payment_payload(invoice["total_amount"]),
            caseworker_headers,
        )
        paid = validate_success(res, 200)
        assert paid["status"] == "PAID"
        assert paid["paid_amount"] == pytest.approx(invoice["total_amount"], abs=0.01)
        assert paid["balance_due"] == pytest.approx(0, abs=0.01)

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["revenue_balance"] == pytest.approx(
            shelter_before["revenue_balance"] + invoice["total_amount"], abs=0.01,
        )

    def test_partial_payment(self, api, caseworker_headers):
        """Partial payment -> PARTIALLY_PAID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        partial = invoice["total_amount"] / 2

        res = api.pay_invoice(
            invoice["id"],
            create_payment_payload(round(partial, 2)),
            caseworker_headers,
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "PARTIALLY_PAID"
        assert updated["paid_amount"] == pytest.approx(round(partial, 2), abs=0.01)

    def test_two_partial_payments_to_paid(self, api, caseworker_headers):
        """Two partial payments summing to total -> PAID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        half = round(invoice["total_amount"] / 2, 2)
        remainder = round(invoice["total_amount"] - half, 2)

        api.pay_invoice(invoice["id"], create_payment_payload(half), caseworker_headers)
        res = api.pay_invoice(
            invoice["id"], create_payment_payload(remainder), caseworker_headers,
        )
        final = validate_success(res, 200)
        assert final["status"] == "PAID"

    def test_payment_amount_invalid_negative(self, api, caseworker_headers):
        """Negative payment -> ERR_PAYMENT_AMOUNT_INVALID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        res = api.pay_invoice(
            app["fee_invoice_id"],
            create_payment_payload(-10.00),
            caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)

    def test_payment_amount_exceeds_balance(self, api, caseworker_headers):
        """Payment exceeding balance_due -> ERR_PAYMENT_AMOUNT_INVALID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        res = api.pay_invoice(
            invoice["id"],
            create_payment_payload(invoice["total_amount"] + 100),
            caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)

    def test_payment_zero_invalid(self, api, caseworker_headers):
        """Zero payment -> ERR_PAYMENT_AMOUNT_INVALID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        res = api.pay_invoice(
            app["fee_invoice_id"],
            create_payment_payload(0),
            caseworker_headers,
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)


class TestInvoiceRefund:
    """POST /fee-invoices/{id}/refund."""

    def test_refund_paid_invoice(self, api, manager_headers, caseworker_headers):
        """Refund PAID invoice -> REFUNDED, shelter revenue_balance decreased."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])
        pay_invoice_fully(app["fee_invoice_id"])

        shelter_before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        res = api.refund_invoice(app["fee_invoice_id"], manager_headers)
        refunded = validate_success(res, 200)
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_amount"] == pytest.approx(refunded["paid_amount"], abs=0.01)

        shelter_after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_after["revenue_balance"] < shelter_before["revenue_balance"]


class TestInvoiceVoid:
    """POST /fee-invoices/{id}/void."""

    def test_void_issued_invoice(self, api, manager_headers, caseworker_headers):
        """Void an ISSUED invoice with no payments -> VOID."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        res = api.void_invoice(app["fee_invoice_id"], manager_headers)
        voided = validate_success(res, 200)
        assert voided["status"] == "VOID"

    def test_void_invoice_with_payments_fails(self, api, manager_headers, caseworker_headers):
        """Cannot void an invoice that has received payments -> ERR_INVOICE_HAS_PAYMENTS."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = application_to_reviewed(animal["id"], adopter["id"], species="CAT")
        app = approve_application(app["id"])

        # Make a partial payment
        invoice = validate_success(
            api.get_fee_invoice(app["fee_invoice_id"], caseworker_headers), 200,
        )
        api.pay_invoice(
            invoice["id"], create_payment_payload(1.00), caseworker_headers,
        )

        res = api.void_invoice(invoice["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)
