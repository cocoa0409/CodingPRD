"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ─── Brewer ───────────────────────────────────────────────────────
    def create_brewer(self, payload, headers):
        return self._request("POST", "/brewers", payload, headers)

    def get_brewer(self, brewer_id, headers):
        return self._request("GET", f"/brewers/{brewer_id}", headers=headers)

    def update_credit_profile(self, brewer_id, payload, headers):
        return self._request("PUT", f"/brewers/{brewer_id}/credit-profile",
                             payload, headers)

    def post_payment(self, brewer_id, payload, headers):
        return self._request("POST", f"/brewers/{brewer_id}/payments",
                             payload, headers)

    def post_volume_adjustment(self, brewer_id, payload, headers):
        return self._request("POST", f"/brewers/{brewer_id}/volume-adjustments",
                             payload, headers)

    # ─── CropYearProgram ──────────────────────────────────────────────
    def create_crop_year_program(self, payload, headers):
        return self._request("POST", "/crop-year-programs", payload, headers)

    def get_crop_year_program(self, program_id, headers):
        return self._request("GET", f"/crop-year-programs/{program_id}",
                             headers=headers)

    def list_crop_year_programs(self, headers, params=None):
        return self._request("GET", "/crop-year-programs", headers=headers,
                             params=params)

    def report_harvest(self, program_id, payload, headers):
        return self._request("POST",
                             f"/crop-year-programs/{program_id}/report-harvest",
                             payload, headers)

    def settle_program(self, program_id, payload, headers):
        return self._request("POST", f"/crop-year-programs/{program_id}/settle",
                             payload, headers)

    # ─── HopVariety ───────────────────────────────────────────────────
    def create_hop_variety(self, payload, headers):
        return self._request("POST", "/hop-varieties", payload, headers)

    def get_hop_variety(self, variety_id, headers):
        return self._request("GET", f"/hop-varieties/{variety_id}",
                             headers=headers)

    def update_spot_price(self, variety_id, payload, headers):
        return self._request("PUT", f"/hop-varieties/{variety_id}/spot-price",
                             payload, headers)

    # ─── HopContract ──────────────────────────────────────────────────
    def create_hop_contract(self, payload, headers):
        return self._request("POST", "/hop-contracts", payload, headers)

    def get_hop_contract(self, contract_id, headers):
        return self._request("GET", f"/hop-contracts/{contract_id}",
                             headers=headers)

    def list_hop_contracts(self, headers, params=None):
        return self._request("GET", "/hop-contracts", headers=headers,
                             params=params)

    def request_carry_forward(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/hop-contracts/{contract_id}/carry-forward-requests",
            payload, headers)

    def decide_carry_forward(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/hop-contracts/{contract_id}/carry-forward-decision",
            payload, headers)

    def declare_default(self, contract_id, payload, headers):
        return self._request("POST",
                             f"/hop-contracts/{contract_id}/declare-default",
                             payload, headers)

    def resell_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/hop-contracts/{contract_id}/resale",
                             payload, headers)

    def create_substitution_offer(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/hop-contracts/{contract_id}/substitution-offers",
            payload, headers)

    # ─── SubstitutionOffer ────────────────────────────────────────────
    def get_substitution_offer(self, offer_id, headers):
        return self._request("GET", f"/substitution-offers/{offer_id}",
                             headers=headers)

    def list_substitution_offers(self, headers, params=None):
        return self._request("GET", "/substitution-offers", headers=headers,
                             params=params)

    def respond_to_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/substitution-offers/{offer_id}/respond",
                             payload, headers)

    # ─── MaltProduct / MaltLot ────────────────────────────────────────
    def create_malt_product(self, payload, headers):
        return self._request("POST", "/malt-products", payload, headers)

    def get_malt_product(self, product_id, headers):
        return self._request("GET", f"/malt-products/{product_id}",
                             headers=headers)

    def create_malt_lot(self, payload, headers):
        return self._request("POST", "/malt-lots", payload, headers)

    def get_malt_lot(self, lot_id, headers):
        return self._request("GET", f"/malt-lots/{lot_id}", headers=headers)

    def list_malt_lots(self, headers, params=None):
        return self._request("GET", "/malt-lots", headers=headers, params=params)

    def record_analysis(self, lot_id, payload, headers):
        return self._request("POST", f"/malt-lots/{lot_id}/analysis",
                             payload, headers)

    def release_malt_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/malt-lots/{lot_id}/release",
                             payload, headers)

    def retest_malt_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/malt-lots/{lot_id}/retest",
                             payload, headers)

    def reject_malt_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/malt-lots/{lot_id}/reject",
                             payload, headers)

    def spec_match(self, lot_id, headers, params=None):
        return self._request("GET", f"/malt-lots/{lot_id}/spec-match",
                             headers=headers, params=params)

    # ─── BrewerRecipe ─────────────────────────────────────────────────
    def create_brewer_recipe(self, payload, headers):
        return self._request("POST", "/brewer-recipes", payload, headers)

    def get_brewer_recipe(self, recipe_id, headers):
        return self._request("GET", f"/brewer-recipes/{recipe_id}",
                             headers=headers)

    def list_brewer_recipes(self, headers, params=None):
        return self._request("GET", "/brewer-recipes", headers=headers,
                             params=params)

    # ─── YeastStrain / YeastPropagationJob ────────────────────────────
    def create_yeast_strain(self, payload, headers):
        return self._request("POST", "/yeast-strains", payload, headers)

    def get_yeast_strain(self, strain_id, headers):
        return self._request("GET", f"/yeast-strains/{strain_id}",
                             headers=headers)

    def create_propagation_job(self, payload, headers):
        return self._request("POST", "/yeast-propagation-jobs", payload, headers)

    def get_propagation_job(self, job_id, headers):
        return self._request("GET", f"/yeast-propagation-jobs/{job_id}",
                             headers=headers)

    def list_propagation_jobs(self, headers, params=None):
        return self._request("GET", "/yeast-propagation-jobs", headers=headers,
                             params=params)

    def start_propagation(self, job_id, headers):
        return self._request("POST", f"/yeast-propagation-jobs/{job_id}/start",
                             {}, headers)

    def complete_propagation(self, job_id, payload, headers):
        return self._request("POST",
                             f"/yeast-propagation-jobs/{job_id}/complete",
                             payload, headers)

    def requeue_propagation(self, job_id, payload, headers):
        return self._request("POST", f"/yeast-propagation-jobs/{job_id}/requeue",
                             payload, headers)

    # ─── SalesOrder ───────────────────────────────────────────────────
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers,
                             params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/lines",
                             payload, headers)

    def remove_order_line(self, order_id, line_id, headers):
        return self._request("DELETE",
                             f"/sales-orders/{order_id}/lines/{line_id}",
                             headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/confirm",
                             {}, headers)

    def record_credit_decision(self, order_id, payload, headers):
        return self._request("POST",
                             f"/sales-orders/{order_id}/credit-decision",
                             payload, headers)

    def pick_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/pick",
                             {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/ship",
                             {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/deliver",
                             {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel",
                             payload, headers)

    # ─── OrderLine ────────────────────────────────────────────────────
    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers,
                             params=params)

    # ─── ColdStorageZone / ColdChainShipment ──────────────────────────
    def create_cold_storage_zone(self, payload, headers):
        return self._request("POST", "/cold-storage-zones", payload, headers)

    def get_cold_storage_zone(self, zone_id, headers):
        return self._request("GET", f"/cold-storage-zones/{zone_id}",
                             headers=headers)

    def stage_shipment(self, payload, headers):
        return self._request("POST", "/cold-chain-shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/cold-chain-shipments/{shipment_id}",
                             headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/cold-chain-shipments", headers=headers,
                             params=params)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST",
                             f"/cold-chain-shipments/{shipment_id}/depart",
                             {}, headers)

    def add_reading(self, shipment_id, payload, headers):
        return self._request("POST",
                             f"/cold-chain-shipments/{shipment_id}/readings",
                             payload, headers)

    def list_readings(self, shipment_id, headers, params=None):
        return self._request("GET",
                             f"/cold-chain-shipments/{shipment_id}/readings",
                             headers=headers, params=params)

    def release_hold(self, shipment_id, headers):
        return self._request("POST",
                             f"/cold-chain-shipments/{shipment_id}/release-hold",
                             {}, headers)


api_client = ApiClient()
