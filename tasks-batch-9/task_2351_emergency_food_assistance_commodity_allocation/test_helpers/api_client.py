"""One method per endpoint of the Emergency Food Assistance Allocation API.

Every method returns the raw ``requests.Response`` so callers can assert on the
status code as well as the envelope. All business paths are mounted under
``/efap``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/efap"


class ApiClient(GenericApiClient):
    """Endpoint surface of the EFAP allocation API."""

    def _patch(self, path: str, payload: Any, headers: Optional[Dict[str, str]]):
        return self._request("PATCH", path, payload, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def get_clock(self, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/_clock/current", None, headers)

    # ------------------------------------------------------------------
    # Service areas
    # ------------------------------------------------------------------
    def create_service_area(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/service-areas", payload, headers)

    def list_service_areas(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/service-areas", params, headers)

    def get_service_area(self, service_area_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/service-areas/{service_area_id}", None, headers
        )

    def patch_service_area(self, service_area_id, payload, headers=None) -> requests.Response:
        return self._patch(f"{PREFIX}/service-areas/{service_area_id}", payload, headers)

    # ------------------------------------------------------------------
    # Agencies
    # ------------------------------------------------------------------
    def create_agency(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/agencies", payload, headers)

    def list_agencies(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/agencies", params, headers)

    def get_agency(self, agency_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/agencies/{agency_id}", None, headers)

    def patch_agency(self, agency_id, payload, headers=None) -> requests.Response:
        return self._patch(f"{PREFIX}/agencies/{agency_id}", payload, headers)

    def create_agreement_renewal(self, agency_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/agreement-renewals", payload, headers
        )

    def create_civil_rights_training(self, agency_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/agencies/{agency_id}/civil-rights-trainings", payload, headers
        )

    def list_agency_allocations_for_agency(
        self, agency_id, headers=None, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/agencies/{agency_id}/allocations", params, headers
        )

    def run_compliance_sweep(self, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/compliance-sweeps", payload or {}, headers)

    # ------------------------------------------------------------------
    # Commodities
    # ------------------------------------------------------------------
    def create_commodity(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/commodities", payload, headers)

    def list_commodities(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/commodities", params, headers)

    def get_commodity(self, commodity_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/commodities/{commodity_id}", None, headers)

    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------
    def create_warehouse(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/warehouses", payload, headers)

    def list_warehouses(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/warehouses", params, headers)

    def get_warehouse(self, warehouse_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/warehouses/{warehouse_id}", None, headers)

    def patch_warehouse(self, warehouse_id, payload, headers=None) -> requests.Response:
        return self._patch(f"{PREFIX}/warehouses/{warehouse_id}", payload, headers)

    # ------------------------------------------------------------------
    # Inventory lots and the monitor run
    # ------------------------------------------------------------------
    def create_inventory_lot(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/inventory-lots", payload, headers)

    def list_inventory_lots(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/inventory-lots", params, headers)

    def get_inventory_lot(self, inventory_lot_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/inventory-lots/{inventory_lot_id}", None, headers
        )

    def post_inventory_lot(self, inventory_lot_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inventory-lots/{inventory_lot_id}/post", payload or {}, headers
        )

    def run_inventory_monitor(self, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inventory-monitor-runs", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Allocation cycles
    # ------------------------------------------------------------------
    def create_allocation_cycle(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/allocation-cycles", payload, headers)

    def list_allocation_cycles(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/allocation-cycles", params, headers)

    def get_allocation_cycle(self, cycle_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/allocation-cycles/{cycle_id}", None, headers)

    def compute_allocations(self, cycle_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/allocation-cycles/{cycle_id}/compute-allocations",
            payload or {},
            headers,
        )

    def open_order_window(self, cycle_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/open-window", payload or {}, headers
        )

    def close_order_window(self, cycle_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/close-window", payload or {}, headers
        )

    def finalize_cycle(self, cycle_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/allocation-cycles/{cycle_id}/finalize", payload or {}, headers
        )

    def list_cycle_allocations(self, cycle_id, headers=None, params=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/allocation-cycles/{cycle_id}/allocations", params, headers
        )

    def get_admin_funds_report(self, cycle_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/allocation-cycles/{cycle_id}/admin-funds-report", None, headers
        )

    # ------------------------------------------------------------------
    # Entitlement rows
    # ------------------------------------------------------------------
    def list_agency_allocations(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/agency-allocations", params, headers)

    def get_agency_allocation(self, agency_allocation_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/agency-allocations/{agency_allocation_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Commodity orders and lines
    # ------------------------------------------------------------------
    def create_commodity_order(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/commodity-orders", payload, headers)

    def list_commodity_orders(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/commodity-orders", params, headers)

    def get_commodity_order(self, order_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/commodity-orders/{order_id}", None, headers)

    def add_order_line(self, order_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/commodity-orders/{order_id}/lines", payload, headers
        )

    def list_order_lines_of_order(self, order_id, headers=None, params=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/commodity-orders/{order_id}/lines", params, headers
        )

    def submit_order(self, order_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/commodity-orders/{order_id}/submit", payload or {}, headers
        )

    def return_order_for_revision(self, order_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/commodity-orders/{order_id}/return-for-revision",
            payload or {},
            headers,
        )

    def approve_order(self, order_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/commodity-orders/{order_id}/approve", payload or {}, headers
        )

    def cancel_order(self, order_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/commodity-orders/{order_id}/cancel", payload, headers
        )

    def list_order_lines(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/order-lines", params, headers)

    def get_order_line(self, order_line_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/order-lines/{order_line_id}", None, headers)

    # ------------------------------------------------------------------
    # Delivery appointments
    # ------------------------------------------------------------------
    def create_delivery_appointment(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/delivery-appointments", payload, headers)

    def list_delivery_appointments(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/delivery-appointments", params, headers)

    def get_delivery_appointment(self, appointment_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/delivery-appointments/{appointment_id}", None, headers
        )

    def confirm_delivery(self, appointment_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/delivery-appointments/{appointment_id}/confirm-delivery",
            payload or {},
            headers,
        )

    def cancel_delivery_appointment(self, appointment_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/delivery-appointments/{appointment_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Inventory transfers
    # ------------------------------------------------------------------
    def create_inventory_transfer(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/inventory-transfers", payload, headers)

    def list_inventory_transfers(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/inventory-transfers", params, headers)

    def get_inventory_transfer(self, transfer_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/inventory-transfers/{transfer_id}", None, headers
        )

    def accept_inventory_transfer(self, transfer_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inventory-transfers/{transfer_id}/accept", payload or {}, headers
        )

    def decline_inventory_transfer(self, transfer_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/inventory-transfers/{transfer_id}/decline", payload, headers
        )

    # ------------------------------------------------------------------
    # Recalls and recall actions
    # ------------------------------------------------------------------
    def create_recall(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/recalls", payload, headers)

    def list_recalls(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/recalls", params, headers)

    def get_recall(self, recall_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/recalls/{recall_id}", None, headers)

    def dispatch_recall_notices(self, recall_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/recalls/{recall_id}/dispatch-notices", payload or {}, headers
        )

    def expand_recall(self, recall_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/recalls/{recall_id}/expand", payload, headers)

    def close_recall(self, recall_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/recalls/{recall_id}/close", payload or {}, headers
        )

    def list_recall_actions_of_recall(self, recall_id, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/recalls/{recall_id}/actions", params, headers)

    def list_recall_actions(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/recall-actions", params, headers)

    def get_recall_action(self, recall_action_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/recall-actions/{recall_action_id}", None, headers
        )

    def acknowledge_recall_action(self, recall_action_id, headers=None, payload=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/recall-actions/{recall_action_id}/acknowledge",
            payload or {},
            headers,
        )

    def report_recall_disposition(self, recall_action_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/recall-actions/{recall_action_id}/report-disposition",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Household distributions
    # ------------------------------------------------------------------
    def create_household_distribution(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/household-distributions", payload, headers)

    def list_household_distributions(self, headers=None, params=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/household-distributions", params, headers)

    def get_household_distribution(self, distribution_id, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/household-distributions/{distribution_id}", None, headers
        )

    def void_household_distribution(self, distribution_id, payload, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/household-distributions/{distribution_id}/void",
            payload,
            headers,
        )


api_client = ApiClient()
