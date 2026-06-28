"""API client: one method per endpoint defined in the Yearbook Production PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Yearbook (root) ──────────────────────────────────────────────────────
    def create_yearbook(self, payload, headers):
        return self._request("POST", "/yearbooks", payload, headers)

    def get_yearbook(self, yearbook_id, headers):
        return self._request("GET", f"/yearbooks/{yearbook_id}", headers=headers)

    def list_yearbooks(self, headers, params=None):
        return self._request("GET", "/yearbooks", headers=headers, params=params)

    def get_cost_estimate(self, yearbook_id, headers):
        return self._request(
            "GET", f"/yearbooks/{yearbook_id}/cost-estimate", headers=headers
        )

    # ─── LadderPage ───────────────────────────────────────────────────────────
    def create_page(self, payload, headers):
        return self._request("POST", "/yearbooks/pages", payload, headers)

    def get_page(self, page_id, headers):
        return self._request("GET", f"/yearbooks/pages/{page_id}", headers=headers)

    def list_pages(self, headers, params=None):
        return self._request("GET", "/yearbooks/pages", headers=headers, params=params)

    def assign_page(self, page_id, payload, headers):
        return self._request(
            "POST", f"/yearbooks/pages/{page_id}/assign", payload, headers
        )

    def submit_review_page(self, page_id, headers):
        return self._request(
            "POST", f"/yearbooks/pages/{page_id}/submit-review", headers=headers
        )

    def request_changes_page(self, page_id, headers):
        return self._request(
            "POST", f"/yearbooks/pages/{page_id}/request-changes", headers=headers
        )

    def approve_page(self, page_id, headers):
        return self._request(
            "POST", f"/yearbooks/pages/{page_id}/approve", headers=headers
        )

    # ─── Submission ───────────────────────────────────────────────────────────
    def create_submission(self, payload, headers):
        return self._request("POST", "/yearbooks/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/yearbooks/submissions/{submission_id}", headers=headers
        )

    def list_submissions(self, headers, params=None):
        return self._request(
            "GET", "/yearbooks/submissions", headers=headers, params=params
        )

    def approve_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/yearbooks/submissions/{submission_id}/approve", payload, headers
        )

    def reject_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/yearbooks/submissions/{submission_id}/reject", payload, headers
        )

    def resubmit_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/yearbooks/submissions/{submission_id}/resubmit", payload, headers
        )

    # ─── StaffAssignment ──────────────────────────────────────────────────────
    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/yearbooks/staff-assignments", payload, headers)

    def get_staff_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/yearbooks/staff-assignments/{assignment_id}", headers=headers
        )

    def list_staff_assignments(self, headers, params=None):
        return self._request(
            "GET", "/yearbooks/staff-assignments", headers=headers, params=params
        )

    def release_staff_assignment(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/yearbooks/staff-assignments/{assignment_id}/release",
            headers=headers,
        )

    # ─── AdContract ───────────────────────────────────────────────────────────
    def create_ad_contract(self, payload, headers):
        return self._request("POST", "/yearbooks/ad-contracts", payload, headers)

    def get_ad_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/yearbooks/ad-contracts/{contract_id}", headers=headers
        )

    def list_ad_contracts(self, headers, params=None):
        return self._request(
            "GET", "/yearbooks/ad-contracts", headers=headers, params=params
        )

    def sign_ad_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/yearbooks/ad-contracts/{contract_id}/sign", headers=headers
        )

    def place_ad_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/yearbooks/ad-contracts/{contract_id}/place", headers=headers
        )

    def void_ad_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/yearbooks/ad-contracts/{contract_id}/void", headers=headers
        )

    # ─── Proof ────────────────────────────────────────────────────────────────
    def create_proof(self, payload, headers):
        return self._request("POST", "/yearbooks/proofs", payload, headers)

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/yearbooks/proofs/{proof_id}", headers=headers)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/yearbooks/proofs", headers=headers, params=params)

    def request_changes_proof(self, proof_id, payload, headers):
        return self._request(
            "POST", f"/yearbooks/proofs/{proof_id}/request-changes", payload, headers
        )

    def reopen_proof(self, proof_id, headers):
        return self._request(
            "POST", f"/yearbooks/proofs/{proof_id}/reopen", headers=headers
        )

    def submit_plant_proof(self, proof_id, headers):
        return self._request(
            "POST", f"/yearbooks/proofs/{proof_id}/submit-plant", headers=headers
        )

    def approve_plant_proof(self, proof_id, headers):
        return self._request(
            "POST", f"/yearbooks/proofs/{proof_id}/approve-plant", headers=headers
        )

    # ─── PreSaleOrder ─────────────────────────────────────────────────────────
    def create_presale_order(self, payload, headers):
        return self._request("POST", "/yearbooks/presale-orders", payload, headers)

    def get_presale_order(self, order_id, headers):
        return self._request(
            "GET", f"/yearbooks/presale-orders/{order_id}", headers=headers
        )

    def list_presale_orders(self, headers, params=None):
        return self._request(
            "GET", "/yearbooks/presale-orders", headers=headers, params=params
        )

    def pay_presale_order(self, order_id, headers):
        return self._request(
            "POST", f"/yearbooks/presale-orders/{order_id}/pay", headers=headers
        )

    def cancel_presale_order(self, order_id, headers):
        return self._request(
            "POST", f"/yearbooks/presale-orders/{order_id}/cancel", headers=headers
        )

    # ─── PrintRun ─────────────────────────────────────────────────────────────
    def create_print_run(self, payload, headers):
        return self._request("POST", "/yearbooks/print-runs", payload, headers)

    def get_print_run(self, print_run_id, headers):
        return self._request(
            "GET", f"/yearbooks/print-runs/{print_run_id}", headers=headers
        )

    def list_print_runs(self, headers, params=None):
        return self._request(
            "GET", "/yearbooks/print-runs", headers=headers, params=params
        )

    def ship_print_run(self, print_run_id, headers):
        return self._request(
            "POST", f"/yearbooks/print-runs/{print_run_id}/ship", headers=headers
        )

    def deliver_print_run(self, print_run_id, headers):
        return self._request(
            "POST", f"/yearbooks/print-runs/{print_run_id}/deliver", headers=headers
        )

    # ─── DistributionRecord ───────────────────────────────────────────────────
    def get_distribution_record(self, record_id, headers):
        return self._request(
            "GET", f"/yearbooks/distribution-records/{record_id}", headers=headers
        )

    def list_distribution_records(self, headers, params=None):
        return self._request(
            "GET", "/yearbooks/distribution-records", headers=headers, params=params
        )


api_client = ApiClient()
