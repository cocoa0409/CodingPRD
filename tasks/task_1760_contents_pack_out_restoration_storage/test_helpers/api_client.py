"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- PackOutJob ----
    def create_pack_out_job(self, payload, headers):
        return self._request("POST", "/api/pack-out-jobs", payload, headers)

    def get_pack_out_job(self, job_id, headers):
        return self._request("GET", f"/api/pack-out-jobs/{job_id}", headers=headers)

    def transition_pack_out_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/pack-out-jobs/{job_id}/transition", payload, headers)

    # ---- Room ----
    def create_room(self, job_id, payload, headers):
        return self._request("POST", f"/api/pack-out-jobs/{job_id}/rooms", payload, headers)

    def list_rooms(self, job_id, headers, params=None):
        return self._request("GET", f"/api/pack-out-jobs/{job_id}/rooms", headers=headers, params=params)

    # ---- Item ----
    def create_item(self, room_id, payload, headers):
        return self._request("POST", f"/api/rooms/{room_id}/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/api/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}", headers=headers)

    def triage_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/triage", payload, headers)

    # ---- DisposalRecord ----
    def get_disposal_record(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}/disposal-record", headers=headers)

    def transition_disposal_record(self, record_id, payload, headers):
        return self._request("POST", f"/api/disposal-records/{record_id}/transition", payload, headers)

    # ---- CleaningTask ----
    def create_cleaning_task(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/cleaning-tasks", payload, headers)

    def list_cleaning_tasks(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}/cleaning-tasks", headers=headers)

    def transition_cleaning_task(self, task_id, payload, headers):
        return self._request("POST", f"/api/cleaning-tasks/{task_id}/transition", payload, headers)

    # ---- Vault ----
    def create_vault(self, payload, headers):
        return self._request("POST", "/api/vaults", payload, headers)

    def get_vault(self, vault_id, headers):
        return self._request("GET", f"/api/vaults/{vault_id}", headers=headers)

    # ---- StoragePlacement ----
    def create_placement(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/placements", payload, headers)

    def list_item_placements(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}/placements", headers=headers)

    def list_vault_placements(self, vault_id, headers):
        return self._request("GET", f"/api/vaults/{vault_id}/placements", headers=headers)

    def release_placement(self, placement_id, headers):
        return self._request("POST", f"/api/storage-placements/{placement_id}/release", {}, headers)

    # ---- Subcontractor ----
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/api/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request("GET", f"/api/subcontractors/{subcontractor_id}", headers=headers)

    # ---- SpecialtyReferral + CustodyEvent ----
    def create_specialty_referral(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/specialty-referrals", payload, headers)

    def list_specialty_referrals(self, headers, params=None):
        return self._request("GET", "/api/specialty-referrals", headers=headers, params=params)

    def get_specialty_referral(self, referral_id, headers):
        return self._request("GET", f"/api/specialty-referrals/{referral_id}", headers=headers)

    def transition_specialty_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/api/specialty-referrals/{referral_id}/transition", payload, headers)

    def create_custody_event(self, referral_id, payload, headers):
        return self._request("POST", f"/api/specialty-referrals/{referral_id}/custody-events", payload, headers)

    def list_custody_events(self, referral_id, headers):
        return self._request("GET", f"/api/specialty-referrals/{referral_id}/custody-events", headers=headers)

    # ---- HandlingClaim ----
    def create_handling_claim(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/handling-claims", payload, headers)

    def list_item_claims(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}/handling-claims", headers=headers)

    def list_invoice_claims(self, invoice_id, headers):
        return self._request("GET", f"/api/carrier-invoices/{invoice_id}/handling-claims", headers=headers)

    def transition_handling_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/handling-claims/{claim_id}/transition", payload, headers)

    # ---- PackBackSchedule ----
    def create_pack_back_schedule(self, job_id, payload, headers):
        return self._request("POST", f"/api/pack-out-jobs/{job_id}/pack-back-schedules", payload, headers)

    def list_pack_back_schedules(self, job_id, headers):
        return self._request("GET", f"/api/pack-out-jobs/{job_id}/pack-back-schedules", headers=headers)

    def transition_pack_back_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/api/pack-back-schedules/{schedule_id}/transition", payload, headers)

    # ---- StorageStatement / billing ----
    def create_storage_statement(self, job_id, payload, headers):
        return self._request("POST", f"/api/pack-out-jobs/{job_id}/storage-statements", payload, headers)

    def list_storage_statements(self, headers, params=None):
        return self._request("GET", "/api/storage-statements", headers=headers, params=params)

    def get_storage_statement(self, statement_id, headers):
        return self._request("GET", f"/api/storage-statements/{statement_id}", headers=headers)

    def run_billing(self, headers):
        return self._request("POST", "/api/billing-runs", {}, headers)

    # ---- CarrierInvoice ----
    def create_carrier_invoice(self, job_id, payload, headers):
        return self._request("POST", f"/api/pack-out-jobs/{job_id}/carrier-invoices", payload, headers)

    def list_carrier_invoices(self, job_id, headers):
        return self._request("GET", f"/api/pack-out-jobs/{job_id}/carrier-invoices", headers=headers)

    def get_carrier_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/carrier-invoices/{invoice_id}", headers=headers)

    def transition_carrier_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/carrier-invoices/{invoice_id}/transition", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
