"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # Transport hygiene for per-test-server isolation: the runner SIGKILLs
        # and respawns the API server on the same port before every test. The
        # base client pools keep-alive connections on a shared Session, so a
        # pooled connection to the just-killed server can race the next request
        # and surface as a spurious ConnectionResetError. Forcing
        # "Connection: close" makes every request open a fresh socket to the
        # current server incarnation; assertion semantics are untouched.
        merged = {"Connection": "close"}
        if headers:
            merged.update(headers)
        return super()._request(
            method, path, payload=payload, headers=merged, params=params
        )

    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Call programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/api/call-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/api/call-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/call-programs/{program_id}", headers=headers)

    def generate_program(self, program_id, headers):
        return self._request("POST", f"/api/call-programs/{program_id}/generate", {}, headers)

    def regenerate_program(self, program_id, expected_call_program_version, headers):
        return self._request(
            "POST",
            f"/api/call-programs/{program_id}/regenerate",
            {"expected_call_program_version": expected_call_program_version},
            headers,
        )

    def publish_program(self, program_id, headers):
        return self._request("POST", f"/api/call-programs/{program_id}/publish", {}, headers)

    def reconcile_program(self, program_id, headers):
        return self._request("POST", f"/api/call-programs/{program_id}/reconcile", {}, headers)

    def get_fairness_report(self, program_id, headers):
        return self._request(
            "GET", f"/api/call-programs/{program_id}/fairness-report", headers=headers
        )

    def get_coverage_report(self, program_id, headers):
        return self._request(
            "GET", f"/api/call-programs/{program_id}/coverage-report", headers=headers
        )

    # ------------------------------------------------------------------
    # Physicians
    # ------------------------------------------------------------------
    def create_physician(self, payload, headers):
        return self._request("POST", "/api/physicians", payload, headers)

    def list_physicians(self, headers, params=None):
        return self._request("GET", "/api/physicians", headers=headers, params=params)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/api/physicians/{physician_id}", headers=headers)

    def deactivate_physician(self, physician_id, headers):
        return self._request(
            "POST", f"/api/physicians/{physician_id}/deactivate", {}, headers
        )

    # ------------------------------------------------------------------
    # Unavailability windows
    # ------------------------------------------------------------------
    def create_window(self, payload, headers):
        return self._request("POST", "/api/unavailability-windows", payload, headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", "/api/unavailability-windows", headers=headers, params=params)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/api/unavailability-windows/{window_id}", headers=headers)

    def approve_window(self, window_id, headers):
        return self._request(
            "POST", f"/api/unavailability-windows/{window_id}/approve", {}, headers
        )

    def cancel_window(self, window_id, headers):
        return self._request(
            "POST", f"/api/unavailability-windows/{window_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Call slots (read-only; created by generation)
    # ------------------------------------------------------------------
    def list_slots(self, headers, params=None):
        return self._request("GET", "/api/call-slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/api/call-slots/{slot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Call assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/api/call-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/call-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/call-assignments/{assignment_id}", headers=headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/call-assignments/{assignment_id}/cancel", {}, headers
        )

    def mark_served(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/call-assignments/{assignment_id}/mark-served", {}, headers
        )

    def activate_backup(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/api/call-assignments/{assignment_id}/activate-backup", payload, headers
        )

    # ------------------------------------------------------------------
    # Swap requests
    # ------------------------------------------------------------------
    def create_swap(self, payload, headers):
        return self._request("POST", "/api/swap-requests", payload, headers)

    def list_swaps(self, headers, params=None):
        return self._request("GET", "/api/swap-requests", headers=headers, params=params)

    def get_swap(self, swap_id, headers):
        return self._request("GET", f"/api/swap-requests/{swap_id}", headers=headers)

    def claim_swap(self, swap_id, headers):
        return self._request("POST", f"/api/swap-requests/{swap_id}/claim", {}, headers)

    def approve_swap(self, swap_id, headers):
        return self._request("POST", f"/api/swap-requests/{swap_id}/approve", {}, headers)

    def decline_swap(self, swap_id, headers, decline_reason=None):
        payload = {} if decline_reason is None else {"decline_reason": decline_reason}
        return self._request("POST", f"/api/swap-requests/{swap_id}/decline", payload, headers)

    def execute_swap(self, swap_id, headers):
        return self._request("POST", f"/api/swap-requests/{swap_id}/execute", {}, headers)

    def cancel_swap(self, swap_id, headers):
        return self._request("POST", f"/api/swap-requests/{swap_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Coverage gaps (read-only; created by cascades)
    # ------------------------------------------------------------------
    def list_gaps(self, headers, params=None):
        return self._request("GET", "/api/coverage-gaps", headers=headers, params=params)

    def get_gap(self, gap_id, headers):
        return self._request("GET", f"/api/coverage-gaps/{gap_id}", headers=headers)

    # ------------------------------------------------------------------
    # Locum requisitions
    # ------------------------------------------------------------------
    def create_requisition(self, payload, headers):
        return self._request("POST", "/api/locum-requisitions", payload, headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/api/locum-requisitions", headers=headers, params=params)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/api/locum-requisitions/{requisition_id}", headers=headers)

    def propose_candidate(self, requisition_id, candidate_physician_id, headers):
        return self._request(
            "POST",
            f"/api/locum-requisitions/{requisition_id}/propose-candidate",
            {"candidate_physician_id": candidate_physician_id},
            headers,
        )

    def begin_credentialing(self, requisition_id, headers):
        return self._request(
            "POST", f"/api/locum-requisitions/{requisition_id}/begin-credentialing", {}, headers
        )

    def cancel_requisition(self, requisition_id, headers):
        return self._request(
            "POST", f"/api/locum-requisitions/{requisition_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Credentialing cases
    # ------------------------------------------------------------------
    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/credentialing-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/credentialing-cases/{case_id}", headers=headers)

    def complete_item(self, case_id, item, headers):
        return self._request(
            "POST", f"/api/credentialing-cases/{case_id}/complete-item", {"item": item}, headers
        )

    def fail_case(self, case_id, reason, headers):
        return self._request(
            "POST", f"/api/credentialing-cases/{case_id}/fail", {"reason": reason}, headers
        )

    def expire_case(self, case_id, headers):
        return self._request("POST", f"/api/credentialing-cases/{case_id}/expire", {}, headers)

    # ------------------------------------------------------------------
    # Pay entries (read-only; created at mark-served)
    # ------------------------------------------------------------------
    def list_pay_entries(self, headers, params=None):
        return self._request("GET", "/api/pay-entries", headers=headers, params=params)

    def get_pay_entry(self, pay_entry_id, headers):
        return self._request("GET", f"/api/pay-entries/{pay_entry_id}", headers=headers)


api_client = ApiClient()
