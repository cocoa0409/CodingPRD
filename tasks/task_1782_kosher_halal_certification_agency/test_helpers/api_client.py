"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # AgencyClient
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/api/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/api/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}", headers=headers)

    def submit_application(self, client_id, headers):
        return self._request("POST", f"/api/clients/{client_id}/submit-application",
                             {}, headers)

    def withdraw_client(self, client_id, headers):
        return self._request("POST", f"/api/clients/{client_id}/withdraw", {}, headers)

    def terminate_client(self, client_id, headers):
        return self._request("POST", f"/api/clients/{client_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Facility
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/api/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/api/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/api/facilities/{facility_id}", headers=headers)

    def approve_facility(self, facility_id, headers):
        return self._request("POST", f"/api/facilities/{facility_id}/approve",
                             {}, headers)

    def suspend_facility(self, facility_id, headers):
        return self._request("POST", f"/api/facilities/{facility_id}/suspend",
                             {}, headers)

    def reinstate_facility(self, facility_id, headers):
        return self._request("POST", f"/api/facilities/{facility_id}/reinstate",
                             {}, headers)

    def decommission_facility(self, facility_id, headers):
        return self._request("POST", f"/api/facilities/{facility_id}/decommission",
                             {}, headers)

    # ------------------------------------------------------------------
    # EquipmentLine
    # ------------------------------------------------------------------
    def create_equipment_line(self, payload, headers):
        return self._request("POST", "/api/equipment-lines", payload, headers)

    def get_equipment_line(self, line_id, headers):
        return self._request("GET", f"/api/equipment-lines/{line_id}", headers=headers)

    def list_equipment_lines(self, facility_id, headers, params=None):
        return self._request("GET", f"/api/facilities/{facility_id}/equipment-lines",
                             headers=headers, params=params)

    def assess_equipment_line(self, line_id, dedication_status, headers):
        return self._request("POST", f"/api/equipment-lines/{line_id}/assess",
                             {"dedication_status": dedication_status}, headers)

    def record_kosherization_event(self, line_id, headers):
        return self._request("POST",
                             f"/api/equipment-lines/{line_id}/kosherization-events",
                             {}, headers)

    def report_compromise(self, line_id, headers):
        return self._request("POST",
                             f"/api/equipment-lines/{line_id}/report-compromise",
                             {}, headers)

    # ------------------------------------------------------------------
    # Ingredient
    # ------------------------------------------------------------------
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/api/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/api/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/api/ingredients/{ingredient_id}", headers=headers)

    def list_ingredient_usages(self, ingredient_id, headers, params=None):
        return self._request("GET",
                             f"/api/ingredients/{ingredient_id}/product-usages",
                             headers=headers, params=params)

    def start_ingredient_review(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/start-review",
                             {}, headers)

    def approve_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/approve",
                             {}, headers)

    def reject_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/reject",
                             {}, headers)

    def file_change_notice(self, ingredient_id, change_summary, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/change-notices",
                             {"change_summary": change_summary}, headers)

    def resubmit_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/resubmit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Product / ProductIngredient
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/api/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    def list_product_ingredients(self, product_id, headers, params=None):
        return self._request("GET", f"/api/products/{product_id}/ingredients",
                             headers=headers, params=params)

    def list_product_certificate_listings(self, product_id, headers, params=None):
        return self._request("GET",
                             f"/api/products/{product_id}/certificate-listings",
                             headers=headers, params=params)

    def add_product_ingredient(self, product_id, ingredient_id, headers):
        return self._request("POST", f"/api/products/{product_id}/ingredients",
                             {"ingredient_id": ingredient_id}, headers)

    def delete_product_ingredient(self, junction_id, headers):
        return self._request("DELETE", f"/api/product-ingredients/{junction_id}",
                             headers=headers)

    def submit_product_review(self, product_id, headers):
        return self._request("POST", f"/api/products/{product_id}/submit-review",
                             {}, headers)

    def certify_product_eligible(self, product_id, headers):
        return self._request("POST", f"/api/products/{product_id}/certify-eligible",
                             {}, headers)

    def withdraw_product(self, product_id, headers):
        return self._request("POST", f"/api/products/{product_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # SupervisionVisit
    # ------------------------------------------------------------------
    def create_visit(self, payload, headers):
        return self._request("POST", "/api/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/api/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/api/visits/{visit_id}", headers=headers)

    def list_facility_visits(self, facility_id, headers, params=None):
        return self._request("GET", f"/api/facilities/{facility_id}/visits",
                             headers=headers, params=params)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/complete", {}, headers)

    def no_access_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/no-access", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # InspectionFinding
    # ------------------------------------------------------------------
    def create_finding(self, visit_id, payload, headers):
        return self._request("POST", f"/api/visits/{visit_id}/findings",
                             payload, headers)

    def list_visit_findings(self, visit_id, headers, params=None):
        return self._request("GET", f"/api/visits/{visit_id}/findings",
                             headers=headers, params=params)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/api/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/api/findings/{finding_id}", headers=headers)

    def submit_remediation(self, finding_id, remediation_notes, headers):
        return self._request("POST", f"/api/findings/{finding_id}/submit-remediation",
                             {"remediation_notes": remediation_notes}, headers)

    def verify_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/api/findings/{finding_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # CertificationAgreement
    # ------------------------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/api/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/api/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/agreements/{agreement_id}/activate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def record_payment(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/record-payment",
                             {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Certificate / CertificateProduct
    # ------------------------------------------------------------------
    def create_certificate(self, payload, headers):
        return self._request("POST", "/api/certificates", payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/api/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/api/certificates/{certificate_id}",
                             headers=headers)

    def list_certificate_products(self, certificate_id, headers, params=None):
        return self._request("GET", f"/api/certificates/{certificate_id}/products",
                             headers=headers, params=params)

    def issue_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/issue",
                             {}, headers)

    def add_certificate_products(self, certificate_id, product_ids, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/products",
                             {"product_ids": product_ids}, headers)

    def delete_certificate_product(self, entry_id, headers):
        return self._request("DELETE", f"/api/certificate-products/{entry_id}",
                             headers=headers)

    def suspend_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/suspend",
                             {}, headers)

    def reinstate_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/reinstate",
                             {}, headers)

    def revoke_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/revoke",
                             {}, headers)

    def renew_certificate(self, certificate_id, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/renew",
                             {}, headers)

    # ------------------------------------------------------------------
    # HolidayProductionWindow
    # ------------------------------------------------------------------
    def create_holiday_window(self, payload, headers):
        return self._request("POST", "/api/holiday-windows", payload, headers)

    def get_holiday_window(self, window_id, headers):
        return self._request("GET", f"/api/holiday-windows/{window_id}",
                             headers=headers)

    def list_facility_holiday_windows(self, facility_id, headers, params=None):
        return self._request("GET", f"/api/facilities/{facility_id}/holiday-windows",
                             headers=headers, params=params)

    def confirm_holiday_window(self, window_id, assigned_supervisor_id, headers):
        return self._request("POST", f"/api/holiday-windows/{window_id}/confirm",
                             {"assigned_supervisor_id": assigned_supervisor_id},
                             headers)

    def complete_holiday_window(self, window_id, headers):
        return self._request("POST", f"/api/holiday-windows/{window_id}/complete",
                             {}, headers)

    def cancel_holiday_window(self, window_id, headers):
        return self._request("POST", f"/api/holiday-windows/{window_id}/cancel",
                             {}, headers)


api_client = ApiClient()
