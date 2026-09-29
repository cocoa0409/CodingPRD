"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Marine Bunkering & Vessel Fuel Supply API endpoints (PRD §4)."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Ports ────────────────────────────────────────

    def create_port(self, payload, headers):
        return self._request("POST", "/ports", payload, headers)

    def get_port(self, port_id, headers):
        return self._request("GET", f"/ports/{port_id}", headers=headers)

    def list_ports(self, headers, params=None):
        return self._request("GET", "/ports", headers=headers, params=params)

    # ─── Fuel grades ──────────────────────────────────

    def create_fuel_grade(self, payload, headers):
        return self._request("POST", "/fuel-grades", payload, headers)

    def get_fuel_grade(self, grade_id, headers):
        return self._request("GET", f"/fuel-grades/{grade_id}", headers=headers)

    def list_grade_index_quotes(self, grade_id, headers, params=None):
        return self._request(
            "GET", f"/fuel-grades/{grade_id}/index-quotes", headers=headers, params=params
        )

    # ─── Index quotes ─────────────────────────────────

    def create_index_quote(self, payload, headers):
        return self._request("POST", "/index-quotes", payload, headers)

    # ─── Customers ────────────────────────────────────

    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_credit_exposure(self, customer_id, headers):
        return self._request(
            "GET", f"/customers/{customer_id}/credit-exposure", headers=headers
        )

    def credit_review(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/credit-review", payload, headers
        )

    # ─── Delivery assets ──────────────────────────────

    def create_delivery_asset(self, payload, headers):
        return self._request("POST", "/delivery-assets", payload, headers)

    def get_delivery_asset(self, asset_id, headers):
        return self._request("GET", f"/delivery-assets/{asset_id}", headers=headers)

    def list_delivery_assets(self, headers, params=None):
        return self._request("GET", "/delivery-assets", headers=headers, params=params)

    def return_asset_to_service(self, asset_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-assets/{asset_id}/return-to-service", payload or {}, headers
        )

    # ─── Nominations ──────────────────────────────────

    def create_nomination(self, payload, headers):
        return self._request("POST", "/nominations", payload, headers)

    def get_nomination(self, nomination_id, headers):
        return self._request("GET", f"/nominations/{nomination_id}", headers=headers)

    def list_nominations(self, headers, params=None):
        return self._request("GET", "/nominations", headers=headers, params=params)

    def compliance_review(self, nomination_id, payload, headers):
        return self._request(
            "POST", f"/nominations/{nomination_id}/compliance-review", payload, headers
        )

    def confirm_nomination(self, nomination_id, headers, payload=None):
        return self._request(
            "POST", f"/nominations/{nomination_id}/confirm", payload or {}, headers
        )

    def auto_schedule_nomination(self, nomination_id, payload, headers):
        return self._request(
            "POST", f"/nominations/{nomination_id}/auto-schedule", payload, headers
        )

    # ─── Delivery orders ──────────────────────────────

    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def get_delivery_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def clear_delivery_order(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/clear", payload, headers)

    def start_pumping(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/start-pumping", payload or {}, headers
        )

    def complete_pumping(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/complete-pumping", payload, headers
        )

    def file_joint_survey(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/joint-survey", payload, headers
        )

    def submit_quantity_decision(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/quantity-decision", payload, headers
        )

    def cancel_delivery_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/cancel", payload or {}, headers
        )

    # ─── Bunker delivery notes ────────────────────────

    def create_bunker_delivery_note(self, payload, headers):
        return self._request("POST", "/bunker-delivery-notes", payload, headers)

    def get_bunker_delivery_note(self, bdn_id, headers):
        return self._request("GET", f"/bunker-delivery-notes/{bdn_id}", headers=headers)

    def list_bunker_delivery_notes(self, headers, params=None):
        return self._request(
            "GET", "/bunker-delivery-notes", headers=headers, params=params
        )

    def release_sample(self, bdn_id, headers, payload=None):
        return self._request(
            "POST", f"/bunker-delivery-notes/{bdn_id}/release-sample", payload or {}, headers
        )

    # ─── Quality claims ───────────────────────────────

    def create_quality_claim(self, payload, headers):
        return self._request("POST", "/quality-claims", payload, headers)

    def get_quality_claim(self, claim_id, headers):
        return self._request("GET", f"/quality-claims/{claim_id}", headers=headers)

    def list_quality_claims(self, headers, params=None):
        return self._request("GET", "/quality-claims", headers=headers, params=params)

    def claim_decision(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/decision", payload, headers
        )

    def request_retest(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/request-retest", payload or {}, headers
        )

    def accept_remediation(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/quality-claims/{claim_id}/accept-remediation", payload or {}, headers
        )

    # ─── Laboratory analyses ──────────────────────────

    def create_lab_analysis(self, payload, headers):
        return self._request("POST", "/lab-analyses", payload, headers)

    def get_lab_analysis(self, analysis_id, headers):
        return self._request("GET", f"/lab-analyses/{analysis_id}", headers=headers)

    def list_lab_analyses(self, headers, params=None):
        return self._request("GET", "/lab-analyses", headers=headers, params=params)

    # ─── Invoices ─────────────────────────────────────

    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/issue", payload or {}, headers
        )

    def void_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/void", payload or {}, headers
        )

    # ─── Spill incidents ──────────────────────────────

    def create_spill_incident(self, payload, headers):
        return self._request("POST", "/spill-incidents", payload, headers)

    def get_spill_incident(self, incident_id, headers):
        return self._request("GET", f"/spill-incidents/{incident_id}", headers=headers)

    def list_spill_incidents(self, headers, params=None):
        return self._request("GET", "/spill-incidents", headers=headers, params=params)

    def confirm_containment(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/spill-incidents/{incident_id}/confirm-containment", payload, headers
        )

    def close_spill_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST", f"/spill-incidents/{incident_id}/close", payload or {}, headers
        )


api_client = ApiClient()
