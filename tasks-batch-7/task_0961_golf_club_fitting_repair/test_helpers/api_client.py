"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/golf-shop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/golf-shop/customers/{customer_id}", headers=headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request("POST", f"/golf-shop/customers/{customer_id}/set-status", payload, headers)

    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/golf-shop/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/golf-shop/staff/{staff_id}", headers=headers)

    # --- Launch monitor bays ---
    def create_bay(self, payload, headers):
        return self._request("POST", "/golf-shop/launch-monitor-bays", payload, headers)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/golf-shop/launch-monitor-bays/{bay_id}", headers=headers)

    def set_bay_status(self, bay_id, payload, headers):
        return self._request("POST", f"/golf-shop/launch-monitor-bays/{bay_id}/set-status", payload, headers)

    # --- Fitting sessions ---
    def create_fitting_session(self, payload, headers):
        return self._request("POST", "/golf-shop/fitting-sessions", payload, headers)

    def get_fitting_session(self, session_id, headers):
        return self._request("GET", f"/golf-shop/fitting-sessions/{session_id}", headers=headers)

    def list_fitting_sessions(self, headers, params=None):
        return self._request("GET", "/golf-shop/fitting-sessions", headers=headers, params=params)

    def check_in_session(self, session_id, headers):
        return self._request("POST", f"/golf-shop/fitting-sessions/{session_id}/check-in", headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/golf-shop/fitting-sessions/{session_id}/complete", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/golf-shop/fitting-sessions/{session_id}/cancel", headers=headers)

    # --- Lesson packages ---
    def create_lesson_package(self, payload, headers):
        return self._request("POST", "/golf-shop/lesson-packages", payload, headers)

    def get_lesson_package(self, package_id, headers):
        return self._request("GET", f"/golf-shop/lesson-packages/{package_id}", headers=headers)

    def list_lesson_packages(self, headers, params=None):
        return self._request("GET", "/golf-shop/lesson-packages", headers=headers, params=params)

    # --- Build specs ---
    def create_build_spec(self, payload, headers):
        return self._request("POST", "/golf-shop/build-specs", payload, headers)

    def get_build_spec(self, spec_id, headers):
        return self._request("GET", f"/golf-shop/build-specs/{spec_id}", headers=headers)

    def list_build_specs(self, headers, params=None):
        return self._request("GET", "/golf-shop/build-specs", headers=headers, params=params)

    def quote_build_spec(self, spec_id, payload, headers):
        return self._request("POST", f"/golf-shop/build-specs/{spec_id}/quote", payload, headers)

    def approve_build_spec(self, spec_id, payload, headers):
        return self._request("POST", f"/golf-shop/build-specs/{spec_id}/approve", payload, headers)

    def cancel_build_spec(self, spec_id, headers):
        return self._request("POST", f"/golf-shop/build-specs/{spec_id}/cancel", headers=headers)

    def mark_ready_build_spec(self, spec_id, headers):
        return self._request("POST", f"/golf-shop/build-specs/{spec_id}/mark-ready", headers=headers)

    def deliver_build_spec(self, spec_id, headers):
        return self._request("POST", f"/golf-shop/build-specs/{spec_id}/deliver", headers=headers)

    # --- Component items ---
    def create_component_item(self, payload, headers):
        return self._request("POST", "/golf-shop/component-items", payload, headers)

    def get_component_item(self, item_id, headers):
        return self._request("GET", f"/golf-shop/component-items/{item_id}", headers=headers)

    def list_component_items(self, headers, params=None):
        return self._request("GET", "/golf-shop/component-items", headers=headers, params=params)

    def receive_component_item(self, item_id, payload, headers):
        return self._request("POST", f"/golf-shop/component-items/{item_id}/receive", payload, headers)

    # --- Component orders ---
    def get_component_order(self, order_id, headers):
        return self._request("GET", f"/golf-shop/component-orders/{order_id}", headers=headers)

    def list_component_orders(self, headers, params=None):
        return self._request("GET", "/golf-shop/component-orders", headers=headers, params=params)

    # --- Repair tickets ---
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/golf-shop/repair-tickets", payload, headers)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/golf-shop/repair-tickets/{ticket_id}", headers=headers)

    def list_repair_tickets(self, headers, params=None):
        return self._request("GET", "/golf-shop/repair-tickets", headers=headers, params=params)

    def approve_repair_ticket(self, ticket_id, headers):
        return self._request("POST", f"/golf-shop/repair-tickets/{ticket_id}/approve", headers=headers)

    def start_work(self, ticket_id, headers):
        return self._request("POST", f"/golf-shop/repair-tickets/{ticket_id}/start-work", headers=headers)

    def submit_qc(self, ticket_id, payload, headers):
        return self._request("POST", f"/golf-shop/repair-tickets/{ticket_id}/submit-qc", payload, headers)

    def pickup_ticket(self, ticket_id, headers):
        return self._request("POST", f"/golf-shop/repair-tickets/{ticket_id}/pickup", headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/golf-shop/repair-tickets/{ticket_id}/cancel", headers=headers)

    def pay_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/golf-shop/repair-tickets/{ticket_id}/payments", payload, headers)

    # --- Trade-in appraisals ---
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/golf-shop/trade-in-appraisals", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/golf-shop/trade-in-appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/golf-shop/trade-in-appraisals", headers=headers, params=params)

    def create_offer(self, appraisal_id, payload, headers):
        return self._request("POST", f"/golf-shop/trade-in-appraisals/{appraisal_id}/offers", payload, headers)

    def accept_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/golf-shop/trade-in-appraisals/{appraisal_id}/accept", headers=headers)

    def decline_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/golf-shop/trade-in-appraisals/{appraisal_id}/decline", headers=headers)

    # --- Used club listings ---
    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/golf-shop/used-club-listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/golf-shop/used-club-listings", headers=headers, params=params)

    def reserve_listing(self, listing_id, headers):
        return self._request("POST", f"/golf-shop/used-club-listings/{listing_id}/reserve", headers=headers)

    def purchase_listing(self, listing_id, headers):
        return self._request("POST", f"/golf-shop/used-club-listings/{listing_id}/purchase", headers=headers)

    def adjust_listing_price(self, listing_id, payload, headers):
        return self._request("POST", f"/golf-shop/used-club-listings/{listing_id}/adjust-price", payload, headers)

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/golf-shop/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/golf-shop/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/golf-shop/warranty-claims", headers=headers, params=params)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/golf-shop/warranty-claims/{claim_id}/decide", payload, headers)

    def resolve_claim(self, claim_id, headers):
        return self._request("POST", f"/golf-shop/warranty-claims/{claim_id}/resolve", headers=headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/golf-shop/warranty-claims/{claim_id}/appeal", headers=headers)

    # --- Credit ledger ---
    def list_credit_ledger_entries(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/golf-shop/customers/{customer_id}/credit-ledger-entries",
            headers=headers, params=params,
        )

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/golf-shop/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
