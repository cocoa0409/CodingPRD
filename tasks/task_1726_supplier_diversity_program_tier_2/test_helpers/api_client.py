"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under /api/v1 (PRD endpoint-definitions section).
"""
from prd_bench_local_runner.testing import GenericApiClient

_V1 = "/api/v1"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Business units
    # ------------------------------------------------------------------
    def create_business_unit(self, payload, headers):
        return self._request("POST", f"{_V1}/business-units", payload, headers)

    def get_business_unit(self, bu_id, headers):
        return self._request("GET", f"{_V1}/business-units/{bu_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{_V1}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{_V1}/suppliers/{supplier_id}",
                             headers=headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"{_V1}/suppliers/{supplier_id}/suspend",
                             {}, headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request("POST", f"{_V1}/suppliers/{supplier_id}/reinstate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Certifications
    # ------------------------------------------------------------------
    def create_certification(self, supplier_id, payload, headers):
        return self._request("POST",
                             f"{_V1}/suppliers/{supplier_id}/certifications",
                             payload, headers)

    def list_certifications(self, supplier_id, headers, params=None):
        return self._request("GET",
                             f"{_V1}/suppliers/{supplier_id}/certifications",
                             headers=headers, params=params)

    def begin_review_certification(self, cert_id, headers):
        return self._request("POST",
                             f"{_V1}/certifications/{cert_id}/begin-review",
                             {}, headers)

    def request_info_certification(self, cert_id, note, headers):
        return self._request("POST",
                             f"{_V1}/certifications/{cert_id}/request-info",
                             {"note": note}, headers)

    def resubmit_certification(self, cert_id, payload, headers):
        return self._request("POST",
                             f"{_V1}/certifications/{cert_id}/resubmit",
                             payload, headers)

    def verify_certification(self, cert_id, headers):
        return self._request("POST", f"{_V1}/certifications/{cert_id}/verify",
                             {}, headers)

    def reject_certification(self, cert_id, reason, headers):
        return self._request("POST", f"{_V1}/certifications/{cert_id}/reject",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Spend records
    # ------------------------------------------------------------------
    def create_spend_record(self, payload, headers):
        return self._request("POST", f"{_V1}/spend-records", payload, headers)

    def list_spend_records(self, headers, params=None):
        return self._request("GET", f"{_V1}/spend-records",
                             headers=headers, params=params)

    def get_spend_record(self, record_id, headers):
        return self._request("GET", f"{_V1}/spend-records/{record_id}",
                             headers=headers)

    def void_spend_record(self, record_id, headers):
        return self._request("POST", f"{_V1}/spend-records/{record_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Tier-2 reports
    # ------------------------------------------------------------------
    def create_tier2_report(self, payload, headers):
        return self._request("POST", f"{_V1}/tier-2-reports", payload, headers)

    def list_tier2_reports(self, headers, params=None):
        return self._request("GET", f"{_V1}/tier-2-reports",
                             headers=headers, params=params)

    def get_tier2_report(self, report_id, headers):
        return self._request("GET", f"{_V1}/tier-2-reports/{report_id}",
                             headers=headers)

    def replace_tier2_lines(self, report_id, payload, headers):
        return self._request("PUT", f"{_V1}/tier-2-reports/{report_id}",
                             payload, headers)

    def submit_tier2_report(self, report_id, headers):
        return self._request("POST",
                             f"{_V1}/tier-2-reports/{report_id}/submit",
                             {}, headers)

    def approve_tier2_report(self, report_id, headers):
        return self._request("POST",
                             f"{_V1}/tier-2-reports/{report_id}/approve",
                             {}, headers)

    def return_tier2_report(self, report_id, note, headers):
        return self._request("POST",
                             f"{_V1}/tier-2-reports/{report_id}/return",
                             {"note": note}, headers)

    # ------------------------------------------------------------------
    # Program goals
    # ------------------------------------------------------------------
    def create_goal(self, bu_id, payload, headers):
        return self._request("POST", f"{_V1}/business-units/{bu_id}/goals",
                             payload, headers)

    def list_goals(self, bu_id, headers, params=None):
        return self._request("GET", f"{_V1}/business-units/{bu_id}/goals",
                             headers=headers, params=params)

    def publish_goal(self, goal_id, headers):
        return self._request("POST", f"{_V1}/goals/{goal_id}/publish",
                             {}, headers)

    # ------------------------------------------------------------------
    # Scorecards
    # ------------------------------------------------------------------
    def generate_scorecard(self, bu_id, payload, headers):
        return self._request("POST", f"{_V1}/business-units/{bu_id}/scorecards",
                             payload, headers)

    def list_bu_scorecards(self, bu_id, headers, params=None):
        return self._request("GET", f"{_V1}/business-units/{bu_id}/scorecards",
                             headers=headers, params=params)

    def get_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"{_V1}/scorecards/{scorecard_id}",
                             headers=headers)

    def list_scorecards(self, headers, params=None):
        return self._request("GET", f"{_V1}/scorecards",
                             headers=headers, params=params)

    def recompute_scorecard(self, scorecard_id, headers):
        return self._request("POST",
                             f"{_V1}/scorecards/{scorecard_id}/recompute",
                             {}, headers)

    def publish_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"{_V1}/scorecards/{scorecard_id}/publish",
                             {}, headers)

    # ------------------------------------------------------------------
    # Sourcing events and invitations
    # ------------------------------------------------------------------
    def create_sourcing_event(self, payload, headers):
        return self._request("POST", f"{_V1}/sourcing-events", payload, headers)

    def list_sourcing_events(self, headers, params=None):
        return self._request("GET", f"{_V1}/sourcing-events",
                             headers=headers, params=params)

    def get_sourcing_event(self, event_id, headers):
        return self._request("GET", f"{_V1}/sourcing-events/{event_id}",
                             headers=headers)

    def open_sourcing_event(self, event_id, headers):
        return self._request("POST", f"{_V1}/sourcing-events/{event_id}/open",
                             {}, headers)

    def award_sourcing_event(self, event_id, payload, headers):
        return self._request("POST", f"{_V1}/sourcing-events/{event_id}/award",
                             payload, headers)

    def cancel_sourcing_event(self, event_id, headers):
        return self._request("POST", f"{_V1}/sourcing-events/{event_id}/cancel",
                             {}, headers)

    def create_invitation(self, event_id, payload, headers):
        return self._request("POST",
                             f"{_V1}/sourcing-events/{event_id}/invitations",
                             payload, headers)

    def list_event_invitations(self, event_id, headers, params=None):
        return self._request("GET",
                             f"{_V1}/sourcing-events/{event_id}/invitations",
                             headers=headers, params=params)

    def list_supplier_invitations(self, supplier_id, headers, params=None):
        return self._request("GET",
                             f"{_V1}/suppliers/{supplier_id}/invitations",
                             headers=headers, params=params)

    def respond_invitation(self, invitation_id, payload, headers):
        return self._request("POST",
                             f"{_V1}/invitations/{invitation_id}/respond",
                             payload, headers)

    # ------------------------------------------------------------------
    # Development engagements
    # ------------------------------------------------------------------
    def create_engagement(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"{_V1}/suppliers/{supplier_id}/development-engagements",
            payload, headers)

    def list_engagements(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"{_V1}/suppliers/{supplier_id}/development-engagements",
            headers=headers, params=params)

    def complete_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{_V1}/development-engagements/{engagement_id}/complete",
            payload, headers)

    def withdraw_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"{_V1}/development-engagements/{engagement_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Audit cases
    # ------------------------------------------------------------------
    def create_audit_case(self, payload, headers):
        return self._request("POST", f"{_V1}/audit-cases", payload, headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", f"{_V1}/audit-cases",
                             headers=headers, params=params)

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"{_V1}/audit-cases/{case_id}",
                             headers=headers)

    def record_audit_outcome(self, case_id, payload, headers):
        return self._request("POST",
                             f"{_V1}/audit-cases/{case_id}/record-outcome",
                             payload, headers)

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{_V1}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
