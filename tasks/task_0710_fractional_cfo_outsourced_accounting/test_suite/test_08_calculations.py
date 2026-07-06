"""Cash-flow chronological balances and AR payment completion."""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    create_client, create_forecast, create_ar_invoice,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestForecastChronologicalProjection:
    def test_running_balance_and_min_processed_in_date_order(self, api):
        """PRD §3.7: "The projection walks the lines in chronological order — sorted
        by `effective_date` ascending, breaking ties by `created_at` ascending —
        starting from a running balance equal to `opening_balance_cents`."
        PRD §3.7: "The `min_projected_balance_cents` is the lowest value the running
        balance ever takes across the walk, where the opening balance itself is the
        first candidate for that minimum"

        Design: Corner/calculations/forecast_chronological_running_balance_min
        """
        client = create_client(retainer_tier="CFO")
        cid = client["id"]
        fc = create_forecast(cid, opening_balance_cents=1000000)
        fid = fc["id"]
        # Lines created out of date order; engine must sort by effective_date.
        get_success_data(api.create_forecast_line(
            fid, {"effective_date": "2026-04-25T00:00:00Z", "direction": "INFLOW",
                   "amount_cents": 1500000}, CFO))
        get_success_data(api.create_forecast_line(
            fid, {"effective_date": "2026-04-05T00:00:00Z", "direction": "OUTFLOW",
                   "amount_cents": 1200000}, CFO))
        get_success_data(api.create_forecast_line(
            fid, {"effective_date": "2026-04-20T00:00:00Z", "direction": "OUTFLOW",
                   "amount_cents": 300000}, CFO))
        get_success_data(api.create_forecast_line(
            fid, {"effective_date": "2026-04-10T00:00:00Z", "direction": "INFLOW",
                   "amount_cents": 800000}, CFO))
        forecast = get_success_data(api.get_forecast(fid, CFO))
        assert forecast["ending_balance_cents"] == 1800000
        assert forecast["min_projected_balance_cents"] == -200000


class TestArPaymentCompletion:
    def test_exact_total_payment_marks_paid(self, api):
        """PRD §3.5: "A `Bookkeeper` records a payment by supplying `payment_cents`;
        the payment is added to `paid_amount_cents`, and the invoice moves `OPEN →
        PAID`."

        Design: Corner/calculations/ar_payment_exact_total_marks_paid
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        ar = create_ar_invoice(cid, amount_cents=100000)
        paid = get_success_data(api.record_ar_payment(
            ar["id"], {"payment_cents": 100000}, BK))
        assert paid["paid_amount_cents"] == 100000
        assert paid["status"] == "PAID"

    def test_underpayment_rejected_invoice_stays_open(self, api):
        """PRD §3.5: "a payment is allowed only when the resulting
        `paid_amount_cents` would reach or exceed `amount_cents`, and a payment that
        would leave the cumulative paid amount below the invoice total is rejected
        with `ERR_UNDERPAYMENT`."

        Design: Corner/calculations/ar_payment_underpayment_rejected
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        ar = create_ar_invoice(cid, amount_cents=100000)
        resp = api.record_ar_payment(ar["id"], {"payment_cents": 99999}, BK)
        validate_error(resp, ApiErrorId.ERR_UNDERPAYMENT.value)
        after = get_success_data(api.get_ar_invoice(ar["id"], BK))
        assert after["status"] == "OPEN"
