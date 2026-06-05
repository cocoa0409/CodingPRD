"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Owner ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # --- VIN verification ---
    def create_vin_verification(self, payload, headers):
        return self._request("POST", "/vin-verifications", payload, headers)

    def get_vin_verification(self, vin_verification_id, headers):
        return self._request("GET", f"/vin-verifications/{vin_verification_id}", headers=headers)

    def list_vin_verifications(self, headers, params=None):
        return self._request("GET", "/vin-verifications", headers=headers, params=params)

    # --- Title applications ---
    def create_title_application(self, payload, headers):
        return self._request("POST", "/title-applications", payload, headers)

    def get_title_application(self, ta_id, headers):
        return self._request("GET", f"/title-applications/{ta_id}", headers=headers)

    def list_title_applications(self, headers, params=None):
        return self._request("GET", "/title-applications", headers=headers, params=params)

    def submit_title_application(self, ta_id, headers):
        return self._request("POST", f"/title-applications/{ta_id}/submit", {}, headers)

    def approve_title_application(self, ta_id, headers):
        return self._request("POST", f"/title-applications/{ta_id}/approve", {}, headers)

    def reject_title_application(self, ta_id, headers):
        return self._request("POST", f"/title-applications/{ta_id}/reject", {}, headers)

    def issue_title_application(self, ta_id, headers):
        return self._request("POST", f"/title-applications/{ta_id}/issue", {}, headers)

    # --- Salvage inspections ---
    def create_salvage_inspection(self, payload, headers):
        return self._request("POST", "/salvage-inspections", payload, headers)

    def get_salvage_inspection(self, si_id, headers):
        return self._request("GET", f"/salvage-inspections/{si_id}", headers=headers)

    def list_salvage_inspections(self, headers, params=None):
        return self._request("GET", "/salvage-inspections", headers=headers, params=params)

    # --- Emissions inspections ---
    def create_emissions_inspection(self, payload, headers):
        return self._request("POST", "/emissions-inspections", payload, headers)

    def get_emissions_inspection(self, ei_id, headers):
        return self._request("GET", f"/emissions-inspections/{ei_id}", headers=headers)

    def list_emissions_inspections(self, headers, params=None):
        return self._request("GET", "/emissions-inspections", headers=headers, params=params)

    # --- Liens ---
    def create_lien(self, payload, headers):
        return self._request("POST", "/liens", payload, headers)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/liens", headers=headers, params=params)

    def perfect_lien(self, lien_id, headers):
        return self._request("POST", f"/liens/{lien_id}/perfect", {}, headers)

    def release_lien(self, lien_id, headers):
        return self._request("POST", f"/liens/{lien_id}/release", {}, headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/registrations/{reg_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def activate_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/activate", {}, headers)

    def suspend_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/suspend", {}, headers)

    def reinstate_registration(self, reg_id, payload, headers):
        return self._request("POST", f"/registrations/{reg_id}/reinstate", payload, headers)

    def expire_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/expire", {}, headers)

    # --- Fee assessments ---
    def create_fee_assessment(self, payload, headers):
        return self._request("POST", "/fee-assessments", payload, headers)

    def get_fee_assessment(self, fa_id, headers):
        return self._request("GET", f"/fee-assessments/{fa_id}", headers=headers)

    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", "/fee-assessments", headers=headers, params=params)

    def pay_fee_assessment(self, fa_id, headers):
        return self._request("POST", f"/fee-assessments/{fa_id}/pay", {}, headers)

    def void_fee_assessment(self, fa_id, headers):
        return self._request("POST", f"/fee-assessments/{fa_id}/void", {}, headers)

    # --- License plates ---
    def create_license_plate(self, payload, headers):
        return self._request("POST", "/license-plates", payload, headers)

    def get_license_plate(self, plate_id, headers):
        return self._request("GET", f"/license-plates/{plate_id}", headers=headers)

    def list_license_plates(self, headers, params=None):
        return self._request("GET", "/license-plates", headers=headers, params=params)

    def activate_license_plate(self, plate_id, headers):
        return self._request("POST", f"/license-plates/{plate_id}/activate", {}, headers)

    def deactivate_license_plate(self, plate_id, headers):
        return self._request("POST", f"/license-plates/{plate_id}/deactivate", {}, headers)

    # --- REAL ID applications ---
    def create_real_id_application(self, payload, headers):
        return self._request("POST", "/real-id-applications", payload, headers)

    def get_real_id_application(self, rid_id, headers):
        return self._request("GET", f"/real-id-applications/{rid_id}", headers=headers)

    def list_real_id_applications(self, headers, params=None):
        return self._request("GET", "/real-id-applications", headers=headers, params=params)

    def begin_review_real_id_application(self, rid_id, headers):
        return self._request("POST", f"/real-id-applications/{rid_id}/begin-review", {}, headers)

    def approve_real_id_application(self, rid_id, headers):
        return self._request("POST", f"/real-id-applications/{rid_id}/approve", {}, headers)

    def deny_real_id_application(self, rid_id, headers):
        return self._request("POST", f"/real-id-applications/{rid_id}/deny", {}, headers)

    def return_real_id_application(self, rid_id, headers):
        return self._request("POST", f"/real-id-applications/{rid_id}/return-for-documents", {}, headers)


api_client = ApiClient()
