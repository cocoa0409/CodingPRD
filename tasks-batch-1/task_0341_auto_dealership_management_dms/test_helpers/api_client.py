"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Vehicle ----------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def recondition_complete(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/recondition-complete", {}, headers)

    def create_floor_plan_line(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/floor-plan-lines", payload, headers)

    def list_floor_plan_lines_for_vehicle(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/floor-plan-lines", headers=headers, params=params)

    # ---------------- FloorPlanLine ----------------
    def get_floor_plan_line(self, line_id, headers):
        return self._request("GET", f"/floor-plan-lines/{line_id}", headers=headers)

    def create_curtailment(self, line_id, payload, headers):
        return self._request("POST", f"/floor-plan-lines/{line_id}/curtailments", payload, headers)

    def payoff_quote(self, line_id, payload, headers):
        return self._request("POST", f"/floor-plan-lines/{line_id}/payoff-quote", payload, headers)

    # ---------------- Customer ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---------------- Config catalogs ----------------
    def create_lender_program(self, payload, headers):
        return self._request("POST", "/lender-programs", payload, headers)

    def get_lender_program(self, program_id, headers):
        return self._request("GET", f"/lender-programs/{program_id}", headers=headers)

    def create_finance_product(self, payload, headers):
        return self._request("POST", "/finance-products", payload, headers)

    def get_finance_product(self, product_id, headers):
        return self._request("GET", f"/finance-products/{product_id}", headers=headers)

    def create_oem_incentive(self, payload, headers):
        return self._request("POST", "/oem-incentives", payload, headers)

    def get_oem_incentive(self, incentive_id, headers):
        return self._request("GET", f"/oem-incentives/{incentive_id}", headers=headers)

    # ---------------- Deal core ----------------
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def desk_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/desk", {}, headers)

    def apply_incentive(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/apply-incentive", payload, headers)

    def submit_to_lender(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/submit-to-lender", {}, headers)

    def lender_decision(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/lender-decision", payload, headers)

    def contract_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/contract", {}, headers)

    def fund_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/fund", payload, headers)

    def unwind_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/unwind", {}, headers)

    def kill_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/kill", {}, headers)

    # ---------------- Deal sub-resources ----------------
    def attach_product(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/products", payload, headers)

    def list_deal_products(self, deal_id, headers, params=None):
        return self._request("GET", f"/deals/{deal_id}/products", headers=headers, params=params)

    def void_product(self, deal_id, deal_product_id, headers):
        return self._request("DELETE", f"/deals/{deal_id}/products/{deal_product_id}", headers=headers)

    def attach_trade_in(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/trade-ins", payload, headers)

    def list_trade_ins(self, deal_id, headers, params=None):
        return self._request("GET", f"/deals/{deal_id}/trade-ins", headers=headers, params=params)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def create_finance_contract(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/finance-contracts", payload, headers)

    def list_finance_contracts(self, deal_id, headers, params=None):
        return self._request("GET", f"/deals/{deal_id}/finance-contracts", headers=headers, params=params)

    def get_finance_contract(self, contract_id, headers):
        return self._request("GET", f"/finance-contracts/{contract_id}", headers=headers)

    def upload_document(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/documents", payload, headers)

    def list_documents(self, deal_id, headers, params=None):
        return self._request("GET", f"/deals/{deal_id}/documents", headers=headers, params=params)

    # ---------------- TestDrive ----------------
    def book_test_drive(self, payload, headers):
        return self._request("POST", "/test-drives", payload, headers)

    def get_test_drive(self, test_drive_id, headers):
        return self._request("GET", f"/test-drives/{test_drive_id}", headers=headers)

    def list_test_drives(self, headers, params=None):
        return self._request("GET", "/test-drives", headers=headers, params=params)

    def complete_test_drive(self, test_drive_id, headers):
        return self._request("POST", f"/test-drives/{test_drive_id}/complete", {}, headers)

    def cancel_test_drive(self, test_drive_id, headers):
        return self._request("POST", f"/test-drives/{test_drive_id}/cancel", {}, headers)

    # ---------------- RepairOrder ----------------
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def close_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/close", {}, headers)

    def cancel_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/cancel", {}, headers)

    # ---------------- TitleRegistration ----------------
    def get_title_registration(self, tr_id, headers):
        return self._request("GET", f"/title-registrations/{tr_id}", headers=headers)

    def list_title_registrations(self, headers, params=None):
        return self._request("GET", "/title-registrations", headers=headers, params=params)

    def patch_title_registration(self, tr_id, payload, headers):
        return self._request("PATCH", f"/title-registrations/{tr_id}", payload, headers)

    def submit_title_registration(self, tr_id, headers):
        return self._request("POST", f"/title-registrations/{tr_id}/submit", {}, headers)

    def dmv_result(self, tr_id, payload, headers):
        return self._request("POST", f"/title-registrations/{tr_id}/dmv-result", payload, headers)

    # ---------------- Deterministic clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
