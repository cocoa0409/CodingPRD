"""
Endpoint client for the Salt Deicing Operations API.

One method per row of the PRD §4 endpoint table. Every business path is mounted
under the `/salt` prefix; the logical-clock hook of PRD §2.5 is the single
exception. Methods return the raw requests.Response so tests assert status codes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

CLOCK = "/_clock/set_current_utc"
MINES = "/salt/mines"
PANELS = "/salt/panels"
INSPECTIONS = "/salt/ground-control-inspections"
RUNS = "/salt/production-runs"
BATCHES = "/salt/treatment-batches"
DEPOTS = "/salt/depots"
LOTS = "/salt/stockpile-lots"
SHIPMENTS = "/salt/shipments"
FORECASTS = "/salt/season-forecasts"
CONTRACTS = "/salt/bid-contracts"
ORDERS = "/salt/delivery-orders"
ALLOCATIONS = "/salt/allocations"


class SaltApiClient(GenericApiClient):
    """Typed wrapper over the 68 endpoints of PRD §4."""

    # ─── Logical clock (PRD §2.5) ─────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", CLOCK, {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", CLOCK, payload, headers)

    # ─── Mines (PRD §3.1) ─────────────────────────────

    def create_mine(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", MINES, payload, headers)

    def get_mine(self, mine_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{MINES}/{mine_id}", None, headers)

    def list_mines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", MINES, params, headers)

    def get_hoist_capacity(self, mine_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{MINES}/{mine_id}/hoist-capacity", None, headers)

    def set_hoist_status(
        self, mine_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{MINES}/{mine_id}/hoist-status", payload, headers)

    def compliance_action(
        self, mine_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{MINES}/{mine_id}/compliance-action", payload, headers
        )

    # ─── Panels (PRD §3.2) ────────────────────────────

    def create_panel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PANELS, payload, headers)

    def get_panel(self, panel_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PANELS}/{panel_id}", None, headers)

    def list_panels(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PANELS, params, headers)

    def develop_panel(
        self, panel_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{PANELS}/{panel_id}/develop", payload, headers)

    def start_production(
        self, panel_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PANELS}/{panel_id}/start-production", payload, headers
        )

    def suspend_panel(
        self, panel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{PANELS}/{panel_id}/suspend", payload, headers)

    def remediate_defect(
        self, panel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PANELS}/{panel_id}/remediate-defect", payload, headers
        )

    def deplete_panel(
        self, panel_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{PANELS}/{panel_id}/deplete", payload, headers)

    def abandon_panel(
        self, panel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{PANELS}/{panel_id}/abandon", payload, headers)

    # ─── Ground-control inspections (PRD §3.3) ────────

    def create_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", INSPECTIONS, payload, headers)

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{INSPECTIONS}/{inspection_id}", None, headers)

    def list_inspections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", INSPECTIONS, params, headers)

    # ─── Production runs (PRD §3.4) ───────────────────

    def create_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", RUNS, payload, headers)

    def get_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{RUNS}/{run_id}", None, headers)

    def list_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", RUNS, params, headers)

    def hoist_run(self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{RUNS}/{run_id}/hoist", payload, headers)

    def close_run(
        self, run_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{RUNS}/{run_id}/close", payload, headers)

    def reinstate_run(
        self, run_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{RUNS}/{run_id}/reinstate", payload, headers)

    # ─── Treatment batches (PRD §3.5) ─────────────────

    def create_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", BATCHES, payload, headers)

    def get_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BATCHES}/{batch_id}", None, headers)

    def list_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", BATCHES, params, headers)

    def qc_decision(
        self, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BATCHES}/{batch_id}/qc-decision", payload, headers)

    # ─── Depots (PRD §3.6) ────────────────────────────

    def create_depot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", DEPOTS, payload, headers)

    def get_depot(self, depot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{DEPOTS}/{depot_id}", None, headers)

    def list_depots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", DEPOTS, params, headers)

    def get_storage_posture(self, depot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{DEPOTS}/{depot_id}/storage-posture", None, headers)

    def patch_depot(
        self, depot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"{DEPOTS}/{depot_id}", payload, headers)

    def set_posture(
        self, depot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{DEPOTS}/{depot_id}/posture", payload, headers)

    # ─── Stockpile lots (PRD §3.6) ────────────────────

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{LOTS}/{lot_id}", None, headers)

    def list_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", LOTS, params, headers)

    def set_quarantine_state(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{LOTS}/{lot_id}/quarantine-state", payload, headers
        )

    # ─── Shipments (PRD §3.7) ─────────────────────────

    def create_shipment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", SHIPMENTS, payload, headers)

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{SHIPMENTS}/{shipment_id}", None, headers)

    def list_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", SHIPMENTS, params, headers)

    def load_shipment(
        self, shipment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{SHIPMENTS}/{shipment_id}/load", payload, headers)

    def receive_shipment(
        self, shipment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{SHIPMENTS}/{shipment_id}/receive", payload, headers
        )

    def cancel_shipment(
        self, shipment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{SHIPMENTS}/{shipment_id}/cancel", payload, headers)

    # ─── Season forecasts (PRD §3.8) ──────────────────

    def create_forecast(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", FORECASTS, payload, headers)

    def get_forecast(self, forecast_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{FORECASTS}/{forecast_id}", None, headers)

    def list_forecasts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", FORECASTS, params, headers)

    def patch_forecast(
        self, forecast_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"{FORECASTS}/{forecast_id}", payload, headers)

    # ─── Bid contracts (PRD §3.8) ─────────────────────

    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", CONTRACTS, payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{CONTRACTS}/{contract_id}", None, headers)

    def list_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", CONTRACTS, params, headers)

    def get_contract_ledger(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{CONTRACTS}/{contract_id}/ledger", None, headers)

    def submit_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{CONTRACTS}/{contract_id}/submit", payload, headers)

    def decide_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{CONTRACTS}/{contract_id}/decision", payload, headers
        )

    def activate_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{CONTRACTS}/{contract_id}/activate", payload, headers
        )

    def close_season(
        self, contract_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{CONTRACTS}/{contract_id}/close-season", payload, headers
        )

    # ─── Delivery orders (PRD §3.9) ───────────────────

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", ORDERS, payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ORDERS}/{order_id}", None, headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", ORDERS, params, headers)

    def allocate_order(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{ORDERS}/{order_id}/allocate", payload, headers)

    def release_order_allocations(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{ORDERS}/{order_id}/release-allocations", payload, headers
        )

    def deliver_order(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request("POST", f"{ORDERS}/{order_id}/deliver", payload, headers)

    def waive_penalty(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{ORDERS}/{order_id}/waive-penalty", payload, headers
        )

    # ─── Allocations (PRD §3.9) ───────────────────────

    def create_allocation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", ALLOCATIONS, payload, headers)

    def get_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ALLOCATIONS}/{allocation_id}", None, headers)

    def list_allocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", ALLOCATIONS, params, headers)

    def release_allocation(
        self, allocation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{ALLOCATIONS}/{allocation_id}/release", payload, headers
        )
