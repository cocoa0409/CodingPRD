"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock --
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # -------------------------------------------------------- client contracts --
    def list_client_contracts(self, headers, params=None):
        return self._request("GET", "/client-contracts", headers=headers, params=params)

    def get_client_contract(self, contract_id, headers):
        return self._request("GET", f"/client-contracts/{contract_id}", headers=headers)

    def get_utilization_report(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/client-contracts/{contract_id}/utilization-report",
            headers=headers,
            params=params,
        )

    def create_client_contract(self, payload, headers):
        return self._request("POST", "/client-contracts", payload, headers)

    def submit_client_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"/client-contracts/{contract_id}/submit", payload or {}, headers
        )

    def client_decision(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/client-contracts/{contract_id}/client-decision", payload, headers
        )

    def service_status(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/client-contracts/{contract_id}/service-status", payload, headers
        )

    def create_amendment(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/client-contracts/{contract_id}/amendments", payload, headers
        )

    # ----------------------------------------------------------- staff members --
    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    def list_staff_member_credentials(self, staff_id, headers, params=None):
        return self._request(
            "GET", f"/staff-members/{staff_id}/credentials", headers=headers, params=params
        )

    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def record_drill(self, staff_id, payload, headers):
        return self._request("POST", f"/staff-members/{staff_id}/drills", payload, headers)

    def reinstate_duty(self, staff_id, headers, payload=None):
        return self._request(
            "POST", f"/staff-members/{staff_id}/duty-reinstate", payload or {}, headers
        )

    # ------------------------------------------------------- staff credentials --
    def get_staff_credential(self, credential_id, headers):
        return self._request(
            "GET", f"/staff-credentials/{credential_id}", headers=headers
        )

    def create_staff_credential(self, payload, headers):
        return self._request("POST", "/staff-credentials", payload, headers)

    def verify_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/staff-credentials/{credential_id}/verify", payload, headers
        )

    def renew_credential(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/staff-credentials/{credential_id}/renew", payload, headers
        )

    # ---------------------------------------------------------- facility rooms --
    def list_facility_rooms(self, headers, params=None):
        return self._request("GET", "/facility-rooms", headers=headers, params=params)

    def get_facility_room(self, room_id, headers):
        return self._request("GET", f"/facility-rooms/{room_id}", headers=headers)

    def create_facility_room(self, payload, headers):
        return self._request("POST", "/facility-rooms", payload, headers)

    def create_room_inspection(self, room_id, payload, headers):
        return self._request(
            "POST", f"/facility-rooms/{room_id}/inspections", payload, headers
        )

    # --------------------------------------------------------- facility assets --
    def list_facility_assets(self, headers, params=None):
        return self._request("GET", "/facility-assets", headers=headers, params=params)

    def get_facility_asset(self, asset_id, headers):
        return self._request("GET", f"/facility-assets/{asset_id}", headers=headers)

    def create_facility_asset(self, payload, headers):
        return self._request("POST", "/facility-assets", payload, headers)

    def create_service_event(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/facility-assets/{asset_id}/service-events", payload, headers
        )

    # -------------------------------------------------------- program offerings --
    def list_program_offerings(self, headers, params=None):
        return self._request("GET", "/program-offerings", headers=headers, params=params)

    def get_program_offering(self, offering_id, headers):
        return self._request("GET", f"/program-offerings/{offering_id}", headers=headers)

    def get_offering_attainment(self, offering_id, headers):
        return self._request(
            "GET", f"/program-offerings/{offering_id}/attainment", headers=headers
        )

    def create_program_offering(self, payload, headers):
        return self._request("POST", "/program-offerings", payload, headers)

    def offering_status_change(self, offering_id, payload, headers):
        return self._request(
            "POST", f"/program-offerings/{offering_id}/status-changes", payload, headers
        )

    # --------------------------------------------------------- program sessions --
    def list_program_sessions(self, headers, params=None):
        return self._request("GET", "/program-sessions", headers=headers, params=params)

    def get_program_session(self, session_id, headers):
        return self._request("GET", f"/program-sessions/{session_id}", headers=headers)

    def create_program_session(self, payload, headers):
        return self._request("POST", "/program-sessions", payload, headers)

    def session_status_change(self, session_id, payload, headers):
        return self._request(
            "POST", f"/program-sessions/{session_id}/status-changes", payload, headers
        )

    # -------------------------------------------------------- staff assignments --
    def list_staff_assignments(self, headers, params=None):
        return self._request("GET", "/staff-assignments", headers=headers, params=params)

    def get_staff_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/staff-assignments/{assignment_id}", headers=headers
        )

    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/staff-assignments", payload, headers)

    def confirm_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/confirm", payload or {}, headers
        )

    def release_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/release", payload or {}, headers
        )

    # ------------------------------------------------------------------ members --
    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_member_waivers(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/waivers", headers=headers, params=params
        )

    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def eligibility_decision(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/eligibility-decisions", payload, headers
        )

    def badge_access(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/badge-access", payload, headers
        )

    def create_waiver(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/waivers", payload, headers)

    # -------------------------------------------------------- liability waivers --
    def get_liability_waiver(self, waiver_id, headers):
        return self._request("GET", f"/liability-waivers/{waiver_id}", headers=headers)

    # ---------------------------------------------------- participation records --
    def list_participation_records(self, headers, params=None):
        return self._request(
            "GET", "/participation-records", headers=headers, params=params
        )

    def get_participation_record(self, record_id, headers):
        return self._request(
            "GET", f"/participation-records/{record_id}", headers=headers
        )

    def create_participation_record(self, payload, headers):
        return self._request("POST", "/participation-records", payload, headers)

    def void_participation_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/participation-records/{record_id}/void", payload, headers
        )

    # --------------------------------------------------------- incident reports --
    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def review_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/review", payload or {}, headers
        )

    def return_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/return", payload, headers
        )

    def file_claim(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/file-claim", payload, headers
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/close", payload, headers
        )

    # --------------------------------------------------------- monthly invoices --
    def list_monthly_invoices(self, headers, params=None):
        return self._request("GET", "/monthly-invoices", headers=headers, params=params)

    def get_monthly_invoice(self, invoice_id, headers):
        return self._request("GET", f"/monthly-invoices/{invoice_id}", headers=headers)

    def create_monthly_invoice(self, payload, headers):
        return self._request("POST", "/monthly-invoices", payload, headers)

    def issue_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/monthly-invoices/{invoice_id}/issue", payload or {}, headers
        )

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/monthly-invoices/{invoice_id}/dispute", payload, headers
        )

    def rebill_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/monthly-invoices/{invoice_id}/rebill", payload or {}, headers
        )

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/monthly-invoices/{invoice_id}/pay", payload or {}, headers
        )

    # --------------------------------------------------------------- operations --
    def get_readiness_summary(self, headers, params=None):
        return self._request(
            "GET", "/operations/readiness-summary", headers=headers, params=params
        )

    def daily_readiness_run(self, payload, headers):
        return self._request(
            "POST", "/operations/daily-readiness-run", payload, headers
        )


api_client = ApiClient()
