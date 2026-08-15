"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Carriers ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    # --- Escorts (no single-get endpoint exists; use list_escorts) ---
    def create_escort(self, payload, headers):
        return self._request("POST", "/escorts", payload, headers)

    def list_escorts(self, headers, params=None):
        return self._request("GET", "/escorts", headers=headers, params=params)

    def suspend_escort(self, escort_id, headers):
        return self._request("POST", f"/escorts/{escort_id}/suspend", {}, headers)

    def reinstate_escort(self, escort_id, headers):
        return self._request("POST", f"/escorts/{escort_id}/reinstate", {}, headers)

    # --- Jobs ---
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def amend_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/amendments", payload, headers)

    def quote_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/quote", {}, headers)

    def accept_quote(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/accept-quote", {}, headers)

    def schedule_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/schedule", {}, headers)

    def depart_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/depart", {}, headers)

    def hold_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/hold", {}, headers)

    def resume_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/resume", {}, headers)

    def deliver_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/deliver", {}, headers)

    def cancel_job(self, job_id, headers, payload=None):
        return self._request("POST", f"/jobs/{job_id}/cancel", payload or {}, headers)

    # --- Route legs ---
    def list_job_legs(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/legs", headers=headers, params=params)

    def get_leg(self, leg_id, headers):
        return self._request("GET", f"/legs/{leg_id}", headers=headers)

    def confirm_police(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/confirm-police", {}, headers)

    # --- Permits ---
    def create_permit(self, leg_id, payload, headers):
        return self._request("POST", f"/legs/{leg_id}/permits", payload, headers)

    def list_leg_permits(self, leg_id, headers, params=None):
        return self._request("GET", f"/legs/{leg_id}/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    # --- Route surveys / obstructions ---
    def request_route_survey(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/route-surveys", {}, headers)

    def list_leg_surveys(self, leg_id, headers, params=None):
        return self._request("GET", f"/legs/{leg_id}/route-surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/route-surveys/{survey_id}", headers=headers)

    def submit_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/route-surveys/{survey_id}/submit", payload, headers)

    def decide_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/route-surveys/{survey_id}/accept", payload, headers)

    def list_survey_obstructions(self, survey_id, headers, params=None):
        return self._request("GET", f"/route-surveys/{survey_id}/obstructions", headers=headers, params=params)

    # --- Escort assignments ---
    def create_assignment(self, leg_id, payload, headers):
        return self._request("POST", f"/legs/{leg_id}/assignments", payload, headers)

    def list_leg_assignments(self, leg_id, headers, params=None):
        return self._request("GET", f"/legs/{leg_id}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/release", {}, headers)

    def create_checkin(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-ins", {}, headers)

    # --- Delay events ---
    def create_delay_event(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/delay-events", payload, headers)

    def list_job_delay_events(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/delay-events", headers=headers, params=params)

    def close_delay_event(self, delay_event_id, headers):
        return self._request("POST", f"/delay-events/{delay_event_id}/close", {}, headers)

    # --- Incidents ---
    def create_incident(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/incidents", payload, headers)

    def list_job_incidents(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def assess_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/assess", payload, headers)

    def dispute_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/incidents/{incident_id}/dispute", payload or {}, headers)

    def settle_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/settle", {}, headers)

    # --- Invoices ---
    def create_invoice(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/invoices", {}, headers)

    def list_job_invoices(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", payload, headers)

    def adjust_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/adjust", payload, headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/record-payment", payload, headers)

    def write_off_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/write-off", payload or {}, headers)


api_client = ApiClient()
