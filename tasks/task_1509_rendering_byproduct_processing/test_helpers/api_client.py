"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Plants ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/rendering/plants", payload, headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/rendering/plants", headers=headers, params=params)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/rendering/plants/{plant_id}", headers=headers)

    def decommission_plant(self, plant_id, headers):
        return self._request(
            "POST", f"/rendering/plants/{plant_id}/decommission", {}, headers
        )

    def advance_period(self, plant_id, headers):
        return self._request(
            "POST", f"/rendering/plants/{plant_id}/advance-period", {}, headers
        )

    # --- Compliance permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/rendering/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/rendering/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/rendering/permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/rendering/permits/{permit_id}/submit", {}, headers
        )

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/rendering/permits/{permit_id}/issue", {}, headers)

    def suspend_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/rendering/permits/{permit_id}/suspend", {}, headers
        )

    def reinstate_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/rendering/permits/{permit_id}/reinstate", {}, headers
        )

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/rendering/permits/{permit_id}/revoke", {}, headers)

    # --- Odor events ---
    def create_odor_event(self, payload, headers):
        return self._request("POST", "/rendering/odor-events", payload, headers)

    def list_odor_events(self, headers, params=None):
        return self._request(
            "GET", "/rendering/odor-events", headers=headers, params=params
        )

    def get_odor_event(self, event_id, headers):
        return self._request(
            "GET", f"/rendering/odor-events/{event_id}", headers=headers
        )

    def confirm_odor_event(self, event_id, headers):
        return self._request(
            "POST", f"/rendering/odor-events/{event_id}/confirm", {}, headers
        )

    def dismiss_odor_event(self, event_id, headers):
        return self._request(
            "POST", f"/rendering/odor-events/{event_id}/dismiss", {}, headers
        )

    # --- Suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/rendering/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request(
            "GET", "/rendering/suppliers", headers=headers, params=params
        )

    def get_supplier(self, supplier_id, headers):
        return self._request(
            "GET", f"/rendering/suppliers/{supplier_id}", headers=headers
        )

    def reinstate_supplier(self, supplier_id, headers):
        return self._request(
            "POST", f"/rendering/suppliers/{supplier_id}/reinstate", {}, headers
        )

    def terminate_supplier(self, supplier_id, headers):
        return self._request(
            "POST", f"/rendering/suppliers/{supplier_id}/terminate", {}, headers
        )

    # --- Supplier agreements ---
    def create_supplier_agreement(self, payload, headers):
        return self._request("POST", "/rendering/supplier-agreements", payload, headers)

    def list_supplier_agreements(self, headers, params=None):
        return self._request(
            "GET", "/rendering/supplier-agreements", headers=headers, params=params
        )

    def get_supplier_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/rendering/supplier-agreements/{agreement_id}", headers=headers
        )

    def submit_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/rendering/supplier-agreements/{agreement_id}/submit", {}, headers
        )

    def approve_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/rendering/supplier-agreements/{agreement_id}/approve", {}, headers
        )

    def return_agreement_to_draft(self, agreement_id, headers):
        return self._request(
            "POST",
            f"/rendering/supplier-agreements/{agreement_id}/return-to-draft",
            {},
            headers,
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/rendering/supplier-agreements/{agreement_id}/suspend", {}, headers
        )

    def reinstate_agreement(self, agreement_id, headers):
        return self._request(
            "POST",
            f"/rendering/supplier-agreements/{agreement_id}/reinstate",
            {},
            headers,
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST",
            f"/rendering/supplier-agreements/{agreement_id}/terminate",
            {},
            headers,
        )

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rendering/supplier-agreements/{agreement_id}/amend", payload, headers
        )

    # --- Vehicles / wash tickets ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/rendering/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/rendering/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/rendering/vehicles/{vehicle_id}", headers=headers)

    def create_wash_ticket(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/rendering/vehicles/{vehicle_id}/wash-tickets", payload, headers
        )

    def list_wash_tickets(self, headers, params=None):
        return self._request(
            "GET", "/rendering/wash-tickets", headers=headers, params=params
        )

    def get_wash_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/rendering/wash-tickets/{ticket_id}", headers=headers
        )

    def quarantine_vehicle(self, vehicle_id, headers):
        return self._request(
            "POST", f"/rendering/vehicles/{vehicle_id}/quarantine", {}, headers
        )

    # --- Collection routes ---
    def create_collection_route(self, payload, headers):
        return self._request("POST", "/rendering/collection-routes", payload, headers)

    def list_collection_routes(self, headers, params=None):
        return self._request(
            "GET", "/rendering/collection-routes", headers=headers, params=params
        )

    def get_collection_route(self, route_id, headers):
        return self._request(
            "GET", f"/rendering/collection-routes/{route_id}", headers=headers
        )

    def dispatch_route(self, route_id, headers):
        return self._request(
            "POST", f"/rendering/collection-routes/{route_id}/dispatch", {}, headers
        )

    def complete_route(self, route_id, headers):
        return self._request(
            "POST", f"/rendering/collection-routes/{route_id}/complete", {}, headers
        )

    def cancel_route(self, route_id, headers):
        return self._request(
            "POST", f"/rendering/collection-routes/{route_id}/cancel", {}, headers
        )

    # --- Route stops ---
    def create_route_stop(self, payload, headers):
        return self._request("POST", "/rendering/route-stops", payload, headers)

    def list_route_stops(self, headers, params=None):
        return self._request(
            "GET", "/rendering/route-stops", headers=headers, params=params
        )

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/rendering/route-stops/{stop_id}", headers=headers)

    def arrive_stop(self, stop_id, headers):
        return self._request(
            "POST", f"/rendering/route-stops/{stop_id}/arrive", {}, headers
        )

    def collect_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/rendering/route-stops/{stop_id}/collect", payload, headers
        )

    def reject_stop_at_site(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/rendering/route-stops/{stop_id}/reject-at-site", payload, headers
        )

    def miss_stop(self, stop_id, headers):
        return self._request("POST", f"/rendering/route-stops/{stop_id}/miss", {}, headers)

    def deliver_stop(self, stop_id, headers):
        return self._request(
            "POST", f"/rendering/route-stops/{stop_id}/deliver", {}, headers
        )

    def void_stop(self, stop_id, headers):
        return self._request("POST", f"/rendering/route-stops/{stop_id}/void", {}, headers)

    # --- Inbound batches ---
    def create_inbound_batch(self, payload, headers):
        return self._request("POST", "/rendering/inbound-batches", payload, headers)

    def list_inbound_batches(self, headers, params=None):
        return self._request(
            "GET", "/rendering/inbound-batches", headers=headers, params=params
        )

    def get_inbound_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/rendering/inbound-batches/{batch_id}", headers=headers
        )

    def screen_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/rendering/inbound-batches/{batch_id}/screen", payload, headers
        )

    def quarantine_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/rendering/inbound-batches/{batch_id}/quarantine", {}, headers
        )

    def adjudicate_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/rendering/inbound-batches/{batch_id}/adjudicate", payload, headers
        )

    # --- Cook runs ---
    def create_cook_run(self, payload, headers):
        return self._request("POST", "/rendering/cook-runs", payload, headers)

    def list_cook_runs(self, headers, params=None):
        return self._request(
            "GET", "/rendering/cook-runs", headers=headers, params=params
        )

    def get_cook_run(self, run_id, headers):
        return self._request("GET", f"/rendering/cook-runs/{run_id}", headers=headers)

    def start_cook_run(self, run_id, headers):
        return self._request("POST", f"/rendering/cook-runs/{run_id}/start", {}, headers)

    def advance_cook_run(self, run_id, headers):
        return self._request(
            "POST", f"/rendering/cook-runs/{run_id}/advance", {}, headers
        )

    def fail_cook_run(self, run_id, payload, headers):
        return self._request("POST", f"/rendering/cook-runs/{run_id}/fail", payload, headers)

    def restage_cook_run(self, run_id, headers):
        return self._request(
            "POST", f"/rendering/cook-runs/{run_id}/restage", {}, headers
        )

    def complete_cook_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/rendering/cook-runs/{run_id}/complete", payload, headers
        )

    def cancel_cook_run(self, run_id, headers):
        return self._request("POST", f"/rendering/cook-runs/{run_id}/cancel", {}, headers)

    # --- Product lots ---
    def list_product_lots(self, headers, params=None):
        return self._request(
            "GET", "/rendering/product-lots", headers=headers, params=params
        )

    def get_product_lot(self, lot_id, headers):
        return self._request("GET", f"/rendering/product-lots/{lot_id}", headers=headers)

    def grade_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/rendering/product-lots/{lot_id}/grade", payload, headers
        )

    def release_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/rendering/product-lots/{lot_id}/release", {}, headers
        )

    def downgrade_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/rendering/product-lots/{lot_id}/downgrade", {}, headers
        )

    def regrade_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/rendering/product-lots/{lot_id}/regrade", payload, headers
        )

    def reject_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/rendering/product-lots/{lot_id}/reject", {}, headers
        )

    # --- Customer contracts ---
    def create_customer_contract(self, payload, headers):
        return self._request("POST", "/rendering/customer-contracts", payload, headers)

    def list_customer_contracts(self, headers, params=None):
        return self._request(
            "GET", "/rendering/customer-contracts", headers=headers, params=params
        )

    def get_customer_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/rendering/customer-contracts/{contract_id}", headers=headers
        )

    def submit_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rendering/customer-contracts/{contract_id}/submit", {}, headers
        )

    def approve_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rendering/customer-contracts/{contract_id}/approve", {}, headers
        )

    def return_contract_to_draft(self, contract_id, headers):
        return self._request(
            "POST",
            f"/rendering/customer-contracts/{contract_id}/return-to-draft",
            {},
            headers,
        )

    def suspend_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rendering/customer-contracts/{contract_id}/suspend", {}, headers
        )

    def reinstate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rendering/customer-contracts/{contract_id}/reinstate", {}, headers
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rendering/customer-contracts/{contract_id}/terminate", {}, headers
        )

    # --- Sales orders ---
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/rendering/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request(
            "GET", "/rendering/sales-orders", headers=headers, params=params
        )

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/rendering/sales-orders/{order_id}", headers=headers)

    def price_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/rendering/sales-orders/{order_id}/price", payload, headers
        )

    def confirm_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/rendering/sales-orders/{order_id}/confirm", payload, headers
        )

    def deallocate_order(self, order_id, headers):
        return self._request(
            "POST", f"/rendering/sales-orders/{order_id}/deallocate", {}, headers
        )

    def ship_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/rendering/sales-orders/{order_id}/ship", payload, headers
        )

    def invoice_order(self, order_id, headers):
        return self._request(
            "POST", f"/rendering/sales-orders/{order_id}/invoice", {}, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/rendering/sales-orders/{order_id}/cancel", {}, headers
        )

    # --- Price index entries ---
    def create_price_index_entry(self, payload, headers):
        return self._request("POST", "/rendering/price-index-entries", payload, headers)

    def list_price_index_entries(self, headers, params=None):
        return self._request(
            "GET", "/rendering/price-index-entries", headers=headers, params=params
        )

    def get_price_index_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/rendering/price-index-entries/{entry_id}", headers=headers
        )

    # --- Period settlements ---
    def list_period_settlements(self, headers, params=None):
        return self._request(
            "GET", "/rendering/period-settlements", headers=headers, params=params
        )

    def get_period_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/rendering/period-settlements/{settlement_id}", headers=headers
        )

    def close_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/rendering/period-settlements/{settlement_id}/close", {}, headers
        )

    def reopen_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/rendering/period-settlements/{settlement_id}/reopen", {}, headers
        )

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/rendering/period-settlements/{settlement_id}/finalize", {}, headers
        )


api_client = ApiClient()
