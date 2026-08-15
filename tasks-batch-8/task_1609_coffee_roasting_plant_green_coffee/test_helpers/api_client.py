"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/roastery/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Counterparties
    # ------------------------------------------------------------------
    def create_counterparty(self, payload, headers):
        return self._request("POST", "/roastery/counterparties", payload, headers)

    def get_counterparty(self, counterparty_id, headers):
        return self._request("GET", f"/roastery/counterparties/{counterparty_id}",
                             headers=headers)

    def list_counterparties(self, headers, params=None):
        return self._request("GET", "/roastery/counterparties", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def create_contract(self, counterparty_id, payload, headers):
        return self._request("POST",
                             f"/roastery/counterparties/{counterparty_id}/contracts",
                             payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/roastery/contracts/{contract_id}",
                             headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/roastery/contracts", headers=headers,
                             params=params)

    def create_price_fix(self, contract_id, payload, headers):
        return self._request("POST",
                             f"/roastery/contracts/{contract_id}/price-fixes",
                             payload, headers)

    def list_price_fixes(self, contract_id, headers, params=None):
        return self._request("GET", f"/roastery/contracts/{contract_id}/price-fixes",
                             headers=headers, params=params)

    def short_close_contract(self, contract_id, payload, headers):
        return self._request("POST",
                             f"/roastery/contracts/{contract_id}/short-close",
                             payload, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/roastery/contracts/{contract_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def create_shipment(self, contract_id, payload, headers):
        return self._request("POST", f"/roastery/contracts/{contract_id}/shipments",
                             payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/roastery/shipments/{shipment_id}",
                             headers=headers)

    def list_shipments(self, contract_id, headers, params=None):
        return self._request("GET", f"/roastery/contracts/{contract_id}/shipments",
                             headers=headers, params=params)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"/roastery/shipments/{shipment_id}/depart",
                             {}, headers)

    def arrive_shipment(self, shipment_id, headers):
        return self._request("POST", f"/roastery/shipments/{shipment_id}/arrive",
                             {}, headers)

    def receive_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/roastery/shipments/{shipment_id}/receive",
                             payload, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/roastery/shipments/{shipment_id}/cancel",
                             {}, headers)

    def resolve_dispute(self, shipment_id, payload, headers):
        return self._request("POST",
                             f"/roastery/shipments/{shipment_id}/resolve-dispute",
                             payload, headers)

    # ------------------------------------------------------------------
    # Green lots
    # ------------------------------------------------------------------
    def get_green_lot(self, lot_id, headers):
        return self._request("GET", f"/roastery/green-lots/{lot_id}", headers=headers)

    def list_green_lots(self, headers, params=None):
        return self._request("GET", "/roastery/green-lots", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Warehouse position
    # ------------------------------------------------------------------
    def get_warehouse_position(self, headers):
        return self._request("GET", "/roastery/warehouse-position", headers=headers)

    # ------------------------------------------------------------------
    # Financing lines and reserves
    # ------------------------------------------------------------------
    def create_financing_line(self, payload, headers):
        return self._request("POST", "/roastery/financing-lines", payload, headers)

    def get_financing_line(self, line_id, headers):
        return self._request("GET", f"/roastery/financing-lines/{line_id}",
                             headers=headers)

    def create_financing_reserve(self, line_id, payload, headers):
        return self._request("POST", f"/roastery/financing-lines/{line_id}/reserves",
                             payload, headers)

    def release_financing_reserve(self, reserve_id, headers):
        return self._request("POST",
                             f"/roastery/financing-reserves/{reserve_id}/release",
                             {}, headers)

    def suspend_financing_line(self, line_id, headers):
        return self._request("POST", f"/roastery/financing-lines/{line_id}/suspend",
                             {}, headers)

    def unsuspend_financing_line(self, line_id, headers):
        return self._request("POST",
                             f"/roastery/financing-lines/{line_id}/unsuspend",
                             {}, headers)

    def close_financing_line(self, line_id, headers):
        return self._request("POST", f"/roastery/financing-lines/{line_id}/close",
                             {}, headers)

    def get_financing_reserve(self, reserve_id, headers):
        return self._request("GET", f"/roastery/financing-reserves/{reserve_id}",
                             headers=headers)

    def list_financing_reserves(self, headers, params=None):
        return self._request("GET", "/roastery/financing-reserves", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Roast profiles
    # ------------------------------------------------------------------
    def create_roast_profile(self, payload, headers):
        return self._request("POST", "/roastery/roast-profiles", payload, headers)

    def get_roast_profile(self, profile_id, headers):
        return self._request("GET", f"/roastery/roast-profiles/{profile_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/roastery/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/roastery/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/roastery/products", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Blend recipes and components
    # ------------------------------------------------------------------
    def create_recipe(self, product_id, headers):
        return self._request("POST", f"/roastery/products/{product_id}/recipes",
                             {}, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/roastery/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, product_id, headers, params=None):
        return self._request("GET", f"/roastery/products/{product_id}/recipes",
                             headers=headers, params=params)

    def add_recipe_component(self, recipe_id, payload, headers):
        return self._request("POST", f"/roastery/recipes/{recipe_id}/components",
                             payload, headers)

    def list_recipe_components(self, recipe_id, headers, params=None):
        return self._request("GET", f"/roastery/recipes/{recipe_id}/components",
                             headers=headers, params=params)

    def approve_recipe(self, recipe_id, payload, headers):
        return self._request("POST", f"/roastery/recipes/{recipe_id}/approve",
                             payload, headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/roastery/recipes/{recipe_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Roast batches
    # ------------------------------------------------------------------
    def create_roast_batch(self, payload, headers):
        return self._request("POST", "/roastery/roast-batches", payload, headers)

    def get_roast_batch(self, batch_id, headers):
        return self._request("GET", f"/roastery/roast-batches/{batch_id}",
                             headers=headers)

    def list_roast_batches(self, headers, params=None):
        return self._request("GET", "/roastery/roast-batches", headers=headers,
                             params=params)

    def list_batch_allocations(self, batch_id, headers, params=None):
        return self._request("GET",
                             f"/roastery/roast-batches/{batch_id}/allocations",
                             headers=headers, params=params)

    def get_roast_input_allocation(self, alloc_id, headers):
        return self._request("GET", f"/roastery/roast-input-allocations/{alloc_id}",
                             headers=headers)

    def list_roast_input_allocations(self, headers, params=None):
        return self._request("GET", "/roastery/roast-input-allocations",
                             headers=headers, params=params)

    def start_roast_batch(self, batch_id, headers):
        return self._request("POST", f"/roastery/roast-batches/{batch_id}/start",
                             {}, headers)

    def finish_roast_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/roastery/roast-batches/{batch_id}/finish",
                             payload, headers)

    def pack_roast_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/roastery/roast-batches/{batch_id}/pack",
                             payload, headers)

    def void_roast_batch(self, batch_id, headers):
        return self._request("POST", f"/roastery/roast-batches/{batch_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Cupping sessions
    # ------------------------------------------------------------------
    def create_cupping_session(self, payload, headers):
        return self._request("POST", "/roastery/cupping-sessions", payload, headers)

    def get_cupping_session(self, session_id, headers):
        return self._request("GET", f"/roastery/cupping-sessions/{session_id}",
                             headers=headers)

    def finalize_cupping_session(self, session_id, headers):
        return self._request("POST",
                             f"/roastery/cupping-sessions/{session_id}/finalize",
                             {}, headers)

    # ------------------------------------------------------------------
    # Finished goods lots
    # ------------------------------------------------------------------
    def get_finished_goods_lot(self, lot_id, headers):
        return self._request("GET", f"/roastery/finished-goods-lots/{lot_id}",
                             headers=headers)

    def list_finished_goods_lots(self, headers, params=None):
        return self._request("GET", "/roastery/finished-goods-lots", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Fulfillment orders and lines
    # ------------------------------------------------------------------
    def create_fulfillment_order(self, payload, headers):
        return self._request("POST", "/roastery/fulfillment-orders", payload, headers)

    def get_fulfillment_order(self, order_id, headers):
        return self._request("GET", f"/roastery/fulfillment-orders/{order_id}",
                             headers=headers)

    def list_fulfillment_orders(self, headers, params=None):
        return self._request("GET", "/roastery/fulfillment-orders", headers=headers,
                             params=params)

    def add_fulfillment_line(self, order_id, payload, headers):
        return self._request("POST",
                             f"/roastery/fulfillment-orders/{order_id}/lines",
                             payload, headers)

    def list_fulfillment_lines_of_order(self, order_id, headers, params=None):
        return self._request("GET",
                             f"/roastery/fulfillment-orders/{order_id}/lines",
                             headers=headers, params=params)

    def get_fulfillment_line(self, line_id, headers):
        return self._request("GET", f"/roastery/fulfillment-lines/{line_id}",
                             headers=headers)

    def list_fulfillment_lines(self, headers, params=None):
        return self._request("GET", "/roastery/fulfillment-lines", headers=headers,
                             params=params)

    def reserve_fulfillment_order(self, order_id, headers):
        return self._request("POST",
                             f"/roastery/fulfillment-orders/{order_id}/reserve",
                             {}, headers)

    def pack_fulfillment_order(self, order_id, headers):
        return self._request("POST",
                             f"/roastery/fulfillment-orders/{order_id}/pack",
                             {}, headers)

    def ship_fulfillment_order(self, order_id, headers):
        return self._request("POST",
                             f"/roastery/fulfillment-orders/{order_id}/ship",
                             {}, headers)

    def cancel_fulfillment_order(self, order_id, headers):
        return self._request("POST",
                             f"/roastery/fulfillment-orders/{order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Futures hedges
    # ------------------------------------------------------------------
    def create_futures_hedge(self, contract_id, payload, headers):
        return self._request("POST",
                             f"/roastery/contracts/{contract_id}/futures-hedges",
                             payload, headers)

    def get_futures_hedge(self, hedge_id, headers):
        return self._request("GET", f"/roastery/futures-hedges/{hedge_id}",
                             headers=headers)

    def list_futures_hedges(self, contract_id, headers, params=None):
        return self._request("GET",
                             f"/roastery/contracts/{contract_id}/futures-hedges",
                             headers=headers, params=params)

    def approve_futures_hedge(self, hedge_id, headers):
        return self._request("POST",
                             f"/roastery/futures-hedges/{hedge_id}/approve",
                             {}, headers)

    def lift_futures_hedge(self, hedge_id, payload, headers):
        return self._request("POST", f"/roastery/futures-hedges/{hedge_id}/lift",
                             payload, headers)

    def cancel_futures_hedge(self, hedge_id, headers):
        return self._request("POST", f"/roastery/futures-hedges/{hedge_id}/cancel",
                             {}, headers)


api_client = ApiClient()
