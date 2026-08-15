"""API client: one method per endpoint defined in PRD §4."""
import time
from typing import Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sublease-admin"


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Retry transient transport resets caused by per-test-server restarts.

        The runner SIGKILLs the API server between tests and respawns it on the
        same port; under parallel multi-round load a fresh connection can be
        reset while the previous server instance is dying. Those failures
        surface as requests.ConnectionError before the request reaches the new
        server (the server's access log shows no arrival), so retrying cannot
        double-apply a mutation or mask an application-level error — a
        genuinely crashed server still fails the test after retries exhaust.
        """
        attempts = 5
        for attempt in range(attempts):
            try:
                return super()._request(method, path, payload, headers, params)
            except requests.ConnectionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.15 * (attempt + 1))

    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- parties ---
    def create_party(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/parties", payload, headers)

    def list_parties(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/parties", headers=headers, params=params)

    def get_party(self, party_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/parties/{party_id}", headers=headers)

    # --- buildings ---
    def create_building(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/buildings", payload, headers)

    def get_building(self, building_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/buildings/{building_id}", headers=headers)

    def list_building_leases(self, building_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/leases", headers=headers,
        )

    # --- leases ---
    def create_lease(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/leases", payload, headers)

    def get_lease(self, lease_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/leases/{lease_id}", headers=headers)

    def list_leases(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/leases", headers=headers, params=params)

    def list_lease_transfer_requests(self, lease_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/leases/{lease_id}/transfer-requests", headers=headers,
        )

    def list_lease_settlements(self, lease_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/leases/{lease_id}/settlements", headers=headers,
        )

    def list_lease_demised_areas(self, lease_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/leases/{lease_id}/demised-areas", headers=headers,
        )

    # --- transfer requests ---
    def create_transfer_request(self, lease_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/transfer-requests", payload, headers,
        )

    def get_transfer_request(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}", headers=headers,
        )

    def list_transfer_requests(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests", headers=headers, params=params,
        )

    def submit_transfer_request(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/submit", {}, headers,
        )

    def withdraw_transfer_request(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/withdraw", {}, headers,
        )

    def remind_transfer_request(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/remind", {}, headers,
        )

    def document_transfer_request(self, transfer_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/document", payload, headers,
        )

    def get_transfer_consent_review(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}/consent-review",
            headers=headers,
        )

    def get_transfer_credit_review(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}/credit-review",
            headers=headers,
        )

    def list_transfer_demised_areas(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}/demised-areas",
            headers=headers,
        )

    def get_transfer_recognition_agreement(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}/recognition-agreement",
            headers=headers,
        )

    def list_transfer_restoration_obligations(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}/restoration-obligations",
            headers=headers,
        )

    def list_transfer_settlements(self, transfer_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_id}/settlements",
            headers=headers,
        )

    # --- demised areas ---
    def create_demised_area(self, transfer_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{transfer_id}/demised-areas",
            payload, headers,
        )

    def get_demised_area(self, area_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/demised-areas/{area_id}", headers=headers)

    def list_demised_areas(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/demised-areas", headers=headers, params=params)

    def certify_demised_area(self, area_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/demised-areas/{area_id}/certify", {}, headers,
        )

    # --- consent reviews / conditions ---
    def get_consent_review(self, review_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/consent-reviews/{review_id}", headers=headers,
        )

    def list_consent_reviews(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/consent-reviews", headers=headers, params=params,
        )

    def decide_consent_review(self, review_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/consent-reviews/{review_id}/decide", payload, headers,
        )

    def rescind_consent_review(self, review_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/consent-reviews/{review_id}/rescind", {}, headers,
        )

    def list_consent_conditions(self, review_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/consent-reviews/{review_id}/conditions", headers=headers,
        )

    def respond_consent_condition(self, condition_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/consent-conditions/{condition_id}/respond",
            payload, headers,
        )

    def get_consent_condition(self, condition_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/consent-conditions/{condition_id}", headers=headers,
        )

    # --- credit reviews ---
    def get_credit_review(self, review_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/credit-reviews/{review_id}", headers=headers,
        )

    def attest_credit_review(self, review_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/credit-reviews/{review_id}/attest", payload, headers,
        )

    # --- sublease agreements (instruments) ---
    def get_sublease_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/sublease-agreements/{agreement_id}", headers=headers,
        )

    def list_sublease_agreements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/sublease-agreements", headers=headers, params=params,
        )

    def terminate_sublease_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/sublease-agreements/{agreement_id}/terminate",
            {}, headers,
        )

    # --- recognition agreements ---
    def get_recognition_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/recognition-agreements/{agreement_id}", headers=headers,
        )

    def list_recognition_agreements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/recognition-agreements", headers=headers, params=params,
        )

    def sign_recognition_agreement(self, agreement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/recognition-agreements/{agreement_id}/sign",
            payload, headers,
        )

    # --- settlements ---
    def create_settlement(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/settlements", payload, headers)

    def get_settlement(self, settlement_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/finalize", {}, headers,
        )

    def void_settlement(self, settlement_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/settlements/{settlement_id}/void", {}, headers,
        )

    # --- restoration obligations ---
    def get_restoration_obligation(self, obligation_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/restoration-obligations/{obligation_id}", headers=headers,
        )

    def complete_restoration_obligation(self, obligation_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/restoration-obligations/{obligation_id}/complete",
            {}, headers,
        )

    def waive_restoration_obligation(self, obligation_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/restoration-obligations/{obligation_id}/waive",
            {}, headers,
        )


api_client = ApiClient()
