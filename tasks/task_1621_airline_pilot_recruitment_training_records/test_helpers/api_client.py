"""API client: one method per endpoint defined in the PRD.

All paths are mounted under /pilot-training per the endpoint index.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and daily operations scan (test-driving endpoints)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/pilot-training/_clock/set-current-utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily_scan(self, headers):
        return self._request("POST", "/pilot-training/_ops/run-daily-scan",
                             {}, headers)

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", "/pilot-training/applicants", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/pilot-training/applicants",
                             headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/pilot-training/applicants/{applicant_id}",
                             headers=headers)

    def advance_screening(self, applicant_id, headers):
        return self._request(
            "POST", f"/pilot-training/applicants/{applicant_id}/advance-screening",
            {}, headers)

    def clear_applicant(self, applicant_id, headers):
        return self._request(
            "POST", f"/pilot-training/applicants/{applicant_id}/clear", {}, headers)

    def reject_applicant(self, applicant_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/pilot-training/applicants/{applicant_id}/reject",
            payload, headers)

    def appeal_applicant(self, applicant_id, headers):
        return self._request(
            "POST", f"/pilot-training/applicants/{applicant_id}/appeal", {}, headers)

    def withdraw_applicant(self, applicant_id, headers):
        return self._request(
            "POST", f"/pilot-training/applicants/{applicant_id}/withdraw", {}, headers)

    def get_training_footprint(self, applicant_id, headers, variant=None):
        params = {} if variant is None else {"variant": variant}
        return self._request(
            "GET", f"/pilot-training/applicants/{applicant_id}/training-footprint",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Records requests (PRIA pipeline)
    # ------------------------------------------------------------------
    def create_records_request(self, payload, headers):
        return self._request("POST", "/pilot-training/records-requests",
                             payload, headers)

    def list_records_requests(self, headers, params=None):
        return self._request("GET", "/pilot-training/records-requests",
                             headers=headers, params=params)

    def get_records_request(self, request_id, headers):
        return self._request(
            "GET", f"/pilot-training/records-requests/{request_id}", headers=headers)

    def send_records_request(self, request_id, headers):
        return self._request(
            "POST", f"/pilot-training/records-requests/{request_id}/send",
            {}, headers)

    def receive_records_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/pilot-training/records-requests/{request_id}/receive",
            payload, headers)

    def verify_records_request(self, request_id, headers):
        return self._request(
            "POST", f"/pilot-training/records-requests/{request_id}/verify",
            {}, headers)

    # ------------------------------------------------------------------
    # Equipment
    # ------------------------------------------------------------------
    def create_equipment(self, payload, headers):
        return self._request("POST", "/pilot-training/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/pilot-training/equipment",
                             headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/pilot-training/equipment/{equipment_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Training classes
    # ------------------------------------------------------------------
    def create_training_class(self, payload, headers):
        return self._request("POST", "/pilot-training/training-classes",
                             payload, headers)

    def list_training_classes(self, headers, params=None):
        return self._request("GET", "/pilot-training/training-classes",
                             headers=headers, params=params)

    def get_training_class(self, class_id, headers):
        return self._request("GET", f"/pilot-training/training-classes/{class_id}",
                             headers=headers)

    def open_training_class(self, class_id, headers):
        return self._request(
            "POST", f"/pilot-training/training-classes/{class_id}/open", {}, headers)

    def start_training_class(self, class_id, headers):
        return self._request(
            "POST", f"/pilot-training/training-classes/{class_id}/start", {}, headers)

    def complete_training_class(self, class_id, headers):
        return self._request(
            "POST", f"/pilot-training/training-classes/{class_id}/complete",
            {}, headers)

    def cancel_training_class(self, class_id, headers):
        return self._request(
            "POST", f"/pilot-training/training-classes/{class_id}/cancel",
            {}, headers)

    def patch_training_class(self, class_id, payload, headers):
        return self._request(
            "PATCH", f"/pilot-training/training-classes/{class_id}", payload, headers)

    # ------------------------------------------------------------------
    # Enrollments
    # ------------------------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/pilot-training/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/pilot-training/enrollments",
                             headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/pilot-training/enrollments/{enrollment_id}",
                             headers=headers)

    def confirm_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/confirm",
            {}, headers)

    def start_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/start", {}, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/withdraw",
            {}, headers)

    def disqualify_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/disqualify",
            {}, headers)

    def retrain_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/retrain",
            {}, headers)

    def resume_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/resume", {}, headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/pilot-training/enrollments/{enrollment_id}/complete",
            {}, headers)

    # ------------------------------------------------------------------
    # Training events
    # ------------------------------------------------------------------
    def create_training_event(self, payload, headers):
        return self._request("POST", "/pilot-training/training-events",
                             payload, headers)

    def list_training_events(self, headers, params=None):
        return self._request("GET", "/pilot-training/training-events",
                             headers=headers, params=params)

    def get_training_event(self, event_id, headers):
        return self._request("GET", f"/pilot-training/training-events/{event_id}",
                             headers=headers)

    def complete_training_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/pilot-training/training-events/{event_id}/complete",
            payload, headers)

    def fail_training_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/pilot-training/training-events/{event_id}/fail",
            payload, headers)

    def cancel_training_event(self, event_id, headers):
        return self._request(
            "POST", f"/pilot-training/training-events/{event_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Checkrides
    # ------------------------------------------------------------------
    def create_checkride(self, payload, headers):
        return self._request("POST", "/pilot-training/checkrides", payload, headers)

    def list_checkrides(self, headers, params=None):
        return self._request("GET", "/pilot-training/checkrides",
                             headers=headers, params=params)

    def get_checkride(self, checkride_id, headers):
        return self._request("GET", f"/pilot-training/checkrides/{checkride_id}",
                             headers=headers)

    def record_checkride_outcome(self, checkride_id, payload, headers):
        return self._request(
            "POST", f"/pilot-training/checkrides/{checkride_id}/record-outcome",
            payload, headers)

    def cancel_checkride(self, checkride_id, headers):
        return self._request(
            "POST", f"/pilot-training/checkrides/{checkride_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Qualifications and currency
    # ------------------------------------------------------------------
    def create_qualification(self, payload, headers):
        return self._request("POST", "/pilot-training/qualifications",
                             payload, headers)

    def list_qualifications(self, headers, params=None):
        return self._request("GET", "/pilot-training/qualifications",
                             headers=headers, params=params)

    def get_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"/pilot-training/qualifications/{qualification_id}",
            headers=headers)

    def refresh_currency(self, qualification_id, headers):
        return self._request(
            "POST", f"/pilot-training/qualifications/{qualification_id}/refresh-currency",
            {}, headers)

    def requalify(self, qualification_id, headers):
        return self._request(
            "POST", f"/pilot-training/qualifications/{qualification_id}/requalify",
            {}, headers)

    def certify_requalification(self, qualification_id, headers):
        return self._request(
            "POST",
            f"/pilot-training/qualifications/{qualification_id}/certify-requalification",
            {}, headers)

    # ------------------------------------------------------------------
    # Flight activities
    # ------------------------------------------------------------------
    def create_flight_activity(self, payload, headers):
        return self._request("POST", "/pilot-training/flight-activities",
                             payload, headers)

    def list_flight_activities(self, headers, params=None):
        return self._request("GET", "/pilot-training/flight-activities",
                             headers=headers, params=params)

    def get_flight_activity(self, activity_id, headers):
        return self._request(
            "GET", f"/pilot-training/flight-activities/{activity_id}", headers=headers)

    # ------------------------------------------------------------------
    # Medical certificates
    # ------------------------------------------------------------------
    def create_medical_certificate(self, payload, headers):
        return self._request("POST", "/pilot-training/medical-certificates",
                             payload, headers)

    def list_medical_certificates(self, headers, params=None):
        return self._request("GET", "/pilot-training/medical-certificates",
                             headers=headers, params=params)

    def get_medical_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/pilot-training/medical-certificates/{certificate_id}",
            headers=headers)

    def suspend_medical_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/pilot-training/medical-certificates/{certificate_id}/suspend",
            {}, headers)

    # ------------------------------------------------------------------
    # Bid periods and bids
    # ------------------------------------------------------------------
    def create_bid_period(self, payload, headers):
        return self._request("POST", "/pilot-training/bid-periods", payload, headers)

    def list_bid_periods(self, headers, params=None):
        return self._request("GET", "/pilot-training/bid-periods",
                             headers=headers, params=params)

    def get_bid_period(self, period_id, headers):
        return self._request("GET", f"/pilot-training/bid-periods/{period_id}",
                             headers=headers)

    def open_bid_period(self, period_id, headers):
        return self._request(
            "POST", f"/pilot-training/bid-periods/{period_id}/open", {}, headers)

    def close_bid_period(self, period_id, headers):
        return self._request(
            "POST", f"/pilot-training/bid-periods/{period_id}/close", {}, headers)

    def award_bid_period(self, period_id, headers):
        return self._request(
            "POST", f"/pilot-training/bid-periods/{period_id}/award", {}, headers)

    def finalize_bid_period(self, period_id, headers):
        return self._request(
            "POST", f"/pilot-training/bid-periods/{period_id}/finalize", {}, headers)

    def create_bid(self, payload, headers):
        return self._request("POST", "/pilot-training/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/pilot-training/bids",
                             headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/pilot-training/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request(
            "POST", f"/pilot-training/bids/{bid_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Instructors
    # ------------------------------------------------------------------
    def create_instructor(self, payload, headers):
        return self._request("POST", "/pilot-training/instructors", payload, headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/pilot-training/instructors",
                             headers=headers, params=params)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/pilot-training/instructors/{instructor_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Simulator slots
    # ------------------------------------------------------------------
    def create_simulator_slot(self, payload, headers):
        return self._request("POST", "/pilot-training/simulator-slots",
                             payload, headers)

    def list_simulator_slots(self, headers, params=None):
        return self._request("GET", "/pilot-training/simulator-slots",
                             headers=headers, params=params)

    def get_simulator_slot(self, slot_id, headers):
        return self._request("GET", f"/pilot-training/simulator-slots/{slot_id}",
                             headers=headers)

    def toggle_simulator_slot_maintenance(self, slot_id, headers):
        return self._request(
            "POST", f"/pilot-training/simulator-slots/{slot_id}/maintenance",
            {}, headers)

    # ------------------------------------------------------------------
    # Cost ledger (append-only; read-only surface)
    # ------------------------------------------------------------------
    def list_cost_ledger(self, headers, params=None):
        return self._request("GET", "/pilot-training/cost-ledger",
                             headers=headers, params=params)

    def get_cost_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/pilot-training/cost-ledger/{entry_id}",
                             headers=headers)


api_client = ApiClient()
