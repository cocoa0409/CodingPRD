"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the ``/market-conduct`` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/market-conduct"


class ApiClient(GenericApiClient):
    # ── Carriers ────────────────────────────────────────────────────────
    def register_insurer(self, payload, headers):
        return self._request("POST", f"{BASE}/insurers", payload, headers)

    def list_insurers(self, headers, params=None):
        return self._request("GET", f"{BASE}/insurers", headers=headers, params=params)

    def get_insurer(self, insurer_id, headers):
        return self._request("GET", f"{BASE}/insurers/{insurer_id}", headers=headers)

    def refresh_market_data(self, insurer_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/insurers/{insurer_id}/market-data", payload, headers
        )

    def list_insurer_analysis_scores(self, insurer_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/insurers/{insurer_id}/analysis-scores",
            headers=headers,
            params=params,
        )

    # ── Analysis cycles ─────────────────────────────────────────────────
    def create_analysis_cycle(self, payload, headers):
        return self._request("POST", f"{BASE}/analysis-cycles", payload, headers)

    def list_analysis_cycles(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/analysis-cycles", headers=headers, params=params
        )

    def get_analysis_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"{BASE}/analysis-cycles/{cycle_id}", headers=headers
        )

    def score_analysis_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/analysis-cycles/{cycle_id}/score", payload, headers
        )

    def list_cycle_scores(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/analysis-cycles/{cycle_id}/scores",
            headers=headers,
            params=params,
        )

    def select_targets(self, cycle_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/analysis-cycles/{cycle_id}/select-targets",
            payload,
            headers,
        )

    # ── Examinations ────────────────────────────────────────────────────
    def open_examination(self, payload, headers):
        return self._request("POST", f"{BASE}/examinations", payload, headers)

    def list_examinations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/examinations", headers=headers, params=params
        )

    def get_examination(self, exam_id, headers):
        return self._request("GET", f"{BASE}/examinations/{exam_id}", headers=headers)

    def create_scope_area(self, exam_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/examinations/{exam_id}/scope-areas", payload, headers
        )

    def list_scope_areas(self, exam_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/examinations/{exam_id}/scope-areas",
            headers=headers,
            params=params,
        )

    def lock_scope(self, exam_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/examinations/{exam_id}/lock-scope", payload, headers
        )

    def create_fieldwork_activity(self, exam_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/examinations/{exam_id}/fieldwork-activities",
            payload,
            headers,
        )

    def list_fieldwork_activities(self, exam_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/examinations/{exam_id}/fieldwork-activities",
            headers=headers,
            params=params,
        )

    def get_exposure_summary(self, exam_id, headers):
        return self._request(
            "GET", f"{BASE}/examinations/{exam_id}/exposure-summary", headers=headers
        )

    def publish_report(self, exam_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/examinations/{exam_id}/publish-report", payload, headers
        )

    def abort_examination(self, exam_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/examinations/{exam_id}/abort", payload, headers
        )

    # ── Scope areas ─────────────────────────────────────────────────────
    def get_scope_area(self, scope_area_id, headers):
        return self._request(
            "GET", f"{BASE}/scope-areas/{scope_area_id}", headers=headers
        )

    def create_data_call(self, scope_area_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/scope-areas/{scope_area_id}/data-calls", payload, headers
        )

    def list_scope_area_data_calls(self, scope_area_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/scope-areas/{scope_area_id}/data-calls",
            headers=headers,
            params=params,
        )

    # ── Data calls ──────────────────────────────────────────────────────
    def get_data_call(self, data_call_id, headers):
        return self._request(
            "GET", f"{BASE}/data-calls/{data_call_id}", headers=headers
        )

    def respond_to_data_call(self, data_call_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/data-calls/{data_call_id}/respond", payload, headers
        )

    def disposition_data_call(self, data_call_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/data-calls/{data_call_id}/disposition", payload, headers
        )

    def list_file_samples(self, data_call_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/data-calls/{data_call_id}/file-samples",
            headers=headers,
            params=params,
        )

    def bulk_review(self, data_call_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/data-calls/{data_call_id}/bulk-review", payload, headers
        )

    # ── File samples ────────────────────────────────────────────────────
    def get_file_sample(self, file_sample_id, headers):
        return self._request(
            "GET", f"{BASE}/file-samples/{file_sample_id}", headers=headers
        )

    def review_file_sample(self, file_sample_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/file-samples/{file_sample_id}/review", payload, headers
        )

    # ── Criticisms ──────────────────────────────────────────────────────
    def issue_criticism(self, payload, headers):
        return self._request("POST", f"{BASE}/criticisms", payload, headers)

    def list_criticisms(self, headers, params=None):
        return self._request("GET", f"{BASE}/criticisms", headers=headers, params=params)

    def get_criticism(self, criticism_id, headers):
        return self._request(
            "GET", f"{BASE}/criticisms/{criticism_id}", headers=headers
        )

    def create_company_response(self, criticism_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/criticisms/{criticism_id}/responses", payload, headers
        )

    def list_company_responses(self, criticism_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/criticisms/{criticism_id}/responses",
            headers=headers,
            params=params,
        )

    def rebut_criticism(self, criticism_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/criticisms/{criticism_id}/rebut", payload, headers
        )

    def finalize_criticism(self, criticism_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/criticisms/{criticism_id}/finalize", payload, headers
        )

    # ── Corrective action plans ─────────────────────────────────────────
    def propose_corrective_action_plan(self, exam_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/examinations/{exam_id}/corrective-action-plans",
            payload,
            headers,
        )

    def list_corrective_action_plans(self, exam_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/examinations/{exam_id}/corrective-action-plans",
            headers=headers,
            params=params,
        )

    def get_corrective_action_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{BASE}/corrective-action-plans/{plan_id}", headers=headers
        )

    def review_corrective_action_plan(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/corrective-action-plans/{plan_id}/review",
            payload,
            headers,
        )

    # ── Consent orders ──────────────────────────────────────────────────
    def draft_consent_order(self, exam_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/examinations/{exam_id}/consent-orders", payload, headers
        )

    def list_consent_orders(self, exam_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/examinations/{exam_id}/consent-orders",
            headers=headers,
            params=params,
        )

    def get_consent_order(self, order_id, headers):
        return self._request(
            "GET", f"{BASE}/consent-orders/{order_id}", headers=headers
        )

    def execute_consent_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/consent-orders/{order_id}/execute", payload, headers
        )

    # ── Multistate collaboration ────────────────────────────────────────
    def open_collaboration(self, exam_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/examinations/{exam_id}/collaborations", payload, headers
        )

    def list_collaborations(self, exam_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/examinations/{exam_id}/collaborations",
            headers=headers,
            params=params,
        )

    def get_collaboration(self, collaboration_id, headers):
        return self._request(
            "GET", f"{BASE}/collaborations/{collaboration_id}", headers=headers
        )

    def allocate_restitution(self, collaboration_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/collaborations/{collaboration_id}/allocate-restitution",
            payload,
            headers,
        )

    # ── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, payload, headers=None):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
