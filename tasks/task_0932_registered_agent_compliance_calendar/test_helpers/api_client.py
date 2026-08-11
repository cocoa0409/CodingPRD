"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock and ops-run --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_calendar(self, headers):
        return self._request("POST", "/_ops/advance-calendar", {}, headers)

    # --- Clients ------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def get_portfolio_summary(self, client_id, headers):
        return self._request(
            "GET", f"/clients/{client_id}/portfolio-summary", headers=headers
        )

    def list_client_legal_entities(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/legal-entities", headers=headers, params=params
        )

    def create_payment(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/payments", payload, headers)

    def list_client_payments(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/payments", headers=headers, params=params
        )

    # --- Jurisdiction rules -------------------------------------------------
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/state-rules", payload, headers)

    def list_state_rules(self, headers, params=None):
        return self._request("GET", "/state-rules", headers=headers, params=params)

    # --- Legal entities -----------------------------------------------------
    def create_legal_entity(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/legal-entities", payload, headers
        )

    def get_legal_entity(self, entity_id, headers):
        return self._request("GET", f"/legal-entities/{entity_id}", headers=headers)

    def update_legal_entity(self, entity_id, payload, headers):
        return self._request("PATCH", f"/legal-entities/{entity_id}", payload, headers)

    def activate_legal_entity(self, entity_id, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/activate", {}, headers
        )

    def begin_wind_down(self, entity_id, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/begin-wind-down", {}, headers
        )

    def abort_wind_down(self, entity_id, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/abort-wind-down", {}, headers
        )

    def dissolve_legal_entity(self, entity_id, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/dissolve", {}, headers
        )

    # --- Beneficial owners --------------------------------------------------
    def create_beneficial_owner(self, entity_id, payload, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/beneficial-owners", payload, headers
        )

    def list_beneficial_owners(self, entity_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-entities/{entity_id}/beneficial-owners",
            headers=headers,
            params=params,
        )

    def update_beneficial_owner(self, owner_id, payload, headers):
        return self._request(
            "PATCH", f"/beneficial-owners/{owner_id}", payload, headers
        )

    # --- Name clearances ----------------------------------------------------
    def create_name_clearance(self, entity_id, payload, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/name-clearances", payload, headers
        )

    def list_name_clearances(self, entity_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-entities/{entity_id}/name-clearances",
            headers=headers,
            params=params,
        )

    def record_name_clearance_result(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"/name-clearances/{clearance_id}/record-result", payload, headers
        )

    # --- Registrations ------------------------------------------------------
    def create_home_registration(self, entity_id, headers, payload=None):
        return self._request(
            "POST",
            f"/legal-entities/{entity_id}/registrations",
            payload if payload is not None else {},
            headers,
        )

    def create_foreign_qualification(self, entity_id, payload, headers):
        return self._request(
            "POST",
            f"/legal-entities/{entity_id}/foreign-qualifications",
            payload,
            headers,
        )

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers
        )

    def activate_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/activate", {}, headers
        )

    def withdraw_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    def administratively_dissolve_registration(self, registration_id, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/administratively-dissolve",
            {},
            headers,
        )

    def terminate_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/terminate",
            payload if payload is not None else {},
            headers,
        )

    # --- Good-standing certificates ----------------------------------------
    def create_good_standing_certificate(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/good-standing-certificates",
            payload,
            headers,
        )

    def list_good_standing_certificates(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrations/{registration_id}/good-standing-certificates",
            headers=headers,
            params=params,
        )

    # --- Agent appointments -------------------------------------------------
    def create_agent_appointment(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/agent-appointments",
            payload,
            headers,
        )

    def list_agent_appointments(self, headers, params=None):
        return self._request(
            "GET", "/agent-appointments", headers=headers, params=params
        )

    def get_agent_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/agent-appointments/{appointment_id}", headers=headers
        )

    def accept_agent_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/agent-appointments/{appointment_id}/accept", {}, headers
        )

    def reject_agent_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/agent-appointments/{appointment_id}/reject", {}, headers
        )

    def notice_resignation(self, appointment_id, headers):
        return self._request(
            "POST",
            f"/agent-appointments/{appointment_id}/notice-resignation",
            {},
            headers,
        )

    # --- Compliance calendar ------------------------------------------------
    def create_compliance_obligation(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/compliance-obligations",
            payload,
            headers,
        )

    def list_compliance_obligations(self, headers, params=None):
        return self._request(
            "GET", "/compliance-obligations", headers=headers, params=params
        )

    def get_compliance_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"/compliance-obligations/{obligation_id}", headers=headers
        )

    def waive_compliance_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"/compliance-obligations/{obligation_id}/waive", payload, headers
        )

    def list_reminders(self, obligation_id, headers, params=None):
        return self._request(
            "GET",
            f"/compliance-obligations/{obligation_id}/reminders",
            headers=headers,
            params=params,
        )

    def calendar_rebuild(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/calendar-rebuild",
            payload,
            headers,
        )

    # --- Filings ------------------------------------------------------------
    def create_obligation_filing(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"/compliance-obligations/{obligation_id}/filings", payload, headers
        )

    def create_standalone_filing(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/filings", payload, headers
        )

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/submit", {}, headers)

    def record_filing_outcome(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/filings/{filing_id}/record-outcome", payload, headers
        )

    def refile_filing(self, filing_id, headers, payload=None):
        return self._request(
            "POST",
            f"/filings/{filing_id}/refile",
            payload if payload is not None else {},
            headers,
        )

    def abandon_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/abandon", {}, headers)

    # --- Money --------------------------------------------------------------
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def capture_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/payments/{payment_id}/capture", payload, headers
        )

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/void", {}, headers)

    def list_payment_allocations(self, payment_id, headers, params=None):
        return self._request(
            "GET", f"/payments/{payment_id}/allocations", headers=headers, params=params
        )

    def list_filing_allocations(self, filing_id, headers, params=None):
        return self._request(
            "GET",
            f"/filings/{filing_id}/payment-allocations",
            headers=headers,
            params=params,
        )

    # --- Service of process -------------------------------------------------
    def create_sop_document(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/sop-documents", payload, headers
        )

    def list_sop_documents(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrations/{registration_id}/sop-documents",
            headers=headers,
            params=params,
        )

    def get_sop_document(self, sop_document_id, headers):
        return self._request(
            "GET", f"/sop-documents/{sop_document_id}", headers=headers
        )

    def scan_sop_document(self, sop_document_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sop-documents/{sop_document_id}/scan",
            payload if payload is not None else {},
            headers,
        )

    def forward_sop_document(self, sop_document_id, headers):
        return self._request(
            "POST", f"/sop-documents/{sop_document_id}/forward", {}, headers
        )

    def acknowledge_sop_document(self, sop_document_id, headers):
        return self._request(
            "POST", f"/sop-documents/{sop_document_id}/acknowledge", {}, headers
        )

    def escalate_sop_document(self, sop_document_id, headers):
        return self._request(
            "POST", f"/sop-documents/{sop_document_id}/escalate", {}, headers
        )

    def list_sop_escalations(self, sop_document_id, headers, params=None):
        return self._request(
            "GET",
            f"/sop-documents/{sop_document_id}/escalations",
            headers=headers,
            params=params,
        )

    # --- Beneficial-ownership reports --------------------------------------
    def create_boi_report(self, entity_id, payload, headers):
        return self._request(
            "POST", f"/legal-entities/{entity_id}/boi-reports", payload, headers
        )

    def list_boi_reports(self, entity_id, headers, params=None):
        return self._request(
            "GET",
            f"/legal-entities/{entity_id}/boi-reports",
            headers=headers,
            params=params,
        )

    def submit_boi_report(self, report_id, headers):
        return self._request("POST", f"/boi-reports/{report_id}/submit", {}, headers)

    def record_boi_outcome(self, report_id, payload, headers):
        return self._request(
            "POST", f"/boi-reports/{report_id}/record-outcome", payload, headers
        )

    # --- Reinstatement ------------------------------------------------------
    def create_reinstatement_case(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/reinstatement-cases",
            payload if payload is not None else {},
            headers,
        )

    def list_reinstatement_cases(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrations/{registration_id}/reinstatement-cases",
            headers=headers,
            params=params,
        )

    def assess_reinstatement_fees(self, case_id, headers):
        return self._request(
            "POST", f"/reinstatement-cases/{case_id}/assess-fees", {}, headers
        )

    def grant_reinstatement(self, case_id, headers):
        return self._request(
            "POST", f"/reinstatement-cases/{case_id}/grant", {}, headers
        )

    def deny_reinstatement(self, case_id, payload, headers):
        return self._request(
            "POST", f"/reinstatement-cases/{case_id}/deny", payload, headers
        )


api_client = ApiClient()
