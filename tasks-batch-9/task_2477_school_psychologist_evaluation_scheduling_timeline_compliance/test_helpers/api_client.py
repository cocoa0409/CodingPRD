"""API client: one method per endpoint defined in the requirements."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/psych-services"


class ApiClient(GenericApiClient):
    # ---------------- the logical district clock ----------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---------------- buildings ----------------
    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    # ---------------- psychologists ----------------
    def create_psychologist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/psychologists", payload, headers)

    def get_psychologist(self, psychologist_id, headers):
        return self._request(
            "GET", f"{PREFIX}/psychologists/{psychologist_id}", headers=headers
        )

    def place_psychologist_on_leave(self, psychologist_id, headers):
        return self._request(
            "POST", f"{PREFIX}/psychologists/{psychologist_id}/leave", {}, headers
        )

    def list_psychologist_license_seats(self, psychologist_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/psychologists/{psychologist_id}/license-seats",
            headers=headers,
            params=params,
        )

    # ---------------- assessment instruments ----------------
    def create_assessment_instrument(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assessment-instruments", payload, headers
        )

    def get_assessment_instrument(self, instrument_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assessment-instruments/{instrument_id}", headers=headers
        )

    def assign_license_seat(self, instrument_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/assessment-instruments/{instrument_id}/license-seats",
            payload,
            headers,
        )

    def release_license_seat(self, instrument_id, seat_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/assessment-instruments/{instrument_id}"
            f"/license-seats/{seat_id}/release",
            {},
            headers,
        )

    def list_instrument_license_seats(self, instrument_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/assessment-instruments/{instrument_id}/license-seats",
            headers=headers,
            params=params,
        )

    def list_instrument_protocol_orders(self, instrument_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/assessment-instruments/{instrument_id}/protocol-orders",
            headers=headers,
            params=params,
        )

    # ---------------- protocol orders ----------------
    def create_protocol_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/protocol-orders", payload, headers)

    def decide_protocol_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protocol-orders/{order_id}/decision", payload, headers
        )

    def receive_protocol_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protocol-orders/{order_id}/receive", payload, headers
        )

    # ---------------- referrals ----------------
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def create_consent_event(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/consent-events", payload, headers
        )

    # ---------------- evaluations ----------------
    def get_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/evaluations/{evaluation_id}", headers=headers
        )

    def list_evaluations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/evaluations", headers=headers, params=params
        )

    def assign_evaluator(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/evaluations/{evaluation_id}/assign", payload, headers
        )

    def start_testing(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/evaluations/{evaluation_id}/testing-start",
            payload,
            headers,
        )

    def record_scores(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/evaluations/{evaluation_id}/scores", payload, headers
        )

    def submit_report_draft(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/evaluations/{evaluation_id}/report-draft",
            payload,
            headers,
        )

    def review_report(self, evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/evaluations/{evaluation_id}/report-review",
            payload,
            headers,
        )

    def list_evaluation_timeline_exclusions(self, evaluation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/evaluations/{evaluation_id}/timeline-exclusions",
            headers=headers,
            params=params,
        )

    def list_evaluation_interpreter_sessions(self, evaluation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/evaluations/{evaluation_id}/interpreter-sessions",
            headers=headers,
            params=params,
        )

    def list_evaluation_timeline_breaches(self, evaluation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/evaluations/{evaluation_id}/timeline-breaches",
            headers=headers,
            params=params,
        )

    # ---------------- timeline exclusions ----------------
    def claim_timeline_exclusion(self, payload, headers):
        return self._request("POST", f"{PREFIX}/timeline-exclusions", payload, headers)

    def decide_timeline_exclusion(self, exclusion_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/timeline-exclusions/{exclusion_id}/decision",
            payload,
            headers,
        )

    # ---------------- interpreter sessions ----------------
    def book_interpreter_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interpreter-sessions", payload, headers)

    # ---------------- eligibility meetings ----------------
    def create_eligibility_meeting(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-meetings", payload, headers)

    def get_eligibility_meeting(self, meeting_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-meetings/{meeting_id}", headers=headers
        )

    def list_eligibility_meetings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/eligibility-meetings", headers=headers, params=params
        )

    def send_meeting_notice(self, meeting_id, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-meetings/{meeting_id}/notice", {}, headers
        )

    def request_meeting_reschedule(self, meeting_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/eligibility-meetings/{meeting_id}/reschedule-request",
            payload,
            headers,
        )

    def hold_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"{PREFIX}/eligibility-meetings/{meeting_id}/hold", {}, headers
        )

    # ---------------- timeline breaches and remedies ----------------
    def propose_remedy(self, breach_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/timeline-breaches/{breach_id}/propose-remedy",
            payload,
            headers,
        )

    def approve_remedy(self, breach_id, headers):
        return self._request(
            "POST", f"{PREFIX}/timeline-breaches/{breach_id}/approve-remedy", {}, headers
        )

    # ---------------- compliance sweeps ----------------
    def run_compliance_sweep(self, headers):
        return self._request("POST", f"{PREFIX}/compliance-runs", {}, headers)


api_client = ApiClient()
