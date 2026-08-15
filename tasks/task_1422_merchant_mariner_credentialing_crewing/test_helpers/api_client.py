"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Mariner ---
    def create_mariner(self, payload, headers):
        return self._request("POST", "/mariners", payload, headers)

    def list_mariners(self, headers, params=None):
        return self._request("GET", "/mariners", headers=headers, params=params)

    def get_mariner(self, mariner_id, headers):
        return self._request("GET", f"/mariners/{mariner_id}", headers=headers)

    def update_mariner(self, mariner_id, payload, headers):
        return self._request("PUT", f"/mariners/{mariner_id}", payload, headers)

    def activate_mariner(self, mariner_id, headers):
        return self._request("POST", f"/mariners/{mariner_id}/activate", {}, headers)

    def suspend_mariner(self, mariner_id, headers):
        return self._request("POST", f"/mariners/{mariner_id}/suspend", {}, headers)

    def reinstate_mariner(self, mariner_id, headers):
        return self._request("POST", f"/mariners/{mariner_id}/reinstate", {}, headers)

    def terminate_mariner(self, mariner_id, headers):
        return self._request("POST", f"/mariners/{mariner_id}/terminate", {}, headers)

    def get_upgrade_eligibility(self, mariner_id, target_endorsement_code, headers):
        return self._request(
            "GET", f"/mariners/{mariner_id}/upgrade-eligibility",
            headers=headers,
            params={"target_endorsement_code": target_endorsement_code},
        )

    def get_sea_service_summary(self, mariner_id, headers):
        return self._request(
            "GET", f"/mariners/{mariner_id}/sea-service-summary", headers=headers)

    # --- Credential ---
    def create_credential(self, mariner_id, payload, headers):
        return self._request(
            "POST", f"/mariners/{mariner_id}/credentials", payload, headers)

    def list_mariner_credentials(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/credentials", headers=headers, params=params)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/credentials", headers=headers, params=params)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def submit_credential_renewal(self, mariner_id, credential_id, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/credentials/{credential_id}/submit-renewal",
            {}, headers)

    def approve_credential_renewal(self, mariner_id, credential_id, payload, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/credentials/{credential_id}/approve-renewal",
            payload, headers)

    def deny_credential_renewal(self, mariner_id, credential_id, payload, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/credentials/{credential_id}/deny-renewal",
            payload, headers)

    def revoke_credential(self, mariner_id, credential_id, payload, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/credentials/{credential_id}/revoke",
            payload, headers)

    def reinstate_credential(self, mariner_id, credential_id, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/credentials/{credential_id}/reinstate",
            {}, headers)

    # --- SeaServiceRecord ---
    def create_sea_service_record(self, mariner_id, payload, headers):
        return self._request(
            "POST", f"/mariners/{mariner_id}/sea-service-records", payload, headers)

    def list_sea_service_records(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/sea-service-records",
            headers=headers, params=params)

    def get_sea_service_record(self, mariner_id, record_id, headers):
        return self._request(
            "GET", f"/mariners/{mariner_id}/sea-service-records/{record_id}",
            headers=headers)

    def list_vessel_sea_service_records(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/sea-service-records",
            headers=headers, params=params)

    def submit_sea_service_record(self, mariner_id, record_id, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/sea-service-records/{record_id}/submit",
            {}, headers)

    def verify_sea_service_record(self, mariner_id, record_id, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/sea-service-records/{record_id}/verify",
            {}, headers)

    def dispute_sea_service_record(self, mariner_id, record_id, payload, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/sea-service-records/{record_id}/dispute",
            payload, headers)

    def reject_sea_service_record(self, mariner_id, record_id, payload, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/sea-service-records/{record_id}/reject",
            payload, headers)

    # --- MedicalCertificate ---
    def create_medical_certificate(self, mariner_id, payload, headers):
        return self._request(
            "POST", f"/mariners/{mariner_id}/medical-certificates", payload, headers)

    def list_medical_certificates(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/medical-certificates",
            headers=headers, params=params)

    def suspend_medical_certificate(self, mariner_id, cert_id, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/medical-certificates/{cert_id}/suspend",
            {}, headers)

    def reinstate_medical_certificate(self, mariner_id, cert_id, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/medical-certificates/{cert_id}/reinstate",
            {}, headers)

    # --- DrugTestRecord ---
    def create_drug_test(self, mariner_id, payload, headers):
        return self._request(
            "POST", f"/mariners/{mariner_id}/drug-tests", payload, headers)

    def list_drug_tests(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/drug-tests", headers=headers, params=params)

    def record_drug_test_result(self, mariner_id, test_id, payload, headers):
        return self._request(
            "POST",
            f"/mariners/{mariner_id}/drug-tests/{test_id}/record-result",
            payload, headers)

    # --- Vessel ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def activate_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/activate", {}, headers)

    def mark_vessel_underway(self, vessel_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/mark-underway", payload, headers)

    def return_vessel_to_port(self, vessel_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/return-to-port", {}, headers)

    def lay_up_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/lay-up", {}, headers)

    def decommission_vessel(self, vessel_id, headers):
        return self._request("POST", f"/vessels/{vessel_id}/decommission", {}, headers)

    def get_manning_compliance(self, vessel_id, headers):
        return self._request(
            "GET", f"/vessels/{vessel_id}/manning-compliance", headers=headers)

    # --- ManningSlot ---
    def create_manning_slot(self, vessel_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/manning-slots", payload, headers)

    def list_manning_slots(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/manning-slots", headers=headers, params=params)

    def get_manning_slot(self, vessel_id, slot_id, headers):
        return self._request(
            "GET", f"/vessels/{vessel_id}/manning-slots/{slot_id}", headers=headers)

    def update_manning_slot(self, vessel_id, slot_id, payload, headers):
        return self._request(
            "PUT", f"/vessels/{vessel_id}/manning-slots/{slot_id}", payload, headers)

    def retire_manning_slot(self, vessel_id, slot_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/manning-slots/{slot_id}/retire",
            {}, headers)

    # --- CrewRotationPlan ---
    def create_rotation_plan(self, vessel_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/rotation-plans", payload, headers)

    def list_rotation_plans(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/rotation-plans", headers=headers, params=params)

    def archive_rotation_plan(self, vessel_id, plan_id, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/rotation-plans/{plan_id}/archive",
            {}, headers)

    # --- Assignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/confirm", {}, headers)

    def sign_on_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/sign-on", {}, headers)

    def relieve_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/relieve", {}, headers)

    def close_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/close", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/cancel", {}, headers)

    def resume_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/resume", {}, headers)

    # --- TravelBooking ---
    def create_travel_booking(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/travel-bookings", payload, headers)

    def list_travel_bookings(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/assignments/{assignment_id}/travel-bookings",
            headers=headers, params=params)

    def update_travel_booking_legs(self, assignment_id, booking_id, payload, headers):
        return self._request(
            "PUT", f"/assignments/{assignment_id}/travel-bookings/{booking_id}",
            payload, headers)

    def book_travel_booking(self, assignment_id, booking_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/travel-bookings/{booking_id}/book",
            {}, headers)

    def ticket_travel_booking(self, assignment_id, booking_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/travel-bookings/{booking_id}/ticket",
            {}, headers)

    def complete_travel_booking(self, assignment_id, booking_id, headers):
        return self._request(
            "POST",
            f"/assignments/{assignment_id}/travel-bookings/{booking_id}/complete",
            {}, headers)

    def cancel_travel_booking(self, assignment_id, booking_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/travel-bookings/{booking_id}/cancel",
            {}, headers)

    # --- TrainingCourse ---
    def create_course(self, payload, headers):
        return self._request("POST", "/training-courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/training-courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/training-courses/{course_id}", headers=headers)

    def cancel_course(self, course_id, headers):
        return self._request(
            "POST", f"/training-courses/{course_id}/cancel", {}, headers)

    # --- TrainingEnrollment ---
    def request_enrollment(self, course_id, headers):
        return self._request(
            "POST", f"/training-courses/{course_id}/enrollments", {}, headers)

    def list_course_enrollments(self, course_id, headers, params=None):
        return self._request(
            "GET", f"/training-courses/{course_id}/enrollments",
            headers=headers, params=params)

    def list_mariner_enrollments(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/training-enrollments/{enrollment_id}", headers=headers)

    def approve_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/approve", {}, headers)

    def reject_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/reject", payload, headers)

    def enroll_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/enroll", {}, headers)

    def record_enrollment_completion(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/record-completion",
            payload, headers)

    def reimburse_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/reimburse",
            payload, headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/cancel", {}, headers)

    # --- TrainingBudget ---
    def list_training_budgets(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/training-budgets",
            headers=headers, params=params)

    # --- UnionHall / UnionRegistration ---
    def create_union_hall(self, payload, headers):
        return self._request("POST", "/union-halls", payload, headers)

    def list_union_halls(self, headers, params=None):
        return self._request("GET", "/union-halls", headers=headers, params=params)

    def get_union_hall(self, hall_id, headers):
        return self._request("GET", f"/union-halls/{hall_id}", headers=headers)

    def create_union_registration(self, hall_id, payload, headers):
        return self._request(
            "POST", f"/union-halls/{hall_id}/registrations", payload, headers)

    def list_hall_registrations(self, hall_id, headers, params=None):
        return self._request(
            "GET", f"/union-halls/{hall_id}/registrations",
            headers=headers, params=params)

    def list_mariner_union_registrations(self, mariner_id, headers, params=None):
        return self._request(
            "GET", f"/mariners/{mariner_id}/union-registrations",
            headers=headers, params=params)

    def extend_registration_dues(self, hall_id, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/union-halls/{hall_id}/registrations/{registration_id}/extend-dues",
            payload, headers)

    def suspend_registration(self, hall_id, registration_id, headers):
        return self._request(
            "POST",
            f"/union-halls/{hall_id}/registrations/{registration_id}/suspend",
            {}, headers)

    def reinstate_registration(self, hall_id, registration_id, headers):
        return self._request(
            "POST",
            f"/union-halls/{hall_id}/registrations/{registration_id}/reinstate",
            {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock/current", headers=headers)


api_client = ApiClient()
