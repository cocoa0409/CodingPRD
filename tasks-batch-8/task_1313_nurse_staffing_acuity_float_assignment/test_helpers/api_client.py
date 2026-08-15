"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- NursingUnit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    # --- Nurse ---
    def create_nurse(self, payload, headers):
        return self._request("POST", "/nurses", payload, headers)

    def list_nurses(self, headers, params=None):
        return self._request("GET", "/nurses", headers=headers, params=params)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"/nurses/{nurse_id}", headers=headers)

    def get_week_ledger(self, nurse_id, headers, params=None):
        return self._request("GET", f"/nurses/{nurse_id}/week-ledger",
                             headers=headers, params=params)

    # --- StaffingMatrixRule ---
    def create_matrix_rule(self, payload, headers):
        return self._request("POST", "/matrix-rules", payload, headers)

    # --- AcuitySnapshot ---
    def create_acuity_snapshot(self, payload, headers):
        return self._request("POST", "/acuity-snapshots", payload, headers)

    def list_acuity_snapshots(self, headers, params=None):
        return self._request("GET", "/acuity-snapshots", headers=headers,
                             params=params)

    def get_acuity_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/acuity-snapshots/{snapshot_id}",
                             headers=headers)

    # --- Shift ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def lock_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/lock", headers=headers)

    # --- ShiftAssignment ---
    def create_assignment(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/assignments",
                             payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}",
                             headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept",
                             headers=headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline",
                             headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/confirm",
                             headers=headers)

    def revoke_confirmation(self, assignment_id, headers):
        return self._request("POST",
                             f"/assignments/{assignment_id}/revoke-confirmation",
                             headers=headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel",
                             headers=headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/complete",
                             payload, headers)

    # --- FloatRequest ---
    def create_float_request(self, payload, headers):
        return self._request("POST", "/float-requests", payload, headers)

    def list_float_requests(self, headers, params=None):
        return self._request("GET", "/float-requests", headers=headers,
                             params=params)

    def get_float_request(self, float_request_id, headers):
        return self._request("GET", f"/float-requests/{float_request_id}",
                             headers=headers)

    def release_float_request(self, float_request_id, headers):
        return self._request("POST",
                             f"/float-requests/{float_request_id}/release",
                             headers=headers)

    # --- IncentiveOffer ---
    def create_incentive_offer(self, payload, headers):
        return self._request("POST", "/incentive-offers", payload, headers)

    def list_incentive_offers(self, headers, params=None):
        return self._request("GET", "/incentive-offers", headers=headers,
                             params=params)

    def get_incentive_offer(self, offer_id, headers):
        return self._request("GET", f"/incentive-offers/{offer_id}",
                             headers=headers)

    def claim_incentive_offer(self, offer_id, headers):
        return self._request("POST", f"/incentive-offers/{offer_id}/claim",
                             headers=headers)

    def withdraw_incentive_offer(self, offer_id, headers):
        return self._request("POST", f"/incentive-offers/{offer_id}/withdraw",
                             headers=headers)

    # --- SitterRequest ---
    def create_sitter_request(self, payload, headers):
        return self._request("POST", "/sitter-requests", payload, headers)

    def list_sitter_requests(self, headers, params=None):
        return self._request("GET", "/sitter-requests", headers=headers,
                             params=params)

    def get_sitter_request(self, sitter_request_id, headers):
        return self._request("GET", f"/sitter-requests/{sitter_request_id}",
                             headers=headers)

    def fill_sitter_request(self, sitter_request_id, payload, headers):
        return self._request("POST",
                             f"/sitter-requests/{sitter_request_id}/fill",
                             payload, headers)

    def release_sitter_request(self, sitter_request_id, headers):
        return self._request("POST",
                             f"/sitter-requests/{sitter_request_id}/release",
                             headers=headers)

    # --- ComplianceReport ---
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}",
                             headers=headers)

    def submit_compliance_report(self, report_id, headers):
        return self._request("POST",
                             f"/compliance-reports/{report_id}/submit",
                             headers=headers)

    def return_compliance_report(self, report_id, payload, headers):
        return self._request("POST",
                             f"/compliance-reports/{report_id}/return",
                             payload, headers)

    def accept_compliance_report(self, report_id, headers):
        return self._request("POST",
                             f"/compliance-reports/{report_id}/accept",
                             headers=headers)


api_client = ApiClient()
