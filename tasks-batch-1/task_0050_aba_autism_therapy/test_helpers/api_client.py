"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Payer ----
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def discharge_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/discharge", {}, headers)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def deactivate_provider(self, provider_id, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/deactivate", {}, headers
        )

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    # ---- DiagnosticEvaluation ----
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/diagnostic-evaluations", payload, headers)

    def get_evaluation(self, eval_id, headers):
        return self._request(
            "GET", f"/diagnostic-evaluations/{eval_id}", headers=headers
        )

    def list_evaluations(self, headers, params=None):
        return self._request(
            "GET", "/diagnostic-evaluations", headers=headers, params=params
        )

    def submit_evaluation(self, eval_id, headers):
        return self._request(
            "POST", f"/diagnostic-evaluations/{eval_id}/submit", {}, headers
        )

    def review_evaluation(self, eval_id, decision, headers):
        return self._request(
            "POST",
            f"/diagnostic-evaluations/{eval_id}/review",
            {"decision": decision},
            headers,
        )

    # ---- TreatmentPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/submit", {}, headers)

    def review_plan(self, plan_id, decision, headers):
        return self._request(
            "POST",
            f"/treatment-plans/{plan_id}/review",
            {"decision": decision},
            headers,
        )

    # ---- Authorization ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/authorizations", payload, headers)

    def get_authorization(self, auth_id, headers):
        return self._request("GET", f"/authorizations/{auth_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def renew_authorization(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/authorizations/{auth_id}/renew", payload, headers
        )

    def close_authorization(self, auth_id, headers):
        return self._request(
            "POST", f"/authorizations/{auth_id}/close", {}, headers
        )

    # ---- TherapySession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/therapy-sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/therapy-sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/therapy-sessions", headers=headers, params=params)

    def deliver_session(self, session_id, delivered_units, headers):
        return self._request(
            "POST",
            f"/therapy-sessions/{session_id}/deliver",
            {"delivered_units": delivered_units},
            headers,
        )

    def no_show_session(self, session_id, headers):
        return self._request(
            "POST", f"/therapy-sessions/{session_id}/no-show", {}, headers
        )

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/therapy-sessions/{session_id}/cancel", {}, headers
        )

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/adjudicate", payload, headers
        )

    # ---- Generic raw helpers (for header-omission / malformed tests) ----
    def raw_get(self, path, headers):
        return self._request("GET", path, headers=headers)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
