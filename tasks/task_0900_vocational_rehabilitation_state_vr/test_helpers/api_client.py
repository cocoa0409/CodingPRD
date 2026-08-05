"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/vr/_clock/set_current_utc", payload, headers)

    # ---- Actors / config ----
    def create_counselor(self, payload, headers):
        return self._request("POST", "/vr/counselors", payload, headers)

    def create_supervisor(self, payload, headers):
        return self._request("POST", "/vr/supervisors", payload, headers)

    def create_provider(self, payload, headers):
        return self._request("POST", "/vr/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/vr/providers/{provider_id}", headers=headers)

    def create_priority_category(self, payload, headers):
        return self._request("POST", "/vr/priority-categories", payload, headers)

    def get_priority_category(self, category_id, headers):
        return self._request("GET", f"/vr/priority-categories/{category_id}", headers=headers)

    def list_priority_categories(self, headers, params=None):
        return self._request("GET", "/vr/priority-categories", headers=headers, params=params)

    def patch_priority_category(self, category_id, payload, headers):
        return self._request("PATCH", f"/vr/priority-categories/{category_id}", payload, headers)

    def promote_next(self, category_id, headers):
        return self._request("POST", f"/vr/priority-categories/{category_id}/promote-next", headers=headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/vr/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/vr/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/vr/cases", headers=headers, params=params)

    def record_application(self, case_id, headers):
        return self._request("POST", f"/vr/cases/{case_id}/application", {}, headers)

    def record_eligibility(self, case_id, payload, headers):
        return self._request("POST", f"/vr/cases/{case_id}/eligibility", payload, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/vr/cases/{case_id}/close", payload, headers)

    def get_rsa911(self, case_id, headers):
        return self._request("GET", f"/vr/cases/{case_id}/rsa911", headers=headers)

    # ---- IPE ----
    def create_ipe(self, payload, headers):
        return self._request("POST", "/vr/ipes", payload, headers)

    def get_ipe(self, ipe_id, headers):
        return self._request("GET", f"/vr/ipes/{ipe_id}", headers=headers)

    def list_ipes(self, headers, params=None):
        return self._request("GET", "/vr/ipes", headers=headers, params=params)

    def submit_ipe(self, ipe_id, headers):
        return self._request("POST", f"/vr/ipes/{ipe_id}/submit", {}, headers)

    def approve_ipe(self, ipe_id, headers):
        return self._request("POST", f"/vr/ipes/{ipe_id}/approve", {}, headers)

    def return_ipe(self, ipe_id, headers):
        return self._request("POST", f"/vr/ipes/{ipe_id}/return", {}, headers)

    def amend_ipe(self, ipe_id, headers):
        return self._request("POST", f"/vr/ipes/{ipe_id}/amend", {}, headers)

    # ---- ServiceAuthorization ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/vr/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/vr/authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/vr/authorizations", headers=headers, params=params)

    def approve_authorization(self, authorization_id, payload, headers):
        return self._request("POST", f"/vr/authorizations/{authorization_id}/approve", payload, headers)

    def complete_authorization(self, authorization_id, headers):
        return self._request("POST", f"/vr/authorizations/{authorization_id}/complete", {}, headers)

    def cancel_authorization(self, authorization_id, headers):
        return self._request("POST", f"/vr/authorizations/{authorization_id}/cancel", {}, headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/vr/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/vr/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/vr/payments", headers=headers, params=params)

    def issue_payment(self, payment_id, headers):
        return self._request("POST", f"/vr/payments/{payment_id}/issue", {}, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/vr/payments/{payment_id}/void", {}, headers)

    # ---- Placement ----
    def create_placement(self, payload, headers):
        return self._request("POST", "/vr/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/vr/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/vr/placements", headers=headers, params=params)

    def begin_stabilization(self, placement_id, headers):
        return self._request("POST", f"/vr/placements/{placement_id}/begin-stabilization", {}, headers)

    def report_loss(self, placement_id, headers):
        return self._request("POST", f"/vr/placements/{placement_id}/report-loss", {}, headers)

    def resume_stabilization(self, placement_id, headers):
        return self._request("POST", f"/vr/placements/{placement_id}/resume", {}, headers)

    def verify_stability(self, placement_id, headers):
        return self._request("POST", f"/vr/placements/{placement_id}/verify-stability", {}, headers)

    # ---- ProgressReview ----
    def create_progress_review(self, payload, headers):
        return self._request("POST", "/vr/progress-reviews", payload, headers)

    def list_progress_reviews(self, placement_id, headers, params=None):
        return self._request("GET", f"/vr/placements/{placement_id}/progress-reviews", headers=headers, params=params)


api_client = ApiClient()
