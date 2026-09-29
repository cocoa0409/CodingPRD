"""One method per endpoint of the mammography accreditation service.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies.  Paths are absolute with no shared prefix, as
the PRD specifies.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Sixty-seven endpoint methods."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers: dict):
        return self._request("GET", "/_clock/current", headers=headers)

    # ------------------------------------------------------------------
    # State policies
    # ------------------------------------------------------------------

    def create_state_policy(self, payload: dict, headers: dict):
        return self._request("POST", "/state-policies", payload, headers)

    def get_state_policy(self, policy_id: str, headers: dict):
        return self._request("GET", f"/state-policies/{policy_id}", headers=headers)

    def list_policy_facilities(
        self, policy_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/state-policies/{policy_id}/facilities", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------

    def create_facility(self, payload: dict, headers: dict):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: dict):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def create_funding_deposit(self, facility_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/facilities/{facility_id}/funding-deposits", payload, headers
        )

    def create_unit(self, facility_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/facilities/{facility_id}/units", payload, headers)

    def list_facility_units(
        self, facility_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/facilities/{facility_id}/units", headers=headers, params=params
        )

    def create_personnel(self, facility_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/facilities/{facility_id}/personnel", payload, headers
        )

    def list_facility_personnel(
        self, facility_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/facilities/{facility_id}/personnel", headers=headers, params=params
        )

    def create_inspection(self, facility_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/facilities/{facility_id}/inspections", payload, headers
        )

    def list_facility_inspections(
        self, facility_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/facilities/{facility_id}/inspections", headers=headers, params=params
        )

    def run_compliance_run(self, facility_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/facilities/{facility_id}/compliance-runs", payload, headers
        )

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------

    def get_unit(self, unit_id: str, headers: dict):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def create_physicist_survey(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/units/{unit_id}/physicist-surveys", payload, headers
        )

    def list_unit_physicist_surveys(
        self, unit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/units/{unit_id}/physicist-surveys", headers=headers, params=params
        )

    def create_clinical_image_review(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/units/{unit_id}/clinical-image-reviews", payload, headers
        )

    def list_unit_clinical_image_reviews(
        self, unit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/units/{unit_id}/clinical-image-reviews", headers=headers, params=params
        )

    def create_equipment_failure(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/units/{unit_id}/equipment-failures", payload, headers
        )

    def list_unit_equipment_failures(
        self, unit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/units/{unit_id}/equipment-failures", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Personnel
    # ------------------------------------------------------------------

    def get_personnel(self, personnel_id: str, headers: dict):
        return self._request("GET", f"/personnel/{personnel_id}", headers=headers)

    def create_credit(self, personnel_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/personnel/{personnel_id}/credits", payload, headers)

    def list_personnel_credits(
        self, personnel_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/personnel/{personnel_id}/credits", headers=headers, params=params
        )

    def run_qualification_review(
        self, personnel_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/personnel/{personnel_id}/qualification-reviews", payload, headers
        )

    def create_audit_cycle(self, personnel_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/personnel/{personnel_id}/audit-cycles", payload, headers
        )

    def list_personnel_audit_cycles(
        self, personnel_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/personnel/{personnel_id}/audit-cycles", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Physicist surveys
    # ------------------------------------------------------------------

    def get_physicist_survey(self, survey_id: str, headers: dict):
        return self._request("GET", f"/physicist-surveys/{survey_id}", headers=headers)

    def list_physicist_surveys(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/physicist-surveys", headers=headers, params=params)

    def submit_physicist_survey(self, survey_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/physicist-surveys/{survey_id}/submit", payload, headers
        )

    def remediate_physicist_survey(self, survey_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/physicist-surveys/{survey_id}/remediate", payload, headers
        )

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------

    def get_inspection(self, inspection_id: str, headers: dict):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def close_inspection(
        self, inspection_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/inspections/{inspection_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Clinical image reviews
    # ------------------------------------------------------------------

    def get_clinical_image_review(self, submission_id: str, headers: dict):
        return self._request(
            "GET", f"/clinical-image-reviews/{submission_id}", headers=headers
        )

    def review_clinical_image_review(self, submission_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/clinical-image-reviews/{submission_id}/review", payload, headers
        )

    def resubmit_clinical_image_review(self, submission_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/clinical-image-reviews/{submission_id}/resubmit", payload, headers
        )

    def withdraw_clinical_image_review(self, submission_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/clinical-image-reviews/{submission_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Exams
    # ------------------------------------------------------------------

    def create_exam(self, payload: dict, headers: dict):
        return self._request("POST", "/exams", payload, headers)

    def get_exam(self, exam_id: str, headers: dict):
        return self._request("GET", f"/exams/{exam_id}", headers=headers)

    def list_exams(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/exams", headers=headers, params=params)

    def interpret_exam(self, exam_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/exams/{exam_id}/interpret", payload, headers)

    def amend_exam(self, exam_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/exams/{exam_id}/amend", payload, headers)

    def record_exam_outcome(self, exam_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/exams/{exam_id}/outcome", payload, headers)

    def create_repeat_record(self, exam_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/exams/{exam_id}/repeat-records", payload, headers)

    def list_exam_repeat_records(
        self, exam_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/exams/{exam_id}/repeat-records", headers=headers, params=params
        )

    def create_notification_letter(self, exam_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/exams/{exam_id}/notification-letters", payload, headers
        )

    def list_exam_notification_letters(
        self, exam_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/exams/{exam_id}/notification-letters", headers=headers, params=params
        )

    def create_supplemental_order(self, exam_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/exams/{exam_id}/supplemental-orders", payload, headers
        )

    def list_exam_supplemental_orders(
        self, exam_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/exams/{exam_id}/supplemental-orders", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Notification letters
    # ------------------------------------------------------------------

    def get_notification_letter(self, letter_id: str, headers: dict):
        return self._request("GET", f"/notification-letters/{letter_id}", headers=headers)

    def list_notification_letters(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/notification-letters", headers=headers, params=params)

    def send_notification_letter(
        self, letter_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/notification-letters/{letter_id}/send", payload, headers
        )

    def mark_letter_undeliverable(self, letter_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/notification-letters/{letter_id}/mark-undeliverable", payload, headers
        )

    # ------------------------------------------------------------------
    # Supplemental orders
    # ------------------------------------------------------------------

    def get_supplemental_order(self, order_id: str, headers: dict):
        return self._request("GET", f"/supplemental-orders/{order_id}", headers=headers)

    def list_supplemental_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/supplemental-orders", headers=headers, params=params)

    def determine_coverage(
        self, order_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/supplemental-orders/{order_id}/coverage-determination", payload, headers
        )

    def schedule_supplemental_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/supplemental-orders/{order_id}/schedule", payload, headers
        )

    def complete_supplemental_order(
        self, order_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/supplemental-orders/{order_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Equipment failures
    # ------------------------------------------------------------------

    def get_equipment_failure(self, failure_id: str, headers: dict):
        return self._request("GET", f"/equipment-failures/{failure_id}", headers=headers)

    def restore_equipment_failure(self, failure_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/equipment-failures/{failure_id}/restore", payload, headers
        )

    # ------------------------------------------------------------------
    # Repeat records
    # ------------------------------------------------------------------

    def get_repeat_record(self, record_id: str, headers: dict):
        return self._request("GET", f"/repeat-records/{record_id}", headers=headers)

    def list_repeat_records(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/repeat-records", headers=headers, params=params)

    def retract_repeat_record(self, record_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/repeat-records/{record_id}/retract", payload, headers
        )

    # ------------------------------------------------------------------
    # Audit cycles
    # ------------------------------------------------------------------

    def get_audit_cycle(self, cycle_id: str, headers: dict):
        return self._request("GET", f"/audit-cycles/{cycle_id}", headers=headers)

    def get_audit_cycle_metrics(
        self, cycle_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/audit-cycles/{cycle_id}/metrics", headers=headers, params=params
        )

    def close_audit_cycle(self, cycle_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/audit-cycles/{cycle_id}/close", payload, headers)


api_client = ApiClient()
