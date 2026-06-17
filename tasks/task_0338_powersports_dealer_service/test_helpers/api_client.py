"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ─── Customer ─────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Unit ─────────────────────────────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def receive_unit(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/receive", headers=headers)

    # ─── FloorPlanLoan ────────────────────────────────────────────────────────
    def create_floor_plan_loan(self, payload, headers):
        return self._request("POST", "/floor-plan-loans", payload, headers)

    def list_floor_plan_loans(self, headers, params=None):
        return self._request("GET", "/floor-plan-loans", headers=headers, params=params)

    def get_floor_plan_loan(self, loan_id, headers, params=None):
        return self._request("GET", f"/floor-plan-loans/{loan_id}", headers=headers, params=params)

    def run_aging(self, loan_id, headers):
        return self._request("POST", f"/floor-plan-loans/{loan_id}/run-aging", headers=headers)

    # ─── Curtailment ──────────────────────────────────────────────────────────
    def create_curtailment(self, payload, headers):
        return self._request("POST", "/curtailments", payload, headers)

    def list_curtailments(self, headers, params=None):
        return self._request("GET", "/curtailments", headers=headers, params=params)

    def get_curtailment(self, curtailment_id, headers):
        return self._request("GET", f"/curtailments/{curtailment_id}", headers=headers)

    # ─── TradeIn ──────────────────────────────────────────────────────────────
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def reject_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/reject", headers=headers)

    # ─── Deal ─────────────────────────────────────────────────────────────────
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def quote_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/quote", headers=headers)

    def submit_finance_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/submit-finance", headers=headers)

    def approve_deal(self, deal_id, headers, payload=None):
        return self._request("POST", f"/deals/{deal_id}/approve", payload, headers)

    def decline_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/decline", headers=headers)

    def deliver_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/deliver", headers=headers)

    def cancel_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/cancel", headers=headers)

    # ─── Technician ───────────────────────────────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # ─── RepairOrder ──────────────────────────────────────────────────────────
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}", headers=headers)

    def start_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/start", headers=headers)

    def complete_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/complete", headers=headers)

    def invoice_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/invoice", headers=headers)

    def pay_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/pay", headers=headers)

    def cancel_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/cancel", headers=headers)

    # ─── ServiceLine ──────────────────────────────────────────────────────────
    def create_service_line(self, payload, headers):
        return self._request("POST", "/service-lines", payload, headers)

    def list_service_lines(self, headers, params=None):
        return self._request("GET", "/service-lines", headers=headers, params=params)

    def get_service_line(self, line_id, headers):
        return self._request("GET", f"/service-lines/{line_id}", headers=headers)

    # ─── Part ─────────────────────────────────────────────────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def restock_part(self, part_id, payload, headers):
        return self._request("POST", f"/parts/{part_id}/restock", payload, headers)

    # ─── PartLine ─────────────────────────────────────────────────────────────
    def create_part_line(self, payload, headers):
        return self._request("POST", "/part-lines", payload, headers)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", "/part-lines", headers=headers, params=params)

    def get_part_line(self, line_id, headers):
        return self._request("GET", f"/part-lines/{line_id}", headers=headers)

    def release_part_line(self, line_id, headers):
        return self._request("DELETE", f"/part-lines/{line_id}", headers=headers)

    # ─── StorageBay ───────────────────────────────────────────────────────────
    def create_storage_bay(self, payload, headers):
        return self._request("POST", "/storage-bays", payload, headers)

    def list_storage_bays(self, headers, params=None):
        return self._request("GET", "/storage-bays", headers=headers, params=params)

    def get_storage_bay(self, bay_id, headers):
        return self._request("GET", f"/storage-bays/{bay_id}", headers=headers)

    # ─── StorageAgreement ─────────────────────────────────────────────────────
    def create_storage_agreement(self, payload, headers):
        return self._request("POST", "/storage-agreements", payload, headers)

    def list_storage_agreements(self, headers, params=None):
        return self._request("GET", "/storage-agreements", headers=headers, params=params)

    def get_storage_agreement(self, agr_id, headers):
        return self._request("GET", f"/storage-agreements/{agr_id}", headers=headers)

    def check_in_storage_agreement(self, agr_id, headers):
        return self._request("POST", f"/storage-agreements/{agr_id}/check-in", headers=headers)

    def check_out_storage_agreement(self, agr_id, headers):
        return self._request("POST", f"/storage-agreements/{agr_id}/check-out", headers=headers)

    def cancel_storage_agreement(self, agr_id, headers):
        return self._request("POST", f"/storage-agreements/{agr_id}/cancel", headers=headers)

    # ─── TestRideWaiver ───────────────────────────────────────────────────────
    def create_test_ride_waiver(self, payload, headers):
        return self._request("POST", "/test-ride-waivers", payload, headers)

    def list_test_ride_waivers(self, headers, params=None):
        return self._request("GET", "/test-ride-waivers", headers=headers, params=params)

    def get_test_ride_waiver(self, waiver_id, headers):
        return self._request("GET", f"/test-ride-waivers/{waiver_id}", headers=headers)

    def log_ride(self, waiver_id, headers):
        return self._request("POST", f"/test-ride-waivers/{waiver_id}/log-ride", headers=headers)

    def void_waiver(self, waiver_id, headers):
        return self._request("POST", f"/test-ride-waivers/{waiver_id}/void", headers=headers)

    # ─── WarrantyClaim ────────────────────────────────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", headers=headers)

    def reject_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/reject", headers=headers)

    def pay_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/pay", headers=headers)


api_client = ApiClient()
