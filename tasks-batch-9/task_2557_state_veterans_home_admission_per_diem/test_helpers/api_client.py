"""One client method per endpoint of the State Veterans Home API.

Every method returns the raw response so tests can assert on both the HTTP
status and the envelope body. Query filters are passed through `params` and
never folded into the path.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the /svh API surface."""

    # ------------------------------------------------------------------
    # Logical clock and operations checkpoint
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    def census_run(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_ops/census-run", payload, headers)

    # ------------------------------------------------------------------
    # Veterans homes
    # ------------------------------------------------------------------
    def create_veterans_home(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/veterans-homes", payload, headers)

    def get_veterans_home(self, home_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/veterans-homes/{home_id}", None, headers)

    def list_veterans_homes(self, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/veterans-homes", None, headers, _clean(params)
        )

    def set_recognition(self, home_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/veterans-homes/{home_id}/recognition", payload, headers
        )

    # ------------------------------------------------------------------
    # Care units
    # ------------------------------------------------------------------
    def create_care_unit(self, home_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/veterans-homes/{home_id}/care-units", payload, headers
        )

    def list_home_care_units(self, home_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/veterans-homes/{home_id}/care-units",
            None,
            headers,
            _clean(params),
        )

    def get_care_unit(self, care_unit_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/care-units/{care_unit_id}", None, headers)

    def record_survey_result(self, care_unit_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/care-units/{care_unit_id}/survey-result", payload, headers
        )

    def list_unit_waitlist_entries(self, care_unit_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/care-units/{care_unit_id}/waitlist-entries",
            None,
            headers,
            _clean(params),
        )

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/applicants/{applicant_id}", None, headers)

    def list_home_applicants(self, home_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/veterans-homes/{home_id}/applicants",
            None,
            headers,
            _clean(params),
        )

    def determine_eligibility(self, applicant_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applicants/{applicant_id}/eligibility-determination",
            payload,
            headers,
        )

    def list_applicant_waitlist_entries(self, applicant_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/applicants/{applicant_id}/waitlist-entries",
            None,
            headers,
            _clean(params),
        )

    def list_applicant_assessments(self, applicant_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/applicants/{applicant_id}/clinical-assessments",
            None,
            headers,
            _clean(params),
        )

    def create_clinical_assessment(self, applicant_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applicants/{applicant_id}/clinical-assessments",
            payload,
            headers,
        )

    def submit_clinical_assessment(self, assessment_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/clinical-assessments/{assessment_id}/submit",
            payload,
            headers,
        )

    def admission_decision(self, applicant_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/applicants/{applicant_id}/admission-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Waitlist entries
    # ------------------------------------------------------------------
    def create_waitlist_entry(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/waitlist-entries", payload, headers)

    # ------------------------------------------------------------------
    # Residents
    # ------------------------------------------------------------------
    def get_resident(self, resident_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/residents/{resident_id}", None, headers)

    def list_residents(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/residents", None, headers, _clean(params))

    def transfer_resident(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/transfer", payload, headers
        )

    def hospitalize_resident(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/hospitalization", payload, headers
        )

    def readmit_resident(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/readmission", payload, headers
        )

    def discharge_resident(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/discharge", payload, headers
        )

    # ------------------------------------------------------------------
    # Income records and cost share
    # ------------------------------------------------------------------
    def create_income_record(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/income-records", payload, headers
        )

    def list_income_records(self, resident_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/residents/{resident_id}/income-records",
            None,
            headers,
            _clean(params),
        )

    def verify_income_record(self, income_record_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/income-records/{income_record_id}/verify", payload, headers
        )

    def create_cost_share_determination(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/residents/{resident_id}/cost-share-determinations",
            payload,
            headers,
        )

    def list_cost_share_determinations(self, resident_id, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/residents/{resident_id}/cost-share-determinations",
            None,
            headers,
            _clean(params),
        )

    # ------------------------------------------------------------------
    # Care plans
    # ------------------------------------------------------------------
    def create_care_plan(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/care-plans", payload, headers
        )

    def activate_care_plan(self, care_plan_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/care-plans/{care_plan_id}/activate", payload, headers
        )

    def get_care_plan(self, care_plan_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/care-plans/{care_plan_id}", None, headers)

    def list_care_plans(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/care-plans", None, headers, _clean(params))

    # ------------------------------------------------------------------
    # Census days
    # ------------------------------------------------------------------
    def get_census_day(self, census_day_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/census-days/{census_day_id}", None, headers)

    def list_census_days(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/census-days", None, headers, _clean(params))

    # ------------------------------------------------------------------
    # Per diem claims
    # ------------------------------------------------------------------
    def create_per_diem_claim(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/per-diem-claims", payload, headers)

    def get_per_diem_claim(self, claim_id, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/per-diem-claims/{claim_id}", None, headers)

    def list_per_diem_claims(self, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/per-diem-claims", None, headers, _clean(params)
        )

    def submit_per_diem_claim(self, claim_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/per-diem-claims/{claim_id}/submit", payload, headers
        )

    def adjudicate_per_diem_claim(self, claim_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/per-diem-claims/{claim_id}/adjudicate", payload, headers
        )

    def correct_per_diem_claim(self, claim_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/per-diem-claims/{claim_id}/correct", payload, headers
        )

    # ------------------------------------------------------------------
    # Trust fund
    # ------------------------------------------------------------------
    def create_trust_fund_transaction(self, resident_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/residents/{resident_id}/trust-fund-transactions",
            payload,
            headers,
        )

    def reverse_trust_fund_transaction(self, transaction_id, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/trust-fund-transactions/{transaction_id}/reverse",
            payload,
            headers,
        )

    def get_trust_fund_transaction(self, transaction_id, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/trust-fund-transactions/{transaction_id}", None, headers
        )

    def list_trust_fund_transactions(self, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/trust-fund-transactions", None, headers, _clean(params)
        )
