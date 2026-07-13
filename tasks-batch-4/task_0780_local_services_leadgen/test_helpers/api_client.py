"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Pro ----
    def create_pro(self, payload, headers):
        return self._request("POST", "/pros", payload, headers)

    def get_pro(self, pro_id, headers):
        return self._request("GET", f"/pros/{pro_id}", headers=headers)

    def list_pros(self, headers, params=None):
        return self._request("GET", "/pros", headers=headers, params=params)

    def submit_verification(self, pro_id, headers):
        return self._request("POST", f"/pros/{pro_id}/submit-verification", {}, headers)

    def verify_pro(self, pro_id, payload, headers):
        return self._request("POST", f"/pros/{pro_id}/verify", payload, headers)

    def credit_topup(self, pro_id, payload, headers):
        return self._request("POST", f"/pros/{pro_id}/credit-topup", payload, headers)

    def subscribe_pro(self, pro_id, payload, headers):
        return self._request("POST", f"/pros/{pro_id}/subscribe", payload, headers)

    # ---- Config ----
    def create_service_category(self, payload, headers):
        return self._request("POST", "/service-categories", payload, headers)

    def get_service_category(self, category_id, headers):
        return self._request("GET", f"/service-categories/{category_id}", headers=headers)

    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/subscription-plans/{plan_id}", headers=headers)

    # ---- ServiceRequest ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"/service-requests/{request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def distribute(self, request_id, payload, headers):
        return self._request("POST", f"/service-requests/{request_id}/distribute", payload, headers)

    def close_service_request(self, request_id, headers):
        return self._request("POST", f"/service-requests/{request_id}/close", {}, headers)

    # ---- Lead ----
    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/leads/{lead_id}", headers=headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/leads", headers=headers, params=params)

    def contact_lead(self, lead_id, headers):
        return self._request("POST", f"/leads/{lead_id}/contact", {}, headers)

    def refund_request(self, lead_id, payload, headers):
        return self._request("POST", f"/leads/{lead_id}/refund-request", payload, headers)

    # ---- Quote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def send_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", payload, headers)

    def request_revision(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/request-revision", {}, headers)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    # ---- Review ----
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def publish_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/publish", {}, headers)

    # ---- Dispute ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # ---- Calendar ----
    def create_availability_slot(self, payload, headers):
        return self._request("POST", "/availability-slots", payload, headers)

    def get_availability_slot(self, slot_id, headers):
        return self._request("GET", f"/availability-slots/{slot_id}", headers=headers)

    def list_availability_slots(self, headers, params=None):
        return self._request("GET", "/availability-slots", headers=headers, params=params)

    # ---- Test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
