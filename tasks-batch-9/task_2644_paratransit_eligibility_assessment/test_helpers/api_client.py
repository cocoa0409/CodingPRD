"""API client: one method per endpoint defined in the PRD.

Every endpoint is mounted at the top level; there is no shared API prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Riders
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers=headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ------------------------------------------------------------------
    # Intake packets
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers=headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", payload, headers=headers
        )

    def return_application_incomplete(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/return-incomplete",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Professional verification
    # ------------------------------------------------------------------
    def request_verification(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/verifications",
            payload,
            headers=headers,
        )

    def receive_verification(self, application_id, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/verifications/{verification_id}/receive",
            payload,
            headers=headers,
        )

    def list_verifications(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/applications/{application_id}/verifications",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Assessment slots and functional assessments
    # ------------------------------------------------------------------
    def create_assessment_slot(self, payload, headers):
        return self._request("POST", "/assessment-slots", payload, headers=headers)

    def get_assessment_slot(self, slot_id, headers):
        return self._request("GET", f"/assessment-slots/{slot_id}", headers=headers)

    def book_assessment(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/assessments",
            payload,
            headers=headers,
        )

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def record_attendance(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/attendance", payload, headers=headers
        )

    def record_scores(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/scores", payload, headers=headers
        )

    def sign_off_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/sign-off", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Vehicles and provided rides
    # ------------------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers=headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def create_transportation_booking(self, payload, headers):
        return self._request(
            "POST", "/transportation-bookings", payload, headers=headers
        )

    def get_transportation_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/transportation-bookings/{booking_id}", headers=headers
        )

    def list_transportation_bookings(self, headers, params=None):
        return self._request(
            "GET", "/transportation-bookings", headers=headers, params=params
        )

    def cancel_transportation_booking(self, booking_id, payload, headers):
        return self._request(
            "POST",
            f"/transportation-bookings/{booking_id}/cancel",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Determinations and trip conditions
    # ------------------------------------------------------------------
    def draft_determination(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/determinations",
            payload,
            headers=headers,
        )

    def issue_determination(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/determinations/{determination_id}/issue", payload, headers=headers
        )

    def get_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/determinations/{determination_id}", headers=headers
        )

    def list_determinations(self, headers, params=None):
        return self._request("GET", "/determinations", headers=headers, params=params)

    def list_trip_conditions(self, determination_id, headers, params=None):
        return self._request(
            "GET",
            f"/determinations/{determination_id}/trip-conditions",
            headers=headers,
            params=params,
        )

    def trip_eligibility_check(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"/determinations/{determination_id}/trip-eligibility-check",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers=headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_determination_appeals(self, determination_id, headers, params=None):
        return self._request(
            "GET",
            f"/determinations/{determination_id}/appeals",
            headers=headers,
            params=params,
        )

    def assign_appeal_reviewer(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/assign-reviewer", payload, headers=headers
        )

    def open_appeal_hearing(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/hearing", payload, headers=headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/decision", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Trip conduct
    # ------------------------------------------------------------------
    def create_trip_event(self, payload, headers):
        return self._request("POST", "/trip-events", payload, headers=headers)

    def excuse_trip_event(self, trip_event_id, payload, headers):
        return self._request(
            "POST", f"/trip-events/{trip_event_id}/excuse", payload, headers=headers
        )

    def list_trip_events(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"/applicants/{applicant_id}/trip-events", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Suspension proceedings
    # ------------------------------------------------------------------
    def propose_suspension(self, applicant_id, payload, headers):
        return self._request(
            "POST",
            f"/applicants/{applicant_id}/suspension-proceedings",
            payload,
            headers=headers,
        )

    def list_suspension_proceedings(self, applicant_id, headers, params=None):
        return self._request(
            "GET",
            f"/applicants/{applicant_id}/suspension-proceedings",
            headers=headers,
            params=params,
        )

    def get_suspension_proceeding(self, proceeding_id, headers):
        return self._request(
            "GET", f"/suspension-proceedings/{proceeding_id}", headers=headers
        )

    def send_suspension_notice(self, proceeding_id, payload, headers):
        return self._request(
            "POST",
            f"/suspension-proceedings/{proceeding_id}/send-notice",
            payload,
            headers=headers,
        )

    def respond_to_suspension(self, proceeding_id, payload, headers):
        return self._request(
            "POST",
            f"/suspension-proceedings/{proceeding_id}/respond",
            payload,
            headers=headers,
        )

    def decide_suspension(self, proceeding_id, payload, headers):
        return self._request(
            "POST",
            f"/suspension-proceedings/{proceeding_id}/decide",
            payload,
            headers=headers,
        )

    def rescind_suspension(self, proceeding_id, payload, headers):
        return self._request(
            "POST",
            f"/suspension-proceedings/{proceeding_id}/rescind",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Travel-training referrals
    # ------------------------------------------------------------------
    def create_travel_training_referral(self, applicant_id, payload, headers):
        return self._request(
            "POST",
            f"/applicants/{applicant_id}/travel-training-referrals",
            payload,
            headers=headers,
        )

    def get_travel_training_referral(self, referral_id, headers):
        return self._request(
            "GET", f"/travel-training-referrals/{referral_id}", headers=headers
        )

    def list_travel_training_referrals(self, headers, params=None):
        return self._request(
            "GET", "/travel-training-referrals", headers=headers, params=params
        )

    def respond_to_referral(self, referral_id, payload, headers):
        return self._request(
            "POST",
            f"/travel-training-referrals/{referral_id}/response",
            payload,
            headers=headers,
        )

    def complete_referral(self, referral_id, payload, headers):
        return self._request(
            "POST",
            f"/travel-training-referrals/{referral_id}/complete",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Visitor eligibility
    # ------------------------------------------------------------------
    def create_visitor_eligibility(self, applicant_id, payload, headers):
        return self._request(
            "POST",
            f"/applicants/{applicant_id}/visitor-eligibilities",
            payload,
            headers=headers,
        )

    def list_visitor_eligibilities(self, applicant_id, headers, params=None):
        return self._request(
            "GET",
            f"/applicants/{applicant_id}/visitor-eligibilities",
            headers=headers,
            params=params,
        )

    def get_visitor_eligibility(self, record_id, headers):
        return self._request(
            "GET", f"/visitor-eligibilities/{record_id}", headers=headers
        )

    def record_visitor_service_day(self, record_id, payload, headers):
        return self._request(
            "POST",
            f"/visitor-eligibilities/{record_id}/service-days",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Logical clock and the day-close sweep
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", payload, headers=headers
        )

    def day_close(self, headers, payload=None):
        return self._request(
            "POST", "/_ops/day-close", payload if payload is not None else {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch — used only where a test must address a path or a
    # header set that no well-formed method can express.
    # ------------------------------------------------------------------
    def raw(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers=headers, params=params)


api_client = ApiClient()
