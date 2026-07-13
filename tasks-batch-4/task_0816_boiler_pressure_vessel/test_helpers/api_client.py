"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Jurisdiction -----------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ----- InsuranceCompany -------------------------------------------------
    def create_insurance_company(self, payload, headers):
        return self._request("POST", "/insurance-companies", payload, headers)

    def list_insurance_companies(self, headers, params=None):
        return self._request("GET", "/insurance-companies", headers=headers, params=params)

    def get_insurance_company(self, insurance_company_id, headers):
        return self._request("GET", f"/insurance-companies/{insurance_company_id}", headers=headers)

    # ----- Owner ------------------------------------------------------------
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ----- Inspector --------------------------------------------------------
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def commission_inspector(self, inspector_id, headers):
        return self._request("POST", f"/inspectors/{inspector_id}/commission", {}, headers)

    def suspend_inspector(self, inspector_id, headers):
        return self._request("POST", f"/inspectors/{inspector_id}/suspend", {}, headers)

    # ----- Vessel -----------------------------------------------------------
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def register_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/register", {}, headers)

    def retire_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/retire", {}, headers)

    def reinstate_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/reinstate", {}, headers)

    def file_incident(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/incidents", payload, headers)

    # ----- InsurancePolicy --------------------------------------------------
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/cancel", {}, headers)

    def expire_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/expire", {}, headers)

    # ----- Inspection -------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/result", payload, headers)

    def raise_deficiency(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/deficiencies", payload, headers)

    def file_national_board_report(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/national-board-report", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", {}, headers)

    # ----- NationalBoardReport ----------------------------------------------
    def list_national_board_reports(self, headers, params=None):
        return self._request("GET", "/national-board-reports", headers=headers, params=params)

    def get_national_board_report(self, report_id, headers):
        return self._request("GET", f"/national-board-reports/{report_id}", headers=headers)

    # ----- Deficiency -------------------------------------------------------
    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    def reinspect_deficiency(self, deficiency_id, payload, headers):
        return self._request("POST", f"/deficiencies/{deficiency_id}/reinspect", payload, headers)

    def withdraw_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/deficiencies/{deficiency_id}/withdraw", {}, headers)

    # ----- RepairOrder ------------------------------------------------------
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def complete_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/complete", {}, headers)

    def cancel_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/cancel", {}, headers)

    # ----- FeeInvoice -------------------------------------------------------
    def create_fee_invoice(self, payload, headers):
        return self._request("POST", "/fee-invoices", payload, headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def get_fee_invoice(self, fee_invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{fee_invoice_id}", headers=headers)

    def pay_fee_invoice(self, fee_invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{fee_invoice_id}/pay", {}, headers)

    def refund_fee_invoice(self, fee_invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{fee_invoice_id}/refund", {}, headers)

    def void_fee_invoice(self, fee_invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{fee_invoice_id}/void", {}, headers)

    # ----- Certificate ------------------------------------------------------
    def create_certificate(self, payload, headers):
        return self._request("POST", "/certificates", payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def revoke_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/revoke", {}, headers)

    def expire_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/expire", {}, headers)

    # ----- IncidentReport ---------------------------------------------------
    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)


api_client = ApiClient()
