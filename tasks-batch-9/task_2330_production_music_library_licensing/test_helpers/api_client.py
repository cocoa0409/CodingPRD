"""Typed client with exactly one method per endpoint in the PRD routing table.

Every method returns the raw `requests.Response` so tests can assert status
codes, and every method takes `headers` explicitly because the acting role is
part of the contract under test.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

JsonDict = Dict[str, Any]
Headers = Optional[Dict[str, str]]


class MusicLibraryApiClient(GenericApiClient):
    """One method per endpoint of the production music library API."""

    # ------------------------------------------------------------------
    # Logical clock (the one endpoint mounted outside /music-library)
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # Composers
    # ------------------------------------------------------------------

    def create_composer(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/composers", payload, headers)

    def get_composer(self, composer_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/composers/{composer_id}", None, headers)

    def get_royalty_preview(
        self, composer_id: str, params: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/composers/{composer_id}/royalty-preview", params, headers
        )

    # ------------------------------------------------------------------
    # Composer agreements
    # ------------------------------------------------------------------

    def create_composer_agreement(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/composer-agreements", payload, headers)

    def get_composer_agreement(
        self, agreement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/composer-agreements/{agreement_id}", None, headers
        )

    def list_composer_agreements(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/composer-agreements", params or {}, headers)

    def submit_agreement_for_signature(
        self, agreement_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/composer-agreements/{agreement_id}/submit-for-signature",
            payload or {},
            headers,
        )

    def sign_agreement(
        self, agreement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/composer-agreements/{agreement_id}/sign", payload, headers
        )

    def create_amendment(
        self, agreement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/composer-agreements/{agreement_id}/amendments", payload, headers
        )

    def decide_amendment(
        self, agreement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/composer-agreements/{agreement_id}/amendment-decision",
            payload,
            headers,
        )

    def terminate_agreement(
        self, agreement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/composer-agreements/{agreement_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Compositions
    # ------------------------------------------------------------------

    def create_composition(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/compositions", payload, headers)

    def get_composition(self, composition_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/compositions/{composition_id}", None, headers)

    def list_compositions(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/compositions", params or {}, headers)

    def search_compositions(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/compositions/search", params or {}, headers)

    def update_composition(
        self, composition_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/compositions/{composition_id}", payload, headers
        )

    def catalog_composition(
        self, composition_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/compositions/{composition_id}/catalog", payload or {}, headers
        )

    def retire_composition(
        self, composition_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/compositions/{composition_id}/retire", payload, headers
        )

    # ------------------------------------------------------------------
    # Search profile singleton
    # ------------------------------------------------------------------

    def put_search_profile(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("PUT", f"{API_PREFIX}/search-profile", payload, headers)

    def get_search_profile(self, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/search-profile", None, headers)

    # ------------------------------------------------------------------
    # Rate card
    # ------------------------------------------------------------------

    def create_license_tier(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/license-tiers", payload, headers)

    def get_license_tier(self, tier_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/license-tiers/{tier_id}", None, headers)

    # ------------------------------------------------------------------
    # Licensees
    # ------------------------------------------------------------------

    def create_licensee(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licensees", payload, headers)

    def get_licensee(self, licensee_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licensees/{licensee_id}", None, headers)

    # ------------------------------------------------------------------
    # Sync requests
    # ------------------------------------------------------------------

    def create_sync_request(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sync-requests", payload, headers)

    def get_sync_request(self, sync_request_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sync-requests/{sync_request_id}", None, headers)

    def list_sync_requests(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sync-requests", params or {}, headers)

    def review_sync_request(
        self, sync_request_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sync-requests/{sync_request_id}/review", payload or {}, headers
        )

    def quote_sync_request(
        self, sync_request_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sync-requests/{sync_request_id}/quote", payload or {}, headers
        )

    def request_sync_revision(
        self, sync_request_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sync-requests/{sync_request_id}/request-revision",
            payload,
            headers,
        )

    def accept_sync_request(
        self, sync_request_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sync-requests/{sync_request_id}/accept", payload or {}, headers
        )

    def decline_sync_request(
        self, sync_request_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sync-requests/{sync_request_id}/decline", payload, headers
        )

    def start_sync_request_edit(
        self, sync_request_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sync-requests/{sync_request_id}/start-edit",
            payload or {},
            headers,
        )

    def deliver_sync_request(
        self, sync_request_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sync-requests/{sync_request_id}/deliver", payload, headers
        )

    # ------------------------------------------------------------------
    # Licences
    # ------------------------------------------------------------------

    def create_license(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/licenses", payload, headers)

    def get_license(self, license_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", None, headers)

    def list_licenses(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses", params or {}, headers)

    def activate_license(
        self, license_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/activate", payload or {}, headers
        )

    def revoke_license(
        self, license_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/revoke", payload, headers
        )

    def record_license_payment(
        self, license_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/record-payment", payload, headers
        )

    # ------------------------------------------------------------------
    # Blanket agreements
    # ------------------------------------------------------------------

    def create_blanket_agreement(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/blanket-agreements", payload, headers)

    def get_blanket_agreement(
        self, blanket_agreement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/blanket-agreements/{blanket_agreement_id}", None, headers
        )

    def list_blanket_agreements(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/blanket-agreements", params or {}, headers)

    def activate_blanket_agreement(
        self,
        blanket_agreement_id: str,
        payload: Optional[JsonDict] = None,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/blanket-agreements/{blanket_agreement_id}/activate",
            payload or {},
            headers,
        )

    def terminate_blanket_agreement(
        self, blanket_agreement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/blanket-agreements/{blanket_agreement_id}/terminate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Usage reports
    # ------------------------------------------------------------------

    def create_usage_report(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/usage-reports", payload, headers)

    def get_usage_report(self, usage_report_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/usage-reports/{usage_report_id}", None, headers)

    def list_usage_reports(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/usage-reports", params or {}, headers)

    def submit_usage_report(
        self, usage_report_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/usage-reports/{usage_report_id}/submit", payload or {}, headers
        )

    def accept_usage_report(
        self, usage_report_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/usage-reports/{usage_report_id}/accept", payload or {}, headers
        )

    def reject_usage_report(
        self, usage_report_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/usage-reports/{usage_report_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Cue sheets
    # ------------------------------------------------------------------

    def create_cue_sheet(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/cue-sheets", payload, headers)

    def get_cue_sheet(self, cue_sheet_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cue-sheets/{cue_sheet_id}", None, headers)

    def list_cue_sheets(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cue-sheets", params or {}, headers)

    def register_cue_sheet(
        self, cue_sheet_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cue-sheets/{cue_sheet_id}/register", payload, headers
        )

    def record_society_decision(
        self, cue_sheet_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cue-sheets/{cue_sheet_id}/society-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Fingerprint matches
    # ------------------------------------------------------------------

    def create_fingerprint_match(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fingerprint-matches", payload, headers)

    def get_fingerprint_match(self, match_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fingerprint-matches/{match_id}", None, headers)

    def list_fingerprint_matches(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fingerprint-matches", params or {}, headers)

    # ------------------------------------------------------------------
    # Infringement claims
    # ------------------------------------------------------------------

    def create_infringement_claim(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/infringement-claims", payload, headers)

    def get_infringement_claim(self, claim_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/infringement-claims/{claim_id}", None, headers)

    def list_infringement_claims(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/infringement-claims", params or {}, headers)

    def notice_claim(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/infringement-claims/{claim_id}/notice", payload, headers
        )

    def dispute_claim(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/infringement-claims/{claim_id}/dispute", payload, headers
        )

    def settle_claim(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/infringement-claims/{claim_id}/settle", payload, headers
        )

    def escalate_claim(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/infringement-claims/{claim_id}/escalate", payload, headers
        )

    # ------------------------------------------------------------------
    # Royalty statements
    # ------------------------------------------------------------------

    def create_royalty_statement(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/royalty-statements", payload, headers)

    def get_royalty_statement(
        self, statement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/royalty-statements/{statement_id}", None, headers
        )

    def list_royalty_statements(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/royalty-statements", params or {}, headers)

    def finalize_royalty_statement(
        self, statement_id: str, payload: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/royalty-statements/{statement_id}/finalize",
            payload or {},
            headers,
        )

    def pay_royalty_statement(
        self, statement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/royalty-statements/{statement_id}/pay", payload, headers
        )

    # ------------------------------------------------------------------
    # Royalty ledger entries
    # ------------------------------------------------------------------

    def create_royalty_ledger_entry(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/royalty-ledger-entries", payload, headers)

    def get_royalty_ledger_entry(
        self, entry_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/royalty-ledger-entries/{entry_id}", None, headers
        )

    def list_royalty_ledger_entries(
        self, params: Optional[JsonDict] = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/royalty-ledger-entries", params or {}, headers)
