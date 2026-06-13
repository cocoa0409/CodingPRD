"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only the PRD-specific endpoint
methods are defined here. The inherited _request(method, path, payload=None,
headers=None, params=None) performs the actual HTTP call. All resources are
served under the /disaster-relief mount (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient

P = "/disaster-relief"


class ApiClient(GenericApiClient):

    # ─── Logical clock (test-driving) ─────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set", payload, headers)

    # ─── DisasterDeclaration ──────────────────────────────────────────────
    def create_declaration(self, payload, headers):
        return self._request("POST", f"{P}/declarations", payload, headers)

    def get_declaration(self, declaration_id, headers):
        return self._request("GET", f"{P}/declarations/{declaration_id}", headers=headers)

    def list_declarations(self, headers, params=None):
        return self._request("GET", f"{P}/declarations", headers=headers, params=params)

    def close_registration(self, declaration_id, headers):
        return self._request("POST", f"{P}/declarations/{declaration_id}/close-registration", {}, headers)

    def close_declaration(self, declaration_id, headers):
        return self._request("POST", f"{P}/declarations/{declaration_id}/close", {}, headers)

    # ─── Inspector ────────────────────────────────────────────────────────
    def create_inspector(self, payload, headers):
        return self._request("POST", f"{P}/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"{P}/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", f"{P}/inspectors", headers=headers, params=params)

    # ─── Caseworker ───────────────────────────────────────────────────────
    def create_caseworker(self, payload, headers):
        return self._request("POST", f"{P}/caseworkers", payload, headers)

    def get_caseworker(self, caseworker_id, headers):
        return self._request("GET", f"{P}/caseworkers/{caseworker_id}", headers=headers)

    def list_caseworkers(self, headers, params=None):
        return self._request("GET", f"{P}/caseworkers", headers=headers, params=params)

    # ─── Applicant ────────────────────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{P}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{P}/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", f"{P}/applicants", headers=headers, params=params)

    def withdraw_applicant(self, applicant_id, headers):
        return self._request("POST", f"{P}/applicants/{applicant_id}/withdraw", {}, headers)

    # ─── DamageAssessment ─────────────────────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request("POST", f"{P}/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"{P}/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", f"{P}/assessments", headers=headers, params=params)

    def inspect_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{P}/assessments/{assessment_id}/inspect", payload, headers)

    def verify_assessment(self, assessment_id, headers):
        return self._request("POST", f"{P}/assessments/{assessment_id}/verify", {}, headers)

    def cancel_assessment(self, assessment_id, headers):
        return self._request("POST", f"{P}/assessments/{assessment_id}/cancel", {}, headers)

    # ─── IhpCase ──────────────────────────────────────────────────────────
    def create_ihp_case(self, payload, headers):
        return self._request("POST", f"{P}/ihp-cases", payload, headers)

    def get_ihp_case(self, case_id, headers):
        return self._request("GET", f"{P}/ihp-cases/{case_id}", headers=headers)

    def list_ihp_cases(self, headers, params=None):
        return self._request("GET", f"{P}/ihp-cases", headers=headers, params=params)

    def approve_ihp_case(self, case_id, headers):
        return self._request("POST", f"{P}/ihp-cases/{case_id}/approve", {}, headers)

    def deny_ihp_case(self, case_id, headers):
        return self._request("POST", f"{P}/ihp-cases/{case_id}/deny", {}, headers)

    def close_ihp_case(self, case_id, headers):
        return self._request("POST", f"{P}/ihp-cases/{case_id}/close", {}, headers)

    # ─── AwardLineItem ────────────────────────────────────────────────────
    def get_award_line_item(self, line_item_id, headers):
        return self._request("GET", f"{P}/award-line-items/{line_item_id}", headers=headers)

    def list_award_line_items(self, headers, params=None):
        return self._request("GET", f"{P}/award-line-items", headers=headers, params=params)

    # ─── DobRecord ────────────────────────────────────────────────────────
    def create_dob_record(self, payload, headers):
        return self._request("POST", f"{P}/dob-records", payload, headers)

    def get_dob_record(self, dob_id, headers):
        return self._request("GET", f"{P}/dob-records/{dob_id}", headers=headers)

    def list_dob_records(self, headers, params=None):
        return self._request("GET", f"{P}/dob-records", headers=headers, params=params)

    def reverse_dob_record(self, dob_id, headers):
        return self._request("POST", f"{P}/dob-records/{dob_id}/reverse", {}, headers)

    # ─── Appeal ───────────────────────────────────────────────────────────
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{P}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{P}/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{P}/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"{P}/appeals/{appeal_id}/decide", payload, headers)

    # ─── SbaReferral ──────────────────────────────────────────────────────
    def create_sba_referral(self, payload, headers):
        return self._request("POST", f"{P}/sba-referrals", payload, headers)

    def get_sba_referral(self, referral_id, headers):
        return self._request("GET", f"{P}/sba-referrals/{referral_id}", headers=headers)

    def list_sba_referrals(self, headers, params=None):
        return self._request("GET", f"{P}/sba-referrals", headers=headers, params=params)

    def record_sba_outcome(self, referral_id, payload, headers):
        return self._request("POST", f"{P}/sba-referrals/{referral_id}/record-outcome", payload, headers)

    # ─── Disbursement ─────────────────────────────────────────────────────
    def create_disbursement(self, payload, headers):
        return self._request("POST", f"{P}/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"{P}/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", f"{P}/disbursements", headers=headers, params=params)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"{P}/disbursements/{disbursement_id}/void", {}, headers)

    # ─── Recoupment ───────────────────────────────────────────────────────
    def get_recoupment(self, recoupment_id, headers):
        return self._request("GET", f"{P}/recoupments/{recoupment_id}", headers=headers)

    def list_recoupments(self, headers, params=None):
        return self._request("GET", f"{P}/recoupments", headers=headers, params=params)

    def record_recovery(self, recoupment_id, payload, headers):
        return self._request("POST", f"{P}/recoupments/{recoupment_id}/record-recovery", payload, headers)

    def waive_recoupment(self, recoupment_id, headers):
        return self._request("POST", f"{P}/recoupments/{recoupment_id}/waive", {}, headers)

    # ─── RentalAssistancePeriod ───────────────────────────────────────────
    def create_rental_period(self, payload, headers):
        return self._request("POST", f"{P}/rental-periods", payload, headers)

    def get_rental_period(self, period_id, headers):
        return self._request("GET", f"{P}/rental-periods/{period_id}", headers=headers)

    def list_rental_periods(self, headers, params=None):
        return self._request("GET", f"{P}/rental-periods", headers=headers, params=params)

    def close_rental_period(self, period_id, headers):
        return self._request("POST", f"{P}/rental-periods/{period_id}/close", {}, headers)


api_client = ApiClient()
