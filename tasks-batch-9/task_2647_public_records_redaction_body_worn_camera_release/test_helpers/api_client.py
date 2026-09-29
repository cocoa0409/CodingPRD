"""One method per endpoint of the records API.

Every method returns the raw requests.Response so tests can assert on status
codes as well as bodies. Read methods accept an optional `params` dict for
pagination and filtering.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/records"
CLOCK_PATH = "/_clock/set_current_utc"


class ApiClient(GenericApiClient):
    """Domain client for the Public Records Redaction & BWC Release API."""

    # ------------------------------------------------------------- clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------- staff
    def create_staff(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/staff", payload, headers)

    def get_staff(self, staff_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/staff/{staff_id}", None, headers)

    # --------------------------------------------------------- requesters
    def create_requester(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/requesters", payload, headers)

    def get_requester(self, requester_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/requesters/{requester_id}", None, headers)

    # -------------------------------------------------------- video assets
    def create_video_asset(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/video-assets", payload, headers)

    def get_video_asset(self, asset_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/video-assets/{asset_id}", None, headers)

    def list_video_assets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/video-assets", params, headers)

    def purge_video_asset(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/video-assets/{asset_id}/purge", payload, headers)

    # -------------------------------------------------- depicted individuals
    def create_depicted_individual(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/video-assets/{asset_id}/depicted-individuals", payload, headers
        )

    def list_depicted_individuals(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/video-assets/{asset_id}/depicted-individuals", params, headers
        )

    def get_depicted_individual(self, individual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/depicted-individuals/{individual_id}", None, headers)

    def issue_notification(
        self, individual_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/depicted-individuals/{individual_id}/notification", payload, headers
        )

    def record_objection(
        self, individual_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/depicted-individuals/{individual_id}/objection", payload, headers
        )

    # ------------------------------------------------------------ requests
    def create_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/requests", payload, headers)

    def get_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/requests/{request_id}", None, headers)

    def list_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/requests", params, headers)

    def clarify_scope(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/requests/{request_id}/scope-clarification", payload, headers
        )

    # -------------------------------------------------- responsive records
    def attach_responsive_record(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/requests/{request_id}/responsive-records", payload, headers
        )

    def rule_inclusion(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/responsive-records/{record_id}/inclusion", payload, headers
        )

    def get_responsive_record(self, record_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/responsive-records/{record_id}", None, headers)

    def list_responsive_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/responsive-records", params, headers)

    # --------------------------------------------------- exemption claims
    def assert_exemption_claim(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/responsive-records/{record_id}/exemption-claims", payload, headers
        )

    def adjudicate_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/exemption-claims/{claim_id}/adjudication", payload, headers
        )

    def get_exemption_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/exemption-claims/{claim_id}", None, headers)

    def list_exemption_claims(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/exemption-claims", params, headers)

    # ---------------------------------------------------- redaction tasks
    def create_redaction_task(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/responsive-records/{record_id}/redaction-tasks", payload, headers
        )

    def submit_qa(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/redaction-tasks/{task_id}/submit-qa", payload, headers)

    def record_qa_outcome(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/redaction-tasks/{task_id}/qa-outcome", payload, headers)

    def get_redaction_task(self, task_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/redaction-tasks/{task_id}", None, headers)

    def list_redaction_tasks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/redaction-tasks", params, headers)

    # ------------------------------------------------------- cost recovery
    def create_fee_estimate(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/requests/{request_id}/fee-estimates", payload, headers)

    def list_fee_estimates(
        self, request_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/requests/{request_id}/fee-estimates", params, headers)

    def post_payment(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/requests/{request_id}/payments", payload, headers)

    def issue_invoice(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/requests/{request_id}/invoice", payload, headers)

    def reverse_ledger_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/fee-ledger-entries/{entry_id}/reversal", payload, headers
        )

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/fee-ledger-entries/{entry_id}", None, headers)

    def list_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/fee-ledger-entries", params, headers)

    # ------------------------------------------------------------ endgame
    def create_release_package(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/requests/{request_id}/release-packages", payload, headers
        )

    def list_release_packages(
        self, request_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/requests/{request_id}/release-packages", params, headers)

    def issue_denial_letter(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/requests/{request_id}/denial-letters", payload, headers)

    def list_denial_letters(
        self, request_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/requests/{request_id}/denial-letters", params, headers)

    def get_denial_letter(self, letter_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/denial-letters/{letter_id}", None, headers)

    def file_appeal(
        self, letter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/denial-letters/{letter_id}/appeal", payload, headers)

    def decide_appeal(
        self, letter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/denial-letters/{letter_id}/appeal-decision", payload, headers
        )

    # --------------------------------------------------- litigation holds
    def create_litigation_hold(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/litigation-holds", payload, headers)

    def release_litigation_hold(
        self, hold_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/litigation-holds/{hold_id}/release", payload, headers
        )

    def get_litigation_hold(self, hold_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/litigation-holds/{hold_id}", None, headers)
