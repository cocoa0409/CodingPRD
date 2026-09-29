"""API client: one method per endpoint of PRD §4. Every path is absolute."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Ops endpoints (PRD §2.5, §3.1) ────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def daily_close(self, headers, payload=None):
        return self._request("POST", "/daily-close", payload, headers)

    def inject_delivered_unit(self, payload, headers):
        return self._request("POST", "/_inject/delivered-unit", payload, headers)

    # ─── Suppliers ─────────────────────────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def get_supplier_scorecard(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}/scorecard", headers=headers)

    # ─── Floor plans ───────────────────────────────────────────────────────
    def create_floor_plan(self, payload, headers):
        return self._request("POST", "/floor-plans", payload, headers)

    def get_floor_plan(self, floor_plan_id, headers):
        return self._request("GET", f"/floor-plans/{floor_plan_id}", headers=headers)

    def patch_floor_plan(self, floor_plan_id, payload, headers):
        return self._request("PATCH", f"/floor-plans/{floor_plan_id}", payload, headers)

    # ─── Option items ──────────────────────────────────────────────────────
    def create_option_item(self, payload, headers):
        return self._request("POST", "/option-items", payload, headers)

    def get_option_item(self, option_item_id, headers):
        return self._request("GET", f"/option-items/{option_item_id}", headers=headers)

    def patch_option_item(self, option_item_id, payload, headers):
        return self._request("PATCH", f"/option-items/{option_item_id}", payload, headers)

    # ─── Dealers ───────────────────────────────────────────────────────────
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def set_dealer_status(self, dealer_id, payload, headers):
        return self._request("POST", f"/dealers/{dealer_id}/status", payload, headers)

    # ─── Production lines ──────────────────────────────────────────────────
    def create_production_line(self, payload, headers):
        return self._request("POST", "/production-lines", payload, headers)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/production-lines/{line_id}", headers=headers)

    def set_production_line_status(self, line_id, payload, headers):
        return self._request("POST", f"/production-lines/{line_id}/status", payload, headers)

    # ─── Test booths ───────────────────────────────────────────────────────
    def create_test_booth(self, payload, headers):
        return self._request("POST", "/test-booths", payload, headers)

    def get_test_booth(self, booth_id, headers):
        return self._request("GET", f"/test-booths/{booth_id}", headers=headers)

    def set_test_booth_status(self, booth_id, payload, headers):
        return self._request("POST", f"/test-booths/{booth_id}/status", payload, headers)

    # ─── Chassis receipts ──────────────────────────────────────────────────
    def create_chassis_receipt(self, payload, headers):
        return self._request("POST", "/chassis-receipts", payload, headers)

    def get_chassis_receipt(self, chassis_id, headers):
        return self._request("GET", f"/chassis-receipts/{chassis_id}", headers=headers)

    def list_chassis_receipts(self, headers, params=None):
        return self._request("GET", "/chassis-receipts", headers=headers, params=params)

    # ─── Component lots ────────────────────────────────────────────────────
    def create_component_lot(self, payload, headers):
        return self._request("POST", "/component-lots", payload, headers)

    def get_component_lot(self, lot_id, headers):
        return self._request("GET", f"/component-lots/{lot_id}", headers=headers)

    def list_component_lots(self, headers, params=None):
        return self._request("GET", "/component-lots", headers=headers, params=params)

    # ─── Unit orders ───────────────────────────────────────────────────────
    def create_unit_order(self, payload, headers):
        return self._request("POST", "/unit-orders", payload, headers)

    def get_unit_order(self, order_id, headers):
        return self._request("GET", f"/unit-orders/{order_id}", headers=headers)

    def list_unit_orders(self, headers, params=None):
        return self._request("GET", "/unit-orders", headers=headers, params=params)

    def replace_configuration(self, order_id, payload, headers):
        return self._request("PUT", f"/unit-orders/{order_id}/configuration", payload, headers)

    def submit_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/unit-orders/{order_id}/submit", payload, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/unit-orders/{order_id}/cancel", payload, headers)

    # ─── Production slots ──────────────────────────────────────────────────
    def reserve_production_slot(self, order_id, payload, headers):
        return self._request(
            "POST", f"/unit-orders/{order_id}/production-slots", payload, headers
        )

    def get_production_slot(self, slot_id, headers):
        return self._request("GET", f"/production-slots/{slot_id}", headers=headers)

    def list_production_slots(self, headers, params=None):
        return self._request("GET", "/production-slots", headers=headers, params=params)

    # ─── Matching, release, shipment ───────────────────────────────────────
    def match_chassis(self, order_id, headers, payload=None):
        return self._request("POST", f"/unit-orders/{order_id}/match-chassis", payload, headers)

    def release_to_line(self, order_id, headers, payload=None):
        return self._request("POST", f"/unit-orders/{order_id}/release-to-line", payload, headers)

    def ship_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/unit-orders/{order_id}/ship", payload, headers)

    # ─── Floor-plan financing ──────────────────────────────────────────────
    def request_funding(self, order_id, headers, payload=None):
        return self._request("POST", f"/unit-orders/{order_id}/request-funding", payload, headers)

    def funding_decision(self, order_id, payload, headers):
        return self._request("POST", f"/unit-orders/{order_id}/funding-decision", payload, headers)

    def floor_plan_payment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/unit-orders/{order_id}/floor-plan-payment", payload, headers
        )

    # ─── Unit builds ───────────────────────────────────────────────────────
    def get_unit_build(self, build_id, headers):
        return self._request("GET", f"/unit-builds/{build_id}", headers=headers)

    def list_unit_builds(self, headers, params=None):
        return self._request("GET", "/unit-builds", headers=headers, params=params)

    def advance_build(self, build_id, payload, headers):
        return self._request("POST", f"/unit-builds/{build_id}/advance", payload, headers)

    # ─── Component installations ───────────────────────────────────────────
    def create_component_installation(self, payload, headers):
        return self._request("POST", "/component-installations", payload, headers)

    def get_component_installation(self, installation_id, headers):
        return self._request(
            "GET", f"/component-installations/{installation_id}", headers=headers
        )

    def list_component_installations(self, headers, params=None):
        return self._request("GET", "/component-installations", headers=headers, params=params)

    def reverse_installation(self, installation_id, headers, payload=None):
        return self._request(
            "POST", f"/component-installations/{installation_id}/reverse", payload, headers
        )

    def remedy_installation(self, installation_id, headers, payload=None):
        return self._request(
            "POST", f"/component-installations/{installation_id}/remedy", payload, headers
        )

    # ─── Quality inspections ───────────────────────────────────────────────
    def create_quality_inspection(self, payload, headers):
        return self._request("POST", "/quality-inspections", payload, headers)

    def get_quality_inspection(self, inspection_id, headers):
        return self._request("GET", f"/quality-inspections/{inspection_id}", headers=headers)

    def list_quality_inspections(self, headers, params=None):
        return self._request("GET", "/quality-inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/quality-inspections/{inspection_id}/complete", payload, headers
        )

    # ─── Warranty claims ───────────────────────────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def request_claim_info(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/request-info", payload, headers
        )

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/resubmit", payload, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/decide", payload, headers)

    def pay_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty-claims/{claim_id}/pay", payload, headers)

    # ─── Recall campaigns ──────────────────────────────────────────────────
    def create_recall_campaign(self, payload, headers):
        return self._request("POST", "/recall-campaigns", payload, headers)

    def get_recall_campaign(self, campaign_id, headers):
        return self._request("GET", f"/recall-campaigns/{campaign_id}", headers=headers)

    def list_recall_campaigns(self, headers, params=None):
        return self._request("GET", "/recall-campaigns", headers=headers, params=params)

    def open_recall_campaign(self, campaign_id, headers, payload=None):
        return self._request("POST", f"/recall-campaigns/{campaign_id}/open", payload, headers)

    def expand_recall_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/recall-campaigns/{campaign_id}/expand", payload, headers)

    def close_recall_campaign(self, campaign_id, headers, payload=None):
        return self._request("POST", f"/recall-campaigns/{campaign_id}/close", payload, headers)


api_client = ApiClient()
