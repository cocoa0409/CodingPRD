"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Recordkeepers
    # ------------------------------------------------------------------
    def create_recordkeeper(self, payload, headers):
        return self._request("POST", "/recordkeepers", payload, headers)

    def list_recordkeepers(self, headers, params=None):
        return self._request("GET", "/recordkeepers", headers=headers, params=params)

    def get_recordkeeper(self, recordkeeper_id, headers):
        return self._request("GET", f"/recordkeepers/{recordkeeper_id}", headers=headers)

    def activate_recordkeeper(self, recordkeeper_id, headers):
        return self._request("POST", f"/recordkeepers/{recordkeeper_id}/activate", headers=headers)

    def suspend_recordkeeper(self, recordkeeper_id, headers):
        return self._request("POST", f"/recordkeepers/{recordkeeper_id}/suspend", headers=headers)

    def exit_recordkeeper(self, recordkeeper_id, headers):
        return self._request("POST", f"/recordkeepers/{recordkeeper_id}/exit", headers=headers)

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def patch_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/plans/{plan_id}", payload, headers)

    def terminate_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/terminate", headers=headers)

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def patch_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"/participants/{participant_id}", payload, headers)

    # ------------------------------------------------------------------
    # Distribution batches
    # ------------------------------------------------------------------
    def create_distribution_batch(self, payload, headers):
        return self._request("POST", "/distribution-batches", payload, headers)

    def list_distribution_batches(self, headers, params=None):
        return self._request("GET", "/distribution-batches", headers=headers, params=params)

    def get_distribution_batch(self, batch_id, headers):
        return self._request("GET", f"/distribution-batches/{batch_id}", headers=headers)

    def lock_distribution_batch(self, batch_id, headers):
        return self._request("POST", f"/distribution-batches/{batch_id}/lock", headers=headers)

    def execute_distribution_batch(self, batch_id, headers):
        return self._request("POST", f"/distribution-batches/{batch_id}/execute", headers=headers)

    def reconcile_distribution_batch(self, batch_id, headers):
        return self._request("POST", f"/distribution-batches/{batch_id}/reconcile", headers=headers)

    def resume_distribution_batch(self, batch_id, headers):
        return self._request("POST", f"/distribution-batches/{batch_id}/resume", headers=headers)

    # ------------------------------------------------------------------
    # Distribution cases
    # ------------------------------------------------------------------
    def create_distribution_case(self, payload, headers):
        return self._request("POST", "/distribution-cases", payload, headers)

    def list_distribution_cases(self, headers, params=None):
        return self._request("GET", "/distribution-cases", headers=headers, params=params)

    def get_distribution_case(self, case_id, headers):
        return self._request("GET", f"/distribution-cases/{case_id}", headers=headers)

    def cancel_distribution_case(self, case_id, headers):
        return self._request("POST", f"/distribution-cases/{case_id}/cancel", headers=headers)

    def settle_direct_rollover(self, case_id, headers):
        return self._request("POST", f"/distribution-cases/{case_id}/settle-direct-rollover", headers=headers)

    # ------------------------------------------------------------------
    # Notices
    # ------------------------------------------------------------------
    def create_notice(self, case_id, payload, headers):
        return self._request("POST", f"/distribution-cases/{case_id}/notices", payload, headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def record_notice_delivery(self, notice_id, payload, headers):
        return self._request("POST", f"/notices/{notice_id}/record-delivery", payload, headers)

    # ------------------------------------------------------------------
    # Elections
    # ------------------------------------------------------------------
    def create_election(self, case_id, payload, headers):
        return self._request("POST", f"/distribution-cases/{case_id}/elections", payload, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/elections", headers=headers, params=params)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/elections/{election_id}", headers=headers)

    def void_election(self, election_id, headers):
        return self._request("POST", f"/elections/{election_id}/void", headers=headers)

    # ------------------------------------------------------------------
    # Safe harbor IRAs
    # ------------------------------------------------------------------
    def create_safe_harbor_ira(self, payload, headers):
        return self._request("POST", "/safe-harbor-iras", payload, headers)

    def list_safe_harbor_iras(self, headers, params=None):
        return self._request("GET", "/safe-harbor-iras", headers=headers, params=params)

    def get_safe_harbor_ira(self, ira_id, headers):
        return self._request("GET", f"/safe-harbor-iras/{ira_id}", headers=headers)

    def close_safe_harbor_ira(self, ira_id, headers):
        return self._request("POST", f"/safe-harbor-iras/{ira_id}/close", headers=headers)

    def assess_ira_fee(self, ira_id, headers):
        return self._request("POST", f"/safe-harbor-iras/{ira_id}/assess-fee", headers=headers)

    # ------------------------------------------------------------------
    # Fee assessments (append-only ledger)
    # ------------------------------------------------------------------
    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", "/fee-assessments", headers=headers, params=params)

    def get_fee_assessment(self, fee_id, headers):
        return self._request("GET", f"/fee-assessments/{fee_id}", headers=headers)

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    def create_check(self, payload, headers):
        return self._request("POST", "/checks", payload, headers)

    def list_checks(self, headers, params=None):
        return self._request("GET", "/checks", headers=headers, params=params)

    def get_check(self, check_id, headers):
        return self._request("GET", f"/checks/{check_id}", headers=headers)

    def record_check_cashed(self, check_id, headers):
        return self._request("POST", f"/checks/{check_id}/record-cashed", headers=headers)

    def void_check(self, check_id, payload, headers):
        return self._request("POST", f"/checks/{check_id}/void", payload, headers)

    def reissue_check(self, check_id, headers):
        return self._request("POST", f"/checks/{check_id}/reissue", headers=headers)

    # ------------------------------------------------------------------
    # Match candidates
    # ------------------------------------------------------------------
    def create_match_search(self, ira_id, payload, headers):
        return self._request("POST", f"/safe-harbor-iras/{ira_id}/match-searches", payload, headers)

    def list_match_candidates(self, headers, params=None):
        return self._request("GET", "/match-candidates", headers=headers, params=params)

    def get_match_candidate(self, match_id, headers):
        return self._request("GET", f"/match-candidates/{match_id}", headers=headers)

    def confirm_match_candidate(self, match_id, headers):
        return self._request("POST", f"/match-candidates/{match_id}/confirm", headers=headers)

    def reject_match_candidate(self, match_id, headers):
        return self._request("POST", f"/match-candidates/{match_id}/reject", headers=headers)

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------
    def create_transfer(self, ira_id, payload, headers):
        return self._request("POST", f"/safe-harbor-iras/{ira_id}/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def record_transfer_response(self, transfer_id, payload, headers):
        return self._request("POST", f"/transfers/{transfer_id}/record-response", payload, headers)

    # ------------------------------------------------------------------
    # Fiduciary reviews
    # ------------------------------------------------------------------
    def create_fiduciary_review(self, payload, headers):
        return self._request("POST", "/fiduciary-reviews", payload, headers)

    def list_fiduciary_reviews(self, headers, params=None):
        return self._request("GET", "/fiduciary-reviews", headers=headers, params=params)

    def get_fiduciary_review(self, review_id, headers):
        return self._request("GET", f"/fiduciary-reviews/{review_id}", headers=headers)

    def record_finding(self, review_id, headers):
        return self._request("POST", f"/fiduciary-reviews/{review_id}/record-finding", headers=headers)

    def verify_remediation(self, review_id, headers):
        return self._request("POST", f"/fiduciary-reviews/{review_id}/verify-remediation", headers=headers)

    def attest_review(self, review_id, headers):
        return self._request("POST", f"/fiduciary-reviews/{review_id}/attest", headers=headers)

    # ------------------------------------------------------------------
    # System / operations
    # ------------------------------------------------------------------
    def run_sweep(self, headers):
        return self._request("POST", "/sweeps/run", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
