"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def activate_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/activate", {}, headers)

    def close_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/close", {}, headers)

    def run_monthly_close(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/run-monthly-close", payload, headers)

    # --- TankSystem ---
    def create_tank_system(self, payload, headers):
        return self._request("POST", "/tank-systems", payload, headers)

    def list_tank_systems(self, headers, params=None):
        return self._request("GET", "/tank-systems", headers=headers, params=params)

    def get_tank_system(self, tank_id, headers):
        return self._request("GET", f"/tank-systems/{tank_id}", headers=headers)

    def get_test_schedule(self, tank_id, headers):
        return self._request("GET", f"/tank-systems/{tank_id}/test-schedule", headers=headers)

    def place_in_service(self, tank_id, headers):
        return self._request("POST", f"/tank-systems/{tank_id}/place-in-service", {}, headers)

    def close_tank(self, tank_id, payload, headers):
        return self._request("POST", f"/tank-systems/{tank_id}/close", payload, headers)

    def return_to_service(self, tank_id, headers):
        return self._request("POST", f"/tank-systems/{tank_id}/return-to-service", {}, headers)

    # --- Component ---
    def create_component(self, payload, headers):
        return self._request("POST", "/components", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/components", headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/components/{component_id}", headers=headers)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # --- ServiceOrder ---
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def schedule_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/schedule", payload, headers)

    def update_service_order(self, order_id, payload, headers):
        return self._request("PUT", f"/service-orders/{order_id}", payload, headers)

    def start_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/start", {}, headers)

    def record_results(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/results", payload, headers)

    def certify_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/certify", {}, headers)

    def return_for_correction(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/return-for-correction", {}, headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", {}, headers)

    # --- ResultRecord ---
    def list_result_records(self, headers, params=None):
        return self._request("GET", "/result-records", headers=headers, params=params)

    def get_result_record(self, record_id, headers):
        return self._request("GET", f"/result-records/{record_id}", headers=headers)

    # --- Deficiency ---
    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    def order_correction(self, deficiency_id, headers):
        return self._request("POST", f"/deficiencies/{deficiency_id}/order-correction", {}, headers)

    def mark_corrected(self, deficiency_id, headers):
        return self._request("POST", f"/deficiencies/{deficiency_id}/mark-corrected", {}, headers)

    # --- RegulatorySubmission ---
    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def submit_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/submit", {}, headers)

    def accept_submission(self, submission_id, headers):
        return self._request("POST", f"/submissions/{submission_id}/accept", {}, headers)

    def reject_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/submissions/{submission_id}/reject", payload, headers)

    def amend_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/submissions/{submission_id}/amend", payload, headers)

    # --- ReleaseDetectionRecord ---
    def create_release_detection_record(self, payload, headers):
        return self._request("POST", "/release-detection-records", payload, headers)

    def list_release_detection_records(self, headers, params=None):
        return self._request("GET", "/release-detection-records", headers=headers, params=params)

    def get_release_detection_record(self, record_id, headers):
        return self._request("GET", f"/release-detection-records/{record_id}", headers=headers)

    # --- OperatorPerson ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    def activate_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/activate", {}, headers)

    def revoke_operator(self, operator_id, headers):
        return self._request("POST", f"/operators/{operator_id}/revoke", {}, headers)

    # --- TrainingRecord ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/training-records/{record_id}", headers=headers)

    # --- ReleaseEvent ---
    def create_release_event(self, payload, headers):
        return self._request("POST", "/release-events", payload, headers)

    def list_release_events(self, headers, params=None):
        return self._request("GET", "/release-events", headers=headers, params=params)

    def get_release_event(self, release_id, headers):
        return self._request("GET", f"/release-events/{release_id}", headers=headers)

    def confirm_release(self, release_id, headers):
        return self._request("POST", f"/release-events/{release_id}/confirm", {}, headers)

    def dismiss_release(self, release_id, headers):
        return self._request("POST", f"/release-events/{release_id}/dismiss", {}, headers)

    def begin_cleanup(self, release_id, headers):
        return self._request("POST", f"/release-events/{release_id}/begin-cleanup", {}, headers)

    def close_release(self, release_id, headers):
        return self._request("POST", f"/release-events/{release_id}/close", {}, headers)

    # --- StateFundClaim ---
    def create_fund_claim(self, payload, headers):
        return self._request("POST", "/fund-claims", payload, headers)

    def list_fund_claims(self, headers, params=None):
        return self._request("GET", "/fund-claims", headers=headers, params=params)

    def get_fund_claim(self, claim_id, headers):
        return self._request("GET", f"/fund-claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/fund-claims/{claim_id}/submit", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/fund-claims/{claim_id}/withdraw", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/fund-claims/{claim_id}/adjudicate", payload, headers)


api_client = ApiClient()
