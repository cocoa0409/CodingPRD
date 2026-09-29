"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Trade areas ----
    def create_market_area(self, payload, headers):
        return self._request("POST", "/distribution/market-areas", payload, headers)

    def get_market_area(self, market_area_id, headers):
        return self._request(
            "GET", f"/distribution/market-areas/{market_area_id}", headers=headers
        )

    def list_market_areas(self, headers, params=None):
        return self._request(
            "GET", "/distribution/market-areas", headers=headers, params=params
        )

    # ---- Branches ----
    def create_branch(self, payload, headers):
        return self._request("POST", "/distribution/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request(
            "GET", f"/distribution/branches/{branch_id}", headers=headers
        )

    def list_branches(self, headers, params=None):
        return self._request(
            "GET", "/distribution/branches", headers=headers, params=params
        )

    # ---- Performance snapshots ----
    def create_performance_snapshot(self, branch_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/branches/{branch_id}/performance-snapshots",
            payload,
            headers,
        )

    def list_branch_performance_snapshots(self, branch_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution/branches/{branch_id}/performance-snapshots",
            headers=headers,
            params=params,
        )

    def get_performance_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET",
            f"/distribution/performance-snapshots/{snapshot_id}",
            headers=headers,
        )

    def list_performance_snapshots(self, headers, params=None):
        return self._request(
            "GET",
            "/distribution/performance-snapshots",
            headers=headers,
            params=params,
        )

    def get_branch_performance_score(self, branch_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution/branches/{branch_id}/performance-score",
            headers=headers,
            params=params,
        )

    # ---- Consolidation cases ----
    def create_consolidation_case(self, payload, headers):
        return self._request(
            "POST", "/distribution/consolidation-cases", payload, headers
        )

    def get_consolidation_case(self, case_id, headers):
        return self._request(
            "GET", f"/distribution/consolidation-cases/{case_id}", headers=headers
        )

    def list_consolidation_cases(self, headers, params=None):
        return self._request(
            "GET", "/distribution/consolidation-cases", headers=headers, params=params
        )

    def submit_consolidation_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/submit",
            payload,
            headers,
        )

    def decide_consolidation_case(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/decision",
            payload,
            headers,
        )

    def revise_consolidation_case(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/revise",
            payload,
            headers,
        )

    def execute_closure(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/execute-closure",
            payload,
            headers,
        )

    def unwind_closure(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/unwind-closure",
            payload,
            headers,
        )

    def close_out_consolidation_case(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/close-out",
            payload,
            headers,
        )

    # ---- Retention forecasts ----
    def create_retention_forecast(self, payload, headers):
        return self._request(
            "POST", "/distribution/retention-forecasts", payload, headers
        )

    def list_case_retention_forecasts(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution/consolidation-cases/{case_id}/retention-forecasts",
            headers=headers,
            params=params,
        )

    def get_retention_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/distribution/retention-forecasts/{forecast_id}", headers=headers
        )

    def list_retention_forecasts(self, headers, params=None):
        return self._request(
            "GET", "/distribution/retention-forecasts", headers=headers, params=params
        )

    # ---- Community impact assessments ----
    def create_impact_assessment(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/consolidation-cases/{case_id}/impact-assessments",
            payload,
            headers,
        )

    def list_case_impact_assessments(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution/consolidation-cases/{case_id}/impact-assessments",
            headers=headers,
            params=params,
        )

    def get_impact_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/distribution/impact-assessments/{assessment_id}", headers=headers
        )

    def list_impact_assessments(self, headers, params=None):
        return self._request(
            "GET", "/distribution/impact-assessments", headers=headers, params=params
        )

    def finalize_impact_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/impact-assessments/{assessment_id}/finalize",
            payload,
            headers,
        )

    # ---- Closure notices ----
    def create_closure_notice(self, payload, headers):
        return self._request("POST", "/distribution/closure-notices", payload, headers)

    def list_case_closure_notices(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution/consolidation-cases/{case_id}/closure-notices",
            headers=headers,
            params=params,
        )

    def get_closure_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/distribution/closure-notices/{notice_id}", headers=headers
        )

    def list_closure_notices(self, headers, params=None):
        return self._request(
            "GET", "/distribution/closure-notices", headers=headers, params=params
        )

    def withdraw_closure_notice(self, notice_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/closure-notices/{notice_id}/withdraw",
            payload,
            headers,
        )

    # ---- Staff dispositions ----
    def create_staff_disposition(self, payload, headers):
        return self._request(
            "POST", "/distribution/staff-dispositions", payload, headers
        )

    def get_staff_disposition(self, disposition_id, headers):
        return self._request(
            "GET", f"/distribution/staff-dispositions/{disposition_id}", headers=headers
        )

    def list_staff_dispositions(self, headers, params=None):
        return self._request(
            "GET", "/distribution/staff-dispositions", headers=headers, params=params
        )

    def notify_staff_disposition(self, disposition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/staff-dispositions/{disposition_id}/notify",
            payload,
            headers,
        )

    def accept_staff_disposition(self, disposition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/staff-dispositions/{disposition_id}/accept",
            payload,
            headers,
        )

    def rescind_staff_disposition(self, disposition_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/staff-dispositions/{disposition_id}/rescind",
            payload,
            headers,
        )

    def sever_staff_disposition(self, disposition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/staff-dispositions/{disposition_id}/sever",
            payload,
            headers,
        )

    # ---- Property dispositions ----
    def create_property_disposition(self, payload, headers):
        return self._request(
            "POST", "/distribution/property-dispositions", payload, headers
        )

    def get_property_disposition(self, disposition_id, headers):
        return self._request(
            "GET",
            f"/distribution/property-dispositions/{disposition_id}",
            headers=headers,
        )

    def list_property_dispositions(self, headers, params=None):
        return self._request(
            "GET", "/distribution/property-dispositions", headers=headers, params=params
        )

    def contract_property_disposition(self, disposition_id, payload, headers):
        return self._request(
            "POST",
            f"/distribution/property-dispositions/{disposition_id}/contract",
            payload,
            headers,
        )

    def settle_property_disposition(self, disposition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/property-dispositions/{disposition_id}/settle",
            payload,
            headers,
        )

    # ---- Customer transition campaigns ----
    def create_transition_campaign(self, payload, headers):
        return self._request(
            "POST", "/distribution/transition-campaigns", payload, headers
        )

    def get_transition_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/distribution/transition-campaigns/{campaign_id}", headers=headers
        )

    def list_transition_campaigns(self, headers, params=None):
        return self._request(
            "GET", "/distribution/transition-campaigns", headers=headers, params=params
        )

    def launch_transition_campaign(self, campaign_id, headers, payload=None):
        return self._request(
            "POST",
            f"/distribution/transition-campaigns/{campaign_id}/launch",
            payload,
            headers,
        )

    # ---- De novo site plans ----
    def create_de_novo_plan(self, payload, headers):
        return self._request("POST", "/distribution/de-novo-plans", payload, headers)

    def get_de_novo_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/distribution/de-novo-plans/{plan_id}", headers=headers
        )

    def list_de_novo_plans(self, headers, params=None):
        return self._request(
            "GET", "/distribution/de-novo-plans", headers=headers, params=params
        )

    def decide_de_novo_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/distribution/de-novo-plans/{plan_id}/decision", payload, headers
        )

    def open_de_novo_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/distribution/de-novo-plans/{plan_id}/open", payload, headers
        )

    # ---- Deposit observations ----
    def create_deposit_observation(self, payload, headers):
        return self._request(
            "POST", "/distribution/deposit-observations", payload, headers
        )

    def get_deposit_observation(self, observation_id, headers):
        return self._request(
            "GET",
            f"/distribution/deposit-observations/{observation_id}",
            headers=headers,
        )

    def list_deposit_observations(self, headers, params=None):
        return self._request(
            "GET", "/distribution/deposit-observations", headers=headers, params=params
        )

    # ---- The logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
