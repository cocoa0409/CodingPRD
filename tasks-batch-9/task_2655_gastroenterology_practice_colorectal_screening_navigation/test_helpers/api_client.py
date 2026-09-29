"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Colorectal Screening Navigation API client."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Insurance plans ──────────────────────────────

    def create_insurance_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    # ─── Clinicians ───────────────────────────────────

    def create_clinician(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    # ─── Patients ─────────────────────────────────────

    def create_patient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ─── Room blocks (endoscopy sessions) ─────────────

    def create_endoscopy_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/endoscopy-sessions", payload, headers)

    def get_endoscopy_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/endoscopy-sessions/{session_id}", headers=headers)

    def list_endoscopy_sessions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/endoscopy-sessions", headers=headers, params=params)

    def session_status_action(self, session_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/endoscopy-sessions/{session_id}/status-actions", payload, headers
        )

    # ─── Anesthesia coverage ──────────────────────────

    def create_anesthesia_coverage(self, session_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/endoscopy-sessions/{session_id}/anesthesia-coverage", payload, headers
        )

    def get_anesthesia_coverage(self, coverage_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/anesthesia-coverage/{coverage_id}", headers=headers)

    def list_anesthesia_coverage(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/anesthesia-coverage", headers=headers, params=params)

    def release_anesthesia_coverage(self, coverage_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/anesthesia-coverage/{coverage_id}", headers=headers)

    # ─── Referrals ────────────────────────────────────

    def create_referral(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def referral_triage_action(self, referral_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/referrals/{referral_id}/triage-actions", payload, headers
        )

    # ─── Screening episodes ───────────────────────────

    def create_screening_episode(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/screening-episodes", payload, headers)

    def get_screening_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/screening-episodes/{episode_id}", headers=headers)

    def list_screening_episodes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/screening-episodes", headers=headers, params=params)

    def close_screening_episode(self, episode_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/screening-episodes/{episode_id}/close", payload, headers
        )

    def record_outreach(self, episode_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/screening-episodes/{episode_id}/outreach", payload, headers
        )

    def submit_prep_attestation(self, episode_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/screening-episodes/{episode_id}/prep-attestation", payload, headers
        )

    # ─── Non-invasive tests ───────────────────────────

    def create_noninvasive_test(self, episode_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/screening-episodes/{episode_id}/noninvasive-tests", payload, headers
        )

    def get_noninvasive_test(self, test_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/noninvasive-tests/{test_id}", headers=headers)

    def list_noninvasive_tests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/noninvasive-tests", headers=headers, params=params)

    def post_noninvasive_test_result(self, test_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/noninvasive-tests/{test_id}/result", payload, headers
        )

    # ─── Procedure bookings ───────────────────────────

    def create_procedure_booking(self, session_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/endoscopy-sessions/{session_id}/procedure-bookings", payload, headers
        )

    def get_procedure_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/procedure-bookings/{booking_id}", headers=headers)

    def list_procedure_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/procedure-bookings", headers=headers, params=params)

    def check_in_booking(self, booking_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/check-in", payload or {}, headers
        )

    def start_procedure(self, booking_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/start", payload or {}, headers
        )

    def complete_procedure(self, booking_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/complete", payload, headers
        )

    def abort_procedure(self, booking_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/abort", payload, headers
        )

    def cancel_booking(self, booking_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/cancel", payload, headers
        )

    # ─── Pathology reports ────────────────────────────

    def create_pathology_report(self, booking_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/procedure-bookings/{booking_id}/pathology-reports", payload, headers
        )

    def get_pathology_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pathology-reports/{report_id}", headers=headers)

    def list_pathology_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/pathology-reports", headers=headers, params=params)

    def finalize_pathology_report(self, report_id: str, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pathology-reports/{report_id}/finalize", payload or {}, headers
        )

    def amend_pathology_report(self, report_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/pathology-reports/{report_id}/amend", payload, headers
        )

    # ─── Surveillance recommendations ─────────────────

    def create_surveillance_recommendation(self, episode_id: str, payload: Dict[str, Any],
                                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/screening-episodes/{episode_id}/surveillance-recommendations",
            payload,
            headers,
        )

    def get_surveillance_recommendation(self, recommendation_id: str,
                                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/surveillance-recommendations/{recommendation_id}", headers=headers
        )

    def list_surveillance_recommendations(self, headers: Dict[str, str],
                                          params: Optional[Dict] = None):
        return self._request(
            "GET", "/surveillance-recommendations", headers=headers, params=params
        )

    # ─── Billing claims ───────────────────────────────

    def get_billing_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/billing-claims/{claim_id}", headers=headers)

    def list_billing_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/billing-claims", headers=headers, params=params)

    def finalize_billing_claim(self, claim_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/billing-claims/{claim_id}/finalize", payload or {}, headers
        )

    def dispute_billing_claim(self, claim_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/billing-claims/{claim_id}/dispute", payload, headers
        )

    def reprice_billing_claim(self, claim_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/billing-claims/{claim_id}/reprice", payload or {}, headers
        )

    # ─── Quality periods ──────────────────────────────

    def create_quality_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/quality-periods", payload, headers)

    def get_quality_period(self, period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/quality-periods/{period_id}", headers=headers)

    def list_quality_periods(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/quality-periods", headers=headers, params=params)

    def lock_quality_period(self, period_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/quality-periods/{period_id}/lock", payload or {}, headers
        )

    def attest_quality_period(self, period_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/quality-periods/{period_id}/attest", payload, headers
        )


api_client = ApiClient()
