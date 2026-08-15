"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All endpoints are mounted under the /rescue-ops prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/rescue-ops/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Personnel
    # ------------------------------------------------------------------
    def create_personnel(self, payload, headers):
        return self._request("POST", "/rescue-ops/personnel", payload, headers)

    def list_personnel(self, headers, params=None):
        return self._request("GET", "/rescue-ops/personnel", headers=headers,
                             params=params)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"/rescue-ops/personnel/{personnel_id}",
                             headers=headers)

    def patch_personnel(self, personnel_id, payload, headers):
        return self._request("PATCH", f"/rescue-ops/personnel/{personnel_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Client accounts
    # ------------------------------------------------------------------
    def create_client_account(self, payload, headers):
        return self._request("POST", "/rescue-ops/client-accounts", payload, headers)

    def list_client_accounts(self, headers, params=None):
        return self._request("GET", "/rescue-ops/client-accounts", headers=headers,
                             params=params)

    def get_client_account(self, account_id, headers):
        return self._request("GET", f"/rescue-ops/client-accounts/{account_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Confined spaces
    # ------------------------------------------------------------------
    def create_confined_space(self, account_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/client-accounts/{account_id}/confined-spaces",
            payload, headers)

    def list_confined_spaces(self, headers, params=None):
        return self._request("GET", "/rescue-ops/confined-spaces", headers=headers,
                             params=params)

    def get_confined_space(self, space_id, headers):
        return self._request("GET", f"/rescue-ops/confined-spaces/{space_id}",
                             headers=headers)

    def patch_confined_space(self, space_id, payload, headers):
        return self._request("PATCH", f"/rescue-ops/confined-spaces/{space_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Rescue plans
    # ------------------------------------------------------------------
    def create_rescue_plan(self, space_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/confined-spaces/{space_id}/rescue-plans",
            payload, headers)

    def list_rescue_plans(self, headers, params=None):
        return self._request("GET", "/rescue-ops/rescue-plans", headers=headers,
                             params=params)

    def get_rescue_plan(self, plan_id, headers):
        return self._request("GET", f"/rescue-ops/rescue-plans/{plan_id}",
                             headers=headers)

    def approve_rescue_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/rescue-ops/rescue-plans/{plan_id}/approve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Entry permits
    # ------------------------------------------------------------------
    def create_entry_permit(self, space_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/confined-spaces/{space_id}/entry-permits",
            payload, headers)

    def list_entry_permits(self, headers, params=None):
        return self._request("GET", "/rescue-ops/entry-permits", headers=headers,
                             params=params)

    def get_entry_permit(self, permit_id, headers):
        return self._request("GET", f"/rescue-ops/entry-permits/{permit_id}",
                             headers=headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/rescue-ops/entry-permits/{permit_id}/issue",
                             {}, headers)

    def activate_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/activate", {}, headers)

    def suspend_permit(self, permit_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/suspend", payload, headers)

    def resume_permit(self, permit_id, headers):
        return self._request("POST", f"/rescue-ops/entry-permits/{permit_id}/resume",
                             {}, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/rescue-ops/entry-permits/{permit_id}/close",
                             {}, headers)

    def cancel_permit(self, permit_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/cancel", payload, headers)

    # ------------------------------------------------------------------
    # Isolation verifications
    # ------------------------------------------------------------------
    def create_isolation_verification(self, permit_id, payload, headers):
        return self._request(
            "POST",
            f"/rescue-ops/entry-permits/{permit_id}/isolation-verifications",
            payload, headers)

    def list_isolation_verifications(self, headers, params=None):
        return self._request("GET", "/rescue-ops/isolation-verifications",
                             headers=headers, params=params)

    def get_isolation_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/rescue-ops/isolation-verifications/{verification_id}",
            headers=headers)

    def verify_isolation(self, verification_id, headers):
        return self._request(
            "POST",
            f"/rescue-ops/isolation-verifications/{verification_id}/verify",
            {}, headers)

    def void_isolation(self, verification_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/rescue-ops/isolation-verifications/{verification_id}/void",
            payload, headers)

    # ------------------------------------------------------------------
    # Roster entries
    # ------------------------------------------------------------------
    def create_roster_entry(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/roster-entries",
            payload, headers)

    def list_roster_entries(self, headers, params=None):
        return self._request("GET", "/rescue-ops/roster-entries", headers=headers,
                             params=params)

    def get_roster_entry(self, entry_id, headers):
        return self._request("GET", f"/rescue-ops/roster-entries/{entry_id}",
                             headers=headers)

    def roster_check_in(self, entry_id, headers):
        return self._request(
            "POST", f"/rescue-ops/roster-entries/{entry_id}/check-in", {}, headers)

    def roster_check_out(self, entry_id, headers):
        return self._request(
            "POST", f"/rescue-ops/roster-entries/{entry_id}/check-out", {}, headers)

    # ------------------------------------------------------------------
    # Atmospheric readings
    # ------------------------------------------------------------------
    def create_atmospheric_reading(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/atmospheric-readings",
            payload, headers)

    def list_atmospheric_readings(self, headers, params=None):
        return self._request("GET", "/rescue-ops/atmospheric-readings",
                             headers=headers, params=params)

    def get_atmospheric_reading(self, reading_id, headers):
        return self._request(
            "GET", f"/rescue-ops/atmospheric-readings/{reading_id}", headers=headers)

    # ------------------------------------------------------------------
    # Standby assignments
    # ------------------------------------------------------------------
    def create_standby_assignment(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/standby-assignments",
            payload, headers)

    def list_standby_assignments(self, headers, params=None):
        return self._request("GET", "/rescue-ops/standby-assignments",
                             headers=headers, params=params)

    def get_standby_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/rescue-ops/standby-assignments/{assignment_id}", headers=headers)

    def standby_check_in(self, assignment_id, headers):
        return self._request(
            "POST", f"/rescue-ops/standby-assignments/{assignment_id}/check-in",
            {}, headers)

    def standby_release(self, assignment_id, headers):
        return self._request(
            "POST", f"/rescue-ops/standby-assignments/{assignment_id}/release",
            {}, headers)

    def standby_cancel(self, assignment_id, headers):
        return self._request(
            "POST", f"/rescue-ops/standby-assignments/{assignment_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def create_incident(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/entry-permits/{permit_id}/incidents",
            payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/rescue-ops/incidents", headers=headers,
                             params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/rescue-ops/incidents/{incident_id}",
                             headers=headers)

    def triage_incident(self, incident_id, headers, severity=None):
        payload = {} if severity is None else {"severity": severity}
        return self._request(
            "POST", f"/rescue-ops/incidents/{incident_id}/triage", payload, headers)

    def escalate_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/rescue-ops/incidents/{incident_id}/escalate", {}, headers)

    def resolve_incident(self, incident_id, resolution_notes, headers):
        return self._request(
            "POST", f"/rescue-ops/incidents/{incident_id}/resolve",
            {"resolution_notes": resolution_notes}, headers)

    def reopen_incident(self, incident_id, reason, headers):
        return self._request(
            "POST", f"/rescue-ops/incidents/{incident_id}/reopen",
            {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Billing statements
    # ------------------------------------------------------------------
    def generate_statement(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/rescue-ops/client-accounts/{account_id}/statements/generate",
            payload, headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/rescue-ops/statements", headers=headers,
                             params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/rescue-ops/statements/{statement_id}",
                             headers=headers)

    def finalize_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/rescue-ops/statements/{statement_id}/finalize", {}, headers)

    def dispute_statement(self, statement_id, reason, headers):
        return self._request(
            "POST", f"/rescue-ops/statements/{statement_id}/dispute",
            {"reason": reason}, headers)

    def add_statement_adjustment(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/rescue-ops/statements/{statement_id}/adjustments",
            payload, headers)

    def void_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/rescue-ops/statements/{statement_id}/void", {}, headers)

    def pay_statement(self, statement_id, payment_cents, headers):
        return self._request(
            "POST", f"/rescue-ops/statements/{statement_id}/pay",
            {"payment_cents": payment_cents}, headers)

    def list_statement_lines(self, statement_id, headers):
        return self._request(
            "GET", f"/rescue-ops/statements/{statement_id}/lines", headers=headers)


api_client = ApiClient()
