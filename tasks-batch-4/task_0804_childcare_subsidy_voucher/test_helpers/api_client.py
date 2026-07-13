"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Family ----
    def create_family(self, payload, headers):
        return self._request("POST", "/ccdf/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/ccdf/families/{family_id}", headers=headers)

    # ---- ParentActivity ----
    def create_parent_activity(self, payload, headers):
        return self._request("POST", "/ccdf/parent-activities", payload, headers)

    def get_parent_activity(self, activity_id, headers):
        return self._request("GET", f"/ccdf/parent-activities/{activity_id}", headers=headers)

    def list_parent_activities(self, headers, params=None):
        return self._request("GET", "/ccdf/parent-activities", headers=headers, params=params)

    # ---- IncomeStandard ----
    def create_income_standard(self, payload, headers):
        return self._request("POST", "/ccdf/income-standards", payload, headers)

    # ---- EligibilityDetermination ----
    def create_determination(self, payload, headers):
        return self._request("POST", "/ccdf/determinations", payload, headers)

    def finalize_determination(self, determination_id, headers):
        return self._request("POST", f"/ccdf/determinations/{determination_id}/finalize", {}, headers)

    def get_determination(self, determination_id, headers):
        return self._request("GET", f"/ccdf/determinations/{determination_id}", headers=headers)

    def list_determinations(self, headers, params=None):
        return self._request("GET", "/ccdf/determinations", headers=headers, params=params)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/ccdf/providers", payload, headers)

    def license_provider(self, provider_id, payload, headers):
        return self._request("POST", f"/ccdf/providers/{provider_id}/license", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/ccdf/providers/{provider_id}", headers=headers)

    # ---- RateCeiling ----
    def create_rate_ceiling(self, payload, headers):
        return self._request("POST", "/ccdf/rate-ceilings", payload, headers)

    def list_rate_ceilings(self, headers, params=None):
        return self._request("GET", "/ccdf/rate-ceilings", headers=headers, params=params)

    # ---- Authorization ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/ccdf/authorizations", payload, headers)

    def activate_authorization(self, authorization_id, headers):
        return self._request("POST", f"/ccdf/authorizations/{authorization_id}/activate", {}, headers)

    def suspend_authorization(self, authorization_id, headers):
        return self._request("POST", f"/ccdf/authorizations/{authorization_id}/suspend", {}, headers)

    def reinstate_authorization(self, authorization_id, headers):
        return self._request("POST", f"/ccdf/authorizations/{authorization_id}/reinstate", {}, headers)

    def terminate_authorization(self, authorization_id, headers):
        return self._request("POST", f"/ccdf/authorizations/{authorization_id}/terminate", {}, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/ccdf/authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/ccdf/authorizations", headers=headers, params=params)

    # ---- AttendanceRecord ----
    def create_attendance_record(self, payload, headers):
        return self._request("POST", "/ccdf/attendance-records", payload, headers)

    def approve_attendance(self, attendance_id, headers):
        return self._request("POST", f"/ccdf/attendance-records/{attendance_id}/approve", {}, headers)

    def reject_attendance(self, attendance_id, headers, payload=None):
        return self._request("POST", f"/ccdf/attendance-records/{attendance_id}/reject", payload or {}, headers)

    def resubmit_attendance(self, attendance_id, headers, payload=None):
        return self._request("POST", f"/ccdf/attendance-records/{attendance_id}/resubmit", payload or {}, headers)

    def get_attendance_record(self, attendance_id, headers):
        return self._request("GET", f"/ccdf/attendance-records/{attendance_id}", headers=headers)

    def list_attendance_records(self, headers, params=None):
        return self._request("GET", "/ccdf/attendance-records", headers=headers, params=params)

    # ---- Payment ----
    def reverse_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/ccdf/payments/{payment_id}/reverse", payload or {}, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/ccdf/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/ccdf/payments", headers=headers, params=params)

    # ---- OverpaymentClaim ----
    def record_recovery(self, claim_id, payload, headers):
        return self._request("POST", f"/ccdf/overpayment-claims/{claim_id}/record-recovery", payload, headers)

    def waive_claim(self, claim_id, headers):
        return self._request("POST", f"/ccdf/overpayment-claims/{claim_id}/waive", {}, headers)

    def get_overpayment_claim(self, claim_id, headers):
        return self._request("GET", f"/ccdf/overpayment-claims/{claim_id}", headers=headers)

    def list_overpayment_claims(self, headers, params=None):
        return self._request("GET", "/ccdf/overpayment-claims", headers=headers, params=params)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/ccdf/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
