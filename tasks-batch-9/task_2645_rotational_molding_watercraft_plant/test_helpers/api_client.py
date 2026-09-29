"""HTTP client for the rotational-moulding watercraft plant API.

One method per endpoint in PRD.md section 4. Every method returns the raw
``requests.Response`` so tests can assert on the HTTP status as well as on the
body. The fixed response envelope described in PRD.md section 2.2 is unwrapped
in exactly one place: the ``read_*`` accessors near the bottom of this module
and the shared validators, never inside individual tests.
"""

from typing import Any

import requests
from prd_bench_local_runner.testing import GenericApiClient, get_success_data

from .types import (
    ClockState,
    CostSummary,
    FootprintSummary,
    FreightSummary,
)


class ApiClient(GenericApiClient):
    """Typed wrapper over the plant API described by PRD.md section 4."""

    def create_product_model(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a product model (PRD.md 3.1)."""
        return self._request("POST", "/product-models", payload, headers)

    def list_product_models(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List product models with optional filters and pagination."""
        return self._request("GET", "/product-models", params, headers)

    def get_product_model(self, product_model_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one product model, including its current version."""
        return self._request("GET", f"/product-models/{product_model_id}", None, headers)

    def update_product_model(self, product_model_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Patch mutable product model specification fields."""
        return self._request("PATCH", f"/product-models/{product_model_id}", payload, headers)

    def create_mold(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a mould bound to a product model."""
        return self._request("POST", "/molds", payload, headers)

    def list_molds(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List moulds with optional filters and pagination."""
        return self._request("GET", "/molds", params, headers)

    def get_mold(self, mold_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one mould."""
        return self._request("GET", f"/molds/{mold_id}", None, headers)

    def service_hold_mold(self, mold_id: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """Put a mould on service hold; body may carry hold_note."""
        return self._request("POST", f"/molds/{mold_id}/service-hold", payload, headers)

    def complete_service_mold(self, mold_id: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """Return a mould from service hold; body may carry service_note."""
        return self._request("POST", f"/molds/{mold_id}/complete-service", payload, headers)

    def retire_mold(self, mold_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Retire a mould permanently."""
        return self._request("POST", f"/molds/{mold_id}/retire", payload, headers)

    def create_oven_station(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create an oven station with its arm count and changeover buffer."""
        return self._request("POST", "/oven-stations", payload, headers)

    def list_oven_stations(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List oven stations with optional filters and pagination."""
        return self._request("GET", "/oven-stations", params, headers)

    def get_oven_station(self, oven_station_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one oven station."""
        return self._request("GET", f"/oven-stations/{oven_station_id}", None, headers)

    def mark_down_oven_station(self, oven_station_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Take an oven station out of service."""
        return self._request("POST", f"/oven-stations/{oven_station_id}/mark-down", payload, headers)

    def restore_oven_station(self, oven_station_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Return an oven station to service."""
        return self._request("POST", f"/oven-stations/{oven_station_id}/restore", None, headers)

    def create_cooling_bay(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a cooling bay with its concurrent slot capacity."""
        return self._request("POST", "/cooling-bays", payload, headers)

    def list_cooling_bays(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List cooling bays with optional filters and pagination."""
        return self._request("GET", "/cooling-bays", params, headers)

    def get_cooling_bay(self, cooling_bay_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one cooling bay."""
        return self._request("GET", f"/cooling-bays/{cooling_bay_id}", None, headers)

    def mark_down_cooling_bay(self, cooling_bay_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Take a cooling bay out of service."""
        return self._request("POST", f"/cooling-bays/{cooling_bay_id}/mark-down", payload, headers)

    def restore_cooling_bay(self, cooling_bay_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Return a cooling bay to service."""
        return self._request("POST", f"/cooling-bays/{cooling_bay_id}/restore", None, headers)

    def create_technician(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a technician; role_code fixes which header role this row may act as."""
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List technicians with optional filters and pagination."""
        return self._request("GET", "/technicians", params, headers)

    def get_technician(self, technician_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one technician."""
        return self._request("GET", f"/technicians/{technician_id}", None, headers)

    def suspend_technician(self, technician_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Suspend a technician."""
        return self._request("POST", f"/technicians/{technician_id}/suspend", payload, headers)

    def reinstate_technician(self, technician_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Reinstate a suspended technician."""
        return self._request("POST", f"/technicians/{technician_id}/reinstate", None, headers)

    def create_customer(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a customer."""
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List customers with optional filters and pagination."""
        return self._request("GET", "/customers", params, headers)

    def get_customer(self, customer_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one customer."""
        return self._request("GET", f"/customers/{customer_id}", None, headers)

    def acknowledge_storage_guidance(self, customer_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Record a customer storage-guidance acknowledgement at a given instant."""
        return self._request("POST", f"/customers/{customer_id}/acknowledge-storage-guidance", payload, headers)

    def suspend_customer(self, customer_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Suspend a customer."""
        return self._request("POST", f"/customers/{customer_id}/suspend", payload, headers)

    def reinstate_customer(self, customer_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Reinstate a suspended customer."""
        return self._request("POST", f"/customers/{customer_id}/reinstate", None, headers)

    def create_warehouse(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a warehouse with its zones and posture thresholds."""
        return self._request("POST", "/warehouses", payload, headers)

    def list_warehouses(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List warehouses with optional posture filter and pagination."""
        return self._request("GET", "/warehouses", params, headers)

    def get_warehouse(self, warehouse_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one warehouse, including its current version."""
        return self._request("GET", f"/warehouses/{warehouse_id}", None, headers)

    def get_warehouse_footprint_summary(self, warehouse_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read the computed footprint projection for a warehouse."""
        return self._request("GET", f"/warehouses/{warehouse_id}/footprint-summary", None, headers)

    def create_demand_forecast_bucket(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a demand forecast bucket for a model and season window."""
        return self._request("POST", "/demand-forecast-buckets", payload, headers)

    def list_demand_forecast_buckets(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List demand forecast buckets with optional filters and pagination."""
        return self._request("GET", "/demand-forecast-buckets", params, headers)

    def get_demand_forecast_bucket(self, demand_forecast_bucket_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one demand forecast bucket."""
        return self._request("GET", f"/demand-forecast-buckets/{demand_forecast_bucket_id}", None, headers)

    def create_resin_lot(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a received resin lot."""
        return self._request("POST", "/resin-lots", payload, headers)

    def list_resin_lots(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List resin lots with optional filters and pagination."""
        return self._request("GET", "/resin-lots", params, headers)

    def get_resin_lot(self, resin_lot_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one resin lot, including its ledger buckets and version."""
        return self._request("GET", f"/resin-lots/{resin_lot_id}", None, headers)

    def quarantine_resin_lot(self, resin_lot_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Quarantine a resin lot."""
        return self._request("POST", f"/resin-lots/{resin_lot_id}/quarantine", payload, headers)

    def release_resin_lot_quarantine(self, resin_lot_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Release a resin lot from quarantine."""
        return self._request("POST", f"/resin-lots/{resin_lot_id}/release-quarantine", payload, headers)

    def create_resin_charge(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Reserve resin from a lot against a scheduled cycle."""
        return self._request("POST", "/resin-charges", payload, headers)

    def list_resin_charges(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List resin charges with optional filters and pagination."""
        return self._request("GET", "/resin-charges", params, headers)

    def get_resin_charge(self, resin_charge_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one resin charge."""
        return self._request("GET", f"/resin-charges/{resin_charge_id}", None, headers)

    def release_resin_charge(self, resin_charge_id: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """Release a reserved resin charge; body may carry release_reason."""
        return self._request("POST", f"/resin-charges/{resin_charge_id}/release", payload, headers)

    def create_production_order(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a production order for a model and target warehouse."""
        return self._request("POST", "/production-orders", payload, headers)

    def list_production_orders(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List production orders with optional filters and pagination."""
        return self._request("GET", "/production-orders", params, headers)

    def get_production_order(self, production_order_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one production order, including its current version."""
        return self._request("GET", f"/production-orders/{production_order_id}", None, headers)

    def release_production_order(self, production_order_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Release a draft production order so cycles may be scheduled."""
        return self._request("POST", f"/production-orders/{production_order_id}/release", None, headers)

    def cancel_production_order(self, production_order_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Cancel a production order."""
        return self._request("POST", f"/production-orders/{production_order_id}/cancel", payload, headers)

    def get_production_order_cost_summary(self, production_order_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read the computed cost projection for a production order."""
        return self._request("GET", f"/production-orders/{production_order_id}/cost-summary", None, headers)

    def create_molding_cycle(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Schedule a moulding cycle on an oven arm and cooling bay."""
        return self._request("POST", "/molding-cycles", payload, headers)

    def list_molding_cycles(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List moulding cycles with optional filters and pagination."""
        return self._request("GET", "/molding-cycles", params, headers)

    def get_molding_cycle(self, molding_cycle_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one moulding cycle."""
        return self._request("GET", f"/molding-cycles/{molding_cycle_id}", None, headers)

    def start_oven(self, molding_cycle_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Start the oven leg of a scheduled cycle."""
        return self._request("POST", f"/molding-cycles/{molding_cycle_id}/start-oven", payload, headers)

    def enter_cooling(self, molding_cycle_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """End the oven leg and move the cycle into cooling."""
        return self._request("POST", f"/molding-cycles/{molding_cycle_id}/enter-cooling", payload, headers)

    def demold(self, molding_cycle_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """End cooling, demould the cycle and mint its finished units."""
        return self._request("POST", f"/molding-cycles/{molding_cycle_id}/demold", payload, headers)

    def abort_molding_cycle(self, molding_cycle_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Abort a moulding cycle."""
        return self._request("POST", f"/molding-cycles/{molding_cycle_id}/abort", payload, headers)

    def list_finished_units(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List finished units with optional filters and pagination."""
        return self._request("GET", "/finished-units", params, headers)

    def get_finished_unit(self, finished_unit_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one finished unit."""
        return self._request("GET", f"/finished-units/{finished_unit_id}", None, headers)

    def trim_finished_unit(self, finished_unit_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Trim a demoulded hull."""
        return self._request("POST", f"/finished-units/{finished_unit_id}/trim", payload, headers)

    def outfit_finished_unit(self, finished_unit_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Outfit a trimmed hull with its hardware kit."""
        return self._request("POST", f"/finished-units/{finished_unit_id}/outfit", payload, headers)

    def inspect_finished_unit(self, finished_unit_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Inspect an outfitted hull and record its verdict."""
        return self._request("POST", f"/finished-units/{finished_unit_id}/inspect", payload, headers)

    def scrap_finished_unit(self, finished_unit_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Scrap a finished unit."""
        return self._request("POST", f"/finished-units/{finished_unit_id}/scrap", payload, headers)

    def store_finished_unit(self, finished_unit_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Store a sellable unit into its target warehouse."""
        return self._request("POST", f"/finished-units/{finished_unit_id}/store", payload, headers)

    def release_storage(self, finished_unit_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Release a stored unit back out of warehouse storage."""
        return self._request("POST", f"/finished-units/{finished_unit_id}/release-storage", payload, headers)

    def create_shipment(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Create a shipment trailer booking."""
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List shipments with optional filters and pagination."""
        return self._request("GET", "/shipments", params, headers)

    def get_shipment(self, shipment_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one shipment, including its current version."""
        return self._request("GET", f"/shipments/{shipment_id}", None, headers)

    def seal_shipment(self, shipment_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Seal a shipment and quote its freight."""
        return self._request("POST", f"/shipments/{shipment_id}/seal", None, headers)

    def unseal_shipment(self, shipment_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Unseal a sealed shipment."""
        return self._request("POST", f"/shipments/{shipment_id}/unseal", payload, headers)

    def depart_shipment(self, shipment_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Mark a sealed shipment departed."""
        return self._request("POST", f"/shipments/{shipment_id}/depart", payload, headers)

    def deliver_shipment(self, shipment_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Mark a departed shipment delivered and bill its freight."""
        return self._request("POST", f"/shipments/{shipment_id}/deliver", payload, headers)

    def cancel_shipment(self, shipment_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Cancel a shipment."""
        return self._request("POST", f"/shipments/{shipment_id}/cancel", payload, headers)

    def get_shipment_freight_summary(self, shipment_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read the computed freight projection for a shipment."""
        return self._request("GET", f"/shipments/{shipment_id}/freight-summary", None, headers)

    def create_shipment_line(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Add a stored unit to an open shipment."""
        return self._request("POST", "/shipment-lines", payload, headers)

    def list_shipment_lines(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List shipment lines with optional filters and pagination."""
        return self._request("GET", "/shipment-lines", params, headers)

    def get_shipment_line(self, shipment_line_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one shipment line."""
        return self._request("GET", f"/shipment-lines/{shipment_line_id}", None, headers)

    def remove_shipment_line(self, shipment_line_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Remove a line from an open shipment."""
        return self._request("POST", f"/shipment-lines/{shipment_line_id}/remove", payload, headers)

    def create_warranty_claim(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Submit a warranty claim against a delivered unit."""
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        """List warranty claims with optional filters and pagination."""
        return self._request("GET", "/warranty-claims", params, headers)

    def get_warranty_claim(self, warranty_claim_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Read one warranty claim."""
        return self._request("GET", f"/warranty-claims/{warranty_claim_id}", None, headers)

    def start_claim_review(self, warranty_claim_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Move a submitted claim into review."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/start-review", None, headers)

    def submit_storage_review(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Record the storage review outcome for a claim under review."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/storage-review", payload, headers)

    def waive_storage_finding(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Waive a violated storage finding on a claim."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/waive-storage-finding", payload, headers)

    def approve_warranty_claim(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Approve a claim and draw its payout from the model warranty reserve."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/approve", payload, headers)

    def deny_warranty_claim(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Deny a claim under review."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/deny", payload, headers)

    def return_claim_to_queue(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Return a claim under review to the submitted queue."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/return-to-queue", payload, headers)

    def void_warranty_claim(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Void an approved claim and restore its payout to the reserve."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/void", payload, headers)

    def withdraw_warranty_claim(self, warranty_claim_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Withdraw a claim on the customer's behalf."""
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/withdraw", payload, headers)

    def set_clock(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        """Set the logical clock that drives every server-stamped instant."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers: dict[str, str] | None = None) -> requests.Response:
        """Read the logical clock's current instant."""
        return self._request("GET", "/_clock/current_utc", None, headers)
    # ------------------------------------------------------------------
    # Envelope unwrapping and typed projection accessors.
    #
    # PRD.md section 2.2 fixes the success envelope as
    # {"meta": {...}, "response_type": "object" | "array", "data": {...}}.
    # The helpers below are the only place in the suite that reaches into
    # "data" directly; everything else either goes through the shared
    # validators or through these accessors.
    # ------------------------------------------------------------------

    def read_data(self, response: requests.Response) -> dict[str, Any]:
        """Unwrap a success envelope and return its ``data`` object."""
        return get_success_data(response)

    def read_entity(
        self,
        getter_name: str,
        entity_id: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Call a ``get_*`` method by name and return the unwrapped entity."""
        return get_success_data(getattr(self, getter_name)(entity_id, headers))

    def read_version(
        self,
        getter_name: str,
        entity_id: str,
        headers: dict[str, str] | None = None,
    ) -> int:
        """Re-read an entity and return its current ``version``.

        Every write guarded by an ``expected_<parent>_version`` field
        (PRD.md section 2.6) must be handed a freshly read version, never one
        cached from an earlier response.
        """
        return self.read_entity(getter_name, entity_id, headers)["version"]

    def read_footprint_summary(
        self,
        warehouse_id: str,
        headers: dict[str, str] | None = None,
    ) -> FootprintSummary:
        """Return the unwrapped warehouse footprint projection."""
        return get_success_data(
            self.get_warehouse_footprint_summary(warehouse_id, headers)
        )

    def read_cost_summary(
        self,
        production_order_id: str,
        headers: dict[str, str] | None = None,
    ) -> CostSummary:
        """Return the unwrapped production order cost projection."""
        return get_success_data(
            self.get_production_order_cost_summary(production_order_id, headers)
        )

    def read_freight_summary(
        self,
        shipment_id: str,
        headers: dict[str, str] | None = None,
    ) -> FreightSummary:
        """Return the unwrapped shipment freight projection."""
        return get_success_data(self.get_shipment_freight_summary(shipment_id, headers))

    def read_clock(self, headers: dict[str, str] | None = None) -> ClockState:
        """Return the unwrapped logical clock state (PRD.md section 2.5)."""
        return get_success_data(self.get_clock(headers))

    def read_current_utc(self, headers: dict[str, str] | None = None) -> str:
        """Return only the logical clock's current instant as an ISO8601 string."""
        return self.read_clock(headers)["current_utc"]

    def set_current_utc(
        self,
        instant: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Move the logical clock to ``instant`` and return the unwrapped result.

        The result carries the clock-driven resin expiry cascade counters that
        PRD.md section 2.5 declares, so callers can assert on them directly.
        """
        return get_success_data(self.set_clock({"current_utc": instant}, headers))


# Shared client instance; the base URL comes from API_BASE_URL.
api_client = ApiClient()
