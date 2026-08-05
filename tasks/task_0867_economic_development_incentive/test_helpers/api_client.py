"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- IncentiveProgram ----
    def create_program(self, payload, headers):
        return self._request("POST", "/incentive-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/incentive-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/incentive-programs/{program_id}", headers=headers)

    # ---- Parcel ----
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", headers=headers)

    def start_review(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/start-review", payload or {}, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/approve", headers=headers)

    def deny_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/deny", payload or {}, headers)

    # ---- EligibilityReview ----
    def list_eligibility_reviews(self, headers, params=None):
        return self._request("GET", "/eligibility-reviews", headers=headers, params=params)

    def get_eligibility_review(self, review_id, headers):
        return self._request("GET", f"/eligibility-reviews/{review_id}", headers=headers)

    # ---- Agreement ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/activate", headers=headers)

    def declare_default(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/agreements/{agreement_id}/declare-default", payload or {}, headers)

    # ---- Covenant ----
    def create_covenant(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/covenants", payload, headers)

    def list_covenants(self, headers, params=None):
        return self._request("GET", "/covenants", headers=headers, params=params)

    def get_covenant(self, covenant_id, headers):
        return self._request("GET", f"/covenants/{covenant_id}", headers=headers)

    def waive_covenant(self, covenant_id, headers, payload=None):
        return self._request("POST", f"/covenants/{covenant_id}/waive", payload or {}, headers)

    # ---- ComplianceReport ----
    def create_compliance_report(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/compliance-reports", payload, headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request("GET", "/compliance-reports", headers=headers, params=params)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}", headers=headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/accept", headers=headers)

    def return_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/compliance-reports/{report_id}/return", payload or {}, headers)

    def resubmit_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/compliance-reports/{report_id}/resubmit", payload or {}, headers)

    # ---- Disbursement ----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def approve_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/approve", headers=headers)

    def pay_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/pay", headers=headers)

    # ---- RecaptureAssessment ----
    def list_recapture_assessments(self, headers, params=None):
        return self._request("GET", "/recapture-assessments", headers=headers, params=params)

    def get_recapture_assessment(self, assessment_id, headers):
        return self._request("GET", f"/recapture-assessments/{assessment_id}", headers=headers)

    def dispute_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/recapture-assessments/{assessment_id}/dispute", payload or {}, headers)

    def finalize_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/recapture-assessments/{assessment_id}/finalize", payload or {}, headers)

    def waive_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/recapture-assessments/{assessment_id}/waive", payload or {}, headers)

    # ---- TransparencyDisclosure ----
    def create_disclosure(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/disclosures", payload, headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/disclosures/{disclosure_id}", headers=headers)

    # ---- Portfolio dashboard ----
    def portfolio_summary(self, headers, params=None):
        return self._request("GET", "/portfolio/summary", headers=headers, params=params)


api_client = ApiClient()
