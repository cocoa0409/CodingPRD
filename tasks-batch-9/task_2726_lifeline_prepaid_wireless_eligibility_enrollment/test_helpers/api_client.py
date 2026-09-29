"""HTTP client with one method per Lifeline endpoint."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """One method per endpoint published under /lifeline."""

    # ------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ----------------------------------------------------------------- providers
    def create_provider(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/providers", payload, headers)

    def get_provider(
        self, provider_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/providers/{provider_id}", None, headers
        )

    def run_compliance_sweep(
        self, provider_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/providers/{provider_id}/compliance-sweep",
            {} if payload is None else payload,
            headers,
        )

    # ----------------------------------------------------------------- addresses
    def create_address(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/addresses", payload, headers)

    def get_address(
        self, address_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/addresses/{address_id}", None, headers
        )

    def resolve_duplicate_address(
        self, address_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/addresses/{address_id}/duplicate-resolution",
            payload,
            headers,
        )

    # --------------------------------------------------------------- subscribers
    def create_subscriber(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/subscribers", payload, headers)

    def get_subscriber(
        self, subscriber_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/subscribers/{subscriber_id}", None, headers
        )

    def list_subscribers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/subscribers", params, headers)

    # --------------------------------------------------------- eligibility checks
    def create_eligibility_check(
        self, subscriber_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/subscribers/{subscriber_id}/eligibility-checks",
            payload,
            headers,
        )

    def list_subscriber_eligibility_checks(
        self, subscriber_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/subscribers/{subscriber_id}/eligibility-checks",
            params,
            headers,
        )

    def get_eligibility_check(
        self, check_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/eligibility-checks/{check_id}", None, headers
        )

    def submit_verifier_result(
        self, check_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-checks/{check_id}/verifier-result",
            payload,
            headers,
        )

    def resubmit_documentation(
        self, check_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/eligibility-checks/{check_id}/resubmit-documentation",
            payload,
            headers,
        )

    # --------------------------------------------------------------- enrollments
    def create_enrollment(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/enrollments", payload, headers)

    def get_enrollment(
        self, enrollment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/enrollments/{enrollment_id}", None, headers
        )

    def list_enrollments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/enrollments", params, headers)

    def record_usage(
        self, enrollment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/enrollments/{enrollment_id}/usage",
            {} if payload is None else payload,
            headers,
        )

    def recertify(
        self, enrollment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/enrollments/{enrollment_id}/recertify",
            payload,
            headers,
        )

    def de_enroll(
        self, enrollment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/enrollments/{enrollment_id}/de-enroll",
            payload,
            headers,
        )

    def issue_device(
        self, enrollment_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/enrollments/{enrollment_id}/device-issuance",
            {} if payload is None else payload,
            headers,
        )

    # ------------------------------------------------------------------- devices
    def stock_device(
        self, provider_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/providers/{provider_id}/devices", payload, headers
        )

    def get_device(self, device_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/devices/{device_id}", None, headers)

    def list_devices(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/devices", params, headers)

    def return_device(
        self, device_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/devices/{device_id}/return", payload, headers
        )

    # ---------------------------------------------------------- service transfers
    def create_service_transfer(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/service-transfers", payload, headers)

    def get_service_transfer(
        self, transfer_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/service-transfers/{transfer_id}", None, headers
        )

    def list_service_transfers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/service-transfers", params, headers)

    def accept_service_transfer(
        self, transfer_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/service-transfers/{transfer_id}/accept",
            {} if payload is None else payload,
            headers,
        )

    def reject_service_transfer(
        self, transfer_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/service-transfers/{transfer_id}/reject",
            payload,
            headers,
        )

    # ------------------------------------------------------- reimbursement claims
    def create_claim(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/reimbursement-claims", payload, headers
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/reimbursement-claims/{claim_id}", None, headers
        )

    def list_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/reimbursement-claims", params, headers
        )

    def file_claim(
        self, claim_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/reimbursement-claims/{claim_id}/file",
            payload,
            headers,
        )

    def draw_audit_sample(
        self, claim_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/reimbursement-claims/{claim_id}/audit-draw",
            payload,
            headers,
        )

    # ------------------------------------------------------------- audit samples
    def get_audit_sample(
        self, sample_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/audit-samples/{sample_id}", None, headers
        )

    def list_audit_samples(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/audit-samples", params, headers)

    def adjudicate_audit_sample(
        self, sample_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-samples/{sample_id}/adjudicate",
            payload,
            headers,
        )

    # ---------------------------------------------------------- subscriber cases
    def create_subscriber_case(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/subscriber-cases", payload, headers)

    def get_subscriber_case(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/subscriber-cases/{case_id}", None, headers
        )

    def list_subscriber_cases(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/subscriber-cases", params, headers)

    def assign_case_review(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/subscriber-cases/{case_id}/assign-review",
            payload,
            headers,
        )

    def decide_case(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/subscriber-cases/{case_id}/decide",
            payload,
            headers,
        )
