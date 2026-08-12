"""API client: one method per endpoint defined in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/compliance/_clock/set_current_utc", payload, headers)

    # --- CountryRiskProfile ---
    def create_country_profile(self, payload, headers=None):
        return self._request("POST", "/compliance/country-risk-profiles", payload, headers)

    def update_country_profile(self, profile_id, payload, headers=None):
        return self._request("PATCH", f"/compliance/country-risk-profiles/{profile_id}", payload, headers)

    # --- RiskScoringPolicy ---
    def create_policy(self, payload, headers=None):
        return self._request("POST", "/compliance/risk-scoring-policies", payload, headers)

    def activate_policy(self, policy_id, payload, headers=None):
        return self._request("POST", f"/compliance/risk-scoring-policies/{policy_id}/activate", payload, headers)

    def get_policy(self, policy_id, headers=None):
        return self._request("GET", f"/compliance/risk-scoring-policies/{policy_id}", headers=headers)

    # --- ThirdParty ---
    def create_third_party(self, payload, headers=None):
        return self._request("POST", "/compliance/third-parties", payload, headers)

    def get_third_party(self, third_party_id, headers=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}", headers=headers)

    def list_third_parties(self, headers=None, params=None):
        return self._request("GET", "/compliance/third-parties", headers=headers, params=params)

    def patch_third_party(self, third_party_id, payload, headers=None):
        return self._request("PATCH", f"/compliance/third-parties/{third_party_id}", payload, headers)

    def submit_third_party(self, third_party_id, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/submit", {}, headers)

    def approve_third_party(self, third_party_id, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/approve", {}, headers)

    def reject_third_party(self, third_party_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/reject", payload or {}, headers)

    def suspend_third_party(self, third_party_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/suspend", payload or {}, headers)

    def reinstate_third_party(self, third_party_id, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/reinstate", {}, headers)

    def terminate_third_party(self, third_party_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/terminate", payload or {}, headers)

    # --- ScreeningCheck ---
    def disposition_screening_check(self, check_id, payload, headers=None):
        return self._request("POST", f"/compliance/screening-checks/{check_id}/disposition", payload, headers)

    def list_screening_checks(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/screening-checks", headers=headers, params=params)

    # --- Questionnaire ---
    def issue_questionnaire(self, third_party_id, payload, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/questionnaires", payload, headers)

    def submit_questionnaire(self, questionnaire_id, payload, headers=None):
        return self._request("POST", f"/compliance/questionnaires/{questionnaire_id}/submit", payload, headers)

    def accept_questionnaire(self, questionnaire_id, headers=None):
        return self._request("POST", f"/compliance/questionnaires/{questionnaire_id}/accept", {}, headers)

    def return_questionnaire(self, questionnaire_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/questionnaires/{questionnaire_id}/return", payload or {}, headers)

    def list_questionnaires(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/questionnaires", headers=headers, params=params)

    # --- RedFlag ---
    def create_red_flag(self, third_party_id, payload, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/red-flags", payload, headers)

    def disposition_red_flag(self, flag_id, payload, headers=None):
        return self._request("POST", f"/compliance/red-flags/{flag_id}/disposition", payload, headers)

    def list_red_flags(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/red-flags", headers=headers, params=params)

    # --- EscalationCase ---
    def decide_escalation_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/compliance/escalation-cases/{case_id}/decide", payload, headers)

    def list_escalation_cases(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/escalation-cases", headers=headers, params=params)

    # --- Contract ---
    def create_contract(self, third_party_id, payload, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/contracts", payload, headers)

    def attach_clauses(self, contract_id, payload, headers=None):
        return self._request("POST", f"/compliance/contracts/{contract_id}/attach-clauses", payload, headers)

    def activate_contract(self, contract_id, headers=None):
        return self._request("POST", f"/compliance/contracts/{contract_id}/activate", {}, headers)

    def get_contract(self, contract_id, headers=None):
        return self._request("GET", f"/compliance/contracts/{contract_id}", headers=headers)

    def list_contracts(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/contracts", headers=headers, params=params)

    # --- Certification ---
    def create_certification(self, third_party_id, payload, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/certifications", payload, headers)

    def submit_certification(self, certification_id, payload, headers=None):
        return self._request("POST", f"/compliance/certifications/{certification_id}/submit", payload, headers)

    def verify_certification(self, certification_id, headers=None):
        return self._request("POST", f"/compliance/certifications/{certification_id}/verify", {}, headers)

    def reject_certification(self, certification_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/certifications/{certification_id}/reject", payload or {}, headers)

    def list_certifications(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/certifications", headers=headers, params=params)

    # --- PaymentRequest ---
    def create_payment_request(self, contract_id, payload, headers=None):
        return self._request("POST", f"/compliance/contracts/{contract_id}/payment-requests", payload, headers)

    def approve_payment(self, payment_id, headers=None):
        return self._request("POST", f"/compliance/payment-requests/{payment_id}/approve", {}, headers)

    def block_payment(self, payment_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/payment-requests/{payment_id}/block", payload or {}, headers)

    def reverse_payment(self, payment_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/payment-requests/{payment_id}/reverse", payload or {}, headers)

    def list_payment_requests(self, contract_id, headers=None, params=None):
        return self._request("GET", f"/compliance/contracts/{contract_id}/payment-requests", headers=headers, params=params)

    # --- GiftHospitalityEntry ---
    def create_gift_entry(self, third_party_id, payload, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/gift-hospitality-entries", payload, headers)

    def approve_gift_entry(self, entry_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/gift-hospitality-entries/{entry_id}/approve", payload or {}, headers)

    def reject_gift_entry(self, entry_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/gift-hospitality-entries/{entry_id}/reject", payload or {}, headers)

    def void_gift_entry(self, entry_id, payload=None, headers=None):
        return self._request("POST", f"/compliance/gift-hospitality-entries/{entry_id}/void", payload or {}, headers)

    def list_gift_entries(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/gift-hospitality-entries", headers=headers, params=params)

    # --- ReDiligenceCycle ---
    def create_rediligence_cycle(self, third_party_id, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/rediligence-cycles", {}, headers)

    def start_rediligence_cycle(self, cycle_id, headers=None):
        return self._request("POST", f"/compliance/rediligence-cycles/{cycle_id}/start", {}, headers)

    def complete_rediligence_cycle(self, cycle_id, payload, headers=None):
        return self._request("POST", f"/compliance/rediligence-cycles/{cycle_id}/complete", payload, headers)

    def list_rediligence_cycles(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/rediligence-cycles", headers=headers, params=params)

    # --- AuditExercise ---
    def create_audit_exercise(self, third_party_id, payload, headers=None):
        return self._request("POST", f"/compliance/third-parties/{third_party_id}/audit-exercises", payload, headers)

    def begin_fieldwork(self, audit_id, headers=None):
        return self._request("POST", f"/compliance/audit-exercises/{audit_id}/begin-fieldwork", {}, headers)

    def issue_findings(self, audit_id, payload, headers=None):
        return self._request("POST", f"/compliance/audit-exercises/{audit_id}/issue-findings", payload, headers)

    def close_audit(self, audit_id, headers=None):
        return self._request("POST", f"/compliance/audit-exercises/{audit_id}/close", {}, headers)

    def list_audit_exercises(self, third_party_id, headers=None, params=None):
        return self._request("GET", f"/compliance/third-parties/{third_party_id}/audit-exercises", headers=headers, params=params)

    # --- TrainingAssignment ---
    def create_training_assignment(self, payload, headers=None):
        return self._request("POST", "/compliance/training-assignments", payload, headers)

    def complete_training_assignment(self, assignment_id, headers=None):
        return self._request("POST", f"/compliance/training-assignments/{assignment_id}/complete", {}, headers)

    def list_training_assignments(self, headers=None, params=None):
        return self._request("GET", "/compliance/training-assignments", headers=headers, params=params)


api_client = ApiClient()
