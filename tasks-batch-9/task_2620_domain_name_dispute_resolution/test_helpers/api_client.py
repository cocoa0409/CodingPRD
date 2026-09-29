"""API client: one method per endpoint defined in the PRD.

Every path is rooted at the /udrp prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/udrp"


class ApiClient(GenericApiClient):
    # --- Test-driving surfaces ------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def run_deadline_sweep(self, headers, payload=None):
        return self._request("POST", f"{PREFIX}/_ops/deadline-sweep", payload or {}, headers)

    # --- Registrars -----------------------------------------------------
    def create_registrar(self, payload, headers):
        return self._request("POST", f"{PREFIX}/registrars", payload, headers)

    def get_registrar(self, registrar_id, headers):
        return self._request("GET", f"{PREFIX}/registrars/{registrar_id}", headers=headers)

    def set_registrar_status(self, registrar_id, payload, headers):
        return self._request("POST", f"{PREFIX}/registrars/{registrar_id}/status", payload, headers)

    # --- Domains --------------------------------------------------------
    def create_domain(self, payload, headers):
        return self._request("POST", f"{PREFIX}/domains", payload, headers)

    def get_domain(self, domain_id, headers):
        return self._request("GET", f"{PREFIX}/domains/{domain_id}", headers=headers)

    def set_domain_lock(self, domain_id, payload, headers):
        return self._request("POST", f"{PREFIX}/domains/{domain_id}/lock", payload, headers)

    def list_domains(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/domains", headers=headers, params=params)

    # --- Complainants ---------------------------------------------------
    def create_complainant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complainants", payload, headers)

    def get_complainant(self, complainant_id, headers):
        return self._request("GET", f"{PREFIX}/complainants/{complainant_id}", headers=headers)

    # --- Panelist roster ------------------------------------------------
    def create_panelist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/panelists", payload, headers)

    def get_panelist(self, panelist_id, headers):
        return self._request("GET", f"{PREFIX}/panelists/{panelist_id}", headers=headers)

    def set_panelist_availability(self, panelist_id, payload, headers):
        return self._request("POST", f"{PREFIX}/panelists/{panelist_id}/availability", payload, headers)

    # --- Cases ----------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases", headers=headers, params=params)

    def withdraw_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/withdraw", payload, headers)

    # --- Grounds --------------------------------------------------------
    def create_ground(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/grounds", payload, headers)

    def list_grounds(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/grounds", headers=headers, params=params)

    # --- Case ledger ----------------------------------------------------
    def create_fee_transaction(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/fee-transactions", payload, headers)

    def list_fee_transactions(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/fee-transactions", headers=headers, params=params)

    # --- Deficiency notices and corrections -----------------------------
    def create_deficiency_notice(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/deficiency-notices", payload, headers)

    def list_deficiency_notices(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/deficiency-notices", headers=headers, params=params)

    def create_correction(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/corrections", payload, headers)

    def clear_compliance(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/compliance-clearance", payload, headers)

    # --- Registrar verification ----------------------------------------
    def rerequest_verification(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/registrar-verifications", payload, headers)

    def list_registrar_verifications(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/registrar-verifications", headers=headers, params=params)

    def respond_to_verification(self, case_id, verification_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cases/{case_id}/registrar-verifications/{verification_id}/response",
            payload,
            headers,
        )

    # --- Notification and delivery --------------------------------------
    def create_notification(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/notifications", payload, headers)

    def list_notifications(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/notifications", headers=headers, params=params)

    def record_delivery(self, case_id, notification_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cases/{case_id}/notifications/{notification_id}/delivery",
            payload,
            headers,
        )

    # --- Response -------------------------------------------------------
    def create_response(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/responses", payload, headers)

    def list_responses(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/responses", headers=headers, params=params)

    # --- Panel composition ----------------------------------------------
    def create_appointment(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"{PREFIX}/appointments/{appointment_id}", headers=headers)

    def screen_conflict(self, appointment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments/{appointment_id}/conflict-screening", payload, headers)

    def record_waiver(self, appointment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments/{appointment_id}/waiver", payload, headers)

    def replace_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appointments/{appointment_id}/replace", payload, headers)

    # --- Decisions, ballots and issuance --------------------------------
    def create_decision(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/decisions", payload, headers)

    def list_decisions(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/decisions", headers=headers, params=params)

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"{PREFIX}/decisions/{decision_id}", headers=headers)

    def cast_vote(self, decision_id, payload, headers):
        return self._request("POST", f"{PREFIX}/decisions/{decision_id}/votes", payload, headers)

    def list_votes(self, decision_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/decisions/{decision_id}/votes", headers=headers, params=params)

    def issue_decision(self, decision_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/decisions/{decision_id}/issue", payload or {}, headers)

    # --- Publication and precedents -------------------------------------
    def publish_decision(self, decision_id, payload, headers):
        return self._request("POST", f"{PREFIX}/decisions/{decision_id}/publish", payload, headers)

    def get_precedent_entry(self, decision_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/decisions/{decision_id}/precedent-entry", headers=headers, params=params)

    def search_precedents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/precedents", headers=headers, params=params)

    # --- Court challenges and execution ---------------------------------
    def create_court_challenge(self, decision_id, payload, headers):
        return self._request("POST", f"{PREFIX}/decisions/{decision_id}/court-challenges", payload, headers)

    def list_court_challenges(self, decision_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/decisions/{decision_id}/court-challenges", headers=headers, params=params)

    def resolve_court_challenge(self, challenge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/court-challenges/{challenge_id}/resolve", payload, headers)

    def implement_decision(self, decision_id, payload, headers):
        return self._request("POST", f"{PREFIX}/decisions/{decision_id}/implement", payload, headers)


api_client = ApiClient()
