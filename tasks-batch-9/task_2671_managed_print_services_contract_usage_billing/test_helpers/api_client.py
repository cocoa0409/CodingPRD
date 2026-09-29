"""API client: one method per endpoint published by the managed print services platform."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the managed print services API.

    Every method returns the raw ``requests.Response`` so tests can assert on
    HTTP status codes as well as the response envelope.
    """

    # ------------------------------------------------------------------
    # Service contracts and rate cards
    # ------------------------------------------------------------------
    def create_service_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/service-contracts", payload, headers)

    def get_service_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-contracts/{contract_id}", headers=headers)

    def create_cost_tier(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/service-contracts/{contract_id}/cost-tiers", payload, headers
        )

    def list_cost_tiers(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/service-contracts/{contract_id}/cost-tiers", headers=headers, params=params
        )

    def activate_service_contract(self, contract_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/service-contracts/{contract_id}/activate", payload or {}, headers
        )

    def suspend_service_contract(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/service-contracts/{contract_id}/suspend", payload, headers
        )

    def resume_service_contract(self, contract_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/service-contracts/{contract_id}/resume", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Sites, secure print release and the parts locker
    # ------------------------------------------------------------------
    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def configure_secure_release(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/sites/{site_id}/secure-release-config", payload, headers)

    def adjust_spare_part_stock(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/sites/{site_id}/spare-part-stocks", payload, headers)

    def list_spare_part_stocks(self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sites/{site_id}/spare-part-stocks", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def create_device(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def place_device(self, device_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/devices/{device_id}/place", payload or {}, headers)

    def network_integrate_device(self, device_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/devices/{device_id}/network-integration", payload or {}, headers
        )

    def activate_device(self, device_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", f"/devices/{device_id}/activate", payload or {}, headers)

    def link_refresh_replacement(self, device_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/devices/{device_id}/refresh-replacement", payload, headers
        )

    def list_device_statement_lines(self, device_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/devices/{device_id}/statement-lines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Technicians
    # ------------------------------------------------------------------
    def create_technician(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Billing periods
    # ------------------------------------------------------------------
    def create_billing_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/billing-periods", payload, headers)

    def get_billing_period(self, period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/billing-periods/{period_id}", headers=headers)

    def list_billing_periods(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/billing-periods", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Meter capture
    # ------------------------------------------------------------------
    def submit_automated_meter_read(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_agent/meter-reads", payload, headers)

    def submit_manual_meter_read(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/meter-reads", payload, headers)

    def get_meter_read(self, read_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/meter-reads/{read_id}", headers=headers)

    def list_meter_reads(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/meter-reads", headers=headers, params=params)

    def resolve_meter_read_exception(self, read_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/meter-reads/{read_id}/resolve-exception", payload, headers
        )

    def void_meter_read(self, read_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/meter-reads/{read_id}/void", payload, headers)

    def run_meter_sweep(self, period_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/billing-periods/{period_id}/meter-sweep", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------
    def generate_provisional_statement(self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/billing-periods/{period_id}/provisional-statement", payload, headers
        )

    def close_billing_period(self, period_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/billing-periods/{period_id}/close", payload or {}, headers
        )

    def get_billing_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/billing-statements/{statement_id}", headers=headers)

    def list_billing_statements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/billing-statements", headers=headers, params=params)

    def list_statement_lines(self, statement_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/billing-statements/{statement_id}/lines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Consumable orders
    # ------------------------------------------------------------------
    def create_consumable_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/consumable-orders", payload, headers)

    def get_consumable_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/consumable-orders/{order_id}", headers=headers)

    def list_consumable_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/consumable-orders", headers=headers, params=params)

    def deliver_consumable_order(self, order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/consumable-orders/{order_id}/deliver", payload or {}, headers
        )

    def cancel_consumable_order(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/consumable-orders/{order_id}/cancel", payload, headers)

    # ------------------------------------------------------------------
    # Service tickets and dispatch
    # ------------------------------------------------------------------
    def create_service_ticket(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def dispatch_service_ticket(self, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/service-tickets/{ticket_id}/dispatch", payload, headers)

    def put_service_ticket_on_parts_hold(self, ticket_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/parts-hold", payload or {}, headers
        )

    def arrive_onsite(self, ticket_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/arrive-onsite", payload or {}, headers
        )

    def resolve_service_ticket(self, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/service-tickets/{ticket_id}/resolve", payload, headers)

    def cancel_service_ticket(self, ticket_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Quarterly business reviews
    # ------------------------------------------------------------------
    def create_quarterly_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/quarterly-reviews", payload, headers)

    def get_quarterly_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/quarterly-reviews/{review_id}", headers=headers)

    def list_contract_quarterly_reviews(self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/service-contracts/{contract_id}/quarterly-reviews", headers=headers, params=params
        )

    def approve_quarterly_review(self, review_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/quarterly-reviews/{review_id}/approve", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Removal and settlement
    # ------------------------------------------------------------------
    def create_removal_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/removal-orders", payload, headers)

    def get_removal_order(self, removal_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/removal-orders/{removal_order_id}", headers=headers)

    def list_removal_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/removal-orders", headers=headers, params=params)

    def schedule_removal_order(self, removal_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/removal-orders/{removal_order_id}/schedule", payload, headers
        )

    def collect_removal_order(self, removal_order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/removal-orders/{removal_order_id}/collect", payload or {}, headers
        )

    def sanitize_removal_order(self, removal_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/removal-orders/{removal_order_id}/sanitize", payload, headers
        )

    def settle_removal_order(self, removal_order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/removal-orders/{removal_order_id}/settle", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
