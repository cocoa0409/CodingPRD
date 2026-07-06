"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() handles the HTTP
envelope and base URL. GET methods pass filters/pagination via params.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- ClientAccount ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", {}, headers)

    # --- Locations ---
    def create_location(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/locations", payload, headers)

    def list_locations(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/locations",
                             headers=headers, params=params)

    def retire_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/retire", {}, headers)

    # --- ScenarioScripts ---
    def create_script(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/scripts", payload, headers)

    def list_scripts(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/scripts",
                             headers=headers, params=params)

    def publish_script(self, script_id, headers):
        return self._request("POST", f"/scripts/{script_id}/publish", {}, headers)

    def archive_script(self, script_id, headers):
        return self._request("POST", f"/scripts/{script_id}/archive", {}, headers)

    # --- ShopWaves ---
    def create_wave(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/waves", payload, headers)

    def list_waves(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/waves",
                             headers=headers, params=params)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def publish_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/publish", {}, headers)

    def close_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/close", {}, headers)

    # --- Shoppers ---
    def create_shopper(self, payload, headers):
        return self._request("POST", "/shoppers", payload, headers)

    def get_shopper(self, shopper_id, headers):
        return self._request("GET", f"/shoppers/{shopper_id}", headers=headers)

    def set_tax_profile(self, shopper_id, payload, headers):
        return self._request("PATCH", f"/shoppers/{shopper_id}/tax-profile", payload, headers)

    def create_certification_attempt(self, shopper_id, payload, headers):
        return self._request("POST", f"/shoppers/{shopper_id}/certification-attempts",
                             payload, headers)

    def list_certification_attempts(self, shopper_id, headers, params=None):
        return self._request("GET", f"/shoppers/{shopper_id}/certification-attempts",
                             headers=headers, params=params)

    def suspend_shopper(self, shopper_id, headers):
        return self._request("POST", f"/shoppers/{shopper_id}/suspend", {}, headers)

    def reinstate_shopper(self, shopper_id, headers):
        return self._request("POST", f"/shoppers/{shopper_id}/reinstate", {}, headers)

    # --- Assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def upload_evidence(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/evidence", payload, headers)

    def list_evidence(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/evidence",
                             headers=headers, params=params)

    def review_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"/evidence/{evidence_id}/review", payload, headers)

    def create_scorecard(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/scorecard", payload, headers)

    def get_scorecard(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/scorecard", headers=headers)

    def fraud_check_scorecard(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/scorecard/fraud-check",
                             payload, headers)

    def submit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/submit", {}, headers)

    def validate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/validate", {}, headers)

    def request_revision(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/request-revision", {}, headers)

    def resume_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/resume", {}, headers)

    def reject_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/reject", {}, headers)

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", payload, headers)

    def sweep_deadline(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/sweep-deadline", {}, headers)

    def get_assignment_reimbursement(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}/reimbursement", headers=headers)

    # --- Disputes ---
    def open_dispute(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/disputes", payload, headers)

    def list_disputes(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/disputes",
                             headers=headers, params=params)

    def counter_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/counter", {}, headers)

    def respond_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/respond", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", {}, headers)

    # --- Payouts ---
    def create_payout_batch(self, payload, headers):
        return self._request("POST", "/payout-batches", payload, headers)

    def get_payout_batch(self, batch_id, headers):
        return self._request("GET", f"/payout-batches/{batch_id}", headers=headers)

    def list_payout_batches(self, headers, params=None):
        return self._request("GET", "/payout-batches", headers=headers, params=params)

    def list_batch_reimbursements(self, batch_id, headers, params=None):
        return self._request("GET", f"/payout-batches/{batch_id}/reimbursements",
                             headers=headers, params=params)

    def list_shopper_reimbursements(self, shopper_id, headers, params=None):
        return self._request("GET", f"/shoppers/{shopper_id}/reimbursements",
                             headers=headers, params=params)

    def pay_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/payout-batches/{batch_id}/pay", {}, headers)

    def void_payout_batch(self, batch_id, headers):
        return self._request("POST", f"/payout-batches/{batch_id}/void", {}, headers)


api_client = ApiClient()
