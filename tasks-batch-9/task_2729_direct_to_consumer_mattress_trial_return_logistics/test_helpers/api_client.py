"""API client: one method per endpoint declared in PRD §4.

PRD §4 places every collection at the root of the service, so no path prefix is
applied here.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- catalogue and configuration (PRD §3.1) ---
    def create_mattress_model(self, payload, headers):
        return self._request("POST", "/mattress-models", payload, headers)

    def create_promotion_bundle(self, payload, headers):
        return self._request("POST", "/promotion-bundles", payload, headers)

    def create_retail_partner(self, payload, headers):
        return self._request("POST", "/retail-partners", payload, headers)

    def create_disposition_partner(self, payload, headers):
        return self._request("POST", "/disposition-partners", payload, headers)

    def list_disposition_partners(self, headers, params=None):
        return self._request(
            "GET", "/disposition-partners", headers=headers, params=params
        )

    # --- customers and fraud posture (PRD §3.2) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_abuse_signals(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/abuse-signals", headers=headers, params=params
        )

    def create_trial_abuse_signal(self, payload, headers):
        return self._request("POST", "/trial-abuse-signals", payload, headers)

    # --- trial orders (PRD §3.3) ---
    def create_trial_order(self, payload, headers):
        return self._request("POST", "/trial-orders", payload, headers)

    def get_trial_order(self, order_id, headers):
        return self._request("GET", f"/trial-orders/{order_id}", headers=headers)

    def list_trial_orders(self, headers, params=None):
        return self._request("GET", "/trial-orders", headers=headers, params=params)

    def dispatch_trial_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/trial-orders/{order_id}/dispatch", payload, headers
        )

    def deliver_trial_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/trial-orders/{order_id}/deliver", payload, headers
        )

    def keep_trial_order(self, order_id, payload, headers):
        return self._request("POST", f"/trial-orders/{order_id}/keep", payload, headers)

    # --- quality claims (PRD §3.4) ---
    def create_quality_claim(self, payload, headers):
        return self._request("POST", "/quality-claims", payload, headers)

    def get_quality_claim(self, claim_id, headers):
        return self._request("GET", f"/quality-claims/{claim_id}", headers=headers)

    def list_quality_claims(self, headers, params=None):
        return self._request("GET", "/quality-claims", headers=headers, params=params)

    def request_claim_evidence(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/request-evidence", payload, headers
        )

    def submit_claim_evidence(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/submit-evidence", payload, headers
        )

    def adjudicate_quality_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/adjudicate", payload, headers
        )

    def settle_quality_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/settle", payload, headers
        )

    # --- comfort exchanges (PRD §3.5) ---
    def create_comfort_exchange(self, payload, headers):
        return self._request("POST", "/comfort-exchanges", payload, headers)

    def get_comfort_exchange(self, exchange_id, headers):
        return self._request("GET", f"/comfort-exchanges/{exchange_id}", headers=headers)

    def list_comfort_exchanges(self, headers, params=None):
        return self._request("GET", "/comfort-exchanges", headers=headers, params=params)

    def approve_comfort_exchange(self, exchange_id, payload, headers):
        return self._request(
            "POST", f"/comfort-exchanges/{exchange_id}/approve", payload, headers
        )

    def decline_comfort_exchange(self, exchange_id, payload, headers):
        return self._request(
            "POST", f"/comfort-exchanges/{exchange_id}/decline", payload, headers
        )

    # --- return cases (PRD §3.6, §3.8) ---
    def create_return_case(self, payload, headers):
        return self._request("POST", "/return-cases", payload, headers)

    def get_return_case(self, return_case_id, headers):
        return self._request("GET", f"/return-cases/{return_case_id}", headers=headers)

    def list_return_cases(self, headers, params=None):
        return self._request("GET", "/return-cases", headers=headers, params=params)

    def get_refund_summary(self, return_case_id, headers):
        return self._request(
            "GET", f"/return-cases/{return_case_id}/refund-summary", headers=headers
        )

    def cancel_return_case(self, return_case_id, payload, headers):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/cancel", payload, headers
        )

    def inspect_return_case(self, return_case_id, payload, headers):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/inspect", payload, headers
        )

    def disposition_return_case(self, return_case_id, payload, headers):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/disposition", payload, headers
        )

    # --- pickup routing (PRD §3.7) ---
    def create_pickup_route(self, payload, headers):
        return self._request("POST", "/pickup-routes", payload, headers)

    def get_pickup_route(self, route_id, headers):
        return self._request("GET", f"/pickup-routes/{route_id}", headers=headers)

    def publish_pickup_route(self, route_id, payload, headers):
        return self._request(
            "POST", f"/pickup-routes/{route_id}/publish", payload, headers
        )

    def create_pickup_appointment(self, payload, headers):
        return self._request("POST", "/pickup-appointments", payload, headers)

    def get_pickup_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/pickup-appointments/{appointment_id}", headers=headers
        )

    def list_pickup_appointments(self, headers, params=None):
        return self._request(
            "GET", "/pickup-appointments", headers=headers, params=params
        )

    def complete_pickup_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/pickup-appointments/{appointment_id}/complete", payload, headers
        )

    def cancel_pickup_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/pickup-appointments/{appointment_id}/cancel", payload, headers
        )

    # --- disposition assignments (PRD §3.8) ---
    def get_disposition_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/disposition-assignments/{assignment_id}", headers=headers
        )

    def list_disposition_assignments(self, headers, params=None):
        return self._request(
            "GET", "/disposition-assignments", headers=headers, params=params
        )

    def confirm_intake(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/disposition-assignments/{assignment_id}/confirm-intake",
            payload,
            headers,
        )

    # --- refunds (PRD §3.9) ---
    def create_refund_authorization(self, payload, headers):
        return self._request("POST", "/refund-authorizations", payload, headers)

    def get_refund_authorization(self, refund_id, headers):
        return self._request(
            "GET", f"/refund-authorizations/{refund_id}", headers=headers
        )

    def list_refund_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/refund-authorizations", headers=headers, params=params
        )

    def release_refund(self, refund_id, payload, headers):
        return self._request(
            "POST", f"/refund-authorizations/{refund_id}/release", payload, headers
        )

    def void_refund(self, refund_id, payload, headers):
        return self._request(
            "POST", f"/refund-authorizations/{refund_id}/void", payload, headers
        )

    # --- retail partner attribution and price match (PRD §3.10) ---
    def create_attribution_claim(self, payload, headers):
        return self._request("POST", "/attribution-claims", payload, headers)

    def get_attribution_claim(self, claim_id, headers):
        return self._request("GET", f"/attribution-claims/{claim_id}", headers=headers)

    def list_attribution_claims(self, headers, params=None):
        return self._request(
            "GET", "/attribution-claims", headers=headers, params=params
        )

    def review_attribution_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/attribution-claims/{claim_id}/review", payload, headers
        )

    def resubmit_attribution_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/attribution-claims/{claim_id}/resubmit", payload, headers
        )

    def resolve_attribution_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/attribution-claims/{claim_id}/resolve", payload, headers
        )


api_client = ApiClient()
