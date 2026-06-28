"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Customer -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ----- LightingProject -----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def lock_design(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/lock-design", {}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", {}, headers)

    # ----- Transformer -----
    def create_transformer(self, payload, headers):
        return self._request("POST", "/transformers", payload, headers)

    def get_transformer(self, transformer_id, headers):
        return self._request("GET", f"/transformers/{transformer_id}", headers=headers)

    def list_project_transformers(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/transformers", headers=headers, params=params)

    def list_transformer_zones(self, transformer_id, headers, params=None):
        return self._request("GET", f"/transformers/{transformer_id}/zones", headers=headers, params=params)

    def decommission_transformer(self, transformer_id, headers):
        return self._request("POST", f"/transformers/{transformer_id}/decommission", {}, headers)

    # ----- Zone -----
    def create_zone(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def list_project_zones(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/zones", headers=headers, params=params)

    def list_zone_fixtures(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/fixtures", headers=headers, params=params)

    def list_zone_add_ons(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/add-ons", headers=headers, params=params)

    # ----- Fixture -----
    def create_fixture(self, payload, headers):
        return self._request("POST", "/fixtures", payload, headers)

    def get_fixture(self, fixture_id, headers):
        return self._request("GET", f"/fixtures/{fixture_id}", headers=headers)

    def list_project_fixtures(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/fixtures", headers=headers, params=params)

    def assign_zone(self, fixture_id, payload, headers):
        return self._request("POST", f"/fixtures/{fixture_id}/assign-zone", payload, headers)

    def remove_fixture(self, fixture_id, headers):
        return self._request("POST", f"/fixtures/{fixture_id}/remove", {}, headers)

    def list_fixture_warranty_claims(self, fixture_id, headers, params=None):
        return self._request("GET", f"/fixtures/{fixture_id}/warranty-claims", headers=headers, params=params)

    # ----- Quote / QuoteLine -----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_project_quotes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes", headers=headers, params=params)

    def add_quote_line(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/lines", payload, headers)

    def list_quote_lines(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/lines", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", {}, headers)

    def revise_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/revise", {}, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reject", {}, headers)

    # ----- InstallJob -----
    def create_install_job(self, payload, headers):
        return self._request("POST", "/install-jobs", payload, headers)

    def get_install_job(self, job_id, headers):
        return self._request("GET", f"/install-jobs/{job_id}", headers=headers)

    def list_project_install_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/install-jobs", headers=headers, params=params)

    def list_quote_install_jobs(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/install-jobs", headers=headers, params=params)

    def start_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/start", {}, headers)

    def complete_wiring(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/complete-wiring", {}, headers)

    def complete_fixtures(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/complete-fixtures", {}, headers)

    def cancel_install_job(self, job_id, headers):
        return self._request("POST", f"/install-jobs/{job_id}/cancel", {}, headers)

    # ----- ScheduleProgram -----
    def create_schedule_program(self, payload, headers):
        return self._request("POST", "/schedule-programs", payload, headers)

    def get_schedule_program(self, program_id, headers):
        return self._request("GET", f"/schedule-programs/{program_id}", headers=headers)

    def list_project_schedule_programs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/schedule-programs", headers=headers, params=params)

    def activate_schedule_program(self, program_id, headers):
        return self._request("POST", f"/schedule-programs/{program_id}/activate", {}, headers)

    def disable_schedule_program(self, program_id, headers):
        return self._request("POST", f"/schedule-programs/{program_id}/disable", {}, headers)

    # ----- ServicePlan -----
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    def list_project_service_plans(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/service-plans", headers=headers, params=params)

    def activate_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/activate", {}, headers)

    def begin_seasonal_adjustment(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/begin-seasonal-adjustment", {}, headers)

    def complete_seasonal_adjustment(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/complete-seasonal-adjustment", {}, headers)

    def cancel_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/cancel", {}, headers)

    # ----- ServiceVisit -----
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_plan_service_visits(self, plan_id, headers, params=None):
        return self._request("GET", f"/service-plans/{plan_id}/service-visits", headers=headers, params=params)

    def list_project_service_visits(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/service-visits", headers=headers, params=params)

    # ----- CrewRoute -----
    def create_crew_route(self, payload, headers):
        return self._request("POST", "/crew-routes", payload, headers)

    def get_crew_route(self, route_id, headers):
        return self._request("GET", f"/crew-routes/{route_id}", headers=headers)

    def list_route_visits(self, route_id, headers, params=None):
        return self._request("GET", f"/crew-routes/{route_id}/visits", headers=headers, params=params)

    def add_visit_to_route(self, route_id, payload, headers):
        return self._request("POST", f"/crew-routes/{route_id}/add-visit", payload, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/crew-routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/crew-routes/{route_id}/complete", {}, headers)

    # ----- WarrantyClaim -----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_project_warranty_claims(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", {}, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", {}, headers)

    # ----- AddOnModule -----
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def get_add_on(self, addon_id, headers):
        return self._request("GET", f"/add-ons/{addon_id}", headers=headers)

    def list_project_add_ons(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/add-ons", headers=headers, params=params)

    def activate_add_on(self, addon_id, headers):
        return self._request("POST", f"/add-ons/{addon_id}/activate", {}, headers)

    def remove_add_on(self, addon_id, headers):
        return self._request("POST", f"/add-ons/{addon_id}/remove", {}, headers)

    # ----- Test-driving clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
