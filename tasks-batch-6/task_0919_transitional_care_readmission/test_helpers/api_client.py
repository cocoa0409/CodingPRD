"""API client: one method per endpoint described in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock and programme configuration ------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_holidays(self, payload, headers):
        return self._request("POST", "/tcm/holidays", payload, headers)

    # ---- reference data ---------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/tcm/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/tcm/patients/{patient_id}", headers=headers)

    def create_facility(self, payload, headers):
        return self._request("POST", "/tcm/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/tcm/facilities/{facility_id}", headers=headers)

    def create_payer(self, payload, headers):
        return self._request("POST", "/tcm/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/tcm/payers/{payer_id}", headers=headers)

    def create_navigator(self, payload, headers):
        return self._request("POST", "/tcm/navigators", payload, headers)

    def get_navigator(self, navigator_id, headers):
        return self._request("GET", f"/tcm/navigators/{navigator_id}", headers=headers)

    # ---- discharge referral intake ---------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/tcm/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/tcm/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/tcm/referrals", headers=headers, params=params)

    def accept_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/tcm/referrals/{referral_id}/accept", payload, headers
        )

    def close_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/tcm/referrals/{referral_id}/close", payload, headers
        )

    # ---- care episode -----------------------------------------------------
    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/tcm/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/tcm/episodes", headers=headers, params=params)

    def close_service_period(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/close-service-period", payload or {}, headers
        )

    def admin_close_episode(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/admin-close", payload, headers
        )

    def run_sla_sweep(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/sla-sweep", payload or {}, headers
        )

    # ---- risk assessment --------------------------------------------------
    def create_risk_assessment(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/risk-assessments", payload, headers
        )

    def get_risk_assessment(self, risk_assessment_id, headers):
        return self._request(
            "GET", f"/tcm/risk-assessments/{risk_assessment_id}", headers=headers
        )

    def list_risk_assessments(self, headers, params=None):
        return self._request(
            "GET", "/tcm/risk-assessments", headers=headers, params=params
        )

    # ---- interactive contact ----------------------------------------------
    def log_contact_attempt(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/contact-attempts", payload, headers
        )

    def get_contact_attempt(self, contact_attempt_id, headers):
        return self._request(
            "GET", f"/tcm/contact-attempts/{contact_attempt_id}", headers=headers
        )

    def list_contact_attempts(self, headers, params=None):
        return self._request(
            "GET", "/tcm/contact-attempts", headers=headers, params=params
        )

    def disposition_contact_attempt(self, contact_attempt_id, payload, headers):
        return self._request(
            "POST",
            f"/tcm/contact-attempts/{contact_attempt_id}/disposition",
            payload,
            headers,
        )

    # ---- face-to-face visit -----------------------------------------------
    def book_visit(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/visits", payload, headers
        )

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/tcm/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/tcm/visits", headers=headers, params=params)

    def confirm_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/visits/{visit_id}/confirm", payload or {}, headers
        )

    def complete_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/tcm/visits/{visit_id}/complete", payload, headers
        )

    def close_visit_encounter(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/tcm/visits/{visit_id}/close-encounter", payload, headers
        )

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/tcm/visits/{visit_id}/reschedule", payload, headers
        )

    def attest_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/visits/{visit_id}/attest", payload or {}, headers
        )

    def amend_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/tcm/visits/{visit_id}/amend", payload, headers)

    # ---- medication reconciliation ----------------------------------------
    def open_med_reconciliation(self, episode_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tcm/episodes/{episode_id}/med-reconciliations",
            payload or {},
            headers,
        )

    def get_med_reconciliation(self, med_reconciliation_id, headers):
        return self._request(
            "GET", f"/tcm/med-reconciliations/{med_reconciliation_id}", headers=headers
        )

    def list_med_reconciliations(self, headers, params=None):
        return self._request(
            "GET", "/tcm/med-reconciliations", headers=headers, params=params
        )

    def append_discrepancy(self, med_reconciliation_id, payload, headers):
        return self._request(
            "POST",
            f"/tcm/med-reconciliations/{med_reconciliation_id}/discrepancies",
            payload,
            headers,
        )

    def get_discrepancy(self, discrepancy_id, headers):
        return self._request(
            "GET", f"/tcm/discrepancies/{discrepancy_id}", headers=headers
        )

    def list_discrepancies(self, headers, params=None):
        return self._request(
            "GET", "/tcm/discrepancies", headers=headers, params=params
        )

    def disposition_discrepancy(self, discrepancy_id, payload, headers):
        return self._request(
            "POST", f"/tcm/discrepancies/{discrepancy_id}/disposition", payload, headers
        )

    def reopen_discrepancy(self, discrepancy_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/discrepancies/{discrepancy_id}/reopen", payload or {}, headers
        )

    def complete_med_reconciliation(self, med_reconciliation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tcm/med-reconciliations/{med_reconciliation_id}/complete",
            payload or {},
            headers,
        )

    def reopen_med_reconciliation(self, med_reconciliation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tcm/med-reconciliations/{med_reconciliation_id}/reopen",
            payload or {},
            headers,
        )

    # ---- typed barriers ---------------------------------------------------
    def raise_barrier(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/barriers", payload, headers
        )

    def get_barrier(self, barrier_id, headers):
        return self._request("GET", f"/tcm/barriers/{barrier_id}", headers=headers)

    def list_barriers(self, headers, params=None):
        return self._request("GET", "/tcm/barriers", headers=headers, params=params)

    def close_barrier(self, barrier_id, payload, headers):
        return self._request(
            "POST", f"/tcm/barriers/{barrier_id}/close", payload, headers
        )

    # ---- red flags --------------------------------------------------------
    def raise_red_flag(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/red-flags", payload, headers
        )

    def get_red_flag(self, red_flag_id, headers):
        return self._request("GET", f"/tcm/red-flags/{red_flag_id}", headers=headers)

    def list_red_flags(self, headers, params=None):
        return self._request("GET", "/tcm/red-flags", headers=headers, params=params)

    def acknowledge_red_flag(self, red_flag_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/red-flags/{red_flag_id}/acknowledge", payload or {}, headers
        )

    def resolve_red_flag(self, red_flag_id, payload, headers):
        return self._request(
            "POST", f"/tcm/red-flags/{red_flag_id}/resolve", payload, headers
        )

    # ---- 30-day readmission tracking --------------------------------------
    def record_readmission(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/readmissions", payload, headers
        )

    def get_readmission(self, readmission_id, headers):
        return self._request(
            "GET", f"/tcm/readmissions/{readmission_id}", headers=headers
        )

    def list_readmissions(self, headers, params=None):
        return self._request("GET", "/tcm/readmissions", headers=headers, params=params)

    def retract_readmission(self, readmission_id, payload, headers):
        return self._request(
            "POST", f"/tcm/readmissions/{readmission_id}/retract", payload, headers
        )

    # ---- TCM-code billing -------------------------------------------------
    def prepare_claim(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/claims", payload, headers
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/tcm/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/tcm/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/claims/{claim_id}/submit", payload or {}, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/tcm/claims/{claim_id}/adjudicate", payload, headers
        )

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/claims/{claim_id}/appeal", payload or {}, headers
        )

    def void_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/tcm/claims/{claim_id}/void", payload or {}, headers
        )

    # ---- care-team handoff ------------------------------------------------
    def propose_handoff(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/tcm/episodes/{episode_id}/handoffs", payload, headers
        )

    def get_handoff(self, handoff_id, headers):
        return self._request("GET", f"/tcm/handoffs/{handoff_id}", headers=headers)

    def list_handoffs(self, headers, params=None):
        return self._request("GET", "/tcm/handoffs", headers=headers, params=params)

    def respond_handoff(self, handoff_id, payload, headers):
        return self._request(
            "POST", f"/tcm/handoffs/{handoff_id}/respond", payload, headers
        )


api_client = ApiClient()
