"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.6)
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Customer accounts
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/v1/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/v1/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/v1/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/v1/customers/{customer_id}", payload, headers)

    def list_customer_quotes(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/quotes",
                             headers=headers, params=params)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/orders",
                             headers=headers, params=params)

    def list_customer_safety_audits(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/v1/customers/{customer_id}/safety-audits",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/v1/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/api/v1/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/v1/vehicles/{vehicle_id}", headers=headers)

    def send_vehicle_to_maintenance(self, vehicle_id, headers):
        return self._request("POST", f"/api/v1/vehicles/{vehicle_id}/send-to-maintenance",
                             {}, headers)

    def decommission_vehicle(self, vehicle_id, payload, headers):
        return self._request("POST", f"/api/v1/vehicles/{vehicle_id}/decommission",
                             payload, headers)

    def list_vehicle_orders(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/api/v1/vehicles/{vehicle_id}/orders",
                             headers=headers, params=params)

    def list_vehicle_incidents(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/api/v1/vehicles/{vehicle_id}/incidents",
                             headers=headers, params=params)

    def list_vehicle_breakdowns(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/api/v1/vehicles/{vehicle_id}/breakdowns",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Drivers
    # ------------------------------------------------------------------
    def create_driver(self, payload, headers):
        return self._request("POST", "/api/v1/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/api/v1/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/api/v1/drivers/{driver_id}", headers=headers)

    def suspend_driver(self, driver_id, payload, headers):
        return self._request("POST", f"/api/v1/drivers/{driver_id}/suspend",
                             payload, headers)

    def reinstate_driver(self, driver_id, headers):
        return self._request("POST", f"/api/v1/drivers/{driver_id}/reinstate", {}, headers)

    def check_driver_rest(self, driver_id, headers):
        return self._request("POST", f"/api/v1/drivers/{driver_id}/check-rest", {}, headers)

    def list_driver_orders(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/v1/drivers/{driver_id}/orders",
                             headers=headers, params=params)

    def list_driver_trip_logs(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/v1/drivers/{driver_id}/trip-logs",
                             headers=headers, params=params)

    def list_driver_incidents(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/v1/drivers/{driver_id}/incidents",
                             headers=headers, params=params)

    def list_driver_breakdowns(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/v1/drivers/{driver_id}/breakdowns",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Charter quotes
    # ------------------------------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", "/api/v1/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/api/v1/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/api/v1/quotes/{quote_id}", headers=headers)

    def price_quote(self, quote_id, headers):
        return self._request("POST", f"/api/v1/quotes/{quote_id}/price", {}, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/api/v1/quotes/{quote_id}/accept", payload, headers)

    def cancel_quote(self, quote_id, headers):
        return self._request("POST", f"/api/v1/quotes/{quote_id}/cancel", {}, headers)

    def check_quote_expiry(self, quote_id, headers):
        return self._request("POST", f"/api/v1/quotes/{quote_id}/check-expiry", {}, headers)

    def list_quote_orders(self, quote_id, headers, params=None):
        return self._request("GET", f"/api/v1/quotes/{quote_id}/orders",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Charter orders
    # ------------------------------------------------------------------
    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/v1/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/v1/orders/{order_id}", headers=headers)

    def pay_deposit(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/pay-deposit",
                             payload, headers)

    def assign_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/assign", payload, headers)

    def start_trip(self, order_id, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/start-trip", {}, headers)

    def complete_trip(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/complete-trip",
                             payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/cancel", payload, headers)

    def dispute_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/dispute", payload, headers)

    def record_itinerary_change(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/itinerary-change",
                             payload, headers)

    # ------------------------------------------------------------------
    # Trip logs
    # ------------------------------------------------------------------
    def create_trip_log(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/trip-logs",
                             payload, headers)

    def list_trip_logs(self, order_id, headers, params=None):
        return self._request("GET", f"/api/v1/orders/{order_id}/trip-logs",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def create_incident(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/incidents",
                             payload, headers)

    def list_incidents(self, order_id, headers, params=None):
        return self._request("GET", f"/api/v1/orders/{order_id}/incidents",
                             headers=headers, params=params)

    def update_incident(self, incident_id, payload, headers):
        return self._request("PATCH", f"/api/v1/incidents/{incident_id}", payload, headers)

    # ------------------------------------------------------------------
    # Maintenance records
    # ------------------------------------------------------------------
    def create_maintenance_record(self, vehicle_id, payload, headers):
        return self._request("POST", f"/api/v1/vehicles/{vehicle_id}/maintenance-records",
                             payload, headers)

    def list_maintenance_records(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/api/v1/vehicles/{vehicle_id}/maintenance-records",
                             headers=headers, params=params)

    def start_maintenance(self, record_id, headers):
        return self._request("POST", f"/api/v1/maintenance-records/{record_id}/start",
                             {}, headers)

    def complete_maintenance(self, record_id, payload, headers):
        return self._request("POST", f"/api/v1/maintenance-records/{record_id}/complete",
                             payload, headers)

    # ------------------------------------------------------------------
    # Breakdown events
    # ------------------------------------------------------------------
    def report_breakdown(self, order_id, payload, headers):
        return self._request("POST", f"/api/v1/orders/{order_id}/breakdowns",
                             payload, headers)

    def list_order_breakdowns(self, order_id, headers, params=None):
        return self._request("GET", f"/api/v1/orders/{order_id}/breakdowns",
                             headers=headers, params=params)

    def get_breakdown(self, breakdown_id, headers):
        return self._request("GET", f"/api/v1/breakdowns/{breakdown_id}", headers=headers)

    def list_breakdowns(self, headers, params=None):
        return self._request("GET", "/api/v1/breakdowns", headers=headers, params=params)

    def dispatch_breakdown(self, breakdown_id, payload, headers):
        return self._request("POST", f"/api/v1/breakdowns/{breakdown_id}/dispatch",
                             payload, headers)

    def breakdown_en_route(self, breakdown_id, headers):
        return self._request("POST", f"/api/v1/breakdowns/{breakdown_id}/en-route",
                             {}, headers)

    def complete_replacement(self, breakdown_id, payload, headers):
        return self._request("POST", f"/api/v1/breakdowns/{breakdown_id}/complete-replacement",
                             payload, headers)

    def resolve_breakdown_in_place(self, breakdown_id, payload, headers):
        return self._request("POST", f"/api/v1/breakdowns/{breakdown_id}/resolve-in-place",
                             payload, headers)

    def cancel_breakdown_dispatch(self, breakdown_id, headers):
        return self._request("POST", f"/api/v1/breakdowns/{breakdown_id}/cancel-dispatch",
                             {}, headers)

    # ------------------------------------------------------------------
    # Insurance certificates
    # ------------------------------------------------------------------
    def request_certificate(self, payload, headers):
        return self._request("POST", "/api/v1/insurance-certificates", payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/api/v1/insurance-certificates",
                             headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/api/v1/insurance-certificates/{certificate_id}",
                             headers=headers)

    def issue_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/v1/insurance-certificates/{certificate_id}/issue",
                             {}, headers)

    def revoke_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/api/v1/insurance-certificates/{certificate_id}/revoke",
                             payload, headers)

    # ------------------------------------------------------------------
    # Safety audit requests
    # ------------------------------------------------------------------
    def request_safety_audit(self, payload, headers):
        return self._request("POST", "/api/v1/safety-audits", payload, headers)

    def list_safety_audits(self, headers, params=None):
        return self._request("GET", "/api/v1/safety-audits", headers=headers, params=params)

    def get_safety_audit(self, audit_id, headers):
        return self._request("GET", f"/api/v1/safety-audits/{audit_id}", headers=headers)

    def begin_audit_review(self, audit_id, headers):
        return self._request("POST", f"/api/v1/safety-audits/{audit_id}/begin-review",
                             {}, headers)

    def approve_safety_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/v1/safety-audits/{audit_id}/approve",
                             payload, headers)

    def reject_safety_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/api/v1/safety-audits/{audit_id}/reject",
                             payload, headers)

    def finalize_safety_audit(self, audit_id, headers):
        return self._request("POST", f"/api/v1/safety-audits/{audit_id}/finalize",
                             {}, headers)


api_client = ApiClient()
