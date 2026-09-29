"""One client method per endpoint declared by the PRD.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies. Passing ``headers=None`` sends the request with
no authentication headers at all, which is what the unauthenticated cases need.
"""

from typing import Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """HTTP client covering the whole endpoint surface of this service."""

    # ------------------------------------------------------------------
    # Fee programs
    # ------------------------------------------------------------------
    def create_fee_program(
        self, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("POST", "/fee-programs", payload, headers)

    def get_fee_program(
        self, program_id: str, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("GET", f"/fee-programs/{program_id}", headers=headers)

    def list_program_facility_categories(
        self,
        program_id: str,
        headers: Optional[Headers],
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/fee-programs/{program_id}/facility-categories",
            headers=headers,
            params=params,
        )

    def get_annual_report(
        self,
        program_id: str,
        headers: Optional[Headers],
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/fee-programs/{program_id}/annual-report",
            headers=headers,
            params=params,
        )

    def run_deadline_sweep(
        self,
        program_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-programs/{program_id}/deadline-sweep", payload, headers
        )

    def file_annual_report(
        self, program_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-programs/{program_id}/annual-report/file", payload, headers
        )

    # ------------------------------------------------------------------
    # Facility categories
    # ------------------------------------------------------------------
    def create_facility_category(
        self, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("POST", "/facility-categories", payload, headers)

    def get_facility_category(
        self, category_id: str, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "GET", f"/facility-categories/{category_id}", headers=headers
        )

    def create_expenditure(
        self, category_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST", f"/facility-categories/{category_id}/expenditures", payload, headers
        )

    # ------------------------------------------------------------------
    # Fee studies
    # ------------------------------------------------------------------
    def create_fee_study(
        self, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("POST", "/fee-studies", payload, headers)

    def list_fee_studies(
        self, headers: Optional[Headers], params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/fee-studies", headers=headers, params=params)

    def get_fee_study(
        self, study_id: str, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("GET", f"/fee-studies/{study_id}", headers=headers)

    def certify_nexus(
        self,
        study_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-studies/{study_id}/certify-nexus", payload, headers
        )

    def publish_notice(
        self, study_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-studies/{study_id}/publish-notice", payload, headers
        )

    def create_protest_filing(
        self, study_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-studies/{study_id}/protest-filings", payload, headers
        )

    def list_protest_filings(
        self,
        study_id: str,
        headers: Optional[Headers],
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/fee-studies/{study_id}/protest-filings",
            headers=headers,
            params=params,
        )

    def withdraw_protest_filing(
        self,
        filing_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/protest-filings/{filing_id}/withdraw", payload, headers
        )

    def close_protest_window(
        self,
        study_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-studies/{study_id}/close-protest-window", payload, headers
        )

    def adopt_fee_study(
        self,
        study_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-studies/{study_id}/adopt", payload, headers
        )

    def activate_fee_study(
        self,
        study_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/fee-studies/{study_id}/activate", payload, headers
        )

    # ------------------------------------------------------------------
    # Nexus components and schedule lines
    # ------------------------------------------------------------------
    def create_nexus_component(
        self, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("POST", "/nexus-components", payload, headers)

    def list_nexus_components(
        self, headers: Optional[Headers], params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/nexus-components", headers=headers, params=params)

    def get_nexus_component(
        self, component_id: str, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "GET", f"/nexus-components/{component_id}", headers=headers
        )

    def patch_nexus_component(
        self, component_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/nexus-components/{component_id}", payload, headers
        )

    def allocate_nexus_component(
        self,
        component_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/nexus-components/{component_id}/allocate", payload, headers
        )

    def create_fee_schedule_item(
        self, component_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/nexus-components/{component_id}/fee-schedule-items",
            payload,
            headers,
        )

    def list_fee_schedule_items(
        self,
        component_id: str,
        headers: Optional[Headers],
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/nexus-components/{component_id}/fee-schedule-items",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Development applications
    # ------------------------------------------------------------------
    def create_development_application(
        self, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request("POST", "/development-applications", payload, headers)

    def list_development_applications(
        self, headers: Optional[Headers], params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/development-applications", headers=headers, params=params
        )

    def get_development_application(
        self, application_id: str, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "GET", f"/development-applications/{application_id}", headers=headers
        )

    def assess_application(
        self,
        application_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/development-applications/{application_id}/assess", payload, headers
        )

    def create_payment(
        self, application_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/development-applications/{application_id}/payments",
            payload,
            headers,
        )

    def issue_co(
        self,
        application_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/development-applications/{application_id}/issue-co",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Credit claims
    # ------------------------------------------------------------------
    def create_credit_claim(
        self, application_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/development-applications/{application_id}/credit-claims",
            payload,
            headers,
        )

    def list_credit_claims(
        self,
        application_id: str,
        headers: Optional[Headers],
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/development-applications/{application_id}/credit-claims",
            headers=headers,
            params=params,
        )

    def decide_credit_claim(
        self, claim_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST", f"/credit-claims/{claim_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Deferral agreements
    # ------------------------------------------------------------------
    def create_deferral_agreement(
        self, application_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/development-applications/{application_id}/deferral-agreements",
            payload,
            headers,
        )

    def list_deferral_agreements(
        self,
        application_id: str,
        headers: Optional[Headers],
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/development-applications/{application_id}/deferral-agreements",
            headers=headers,
            params=params,
        )

    def decide_deferral_agreement(
        self, agreement_id: str, payload: Payload, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "POST", f"/deferral-agreements/{agreement_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Fund ledger
    # ------------------------------------------------------------------
    def list_fund_ledger_entries(
        self, headers: Optional[Headers], params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/fund-ledger-entries", headers=headers, params=params
        )

    def get_fund_ledger_entry(
        self, entry_id: str, headers: Optional[Headers]
    ) -> requests.Response:
        return self._request(
            "GET", f"/fund-ledger-entries/{entry_id}", headers=headers
        )

    def refund_ledger_entry(
        self,
        entry_id: str,
        headers: Optional[Headers],
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/fund-ledger-entries/{entry_id}/refund", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock control
    # ------------------------------------------------------------------
    def set_clock(
        self, current_utc: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()
