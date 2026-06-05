"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Policies & Coverages ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", headers=headers)

    def create_coverage(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/coverages", payload, headers)

    def list_coverages(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/coverages", headers=headers, params=params)

    # ---- Adjusters ----
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/adjusters", payload, headers)

    def get_adjuster(self, adjuster_id, headers):
        return self._request("GET", f"/adjusters/{adjuster_id}", headers=headers)

    # ---- Claims (FNOL lifecycle) ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def verify_coverage(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/verify-coverage", headers=headers)

    def assign_adjuster(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/assign-adjuster", payload, headers)

    def decide_disposition(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/decide-disposition", payload, headers)

    def settle_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/settle", payload, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", headers=headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", headers=headers)

    def get_ledger(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/ledger", headers=headers)

    def list_coverage_verifications(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/coverage-verifications", headers=headers, params=params)

    def list_claim_parties(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/parties", headers=headers, params=params)

    def list_claim_disbursements(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/disbursements", headers=headers, params=params)

    # ---- Claim parties ----
    def create_claim_party(self, payload, headers):
        return self._request("POST", "/claim-parties", payload, headers)

    # ---- Repair estimates ----
    def create_repair_estimate(self, payload, headers):
        return self._request("POST", "/repair-estimates", payload, headers)

    def get_repair_estimate(self, estimate_id, headers):
        return self._request("GET", f"/repair-estimates/{estimate_id}", headers=headers)

    def list_repair_estimates(self, headers, params=None):
        return self._request("GET", "/repair-estimates", headers=headers, params=params)

    def submit_repair_estimate(self, estimate_id, headers):
        return self._request("POST", f"/repair-estimates/{estimate_id}/submit", headers=headers)

    # ---- Total-loss evaluations ----
    def create_total_loss_evaluation(self, payload, headers):
        return self._request("POST", "/total-loss-evaluations", payload, headers)

    def get_total_loss_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/total-loss-evaluations/{evaluation_id}", headers=headers)

    def list_total_loss_evaluations(self, headers, params=None):
        return self._request("GET", "/total-loss-evaluations", headers=headers, params=params)

    # ---- Rental reimbursements ----
    def create_rental_reimbursement(self, payload, headers):
        return self._request("POST", "/rental-reimbursements", payload, headers)

    def get_rental_reimbursement(self, rental_id, headers):
        return self._request("GET", f"/rental-reimbursements/{rental_id}", headers=headers)

    def list_rental_reimbursements(self, headers, params=None):
        return self._request("GET", "/rental-reimbursements", headers=headers, params=params)

    def approve_rental_reimbursement(self, rental_id, headers):
        return self._request("POST", f"/rental-reimbursements/{rental_id}/approve", headers=headers)

    def reject_rental_reimbursement(self, rental_id, headers):
        return self._request("POST", f"/rental-reimbursements/{rental_id}/reject", headers=headers)

    # ---- Subrogation ----
    def create_subrogation_case(self, payload, headers):
        return self._request("POST", "/subrogation-cases", payload, headers)

    def get_subrogation_case(self, case_id, headers):
        return self._request("GET", f"/subrogation-cases/{case_id}", headers=headers)

    def list_subrogation_cases(self, headers, params=None):
        return self._request("GET", "/subrogation-cases", headers=headers, params=params)

    def send_demand(self, case_id, payload, headers):
        return self._request("POST", f"/subrogation-cases/{case_id}/send-demand", payload, headers)

    def begin_negotiation(self, case_id, headers):
        return self._request("POST", f"/subrogation-cases/{case_id}/begin-negotiation", headers=headers)

    def resolve_subrogation_case(self, case_id, payload, headers):
        return self._request("POST", f"/subrogation-cases/{case_id}/resolve", payload, headers)

    # ---- Disbursements ----
    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/void", headers=headers)


api_client = ApiClient()
