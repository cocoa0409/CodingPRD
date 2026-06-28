"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ServiceContract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/aquatics/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/aquatics/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/aquatics/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/aquatics/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/aquatics/contracts/{contract_id}/suspend", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/aquatics/contracts/{contract_id}/terminate", {}, headers)

    # ---- SystemProfile ----
    def create_system(self, payload, headers):
        return self._request("POST", "/aquatics/systems", payload, headers)

    def get_system(self, system_id, headers):
        return self._request("GET", f"/aquatics/systems/{system_id}", headers=headers)

    def list_systems_under_contract(self, contract_id, headers, params=None):
        return self._request("GET", f"/aquatics/contracts/{contract_id}/systems", headers=headers, params=params)

    def commission_system(self, system_id, headers):
        return self._request("POST", f"/aquatics/systems/{system_id}/commission", {}, headers)

    def decommission_system(self, system_id, headers):
        return self._request("POST", f"/aquatics/systems/{system_id}/decommission", {}, headers)

    # ---- Livestock ----
    def create_livestock(self, payload, headers):
        return self._request("POST", "/aquatics/livestock", payload, headers)

    def list_livestock_under_system(self, system_id, headers, params=None):
        return self._request("GET", f"/aquatics/systems/{system_id}/livestock", headers=headers, params=params)

    def get_livestock(self, livestock_id, headers):
        return self._request("GET", f"/aquatics/livestock/{livestock_id}", headers=headers)

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", "/aquatics/equipment", payload, headers)

    def list_equipment_under_system(self, system_id, headers, params=None):
        return self._request("GET", f"/aquatics/systems/{system_id}/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/aquatics/equipment/{equipment_id}", headers=headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/aquatics/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/aquatics/technicians/{technician_id}", headers=headers)

    # ---- ServiceVisit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/aquatics/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/aquatics/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/aquatics/visits", headers=headers, params=params)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/aquatics/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/aquatics/visits/{visit_id}/complete", payload, headers)

    def dispute_visit(self, visit_id, headers):
        return self._request("POST", f"/aquatics/visits/{visit_id}/dispute", {}, headers)

    def rework_visit(self, visit_id, headers):
        return self._request("POST", f"/aquatics/visits/{visit_id}/rework", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/aquatics/visits/{visit_id}/cancel", {}, headers)

    # ---- WaterTest ----
    def create_water_test(self, visit_id, payload, headers):
        return self._request("POST", f"/aquatics/visits/{visit_id}/water-tests", payload, headers)

    def list_water_tests(self, visit_id, headers, params=None):
        return self._request("GET", f"/aquatics/visits/{visit_id}/water-tests", headers=headers, params=params)

    # ---- Invoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/aquatics/invoices/{invoice_id}", headers=headers)

    def list_invoices_under_contract(self, contract_id, headers, params=None):
        return self._request("GET", f"/aquatics/contracts/{contract_id}/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/aquatics/invoices/{invoice_id}/payments", payload, headers)

    def flag_invoice_overdue(self, invoice_id, headers):
        return self._request("POST", f"/aquatics/invoices/{invoice_id}/flag-overdue", {}, headers)

    # ---- InstallProject ----
    def create_install(self, payload, headers):
        return self._request("POST", "/aquatics/installs", payload, headers)

    def get_install(self, install_id, headers):
        return self._request("GET", f"/aquatics/installs/{install_id}", headers=headers)

    def list_installs_under_contract(self, contract_id, headers, params=None):
        return self._request("GET", f"/aquatics/contracts/{contract_id}/installs", headers=headers, params=params)

    def list_installs_under_system(self, system_id, headers, params=None):
        return self._request("GET", f"/aquatics/systems/{system_id}/installs", headers=headers, params=params)

    def approve_install(self, install_id, headers):
        return self._request("POST", f"/aquatics/installs/{install_id}/approve", {}, headers)

    def start_build_install(self, install_id, headers):
        return self._request("POST", f"/aquatics/installs/{install_id}/start-build", {}, headers)

    def handoff_install(self, install_id, payload, headers):
        return self._request("POST", f"/aquatics/installs/{install_id}/handoff", payload, headers)

    def cancel_install(self, install_id, headers):
        return self._request("POST", f"/aquatics/installs/{install_id}/cancel", {}, headers)

    # ---- EmergencyCall ----
    def create_emergency(self, payload, headers):
        return self._request("POST", "/aquatics/emergencies", payload, headers)

    def get_emergency(self, emergency_id, headers):
        return self._request("GET", f"/aquatics/emergencies/{emergency_id}", headers=headers)

    def list_emergencies_under_system(self, system_id, headers, params=None):
        return self._request("GET", f"/aquatics/systems/{system_id}/emergencies", headers=headers, params=params)

    def dispatch_emergency(self, emergency_id, payload, headers):
        return self._request("POST", f"/aquatics/emergencies/{emergency_id}/dispatch", payload, headers)

    def cancel_emergency(self, emergency_id, headers):
        return self._request("POST", f"/aquatics/emergencies/{emergency_id}/cancel", {}, headers)

    # ---- QuarantineRecord ----
    def create_quarantine(self, payload, headers):
        return self._request("POST", "/aquatics/quarantines", payload, headers)

    def get_quarantine(self, quarantine_id, headers):
        return self._request("GET", f"/aquatics/quarantines/{quarantine_id}", headers=headers)

    def list_quarantines_for_livestock(self, livestock_id, headers, params=None):
        return self._request("GET", f"/aquatics/livestock/{livestock_id}/quarantines", headers=headers, params=params)

    def list_quarantines_for_system(self, system_id, headers, params=None):
        return self._request("GET", f"/aquatics/systems/{system_id}/quarantines", headers=headers, params=params)

    def clear_quarantine(self, quarantine_id, headers):
        return self._request("POST", f"/aquatics/quarantines/{quarantine_id}/clear", {}, headers)

    def abort_quarantine(self, quarantine_id, headers):
        return self._request("POST", f"/aquatics/quarantines/{quarantine_id}/abort", {}, headers)

    # ---- RepairOrder ----
    def create_repair(self, payload, headers):
        return self._request("POST", "/aquatics/repairs", payload, headers)

    def get_repair(self, repair_id, headers):
        return self._request("GET", f"/aquatics/repairs/{repair_id}", headers=headers)

    def list_repairs_for_equipment(self, equipment_id, headers, params=None):
        return self._request("GET", f"/aquatics/equipment/{equipment_id}/repairs", headers=headers, params=params)

    def diagnose_repair(self, repair_id, headers):
        return self._request("POST", f"/aquatics/repairs/{repair_id}/diagnose", {}, headers)

    def order_parts_repair(self, repair_id, headers):
        return self._request("POST", f"/aquatics/repairs/{repair_id}/order-parts", {}, headers)

    def parts_arrived_repair(self, repair_id, headers):
        return self._request("POST", f"/aquatics/repairs/{repair_id}/parts-arrived", {}, headers)

    def close_repair(self, repair_id, headers):
        return self._request("POST", f"/aquatics/repairs/{repair_id}/close", {}, headers)

    def scrap_repair(self, repair_id, headers):
        return self._request("POST", f"/aquatics/repairs/{repair_id}/scrap", {}, headers)

    # ---- VacationFeedingPlan ----
    def create_feeding_plan(self, payload, headers):
        return self._request("POST", "/aquatics/feeding-plans", payload, headers)

    def get_feeding_plan(self, plan_id, headers):
        return self._request("GET", f"/aquatics/feeding-plans/{plan_id}", headers=headers)

    def list_feeding_plans_under_system(self, system_id, headers, params=None):
        return self._request("GET", f"/aquatics/systems/{system_id}/feeding-plans", headers=headers, params=params)

    def cancel_feeding_plan(self, plan_id, headers):
        return self._request("POST", f"/aquatics/feeding-plans/{plan_id}/cancel", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
