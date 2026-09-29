"""
Typed endpoint methods for the Vehicle Safety Recall Campaigns API.

One method per row of the PRD's endpoint table. The HTTP plumbing
(`_request`) is inherited from the framework's GenericApiClient.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Domain client: one method per PRD endpoint."""

    # ─── Recall campaigns ─────────────────────────────

    def create_campaign(self, payload: Dict[str, Any], headers: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", "/recall-campaigns", payload, headers)

    def list_campaigns(self, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/recall-campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id: str, headers: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/recall-campaigns/{campaign_id}", headers=headers)

    def record_defect_determination(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/defect-determination", payload, headers
        )

    def issue_interim_advisory(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/interim-advisory", payload, headers
        )

    def release_remedy(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/remedy-releases", payload, headers
        )

    def close_campaign(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/recall-campaigns/{campaign_id}/close", payload, headers)

    def get_completion_metrics(self, campaign_id: str, headers: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"/recall-campaigns/{campaign_id}/completion-metrics", headers=headers
        )

    # ─── Population rules and runs ────────────────────

    def create_population_rule(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/population-rules", payload, headers
        )

    def list_population_rules(
        self, campaign_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/recall-campaigns/{campaign_id}/population-rules", headers=headers, params=params
        )

    def run_population(
        self, campaign_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/population-runs", payload or {}, headers
        )

    # ─── Build records ────────────────────────────────

    def create_vehicle(self, payload: Dict[str, Any], headers: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def update_vehicle(
        self, vehicle_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/vehicles/{vehicle_id}", payload, headers)

    # ─── Affected-vehicle rows ────────────────────────

    def list_affected_vehicles(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/affected-vehicles", headers=headers, params=params)

    def get_affected_vehicle(
        self, affected_vehicle_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/affected-vehicles/{affected_vehicle_id}", headers=headers)

    def schedule_repair(
        self, affected_vehicle_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/affected-vehicles/{affected_vehicle_id}/schedule", payload, headers
        )

    def create_outreach_attempt(
        self, affected_vehicle_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/affected-vehicles/{affected_vehicle_id}/outreach-attempts", payload, headers
        )

    def list_outreach_attempts(
        self, affected_vehicle_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/affected-vehicles/{affected_vehicle_id}/outreach-attempts",
            headers=headers,
            params=params,
        )

    # ─── Notification waves ───────────────────────────

    def create_notification_wave(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/notification-waves", payload, headers
        )

    def list_notification_waves(
        self, campaign_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/recall-campaigns/{campaign_id}/notification-waves",
            headers=headers,
            params=params,
        )

    def release_wave(
        self, wave_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/notification-waves/{wave_id}/release", payload or {}, headers)

    def mail_wave(
        self, wave_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/notification-waves/{wave_id}/mail", payload or {}, headers)

    def cancel_wave(
        self, wave_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/notification-waves/{wave_id}/cancel", payload or {}, headers)

    # ─── Dealers ──────────────────────────────────────

    def create_dealer(self, payload: Dict[str, Any], headers: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", "/dealers", payload, headers)

    def get_dealer(self, dealer_id: str, headers: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def suspend_dealer(
        self, dealer_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/dealers/{dealer_id}/suspend", payload, headers)

    # ─── Remedy parts and labor operations ────────────

    def create_remedy_part(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/remedy-parts", payload, headers
        )

    def list_remedy_parts(
        self, campaign_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/recall-campaigns/{campaign_id}/remedy-parts", headers=headers, params=params
        )

    def create_labor_operation(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/labor-operations", payload, headers
        )

    def list_labor_operations(
        self, campaign_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/recall-campaigns/{campaign_id}/labor-operations",
            headers=headers,
            params=params,
        )

    # ─── Parts allocations ────────────────────────────

    def create_parts_allocation(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", "/parts-allocations", payload, headers)

    def list_parts_allocations(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/parts-allocations", headers=headers, params=params)

    def get_parts_allocation(
        self, allocation_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/parts-allocations/{allocation_id}", headers=headers)

    def revoke_parts_allocation(
        self, allocation_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/parts-allocations/{allocation_id}/revoke", payload or {}, headers
        )

    # ─── Repair claims ────────────────────────────────

    def create_repair_claim(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", "/repair-claims", payload, headers)

    def list_repair_claims(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/repair-claims", headers=headers, params=params)

    def get_repair_claim(self, claim_id: str, headers: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/repair-claims/{claim_id}", headers=headers)

    def audit_repair_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/repair-claims/{claim_id}/audit", payload, headers)

    def reverse_repair_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/repair-claims/{claim_id}/reverse", payload, headers)

    # ─── Owner reimbursements ─────────────────────────

    def create_owner_reimbursement(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", "/owner-reimbursements", payload, headers)

    def list_owner_reimbursements(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/owner-reimbursements", headers=headers, params=params)

    def get_owner_reimbursement(
        self, reimbursement_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/owner-reimbursements/{reimbursement_id}", headers=headers)

    def request_reimbursement_documents(
        self, reimbursement_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/owner-reimbursements/{reimbursement_id}/request-documents", payload, headers
        )

    def resubmit_owner_reimbursement(
        self, reimbursement_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/owner-reimbursements/{reimbursement_id}/resubmit", payload, headers
        )

    def adjudicate_owner_reimbursement(
        self, reimbursement_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/owner-reimbursements/{reimbursement_id}/adjudicate", payload, headers
        )

    # ─── Regulatory filings ───────────────────────────

    def create_filing(
        self, campaign_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/recall-campaigns/{campaign_id}/filings", payload, headers)

    def list_filings(
        self, campaign_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/recall-campaigns/{campaign_id}/filings", headers=headers, params=params
        )

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


# Module-level singleton reused by conftest's session-scoped `api` fixture.
api_client = ApiClient()
