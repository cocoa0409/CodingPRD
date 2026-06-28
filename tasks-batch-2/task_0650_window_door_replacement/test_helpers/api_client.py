"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Homeowner ----
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/homeowners/{homeowner_id}", headers=headers)

    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    # ---- Consultation ----
    def create_consultation(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/consultations", payload, headers)

    def list_consultations(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/consultations", headers=headers, params=params)

    def get_consultation_nested(self, project_id, consultation_id, headers):
        return self._request("GET", f"/projects/{project_id}/consultations/{consultation_id}", headers=headers)

    def complete_measure(self, project_id, consultation_id, headers):
        return self._request("POST", f"/projects/{project_id}/consultations/{consultation_id}/complete-measure", {}, headers)

    def cancel_consultation(self, project_id, consultation_id, headers):
        return self._request("POST", f"/projects/{project_id}/consultations/{consultation_id}/cancel", {}, headers)

    def get_consultation(self, consultation_id, headers):
        return self._request("GET", f"/consultations/{consultation_id}", headers=headers)

    def list_consultations_flat(self, headers, params=None):
        return self._request("GET", "/consultations", headers=headers, params=params)

    # ---- Opening ----
    def create_opening(self, project_id, consultation_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/consultations/{consultation_id}/openings", payload, headers)

    def list_openings(self, project_id, consultation_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/consultations/{consultation_id}/openings", headers=headers, params=params)

    def get_opening(self, opening_id, headers):
        return self._request("GET", f"/openings/{opening_id}", headers=headers)

    def patch_opening(self, opening_id, payload, headers):
        return self._request("PATCH", f"/openings/{opening_id}", payload, headers)

    def list_openings_flat(self, headers, params=None):
        return self._request("GET", "/openings", headers=headers, params=params)

    def list_opening_service_tickets(self, opening_id, headers, params=None):
        return self._request("GET", f"/openings/{opening_id}/service-tickets", headers=headers, params=params)

    # ---- Quote ----
    def create_quote(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes", payload, headers)

    def list_quotes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes", headers=headers, params=params)

    def get_quote_nested(self, project_id, quote_id, headers):
        return self._request("GET", f"/projects/{project_id}/quotes/{quote_id}", headers=headers)

    def send_quote(self, project_id, quote_id, headers):
        return self._request("POST", f"/projects/{project_id}/quotes/{quote_id}/send", {}, headers)

    def accept_quote(self, project_id, quote_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes/{quote_id}/accept", payload, headers)

    def reject_quote(self, project_id, quote_id, headers):
        return self._request("POST", f"/projects/{project_id}/quotes/{quote_id}/reject", {}, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes_flat(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    # ---- Financing ----
    def create_financing(self, project_id, quote_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes/{quote_id}/financing", payload, headers)

    def list_financing(self, project_id, quote_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/quotes/{quote_id}/financing", headers=headers, params=params)

    def decide_financing(self, project_id, quote_id, financing_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quotes/{quote_id}/financing/{financing_id}/decide", payload, headers)

    def get_financing(self, financing_id, headers):
        return self._request("GET", f"/financing-applications/{financing_id}", headers=headers)

    def list_financing_flat(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    # ---- Manufacture ----
    def list_manufacture(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/manufacture", headers=headers, params=params)

    def get_manufacture_nested(self, project_id, manufacture_id, headers):
        return self._request("GET", f"/projects/{project_id}/manufacture/{manufacture_id}", headers=headers)

    def start_build(self, project_id, manufacture_id, headers):
        return self._request("POST", f"/projects/{project_id}/manufacture/{manufacture_id}/start-build", {}, headers)

    def mark_ready(self, project_id, manufacture_id, headers):
        return self._request("POST", f"/projects/{project_id}/manufacture/{manufacture_id}/mark-ready", {}, headers)

    def get_manufacture_order(self, manufacture_id, headers):
        return self._request("GET", f"/manufacture-orders/{manufacture_id}", headers=headers)

    def list_manufacture_orders_flat(self, headers, params=None):
        return self._request("GET", "/manufacture-orders", headers=headers, params=params)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ---- InstallJob ----
    def create_install_job(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/install-jobs", payload, headers)

    def list_install_jobs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/install-jobs", headers=headers, params=params)

    def list_install_jobs_flat(self, headers, params=None):
        return self._request("GET", "/install-jobs", headers=headers, params=params)

    def get_install_job(self, install_job_id, headers):
        return self._request("GET", f"/install-jobs/{install_job_id}", headers=headers)

    def depart_install_job(self, project_id, install_job_id, headers):
        return self._request("POST", f"/projects/{project_id}/install-jobs/{install_job_id}/depart", {}, headers)

    def complete_install_job(self, project_id, install_job_id, headers):
        return self._request("POST", f"/projects/{project_id}/install-jobs/{install_job_id}/complete", {}, headers)

    def cancel_install_job(self, project_id, install_job_id, headers):
        return self._request("POST", f"/projects/{project_id}/install-jobs/{install_job_id}/cancel", {}, headers)

    # ---- Permit ----
    def create_permit(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/permits", payload, headers)

    def list_permits(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/permits", headers=headers, params=params)

    def approve_permit(self, project_id, permit_id, headers):
        return self._request("POST", f"/projects/{project_id}/permits/{permit_id}/approve", {}, headers)

    def record_inspection(self, project_id, permit_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/permits/{permit_id}/record-inspection", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits_flat(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    # ---- ServiceTicket ----
    def create_service_ticket(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/service-tickets", payload, headers)

    def list_service_tickets(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/service-tickets", headers=headers, params=params)

    def dispatch_service_ticket(self, project_id, ticket_id, headers):
        return self._request("POST", f"/projects/{project_id}/service-tickets/{ticket_id}/dispatch", {}, headers)

    def resolve_service_ticket(self, project_id, ticket_id, headers):
        return self._request("POST", f"/projects/{project_id}/service-tickets/{ticket_id}/resolve", {}, headers)

    def close_service_ticket(self, project_id, ticket_id, headers):
        return self._request("POST", f"/projects/{project_id}/service-tickets/{ticket_id}/close", {}, headers)

    def reopen_service_ticket(self, project_id, ticket_id, headers):
        return self._request("POST", f"/projects/{project_id}/service-tickets/{ticket_id}/reopen", {}, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets_flat(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
