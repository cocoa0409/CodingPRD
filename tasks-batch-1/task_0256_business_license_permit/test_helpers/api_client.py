"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base _request() method
(signature: _request(method, path, payload=None, headers=None, params=None))
is inherited. For GET the framework passes `payload` as query params, so list
methods forward pagination/filter dicts there.

Every endpoint method takes an explicit `headers` argument so tests can thread
the correct role and — for the entity-backed Applicant — the correct owning
Business identity.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── ActivityCategory ────────────────────────────────────────────────
    def create_activity_category(self, payload, headers):
        return self._request("POST", "/activity-categories", payload, headers)

    def get_activity_category(self, category_id, headers):
        return self._request("GET", f"/activity-categories/{category_id}", headers=headers)

    def list_activity_categories(self, headers, params=None):
        return self._request("GET", "/activity-categories", headers=headers, params=params)

    # ─── Business ────────────────────────────────────────────────────────
    def create_business(self, payload, headers):
        return self._request("POST", "/businesses", payload, headers)

    def get_business(self, business_id, headers):
        return self._request("GET", f"/businesses/{business_id}", headers=headers)

    def list_business_applications(self, business_id, headers, params=None):
        return self._request("GET", f"/businesses/{business_id}/applications",
                             headers=headers, params=params)

    def list_business_licenses(self, business_id, headers, params=None):
        return self._request("GET", f"/businesses/{business_id}/licenses",
                             headers=headers, params=params)

    # ─── Application ─────────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def zoning_check_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/zoning-check", {}, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/approve", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/reject", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    def issue_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/issue", {}, headers)

    def list_application_inspections(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/inspections",
                             headers=headers, params=params)

    def list_application_fee_assessments(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/fee-assessments",
                             headers=headers, params=params)

    # ─── Inspection ──────────────────────────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/record", payload, headers)

    # ─── License ─────────────────────────────────────────────────────────
    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def assess_delinquency(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/assess-delinquency", {}, headers)

    def renew_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/renew", {}, headers)

    def revoke_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/revoke", {}, headers)

    def surrender_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/surrender", {}, headers)

    def list_license_endorsements(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/endorsements",
                             headers=headers, params=params)

    def list_license_transfers(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/transfers",
                             headers=headers, params=params)

    def list_license_fee_assessments(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/fee-assessments",
                             headers=headers, params=params)

    # ─── Endorsement ─────────────────────────────────────────────────────
    def create_endorsement(self, payload, headers):
        return self._request("POST", "/endorsements", payload, headers)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/endorsements/{endorsement_id}", headers=headers)

    def suspend_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/endorsements/{endorsement_id}/suspend", {}, headers)

    def reinstate_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/endorsements/{endorsement_id}/reinstate", {}, headers)

    def void_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/endorsements/{endorsement_id}/void", {}, headers)

    # ─── OwnershipTransfer ───────────────────────────────────────────────
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def approve_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/approve", {}, headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/reject", {}, headers)

    def complete_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/transfers/{transfer_id}/complete", payload, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/cancel", {}, headers)

    # ─── FeeAssessment ───────────────────────────────────────────────────
    def get_fee_assessment(self, assessment_id, headers):
        return self._request("GET", f"/fee-assessments/{assessment_id}", headers=headers)

    def settle_fee_assessment(self, assessment_id, headers):
        return self._request("POST", f"/fee-assessments/{assessment_id}/settle", {}, headers)

    # ─── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
