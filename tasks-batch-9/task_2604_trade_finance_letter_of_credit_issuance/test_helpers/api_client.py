"""One method per endpoint declared in the PRD endpoint table."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, typed wrapper over the trade finance API surface."""

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------
    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicant_facilities(
        self,
        applicant_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/applicants/{applicant_id}/facilities", headers=headers, params=params
        )

    def create_facility(
        self, applicant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applicants/{applicant_id}/facilities", payload, headers
        )

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def get_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facility_allocations(
        self,
        facility_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/facilities/{facility_id}/allocations", headers=headers, params=params
        )

    def create_collateral_posting(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/facilities/{facility_id}/collateral-postings", payload, headers
        )

    def create_facility_status_change(
        self, facility_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/facilities/{facility_id}/status-changes", payload, headers
        )

    # ------------------------------------------------------------------
    # Banks
    # ------------------------------------------------------------------
    def create_bank(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/banks", payload, headers)

    def get_bank(self, bank_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/banks/{bank_id}", headers=headers)

    def list_banks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/banks", headers=headers, params=params)

    def patch_bank(self, bank_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/banks/{bank_id}", payload, headers)

    # ------------------------------------------------------------------
    # Beneficiaries
    # ------------------------------------------------------------------
    def create_beneficiary(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def list_beneficiaries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/beneficiaries", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Documentary credits
    # ------------------------------------------------------------------
    def create_credit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/credits", payload, headers)

    def get_credit(self, credit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/credits/{credit_id}", headers=headers)

    def list_credits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/credits", headers=headers, params=params)

    def create_documentary_requirement(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/credits/{credit_id}/documentary-requirements", payload, headers
        )

    def list_documentary_requirements(
        self,
        credit_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/credits/{credit_id}/documentary-requirements",
            headers=headers,
            params=params,
        )

    def submit_credit_for_approval(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/credits/{credit_id}/submit-for-approval", payload, headers
        )

    def approve_credit(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/credits/{credit_id}/approve", payload, headers)

    def issue_credit(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/credits/{credit_id}/issue", payload, headers)

    def cancel_credit(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/credits/{credit_id}/cancel", payload, headers)

    def create_confirmation_request(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/credits/{credit_id}/confirmation-requests", payload, headers
        )

    def create_confirmation_response(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/credits/{credit_id}/confirmation-responses", payload, headers
        )

    def list_credit_allocations(
        self,
        credit_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/credits/{credit_id}/allocations", headers=headers, params=params
        )

    def list_credit_screening_checks(
        self,
        credit_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/credits/{credit_id}/screening-checks", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Amendments
    # ------------------------------------------------------------------
    def create_amendment(
        self, credit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/credits/{credit_id}/amendments", payload, headers)

    def list_credit_amendments(
        self,
        credit_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/credits/{credit_id}/amendments", headers=headers, params=params
        )

    def issue_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/amendments/{amendment_id}/issue", payload, headers)

    def consent_amendment(
        self, amendment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/amendments/{amendment_id}/consent", payload, headers
        )

    # ------------------------------------------------------------------
    # Presentations
    # ------------------------------------------------------------------
    def create_presentation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/presentations", payload, headers)

    def get_presentation(self, presentation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/presentations/{presentation_id}", headers=headers)

    def list_presentations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/presentations", headers=headers, params=params)

    def create_presented_document(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/documents", payload, headers
        )

    def list_presented_documents(
        self,
        presentation_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/presentations/{presentation_id}/documents", headers=headers, params=params
        )

    def submit_presentation(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/submit", payload, headers
        )

    def create_presentation_screening(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/screenings", payload, headers
        )

    def list_presentation_screenings(
        self,
        presentation_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/presentations/{presentation_id}/screenings",
            headers=headers,
            params=params,
        )

    def review_screening_check(
        self, screening_check_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/screening-checks/{screening_check_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Discrepancies, waivers, refusal
    # ------------------------------------------------------------------
    def create_discrepancy(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/discrepancies", payload, headers
        )

    def list_discrepancies(
        self,
        presentation_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/presentations/{presentation_id}/discrepancies",
            headers=headers,
            params=params,
        )

    def conclude_examination(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/presentations/{presentation_id}/conclude-examination",
            payload,
            headers,
        )

    def create_waiver_request(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/waiver-requests", payload, headers
        )

    def list_waiver_requests(
        self,
        presentation_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/presentations/{presentation_id}/waiver-requests",
            headers=headers,
            params=params,
        )

    def respond_to_waiver_request(
        self, waiver_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/waiver-requests/{waiver_request_id}/respond", payload, headers
        )

    def refuse_presentation(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/refuse", payload, headers
        )

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------
    def create_settlement_claim(
        self, presentation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/presentations/{presentation_id}/settlement-claims", payload, headers
        )

    def list_settlement_claims(
        self,
        presentation_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/presentations/{presentation_id}/settlement-claims",
            headers=headers,
            params=params,
        )

    def settle_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/settlement-claims/{claim_id}/settle", payload, headers
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_expiry_sweep(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_ops/run-expiry-sweep", payload, headers)


api_client = ApiClient()
