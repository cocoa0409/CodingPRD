"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/locker/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/locker/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/locker/customers/{customer_id}", headers=headers)

    # ---- capacity days ----
    def create_capacity_day(self, payload, headers):
        return self._request("POST", "/locker/capacity-days", payload, headers)

    def list_capacity_days(self, headers, params=None):
        return self._request("GET", "/locker/capacity-days", headers=headers, params=params)

    # ---- appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/locker/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/locker/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/locker/appointments/{appointment_id}", headers=headers)

    def pay_deposit(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/locker/appointments/{appointment_id}/pay-deposit", payload, headers
        )

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/locker/appointments/{appointment_id}/cancel", payload or {}, headers
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/locker/appointments/{appointment_id}/reschedule", payload, headers
        )

    def mark_no_show(self, appointment_id, headers):
        return self._request(
            "POST", f"/locker/appointments/{appointment_id}/no-show", {}, headers
        )

    def list_appointment_animals(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/locker/appointments/{appointment_id}/animals",
            headers=headers, params=params,
        )

    # ---- animals ----
    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/locker/animals/{animal_id}", headers=headers)

    def receive_animal(self, animal_id, payload, headers):
        return self._request(
            "POST", f"/locker/animals/{animal_id}/receive", payload, headers
        )

    def slaughter_animal(self, animal_id, headers):
        return self._request("POST", f"/locker/animals/{animal_id}/slaughter", {}, headers)

    def weigh_animal(self, animal_id, payload, headers):
        return self._request("POST", f"/locker/animals/{animal_id}/weigh", payload, headers)

    def start_fabrication(self, animal_id, headers):
        return self._request(
            "POST", f"/locker/animals/{animal_id}/start-fabrication", {}, headers
        )

    def complete_fabrication(self, animal_id, headers):
        return self._request(
            "POST", f"/locker/animals/{animal_id}/complete-fabrication", {}, headers
        )

    # ---- shares ----
    def add_share(self, animal_id, payload, headers):
        return self._request("POST", f"/locker/animals/{animal_id}/shares", payload, headers)

    def finalize_shares(self, animal_id, headers):
        return self._request(
            "POST", f"/locker/animals/{animal_id}/shares/finalize", {}, headers
        )

    def list_shares(self, headers, params=None):
        return self._request("GET", "/locker/shares", headers=headers, params=params)

    def get_share(self, share_id, headers):
        return self._request("GET", f"/locker/shares/{share_id}", headers=headers)

    def delete_share(self, share_id, headers):
        return self._request("DELETE", f"/locker/shares/{share_id}", headers=headers)

    # ---- cut sheets ----
    def create_cut_sheet(self, share_id, payload, headers):
        return self._request("POST", f"/locker/shares/{share_id}/cut-sheet", payload, headers)

    def list_cut_sheets(self, headers, params=None):
        return self._request("GET", "/locker/cut-sheets", headers=headers, params=params)

    def get_cut_sheet(self, cut_sheet_id, headers):
        return self._request("GET", f"/locker/cut-sheets/{cut_sheet_id}", headers=headers)

    def submit_cut_sheet(self, cut_sheet_id, headers):
        return self._request("POST", f"/locker/cut-sheets/{cut_sheet_id}/submit", {}, headers)

    def revise_cut_sheet(self, cut_sheet_id, payload, headers):
        return self._request(
            "POST", f"/locker/cut-sheets/{cut_sheet_id}/revise", payload, headers
        )

    # ---- invoices ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/locker/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/locker/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/locker/invoices/{invoice_id}/payments", payload, headers
        )

    def waive_storage(self, invoice_id, headers):
        return self._request(
            "POST", f"/locker/invoices/{invoice_id}/waive-storage", {}, headers
        )

    # ---- storage records ----
    def list_storage_records(self, headers, params=None):
        return self._request("GET", "/locker/storage-records", headers=headers, params=params)

    def get_storage_record(self, record_id, headers):
        return self._request("GET", f"/locker/storage-records/{record_id}", headers=headers)

    def pickup_storage_record(self, record_id, headers):
        return self._request(
            "POST", f"/locker/storage-records/{record_id}/pickup", {}, headers
        )

    # ---- labels ----
    def list_labels(self, headers, params=None):
        return self._request("GET", "/locker/labels", headers=headers, params=params)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/locker/labels/{label_id}", headers=headers)

    def approve_label(self, label_id, headers):
        return self._request("POST", f"/locker/labels/{label_id}/approve", {}, headers)

    # ---- ops + logical clock ----
    def run_daily(self, headers):
        return self._request("POST", "/locker/ops/run-daily", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
