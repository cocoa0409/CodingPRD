"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/reuse/_clock/set_current_utc", payload, headers)

    # --- Donors ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/reuse/donors", payload, headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/reuse/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/reuse/donors/{donor_id}", headers=headers)

    def update_donor(self, donor_id, payload, headers):
        return self._request("PATCH", f"/reuse/donors/{donor_id}", payload, headers)

    # --- Categories ---
    def create_category(self, payload, headers):
        return self._request("POST", "/reuse/categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/reuse/categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/reuse/categories/{category_id}", headers=headers)

    def update_category(self, category_id, payload, headers):
        return self._request("PATCH", f"/reuse/categories/{category_id}", payload, headers)

    # --- Donation offers ---
    def create_donation_offer(self, payload, headers):
        return self._request("POST", "/reuse/donation-offers", payload, headers)

    def list_donation_offers(self, headers, params=None):
        return self._request("GET", "/reuse/donation-offers", headers=headers, params=params)

    def get_donation_offer(self, offer_id, headers):
        return self._request("GET", f"/reuse/donation-offers/{offer_id}", headers=headers)

    def review_offer(self, offer_id, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/review", {}, headers)

    def request_info_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/request-info", payload, headers)

    def resubmit_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/resubmit", payload, headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/accept", {}, headers)

    def reject_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/reject", payload, headers)

    def receive_offer(self, offer_id, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/receive", {}, headers)

    def cancel_offer(self, offer_id, headers):
        return self._request("POST", f"/reuse/donation-offers/{offer_id}/cancel", {}, headers)

    # --- Deconstruction jobs ---
    def create_deconstruction_job(self, payload, headers):
        return self._request("POST", "/reuse/deconstruction-jobs", payload, headers)

    def list_deconstruction_jobs(self, headers, params=None):
        return self._request("GET", "/reuse/deconstruction-jobs", headers=headers, params=params)

    def get_deconstruction_job(self, job_id, headers):
        return self._request("GET", f"/reuse/deconstruction-jobs/{job_id}", headers=headers)

    def request_screening(self, job_id, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/request-screening", {}, headers)

    def schedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/schedule", payload, headers)

    def start_job(self, job_id, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/start", {}, headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/complete", {}, headers)

    def begin_remediation(self, job_id, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/begin-remediation", {}, headers)

    def complete_remediation(self, job_id, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/complete-remediation", {}, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/reuse/deconstruction-jobs/{job_id}/cancel", {}, headers)

    # --- Hazmat screenings ---
    def create_hazmat_screening(self, payload, headers):
        return self._request("POST", "/reuse/hazmat-screenings", payload, headers)

    def list_hazmat_screenings(self, headers, params=None):
        return self._request("GET", "/reuse/hazmat-screenings", headers=headers, params=params)

    def get_hazmat_screening(self, screening_id, headers):
        return self._request("GET", f"/reuse/hazmat-screenings/{screening_id}", headers=headers)

    # --- Salvage batches ---
    def create_salvage_batch(self, payload, headers):
        return self._request("POST", "/reuse/salvage-batches", payload, headers)

    def list_salvage_batches(self, headers, params=None):
        return self._request("GET", "/reuse/salvage-batches", headers=headers, params=params)

    def get_salvage_batch(self, batch_id, headers):
        return self._request("GET", f"/reuse/salvage-batches/{batch_id}", headers=headers)

    def weigh_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/reuse/salvage-batches/{batch_id}/weigh", payload, headers)

    def quarantine_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/reuse/salvage-batches/{batch_id}/quarantine", payload, headers)

    def resolve_quarantine(self, batch_id, payload, headers):
        return self._request("POST", f"/reuse/salvage-batches/{batch_id}/resolve-quarantine", payload, headers)

    def mark_batch_sorted(self, batch_id, headers):
        return self._request("POST", f"/reuse/salvage-batches/{batch_id}/mark-sorted", {}, headers)

    # --- Items ---
    def create_item(self, payload, headers):
        return self._request("POST", "/reuse/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/reuse/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/reuse/items/{item_id}", headers=headers)

    def price_item(self, item_id, payload, headers):
        return self._request("POST", f"/reuse/items/{item_id}/price", payload, headers)

    def place_item(self, item_id, payload, headers):
        return self._request("POST", f"/reuse/items/{item_id}/place", payload, headers)

    def unplace_item(self, item_id, headers):
        return self._request("POST", f"/reuse/items/{item_id}/unplace", {}, headers)

    def dispose_item(self, item_id, payload, headers):
        return self._request("POST", f"/reuse/items/{item_id}/dispose", payload, headers)

    def split_item(self, item_id, payload, headers):
        return self._request("POST", f"/reuse/items/{item_id}/split", payload, headers)

    # --- Store zones ---
    def create_store_zone(self, payload, headers):
        return self._request("POST", "/reuse/store-zones", payload, headers)

    def list_store_zones(self, headers, params=None):
        return self._request("GET", "/reuse/store-zones", headers=headers, params=params)

    def get_store_zone(self, zone_id, headers):
        return self._request("GET", f"/reuse/store-zones/{zone_id}", headers=headers)

    def update_store_zone(self, zone_id, payload, headers):
        return self._request("PATCH", f"/reuse/store-zones/{zone_id}", payload, headers)

    # --- Markdown runs ---
    def create_markdown_run(self, payload, headers):
        return self._request("POST", "/reuse/markdown-runs", payload, headers)

    def list_markdown_runs(self, headers, params=None):
        return self._request("GET", "/reuse/markdown-runs", headers=headers, params=params)

    def get_markdown_run(self, run_id, headers):
        return self._request("GET", f"/reuse/markdown-runs/{run_id}", headers=headers)

    # --- Contractor accounts ---
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/reuse/contractor-accounts", payload, headers)

    def list_contractor_accounts(self, headers, params=None):
        return self._request("GET", "/reuse/contractor-accounts", headers=headers, params=params)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/reuse/contractor-accounts/{account_id}", headers=headers)

    def approve_account(self, account_id, headers):
        return self._request("POST", f"/reuse/contractor-accounts/{account_id}/approve", {}, headers)

    def suspend_account(self, account_id, payload, headers):
        return self._request("POST", f"/reuse/contractor-accounts/{account_id}/suspend", payload, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/reuse/contractor-accounts/{account_id}/reinstate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/reuse/contractor-accounts/{account_id}/close", {}, headers)

    def record_payment(self, account_id, payload, headers):
        return self._request("POST", f"/reuse/contractor-accounts/{account_id}/payments", payload, headers)

    # --- Bulk purchase agreements ---
    def create_bulk_agreement(self, payload, headers):
        return self._request("POST", "/reuse/bulk-agreements", payload, headers)

    def list_bulk_agreements(self, headers, params=None):
        return self._request("GET", "/reuse/bulk-agreements", headers=headers, params=params)

    def get_bulk_agreement(self, agreement_id, headers):
        return self._request("GET", f"/reuse/bulk-agreements/{agreement_id}", headers=headers)

    def cancel_bulk_agreement(self, agreement_id, headers):
        return self._request("POST", f"/reuse/bulk-agreements/{agreement_id}/cancel", {}, headers)

    # --- Sales ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/reuse/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/reuse/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/reuse/sales/{sale_id}", headers=headers)

    def add_sale_line(self, sale_id, payload, headers):
        return self._request("POST", f"/reuse/sales/{sale_id}/lines", payload, headers)

    def list_sale_lines(self, headers, params=None):
        return self._request("GET", "/reuse/sale-lines", headers=headers, params=params)

    def get_sale_line(self, line_id, headers):
        return self._request("GET", f"/reuse/sale-lines/{line_id}", headers=headers)

    def delete_sale_line(self, line_id, headers):
        return self._request("DELETE", f"/reuse/sale-lines/{line_id}", headers=headers)

    def finalize_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/reuse/sales/{sale_id}/finalize", payload, headers)

    def void_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/reuse/sales/{sale_id}/void", payload, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"/reuse/sales/{sale_id}/cancel", {}, headers)

    # --- Tax receipts ---
    def create_tax_receipt(self, payload, headers):
        return self._request("POST", "/reuse/tax-receipts", payload, headers)

    def list_tax_receipts(self, headers, params=None):
        return self._request("GET", "/reuse/tax-receipts", headers=headers, params=params)

    def get_tax_receipt(self, receipt_id, headers):
        return self._request("GET", f"/reuse/tax-receipts/{receipt_id}", headers=headers)

    def issue_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/reuse/tax-receipts/{receipt_id}/issue", payload, headers)

    def request_void_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/reuse/tax-receipts/{receipt_id}/request-void", payload, headers)

    def confirm_void_receipt(self, receipt_id, headers):
        return self._request("POST", f"/reuse/tax-receipts/{receipt_id}/confirm-void", {}, headers)

    def reject_void_receipt(self, receipt_id, headers):
        return self._request("POST", f"/reuse/tax-receipts/{receipt_id}/reject-void", {}, headers)

    def amend_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/reuse/tax-receipts/{receipt_id}/amend", payload, headers)

    # --- Crew members ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/reuse/crew-members", payload, headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/reuse/crew-members", headers=headers, params=params)

    def get_crew_member(self, member_id, headers):
        return self._request("GET", f"/reuse/crew-members/{member_id}", headers=headers)

    def update_crew_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/reuse/crew-members/{member_id}", payload, headers)

    # --- Crew assignments ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/reuse/crew-assignments", payload, headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/reuse/crew-assignments", headers=headers, params=params)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/reuse/crew-assignments/{assignment_id}", headers=headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/reuse/crew-assignments/{assignment_id}/complete", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/reuse/crew-assignments/{assignment_id}/cancel", {}, headers)

    def mark_assignment_no_show(self, assignment_id, headers):
        return self._request("POST", f"/reuse/crew-assignments/{assignment_id}/mark-no-show", {}, headers)

    # --- Vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/reuse/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/reuse/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/reuse/vehicles/{vehicle_id}", headers=headers)

    def update_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/reuse/vehicles/{vehicle_id}", payload, headers)

    # --- Pickup appointments ---
    def create_pickup_appointment(self, payload, headers):
        return self._request("POST", "/reuse/pickup-appointments", payload, headers)

    def list_pickup_appointments(self, headers, params=None):
        return self._request("GET", "/reuse/pickup-appointments", headers=headers, params=params)

    def get_pickup_appointment(self, appointment_id, headers):
        return self._request("GET", f"/reuse/pickup-appointments/{appointment_id}", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/reuse/pickup-appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/reuse/pickup-appointments/{appointment_id}/cancel", {}, headers)

    def mark_appointment_no_show(self, appointment_id, headers):
        return self._request("POST", f"/reuse/pickup-appointments/{appointment_id}/mark-no-show", {}, headers)

    # --- Diversion reports ---
    def create_diversion_report(self, payload, headers):
        return self._request("POST", "/reuse/diversion-reports", payload, headers)

    def list_diversion_reports(self, headers, params=None):
        return self._request("GET", "/reuse/diversion-reports", headers=headers, params=params)

    def get_diversion_report(self, report_id, headers):
        return self._request("GET", f"/reuse/diversion-reports/{report_id}", headers=headers)

    def close_diversion_report(self, report_id, headers):
        return self._request("POST", f"/reuse/diversion-reports/{report_id}/close", {}, headers)


api_client = ApiClient()
