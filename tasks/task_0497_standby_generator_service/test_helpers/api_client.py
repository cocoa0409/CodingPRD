"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient, which supplies _request() and reads
API_BASE_URL from the environment. GET endpoints pass filters/pagination through
`params`; mutating endpoints pass the JSON body through `payload`.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (test-driving) ────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Customer ────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_projects(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/projects", headers=headers, params=params
        )

    def list_customer_units(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/units", headers=headers, params=params
        )

    # ─── Technician ──────────────────────────────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def update_technician(self, technician_id, payload, headers):
        return self._request("PATCH", f"/technicians/{technician_id}", payload, headers)

    # ─── GeneratorModel (catalog) ────────────────────────────────────────────
    def create_model(self, payload, headers):
        return self._request("POST", "/models", payload, headers)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/models/{model_id}", headers=headers)

    def list_model_recall_campaigns(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/models/{model_id}/recall-campaigns", headers=headers, params=params
        )

    # ─── GeneratorProject ────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def create_load_assessment(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/load-assessments", payload, headers
        )

    def list_load_assessments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/load-assessments", headers=headers, params=params
        )

    def size_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/size", payload, headers)

    def permit_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/permit", payload, headers)

    def install_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/install", payload, headers)

    def activate_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/activate", payload, headers)

    def cancel_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", payload, headers)

    # ─── Unit ────────────────────────────────────────────────────────────────
    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def update_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/units/{unit_id}", payload, headers)

    def decommission_unit(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/decommission", {}, headers)

    def create_exercise_log(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/exercise-logs", payload, headers)

    def list_exercise_logs(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/units/{unit_id}/exercise-logs", headers=headers, params=params
        )

    def create_maintenance_plan(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/maintenance-plans", payload, headers)

    def list_unit_maintenance_plans(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/units/{unit_id}/maintenance-plans", headers=headers, params=params
        )

    def create_warranty_claim(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/warranty-claims", payload, headers)

    def list_unit_warranty_claims(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/units/{unit_id}/warranty-claims", headers=headers, params=params
        )

    def create_repair_dispatch(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/repair-dispatches", payload, headers)

    def list_unit_repair_dispatches(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/units/{unit_id}/repair-dispatches", headers=headers, params=params
        )

    def list_unit_remediations(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/units/{unit_id}/remediations", headers=headers, params=params
        )

    # ─── MaintenancePlan / Visit ─────────────────────────────────────────────
    def list_maintenance_plans(self, headers, params=None):
        return self._request("GET", "/maintenance-plans", headers=headers, params=params)

    def get_maintenance_plan(self, plan_id, headers):
        return self._request("GET", f"/maintenance-plans/{plan_id}", headers=headers)

    def suspend_plan(self, plan_id, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/suspend", {}, headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/resume", {}, headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/cancel", {}, headers)

    def schedule_visit(self, plan_id, payload, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/visits", payload, headers)

    def list_plan_visits(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/maintenance-plans/{plan_id}/visits", headers=headers, params=params
        )

    def list_maintenance_visits(self, headers, params=None):
        return self._request("GET", "/maintenance-visits", headers=headers, params=params)

    def get_maintenance_visit(self, visit_id, headers):
        return self._request("GET", f"/maintenance-visits/{visit_id}", headers=headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/maintenance-visits/{visit_id}/complete", payload, headers
        )

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/maintenance-visits/{visit_id}/cancel", {}, headers)

    # ─── LoadAssessment / ExerciseLog reads ─────────────────────────────────
    def get_load_assessment(self, assessment_id, headers):
        return self._request("GET", f"/load-assessments/{assessment_id}", headers=headers)

    def list_all_load_assessments(self, headers, params=None):
        return self._request("GET", "/load-assessments", headers=headers, params=params)

    def get_exercise_log(self, log_id, headers):
        return self._request("GET", f"/exercise-logs/{log_id}", headers=headers)

    def list_all_exercise_logs(self, headers, params=None):
        return self._request("GET", "/exercise-logs", headers=headers, params=params)

    # ─── WarrantyClaim ───────────────────────────────────────────────────────
    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/review", {}, headers)

    def return_claim_for_info(self, claim_id, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/return-for-info", {}, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/adjudicate", payload, headers
        )

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/withdraw", {}, headers)

    # ─── RepairDispatch ──────────────────────────────────────────────────────
    def list_repair_dispatches(self, headers, params=None):
        return self._request("GET", "/repair-dispatches", headers=headers, params=params)

    def get_repair_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/repair-dispatches/{dispatch_id}", headers=headers)

    def assign_dispatch(self, dispatch_id, payload, headers):
        return self._request(
            "POST", f"/repair-dispatches/{dispatch_id}/assign", payload, headers
        )

    def start_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/repair-dispatches/{dispatch_id}/start", {}, headers)

    def pause_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/repair-dispatches/{dispatch_id}/pause", {}, headers)

    def resolve_dispatch(self, dispatch_id, payload, headers):
        return self._request(
            "POST", f"/repair-dispatches/{dispatch_id}/resolve", payload, headers
        )

    def close_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/repair-dispatches/{dispatch_id}/close", {}, headers)

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/repair-dispatches/{dispatch_id}/cancel", {}, headers)

    # ─── RecallCampaign / Remediation ───────────────────────────────────────
    def create_recall_campaign(self, payload, headers):
        return self._request("POST", "/recall-campaigns", payload, headers)

    def list_recall_campaigns(self, headers, params=None):
        return self._request("GET", "/recall-campaigns", headers=headers, params=params)

    def get_recall_campaign(self, campaign_id, headers):
        return self._request("GET", f"/recall-campaigns/{campaign_id}", headers=headers)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/recall-campaigns/{campaign_id}/open", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/recall-campaigns/{campaign_id}/close", {}, headers)

    def list_campaign_remediations(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/recall-campaigns/{campaign_id}/remediations", headers=headers, params=params
        )

    def list_recall_remediations(self, headers, params=None):
        return self._request("GET", "/recall-remediations", headers=headers, params=params)

    def get_recall_remediation(self, remediation_id, headers):
        return self._request("GET", f"/recall-remediations/{remediation_id}", headers=headers)

    def schedule_remediation(self, remediation_id, headers):
        return self._request(
            "POST", f"/recall-remediations/{remediation_id}/schedule", {}, headers
        )


api_client = ApiClient()
