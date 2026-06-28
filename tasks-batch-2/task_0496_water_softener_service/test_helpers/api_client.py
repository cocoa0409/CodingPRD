"""API client: one method per endpoint defined in the Water Softener Service PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers / Field Techs ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_field_tech(self, payload, headers):
        return self._request("POST", "/field-techs", payload, headers)

    def get_field_tech(self, tech_id, headers):
        return self._request("GET", f"/field-techs/{tech_id}", headers=headers)

    # ---- Service Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def credit_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/credit", payload, headers)

    # ---- Water Tests ----
    def create_water_test(self, payload, headers):
        return self._request("POST", "/water-tests", payload, headers)

    def get_water_test(self, water_test_id, headers):
        return self._request("GET", f"/water-tests/{water_test_id}", headers=headers)

    def list_water_tests(self, headers, params=None):
        return self._request("GET", "/water-tests", headers=headers, params=params)

    def recommend_water_test(self, water_test_id, headers):
        return self._request("POST", f"/water-tests/{water_test_id}/recommend", {}, headers)

    def accept_water_test(self, water_test_id, headers):
        return self._request("POST", f"/water-tests/{water_test_id}/accept", {}, headers)

    # ---- Softener Systems ----
    def create_system(self, payload, headers):
        return self._request("POST", "/systems", payload, headers)

    def get_system(self, system_id, headers):
        return self._request("GET", f"/systems/{system_id}", headers=headers)

    def list_systems(self, headers, params=None):
        return self._request("GET", "/systems", headers=headers, params=params)

    def install_system(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/install", {}, headers)

    def activate_system(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/activate", {}, headers)

    def decommission_system(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/decommission", {}, headers)

    def meter_reading(self, system_id, payload, headers):
        return self._request("POST", f"/systems/{system_id}/meter-reading", payload, headers)

    def regenerate_system(self, system_id, headers):
        return self._request("POST", f"/systems/{system_id}/regenerate", {}, headers)

    def list_system_cartridge_schedules(self, system_id, headers, params=None):
        return self._request("GET", f"/systems/{system_id}/cartridge-schedules", headers=headers, params=params)

    def list_system_service_visits(self, system_id, headers, params=None):
        return self._request("GET", f"/systems/{system_id}/service-visits", headers=headers, params=params)

    def list_system_warranty_claims(self, system_id, headers, params=None):
        return self._request("GET", f"/systems/{system_id}/warranty-claims", headers=headers, params=params)

    # ---- Rental Contracts ----
    def create_rental_contract(self, payload, headers):
        return self._request("POST", "/rental-contracts", payload, headers)

    def get_rental_contract(self, contract_id, headers):
        return self._request("GET", f"/rental-contracts/{contract_id}", headers=headers)

    def list_rental_contracts(self, headers, params=None):
        return self._request("GET", "/rental-contracts", headers=headers, params=params)

    def suspend_rental_contract(self, contract_id, headers):
        return self._request("POST", f"/rental-contracts/{contract_id}/suspend", {}, headers)

    def resume_rental_contract(self, contract_id, headers):
        return self._request("POST", f"/rental-contracts/{contract_id}/resume", {}, headers)

    def terminate_rental_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/rental-contracts/{contract_id}/terminate", payload, headers)

    # ---- Routes & Stops ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def list_route_stops_for_route(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/complete", {}, headers)

    # ---- Route Stops (peer access) ----
    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def complete_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/complete", {}, headers)

    # ---- Cartridge Schedules ----
    def create_cartridge_schedule(self, payload, headers):
        return self._request("POST", "/cartridge-schedules", payload, headers)

    def get_cartridge_schedule(self, schedule_id, headers):
        return self._request("GET", f"/cartridge-schedules/{schedule_id}", headers=headers)

    def evaluate_cartridge_schedule(self, schedule_id, headers):
        return self._request("POST", f"/cartridge-schedules/{schedule_id}/evaluate", {}, headers)

    def replace_cartridge_schedule(self, schedule_id, headers):
        return self._request("POST", f"/cartridge-schedules/{schedule_id}/replace", {}, headers)

    # ---- Service Visits ----
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/service-visits", headers=headers, params=params)

    def confirm_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/confirm", {}, headers)

    def void_service_visit(self, visit_id, headers):
        return self._request("POST", f"/service-visits/{visit_id}/void", {}, headers)

    # ---- Warranty Claims ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def triage_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/triage", {}, headers)

    def resolve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/resolve", payload, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", {}, headers)

    def close_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/close", {}, headers)

    # ---- Invoices ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def evaluate_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/evaluate", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ---- Logical Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
