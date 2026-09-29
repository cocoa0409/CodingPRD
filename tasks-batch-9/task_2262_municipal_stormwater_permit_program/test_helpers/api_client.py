"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/stormwater"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Municipal Stormwater Permit Program API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Permit terms
    # ------------------------------------------------------------------

    def create_permit_term(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/permit-terms", payload, headers)

    def list_permit_terms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/permit-terms", headers=headers, params=params)

    def get_permit_term(self, term_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/permit-terms/{term_id}", headers=headers)

    def activate_permit_term(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/permit-terms/{term_id}/activate", headers=headers
        )

    def expire_permit_term(self, term_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/permit-terms/{term_id}/expire", headers=headers
        )

    def list_term_control_measures(
        self, term_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/permit-terms/{term_id}/control-measures",
            headers=headers,
            params=params,
        )

    def list_term_outfalls(
        self, term_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/permit-terms/{term_id}/outfalls", headers=headers, params=params
        )

    def list_term_construction_sites(
        self, term_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/permit-terms/{term_id}/construction-sites",
            headers=headers,
            params=params,
        )

    def list_term_accounts(
        self, term_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/permit-terms/{term_id}/accounts", headers=headers, params=params
        )

    def list_term_annual_reports(
        self, term_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/permit-terms/{term_id}/annual-reports",
            headers=headers,
            params=params,
        )

    def create_billing_run(self, term_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/permit-terms/{term_id}/billing-runs", payload, headers
        )

    # ------------------------------------------------------------------
    # Control measures
    # ------------------------------------------------------------------

    def create_control_measure(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/control-measures", payload, headers)

    def get_control_measure(self, measure_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/control-measures/{measure_id}", headers=headers
        )

    def report_measure_progress(
        self, measure_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/control-measures/{measure_id}/report-progress", payload, headers
        )

    def retire_control_measure(self, measure_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/control-measures/{measure_id}/retire", headers=headers
        )

    # ------------------------------------------------------------------
    # Outfalls
    # ------------------------------------------------------------------

    def create_outfall(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/outfalls", payload, headers)

    def get_outfall(self, outfall_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/outfalls/{outfall_id}", headers=headers)

    def retire_outfall(self, outfall_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/outfalls/{outfall_id}/retire", headers=headers
        )

    def create_observation(self, outfall_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/outfalls/{outfall_id}/observations", payload, headers
        )

    def list_outfall_observations(
        self, outfall_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/outfalls/{outfall_id}/observations",
            headers=headers,
            params=params,
        )

    def validate_observation(
        self, observation_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/observations/{observation_id}/validate", payload, headers
        )

    def create_sweeping_run(self, outfall_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/outfalls/{outfall_id}/sweeping-runs", payload, headers
        )

    def create_load_assessment(
        self, outfall_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/outfalls/{outfall_id}/load-assessments", payload, headers
        )

    # ------------------------------------------------------------------
    # Illicit discharge cases
    # ------------------------------------------------------------------

    def list_illicit_discharge_cases(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/illicit-discharge-cases", headers=headers, params=params
        )

    def get_illicit_discharge_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/illicit-discharge-cases/{case_id}", headers=headers
        )

    def start_tracing(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/illicit-discharge-cases/{case_id}/start-tracing", payload, headers
        )

    def identify_source(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/illicit-discharge-cases/{case_id}/identify-source",
            payload,
            headers,
        )

    def reopen_tracing(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/illicit-discharge-cases/{case_id}/reopen-tracing",
            payload,
            headers,
        )

    def resolve_case(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/illicit-discharge-cases/{case_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Construction sites
    # ------------------------------------------------------------------

    def create_construction_site(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/construction-sites", payload, headers)

    def get_construction_site(self, site_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/construction-sites/{site_id}", headers=headers
        )

    def submit_esc_plan(self, site_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/construction-sites/{site_id}/submit-esc-plan", payload, headers
        )

    def esc_review(self, site_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/construction-sites/{site_id}/esc-review", payload, headers
        )

    def stop_work(self, site_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/construction-sites/{site_id}/stop-work", payload, headers
        )

    def release_stop_work(self, site_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/construction-sites/{site_id}/release-stop-work",
            payload,
            headers,
        )

    def close_construction_site(self, site_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/construction-sites/{site_id}/close", payload, headers
        )

    def list_site_post_construction_facilities(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/construction-sites/{site_id}/post-construction-facilities",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Post-construction facilities
    # ------------------------------------------------------------------

    def create_post_construction_facility(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/post-construction-facilities", payload, headers
        )

    def get_post_construction_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/post-construction-facilities/{facility_id}", headers=headers
        )

    def record_agreement(self, facility_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/post-construction-facilities/{facility_id}/record-agreement",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------

    def create_inspection(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def list_inspections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers)

    def add_inspection_finding(
        self, inspection_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/findings", payload, headers
        )

    def finalize_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/finalize", headers=headers
        )

    # ------------------------------------------------------------------
    # Enforcement actions
    # ------------------------------------------------------------------

    def create_enforcement_action(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/enforcement-actions", payload, headers)

    def list_enforcement_actions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/enforcement-actions", headers=headers, params=params
        )

    def get_enforcement_action(self, action_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/enforcement-actions/{action_id}", headers=headers
        )

    def escalate_enforcement_action(
        self, action_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/enforcement-actions/{action_id}/escalate", payload, headers
        )

    def close_enforcement_action(
        self, action_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/enforcement-actions/{action_id}/close", payload, headers
        )

    def rescind_enforcement_action(
        self, action_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/enforcement-actions/{action_id}/rescind", payload, headers
        )

    # ------------------------------------------------------------------
    # Stormwater accounts
    # ------------------------------------------------------------------

    def create_account(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def create_impervious_update(
        self, account_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/impervious-updates", payload, headers
        )

    # ------------------------------------------------------------------
    # Fee credit applications
    # ------------------------------------------------------------------

    def create_fee_credit_application(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/fee-credit-applications", payload, headers)

    def list_fee_credit_applications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/fee-credit-applications", headers=headers, params=params
        )

    def get_fee_credit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/fee-credit-applications/{application_id}", headers=headers
        )

    def review_fee_credit_application(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/fee-credit-applications/{application_id}/review",
            payload,
            headers,
        )

    def resubmit_fee_credit_application(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/fee-credit-applications/{application_id}/resubmit",
            payload,
            headers,
        )

    def revoke_fee_credit_application(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/fee-credit-applications/{application_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Annual reports
    # ------------------------------------------------------------------

    def create_annual_report(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/annual-reports", payload, headers)

    def get_annual_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/annual-reports/{report_id}", headers=headers)

    def compile_annual_report(self, report_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/annual-reports/{report_id}/compile", payload, headers
        )

    def certify_annual_report(self, report_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/annual-reports/{report_id}/certify", payload, headers
        )

    def submit_annual_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/annual-reports/{report_id}/submit", headers=headers
        )


api_client = ApiClient()
