"""API client: one method per endpoint defined in the Sign Fabrication &
Installation PRD (§4). Subclasses GenericApiClient; the base _request() handles
the HTTP envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- SignProject ----
    def create_sign_project(self, payload, headers):
        return self._request("POST", "/sign-projects", payload, headers)

    def get_sign_project(self, project_id, headers):
        return self._request("GET", f"/sign-projects/{project_id}", headers=headers)

    def list_sign_projects(self, headers, params=None):
        return self._request("GET", "/sign-projects", headers=headers, params=params)

    def cancel_sign_project(self, project_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/cancel", {}, headers)

    def close_sign_project(self, project_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/close", {}, headers)

    # ---- ArtProof ----
    def create_art_proof(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/art-proofs", payload, headers)

    def list_art_proofs(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/art-proofs", headers=headers, params=params)

    def submit_art_proof(self, project_id, proof_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/art-proofs/{proof_id}/submit", {}, headers)

    def decide_art_proof(self, project_id, proof_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/art-proofs/{proof_id}/decision", payload, headers)

    # ---- Estimate ----
    def create_estimate(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/estimates", payload, headers)

    def list_estimates(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/estimates", headers=headers, params=params)

    def send_estimate(self, project_id, estimate_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/estimates/{estimate_id}/send", {}, headers)

    def accept_estimate(self, project_id, estimate_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/estimates/{estimate_id}/accept", payload, headers)

    def decline_estimate(self, project_id, estimate_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/estimates/{estimate_id}/decline", {}, headers)

    def get_estimate_by_id(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates_global(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    # ---- SiteSurvey ----
    def create_site_survey(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/site-surveys", payload, headers)

    def list_site_surveys(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/site-surveys", headers=headers, params=params)

    def decide_site_survey(self, project_id, survey_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/site-surveys/{survey_id}/decide", payload, headers)

    # ---- Permit ----
    def create_permit(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/permits", payload, headers)

    def list_permits(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/permits", headers=headers, params=params)

    def submit_permit(self, project_id, permit_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/permits/{permit_id}/submit", {}, headers)

    def decide_permit(self, project_id, permit_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/permits/{permit_id}/decide", payload, headers)

    # ---- FabricationWorkOrder ----
    def create_work_order(self, project_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/fabrication-work-orders", {}, headers)

    def list_work_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/fabrication-work-orders", headers=headers, params=params)

    def start_work_order(self, project_id, wo_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/fabrication-work-orders/{wo_id}/start", {}, headers)

    def qc_hold_work_order(self, project_id, wo_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/fabrication-work-orders/{wo_id}/qc-hold", {}, headers)

    def qc_decide_work_order(self, project_id, wo_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/fabrication-work-orders/{wo_id}/qc-decide", payload, headers)

    def cancel_work_order(self, project_id, wo_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/fabrication-work-orders/{wo_id}/cancel", {}, headers)

    def get_work_order_by_id(self, wo_id, headers):
        return self._request("GET", f"/fabrication-work-orders/{wo_id}", headers=headers)

    def list_work_orders_global(self, headers, params=None):
        return self._request("GET", "/fabrication-work-orders", headers=headers, params=params)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def update_crew(self, crew_id, payload, headers):
        return self._request("PATCH", f"/crews/{crew_id}", payload, headers)

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    # ---- InstallJob ----
    def create_install_job(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/install-jobs", payload, headers)

    def list_install_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/install-jobs", headers=headers, params=params)

    def dispatch_install_job(self, project_id, job_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/install-jobs/{job_id}/dispatch", {}, headers)

    def complete_install_job(self, project_id, job_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/install-jobs/{job_id}/complete", {}, headers)

    def fail_install_job(self, project_id, job_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/install-jobs/{job_id}/fail", {}, headers)

    def cancel_install_job(self, project_id, job_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/install-jobs/{job_id}/cancel", {}, headers)

    def get_install_job_by_id(self, job_id, headers):
        return self._request("GET", f"/install-jobs/{job_id}", headers=headers)

    def list_install_jobs_global(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    # ---- ChangeOrder ----
    def create_change_order(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/change-orders", payload, headers)

    def list_change_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/change-orders", headers=headers, params=params)

    def approve_change_order(self, project_id, co_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/change-orders/{co_id}/approve", {}, headers)

    def apply_change_order(self, project_id, co_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/change-orders/{co_id}/apply", payload, headers)

    def reject_change_order(self, project_id, co_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/change-orders/{co_id}/reject", {}, headers)

    # ---- WarrantyClaim ----
    def create_warranty_claim(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/warranty-claims", payload, headers)

    def list_warranty_claims(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/warranty-claims", headers=headers, params=params)

    def decide_warranty_claim(self, project_id, claim_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/warranty-claims/{claim_id}/decide", payload, headers)

    def resolve_warranty_claim(self, project_id, claim_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/warranty-claims/{claim_id}/resolve", {}, headers)

    def get_warranty_claim_by_id(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims_global(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    # ---- Reorder ----
    def create_reorder(self, project_id, payload, headers):
        return self._request("POST", f"/sign-projects/{project_id}/reorders", payload, headers)

    def list_reorders(self, project_id, headers, params=None):
        return self._request("GET", f"/sign-projects/{project_id}/reorders", headers=headers, params=params)

    def confirm_reorder(self, project_id, reorder_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/reorders/{reorder_id}/confirm", {}, headers)

    def cancel_reorder(self, project_id, reorder_id, headers):
        return self._request("POST", f"/sign-projects/{project_id}/reorders/{reorder_id}/cancel", {}, headers)


api_client = ApiClient()
