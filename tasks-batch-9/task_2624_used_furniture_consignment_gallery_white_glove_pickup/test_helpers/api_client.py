"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Used Furniture Consignment Gallery API.

    Every endpoint is mounted at the service root; there is no shared prefix.
    """

    # --- Consignors ---------------------------------------------------------
    def create_consignor(self, payload, headers):
        return self._request("POST", "/consignors", payload, headers)

    def get_consignor(self, consignor_id, headers):
        return self._request("GET", f"/consignors/{consignor_id}", headers=headers)

    def list_consignors(self, headers, params=None):
        return self._request("GET", "/consignors", headers=headers, params=params)

    def patch_consignor(self, consignor_id, payload, headers):
        return self._request("PATCH", f"/consignors/{consignor_id}", payload, headers)

    def list_consignor_ledger_entries(self, consignor_id, headers, params=None):
        return self._request(
            "GET", f"/consignors/{consignor_id}/ledger-entries",
            headers=headers, params=params,
        )

    def create_payout(self, consignor_id, payload, headers):
        return self._request(
            "POST", f"/consignors/{consignor_id}/payouts", payload, headers
        )

    # --- Buyers -------------------------------------------------------------
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/buyers", headers=headers, params=params)

    def block_buyer(self, buyer_id, headers):
        return self._request("POST", f"/buyers/{buyer_id}/block", {}, headers)

    # --- Price schedules ----------------------------------------------------
    def create_price_schedule(self, payload, headers):
        return self._request("POST", "/price-schedules", payload, headers)

    def get_price_schedule(self, schedule_id, headers):
        return self._request("GET", f"/price-schedules/{schedule_id}", headers=headers)

    def list_price_schedules(self, headers, params=None):
        return self._request("GET", "/price-schedules", headers=headers, params=params)

    def create_price_schedule_step(self, payload, headers):
        return self._request("POST", "/price-schedule-steps", payload, headers)

    def list_price_schedule_steps(self, schedule_id, headers, params=None):
        return self._request(
            "GET", f"/price-schedules/{schedule_id}/steps",
            headers=headers, params=params,
        )

    def retire_price_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/price-schedules/{schedule_id}/retire", {}, headers
        )

    # --- Consignment agreements --------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/consignment-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/consignment-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/consignment-agreements", headers=headers, params=params
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/consignment-agreements/{agreement_id}/activate", {}, headers
        )

    # --- Consignment items --------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", "/consignment-items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/consignment-items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request(
            "GET", "/consignment-items", headers=headers, params=params
        )

    def screen_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/screen", payload, headers
        )

    def receive_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/receive", payload, headers
        )

    def place_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/place", payload, headers
        )

    def elect_disposition(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/elect-disposition", payload, headers
        )

    def inventory_flag(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/inventory-flag", payload, headers
        )

    def write_off_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/write-off", payload, headers
        )

    def release_item(self, item_id, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/release", {}, headers
        )

    def list_item_ledger_entries(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/consignment-items/{item_id}/ledger-entries",
            headers=headers, params=params,
        )

    # --- Trucks -------------------------------------------------------------
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    # --- White-glove crews --------------------------------------------------
    def create_crew(self, payload, headers):
        return self._request("POST", "/white-glove-crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/white-glove-crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request(
            "GET", "/white-glove-crews", headers=headers, params=params
        )

    # --- Floor zones --------------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/floor-zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/floor-zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/floor-zones", headers=headers, params=params)

    def close_zone(self, zone_id, headers):
        return self._request("POST", f"/floor-zones/{zone_id}/close", {}, headers)

    def list_zone_shrinkage_audits(self, zone_id, headers, params=None):
        return self._request(
            "GET", f"/floor-zones/{zone_id}/shrinkage-audits",
            headers=headers, params=params,
        )

    # --- Pickup jobs --------------------------------------------------------
    def create_pickup_job(self, payload, headers):
        return self._request("POST", "/pickup-jobs", payload, headers)

    def get_pickup_job(self, job_id, headers):
        return self._request("GET", f"/pickup-jobs/{job_id}", headers=headers)

    def list_pickup_jobs(self, headers, params=None):
        return self._request("GET", "/pickup-jobs", headers=headers, params=params)

    def attach_pickup_item(self, job_id, payload, headers):
        return self._request("POST", f"/pickup-jobs/{job_id}/items", payload, headers)

    def complete_pickup_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/pickup-jobs/{job_id}/complete", payload, headers
        )

    def cancel_pickup_job(self, job_id, headers):
        return self._request("POST", f"/pickup-jobs/{job_id}/cancel", {}, headers)

    # --- Sales --------------------------------------------------------------
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def reverse_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/reverse", {}, headers)

    # --- Delivery orders ----------------------------------------------------
    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def get_delivery_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def complete_delivery_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/complete", payload, headers
        )

    # --- Damage claims ------------------------------------------------------
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def request_claim_info(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/request-info", payload, headers
        )

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/resubmit", payload, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/adjudicate", payload, headers
        )

    # --- Shrinkage audits ---------------------------------------------------
    def create_shrinkage_audit(self, payload, headers):
        return self._request("POST", "/shrinkage-audits", payload, headers)

    def approve_write_off(self, audit_id, headers):
        return self._request(
            "POST", f"/shrinkage-audits/{audit_id}/approve-write-off", {}, headers
        )

    # --- Logical clock and the two nightly epochs ---------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_markdown_epoch(self, headers):
        return self._request("POST", "/_ops/markdown-run", {}, headers)

    def run_escheatment_epoch(self, headers):
        return self._request("POST", "/_ops/escheatment-run", {}, headers)


api_client = ApiClient()
