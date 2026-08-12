"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock & sweep ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_sweep(self, payload, headers):
        return self._request("POST", "/biobank/sweeps/process-due", payload, headers)

    # --- Donors ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/biobank/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/biobank/donors/{donor_id}", headers=headers)

    # --- Consent records ---
    def create_consent_record(self, donor_id, payload, headers):
        return self._request("POST", f"/biobank/donors/{donor_id}/consent-records", payload, headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/biobank/consent-records", headers=headers, params=params)

    def list_donor_consent_records(self, donor_id, headers):
        return self._request("GET", f"/biobank/donors/{donor_id}/consent-records", headers=headers)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/biobank/consent-records/{consent_id}", headers=headers)

    def withdraw_consent(self, consent_id, payload, headers):
        return self._request("POST", f"/biobank/consent-records/{consent_id}/withdraw", payload, headers)

    def rescind_withdrawal(self, consent_id, payload, headers):
        return self._request("POST", f"/biobank/consent-records/{consent_id}/rescind-withdrawal", payload, headers)

    def amend_consent(self, consent_id, payload, headers):
        return self._request("POST", f"/biobank/consent-records/{consent_id}/amendments", payload, headers)

    # --- Collection kits & custody ---
    def create_collection_kit(self, payload, headers):
        return self._request("POST", "/biobank/collection-kits", payload, headers)

    def list_collection_kits(self, headers, params=None):
        return self._request("GET", "/biobank/collection-kits", headers=headers, params=params)

    def get_collection_kit(self, kit_id, headers):
        return self._request("GET", f"/biobank/collection-kits/{kit_id}", headers=headers)

    def distribute_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/biobank/collection-kits/{kit_id}/distribute", payload, headers)

    def receive_return_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/biobank/collection-kits/{kit_id}/receive-return", payload, headers)

    def list_custody_events(self, kit_id, headers):
        return self._request("GET", f"/biobank/collection-kits/{kit_id}/custody-events", headers=headers)

    # --- Specimens ---
    def create_specimen(self, payload, headers):
        return self._request("POST", "/biobank/specimens", payload, headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/biobank/specimens", headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/biobank/specimens/{specimen_id}", headers=headers)

    # --- Aliquots ---
    def create_aliquot(self, specimen_id, payload, headers):
        return self._request("POST", f"/biobank/specimens/{specimen_id}/aliquots", payload, headers)

    def list_specimen_aliquots(self, specimen_id, headers):
        return self._request("GET", f"/biobank/specimens/{specimen_id}/aliquots", headers=headers)

    def list_aliquots(self, headers, params=None):
        return self._request("GET", "/biobank/aliquots", headers=headers, params=params)

    def get_aliquot(self, aliquot_id, headers):
        return self._request("GET", f"/biobank/aliquots/{aliquot_id}", headers=headers)

    def void_aliquot(self, aliquot_id, payload, headers):
        return self._request("POST", f"/biobank/aliquots/{aliquot_id}/void", payload, headers)

    def checkout_aliquot(self, aliquot_id, payload, headers):
        return self._request("POST", f"/biobank/aliquots/{aliquot_id}/checkout", payload, headers)

    # --- Storage ---
    def create_storage_unit(self, payload, headers):
        return self._request("POST", "/biobank/storage-units", payload, headers)

    def get_storage_unit(self, unit_id, headers):
        return self._request("GET", f"/biobank/storage-units/{unit_id}", headers=headers)

    def create_storage_slot(self, unit_id, payload, headers):
        return self._request("POST", f"/biobank/storage-units/{unit_id}/slots", payload, headers)

    def list_storage_slots(self, unit_id, headers):
        return self._request("GET", f"/biobank/storage-units/{unit_id}/slots", headers=headers)

    def get_storage_slot(self, slot_id, headers):
        return self._request("GET", f"/biobank/storage-slots/{slot_id}", headers=headers)

    def create_slot_reservation(self, slot_id, payload, headers):
        return self._request("POST", f"/biobank/storage-slots/{slot_id}/reservations", payload, headers)

    def list_slot_reservations(self, slot_id, headers):
        return self._request("GET", f"/biobank/storage-slots/{slot_id}/reservations", headers=headers)

    def create_temperature_reading(self, unit_id, payload, headers):
        return self._request("POST", f"/biobank/storage-units/{unit_id}/temperature-readings", payload, headers)

    def list_temperature_readings(self, unit_id, headers):
        return self._request("GET", f"/biobank/storage-units/{unit_id}/temperature-readings", headers=headers)

    def declare_failure(self, unit_id, payload, headers):
        return self._request("POST", f"/biobank/storage-units/{unit_id}/declare-failure", payload, headers)

    def return_to_service(self, unit_id, payload, headers):
        return self._request("POST", f"/biobank/storage-units/{unit_id}/return-to-service", payload, headers)

    # --- Sample requests & committee review ---
    def create_sample_request(self, payload, headers):
        return self._request("POST", "/biobank/sample-requests", payload, headers)

    def list_sample_requests(self, headers, params=None):
        return self._request("GET", "/biobank/sample-requests", headers=headers, params=params)

    def get_sample_request(self, request_id, headers):
        return self._request("GET", f"/biobank/sample-requests/{request_id}", headers=headers)

    def submit_sample_request(self, request_id, payload, headers):
        return self._request("POST", f"/biobank/sample-requests/{request_id}/submit", payload, headers)

    def cast_vote(self, request_id, payload, headers):
        return self._request("POST", f"/biobank/sample-requests/{request_id}/votes", payload, headers)

    def list_votes(self, request_id, headers):
        return self._request("GET", f"/biobank/sample-requests/{request_id}/votes", headers=headers)

    def request_revision(self, request_id, payload, headers):
        return self._request("POST", f"/biobank/sample-requests/{request_id}/request-revision", payload, headers)

    def fulfill_sample_request(self, request_id, payload, headers):
        return self._request("POST", f"/biobank/sample-requests/{request_id}/fulfill", payload, headers)

    def cancel_sample_request(self, request_id, payload, headers):
        return self._request("POST", f"/biobank/sample-requests/{request_id}/cancel", payload, headers)

    # --- Sharing agreements ---
    def create_sharing_agreement(self, payload, headers):
        return self._request("POST", "/biobank/sharing-agreements", payload, headers)

    def get_sharing_agreement(self, agreement_id, headers):
        return self._request("GET", f"/biobank/sharing-agreements/{agreement_id}", headers=headers)

    def activate_sharing_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/biobank/sharing-agreements/{agreement_id}/activate", payload, headers)

    def terminate_sharing_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/biobank/sharing-agreements/{agreement_id}/terminate", payload, headers)

    # --- De-identification keys & access grants ---
    def create_deidentification_key(self, payload, headers):
        return self._request("POST", "/biobank/deidentification-keys", payload, headers)

    def list_deidentification_keys(self, headers, params=None):
        return self._request("GET", "/biobank/deidentification-keys", headers=headers, params=params)

    def get_deidentification_key(self, key_id, headers):
        return self._request("GET", f"/biobank/deidentification-keys/{key_id}", headers=headers)

    def create_key_access_grant(self, key_id, payload, headers):
        return self._request("POST", f"/biobank/deidentification-keys/{key_id}/grants", payload, headers)

    def list_key_access_grants(self, key_id, headers):
        return self._request("GET", f"/biobank/deidentification-keys/{key_id}/grants", headers=headers)

    def reveal_key(self, key_id, payload, headers):
        return self._request("POST", f"/biobank/deidentification-keys/{key_id}/reveal", payload, headers)

    # --- Destruction orders ---
    def create_destruction_order(self, payload, headers):
        return self._request("POST", "/biobank/destruction-orders", payload, headers)

    def list_destruction_orders(self, headers, params=None):
        return self._request("GET", "/biobank/destruction-orders", headers=headers, params=params)

    def get_destruction_order(self, order_id, headers):
        return self._request("GET", f"/biobank/destruction-orders/{order_id}", headers=headers)

    def confirm_destruction_order(self, order_id, payload, headers):
        return self._request("POST", f"/biobank/destruction-orders/{order_id}/confirm-execution", payload, headers)


api_client = ApiClient()
