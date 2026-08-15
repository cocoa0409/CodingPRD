"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under the /ih prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ih"


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- ClientSite ---
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/employees", headers=headers, params=params
        )

    def get_employee(self, employee_id, headers):
        return self._request(
            "GET", f"{PREFIX}/employees/{employee_id}", headers=headers
        )

    # --- ExposureLimit ---
    def create_exposure_limit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exposure-limits", payload, headers)

    def list_exposure_limits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/exposure-limits", headers=headers, params=params
        )

    def get_exposure_limit(self, limit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/exposure-limits/{limit_id}", headers=headers
        )

    # --- Pump ---
    def create_pump(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pumps", payload, headers)

    def list_pumps(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pumps", headers=headers, params=params)

    def get_pump(self, pump_id, headers):
        return self._request("GET", f"{PREFIX}/pumps/{pump_id}", headers=headers)

    # --- SimilarExposureGroup ---
    def create_seg(self, payload, headers):
        return self._request("POST", f"{PREFIX}/segs", payload, headers)

    def list_segs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/segs", headers=headers, params=params)

    def get_seg(self, seg_id, headers):
        return self._request("GET", f"{PREFIX}/segs/{seg_id}", headers=headers)

    # --- SEGMembership ---
    def create_membership(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seg-memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/seg-memberships", headers=headers, params=params
        )

    def get_membership(self, membership_id, headers):
        return self._request(
            "GET", f"{PREFIX}/seg-memberships/{membership_id}", headers=headers
        )

    def transfer_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/seg-memberships/{membership_id}/transfer",
            payload, headers,
        )

    # --- SamplingPlan ---
    def create_sampling_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sampling-plans", payload, headers)

    def list_sampling_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sampling-plans", headers=headers, params=params
        )

    def get_sampling_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sampling-plans/{plan_id}", headers=headers
        )

    def revise_sampling_plan(self, plan_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/sampling-plans/{plan_id}", payload, headers
        )

    def submit_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/sampling-plans/{plan_id}/submit", headers=headers
        )

    def approve_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/sampling-plans/{plan_id}/approve", headers=headers
        )

    def reject_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/sampling-plans/{plan_id}/reject", headers=headers
        )

    def complete_field(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/sampling-plans/{plan_id}/complete-field",
            headers=headers,
        )

    # --- PumpCalibration ---
    def create_pump_calibration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pump-calibrations", payload, headers)

    def list_pump_calibrations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pump-calibrations", headers=headers, params=params
        )

    def get_pump_calibration(self, calibration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pump-calibrations/{calibration_id}", headers=headers
        )

    def record_post_flow(self, calibration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pump-calibrations/{calibration_id}/record-post",
            payload, headers,
        )

    # --- FieldSample ---
    def create_field_sample(self, payload, headers):
        return self._request("POST", f"{PREFIX}/field-samples", payload, headers)

    def list_field_samples(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/field-samples", headers=headers, params=params
        )

    def get_field_sample(self, sample_id, headers):
        return self._request(
            "GET", f"{PREFIX}/field-samples/{sample_id}", headers=headers
        )

    def seal_sample(self, sample_id, headers):
        return self._request(
            "POST", f"{PREFIX}/field-samples/{sample_id}/seal", headers=headers
        )

    def invalidate_sample(self, sample_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/field-samples/{sample_id}/invalidate",
            payload, headers,
        )

    # --- LabBatch / LabResult ---
    def create_lab_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lab-batches", payload, headers)

    def list_lab_batches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lab-batches", headers=headers, params=params
        )

    def get_lab_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lab-batches/{batch_id}", headers=headers
        )

    def create_lab_result(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lab-results", payload, headers)

    def list_lab_results(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lab-results", headers=headers, params=params
        )

    def get_lab_result(self, result_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lab-results/{result_id}", headers=headers
        )

    # --- ExposureAssessment ---
    def create_exposure_assessment(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-assessments", payload, headers
        )

    def list_exposure_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/exposure-assessments", headers=headers, params=params
        )

    def get_exposure_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/exposure-assessments/{assessment_id}", headers=headers
        )

    def submit_assessment_review(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-assessments/{assessment_id}/submit-review",
            headers=headers,
        )

    def sign_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-assessments/{assessment_id}/sign",
            headers=headers,
        )

    def reject_assessment_review(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-assessments/{assessment_id}/reject-review",
            headers=headers,
        )

    def update_assessment(self, assessment_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/exposure-assessments/{assessment_id}", payload, headers
        )

    def archive_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-assessments/{assessment_id}/archive",
            headers=headers,
        )

    # --- ControlRecommendation ---
    def create_control(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/control-recommendations", payload, headers
        )

    def list_controls(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/control-recommendations", headers=headers,
            params=params,
        )

    def get_control(self, control_id, headers):
        return self._request(
            "GET", f"{PREFIX}/control-recommendations/{control_id}", headers=headers
        )

    def accept_control(self, control_id, headers):
        return self._request(
            "POST", f"{PREFIX}/control-recommendations/{control_id}/accept",
            headers=headers,
        )

    def reject_control(self, control_id, headers):
        return self._request(
            "POST", f"{PREFIX}/control-recommendations/{control_id}/reject",
            headers=headers,
        )

    def implement_control(self, control_id, headers):
        return self._request(
            "POST", f"{PREFIX}/control-recommendations/{control_id}/implement",
            headers=headers,
        )

    def verify_control(self, control_id, headers):
        return self._request(
            "POST", f"{PREFIX}/control-recommendations/{control_id}/verify",
            headers=headers,
        )

    # --- MedicalClearance ---
    def create_medical_clearance(self, payload, headers):
        return self._request("POST", f"{PREFIX}/medical-clearances", payload, headers)

    def list_medical_clearances(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/medical-clearances", headers=headers, params=params
        )

    def get_medical_clearance(self, clearance_id, headers):
        return self._request(
            "GET", f"{PREFIX}/medical-clearances/{clearance_id}", headers=headers
        )

    def decide_clearance(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/medical-clearances/{clearance_id}/decide",
            payload, headers,
        )

    # --- RespiratorFitTest ---
    def create_fit_test(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fit-tests", payload, headers)

    def list_fit_tests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fit-tests", headers=headers, params=params
        )

    def get_fit_test(self, fit_test_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fit-tests/{fit_test_id}", headers=headers
        )

    def record_fit_test_result(self, fit_test_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fit-tests/{fit_test_id}/record-result",
            payload, headers,
        )

    # --- EmployeeNotification ---
    def list_notifications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/notifications", headers=headers, params=params
        )

    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/notifications/{notification_id}", headers=headers
        )

    def send_notification(self, notification_id, headers):
        return self._request(
            "POST", f"{PREFIX}/notifications/{notification_id}/send", headers=headers
        )

    def acknowledge_notification(self, notification_id, headers):
        return self._request(
            "POST", f"{PREFIX}/notifications/{notification_id}/acknowledge",
            headers=headers,
        )


api_client = ApiClient()
