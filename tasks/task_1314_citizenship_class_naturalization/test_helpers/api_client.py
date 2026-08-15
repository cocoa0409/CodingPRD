"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/naturalization"


class ApiClient(GenericApiClient):
    # --- Program / clock ---
    def create_program(self, payload, headers):
        return self._request("POST", f"{BASE}/programs", payload, headers)

    def get_current_program(self, headers):
        return self._request("GET", f"{BASE}/programs/current", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # --- Applicants / screenings / readiness ---
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{BASE}/applicants", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", f"{BASE}/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{BASE}/applicants/{applicant_id}", headers=headers)

    def create_screening(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/applicants/{applicant_id}/screenings", payload, headers
        )

    def list_screenings(self, applicant_id, headers):
        return self._request(
            "GET", f"{BASE}/applicants/{applicant_id}/screenings", headers=headers
        )

    def get_readiness(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/applicants/{applicant_id}/readiness",
            headers=headers, params=params,
        )

    # --- Class sections / enrollments / attendance ---
    def create_class_section(self, payload, headers):
        return self._request("POST", f"{BASE}/class-sections", payload, headers)

    def list_class_sections(self, headers, params=None):
        return self._request("GET", f"{BASE}/class-sections", headers=headers, params=params)

    def get_class_section(self, section_id, headers):
        return self._request("GET", f"{BASE}/class-sections/{section_id}", headers=headers)

    def list_section_enrollments(self, section_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/class-sections/{section_id}/enrollments",
            headers=headers, params=params,
        )

    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{BASE}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{BASE}/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{BASE}/enrollments/{enrollment_id}", headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/withdraw", {}, headers
        )

    def confirm_promotion(self, enrollment_id, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/confirm-promotion", {}, headers
        )

    def complete_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/complete", {}, headers
        )

    def create_attendance_record(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/attendance-records",
            payload, headers,
        )

    def list_attendance_records(self, enrollment_id, headers):
        return self._request(
            "GET", f"{BASE}/enrollments/{enrollment_id}/attendance-records",
            headers=headers,
        )

    # --- Volunteers / training / accreditation ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{BASE}/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"{BASE}/volunteers/{volunteer_id}", headers=headers)

    def create_training_credit(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/volunteers/{volunteer_id}/training-credits", payload, headers
        )

    def list_training_credits(self, volunteer_id, headers):
        return self._request(
            "GET", f"{BASE}/volunteers/{volunteer_id}/training-credits", headers=headers
        )

    def accredit_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/volunteers/{volunteer_id}/accredit", payload, headers
        )

    def renew_volunteer(self, volunteer_id, headers):
        return self._request(
            "POST", f"{BASE}/volunteers/{volunteer_id}/renew", {}, headers
        )

    # --- Workshops / seats ---
    def create_workshop(self, payload, headers):
        return self._request("POST", f"{BASE}/workshops", payload, headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", f"{BASE}/workshops", headers=headers, params=params)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"{BASE}/workshops/{workshop_id}", headers=headers)

    def reserve_workshop_seat(self, workshop_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/workshops/{workshop_id}/seats", payload, headers
        )

    def list_workshop_seats(self, workshop_id, headers):
        return self._request(
            "GET", f"{BASE}/workshops/{workshop_id}/seats", headers=headers
        )

    def list_all_workshop_seats(self, headers, params=None):
        return self._request("GET", f"{BASE}/workshop-seats", headers=headers, params=params)

    def get_workshop_seat(self, seat_id, headers):
        return self._request("GET", f"{BASE}/workshop-seats/{seat_id}", headers=headers)

    def cancel_workshop_seat(self, seat_id, headers):
        return self._request("POST", f"{BASE}/workshop-seats/{seat_id}/cancel", {}, headers)

    def complete_workshop(self, workshop_id, headers):
        return self._request(
            "POST", f"{BASE}/workshops/{workshop_id}/complete", {}, headers
        )

    def reverse_workshop_completion(self, workshop_id, headers):
        return self._request(
            "POST", f"{BASE}/workshops/{workshop_id}/reverse-completion", {}, headers
        )

    def cancel_workshop(self, workshop_id, headers):
        return self._request("POST", f"{BASE}/workshops/{workshop_id}/cancel", {}, headers)

    # --- Application packets ---
    def create_packet(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/applicants/{applicant_id}/packets", payload, headers
        )

    def list_packets(self, headers, params=None):
        return self._request("GET", f"{BASE}/packets", headers=headers, params=params)

    def get_packet(self, packet_id, headers):
        return self._request("GET", f"{BASE}/packets/{packet_id}", headers=headers)

    def submit_packet_review(self, packet_id, headers):
        return self._request(
            "POST", f"{BASE}/packets/{packet_id}/submit-review", {}, headers
        )

    def request_packet_revision(self, packet_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/packets/{packet_id}/request-revision", payload, headers
        )

    def revise_packet(self, packet_id, headers):
        return self._request("POST", f"{BASE}/packets/{packet_id}/revise", {}, headers)

    def certify_packet(self, packet_id, headers):
        return self._request("POST", f"{BASE}/packets/{packet_id}/certify", {}, headers)

    def file_packet(self, packet_id, headers):
        return self._request("POST", f"{BASE}/packets/{packet_id}/file", {}, headers)

    # --- Fee waiver requests ---
    def create_fee_waiver_request(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/applicants/{applicant_id}/fee-waiver-requests",
            payload, headers,
        )

    def list_fee_waiver_requests(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/fee-waiver-requests", headers=headers, params=params
        )

    def get_fee_waiver_request(self, request_id, headers):
        return self._request(
            "GET", f"{BASE}/fee-waiver-requests/{request_id}", headers=headers
        )

    def submit_fee_waiver_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/fee-waiver-requests/{request_id}/submit", payload, headers
        )

    def decide_fee_waiver_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/fee-waiver-requests/{request_id}/decide", payload, headers
        )

    def resubmit_fee_waiver_request(self, request_id, headers):
        return self._request(
            "POST", f"{BASE}/fee-waiver-requests/{request_id}/resubmit", {}, headers
        )

    # --- Cases / RFE ---
    def list_cases(self, headers, params=None):
        return self._request("GET", f"{BASE}/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{BASE}/cases/{case_id}", headers=headers)

    def advance_case(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/advance", payload, headers)

    def issue_rfe(self, case_id, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/issue-rfe", {}, headers)

    def respond_rfe(self, case_id, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/respond-rfe", {}, headers)

    def clear_rfe(self, case_id, headers):
        return self._request("POST", f"{BASE}/cases/{case_id}/clear-rfe", {}, headers)

    # --- Oath ceremonies ---
    def create_oath_ceremony(self, payload, headers):
        return self._request("POST", f"{BASE}/oath-ceremonies", payload, headers)

    def get_oath_ceremony(self, ceremony_id, headers):
        return self._request("GET", f"{BASE}/oath-ceremonies/{ceremony_id}", headers=headers)

    def assign_oath_ceremony(self, ceremony_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/oath-ceremonies/{ceremony_id}/assign", payload, headers
        )

    def conclude_oath_ceremony(self, ceremony_id, headers):
        return self._request(
            "POST", f"{BASE}/oath-ceremonies/{ceremony_id}/conclude", {}, headers
        )

    def cancel_oath_ceremony(self, ceremony_id, headers):
        return self._request(
            "POST", f"{BASE}/oath-ceremonies/{ceremony_id}/cancel", {}, headers
        )

    # --- Mock interviews ---
    def create_mock_interview(self, payload, headers):
        return self._request("POST", f"{BASE}/mock-interviews", payload, headers)

    def list_mock_interviews(self, headers, params=None):
        return self._request("GET", f"{BASE}/mock-interviews", headers=headers, params=params)

    def get_mock_interview(self, interview_id, headers):
        return self._request("GET", f"{BASE}/mock-interviews/{interview_id}", headers=headers)

    def score_mock_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/mock-interviews/{interview_id}/score", payload, headers
        )

    def no_show_mock_interview(self, interview_id, headers):
        return self._request(
            "POST", f"{BASE}/mock-interviews/{interview_id}/no-show", {}, headers
        )

    def cancel_mock_interview(self, interview_id, headers):
        return self._request(
            "POST", f"{BASE}/mock-interviews/{interview_id}/cancel", {}, headers
        )


api_client = ApiClient()
