"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Reserving segments ---
    def create_segment(self, payload, headers):
        return self._request("POST", "/actuarial/segments", payload, headers)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/actuarial/segments/{segment_id}", headers=headers)

    # --- Catastrophe events ---
    def create_catastrophe_event(self, payload, headers):
        return self._request("POST", "/actuarial/catastrophe-events", payload, headers)

    def list_catastrophe_events(self, segment_id, headers, params=None):
        return self._request(
            "GET", f"/actuarial/segments/{segment_id}/catastrophe-events",
            headers=headers, params=params,
        )

    # --- Claims and the transaction ledger ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/actuarial/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/actuarial/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/actuarial/claims", headers=headers, params=params)

    def patch_claim(self, claim_id, payload, headers):
        return self._request("PATCH", f"/actuarial/claims/{claim_id}", payload, headers)

    def set_claim_status(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/actuarial/claims/{claim_id}/status", payload, headers
        )

    def post_claim_transaction(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/actuarial/claims/{claim_id}/transactions", payload, headers
        )

    def list_claim_transactions(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/actuarial/claims/{claim_id}/transactions",
            headers=headers, params=params,
        )

    # --- Loss triangles ---
    def create_triangle(self, payload, headers):
        return self._request("POST", "/actuarial/triangles", payload, headers)

    def get_triangle(self, triangle_id, headers):
        return self._request("GET", f"/actuarial/triangles/{triangle_id}", headers=headers)

    def list_triangles(self, headers, params=None):
        return self._request("GET", "/actuarial/triangles", headers=headers, params=params)

    # --- Development patterns ---
    def create_development_pattern(self, payload, headers):
        return self._request("POST", "/actuarial/development-patterns", payload, headers)

    def get_development_pattern(self, pattern_id, headers):
        return self._request(
            "GET", f"/actuarial/development-patterns/{pattern_id}", headers=headers
        )

    def list_development_patterns(self, headers, params=None):
        return self._request(
            "GET", "/actuarial/development-patterns", headers=headers, params=params
        )

    def select_development_pattern(self, pattern_id, headers):
        return self._request(
            "POST", f"/actuarial/development-patterns/{pattern_id}/select",
            headers=headers,
        )

    def withdraw_development_pattern(self, pattern_id, headers):
        return self._request(
            "POST", f"/actuarial/development-patterns/{pattern_id}/withdraw",
            headers=headers,
        )

    # --- Reserve runs ---
    def create_reserve_run(self, payload, headers):
        return self._request("POST", "/actuarial/reserve-runs", payload, headers)

    def get_reserve_run(self, run_id, headers):
        return self._request("GET", f"/actuarial/reserve-runs/{run_id}", headers=headers)

    def list_reserve_runs(self, headers, params=None):
        return self._request("GET", "/actuarial/reserve-runs", headers=headers, params=params)

    # --- Reserving studies ---
    def create_study(self, payload, headers):
        return self._request("POST", "/actuarial/studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/actuarial/studies/{study_id}", headers=headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/actuarial/studies", headers=headers, params=params)

    def patch_study(self, study_id, payload, headers):
        return self._request("PATCH", f"/actuarial/studies/{study_id}", payload, headers)

    def submit_study(self, study_id, headers):
        return self._request("POST", f"/actuarial/studies/{study_id}/submit", headers=headers)

    def review_study(self, study_id, payload, headers):
        return self._request("POST", f"/actuarial/studies/{study_id}/review", payload, headers)

    def withdraw_study(self, study_id, headers):
        return self._request("POST", f"/actuarial/studies/{study_id}/withdraw", headers=headers)

    # --- Actuarial opinions ---
    def create_opinion(self, payload, headers):
        return self._request("POST", "/actuarial/opinions", payload, headers)

    def get_opinion(self, opinion_id, headers):
        return self._request("GET", f"/actuarial/opinions/{opinion_id}", headers=headers)

    def attach_study(self, opinion_id, payload, headers):
        return self._request(
            "POST", f"/actuarial/opinions/{opinion_id}/attach-study", payload, headers
        )

    def sign_opinion(self, opinion_id, headers):
        return self._request("POST", f"/actuarial/opinions/{opinion_id}/sign", headers=headers)

    # --- Roll-forwards ---
    def create_roll_forward(self, payload, headers):
        return self._request("POST", "/actuarial/roll-forwards", payload, headers)

    def list_roll_forwards(self, segment_id, headers, params=None):
        return self._request(
            "GET", f"/actuarial/segments/{segment_id}/roll-forwards",
            headers=headers, params=params,
        )

    # --- Logical clock (test-driving endpoint, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/actuarial/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
