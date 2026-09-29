"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the mail-order contact lens platform."""

    # ----------------------------------------------------------------- clock
    def set_logical_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def read_logical_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # -------------------------------------------------------- insurance plans
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    def list_insurance_plans(self, headers, params=None):
        return self._request("GET", "/insurance-plans", headers=headers, params=params)

    def retire_insurance_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/insurance-plans/{plan_id}/retire", {}, headers
        )

    # --------------------------------------------------------------- products
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def deactivate_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/deactivate", {}, headers)

    def create_lens_equivalence(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/lens-equivalences", payload, headers
        )

    def list_lens_equivalences_for_product(self, product_id, headers, params=None):
        return self._request(
            "GET",
            f"/products/{product_id}/lens-equivalences",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------- prescribers
    def create_prescriber(self, payload, headers):
        return self._request("POST", "/prescribers", payload, headers)

    def get_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/prescribers/{prescriber_id}", headers=headers)

    def list_prescribers(self, headers, params=None):
        return self._request("GET", "/prescribers", headers=headers, params=params)

    def suspend_prescriber(self, prescriber_id, headers):
        return self._request(
            "POST", f"/prescribers/{prescriber_id}/suspend", {}, headers
        )

    # --------------------------------------------------------------- customers
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer_ledger(self, customer_id, headers):
        return self._request(
            "GET", f"/customers/{customer_id}/ledger", headers=headers
        )

    # ----------------------------------------------------------- prescriptions
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"/prescriptions/{prescription_id}", headers=headers
        )

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def submit_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/submit", {}, headers
        )

    def send_verification_request(self, prescription_id, payload, headers):
        return self._request(
            "POST",
            f"/prescriptions/{prescription_id}/verification-requests",
            payload,
            headers,
        )

    def list_compliance_events_for_prescription(
        self, prescription_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/prescriptions/{prescription_id}/compliance-events",
            headers=headers,
            params=params,
        )

    def invalidate_prescription(self, prescription_id, payload, headers):
        return self._request(
            "POST", f"/prescriptions/{prescription_id}/invalidate", payload, headers
        )

    # ---------------------------------------------------- verification requests
    def get_verification_request(self, request_id, headers):
        return self._request(
            "GET", f"/verification-requests/{request_id}", headers=headers
        )

    def list_verification_requests(self, headers, params=None):
        return self._request(
            "GET", "/verification-requests", headers=headers, params=params
        )

    def respond_to_verification_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/verification-requests/{request_id}/respond", payload, headers
        )

    def run_verification_sweep(self, headers):
        return self._request("POST", "/compliance/verification-sweep", {}, headers)

    # ------------------------------------------------------------------ orders
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def apply_substitution(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/substitution", payload, headers
        )

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # ----------------------------------------------------------- reorder holds
    def create_reorder_hold(self, payload, headers):
        return self._request("POST", "/reorder-holds", payload, headers)

    def get_reorder_hold(self, hold_id, headers):
        return self._request("GET", f"/reorder-holds/{hold_id}", headers=headers)

    def list_reorder_holds(self, headers, params=None):
        return self._request("GET", "/reorder-holds", headers=headers, params=params)

    def release_reorder_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/reorder-holds/{hold_id}/release", payload, headers
        )

    def escalate_reorder_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/reorder-holds/{hold_id}/escalate", payload, headers
        )

    # --------------------------------------------------- auto-reorder schedules
    def create_auto_reorder_schedule(self, payload, headers):
        return self._request("POST", "/auto-reorder-schedules", payload, headers)

    def get_auto_reorder_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/auto-reorder-schedules/{schedule_id}", headers=headers
        )

    def list_auto_reorder_schedules(self, headers, params=None):
        return self._request(
            "GET", "/auto-reorder-schedules", headers=headers, params=params
        )

    def pause_auto_reorder_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/auto-reorder-schedules/{schedule_id}/pause", {}, headers
        )

    def resume_auto_reorder_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/auto-reorder-schedules/{schedule_id}/resume", {}, headers
        )

    def cancel_auto_reorder_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/auto-reorder-schedules/{schedule_id}/cancel", {}, headers
        )

    def run_auto_reorder(self, headers):
        return self._request("POST", "/fulfillment/auto-reorder-run", {}, headers)

    # --------------------------------------------------------- return requests
    def create_return_request(self, payload, headers):
        return self._request("POST", "/return-requests", payload, headers)

    def get_return_request(self, return_id, headers):
        return self._request("GET", f"/return-requests/{return_id}", headers=headers)

    def list_return_requests(self, headers, params=None):
        return self._request("GET", "/return-requests", headers=headers, params=params)

    def approve_return_request(self, return_id, headers):
        return self._request(
            "POST", f"/return-requests/{return_id}/approve", {}, headers
        )

    def reject_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"/return-requests/{return_id}/reject", payload, headers
        )

    def settle_return_request(self, return_id, headers):
        return self._request(
            "POST", f"/return-requests/{return_id}/settle", {}, headers
        )

    # ---------------------------------------------------- reimbursement claims
    def create_reimbursement_claim(self, payload, headers):
        return self._request("POST", "/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/reimbursement-claims/{claim_id}", headers=headers
        )

    def list_reimbursement_claims(self, headers, params=None):
        return self._request(
            "GET", "/reimbursement-claims", headers=headers, params=params
        )

    def generate_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/generate", {}, headers
        )

    def submit_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/submit", {}, headers
        )

    def void_reimbursement_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/void", payload, headers
        )

    # ------------------------------------------------------ prescriber disputes
    def file_prescriber_dispute(self, payload, headers):
        return self._request("POST", "/prescriber-disputes", payload, headers)

    def get_prescriber_dispute(self, dispute_id, headers):
        return self._request(
            "GET", f"/prescriber-disputes/{dispute_id}", headers=headers
        )

    def list_prescriber_disputes(self, headers, params=None):
        return self._request(
            "GET", "/prescriber-disputes", headers=headers, params=params
        )

    def resolve_prescriber_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/prescriber-disputes/{dispute_id}/resolve", payload, headers
        )


api_client = ApiClient()
