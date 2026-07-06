"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Donor ----
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers=headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/donors", headers=headers, params=params)

    # ---- ScreeningApplication ----
    def create_screening_application(self, payload, headers):
        return self._request("POST", "/screening-applications", payload, headers=headers)

    def get_screening_application(self, app_id, headers):
        return self._request("GET", f"/screening-applications/{app_id}", headers=headers)

    def list_screening_applications(self, headers, params=None):
        return self._request("GET", "/screening-applications", headers=headers, params=params)

    def start_review(self, app_id, headers):
        return self._request("POST", f"/screening-applications/{app_id}/start-review", {}, headers=headers)

    def approve_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/screening-applications/{app_id}/approve", payload or {}, headers=headers)

    def defer_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/screening-applications/{app_id}/defer", payload or {}, headers=headers)

    # ---- Specimen ----
    def create_specimen(self, payload, headers):
        return self._request("POST", "/specimens", payload, headers=headers)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/specimens", headers=headers, params=params)

    def begin_quarantine(self, specimen_id, dewar_code, headers):
        return self._request("POST", f"/specimens/{specimen_id}/begin-quarantine",
                             {"dewar_code": dewar_code}, headers=headers)

    def release_quarantine(self, specimen_id, headers):
        return self._request("POST", f"/specimens/{specimen_id}/release-quarantine", {}, headers=headers)

    def discard_specimen(self, specimen_id, headers):
        return self._request("POST", f"/specimens/{specimen_id}/discard", {}, headers=headers)

    # ---- DonorInventory ----
    def get_donor_inventory(self, inventory_id, headers):
        return self._request("GET", f"/donor-inventories/{inventory_id}", headers=headers)

    def list_donor_inventories(self, headers, params=None):
        return self._request("GET", "/donor-inventories", headers=headers, params=params)

    # ---- Recipient ----
    def create_recipient(self, payload, headers):
        return self._request("POST", "/recipients", payload, headers=headers)

    def get_recipient(self, recipient_id, headers):
        return self._request("GET", f"/recipients/{recipient_id}", headers=headers)

    def list_recipients(self, headers, params=None):
        return self._request("GET", "/recipients", headers=headers, params=params)

    # ---- RecipientConsent ----
    def create_recipient_consent(self, payload, headers):
        return self._request("POST", "/recipient-consents", payload, headers=headers)

    def get_recipient_consent(self, consent_id, headers):
        return self._request("GET", f"/recipient-consents/{consent_id}", headers=headers)

    def list_recipient_consents(self, headers, params=None):
        return self._request("GET", "/recipient-consents", headers=headers, params=params)

    def sign_consent(self, consent_id, headers):
        return self._request("POST", f"/recipient-consents/{consent_id}/sign", {}, headers=headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/recipient-consents/{consent_id}/revoke", {}, headers=headers)

    # ---- VialReservation ----
    def create_vial_reservation(self, payload, headers):
        return self._request("POST", "/vial-reservations", payload, headers=headers)

    def get_vial_reservation(self, reservation_id, headers):
        return self._request("GET", f"/vial-reservations/{reservation_id}", headers=headers)

    def list_vial_reservations(self, headers, params=None):
        return self._request("GET", "/vial-reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/vial-reservations/{reservation_id}/confirm", {}, headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/vial-reservations/{reservation_id}/cancel", {}, headers=headers)

    def expire_reservation(self, reservation_id, headers):
        return self._request("POST", f"/vial-reservations/{reservation_id}/expire", {}, headers=headers)

    # ---- Shipment ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers=headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers=headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers=headers)

    # ---- StorageAccount / StorageInvoice ----
    def get_storage_account(self, account_id, headers):
        return self._request("GET", f"/storage-accounts/{account_id}", headers=headers)

    def list_storage_accounts(self, headers, params=None):
        return self._request("GET", "/storage-accounts", headers=headers, params=params)

    def assess_lapse(self, account_id, headers):
        return self._request("POST", f"/storage-accounts/{account_id}/assess-lapse", {}, headers=headers)

    def renew_account(self, account_id, headers):
        return self._request("POST", f"/storage-accounts/{account_id}/renew", {}, headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/storage-accounts/{account_id}/close", {}, headers=headers)

    def get_storage_invoice(self, invoice_id, headers):
        return self._request("GET", f"/storage-invoices/{invoice_id}", headers=headers)

    def list_storage_invoices(self, headers, params=None):
        return self._request("GET", "/storage-invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/storage-invoices/{invoice_id}/pay", {}, headers=headers)

    # ---- SiblingRegistry ----
    def create_sibling_registry_entry(self, payload, headers):
        return self._request("POST", "/sibling-registry", payload, headers=headers)

    def get_sibling_registry_entry(self, entry_id, headers):
        return self._request("GET", f"/sibling-registry/{entry_id}", headers=headers)

    def list_sibling_registry(self, headers, params=None):
        return self._request("GET", "/sibling-registry", headers=headers, params=params)

    def confirm_sibling_registry(self, entry_id, headers):
        return self._request("POST", f"/sibling-registry/{entry_id}/confirm", {}, headers=headers)

    def reject_sibling_registry(self, entry_id, headers):
        return self._request("POST", f"/sibling-registry/{entry_id}/reject", {}, headers=headers)

    # ---- CollectionAppointment ----
    def create_collection_appointment(self, payload, headers):
        return self._request("POST", "/collection-appointments", payload, headers=headers)

    def get_collection_appointment(self, appt_id, headers):
        return self._request("GET", f"/collection-appointments/{appt_id}", headers=headers)

    def list_collection_appointments(self, headers, params=None):
        return self._request("GET", "/collection-appointments", headers=headers, params=params)

    def complete_appointment(self, appt_id, headers):
        return self._request("POST", f"/collection-appointments/{appt_id}/complete", {}, headers=headers)

    def cancel_appointment(self, appt_id, headers):
        return self._request("POST", f"/collection-appointments/{appt_id}/cancel", {}, headers=headers)

    # ---- DewarMaintenanceWindow ----
    def create_dewar_maintenance_window(self, payload, headers):
        return self._request("POST", "/dewar-maintenance-windows", payload, headers=headers)

    def get_dewar_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/dewar-maintenance-windows/{window_id}", headers=headers)

    def list_dewar_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/dewar-maintenance-windows", headers=headers, params=params)

    def complete_maintenance(self, window_id, headers):
        return self._request("POST", f"/dewar-maintenance-windows/{window_id}/complete", {}, headers=headers)

    def cancel_maintenance(self, window_id, headers):
        return self._request("POST", f"/dewar-maintenance-windows/{window_id}/cancel", {}, headers=headers)

    # ---- RegulatoryReport ----
    def create_regulatory_report(self, payload, headers):
        return self._request("POST", "/regulatory-reports", payload, headers=headers)

    def get_regulatory_report(self, report_id, headers):
        return self._request("GET", f"/regulatory-reports/{report_id}", headers=headers)

    def list_regulatory_reports(self, headers, params=None):
        return self._request("GET", "/regulatory-reports", headers=headers, params=params)


api_client = ApiClient()
