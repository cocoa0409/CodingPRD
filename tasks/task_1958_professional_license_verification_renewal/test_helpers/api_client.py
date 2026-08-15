"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/licensing/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # License types
    # ------------------------------------------------------------------
    def create_license_type(self, payload, headers):
        return self._request("POST", "/licensing/license-types", payload, headers)

    def list_license_types(self, headers, params=None):
        return self._request("GET", "/licensing/license-types", headers=headers,
                             params=params)

    def get_license_type(self, license_type_id, headers):
        return self._request("GET", f"/licensing/license-types/{license_type_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Role requirements
    # ------------------------------------------------------------------
    def create_role_requirement(self, payload, headers):
        return self._request("POST", "/licensing/role-requirements", payload, headers)

    def list_role_requirements(self, headers, params=None):
        return self._request("GET", "/licensing/role-requirements", headers=headers,
                             params=params)

    def get_role_requirement(self, requirement_id, headers):
        return self._request("GET", f"/licensing/role-requirements/{requirement_id}",
                             headers=headers)

    def delete_role_requirement(self, requirement_id, headers):
        return self._request("DELETE", f"/licensing/role-requirements/{requirement_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/licensing/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/licensing/employees", headers=headers,
                             params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/licensing/employees/{employee_id}",
                             headers=headers)

    def patch_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"/licensing/employees/{employee_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Licenses
    # ------------------------------------------------------------------
    def create_license(self, payload, headers):
        return self._request("POST", "/licensing/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licensing/licenses", headers=headers,
                             params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licensing/licenses/{license_id}",
                             headers=headers)

    def list_employee_licenses(self, employee_id, headers, params=None):
        return self._request("GET", f"/licensing/employees/{employee_id}/licenses",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def verify_license(self, license_id, payload, headers):
        return self._request("POST", f"/licensing/licenses/{license_id}/verify",
                             payload, headers)

    def list_verification_events(self, license_id, headers, params=None):
        return self._request("GET",
                             f"/licensing/licenses/{license_id}/verification-events",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # CE activities
    # ------------------------------------------------------------------
    def create_ce_activity(self, license_id, payload, headers):
        return self._request("POST", f"/licensing/licenses/{license_id}/ce-activities",
                             payload, headers)

    def list_ce_activities(self, license_id, headers, params=None):
        return self._request("GET", f"/licensing/licenses/{license_id}/ce-activities",
                             headers=headers, params=params)

    def validate_ce_activity(self, activity_id, headers):
        return self._request("POST", f"/licensing/ce-activities/{activity_id}/validate",
                             {}, headers)

    def reject_ce_activity(self, activity_id, headers):
        return self._request("POST", f"/licensing/ce-activities/{activity_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Renewal requests
    # ------------------------------------------------------------------
    def create_renewal_request(self, license_id, payload, headers):
        return self._request("POST",
                             f"/licensing/licenses/{license_id}/renewal-requests",
                             payload, headers)

    def list_renewal_requests(self, license_id, headers, params=None):
        return self._request("GET",
                             f"/licensing/licenses/{license_id}/renewal-requests",
                             headers=headers, params=params)

    def get_renewal_request(self, request_id, headers):
        return self._request("GET", f"/licensing/renewal-requests/{request_id}",
                             headers=headers)

    def submit_renewal_request(self, request_id, headers):
        return self._request("POST", f"/licensing/renewal-requests/{request_id}/submit",
                             {}, headers)

    def request_info_renewal_request(self, request_id, info_note, headers):
        return self._request("POST",
                             f"/licensing/renewal-requests/{request_id}/request-info",
                             {"info_note": info_note}, headers)

    def approve_renewal_request(self, request_id, headers):
        return self._request("POST",
                             f"/licensing/renewal-requests/{request_id}/approve",
                             {}, headers)

    def reject_renewal_request(self, request_id, decision_note, headers):
        return self._request("POST",
                             f"/licensing/renewal-requests/{request_id}/reject",
                             {"decision_note": decision_note}, headers)

    def mark_paid_renewal_request(self, request_id, payment_ref, headers):
        return self._request("POST",
                             f"/licensing/renewal-requests/{request_id}/mark-paid",
                             {"payment_ref": payment_ref}, headers)

    def void_renewal_request(self, request_id, void_reason, headers):
        return self._request("POST", f"/licensing/renewal-requests/{request_id}/void",
                             {"void_reason": void_reason}, headers)

    # ------------------------------------------------------------------
    # Disciplinary events
    # ------------------------------------------------------------------
    def create_disciplinary_event(self, license_id, payload, headers):
        return self._request("POST",
                             f"/licensing/licenses/{license_id}/disciplinary-events",
                             payload, headers)

    def list_disciplinary_events(self, license_id, headers, params=None):
        return self._request("GET",
                             f"/licensing/licenses/{license_id}/disciplinary-events",
                             headers=headers, params=params)

    def confirm_disciplinary_event(self, event_id, headers):
        return self._request("POST",
                             f"/licensing/disciplinary-events/{event_id}/confirm",
                             {}, headers)

    def dismiss_disciplinary_event(self, event_id, resolution_note, headers):
        return self._request("POST",
                             f"/licensing/disciplinary-events/{event_id}/dismiss",
                             {"resolution_note": resolution_note}, headers)

    def resolve_disciplinary_event(self, event_id, resolution_note, headers):
        return self._request("POST",
                             f"/licensing/disciplinary-events/{event_id}/resolve",
                             {"resolution_note": resolution_note}, headers)

    # ------------------------------------------------------------------
    # Exclusion screenings
    # ------------------------------------------------------------------
    def create_exclusion_screening(self, employee_id, payload, headers):
        return self._request("POST",
                             f"/licensing/employees/{employee_id}/exclusion-screenings",
                             payload, headers)

    def list_exclusion_screenings(self, employee_id, headers, params=None):
        return self._request("GET",
                             f"/licensing/employees/{employee_id}/exclusion-screenings",
                             headers=headers, params=params)

    def confirm_match_exclusion_screening(self, screening_id, headers):
        return self._request(
            "POST",
            f"/licensing/exclusion-screenings/{screening_id}/confirm-match",
            {}, headers)

    def clear_false_positive_exclusion_screening(self, screening_id, resolution_note,
                                                 headers):
        return self._request(
            "POST",
            f"/licensing/exclusion-screenings/{screening_id}/clear-false-positive",
            {"resolution_note": resolution_note}, headers)

    # ------------------------------------------------------------------
    # Audit packages
    # ------------------------------------------------------------------
    def create_audit_package(self, employee_id, payload, headers):
        return self._request("POST",
                             f"/licensing/employees/{employee_id}/audit-packages",
                             payload, headers)

    def list_audit_packages(self, employee_id, headers, params=None):
        return self._request("GET",
                             f"/licensing/employees/{employee_id}/audit-packages",
                             headers=headers, params=params)

    def get_audit_package(self, package_id, headers):
        return self._request("GET", f"/licensing/audit-packages/{package_id}",
                             headers=headers)

    def seal_audit_package(self, package_id, headers):
        return self._request("POST", f"/licensing/audit-packages/{package_id}/seal",
                             {}, headers)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def get_compliance_summary(self, headers):
        return self._request("GET", "/licensing/reports/compliance-summary",
                             headers=headers)


api_client = ApiClient()
