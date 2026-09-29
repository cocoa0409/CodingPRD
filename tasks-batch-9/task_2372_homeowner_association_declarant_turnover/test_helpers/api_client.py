"""Endpoint client for the HOA Declarant Turnover API.

One method per row of the PRD's endpoint table, so tests never build URLs by
hand. Every method returns the raw ``requests.Response`` so the caller decides
whether to validate a success or an error.
"""

from typing import Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH
from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Typed access to every endpoint the PRD declares."""

    # ─── The logical clock (§2.5) ──────────────────────

    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers
        )

    # ─── Associations (§3.1) ───────────────────────────

    def create_association(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/associations", payload, headers)

    def get_association(
        self, association_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/associations/{association_id}", None, headers
        )

    def list_lots(
        self,
        association_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/associations/{association_id}/lots",
            None,
            headers,
            params=params,
        )

    def list_components(
        self,
        association_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/associations/{association_id}/components",
            None,
            headers,
            params=params,
        )

    def list_turnover_cases(
        self,
        association_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/associations/{association_id}/turnover-cases",
            None,
            headers,
            params=params,
        )

    def list_reserve_studies(
        self,
        association_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/associations/{association_id}/reserve-studies",
            None,
            headers,
            params=params,
        )

    def list_audit_engagements(
        self,
        association_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/associations/{association_id}/audit-engagements",
            None,
            headers,
            params=params,
        )

    def list_assessment_schedules(
        self,
        association_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/associations/{association_id}/assessment-schedules",
            None,
            headers,
            params=params,
        )

    def repose_sweep(
        self,
        association_id: str,
        headers: Headers,
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/associations/{association_id}/repose-sweep",
            payload if payload is not None else {},
            headers,
        )

    # ─── Lots (§3.1) ───────────────────────────────────

    def create_lot(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/lots", payload, headers)

    def close_lot_sale(
        self, lot_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/lots/{lot_id}/close-sale", payload, headers
        )

    # ─── Common area components (§3.2) ─────────────────

    def create_component(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/components", payload, headers)

    def record_milestone(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/components/{component_id}/milestones",
            payload,
            headers,
        )

    # ─── Turnover cases (§3.1, §3.3, §3.4, §3.9) ───────

    def create_turnover_case(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/turnover-cases", payload, headers)

    def get_turnover_case(
        self, case_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/turnover-cases/{case_id}", None, headers
        )

    def certify_trigger(
        self, case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/turnover-cases/{case_id}/certify-trigger",
            payload,
            headers,
        )

    def advance_case(
        self, case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/turnover-cases/{case_id}/advance",
            payload,
            headers,
        )

    def list_records_items(
        self,
        case_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/turnover-cases/{case_id}/records-items",
            None,
            headers,
            params=params,
        )

    def list_directors(
        self,
        case_id: str,
        headers: Headers,
        params: Optional[dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/turnover-cases/{case_id}/directors",
            None,
            headers,
            params=params,
        )

    # ─── Directors (§3.4) ──────────────────────────────

    def seat_director(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/directors", payload, headers)

    def rescind_director(
        self,
        director_id: str,
        headers: Headers,
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/directors/{director_id}/rescind",
            payload if payload is not None else {},
            headers,
        )

    # ─── Records transfer items (§3.5) ─────────────────

    def create_records_item(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/records-items", payload, headers)

    def records_item_transition(
        self, item_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/records-items/{item_id}/transitions",
            payload,
            headers,
        )

    # ─── Subsidy ledger (§3.6) ─────────────────────────

    def create_subsidy_entry(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/subsidy-entries", payload, headers)

    def list_subsidy_entries(
        self, headers: Headers, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/subsidy-entries", None, headers, params=params
        )

    def get_subsidy_entry(
        self, entry_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/subsidy-entries/{entry_id}", None, headers
        )

    def reverse_subsidy_entry(
        self, entry_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/subsidy-entries/{entry_id}/reverse",
            payload,
            headers,
        )

    # ─── Audit engagements (§3.6) ──────────────────────

    def create_audit_engagement(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/audit-engagements", payload, headers
        )

    def issue_audit_engagement(
        self,
        engagement_id: str,
        headers: Headers,
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-engagements/{engagement_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    # ─── Reserve studies (§3.7) ────────────────────────

    def create_reserve_study(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/reserve-studies", payload, headers)

    def reserve_study_action(
        self, study_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/reserve-studies/{study_id}/actions",
            payload,
            headers,
        )

    # ─── Defect claims (§3.8) ──────────────────────────

    def create_defect_claim(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/defect-claims", payload, headers)

    def list_defect_claims(
        self, headers: Headers, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/defect-claims", None, headers, params=params
        )

    def get_defect_claim(
        self, claim_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/defect-claims/{claim_id}", None, headers
        )

    def defect_claim_action(
        self, claim_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/defect-claims/{claim_id}/actions",
            payload,
            headers,
        )

    # ─── Vendor contracts (§3.5) ───────────────────────

    def create_vendor_contract(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/vendor-contracts", payload, headers
        )

    def list_vendor_contracts(
        self, headers: Headers, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vendor-contracts", None, headers, params=params
        )

    def get_vendor_contract(
        self, contract_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vendor-contracts/{contract_id}", None, headers
        )

    def vendor_contract_action(
        self, contract_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/vendor-contracts/{contract_id}/actions",
            payload,
            headers,
        )

    # ─── Assessment schedules (§3.9) ───────────────────

    def create_assessment_schedule(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/assessment-schedules", payload, headers
        )

    def adopt_assessment_schedule(
        self,
        schedule_id: str,
        headers: Headers,
        payload: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/assessment-schedules/{schedule_id}/adopt",
            payload if payload is not None else {},
            headers,
        )
