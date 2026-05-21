"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. All endpoints are mounted under `/lease-agreements`
domain (PRD §1) — but individual paths vary per the PRD §4
endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Lessee — PRD §3.1, §3.8
    # ======================================================================
    def create_lessee(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/lessees", payload, headers)

    def get_lessee(self, lessee_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/lessees/{lessee_id}", headers=headers,
        )

    def suspend_lessee(self, lessee_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lessees/{lessee_id}/suspend",
            payload, headers,
        )

    def reinstate_lessee(self, lessee_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lessees/{lessee_id}/reinstate",
            payload, headers,
        )

    # ======================================================================
    # Vehicle — PRD §3.1, §3.4
    # ======================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}", headers=headers,
        )

    def create_telematics_event(self, vehicle_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/telematics-events",
            payload, headers,
        )

    # ======================================================================
    # LeaseAgreement — PRD §3.2, §3.8
    # ======================================================================
    def create_lease_agreement(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/lease-agreements", payload, headers,
        )

    def get_lease_agreement(self, lease_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/lease-agreements/{lease_id}", headers=headers,
        )

    def activate_lease(self, lease_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/activate",
            payload, headers,
        )

    def begin_return_lease(self, lease_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/begin-return",
            payload, headers,
        )

    def finalize_return_lease(self, lease_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/finalize-return",
            payload, headers,
        )

    # ======================================================================
    # FuelCard — PRD §3.3
    # ======================================================================
    def create_fuel_card(self, lease_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/fuel-cards",
            payload, headers,
        )

    def get_fuel_card(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fuel-cards/{card_id}", headers=headers,
        )

    # ======================================================================
    # FuelCardTransaction — PRD §3.3
    # ======================================================================
    def create_fuel_card_transaction(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/fuel-card-transactions", payload, headers,
        )

    def reverse_fuel_card_transaction(self, txn_id: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fuel-card-transactions/{txn_id}/reverse",
            payload, headers,
        )

    # ======================================================================
    # MaintenanceTicket — PRD §3.5
    # ======================================================================
    def create_maintenance_ticket(self, vehicle_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/maintenance-tickets",
            payload, headers,
        )

    def start_maintenance_ticket(self, ticket_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/start",
            payload, headers,
        )

    def close_maintenance_ticket(self, ticket_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/close",
            payload, headers,
        )

    def cancel_maintenance_ticket(self, ticket_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/cancel",
            payload, headers,
        )

    # ======================================================================
    # CollisionClaim — PRD §3.7
    # ======================================================================
    def create_collision_claim(self, lease_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/lease-agreements/{lease_id}/collision-claims",
            payload, headers,
        )

    def start_review_collision_claim(self, claim_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/collision-claims/{claim_id}/start-review",
            payload, headers,
        )

    def request_revision_collision_claim(self, claim_id: str,
                                         headers: Dict[str, str],
                                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/collision-claims/{claim_id}/request-revision",
            payload, headers,
        )

    def patch_collision_claim(self, claim_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/collision-claims/{claim_id}",
            payload, headers,
        )

    def approve_collision_claim(self, claim_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/collision-claims/{claim_id}/approve",
            payload, headers,
        )

    def reject_collision_claim(self, claim_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/collision-claims/{claim_id}/reject",
            payload, headers,
        )

    # ======================================================================
    # OverageSettlement — PRD §3.6
    # ======================================================================
    def create_overage_settlement(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/overage-settlements", payload, headers,
        )

    def get_overage_settlement(self, settlement_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/overage-settlements/{settlement_id}",
            headers=headers,
        )

    def finalize_overage_settlement(self, settlement_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/overage-settlements/{settlement_id}/finalize",
            payload, headers,
        )

    def mark_paid_overage_settlement(self, settlement_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/overage-settlements/{settlement_id}/mark-paid",
            payload, headers,
        )

    def dispute_overage_settlement(self, settlement_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/overage-settlements/{settlement_id}/dispute",
            payload, headers,
        )

    # ======================================================================
    # IFTAQuarter — PRD §3.9
    # ======================================================================
    def create_ifta_quarter(self, lessee_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/lessees/{lessee_id}/ifta-quarters",
            payload, headers,
        )

    def get_ifta_quarter(self, quarter_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/ifta-quarters/{quarter_id}", headers=headers,
        )

    def prepare_ifta_quarter(self, quarter_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ifta-quarters/{quarter_id}/prepare",
            payload, headers,
        )

    def file_ifta_quarter(self, quarter_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/ifta-quarters/{quarter_id}/file",
            payload, headers,
        )

    # ======================================================================
    # Logical clock — PRD §3.10
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
