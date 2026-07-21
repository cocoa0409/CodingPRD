"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customer ─────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/boutique/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/boutique/customers/{customer_id}", headers=headers)

    def create_loyalty_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/boutique/customers/{customer_id}/loyalty-adjustments", payload, headers
        )

    def get_loyalty_event(self, event_id, headers):
        return self._request("GET", f"/boutique/loyalty-events/{event_id}", headers=headers)

    def list_loyalty_events(self, headers, params=None):
        return self._request("GET", "/boutique/loyalty-events", headers=headers, params=params)

    # ─── Fitter ───────────────────────────────────────────────────────────
    def create_fitter(self, payload, headers):
        return self._request("POST", "/boutique/fitters", payload, headers)

    def get_fitter(self, fitter_id, headers):
        return self._request("GET", f"/boutique/fitters/{fitter_id}", headers=headers)

    # ─── FittingRoom ──────────────────────────────────────────────────────
    def create_room(self, payload, headers):
        return self._request("POST", "/boutique/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/boutique/rooms/{room_id}", headers=headers)

    # ─── FittingAppointment ───────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/boutique/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/boutique/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/boutique/appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/boutique/appointments/{appointment_id}/confirm", {}, headers
        )

    def checkin_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/boutique/appointments/{appointment_id}/check-in", {}, headers
        )

    def fit_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/boutique/appointments/{appointment_id}/fit", payload, headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/boutique/appointments/{appointment_id}/complete", {}, headers
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/boutique/appointments/{appointment_id}/reschedule", payload, headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/boutique/appointments/{appointment_id}/cancel", {}, headers
        )

    # ─── Product & SKU ────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/boutique/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/boutique/products/{product_id}", headers=headers)

    def create_sku(self, payload, headers):
        return self._request("POST", "/boutique/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/boutique/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/boutique/skus", headers=headers, params=params)

    def restock_sku(self, sku_id, payload, headers):
        return self._request("POST", f"/boutique/skus/{sku_id}/restock", payload, headers)

    # ─── Order / OrderLine ────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/boutique/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/boutique/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/boutique/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/boutique/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/boutique/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/boutique/order-lines", headers=headers, params=params)

    def place_order(self, order_id, headers):
        return self._request("POST", f"/boutique/orders/{order_id}/place", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/boutique/orders/{order_id}/pay", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/boutique/orders/{order_id}/fulfill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/boutique/orders/{order_id}/cancel", {}, headers)

    # ─── Exchange ─────────────────────────────────────────────────────────
    def create_exchange(self, payload, headers):
        return self._request("POST", "/boutique/exchanges", payload, headers)

    def get_exchange(self, exchange_id, headers):
        return self._request("GET", f"/boutique/exchanges/{exchange_id}", headers=headers)

    def list_exchanges(self, headers, params=None):
        return self._request("GET", "/boutique/exchanges", headers=headers, params=params)

    def approve_exchange(self, exchange_id, headers):
        return self._request("POST", f"/boutique/exchanges/{exchange_id}/approve", {}, headers)

    def reject_exchange(self, exchange_id, headers):
        return self._request("POST", f"/boutique/exchanges/{exchange_id}/reject", {}, headers)

    # ─── InsuranceClaim ───────────────────────────────────────────────────
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/boutique/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id, headers):
        return self._request("GET", f"/boutique/insurance-claims/{claim_id}", headers=headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", "/boutique/insurance-claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/boutique/insurance-claims/{claim_id}/adjudicate", payload, headers
        )

    def reimburse_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/boutique/insurance-claims/{claim_id}/reimburse", {}, headers
        )

    def resubmit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/boutique/insurance-claims/{claim_id}/resubmit", {}, headers
        )

    # ─── ReplacementReminder ──────────────────────────────────────────────
    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/boutique/reminders/{reminder_id}", headers=headers)

    def list_reminders(self, headers, params=None):
        return self._request("GET", "/boutique/reminders", headers=headers, params=params)

    def send_reminder(self, reminder_id, headers):
        return self._request("POST", f"/boutique/reminders/{reminder_id}/send", {}, headers)

    def dismiss_reminder(self, reminder_id, headers):
        return self._request("POST", f"/boutique/reminders/{reminder_id}/dismiss", {}, headers)

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
