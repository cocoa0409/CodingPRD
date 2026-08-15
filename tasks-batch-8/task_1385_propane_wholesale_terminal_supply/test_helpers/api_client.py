"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_epoch(self, headers):
        return self._request("POST", "/ops/run_epoch", {}, headers)

    # --- Terminal ---
    def create_terminal(self, payload, headers):
        return self._request("POST", "/terminals", payload, headers)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/terminals/{terminal_id}", headers=headers)

    def get_inventory_summary(self, terminal_id, headers):
        return self._request("GET", f"/terminals/{terminal_id}/inventory-summary",
                             headers=headers)

    # --- SupplyContract ---
    def create_supply_contract(self, payload, headers):
        return self._request("POST", "/supply-contracts", payload, headers)

    def get_supply_contract(self, contract_id, headers):
        return self._request("GET", f"/supply-contracts/{contract_id}",
                             headers=headers)

    def list_supply_contracts(self, headers, params=None):
        return self._request("GET", "/supply-contracts", headers=headers,
                             params=params)

    def activate_supply_contract(self, contract_id, headers):
        return self._request("POST", f"/supply-contracts/{contract_id}/activate",
                             {}, headers)

    def cancel_supply_contract(self, contract_id, headers):
        return self._request("POST", f"/supply-contracts/{contract_id}/cancel",
                             {}, headers)

    # --- RailShipment ---
    def create_rail_shipment(self, payload, headers):
        return self._request("POST", "/rail-shipments", payload, headers)

    def get_rail_shipment(self, shipment_id, headers):
        return self._request("GET", f"/rail-shipments/{shipment_id}",
                             headers=headers)

    def list_rail_shipments(self, headers, params=None):
        return self._request("GET", "/rail-shipments", headers=headers,
                             params=params)

    def transition_rail_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/rail-shipments/{shipment_id}/transition",
                             payload, headers)

    # --- Dealer ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/dealers", headers=headers, params=params)

    def update_dealer(self, dealer_id, payload, headers):
        return self._request("PATCH", f"/dealers/{dealer_id}", payload, headers)

    # --- DealerContract ---
    def create_dealer_contract(self, payload, headers):
        return self._request("POST", "/dealer-contracts", payload, headers)

    def get_dealer_contract(self, contract_id, headers):
        return self._request("GET", f"/dealer-contracts/{contract_id}",
                             headers=headers)

    def list_dealer_contracts(self, headers, params=None):
        return self._request("GET", "/dealer-contracts", headers=headers,
                             params=params)

    def activate_dealer_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/dealer-contracts/{contract_id}/activate",
                             payload, headers)

    def cancel_dealer_contract(self, contract_id, headers):
        return self._request("POST", f"/dealer-contracts/{contract_id}/cancel",
                             {}, headers)

    # --- PriceIndexPublication ---
    def create_price_index_publication(self, payload, headers):
        return self._request("POST", "/price-index-publications", payload, headers)

    def get_price_index_publication(self, publication_id, headers):
        return self._request("GET", f"/price-index-publications/{publication_id}",
                             headers=headers)

    def list_price_index_publications(self, headers, params=None):
        return self._request("GET", "/price-index-publications", headers=headers,
                             params=params)

    def resolve_price_index(self, headers, params=None):
        return self._request("GET", "/price-index-publications/resolve",
                             headers=headers, params=params)

    # --- FreightZone ---
    def create_freight_zone(self, payload, headers):
        return self._request("POST", "/freight-zones", payload, headers)

    def get_freight_zone(self, zone_id, headers):
        return self._request("GET", f"/freight-zones/{zone_id}", headers=headers)

    def list_freight_zones(self, headers, params=None):
        return self._request("GET", "/freight-zones", headers=headers,
                             params=params)

    # --- TransportTruck ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    def transition_truck(self, truck_id, payload, headers):
        return self._request("POST", f"/trucks/{truck_id}/transition",
                             payload, headers)

    # --- DeliveryOrder ---
    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def get_delivery_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}",
                             headers=headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers,
                             params=params)

    def schedule_delivery_order(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/schedule",
                             payload, headers)

    def unschedule_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/unschedule",
                             {}, headers)

    def load_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/load",
                             {}, headers)

    def deliver_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/deliver",
                             {}, headers)

    def cancel_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/cancel",
                             {}, headers)

    # --- ColdSnapEvent ---
    def create_cold_snap_event(self, payload, headers):
        return self._request("POST", "/cold-snap-events", payload, headers)

    def get_cold_snap_event(self, event_id, headers):
        return self._request("GET", f"/cold-snap-events/{event_id}",
                             headers=headers)

    def list_cold_snap_events(self, headers, params=None):
        return self._request("GET", "/cold-snap-events", headers=headers,
                             params=params)

    def activate_cold_snap(self, event_id, headers):
        return self._request("POST", f"/cold-snap-events/{event_id}/activate",
                             {}, headers)

    def lift_cold_snap(self, event_id, headers):
        return self._request("POST", f"/cold-snap-events/{event_id}/lift",
                             {}, headers)

    # --- AllocationRun ---
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/allocation-runs", payload, headers)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/allocation-runs/{run_id}", headers=headers)

    def list_allocation_runs(self, headers, params=None):
        return self._request("GET", "/allocation-runs", headers=headers,
                             params=params)

    def compute_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/compute",
                             {}, headers)

    def ratify_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/ratify",
                             {}, headers)

    # --- DealerPayment ---
    def create_dealer_payment(self, payload, headers):
        return self._request("POST", "/dealer-payments", payload, headers)

    def get_dealer_payment(self, payment_id, headers):
        return self._request("GET", f"/dealer-payments/{payment_id}",
                             headers=headers)

    def list_dealer_payments(self, headers, params=None):
        return self._request("GET", "/dealer-payments", headers=headers,
                             params=params)

    def return_dealer_payment(self, payment_id, headers):
        return self._request("POST", f"/dealer-payments/{payment_id}/return",
                             {}, headers)


api_client = ApiClient()
