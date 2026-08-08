"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Franchise -----
    def create_franchise(self, payload, headers):
        return self._request("POST", "/franchises", payload, headers)

    def get_franchise(self, franchise_id, headers):
        return self._request("GET", f"/franchises/{franchise_id}", headers=headers)

    def get_franchise_summary(self, franchise_id, headers):
        return self._request("GET", f"/franchises/{franchise_id}/summary", headers=headers)

    def activate_franchise(self, franchise_id, headers):
        return self._request("POST", f"/franchises/{franchise_id}/activate", {}, headers)

    def revoke_franchise(self, franchise_id, headers):
        return self._request("POST", f"/franchises/{franchise_id}/revoke", {}, headers)

    def cure_franchise(self, franchise_id, headers):
        return self._request("POST", f"/franchises/{franchise_id}/cure", {}, headers)

    # ----- Row segments -----
    def create_row_segment(self, payload, headers):
        return self._request("POST", "/row-segments", payload, headers)

    def get_row_segment(self, segment_id, headers):
        return self._request("GET", f"/row-segments/{segment_id}", headers=headers)

    # ----- Row permits -----
    def create_row_permit(self, payload, headers):
        return self._request("POST", "/row-permits", payload, headers)

    def get_row_permit(self, permit_id, headers):
        return self._request("GET", f"/row-permits/{permit_id}", headers=headers)

    def list_row_permits(self, headers, params=None):
        return self._request("GET", "/row-permits", headers=headers, params=params)

    def decide_row_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/row-permits/{permit_id}/decide", payload, headers)

    # ----- Buildout milestones -----
    def create_milestone(self, payload, headers):
        return self._request("POST", "/buildout-milestones", payload, headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/buildout-milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/buildout-milestones", headers=headers, params=params)

    def certify_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/buildout-milestones/{milestone_id}/certify", payload, headers)

    # ----- Revenue reports -----
    def create_revenue_report(self, payload, headers):
        return self._request("POST", "/revenue-reports", payload, headers)

    def get_revenue_report(self, report_id, headers):
        return self._request("GET", f"/revenue-reports/{report_id}", headers=headers)

    def list_revenue_reports(self, headers, params=None):
        return self._request("GET", "/revenue-reports", headers=headers, params=params)

    def accept_revenue_report(self, report_id, headers):
        return self._request("POST", f"/revenue-reports/{report_id}/accept", {}, headers)

    def pay_revenue_report(self, report_id, payload, headers):
        return self._request("POST", f"/revenue-reports/{report_id}/pay", payload, headers)

    # ----- Audits -----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def finalize_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/finalize", payload, headers)

    def get_audit_assessments(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}/assessments", headers=headers)

    # ----- Assessments -----
    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def pay_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/assessments/{assessment_id}/pay", payload, headers)

    def dispute_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/dispute", {}, headers)

    def waive_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/waive", {}, headers)

    # ----- Complaints -----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers)

    def escalate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/escalate", {}, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/reopen", {}, headers)

    # ----- PEG contributions -----
    def create_peg_contribution(self, payload, headers):
        return self._request("POST", "/peg-contributions", payload, headers)

    def get_peg_contribution(self, contribution_id, headers):
        return self._request("GET", f"/peg-contributions/{contribution_id}", headers=headers)

    def list_peg_contributions(self, headers, params=None):
        return self._request("GET", "/peg-contributions", headers=headers, params=params)

    def void_peg_contribution(self, contribution_id, payload, headers):
        return self._request("POST", f"/peg-contributions/{contribution_id}/void", payload, headers)

    # ----- Franchise applications -----
    def create_application(self, payload, headers):
        return self._request("POST", "/franchise-applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/franchise-applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/franchise-applications", headers=headers, params=params)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/franchise-applications/{application_id}/decide", payload, headers)

    def deem_application(self, application_id, headers):
        return self._request("POST", f"/franchise-applications/{application_id}/deem", {}, headers)


api_client = ApiClient()
