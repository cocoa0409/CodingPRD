"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ------------------------------------------------------------------
    # Referral orders / authorizations
    # ------------------------------------------------------------------
    def create_referral_order(self, payload, headers):
        return self._request("POST", "/referral-orders", payload, headers)

    def list_referral_orders(self, headers, params=None):
        return self._request("GET", "/referral-orders", headers=headers, params=params)

    def get_referral_order(self, order_id, headers):
        return self._request("GET", f"/referral-orders/{order_id}", headers=headers)

    def submit_authorization(self, order_id, payload, headers):
        return self._request("POST", f"/referral-orders/{order_id}/authorizations",
                             payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}",
                             headers=headers)

    def decide_authorization(self, authorization_id, outcome, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/decision",
                             {"outcome": outcome}, headers)

    def provider_review(self, order_id, action, headers):
        return self._request("POST", f"/referral-orders/{order_id}/provider-review",
                             {"action": action}, headers)

    def cancel_referral_order(self, order_id, headers):
        return self._request("POST", f"/referral-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Beds / staff registry / staffing
    # ------------------------------------------------------------------
    def create_bed(self, payload, headers):
        return self._request("POST", "/beds", payload, headers)

    def create_technologist(self, payload, headers):
        return self._request("POST", "/technologists", payload, headers)

    def create_scorer(self, payload, headers):
        return self._request("POST", "/scorers", payload, headers)

    def get_scorer(self, scorer_id, headers):
        return self._request("GET", f"/scorers/{scorer_id}", headers=headers)

    def reinstate_scorer(self, scorer_id, headers):
        return self._request("POST", f"/scorers/{scorer_id}/reinstate", {}, headers)

    def create_physician(self, payload, headers):
        return self._request("POST", "/physicians", payload, headers)

    def create_staffing_assignment(self, payload, headers):
        return self._request("POST", "/staffing-assignments", payload, headers)

    def list_staffing_assignments(self, headers, params=None):
        return self._request("GET", "/staffing-assignments", headers=headers,
                             params=params)

    def get_staffing_assignment(self, staffing_assignment_id, headers):
        return self._request("GET",
                             f"/staffing-assignments/{staffing_assignment_id}",
                             headers=headers)

    def confirm_staffing_assignment(self, staffing_assignment_id, headers):
        return self._request(
            "POST", f"/staffing-assignments/{staffing_assignment_id}/confirm",
            {}, headers)

    def cancel_staffing_assignment(self, staffing_assignment_id, headers):
        return self._request(
            "POST", f"/staffing-assignments/{staffing_assignment_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Sleep studies
    # ------------------------------------------------------------------
    def create_sleep_study(self, payload, headers):
        return self._request("POST", "/sleep-studies", payload, headers)

    def list_sleep_studies(self, headers, params=None):
        return self._request("GET", "/sleep-studies", headers=headers, params=params)

    def get_sleep_study(self, study_id, headers):
        return self._request("GET", f"/sleep-studies/{study_id}", headers=headers)

    def check_in_study(self, study_id, headers):
        return self._request("POST", f"/sleep-studies/{study_id}/check-in",
                             {}, headers)

    def split_decision(self, study_id, payload, headers):
        return self._request("POST", f"/sleep-studies/{study_id}/split-decision",
                             payload, headers)

    def complete_acquisition(self, study_id, payload, headers):
        return self._request("POST",
                             f"/sleep-studies/{study_id}/complete-acquisition",
                             payload, headers)

    def no_show_study(self, study_id, headers):
        return self._request("POST", f"/sleep-studies/{study_id}/no-show",
                             {}, headers)

    def cancel_sleep_study(self, study_id, headers):
        return self._request("POST", f"/sleep-studies/{study_id}/cancel",
                             {}, headers)

    def technical_failure_study(self, study_id, headers):
        return self._request("POST", f"/sleep-studies/{study_id}/technical-failure",
                             {}, headers)

    def titration_recommendation(self, study_id, headers):
        return self._request(
            "GET", f"/sleep-studies/{study_id}/titration-recommendation",
            headers=headers)

    # ------------------------------------------------------------------
    # Scoring tasks
    # ------------------------------------------------------------------
    def create_scoring_task(self, payload, headers):
        return self._request("POST", "/scoring-tasks", payload, headers)

    def list_scoring_tasks(self, headers, params=None):
        return self._request("GET", "/scoring-tasks", headers=headers, params=params)

    def get_scoring_task(self, scoring_task_id, headers):
        return self._request("GET", f"/scoring-tasks/{scoring_task_id}",
                             headers=headers)

    def start_scoring_task(self, scoring_task_id, headers):
        return self._request("POST", f"/scoring-tasks/{scoring_task_id}/start",
                             {}, headers)

    def submit_scoring_task(self, scoring_task_id, payload, headers):
        return self._request("POST", f"/scoring-tasks/{scoring_task_id}/submit",
                             payload, headers)

    def accept_scoring_task(self, scoring_task_id, headers):
        return self._request("POST", f"/scoring-tasks/{scoring_task_id}/accept",
                             {}, headers)

    def return_scoring_task(self, scoring_task_id, reason, headers):
        return self._request("POST", f"/scoring-tasks/{scoring_task_id}/return",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Interpretation reports
    # ------------------------------------------------------------------
    def create_interpretation_report(self, payload, headers):
        return self._request("POST", "/interpretation-reports", payload, headers)

    def list_interpretation_reports(self, headers, params=None):
        return self._request("GET", "/interpretation-reports", headers=headers,
                             params=params)

    def get_interpretation_report(self, report_id, headers):
        return self._request("GET", f"/interpretation-reports/{report_id}",
                             headers=headers)

    def sign_report(self, report_id, headers):
        return self._request("POST", f"/interpretation-reports/{report_id}/sign",
                             {}, headers)

    def finalize_report(self, report_id, headers):
        return self._request("POST",
                             f"/interpretation-reports/{report_id}/finalize",
                             {}, headers)

    def open_addendum(self, report_id, headers):
        return self._request("POST",
                             f"/interpretation-reports/{report_id}/open-addendum",
                             {}, headers)

    def close_addendum(self, report_id, headers):
        return self._request("POST",
                             f"/interpretation-reports/{report_id}/close-addendum",
                             {}, headers)

    # ------------------------------------------------------------------
    # Therapy prescriptions / DME orders
    # ------------------------------------------------------------------
    def create_therapy_prescription(self, payload, headers):
        return self._request("POST", "/therapy-prescriptions", payload, headers)

    def list_therapy_prescriptions(self, headers, params=None):
        return self._request("GET", "/therapy-prescriptions", headers=headers,
                             params=params)

    def get_therapy_prescription(self, prescription_id, headers):
        return self._request("GET", f"/therapy-prescriptions/{prescription_id}",
                             headers=headers)

    def order_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/therapy-prescriptions/{prescription_id}/order", {}, headers)

    def cancel_prescription(self, prescription_id, headers):
        return self._request(
            "POST", f"/therapy-prescriptions/{prescription_id}/cancel", {}, headers)

    def create_dme_order(self, payload, headers):
        return self._request("POST", "/dme-orders", payload, headers)

    def list_dme_orders(self, headers, params=None):
        return self._request("GET", "/dme-orders", headers=headers, params=params)

    def get_dme_order(self, dme_order_id, headers):
        return self._request("GET", f"/dme-orders/{dme_order_id}", headers=headers)

    def deliver_dme_order(self, dme_order_id, headers):
        return self._request("POST", f"/dme-orders/{dme_order_id}/deliver",
                             {}, headers)

    def decline_dme_order(self, dme_order_id, headers):
        return self._request("POST", f"/dme-orders/{dme_order_id}/decline",
                             {}, headers)

    def cancel_dme_order(self, dme_order_id, headers):
        return self._request("POST", f"/dme-orders/{dme_order_id}/cancel",
                             {}, headers)

    def record_dme_follow_up(self, dme_order_id, payload, headers):
        return self._request("POST",
                             f"/dme-orders/{dme_order_id}/record-follow-up",
                             payload, headers)

    def resolve_dme_adherence(self, dme_order_id, action, headers):
        return self._request("POST",
                             f"/dme-orders/{dme_order_id}/resolve-adherence",
                             {"action": action}, headers)

    # ------------------------------------------------------------------
    # Inter-rater reliability / quality metrics
    # ------------------------------------------------------------------
    def create_inter_rater_case(self, payload, headers):
        return self._request("POST", "/inter-rater-cases", payload, headers)

    def list_inter_rater_cases(self, headers, params=None):
        return self._request("GET", "/inter-rater-cases", headers=headers,
                             params=params)

    def get_inter_rater_case(self, case_id, headers):
        return self._request("GET", f"/inter-rater-cases/{case_id}",
                             headers=headers)

    def adjudicate_inter_rater_case(self, case_id, epochs_concordant, headers):
        return self._request(
            "POST", f"/inter-rater-cases/{case_id}/adjudicate",
            {"epochs_concordant": epochs_concordant}, headers)

    def get_quality_metrics_summary(self, headers):
        return self._request("GET", "/quality-metrics/summary", headers=headers)


api_client = ApiClient()
