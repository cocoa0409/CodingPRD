"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers=None):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Projects ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    def get_project_balance(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/balance", headers=headers)

    # ---- Design consults ----
    def create_design_consult(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/design-consults", payload, headers)

    def list_design_consults(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/design-consults", headers=headers, params=params)

    def render_design_consult(self, consult_id, payload, headers):
        return self._request("POST", f"/design-consults/{consult_id}/render", payload, headers)

    def complete_design_consult(self, consult_id, headers):
        return self._request("POST", f"/design-consults/{consult_id}/complete", {}, headers)

    def cancel_design_consult(self, consult_id, headers):
        return self._request("POST", f"/design-consults/{consult_id}/cancel", {}, headers)

    # ---- Space measures ----
    def create_space_measure(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/space-measures", payload, headers)

    def list_space_measures(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/space-measures", headers=headers, params=params)

    # ---- Component configs ----
    def create_component_config(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/component-configs", payload, headers)

    def list_project_component_configs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/component-configs", headers=headers, params=params)

    def get_component_config(self, config_id, headers):
        return self._request("GET", f"/component-configs/{config_id}", headers=headers)

    def list_component_configs(self, headers, params=None):
        return self._request("GET", "/component-configs", headers=headers, params=params)

    def finalize_component_config(self, config_id, headers):
        return self._request("POST", f"/component-configs/{config_id}/finalize", {}, headers)

    # ---- Quotes ----
    def create_quote(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes", payload, headers)

    def list_project_quotes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/issue", {}, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    # ---- Deposits ----
    def create_deposit(self, payload, headers):
        return self._request("POST", "/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def capture_deposit(self, deposit_id, payload, headers):
        return self._request("POST", f"/deposits/{deposit_id}/capture", payload, headers)

    def refund_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/refund", {}, headers)

    # ---- Manufacture orders ----
    def get_manufacture_order(self, order_id, headers):
        return self._request("GET", f"/manufacture-orders/{order_id}", headers=headers)

    def list_manufacture_orders(self, headers, params=None):
        return self._request("GET", "/manufacture-orders", headers=headers, params=params)

    def start_manufacture_order(self, order_id, headers):
        return self._request("POST", f"/manufacture-orders/{order_id}/start", {}, headers)

    def complete_manufacture_order(self, order_id, headers):
        return self._request("POST", f"/manufacture-orders/{order_id}/complete", {}, headers)

    # ---- Crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_install_jobs(self, crew_id, headers, params=None):
        return self._request("GET", f"/crews/{crew_id}/install-jobs", headers=headers, params=params)

    # ---- Install jobs ----
    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers)

    def get_install_job(self, job_id, headers):
        return self._request("GET", f"/install-jobs/{job_id}", headers=headers)

    def list_install_jobs(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def book_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/book", {}, headers)

    def request_reschedule_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/request-reschedule", {}, headers)

    def rebook_install_job(self, job_id, payload, headers):
        return self._request("POST", f"/install-jobs/{job_id}/rebook", payload, headers)

    def cancel_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/cancel", {}, headers)

    def start_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/start", {}, headers)

    def complete_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/complete", {}, headers)

    # ---- Change orders ----
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", {}, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject", {}, headers)

    def apply_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/apply", payload, headers)

    # ---- Warranty claims ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", {}, headers)

    def reject_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/reject", {}, headers)

    def schedule_adjustment_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/schedule-adjustment", {}, headers)

    def order_replacement_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/order-replacement", {}, headers)

    def resolve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/resolve", {}, headers)

    # ---- Financing ----
    def create_financing_application(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def get_financing_application(self, app_id, headers):
        return self._request("GET", f"/financing-applications/{app_id}", headers=headers)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def submit_financing_application(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/submit", {}, headers)

    def fund_financing_application(self, app_id, headers):
        return self._request("POST", f"/financing-applications/{app_id}/fund", {}, headers)

    # ---- Test-driving endpoints ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def financing_decision(self, payload, headers):
        return self._request("POST", "/_financing/decision", payload, headers)


api_client = ApiClient()
