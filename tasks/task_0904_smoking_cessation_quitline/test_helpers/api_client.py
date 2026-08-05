"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- EmployerProgram ----
    def create_employer_program(self, payload, headers):
        return self._request("POST", "/employer-programs", payload, headers)

    def get_employer_program(self, program_id, headers):
        return self._request("GET", f"/employer-programs/{program_id}", headers=headers)

    def close_employer_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/employer-programs/{program_id}/close", payload, headers
        )

    def list_program_participants(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/employer-programs/{program_id}/participants",
            headers=headers, params=params,
        )

    def get_outcome_report(self, program_id, headers):
        return self._request(
            "GET", f"/employer-programs/{program_id}/outcome-report", headers=headers
        )

    # ---- Coach ----
    def create_coach(self, payload, headers):
        return self._request("POST", "/coaches", payload, headers)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/coaches/{coach_id}", headers=headers)

    def list_coach_calls(self, coach_id, headers, params=None):
        return self._request(
            "GET", f"/coaches/{coach_id}/coaching-calls", headers=headers, params=params
        )

    # ---- Participant ----
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participant_enrollments(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/enrollments",
            headers=headers, params=params,
        )

    # ---- Enrollment ----
    def create_enrollment(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/enrollments", payload, headers
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/activate", {}, headers
        )

    def disenroll_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/disenroll", {}, headers
        )

    # ---- ReadinessAssessment ----
    def create_readiness_assessment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/readiness-assessments", payload, headers
        )

    def list_readiness_assessments(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/readiness-assessments",
            headers=headers, params=params,
        )

    # ---- QuitAttempt ----
    def create_quit_attempt(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/quit-attempts", payload, headers
        )

    def list_quit_attempts(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/quit-attempts",
            headers=headers, params=params,
        )

    def transition_quit_attempt(self, quit_attempt_id, payload, headers):
        return self._request(
            "POST", f"/quit-attempts/{quit_attempt_id}/transition", payload, headers
        )

    # ---- CoachingCall ----
    def create_coaching_call(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/coaching-calls", payload, headers
        )

    def list_coaching_calls(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/coaching-calls",
            headers=headers, params=params,
        )

    def transition_coaching_call(self, coaching_call_id, payload, headers):
        return self._request(
            "POST", f"/coaching-calls/{coaching_call_id}/transition", payload, headers
        )

    # ---- NRTShipment ----
    def create_nrt_shipment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/nrt-shipments", payload, headers
        )

    def list_nrt_shipments(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/nrt-shipments",
            headers=headers, params=params,
        )

    def transition_nrt_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/nrt-shipments/{shipment_id}/transition", payload, headers
        )

    # ---- IncentiveAward ----
    def create_incentive_award(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/incentive-awards", payload, headers
        )

    def list_incentive_awards(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/incentive-awards",
            headers=headers, params=params,
        )

    def get_incentive_summary(self, enrollment_id, headers):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/incentive-summary", headers=headers
        )

    # ---- Referral ----
    def create_referral(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/referrals", payload, headers
        )

    def list_referrals(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/referrals",
            headers=headers, params=params,
        )

    # ---- FollowUpOutcome ----
    def create_follow_up_outcome(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/follow-up-outcomes", payload, headers
        )

    def list_follow_up_outcomes(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/follow-up-outcomes",
            headers=headers, params=params,
        )


api_client = ApiClient()
