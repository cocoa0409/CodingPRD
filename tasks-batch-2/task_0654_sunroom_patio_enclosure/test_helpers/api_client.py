"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Homeowner ----
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def finalize_design(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/finalize-design", headers=headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", headers=headers)

    def list_project_measurements(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/measurements", headers=headers,
                             params=params)

    def list_project_quotes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes", headers=headers,
                             params=params)

    def list_project_permit_applications(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/permit-applications",
                             headers=headers, params=params)

    def list_project_manufacture_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/manufacture-orders",
                             headers=headers, params=params)

    def list_project_install_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/install-jobs", headers=headers,
                             params=params)

    def list_project_inspections(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/inspections", headers=headers,
                             params=params)

    def list_project_warranties(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/warranties", headers=headers,
                             params=params)

    # ---- Measurement ----
    def create_measurement(self, payload, headers):
        return self._request("POST", "/measurements", payload, headers)

    def accept_measurement(self, measurement_id, headers):
        return self._request("POST", f"/measurements/{measurement_id}/accept", headers=headers)

    # ---- Quote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quote_financing_applications(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/financing-applications",
                             headers=headers, params=params)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", headers=headers)

    # ---- Financing ----
    def create_financing_application(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def decide_financing_application(self, financing_id, headers):
        return self._request("POST", f"/financing-applications/{financing_id}/decide",
                             headers=headers)

    # ---- Permit ----
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def get_permit_application(self, permit_id, headers):
        return self._request("GET", f"/permit-applications/{permit_id}", headers=headers)

    def list_permit_engineering_reviews(self, permit_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{permit_id}/engineering-reviews",
                             headers=headers, params=params)

    def begin_permit_review(self, permit_id, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/begin-review",
                             headers=headers)

    def permit_hoa_decision(self, permit_id, payload, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/hoa-decision",
                             payload, headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/decide", payload, headers)

    def resubmit_permit(self, permit_id, headers):
        return self._request("POST", f"/permit-applications/{permit_id}/resubmit", headers=headers)

    # ---- Engineering ----
    def create_engineering_review(self, payload, headers):
        return self._request("POST", "/engineering-reviews", payload, headers)

    def rule_engineering_review(self, review_id, headers):
        return self._request("POST", f"/engineering-reviews/{review_id}/rule", headers=headers)

    # ---- Manufacture ----
    def create_manufacture_order(self, payload, headers):
        return self._request("POST", "/manufacture-orders", payload, headers)

    def start_manufacture_order(self, order_id, headers):
        return self._request("POST", f"/manufacture-orders/{order_id}/start", headers=headers)

    def ready_manufacture_order(self, order_id, headers):
        return self._request("POST", f"/manufacture-orders/{order_id}/ready", headers=headers)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_install_jobs(self, crew_id, headers, params=None):
        return self._request("GET", f"/crews/{crew_id}/install-jobs", headers=headers,
                             params=params)

    # ---- Install ----
    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers)

    def start_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/start", headers=headers)

    def set_install_job_weather(self, job_id, payload, headers):
        return self._request("POST", f"/install-jobs/{job_id}/weather", payload, headers)

    def complete_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/complete", headers=headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def pass_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/pass", headers=headers)

    def fail_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/fail", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
