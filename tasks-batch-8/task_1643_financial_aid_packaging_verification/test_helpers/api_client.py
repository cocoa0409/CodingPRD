"""API client: one method per endpoint defined in the PRD endpoint table (§4).

All resources are mounted under `/api`. Methods return raw requests.Response
objects so tests can assert status codes and envelopes themselves.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.6)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Aid years
    # ------------------------------------------------------------------
    def create_aid_year(self, payload, headers):
        return self._request("POST", "/api/aid-years", payload, headers)

    def list_aid_years(self, headers, params=None):
        return self._request("GET", "/api/aid-years", headers=headers, params=params)

    def get_aid_year(self, aid_year_id, headers):
        return self._request("GET", f"/api/aid-years/{aid_year_id}", headers=headers)

    def open_aid_year(self, aid_year_id, headers):
        return self._request("POST", f"/api/aid-years/{aid_year_id}/open", {}, headers)

    def lock_packaging(self, aid_year_id, headers):
        return self._request("POST", f"/api/aid-years/{aid_year_id}/lock-packaging", {}, headers)

    def begin_reconciliation(self, aid_year_id, headers):
        return self._request("POST", f"/api/aid-years/{aid_year_id}/begin-reconciliation", {}, headers)

    def close_aid_year(self, aid_year_id, headers):
        return self._request("POST", f"/api/aid-years/{aid_year_id}/close", {}, headers)

    def list_aid_year_fund_types(self, aid_year_id, headers, params=None):
        return self._request("GET", f"/api/aid-years/{aid_year_id}/fund-types",
                             headers=headers, params=params)

    def list_aid_year_reconciliation_runs(self, aid_year_id, headers, params=None):
        return self._request("GET", f"/api/aid-years/{aid_year_id}/reconciliation-runs",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fund types
    # ------------------------------------------------------------------
    def create_fund_type(self, payload, headers):
        return self._request("POST", "/api/fund-types", payload, headers)

    def list_fund_types(self, headers, params=None):
        return self._request("GET", "/api/fund-types", headers=headers, params=params)

    def get_fund_type(self, fund_type_id, headers):
        return self._request("GET", f"/api/fund-types/{fund_type_id}", headers=headers)

    def activate_fund_type(self, fund_type_id, headers):
        return self._request("POST", f"/api/fund-types/{fund_type_id}/activate", {}, headers)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/api/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/api/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/api/students/{student_id}", payload, headers)

    def evaluate_sap(self, student_id, payload, headers):
        return self._request("POST", f"/api/students/{student_id}/evaluate-sap",
                             payload, headers)

    def sap_appeal(self, student_id, appeal_reason, headers):
        return self._request("POST", f"/api/students/{student_id}/sap-appeal",
                             {"appeal_reason": appeal_reason}, headers)

    def list_student_isir_records(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/isir-records",
                             headers=headers, params=params)

    def list_student_verification_cases(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/verification-cases",
                             headers=headers, params=params)

    def list_student_award_packages(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/award-packages",
                             headers=headers, params=params)

    def list_student_external_aid(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/external-aid",
                             headers=headers, params=params)

    def list_student_overaward_cases(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/overaward-cases",
                             headers=headers, params=params)

    def list_student_pj_cases(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/pj-cases",
                             headers=headers, params=params)

    def list_student_conflicting_info_cases(self, student_id, headers, params=None):
        return self._request("GET", f"/api/students/{student_id}/conflicting-info-cases",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # ISIR records
    # ------------------------------------------------------------------
    def create_isir_record(self, payload, headers):
        return self._request("POST", "/api/isir-records", payload, headers)

    def list_isir_records(self, headers, params=None):
        return self._request("GET", "/api/isir-records", headers=headers, params=params)

    def get_isir_record(self, isir_id, headers):
        return self._request("GET", f"/api/isir-records/{isir_id}", headers=headers)

    # ------------------------------------------------------------------
    # Verification cases and documents
    # ------------------------------------------------------------------
    def list_verification_cases(self, headers, params=None):
        return self._request("GET", "/api/verification-cases", headers=headers, params=params)

    def get_verification_case(self, case_id, headers):
        return self._request("GET", f"/api/verification-cases/{case_id}", headers=headers)

    def begin_review_verification_case(self, case_id, headers):
        return self._request("POST", f"/api/verification-cases/{case_id}/begin-review",
                             {}, headers)

    def request_verification_documents(self, case_id, doc_types, headers):
        return self._request("POST", f"/api/verification-cases/{case_id}/request-documents",
                             {"doc_types": doc_types}, headers)

    def complete_satisfied(self, case_id, payload, headers):
        return self._request("POST", f"/api/verification-cases/{case_id}/complete-satisfied",
                             payload, headers)

    def complete_correction(self, case_id, resolution_notes, headers):
        return self._request("POST", f"/api/verification-cases/{case_id}/complete-correction",
                             {"resolution_notes": resolution_notes}, headers)

    def waive_verification_case(self, case_id, waived_reason, headers):
        return self._request("POST", f"/api/verification-cases/{case_id}/waive",
                             {"waived_reason": waived_reason}, headers)

    def list_verification_documents(self, case_id, headers, params=None):
        return self._request("GET", f"/api/verification-cases/{case_id}/documents",
                             headers=headers, params=params)

    def mark_document_received(self, doc_id, headers):
        return self._request("POST", f"/api/verification-documents/{doc_id}/mark-received",
                             {}, headers)

    def accept_document(self, doc_id, headers):
        return self._request("POST", f"/api/verification-documents/{doc_id}/accept",
                             {}, headers)

    def reject_document(self, doc_id, rejection_reason, headers):
        return self._request("POST", f"/api/verification-documents/{doc_id}/reject",
                             {"rejection_reason": rejection_reason}, headers)

    def request_document_resubmission(self, doc_id, headers):
        return self._request("POST",
                             f"/api/verification-documents/{doc_id}/request-resubmission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Conflicting-information cases
    # ------------------------------------------------------------------
    def create_conflicting_info_case(self, payload, headers):
        return self._request("POST", "/api/conflicting-info-cases", payload, headers)

    def list_conflicting_info_cases(self, headers, params=None):
        return self._request("GET", "/api/conflicting-info-cases", headers=headers,
                             params=params)

    def get_conflicting_info_case(self, case_id, headers):
        return self._request("GET", f"/api/conflicting-info-cases/{case_id}",
                             headers=headers)

    def substantiate_conflicting_info_case(self, case_id, headers):
        return self._request("POST",
                             f"/api/conflicting-info-cases/{case_id}/substantiate",
                             {}, headers)

    def unsubstantiate_conflicting_info_case(self, case_id, headers):
        return self._request("POST",
                             f"/api/conflicting-info-cases/{case_id}/unsubstantiate",
                             {}, headers)

    def resolve_requires_correction(self, case_id, resolution, headers):
        return self._request(
            "POST", f"/api/conflicting-info-cases/{case_id}/resolve-requires-correction",
            {"resolution": resolution}, headers)

    def resolve_conflicting_info_case(self, case_id, resolution, headers):
        return self._request("POST", f"/api/conflicting-info-cases/{case_id}/resolve",
                             {"resolution": resolution}, headers)

    # ------------------------------------------------------------------
    # Professional judgment cases
    # ------------------------------------------------------------------
    def create_pj_case(self, payload, headers):
        return self._request("POST", "/api/pj-cases", payload, headers)

    def list_pj_cases(self, headers, params=None):
        return self._request("GET", "/api/pj-cases", headers=headers, params=params)

    def get_pj_case(self, pj_id, headers):
        return self._request("GET", f"/api/pj-cases/{pj_id}", headers=headers)

    def begin_review_pj_case(self, pj_id, headers):
        return self._request("POST", f"/api/pj-cases/{pj_id}/begin-review", {}, headers)

    def approve_pj_case(self, pj_id, expected_pj_version, headers):
        return self._request("POST", f"/api/pj-cases/{pj_id}/approve",
                             {"expected_pj_version": expected_pj_version}, headers)

    def deny_pj_case(self, pj_id, headers):
        return self._request("POST", f"/api/pj-cases/{pj_id}/deny", {}, headers)

    # ------------------------------------------------------------------
    # Award packages
    # ------------------------------------------------------------------
    def create_award_package(self, payload, headers):
        return self._request("POST", "/api/award-packages", payload, headers)

    def list_award_packages(self, headers, params=None):
        return self._request("GET", "/api/award-packages", headers=headers, params=params)

    def get_award_package(self, package_id, headers):
        return self._request("GET", f"/api/award-packages/{package_id}", headers=headers)

    def build_award_package(self, package_id, headers):
        return self._request("POST", f"/api/award-packages/{package_id}/build", {}, headers)

    def notify_award_package(self, package_id, headers):
        return self._request("POST", f"/api/award-packages/{package_id}/notify", {}, headers)

    def accept_award_package(self, package_id, line_acceptances, headers):
        return self._request("POST", f"/api/award-packages/{package_id}/accept",
                             {"line_acceptances": line_acceptances}, headers)

    def decline_award_package(self, package_id, headers):
        return self._request("POST", f"/api/award-packages/{package_id}/decline",
                             {}, headers)

    def lock_award_package(self, package_id, expected_package_version, headers):
        return self._request("POST", f"/api/award-packages/{package_id}/lock",
                             {"expected_package_version": expected_package_version},
                             headers)

    def create_revision_request(self, package_id, reason, headers):
        return self._request("POST", f"/api/award-packages/{package_id}/revision-requests",
                             {"reason": reason}, headers)

    def list_package_award_lines(self, package_id, headers, params=None):
        return self._request("GET", f"/api/award-packages/{package_id}/award-lines",
                             headers=headers, params=params)

    def list_package_notifications(self, package_id, headers, params=None):
        return self._request("GET", f"/api/award-packages/{package_id}/notifications",
                             headers=headers, params=params)

    def list_package_revision_requests(self, package_id, headers, params=None):
        return self._request("GET",
                             f"/api/award-packages/{package_id}/revision-requests",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Award lines and notifications
    # ------------------------------------------------------------------
    def list_award_lines(self, headers, params=None):
        return self._request("GET", "/api/award-lines", headers=headers, params=params)

    def get_award_line(self, line_id, headers):
        return self._request("GET", f"/api/award-lines/{line_id}", headers=headers)

    def begin_line_disbursement(self, line_id, headers):
        return self._request("POST", f"/api/award-lines/{line_id}/begin-disbursement",
                             {}, headers)

    def request_line_return(self, line_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/api/award-lines/{line_id}/request-return",
                             payload, headers)

    def confirm_line_return(self, line_id, return_cents, headers):
        return self._request("POST", f"/api/award-lines/{line_id}/confirm-return",
                             {"return_cents": return_cents}, headers)

    def acknowledge_notification(self, notification_id, headers):
        return self._request("POST",
                             f"/api/award-notifications/{notification_id}/acknowledge",
                             {}, headers)

    # ------------------------------------------------------------------
    # Revision requests
    # ------------------------------------------------------------------
    def get_revision_request(self, request_id, headers):
        return self._request("GET", f"/api/revision-requests/{request_id}", headers=headers)

    def begin_review_revision_request(self, request_id, headers):
        return self._request("POST", f"/api/revision-requests/{request_id}/begin-review",
                             {}, headers)

    def approve_revision_request(self, request_id, decision_notes, headers):
        return self._request("POST", f"/api/revision-requests/{request_id}/approve",
                             {"decision_notes": decision_notes}, headers)

    def deny_revision_request(self, request_id, decision_notes, headers):
        return self._request("POST", f"/api/revision-requests/{request_id}/deny",
                             {"decision_notes": decision_notes}, headers)

    # ------------------------------------------------------------------
    # Disbursements
    # ------------------------------------------------------------------
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/api/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/api/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/api/disbursements/{disbursement_id}",
                             headers=headers)

    def evaluate_disbursement_eligibility(self, disbursement_id, headers):
        return self._request("POST",
                             f"/api/disbursements/{disbursement_id}/evaluate-eligibility",
                             {}, headers)

    def reset_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/api/disbursements/{disbursement_id}/reset",
                             {}, headers)

    def post_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/api/disbursements/{disbursement_id}/post",
                             {}, headers)

    def request_disbursement_return(self, disbursement_id, headers):
        return self._request("POST",
                             f"/api/disbursements/{disbursement_id}/request-return",
                             {}, headers)

    def confirm_disbursement_return(self, disbursement_id, headers):
        return self._request("POST",
                             f"/api/disbursements/{disbursement_id}/confirm-return",
                             {}, headers)

    # ------------------------------------------------------------------
    # External aid and over-award cases
    # ------------------------------------------------------------------
    def create_external_aid(self, payload, headers):
        return self._request("POST", "/api/external-aid", payload, headers)

    def list_external_aid(self, headers, params=None):
        return self._request("GET", "/api/external-aid", headers=headers, params=params)

    def get_external_aid(self, external_aid_id, headers):
        return self._request("GET", f"/api/external-aid/{external_aid_id}", headers=headers)

    def list_overaward_cases(self, headers, params=None):
        return self._request("GET", "/api/overaward-cases", headers=headers, params=params)

    def get_overaward_case(self, case_id, headers):
        return self._request("GET", f"/api/overaward-cases/{case_id}", headers=headers)

    def begin_overaward_resolution(self, case_id, resolution_plan, headers):
        return self._request("POST", f"/api/overaward-cases/{case_id}/begin-resolution",
                             {"resolution_plan": resolution_plan}, headers)

    def rollback_overaward_case(self, case_id, headers):
        return self._request("POST", f"/api/overaward-cases/{case_id}/rollback",
                             {}, headers)

    def verify_overaward_case(self, case_id, headers):
        return self._request("POST", f"/api/overaward-cases/{case_id}/verify", {}, headers)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------
    def get_reconciliation_run(self, run_id, headers):
        return self._request("GET", f"/api/reconciliation-runs/{run_id}", headers=headers)

    def import_federal(self, run_id, federal_reported_cents, headers):
        return self._request("POST", f"/api/reconciliation-runs/{run_id}/import-federal",
                             {"federal_reported_cents": federal_reported_cents}, headers)

    def compare_reconciliation_run(self, run_id, headers):
        return self._request("POST", f"/api/reconciliation-runs/{run_id}/compare",
                             {}, headers)

    def create_reconciliation_adjustment(self, run_id, payload, headers):
        return self._request("POST", f"/api/reconciliation-runs/{run_id}/adjustments",
                             payload, headers)

    def finalize_reconciliation_run(self, run_id, headers):
        return self._request("POST", f"/api/reconciliation-runs/{run_id}/finalize",
                             {}, headers)

    def list_line_reconciliation_adjustments(self, line_id, headers, params=None):
        return self._request("GET",
                             f"/api/award-lines/{line_id}/reconciliation-adjustments",
                             headers=headers, params=params)

    def list_run_adjustments(self, run_id, headers, params=None):
        return self._request("GET", f"/api/reconciliation-runs/{run_id}/adjustments",
                             headers=headers, params=params)


api_client = ApiClient()
