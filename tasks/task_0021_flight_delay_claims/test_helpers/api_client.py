"""API client for the Flight Delay Claims API.

The API is mounted under `/insurers` per PRD §1 and §4.
Each method maps 1:1 to an endpoint defined in PRD §4.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ Insurer
    def create_insurer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/insurers", payload, headers)

    def get_insurer(self, insurer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurers/{insurer_id}", headers=headers)

    # ----------------------------------------------------- Test driver / clock
    def advance_clock(self, insurer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /insurers/{id}/_clock/advance — body has delta_ms or to_epoch_ms."""
        return self._request("POST", f"/insurers/{insurer_id}/_clock/advance", payload, headers)

    def run_sweep(self, insurer_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/insurers/{insurer_id}/_sweep/run", {}, headers)

    def check_invariant(self, insurer_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/insurers/{insurer_id}/_invariant/check", {}, headers)

    # ------------------------------------------------------------------- Policy
    def create_policy(self, insurer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/insurers/{insurer_id}/policies", payload, headers)

    def get_policy(self, insurer_id: str, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurers/{insurer_id}/policies/{policy_id}", headers=headers)

    def get_risk_view(self, insurer_id: str, policy_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/policies/{policy_id}/risk_view",
            headers=headers,
        )

    def suspend_policy(self, insurer_id: str, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/policies/{policy_id}/suspend",
            payload,
            headers,
        )

    def terminate_policy(self, insurer_id: str, policy_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/policies/{policy_id}/terminate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------- Ticket
    def create_ticket(self, insurer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/insurers/{insurer_id}/tickets", payload, headers)

    def get_ticket(self, insurer_id: str, ticket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurers/{insurer_id}/tickets/{ticket_id}", headers=headers)

    def change_ticket(self, insurer_id: str, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/tickets/{ticket_id}/change",
            payload,
            headers,
        )

    def confirm_ticket(self, insurer_id: str, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/tickets/{ticket_id}/confirm",
            {},
            headers,
        )

    def refund_ticket(self, insurer_id: str, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/tickets/{ticket_id}/refund",
            {},
            headers,
        )

    # ------------------------------------------------------------------- Flight
    def create_flight(self, insurer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/insurers/{insurer_id}/flights", payload, headers)

    def get_flight(self, insurer_id: str, flight_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/insurers/{insurer_id}/flights/{flight_id}", headers=headers)

    def list_flights(self, insurer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/flights",
            headers=headers,
            params=params,
        )

    def ingest_flight_event(self, insurer_id: str, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/flights/{flight_id}/events",
            payload,
            headers,
        )

    def archive_flight(self, insurer_id: str, flight_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/flights/{flight_id}/archive",
            {},
            headers,
        )

    # ------------------------------------------------------------ Manual review
    def get_manual_review(self, insurer_id: str, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/manual_review/{case_id}",
            headers=headers,
        )

    def resolve_bind(self, insurer_id: str, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/manual_review/{case_id}/resolve_bind",
            payload,
            headers,
        )

    def resolve_reject(self, insurer_id: str, case_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/manual_review/{case_id}/resolve_reject",
            {},
            headers,
        )

    # -------------------------------------------------------------------- Claim
    def create_claim(self, insurer_id: str, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/policies/{policy_id}/claims",
            payload,
            headers,
        )

    def get_claim(self, insurer_id: str, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/claims/{claim_id}",
            headers=headers,
        )

    def list_claims(self, insurer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/claims",
            headers=headers,
            params=params,
        )

    def submit_review(self, insurer_id: str, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/submit_review",
            payload,
            headers,
        )

    def return_to_match(self, insurer_id: str, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/return_to_match",
            {},
            headers,
        )

    def approve_claim(self, insurer_id: str, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/approve",
            payload,
            headers,
        )

    def reject_claim(self, insurer_id: str, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/reject",
            payload,
            headers,
        )

    def settle_claim(self, insurer_id: str, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/settle",
            {},
            headers,
        )

    def mark_exception(self, insurer_id: str, claim_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/mark_exception",
            payload or {},
            headers,
        )

    def reverse_claim(self, insurer_id: str, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/claims/{claim_id}/reverse",
            {},
            headers,
        )

    # ------------------------------------------------------------- Payout Batch
    def create_payout_batch(self, insurer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/payout_batches",
            payload,
            headers,
        )

    def get_payout_batch(self, insurer_id: str, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/payout_batches/{batch_id}",
            headers=headers,
        )

    def approve_batch(self, insurer_id: str, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/payout_batches/{batch_id}/approve",
            payload,
            headers,
        )

    def reject_batch(self, insurer_id: str, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/payout_batches/{batch_id}/reject",
            payload,
            headers,
        )

    def execute_batch(self, insurer_id: str, batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/payout_batches/{batch_id}/execute",
            payload,
            headers,
        )

    def retry_exceptions(self, insurer_id: str, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/payout_batches/{batch_id}/retry_exceptions",
            {},
            headers,
        )

    # ------------------------------------------------------- Audit / Outbox
    def list_audit_logs(self, insurer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/audit_logs",
            headers=headers,
            params=params,
        )

    def list_outbox_events(self, insurer_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/insurers/{insurer_id}/outbox_events",
            headers=headers,
            params=params,
        )

    def mark_outbox_delivered(self, insurer_id: str, event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/insurers/{insurer_id}/outbox_events/{event_id}/mark_delivered",
            {},
            headers,
        )


api_client = ApiClient()
