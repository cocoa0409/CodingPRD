"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Pricing Profiles (PRD §3.2)
    # =======================================================================
    def create_pricing_profile(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/pricing-profiles", payload, headers)

    def list_pricing_profiles(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/pricing-profiles",
                             headers=headers, params=params)

    # =======================================================================
    # Cabinets (PRD §3.1, §3.7)
    # =======================================================================
    def create_cabinet(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/cabinets", payload, headers)

    def get_cabinet(self, cabinet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cabinets/{cabinet_id}", headers=headers)

    def list_cabinets(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/cabinets",
                             headers=headers, params=params)

    def update_cabinet(self, cabinet_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("PATCH", f"/cabinets/{cabinet_id}",
                             payload, headers)

    def cabinet_heartbeat(self, cabinet_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/cabinets/{cabinet_id}/heartbeat",
                             {}, headers)

    def get_redistribution_suggestion(self, cabinet_id: str,
                                      headers: Dict[str, str],
                                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cabinets/{cabinet_id}/redistribution-suggestion",
            headers=headers, params=params,
        )

    # =======================================================================
    # Compartments (PRD §3.2)
    # =======================================================================
    def create_compartment(self, cabinet_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/cabinets/{cabinet_id}/compartments", payload, headers,
        )

    def get_compartment(self, cabinet_id: str, compartment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/cabinets/{cabinet_id}/compartments/{compartment_id}",
            headers=headers,
        )

    def list_compartments(self, cabinet_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cabinets/{cabinet_id}/compartments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Rentals (PRD §3.2, §3.3, §3.5, §3.6)
    # =======================================================================
    def create_rental(self, cabinet_id: str, compartment_id: str,
                      payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cabinets/{cabinet_id}/compartments/{compartment_id}/rentals",
            payload, headers,
        )

    def claim_holding(self, compartment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/compartments/{compartment_id}/claim-holding",
            {}, headers,
        )

    def get_rental(self, rental_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/rentals",
                             headers=headers, params=params)

    def renew_rental(self, rental_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", f"/rentals/{rental_id}/renew",
                             payload, headers)

    def return_rental(self, rental_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/rentals/{rental_id}/return",
                             payload, headers)

    def refund_rental(self, rental_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/rentals/{rental_id}/refund",
                             payload, headers)

    # =======================================================================
    # Insurance claims (PRD §3.9)
    # =======================================================================
    def create_insurance_claim(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurance-claims/{claim_id}",
                             headers=headers)

    def request_evidence(self, claim_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/request-evidence",
            payload or {}, headers,
        )

    def submit_evidence(self, claim_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/evidence",
            payload, headers,
        )

    def reject_evidence(self, claim_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/reject-evidence",
            payload, headers,
        )

    def approve_claim(self, claim_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/approve",
            payload, headers,
        )

    def deny_claim(self, claim_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/deny",
            payload, headers,
        )

    def pay_claim(self, claim_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/pay",
            payload or {}, headers,
        )

    # =======================================================================
    # Repair tickets (PRD §3.8)
    # =======================================================================
    def create_repair_ticket(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/repair-tickets", payload, headers)

    def get_repair_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/repair-tickets/{ticket_id}",
                             headers=headers)

    def dispatch_repair(self, ticket_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/repair-tickets/{ticket_id}/dispatch",
                             payload, headers)

    def repair_ticket(self, ticket_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/repair-tickets/{ticket_id}/repair",
                             payload, headers)

    def accept_repair(self, ticket_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/repair-tickets/{ticket_id}/accept",
                             payload or {}, headers)

    def reject_repair(self, ticket_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/repair-tickets/{ticket_id}/reject",
                             payload, headers)

    # =======================================================================
    # Revenue / audit (PRD §3.6, §2.12)
    # =======================================================================
    def list_revenue_records(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/revenue-records",
                             headers=headers, params=params)

    def get_revenue_summary(self, cabinet_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cabinets/{cabinet_id}/revenue-summary",
            headers=headers, params=params,
        )

    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-events",
                             headers=headers, params=params)

    # =======================================================================
    # Test-driver endpoints (PRD §2.11)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_run(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
