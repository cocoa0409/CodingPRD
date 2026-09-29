"""API client: one method per endpoint declared in the PRD.

Every path is rooted at the `/osup` prefix. Methods return the raw response so
that tests can assert status codes as well as payloads.
"""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/osup"


class ApiClient(GenericApiClient):
    # --- Operations: logical clock and nightly sweep ---
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def run_daily_compliance_sweep(self, headers):
        return self._request(
            "POST", f"{PREFIX}/_ops/run-daily-compliance-sweep", {}, headers
        )

    # --- Use areas ---
    def create_use_area(self, payload, headers):
        return self._request("POST", f"{PREFIX}/use-areas", payload, headers)

    def get_use_area(self, use_area_id, headers):
        return self._request(
            "GET", f"{PREFIX}/use-areas/{use_area_id}", headers=headers
        )

    def list_use_areas(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/use-areas", headers=headers, params=params)

    def get_allocation_summary(self, use_area_id, headers):
        return self._request(
            "GET", f"{PREFIX}/use-areas/{use_area_id}/allocation-summary",
            headers=headers,
        )

    # --- Outfitters ---
    def create_outfitter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/outfitters", payload, headers)

    def get_outfitter(self, outfitter_id, headers):
        return self._request(
            "GET", f"{PREFIX}/outfitters/{outfitter_id}", headers=headers
        )

    def record_prequalification(self, outfitter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/outfitters/{outfitter_id}/prequalification",
            payload, headers,
        )

    # --- Needs assessments ---
    def create_needs_assessment(self, use_area_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/use-areas/{use_area_id}/needs-assessments",
            payload, headers,
        )

    def publish_needs_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/needs-assessments/{assessment_id}/publish", {}, headers
        )

    def list_needs_assessments(self, use_area_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/use-areas/{use_area_id}/needs-assessments",
            headers=headers, params=params,
        )

    # --- Prospectuses ---
    def create_prospectus(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prospectuses", payload, headers)

    def get_prospectus(self, prospectus_id, headers):
        return self._request(
            "GET", f"{PREFIX}/prospectuses/{prospectus_id}", headers=headers
        )

    def list_prospectuses(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/prospectuses", headers=headers, params=params
        )

    def create_prospectus_response(self, prospectus_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prospectuses/{prospectus_id}/responses", payload, headers
        )

    def close_prospectus_submissions(self, prospectus_id, headers):
        return self._request(
            "POST", f"{PREFIX}/prospectuses/{prospectus_id}/close-submissions",
            {}, headers,
        )

    def award_prospectus(self, prospectus_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prospectuses/{prospectus_id}/award", payload, headers
        )

    def cancel_prospectus(self, prospectus_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prospectuses/{prospectus_id}/cancel", payload, headers
        )

    # --- Permit applications ---
    def create_permit_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permit-applications", payload, headers)

    def get_permit_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/permit-applications/{application_id}", headers=headers
        )

    def list_permit_applications(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permit-applications", headers=headers, params=params
        )

    def submit_permit_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/submit", {}, headers
        )

    def screen_permit_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/screen", {}, headers
        )

    def deny_permit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/deny",
            payload, headers,
        )

    def withdraw_permit_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/withdraw", {}, headers
        )

    def issue_permit(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/issue-permit",
            payload, headers,
        )

    # --- Permits ---
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/permits", headers=headers, params=params)

    def acknowledge_indemnification(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/acknowledge-indemnification",
            {}, headers,
        )

    def activate_permit(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/activate", {}, headers
        )

    def suspend_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/suspend", payload, headers
        )

    def reinstate_permit(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/reinstate", {}, headers
        )

    def revoke_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/revoke", payload, headers
        )

    def change_permit_holder(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/holder-change", payload, headers
        )

    # --- Operating plans ---
    def create_operating_plan(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/operating-plans", payload, headers
        )

    def list_operating_plans(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/operating-plans",
            headers=headers, params=params,
        )

    def get_operating_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/operating-plans/{plan_id}", headers=headers
        )

    def replace_operating_plan_section(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operating-plans/{plan_id}/sections", payload, headers
        )

    def submit_operating_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/operating-plans/{plan_id}/submit", {}, headers
        )

    def start_operating_plan_review(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/operating-plans/{plan_id}/start-review", {}, headers
        )

    def request_operating_plan_revision(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operating-plans/{plan_id}/request-revision",
            payload, headers,
        )

    def approve_operating_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/operating-plans/{plan_id}/approve", {}, headers
        )

    def reject_operating_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operating-plans/{plan_id}/reject", payload, headers
        )

    # --- Guides ---
    def create_guide(self, outfitter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/outfitters/{outfitter_id}/guides", payload, headers
        )

    def list_guides(self, outfitter_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/outfitters/{outfitter_id}/guides",
            headers=headers, params=params,
        )

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"{PREFIX}/guides/{guide_id}", headers=headers)

    def record_guide_certification(self, guide_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/guides/{guide_id}/certifications", payload, headers
        )

    def qualify_guide(self, guide_id, headers):
        return self._request(
            "POST", f"{PREFIX}/guides/{guide_id}/qualify", {}, headers
        )

    # --- Guide authorizations ---
    def create_guide_authorization(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/guide-authorizations", payload, headers
        )

    def list_permit_guide_authorizations(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/guide-authorizations",
            headers=headers, params=params,
        )

    def list_guide_guide_authorizations(self, guide_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/guides/{guide_id}/guide-authorizations",
            headers=headers, params=params,
        )

    def revoke_guide_authorization(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/guide-authorizations/{authorization_id}/revoke",
            payload, headers,
        )

    # --- Insurance certificates and bonds ---
    def create_insurance_certificate(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/insurance-certificates",
            payload, headers,
        )

    def list_insurance_certificates(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/insurance-certificates",
            headers=headers, params=params,
        )

    def create_bond(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/bonds", payload, headers
        )

    def list_bonds(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/bonds", headers=headers, params=params
        )

    # --- Trip use reports ---
    def create_trip_use_report(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/trip-use-reports", payload, headers
        )

    def get_trip_use_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/trip-use-reports/{report_id}", headers=headers
        )

    def list_trip_use_reports(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/trip-use-reports", headers=headers, params=params
        )

    def accept_trip_use_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/trip-use-reports/{report_id}/accept", {}, headers
        )

    def amend_trip_use_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trip-use-reports/{report_id}/amend", payload, headers
        )

    # --- Fee assessments ---
    def list_fee_assessments(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/fee-assessments",
            headers=headers, params=params,
        )

    def get_fee_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fee-assessments/{assessment_id}", headers=headers
        )

    def finalize_fee_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/fee-assessments/{assessment_id}/finalize", {}, headers
        )

    def create_fee_payment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fee-assessments/{assessment_id}/payments", payload, headers
        )

    def close_fee_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/fee-assessments/{assessment_id}/close", {}, headers
        )

    # --- Performance evaluations ---
    def create_performance_evaluation(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/performance-evaluations",
            payload, headers,
        )

    def list_performance_evaluations(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/performance-evaluations",
            headers=headers, params=params,
        )

    # --- Noncompliance actions ---
    def create_noncompliance_action(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/noncompliance-actions",
            payload, headers,
        )

    def list_noncompliance_actions(self, permit_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/noncompliance-actions",
            headers=headers, params=params,
        )

    def cure_noncompliance_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/noncompliance-actions/{action_id}/cure", payload, headers
        )

    def appeal_noncompliance_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/noncompliance-actions/{action_id}/appeal", payload, headers
        )

    def decide_noncompliance_appeal(self, action_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/noncompliance-actions/{action_id}/decide-appeal",
            payload, headers,
        )


api_client = ApiClient()
