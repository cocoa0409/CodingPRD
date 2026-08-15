"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving / ops ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/fleet-wash/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_daily(self, headers):
        return self._request("POST", "/fleet-wash/ops/run-daily", {}, headers)

    def evaluate_weather(self, payload, headers):
        return self._request("POST", "/fleet-wash/weather/evaluations", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/fleet-wash/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/fleet-wash/customers/{customer_id}", headers=headers)

    def customer_event(self, customer_id, payload, headers):
        return self._request("POST", f"/fleet-wash/customers/{customer_id}/events", payload, headers)

    # --- sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/fleet-wash/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/fleet-wash/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/fleet-wash/sites", headers=headers, params=params)

    def site_event(self, site_id, payload, headers):
        return self._request("POST", f"/fleet-wash/sites/{site_id}/events", payload, headers)

    # --- vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/fleet-wash/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/fleet-wash/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/fleet-wash/vehicles", headers=headers, params=params)

    # --- fleet contracts ---
    def create_fleet_contract(self, payload, headers):
        return self._request("POST", "/fleet-wash/fleet-contracts", payload, headers)

    def get_fleet_contract(self, contract_id, headers):
        return self._request("GET", f"/fleet-wash/fleet-contracts/{contract_id}", headers=headers)

    def list_fleet_contracts(self, headers, params=None):
        return self._request("GET", "/fleet-wash/fleet-contracts", headers=headers, params=params)

    def amend_fleet_contract(self, contract_id, payload, headers):
        return self._request("PUT", f"/fleet-wash/fleet-contracts/{contract_id}", payload, headers)

    def fleet_contract_event(self, contract_id, payload, headers):
        return self._request("POST", f"/fleet-wash/fleet-contracts/{contract_id}/events", payload, headers)

    # --- subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/fleet-wash/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/fleet-wash/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/fleet-wash/subscriptions", headers=headers, params=params)

    def subscription_event(self, subscription_id, payload, headers):
        return self._request("POST", f"/fleet-wash/subscriptions/{subscription_id}/events", payload, headers)

    # --- wash orders ---
    def create_wash_order(self, payload, headers):
        return self._request("POST", "/fleet-wash/wash-orders", payload, headers)

    def get_wash_order(self, order_id, headers):
        return self._request("GET", f"/fleet-wash/wash-orders/{order_id}", headers=headers)

    def list_wash_orders(self, headers, params=None):
        return self._request("GET", "/fleet-wash/wash-orders", headers=headers, params=params)

    def wash_order_event(self, order_id, payload, headers):
        return self._request("POST", f"/fleet-wash/wash-orders/{order_id}/events", payload, headers)

    def reschedule_wash_order(self, order_id, payload, headers):
        return self._request("POST", f"/fleet-wash/wash-orders/{order_id}/reschedule", payload, headers)

    def rewash_wash_order(self, order_id, headers):
        return self._request("POST", f"/fleet-wash/wash-orders/{order_id}/rewash", {}, headers)

    def list_order_route_stops(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/fleet-wash/wash-orders/{order_id}/route-stops",
            headers=headers, params=params,
        )

    # --- routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/fleet-wash/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/fleet-wash/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/fleet-wash/routes", headers=headers, params=params)

    def route_event(self, route_id, payload, headers):
        return self._request("POST", f"/fleet-wash/routes/{route_id}/events", payload, headers)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/fleet-wash/routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/fleet-wash/routes/{route_id}/stops", headers=headers, params=params)

    def route_stop_event(self, route_id, stop_id, payload, headers):
        return self._request(
            "POST", f"/fleet-wash/routes/{route_id}/stops/{stop_id}/events", payload, headers,
        )

    # --- vans ---
    def create_van(self, payload, headers):
        return self._request("POST", "/fleet-wash/vans", payload, headers)

    def get_van(self, van_id, headers):
        return self._request("GET", f"/fleet-wash/vans/{van_id}", headers=headers)

    def van_event(self, van_id, payload, headers):
        return self._request("POST", f"/fleet-wash/vans/{van_id}/events", payload, headers)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/fleet-wash/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/fleet-wash/technicians/{technician_id}", headers=headers)

    def technician_event(self, technician_id, payload, headers):
        return self._request("POST", f"/fleet-wash/technicians/{technician_id}/events", payload, headers)

    # --- inspection reports ---
    def create_inspection_report(self, payload, headers):
        return self._request("POST", "/fleet-wash/inspection-reports", payload, headers)

    def get_inspection_report(self, report_id, headers):
        return self._request("GET", f"/fleet-wash/inspection-reports/{report_id}", headers=headers)

    def list_inspection_reports(self, headers, params=None):
        return self._request("GET", "/fleet-wash/inspection-reports", headers=headers, params=params)

    def inspection_report_event(self, report_id, payload, headers):
        return self._request("POST", f"/fleet-wash/inspection-reports/{report_id}/events", payload, headers)

    # --- damage claims ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/fleet-wash/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/fleet-wash/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/fleet-wash/damage-claims", headers=headers, params=params)

    def damage_claim_event(self, claim_id, payload, headers):
        return self._request("POST", f"/fleet-wash/damage-claims/{claim_id}/events", payload, headers)

    # --- quality audits ---
    def create_quality_audit(self, payload, headers):
        return self._request("POST", "/fleet-wash/quality-audits", payload, headers)

    def get_quality_audit(self, audit_id, headers):
        return self._request("GET", f"/fleet-wash/quality-audits/{audit_id}", headers=headers)

    def list_quality_audits(self, headers, params=None):
        return self._request("GET", "/fleet-wash/quality-audits", headers=headers, params=params)

    # --- compliance incidents ---
    def create_compliance_incident(self, payload, headers):
        return self._request("POST", "/fleet-wash/compliance-incidents", payload, headers)

    def get_compliance_incident(self, incident_id, headers):
        return self._request("GET", f"/fleet-wash/compliance-incidents/{incident_id}", headers=headers)

    def list_compliance_incidents(self, headers, params=None):
        return self._request("GET", "/fleet-wash/compliance-incidents", headers=headers, params=params)

    def compliance_incident_event(self, incident_id, payload, headers):
        return self._request("POST", f"/fleet-wash/compliance-incidents/{incident_id}/events", payload, headers)

    # --- invoices ---
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/fleet-wash/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fleet-wash/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/fleet-wash/invoices", headers=headers, params=params)

    def invoice_event(self, invoice_id, payload, headers):
        return self._request("POST", f"/fleet-wash/invoices/{invoice_id}/events", payload, headers)


api_client = ApiClient()
