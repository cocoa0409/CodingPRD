"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # --- Technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # --- Vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def patch_vessel(self, vessel_id, payload, headers):
        return self._request("PATCH", f"/vessels/{vessel_id}", payload, headers)

    # --- Level readings ---
    def create_level_reading(self, payload, headers):
        return self._request("POST", "/level-readings", payload, headers)

    def list_level_readings(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/level-readings", headers=headers, params=params
        )

    # --- Quality reports ---
    def create_quality_report(self, payload, headers):
        return self._request("POST", "/quality-reports", payload, headers)

    def list_quality_reports(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/quality-reports", headers=headers, params=params
        )

    # --- Scale calibrations ---
    def create_scale_calibration(self, payload, headers):
        return self._request("POST", "/scale-calibrations", payload, headers)

    def list_scale_calibrations(self, vessel_id, headers, params=None):
        return self._request(
            "GET",
            f"/vessels/{vessel_id}/scale-calibrations",
            headers=headers,
            params=params,
        )

    # --- Replenishment orders ---
    def get_replenishment_order(self, order_id, headers):
        return self._request(
            "GET", f"/replenishment-orders/{order_id}", headers=headers
        )

    def list_replenishment_orders(self, headers, params=None):
        return self._request(
            "GET", "/replenishment-orders", headers=headers, params=params
        )

    def dispatch_replenishment_order(self, order_id, headers):
        return self._request(
            "POST", f"/replenishment-orders/{order_id}/dispatch", None, headers
        )

    def receive_replenishment_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/replenishment-orders/{order_id}/receive", payload, headers
        )

    def cancel_replenishment_order(self, order_id, headers):
        return self._request(
            "POST", f"/replenishment-orders/{order_id}/cancel", None, headers
        )

    def void_replenishment_order(self, order_id, headers):
        return self._request(
            "POST", f"/replenishment-orders/{order_id}/void", None, headers
        )

    # --- Service tickets ---
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def quote_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/quote", None, headers
        )

    def approve_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/approve", None, headers
        )

    def decline_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/decline", None, headers
        )

    def schedule_service_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/schedule", payload, headers
        )

    def start_service_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/start", None, headers
        )

    def complete_service_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/complete", payload, headers
        )

    # --- Entry permits ---
    def create_entry_permit(self, payload, headers):
        return self._request("POST", "/entry-permits", payload, headers)

    def get_entry_permit(self, permit_id, headers):
        return self._request("GET", f"/entry-permits/{permit_id}", headers=headers)

    def list_entry_permits(self, headers, params=None):
        return self._request("GET", "/entry-permits", headers=headers, params=params)

    def issue_entry_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/entry-permits/{permit_id}/issue", payload, headers
        )

    def activate_entry_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/entry-permits/{permit_id}/activate", payload, headers
        )

    def atmosphere_check_entry_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/entry-permits/{permit_id}/atmosphere-check", payload, headers
        )

    def resume_entry_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/entry-permits/{permit_id}/resume", payload, headers
        )

    def close_entry_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/entry-permits/{permit_id}/close", payload, headers
        )

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
