"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # State reserve rules
    # ------------------------------------------------------------------
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/state-reserve-rules", payload, headers)

    # ------------------------------------------------------------------
    # Associations
    # ------------------------------------------------------------------
    def create_association(self, payload, headers):
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/associations/{association_id}", headers=headers)

    def run_annual_update(self, association_id, headers):
        return self._request("POST", f"/associations/{association_id}/annual-update",
                             {}, headers)

    # ------------------------------------------------------------------
    # Reserve studies
    # ------------------------------------------------------------------
    def create_study(self, payload, headers):
        return self._request("POST", "/reserve-studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/reserve-studies/{study_id}", headers=headers)

    def list_association_studies(self, association_id, headers, params=None):
        return self._request("GET", f"/associations/{association_id}/reserve-studies",
                             headers=headers, params=params)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/reserve-studies", headers=headers, params=params)

    def submit_study(self, study_id, headers):
        return self._request("POST", f"/reserve-studies/{study_id}/submit", {}, headers)

    def adopt_study(self, study_id, headers):
        return self._request("POST", f"/reserve-studies/{study_id}/adopt", {}, headers)

    def reject_study(self, study_id, headers, reason=None):
        payload = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"/reserve-studies/{study_id}/reject",
                             payload, headers)

    def withdraw_study(self, study_id, headers):
        return self._request("POST", f"/reserve-studies/{study_id}/withdraw", {}, headers)

    def get_special_assessment_analysis(self, study_id, headers):
        return self._request(
            "GET", f"/reserve-studies/{study_id}/special-assessment-analysis",
            headers=headers)

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------
    def create_component(self, payload, headers):
        return self._request("POST", "/components", payload, headers)

    def list_components(self, study_id, headers, params=None):
        return self._request("GET", f"/reserve-studies/{study_id}/components",
                             headers=headers, params=params)

    def patch_component(self, component_id, payload, headers):
        return self._request("PATCH", f"/components/{component_id}", payload, headers)

    def retire_component(self, component_id, headers):
        return self._request("POST", f"/components/{component_id}/retire", {}, headers)

    def restore_component(self, component_id, headers):
        return self._request("POST", f"/components/{component_id}/restore", {}, headers)

    # ------------------------------------------------------------------
    # Funding plans
    # ------------------------------------------------------------------
    def create_funding_plan(self, study_id, payload, headers):
        return self._request("POST", f"/reserve-studies/{study_id}/funding-plans",
                             payload, headers)

    def list_funding_plans(self, study_id, headers, params=None):
        return self._request("GET", f"/reserve-studies/{study_id}/funding-plans",
                             headers=headers, params=params)

    def recommend_plan(self, plan_id, headers):
        return self._request("POST", f"/funding-plans/{plan_id}/recommend", {}, headers)

    def select_plan(self, plan_id, headers):
        return self._request("POST", f"/funding-plans/{plan_id}/select", {}, headers)

    # ------------------------------------------------------------------
    # Site visits
    # ------------------------------------------------------------------
    def create_site_visit(self, payload, headers):
        return self._request("POST", "/site-visits", payload, headers)

    def complete_site_visit(self, visit_id, headers):
        return self._request("POST", f"/site-visits/{visit_id}/complete", {}, headers)

    def list_site_visits(self, association_id, headers, params=None):
        return self._request("GET", f"/associations/{association_id}/site-visits",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Expenditures
    # ------------------------------------------------------------------
    def create_expenditure(self, payload, headers):
        return self._request("POST", "/expenditures", payload, headers)

    def get_expenditure(self, expenditure_id, headers):
        return self._request("GET", f"/expenditures/{expenditure_id}", headers=headers)

    def list_expenditures(self, headers, params=None):
        return self._request("GET", "/expenditures", headers=headers, params=params)

    def approve_expenditure(self, expenditure_id, headers):
        return self._request("POST", f"/expenditures/{expenditure_id}/approve",
                             {}, headers)

    def reject_expenditure(self, expenditure_id, headers):
        return self._request("POST", f"/expenditures/{expenditure_id}/reject",
                             {}, headers)

    def reverse_expenditure(self, expenditure_id, headers):
        return self._request("POST", f"/expenditures/{expenditure_id}/reverse",
                             {}, headers)

    def accept_variance(self, expenditure_id, headers, reason=None):
        payload = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"/expenditures/{expenditure_id}/accept-variance",
                             payload, headers)

    # ------------------------------------------------------------------
    # Disclosures
    # ------------------------------------------------------------------
    def list_disclosures(self, study_id, headers, params=None):
        return self._request("GET", f"/reserve-studies/{study_id}/disclosures",
                             headers=headers, params=params)

    def distribute_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/disclosures/{disclosure_id}/distribute",
                             {}, headers)


api_client = ApiClient()
