"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Association & configuration ---
    def create_association(self, payload, headers):
        return self._request("POST", "/arc/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/arc/associations/{association_id}", headers=headers)

    def create_owner(self, association_id, payload, headers):
        return self._request("POST", f"/arc/associations/{association_id}/owners", payload, headers)

    def list_owners(self, association_id, headers, params=None):
        return self._request("GET", f"/arc/associations/{association_id}/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/arc/owners/{owner_id}", headers=headers)

    def create_property(self, association_id, payload, headers):
        return self._request("POST", f"/arc/associations/{association_id}/properties", payload, headers)

    def list_properties(self, association_id, headers, params=None):
        return self._request("GET", f"/arc/associations/{association_id}/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/arc/properties/{property_id}", headers=headers)

    def list_owner_properties(self, owner_id, headers, params=None):
        return self._request("GET", f"/arc/owners/{owner_id}/properties", headers=headers, params=params)

    # --- Blackout calendar ---
    def create_blackout(self, association_id, payload, headers):
        return self._request("POST", f"/arc/associations/{association_id}/blackouts", payload, headers)

    def list_blackouts(self, association_id, headers, params=None):
        return self._request("GET", f"/arc/associations/{association_id}/blackouts", headers=headers, params=params)

    # --- Variance precedent registry ---
    def create_variance(self, association_id, payload, headers):
        return self._request("POST", f"/arc/associations/{association_id}/variances", payload, headers)

    def list_variances(self, association_id, headers, params=None):
        return self._request("GET", f"/arc/associations/{association_id}/variances", headers=headers, params=params)

    # --- Applications ---
    def create_application(self, property_id, payload, headers):
        return self._request("POST", f"/arc/properties/{property_id}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/arc/applications/{application_id}", headers=headers)

    def list_property_applications(self, property_id, headers, params=None):
        return self._request("GET", f"/arc/properties/{property_id}/applications", headers=headers, params=params)

    def list_owner_applications(self, owner_id, headers, params=None):
        return self._request("GET", f"/arc/owners/{owner_id}/applications", headers=headers, params=params)

    def create_attachment(self, application_id, payload, headers):
        return self._request("POST", f"/arc/applications/{application_id}/attachments", payload, headers)

    def list_attachments(self, application_id, headers, params=None):
        return self._request("GET", f"/arc/applications/{application_id}/attachments", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/arc/applications/{application_id}/submit", headers=headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/arc/applications/{application_id}/start-review", headers=headers)

    def request_revision(self, application_id, payload, headers):
        return self._request("POST", f"/arc/applications/{application_id}/request-revision", payload, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"/arc/applications/{application_id}/resubmit", headers=headers)

    def cast_vote(self, application_id, payload, headers):
        return self._request("POST", f"/arc/applications/{application_id}/votes", payload, headers)

    def list_votes(self, application_id, headers, params=None):
        return self._request("GET", f"/arc/applications/{application_id}/votes", headers=headers, params=params)

    def list_owner_votes(self, owner_id, headers, params=None):
        return self._request("GET", f"/arc/owners/{owner_id}/votes", headers=headers, params=params)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/arc/applications/{application_id}/decide", payload, headers)

    def amend_conditions(self, application_id, payload, headers):
        return self._request("POST", f"/arc/applications/{application_id}/conditions", payload, headers)

    def file_appeal(self, application_id, payload, headers):
        return self._request("POST", f"/arc/applications/{application_id}/appeals", payload, headers)

    def list_appeals(self, application_id, headers, params=None):
        return self._request("GET", f"/arc/applications/{application_id}/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/arc/appeals/{appeal_id}/decide", payload, headers)

    # --- Permits & inspections ---
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/arc/permits/{permit_id}", headers=headers)

    def list_application_permits(self, application_id, headers, params=None):
        return self._request("GET", f"/arc/applications/{application_id}/permits", headers=headers, params=params)

    def change_contractor(self, permit_id, payload, headers):
        return self._request("POST", f"/arc/permits/{permit_id}/contractor-change", payload, headers)

    def extend_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/arc/permits/{permit_id}/extensions", payload, headers)

    def request_inspection(self, permit_id, headers):
        return self._request("POST", f"/arc/permits/{permit_id}/request-inspection", headers=headers)

    def list_inspections(self, permit_id, headers, params=None):
        return self._request("GET", f"/arc/permits/{permit_id}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/arc/inspections/{inspection_id}", headers=headers)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/arc/inspections/{inspection_id}/record", payload, headers)

    def reschedule_inspection(self, inspection_id, headers):
        return self._request("POST", f"/arc/inspections/{inspection_id}/reschedule", headers=headers)

    # --- Violations, fines, liens ---
    def create_violation(self, property_id, payload, headers):
        return self._request("POST", f"/arc/properties/{property_id}/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/arc/violations/{violation_id}", headers=headers)

    def list_property_violations(self, property_id, headers, params=None):
        return self._request("GET", f"/arc/properties/{property_id}/violations", headers=headers, params=params)

    def list_application_violations(self, application_id, headers, params=None):
        return self._request("GET", f"/arc/applications/{application_id}/violations", headers=headers, params=params)

    def list_application_variances(self, application_id, headers, params=None):
        return self._request("GET", f"/arc/applications/{application_id}/variances", headers=headers, params=params)

    def list_permit_violations(self, permit_id, headers, params=None):
        return self._request("GET", f"/arc/permits/{permit_id}/violations", headers=headers, params=params)

    def list_inspection_violations(self, inspection_id, headers, params=None):
        return self._request("GET", f"/arc/inspections/{inspection_id}/violations", headers=headers, params=params)

    def remediate_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/arc/violations/{violation_id}/remediate", payload, headers)

    def list_violation_fines(self, violation_id, headers, params=None):
        return self._request("GET", f"/arc/violations/{violation_id}/fines", headers=headers, params=params)

    def settle_fine(self, fine_id, payload, headers):
        return self._request("POST", f"/arc/fines/{fine_id}/settle", payload, headers)

    def waive_fine(self, fine_id, payload, headers):
        return self._request("POST", f"/arc/fines/{fine_id}/waive", payload, headers)

    def list_liens(self, property_id, headers, params=None):
        return self._request("GET", f"/arc/properties/{property_id}/liens", headers=headers, params=params)

    def satisfy_lien(self, lien_id, headers):
        return self._request("POST", f"/arc/liens/{lien_id}/satisfy", headers=headers)

    # --- Test-driving system endpoints ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/arc/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/arc/_sweeps/daily", headers=headers)


api_client = ApiClient()
