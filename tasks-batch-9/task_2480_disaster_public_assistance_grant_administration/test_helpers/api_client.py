"""API client: one method per endpoint defined in the PRD.

Every path is rooted at the `/public-assistance` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/public-assistance"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Disaster Public Assistance Grant API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------- disasters
    def create_disaster(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disasters", payload, headers)

    def get_disaster(self, disaster_id, headers):
        return self._request("GET", f"{PREFIX}/disasters/{disaster_id}", headers=headers)

    def list_disasters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disasters", headers=headers, params=params)

    def amend_incident_period(self, disaster_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/disasters/{disaster_id}/incident-period", payload, headers
        )

    def close_obligations(self, disaster_id, headers):
        return self._request(
            "POST", f"{PREFIX}/disasters/{disaster_id}/close-obligations", {}, headers
        )

    # ------------------------------------------------------------ applicants
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applicants", headers=headers, params=params)

    def determine_eligibility(self, applicant_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applicants/{applicant_id}/eligibility-determination",
            payload,
            headers,
        )

    def reporting_sweep(self, applicant_id, headers):
        return self._request(
            "POST", f"{PREFIX}/applicants/{applicant_id}/reporting-sweep", {}, headers
        )

    # ------------------------------------------------------------ facilities
    def create_facility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/facilities", headers=headers, params=params)

    def amend_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/facilities/{facility_id}", payload, headers)

    def screen_facility(self, facility_id, headers):
        return self._request("POST", f"{PREFIX}/facilities/{facility_id}/screen", {}, headers)

    # ---------------------------------------------------------- damage sites
    def create_damage_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-sites", payload, headers)

    def get_damage_site(self, damage_site_id, headers):
        return self._request(
            "GET", f"{PREFIX}/damage-sites/{damage_site_id}", headers=headers
        )

    def list_damage_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/damage-sites", headers=headers, params=params)

    def validate_damage_site(self, damage_site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-sites/{damage_site_id}/validate", payload, headers
        )

    # ----------------------------------------------- force account resources
    def create_force_account_resource(self, payload, headers):
        return self._request("POST", f"{PREFIX}/force-account-resources", payload, headers)

    def get_force_account_resource(self, force_account_resource_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/force-account-resources/{force_account_resource_id}",
            headers=headers,
        )

    def list_force_account_resources(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/force-account-resources", headers=headers, params=params
        )

    # ------------------------------------------------------------- contracts
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    def review_procurement(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/procurement-review", {}, headers
        )

    # ----------------------------------------------------- insurance policies
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-policies", payload, headers)

    def get_insurance_policy(self, insurance_policy_id, headers):
        return self._request(
            "GET", f"{PREFIX}/insurance-policies/{insurance_policy_id}", headers=headers
        )

    def list_insurance_policies(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insurance-policies", headers=headers, params=params
        )

    def record_settlement(self, insurance_policy_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/insurance-policies/{insurance_policy_id}/record-settlement",
            payload,
            headers,
        )

    # -------------------------------------------------------------- projects
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def submit_project(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/submit", {}, headers)

    def issue_rfi(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/rfi", payload, headers)

    def respond_to_rfi(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/rfi-response", payload, headers
        )

    def cost_review(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/cost-review", payload, headers
        )

    def obligate_project(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/obligate", {}, headers)

    def request_closeout(self, project_id, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/closeout-request", {}, headers
        )

    def certify_closeout(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/closeout-certify", payload, headers
        )

    # ------------------------------------------------------- cost line items
    def create_cost_line_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cost-line-items", payload, headers)

    def get_cost_line_item(self, cost_line_item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/cost-line-items/{cost_line_item_id}", headers=headers
        )

    def list_cost_line_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cost-line-items", headers=headers, params=params
        )

    def review_cost_line_item(self, cost_line_item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-line-items/{cost_line_item_id}/review", {}, headers
        )

    # ------------------------------------------------------------- drawdowns
    def create_drawdown(self, payload, headers):
        return self._request("POST", f"{PREFIX}/drawdowns", payload, headers)

    def get_drawdown(self, drawdown_id, headers):
        return self._request("GET", f"{PREFIX}/drawdowns/{drawdown_id}", headers=headers)

    def list_drawdowns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/drawdowns", headers=headers, params=params)

    def disburse_drawdown(self, drawdown_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/drawdowns/{drawdown_id}/disburse", payload, headers
        )

    def refund_drawdown(self, drawdown_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/drawdowns/{drawdown_id}/refund", payload, headers
        )

    # ------------------------------------------------------- progress reports
    def create_progress_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/progress-reports", payload, headers)

    def get_progress_report(self, progress_report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/progress-reports/{progress_report_id}", headers=headers
        )

    def list_progress_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/progress-reports", headers=headers, params=params
        )

    def submit_progress_report(self, progress_report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/progress-reports/{progress_report_id}/submit", payload, headers
        )

    # --------------------------------------------------------- deobligations
    def create_deobligation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deobligations", payload, headers)

    def get_deobligation(self, deobligation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/deobligations/{deobligation_id}", headers=headers
        )

    def list_deobligations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deobligations", headers=headers, params=params)

    def finalize_deobligation(self, deobligation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/deobligations/{deobligation_id}/finalize", {}, headers
        )

    # --------------------------------------------------------------- appeals
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{PREFIX}/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/appeals/{appeal_id}/decide", payload, headers
        )


api_client = ApiClient()
