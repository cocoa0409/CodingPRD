"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Provider Sites ---
    def create_provider_site(self, payload, headers):
        return self._request("POST", "/provider-sites", payload, headers)

    def list_provider_sites(self, headers, params=None):
        return self._request("GET", "/provider-sites", headers=headers, params=params)

    def get_provider_site(self, site_id, headers):
        return self._request("GET", f"/provider-sites/{site_id}", headers=headers)

    def suspend_ordering(self, site_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/suspend-ordering", {}, headers)

    def reinstate_ordering(self, site_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/reinstate-ordering", {}, headers)

    def terminate_provider_site(self, site_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/terminate", {}, headers)

    # --- Storage Units ---
    def create_storage_unit(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/storage-units", payload, headers)

    def list_storage_units(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/storage-units", headers=headers, params=params)

    def get_storage_unit(self, unit_id, headers):
        return self._request("GET", f"/storage-units/{unit_id}", headers=headers)

    def list_all_storage_units(self, headers, params=None):
        return self._request("GET", "/storage-units", headers=headers, params=params)

    # --- Temperature Readings ---
    def record_temperature_reading(self, unit_id, payload, headers):
        return self._request("POST", f"/storage-units/{unit_id}/temperature-readings", payload, headers)

    def list_temperature_readings(self, unit_id, headers, params=None):
        return self._request("GET", f"/storage-units/{unit_id}/temperature-readings", headers=headers, params=params)

    def list_all_temperature_readings(self, headers, params=None):
        return self._request("GET", "/temperature-readings", headers=headers, params=params)

    # --- Temperature Excursions ---
    def list_excursions(self, unit_id, headers, params=None):
        return self._request("GET", f"/storage-units/{unit_id}/excursions", headers=headers, params=params)

    def get_excursion(self, unit_id, excursion_id, headers):
        return self._request("GET", f"/storage-units/{unit_id}/excursions/{excursion_id}", headers=headers)

    def begin_excursion_review(self, unit_id, excursion_id, headers):
        return self._request("POST", f"/storage-units/{unit_id}/excursions/{excursion_id}/begin-review", {}, headers)

    def resolve_excursion_viable(self, unit_id, excursion_id, payload, headers):
        return self._request("POST", f"/storage-units/{unit_id}/excursions/{excursion_id}/resolve-viable", payload, headers)

    def resolve_excursion_wasted(self, unit_id, excursion_id, payload, headers):
        return self._request("POST", f"/storage-units/{unit_id}/excursions/{excursion_id}/resolve-wasted", payload, headers)

    def list_all_excursions(self, headers, params=None):
        return self._request("GET", "/temperature-excursions", headers=headers, params=params)

    # --- Vaccine Products ---
    def create_vaccine_product(self, payload, headers):
        return self._request("POST", "/vaccine-products", payload, headers)

    def list_vaccine_products(self, headers, params=None):
        return self._request("GET", "/vaccine-products", headers=headers, params=params)

    def get_vaccine_product(self, product_id, headers):
        return self._request("GET", f"/vaccine-products/{product_id}", headers=headers)

    # --- Lots ---
    def create_lot(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/lots", payload, headers)

    def list_lots(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_all_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # --- Patients ---
    def create_patient(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/patients", payload, headers)

    def list_patients(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_all_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # --- Eligibility Screenings ---
    def create_eligibility_screening(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/eligibility-screenings", payload, headers)

    def list_eligibility_screenings(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/eligibility-screenings", headers=headers, params=params)

    def get_eligibility_screening(self, screening_id, headers):
        return self._request("GET", f"/eligibility-screenings/{screening_id}", headers=headers)

    def list_all_eligibility_screenings(self, headers, params=None):
        return self._request("GET", "/eligibility-screenings", headers=headers, params=params)

    # --- Dose Administrations ---
    def create_dose_administration(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/dose-administrations", payload, headers)

    def list_dose_administrations(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/dose-administrations", headers=headers, params=params)

    def get_dose_administration(self, dose_id, headers):
        return self._request("GET", f"/dose-administrations/{dose_id}", headers=headers)

    def submit_registry(self, site_id, dose_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/dose-administrations/{dose_id}/submit-registry", {}, headers)

    def mark_registry_rejected(self, site_id, dose_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/dose-administrations/{dose_id}/mark-registry-rejected", {}, headers)

    def reset_registry(self, site_id, dose_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/dose-administrations/{dose_id}/reset-registry", {}, headers)

    def list_all_dose_administrations(self, headers, params=None):
        return self._request("GET", "/dose-administrations", headers=headers, params=params)

    # --- Vaccine Orders ---
    def create_vaccine_order(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/vaccine-orders", payload, headers)

    def list_vaccine_orders(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/vaccine-orders", headers=headers, params=params)

    def get_vaccine_order(self, site_id, order_id, headers):
        return self._request("GET", f"/provider-sites/{site_id}/vaccine-orders/{order_id}", headers=headers)

    def add_order_line(self, site_id, order_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, site_id, order_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/lines", headers=headers, params=params)

    def submit_order(self, site_id, order_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/submit", {}, headers)

    def approve_order(self, site_id, order_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/approve", payload, headers)

    def cancel_order(self, site_id, order_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/cancel", {}, headers)

    def list_all_vaccine_orders(self, headers, params=None):
        return self._request("GET", "/vaccine-orders", headers=headers, params=params)

    # --- Order Lines (top-level) ---
    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    # --- Allocation Receipts ---
    def create_allocation_receipt(self, site_id, order_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/allocation-receipts", payload, headers)

    def list_allocation_receipts(self, site_id, order_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/vaccine-orders/{order_id}/allocation-receipts", headers=headers, params=params)

    def get_allocation_receipt(self, receipt_id, headers):
        return self._request("GET", f"/allocation-receipts/{receipt_id}", headers=headers)

    def list_all_allocation_receipts(self, headers, params=None):
        return self._request("GET", "/allocation-receipts", headers=headers, params=params)

    # --- Borrow Tickets ---
    def create_borrow_ticket(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/borrow-tickets", payload, headers)

    def list_borrow_tickets(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/borrow-tickets", headers=headers, params=params)

    def get_borrow_ticket(self, ticket_id, headers):
        return self._request("GET", f"/borrow-tickets/{ticket_id}", headers=headers)

    def record_payback(self, site_id, ticket_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/borrow-tickets/{ticket_id}/record-payback", payload, headers)

    def void_borrow_ticket(self, site_id, ticket_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/borrow-tickets/{ticket_id}/void", {}, headers)

    def list_all_borrow_tickets(self, headers, params=None):
        return self._request("GET", "/borrow-tickets", headers=headers, params=params)

    # --- Short-Date Transfers ---
    def create_short_date_transfer(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/short-date-transfers", payload, headers)

    def list_short_date_transfers(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/short-date-transfers", headers=headers, params=params)

    def get_short_date_transfer(self, transfer_id, headers):
        return self._request("GET", f"/short-date-transfers/{transfer_id}", headers=headers)

    def ship_transfer(self, site_id, transfer_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/short-date-transfers/{transfer_id}/ship", {}, headers)

    def receive_transfer(self, site_id, transfer_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/short-date-transfers/{transfer_id}/receive", {}, headers)

    def cancel_transfer(self, site_id, transfer_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/short-date-transfers/{transfer_id}/cancel", {}, headers)

    def list_all_short_date_transfers(self, headers, params=None):
        return self._request("GET", "/short-date-transfers", headers=headers, params=params)

    # --- Site Visit Audits ---
    def create_site_visit_audit(self, site_id, payload, headers):
        return self._request("POST", f"/provider-sites/{site_id}/site-visit-audits", payload, headers)

    def list_site_visit_audits(self, site_id, headers, params=None):
        return self._request("GET", f"/provider-sites/{site_id}/site-visit-audits", headers=headers, params=params)

    def get_site_visit_audit(self, audit_id, headers):
        return self._request("GET", f"/site-visit-audits/{audit_id}", headers=headers)

    def begin_audit(self, site_id, audit_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/site-visit-audits/{audit_id}/begin", {}, headers)

    def issue_findings(self, site_id, audit_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/site-visit-audits/{audit_id}/issue-findings", {}, headers)

    def close_audit_pass(self, site_id, audit_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/site-visit-audits/{audit_id}/close-pass", {}, headers)

    def close_audit_fail(self, site_id, audit_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/site-visit-audits/{audit_id}/close-fail", {}, headers)

    def cancel_audit(self, site_id, audit_id, headers):
        return self._request("POST", f"/provider-sites/{site_id}/site-visit-audits/{audit_id}/cancel", {}, headers)

    def list_all_site_visit_audits(self, headers, params=None):
        return self._request("GET", "/site-visit-audits", headers=headers, params=params)

    # --- Logical Clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
