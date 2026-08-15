"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Taxonomy categories ----------------
    def create_category(self, payload, headers):
        return self._request("POST", "/categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/categories/{category_id}", headers=headers)

    def reparent_category(self, category_id, payload, headers):
        return self._request("PATCH", f"/categories/{category_id}", payload, headers)

    def list_subcategories(self, category_id, headers, params=None):
        return self._request("GET", f"/categories/{category_id}/subcategories",
                             headers=headers, params=params)

    def list_category_risks(self, category_id, headers, params=None):
        return self._request("GET", f"/categories/{category_id}/risks",
                             headers=headers, params=params)

    def list_category_appetite_statements(self, category_id, headers, params=None):
        return self._request("GET", f"/categories/{category_id}/appetite-statements",
                             headers=headers, params=params)

    def list_category_kris(self, category_id, headers, params=None):
        return self._request("GET", f"/categories/{category_id}/kris",
                             headers=headers, params=params)

    def list_category_emerging_risks(self, category_id, headers, params=None):
        return self._request("GET", f"/categories/{category_id}/emerging-risks",
                             headers=headers, params=params)

    # ---------------- Risks ----------------
    def create_risk(self, payload, headers):
        return self._request("POST", "/risks", payload, headers)

    def list_risks(self, headers, params=None):
        return self._request("GET", "/risks", headers=headers, params=params)

    def get_risk(self, risk_id, headers):
        return self._request("GET", f"/risks/{risk_id}", headers=headers)

    def submit_risk(self, risk_id, headers):
        return self._request("POST", f"/risks/{risk_id}/submit", {}, headers)

    def create_assessment(self, risk_id, payload, headers):
        return self._request("POST", f"/risks/{risk_id}/assessments", payload, headers)

    def list_assessments(self, risk_id, headers, params=None):
        return self._request("GET", f"/risks/{risk_id}/assessments",
                             headers=headers, params=params)

    def enter_treatment(self, risk_id, headers):
        return self._request("POST", f"/risks/{risk_id}/enter-treatment", {}, headers)

    def monitor_risk(self, risk_id, headers):
        return self._request("POST", f"/risks/{risk_id}/monitor", {}, headers)

    def reassess_risk(self, risk_id, headers):
        return self._request("POST", f"/risks/{risk_id}/reassess", {}, headers)

    def close_risk(self, risk_id, headers):
        return self._request("POST", f"/risks/{risk_id}/close", {}, headers)

    def reopen_risk(self, risk_id, headers, payload=None):
        return self._request("POST", f"/risks/{risk_id}/reopen", payload or {}, headers)

    def list_risk_treatment_plans(self, risk_id, headers, params=None):
        return self._request("GET", f"/risks/{risk_id}/treatment-plans",
                             headers=headers, params=params)

    def list_risk_control_mappings(self, risk_id, headers, params=None):
        return self._request("GET", f"/risks/{risk_id}/control-mappings",
                             headers=headers, params=params)

    def list_risk_tolerance_breaches(self, risk_id, headers, params=None):
        return self._request("GET", f"/risks/{risk_id}/tolerance-breaches",
                             headers=headers, params=params)

    def create_control_mapping(self, risk_id, payload, headers):
        return self._request("POST", f"/risks/{risk_id}/control-mappings",
                             payload, headers)

    def create_treatment_plan(self, risk_id, payload, headers):
        return self._request("POST", f"/risks/{risk_id}/treatment-plans",
                             payload, headers)

    # ---------------- Controls ----------------
    def create_control(self, payload, headers):
        return self._request("POST", "/controls", payload, headers)

    def get_control(self, control_id, headers):
        return self._request("GET", f"/controls/{control_id}", headers=headers)

    def activate_control(self, control_id, headers):
        return self._request("POST", f"/controls/{control_id}/activate", {}, headers)

    def review_control(self, control_id, headers):
        return self._request("POST", f"/controls/{control_id}/review", {}, headers)

    def attest_control(self, control_id, payload, headers):
        return self._request("POST", f"/controls/{control_id}/attest", payload, headers)

    def retire_control(self, control_id, headers):
        return self._request("POST", f"/controls/{control_id}/retire", {}, headers)

    def list_control_mappings(self, control_id, headers, params=None):
        return self._request("GET", f"/controls/{control_id}/control-mappings",
                             headers=headers, params=params)

    # ---------------- Control mappings (flat) ----------------
    def approve_mapping(self, mapping_id, headers):
        return self._request("POST", f"/control-mappings/{mapping_id}/approve",
                             {}, headers)

    def retire_mapping(self, mapping_id, headers):
        return self._request("POST", f"/control-mappings/{mapping_id}/retire",
                             {}, headers)

    # ---------------- Appetite statements ----------------
    def create_appetite_statement(self, payload, headers):
        return self._request("POST", "/appetite-statements", payload, headers)

    def get_appetite_statement(self, statement_id, headers):
        return self._request("GET", f"/appetite-statements/{statement_id}",
                             headers=headers)

    def approve_appetite_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/appetite-statements/{statement_id}/approve",
                             {}, headers)

    def retire_appetite_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/appetite-statements/{statement_id}/retire",
                             {}, headers)

    def list_appetite_breaches(self, statement_id, headers, params=None):
        return self._request("GET",
                             f"/appetite-statements/{statement_id}/tolerance-breaches",
                             headers=headers, params=params)

    # ---------------- Treatment plans ----------------
    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def approve_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/approve",
                             {}, headers)

    def reject_treatment_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/treatment-plans/{plan_id}/reject",
                             payload or {}, headers)

    def start_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/start", {}, headers)

    def complete_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/complete",
                             {}, headers)

    def cancel_treatment_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/treatment-plans/{plan_id}/cancel",
                             payload or {}, headers)

    def extend_treatment_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/extend",
                             payload, headers)

    def create_treatment_action(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/actions",
                             payload, headers)

    def list_treatment_actions(self, plan_id, headers, params=None):
        return self._request("GET", f"/treatment-plans/{plan_id}/actions",
                             headers=headers, params=params)

    # ---------------- Treatment actions ----------------
    def mark_action_done(self, action_id, headers):
        return self._request("POST", f"/treatment-actions/{action_id}/done",
                             {}, headers)

    # ---------------- Tolerance breaches ----------------
    def get_tolerance_breach(self, breach_id, headers):
        return self._request("GET", f"/tolerance-breaches/{breach_id}", headers=headers)

    def acknowledge_breach(self, breach_id, headers):
        return self._request("POST", f"/tolerance-breaches/{breach_id}/acknowledge",
                             {}, headers)

    def resolve_breach(self, breach_id, headers):
        return self._request("POST", f"/tolerance-breaches/{breach_id}/resolve",
                             {}, headers)

    def accept_breach(self, breach_id, payload, headers):
        return self._request("POST", f"/tolerance-breaches/{breach_id}/accept",
                             payload, headers)

    # ---------------- KRIs ----------------
    def create_kri(self, payload, headers):
        return self._request("POST", "/kris", payload, headers)

    def get_kri(self, kri_id, headers):
        return self._request("GET", f"/kris/{kri_id}", headers=headers)

    def activate_kri(self, kri_id, headers):
        return self._request("POST", f"/kris/{kri_id}/activate", {}, headers)

    def retire_kri(self, kri_id, headers):
        return self._request("POST", f"/kris/{kri_id}/retire", {}, headers)

    def create_kri_observation(self, kri_id, payload, headers):
        return self._request("POST", f"/kris/{kri_id}/observations", payload, headers)

    def list_kri_observations(self, kri_id, headers, params=None):
        return self._request("GET", f"/kris/{kri_id}/observations",
                             headers=headers, params=params)

    # ---------------- Board reports ----------------
    def create_report(self, payload, headers):
        return self._request("POST", "/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST", f"/reports/{report_id}/finalize", {}, headers)

    # ---------------- Emerging risks ----------------
    def create_emerging_risk(self, payload, headers):
        return self._request("POST", "/emerging-risks", payload, headers)

    def get_emerging_risk(self, emerging_id, headers):
        return self._request("GET", f"/emerging-risks/{emerging_id}", headers=headers)

    def list_emerging_risks_promoted_risks(self, emerging_id, headers, params=None):
        return self._request("GET", f"/emerging-risks/{emerging_id}/risks",
                             headers=headers, params=params)

    def validate_emerging_risk(self, emerging_id, headers):
        return self._request("POST", f"/emerging-risks/{emerging_id}/validate",
                             {}, headers)

    def promote_emerging_risk(self, emerging_id, payload, headers):
        return self._request("POST", f"/emerging-risks/{emerging_id}/promote",
                             payload, headers)

    def dismiss_emerging_risk(self, emerging_id, headers, payload=None):
        return self._request("POST", f"/emerging-risks/{emerging_id}/dismiss",
                             payload or {}, headers)

    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
