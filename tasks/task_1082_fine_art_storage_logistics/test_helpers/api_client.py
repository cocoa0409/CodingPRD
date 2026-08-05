"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def transition_client(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/state", payload, headers)

    # ---- Vault ----
    def create_vault(self, payload, headers):
        return self._request("POST", "/vaults", payload, headers)

    def get_vault(self, vault_id, headers):
        return self._request("GET", f"/vaults/{vault_id}", headers=headers)

    def list_vaults(self, headers, params=None):
        return self._request("GET", "/vaults", headers=headers, params=params)

    def transition_vault(self, vault_id, payload, headers):
        return self._request("POST", f"/vaults/{vault_id}/state", payload, headers)

    # ---- Artwork ----
    def create_artwork(self, payload, headers):
        return self._request("POST", "/artworks", payload, headers)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}", headers=headers)

    def list_artworks(self, headers, params=None):
        return self._request("GET", "/artworks", headers=headers, params=params)

    def transition_artwork(self, artwork_id, payload, headers):
        return self._request("POST", f"/artworks/{artwork_id}/state", payload, headers)

    # ---- ConditionReport ----
    def create_condition_report(self, payload, headers):
        return self._request("POST", "/condition-reports", payload, headers)

    def get_condition_report(self, report_id, headers):
        return self._request("GET", f"/condition-reports/{report_id}", headers=headers)

    def list_condition_reports(self, headers, params=None):
        return self._request("GET", "/condition-reports", headers=headers, params=params)

    # ---- Appraisal ----
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    # ---- InsurancePolicy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def transition_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/state", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    # ---- Crate ----
    def create_crate(self, payload, headers):
        return self._request("POST", "/crates", payload, headers)

    def transition_crate(self, crate_id, payload, headers):
        return self._request("POST", f"/crates/{crate_id}/state", payload, headers)

    def get_crate(self, crate_id, headers):
        return self._request("GET", f"/crates/{crate_id}", headers=headers)

    def list_crates(self, headers, params=None):
        return self._request("GET", "/crates", headers=headers, params=params)

    # ---- RiggingCrew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    # ---- TransportJob ----
    def create_transport_job(self, payload, headers):
        return self._request("POST", "/transport-jobs", payload, headers)

    def transition_transport_job(self, job_id, payload, headers):
        return self._request("POST", f"/transport-jobs/{job_id}/state", payload, headers)

    def get_transport_job(self, job_id, headers):
        return self._request("GET", f"/transport-jobs/{job_id}", headers=headers)

    def list_transport_jobs(self, headers, params=None):
        return self._request("GET", "/transport-jobs", headers=headers, params=params)

    # ---- StoragePlacement ----
    def create_placement(self, payload, headers):
        return self._request("POST", "/storage-placements", payload, headers)

    def transition_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/storage-placements/{placement_id}/state", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/storage-placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/storage-placements", headers=headers, params=params)

    # ---- LoanAgreement ----
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def transition_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/state", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    # ---- Carnet ----
    def create_carnet(self, payload, headers):
        return self._request("POST", "/carnets", payload, headers)

    def transition_carnet(self, carnet_id, payload, headers):
        return self._request("POST", f"/carnets/{carnet_id}/state", payload, headers)

    def get_carnet(self, carnet_id, headers):
        return self._request("GET", f"/carnets/{carnet_id}", headers=headers)

    def list_carnets(self, headers, params=None):
        return self._request("GET", "/carnets", headers=headers, params=params)

    # ---- ViewingRoom ----
    def create_viewing_room(self, payload, headers):
        return self._request("POST", "/viewing-rooms", payload, headers)

    def transition_viewing_room(self, room_id, payload, headers):
        return self._request("POST", f"/viewing-rooms/{room_id}/state", payload, headers)

    def get_viewing_room(self, room_id, headers):
        return self._request("GET", f"/viewing-rooms/{room_id}", headers=headers)

    def list_viewing_rooms(self, headers, params=None):
        return self._request("GET", "/viewing-rooms", headers=headers, params=params)

    # ---- ViewingBooking ----
    def create_viewing_booking(self, payload, headers):
        return self._request("POST", "/viewing-bookings", payload, headers)

    def transition_viewing_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/viewing-bookings/{booking_id}/state", payload, headers)

    def get_viewing_booking(self, booking_id, headers):
        return self._request("GET", f"/viewing-bookings/{booking_id}", headers=headers)

    def list_viewing_bookings(self, headers, params=None):
        return self._request("GET", "/viewing-bookings", headers=headers, params=params)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/state", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)


api_client = ApiClient()
