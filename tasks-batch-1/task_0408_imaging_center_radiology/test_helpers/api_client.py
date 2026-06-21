"""API client: one method per endpoint defined in the PRD (§4).

Paths are mounted at the API root (no version prefix). The base _request()
method is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ImagingCenter ----
    def create_center(self, payload, headers):
        return self._request("POST", "/imaging-centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/imaging-centers/{center_id}", headers=headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/imaging-centers", headers=headers, params=params)

    def lock_center(self, center_id, headers):
        return self._request("POST", f"/imaging-centers/{center_id}/lock", {}, headers)

    def unlock_center(self, center_id, headers):
        return self._request("POST", f"/imaging-centers/{center_id}/unlock", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Modality ----
    def create_modality(self, center_id, payload, headers):
        return self._request("POST", f"/imaging-centers/{center_id}/modalities", payload, headers)

    def get_modality(self, modality_id, headers):
        return self._request("GET", f"/modalities/{modality_id}", headers=headers)

    def list_center_modalities(self, center_id, headers, params=None):
        return self._request("GET", f"/imaging-centers/{center_id}/modalities", headers=headers, params=params)

    def list_modality_rooms(self, modality_id, headers, params=None):
        return self._request("GET", f"/modalities/{modality_id}/rooms", headers=headers, params=params)

    def list_modality_orders(self, modality_id, headers, params=None):
        return self._request("GET", f"/modalities/{modality_id}/imaging-orders", headers=headers, params=params)

    # ---- Room ----
    def create_room(self, center_id, payload, headers):
        return self._request("POST", f"/imaging-centers/{center_id}/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_center_rooms(self, center_id, headers, params=None):
        return self._request("GET", f"/imaging-centers/{center_id}/rooms", headers=headers, params=params)

    def room_out_of_service(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/out-of-service", {}, headers)

    def list_room_exams(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/exams", headers=headers, params=params)

    # ---- Staff ----
    def create_staff(self, center_id, payload, headers):
        return self._request("POST", f"/imaging-centers/{center_id}/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def list_center_staff(self, center_id, headers, params=None):
        return self._request("GET", f"/imaging-centers/{center_id}/staff", headers=headers, params=params)

    def list_staff_exams(self, staff_id, headers, params=None):
        return self._request("GET", f"/staff/{staff_id}/exams", headers=headers, params=params)

    def list_staff_reports(self, staff_id, headers, params=None):
        return self._request("GET", f"/staff/{staff_id}/reports", headers=headers, params=params)

    # ---- ImagingOrder ----
    def create_order(self, center_id, payload, headers):
        return self._request("POST", f"/imaging-centers/{center_id}/imaging-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/imaging-orders/{order_id}", headers=headers)

    def list_center_orders(self, center_id, headers, params=None):
        return self._request("GET", f"/imaging-centers/{center_id}/imaging-orders", headers=headers, params=params)

    def benefit_check(self, order_id, payload, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/benefit-check", payload, headers)

    def clear_screening(self, order_id, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/clear-screening", {}, headers)

    def create_exam(self, order_id, payload, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/exams", payload, headers)

    def list_order_exams(self, order_id, headers, params=None):
        return self._request("GET", f"/imaging-orders/{order_id}/exams", headers=headers, params=params)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/cancel", {}, headers)

    def request_addendum(self, order_id, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/request-addendum", {}, headers)

    # ---- PriorAuthorization ----
    def create_prior_auth(self, order_id, payload, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/prior-authorizations", payload, headers)

    def get_prior_auth(self, pa_id, headers):
        return self._request("GET", f"/prior-authorizations/{pa_id}", headers=headers)

    def list_order_prior_auths(self, order_id, headers, params=None):
        return self._request("GET", f"/imaging-orders/{order_id}/prior-authorizations", headers=headers, params=params)

    def prior_auth_decision(self, pa_id, payload, headers):
        return self._request("POST", f"/prior-authorizations/{pa_id}/decision", payload, headers)

    # ---- ContrastScreening ----
    def create_screening(self, order_id, payload, headers):
        return self._request("POST", f"/imaging-orders/{order_id}/contrast-screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/contrast-screenings/{screening_id}", headers=headers)

    def list_order_screenings(self, order_id, headers, params=None):
        return self._request("GET", f"/imaging-orders/{order_id}/contrast-screenings", headers=headers, params=params)

    def evaluate_screening(self, screening_id, headers):
        return self._request("POST", f"/contrast-screenings/{screening_id}/evaluate", {}, headers)

    # ---- ImagingExam ----
    def get_exam(self, exam_id, headers):
        return self._request("GET", f"/imaging-exams/{exam_id}", headers=headers)

    def check_in(self, exam_id, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/check-in", {}, headers)

    def start_acquisition(self, exam_id, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/start-acquisition", {}, headers)

    def finish_acquisition(self, exam_id, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/finish-acquisition", {}, headers)

    def claim_read(self, exam_id, payload, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/claim-read", payload, headers)

    def sign_off(self, exam_id, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/sign-off", {}, headers)

    def cancel_exam(self, exam_id, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/cancel", {}, headers)

    # ---- ImageSeries ----
    def create_series(self, exam_id, payload, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/image-series", payload, headers)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/image-series/{series_id}", headers=headers)

    def list_exam_series(self, exam_id, headers, params=None):
        return self._request("GET", f"/imaging-exams/{exam_id}/image-series", headers=headers, params=params)

    def list_center_series(self, center_id, headers, params=None):
        return self._request("GET", f"/imaging-centers/{center_id}/image-series", headers=headers, params=params)

    def finalize_series(self, series_id, payload, headers):
        return self._request("POST", f"/image-series/{series_id}/finalize", payload, headers)

    # ---- RadiologyReport ----
    def create_report(self, exam_id, payload, headers):
        return self._request("POST", f"/imaging-exams/{exam_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/radiology-reports/{report_id}", headers=headers)

    def list_exam_reports(self, exam_id, headers, params=None):
        return self._request("GET", f"/imaging-exams/{exam_id}/reports", headers=headers, params=params)

    def finalize_report(self, report_id, headers):
        return self._request("POST", f"/radiology-reports/{report_id}/finalize", {}, headers)

    # ---- CriticalResult ----
    def create_critical_result(self, report_id, payload, headers):
        return self._request("POST", f"/radiology-reports/{report_id}/critical-results", payload, headers)

    def get_critical_result(self, cr_id, headers):
        return self._request("GET", f"/critical-results/{cr_id}", headers=headers)

    def list_report_critical_results(self, report_id, headers, params=None):
        return self._request("GET", f"/radiology-reports/{report_id}/critical-results", headers=headers, params=params)

    def list_center_critical_results(self, center_id, headers, params=None):
        return self._request("GET", f"/imaging-centers/{center_id}/critical-results", headers=headers, params=params)

    def acknowledge_critical_result(self, cr_id, headers):
        return self._request("POST", f"/critical-results/{cr_id}/acknowledge", {}, headers)


api_client = ApiClient()
