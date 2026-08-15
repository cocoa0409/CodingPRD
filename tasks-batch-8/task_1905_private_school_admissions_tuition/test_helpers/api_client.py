"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )

    # --- admission cycles ---
    def create_cycle(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/cycles", payload, headers)

    def list_cycles(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/admissions/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id: str, headers: Dict):
        return self._request("GET", f"/admissions/cycles/{cycle_id}", headers=headers)

    def open_cycle(self, cycle_id: str, headers: Dict):
        return self._request("POST", f"/admissions/cycles/{cycle_id}/open", {}, headers)

    def close_round(self, cycle_id: str, round_name: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/cycles/{cycle_id}/close-round",
            {"round": round_name}, headers,
        )

    def run_sweep(self, cycle_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/cycles/{cycle_id}/run-sweep", {}, headers,
        )

    def archive_cycle(self, cycle_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/cycles/{cycle_id}/archive", {}, headers,
        )

    # --- grade sections ---
    def create_grade_section(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/grade-sections", payload, headers)

    def list_grade_sections(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/admissions/grade-sections", headers=headers, params=params,
        )

    def get_grade_section(self, section_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/grade-sections/{section_id}", headers=headers,
        )

    # --- applicants ---
    def create_applicant(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/applicants", payload, headers)

    def list_applicants(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/admissions/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/applicants/{applicant_id}", headers=headers,
        )

    # --- students ---
    def create_student(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/students", payload, headers)

    def list_students(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/admissions/students", headers=headers, params=params)

    def get_student(self, student_id: str, headers: Dict):
        return self._request("GET", f"/admissions/students/{student_id}", headers=headers)

    # --- applications ---
    def create_application(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/applications", payload, headers)

    def list_applications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/admissions/applications", headers=headers, params=params,
        )

    def get_application(self, application_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/applications/{application_id}", headers=headers,
        )

    def submit_application(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/applications/{application_id}/submit", {}, headers,
        )

    def issue_contract(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/applications/{application_id}/issue-contract",
            {}, headers,
        )

    def decline_application(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/applications/{application_id}/decline", {}, headers,
        )

    def withdraw_application(self, application_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/applications/{application_id}/withdraw", {}, headers,
        )

    # --- entrance evaluations ---
    def create_evaluation(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/evaluations", payload, headers)

    def reschedule_evaluation(self, evaluation_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"/admissions/evaluations/{evaluation_id}", payload, headers,
        )

    def score_evaluation(self, evaluation_id: str, score: int, headers: Dict):
        return self._request(
            "POST", f"/admissions/evaluations/{evaluation_id}/score",
            {"score": score}, headers,
        )

    def cancel_evaluation(self, evaluation_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/evaluations/{evaluation_id}/cancel", {}, headers,
        )

    def list_evaluations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/admissions/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/evaluations/{evaluation_id}", headers=headers,
        )

    # --- test sessions ---
    def create_test_session(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/test-sessions", payload, headers)

    def list_test_sessions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/admissions/test-sessions", headers=headers, params=params,
        )

    def get_test_session(self, session_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/test-sessions/{session_id}", headers=headers,
        )

    # --- financial aid ---
    def create_aid_application(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/aid-applications", payload, headers)

    def list_aid_applications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/admissions/aid-applications", headers=headers, params=params,
        )

    def get_aid_application(self, aid_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/aid-applications/{aid_id}", headers=headers,
        )

    def verify_aid(self, aid_id: str, verified_annual_income_cents: int, headers: Dict):
        return self._request(
            "POST", f"/admissions/aid-applications/{aid_id}/verify",
            {"verified_annual_income_cents": verified_annual_income_cents}, headers,
        )

    def resubmit_income(self, aid_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/admissions/aid-applications/{aid_id}/resubmit-income",
            payload, headers,
        )

    def finalize_award(self, aid_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/aid-applications/{aid_id}/finalize-award", {}, headers,
        )

    def accept_award(self, aid_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/aid-applications/{aid_id}/accept-award", {}, headers,
        )

    def appeal_award(self, aid_id: str, appeal_reason: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/aid-applications/{aid_id}/appeal-award",
            {"appeal_reason": appeal_reason}, headers,
        )

    def revise_award(self, aid_id: str, revised_final_amount_cents: int, headers: Dict):
        return self._request(
            "POST", f"/admissions/aid-applications/{aid_id}/revise-award",
            {"revised_final_amount_cents": revised_final_amount_cents}, headers,
        )

    # --- enrollment contracts ---
    def list_contracts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/admissions/contracts", headers=headers, params=params)

    def get_contract(self, contract_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/contracts/{contract_id}", headers=headers,
        )

    def sign_contract(self, contract_id: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/contracts/{contract_id}/sign", {}, headers,
        )

    def pay_deposit(self, contract_id: str, amount_cents: int, headers: Dict):
        return self._request(
            "POST", f"/admissions/contracts/{contract_id}/deposit-payments",
            {"amount_cents": amount_cents}, headers,
        )

    # --- re-enrollment offers ---
    def create_reenrollment_offer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/admissions/reenrollment-offers", payload, headers)

    def list_reenrollment_offers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/admissions/reenrollment-offers", headers=headers, params=params,
        )

    def get_reenrollment_offer(self, offer_id: str, headers: Dict):
        return self._request(
            "GET", f"/admissions/reenrollment-offers/{offer_id}", headers=headers,
        )

    def respond_reenrollment_offer(self, offer_id: str, decision: str, headers: Dict):
        return self._request(
            "POST", f"/admissions/reenrollment-offers/{offer_id}/respond",
            {"decision": decision}, headers,
        )


api_client = ApiClient()
