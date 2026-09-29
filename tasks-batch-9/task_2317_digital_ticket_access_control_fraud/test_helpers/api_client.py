"""One method per endpoint of the Ticket Access Control API (PRD section 4).

Every method returns the raw response so a test can assert its status code and
its envelope. Paths are exactly those declared by the endpoint table.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every declared endpoint."""

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Events ───────────────────────────────────────────────────────────────

    def create_event(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/events", headers=headers, params=params)

    def advance_event_status(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/advance-status", payload, headers)

    def get_event_occupancy(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/events/{event_id}/occupancy", headers=headers)

    def list_audit_log_entries(
        self, event_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/events/{event_id}/audit-log-entries", headers=headers, params=params
        )

    # ─── Access zones ─────────────────────────────────────────────────────────

    def create_access_zone(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/access-zones", payload, headers)

    def get_access_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/access-zones/{zone_id}", headers=headers)

    def list_access_zones(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/access-zones", headers=headers, params=params)

    # ─── Gates ────────────────────────────────────────────────────────────────

    def create_gate(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/events/{event_id}/gates", payload, headers)

    def get_gate(self, gate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/gates/{gate_id}", headers=headers)

    def list_gates(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/gates", headers=headers, params=params)

    # ─── Patrons ──────────────────────────────────────────────────────────────

    def create_patron(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/patrons", payload, headers)

    def get_patron(self, patron_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    def list_patrons(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/patrons", headers=headers, params=params)

    def verify_patron_identity(
        self, patron_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/patrons/{patron_id}/verify-identity", payload, headers)

    # ─── Tickets ──────────────────────────────────────────────────────────────

    def create_ticket(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/tickets", headers=headers, params=params)

    def get_ticket_barcode(self, ticket_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/tickets/{ticket_id}/barcode", headers=headers)

    def bind_device(
        self, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/tickets/{ticket_id}/device-binding", payload, headers)

    def release_device_binding(
        self, ticket_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/tickets/{ticket_id}/device-binding/release", payload, headers
        )

    def void_ticket(
        self, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/tickets/{ticket_id}/void", payload, headers)

    # ─── Transfer requests ────────────────────────────────────────────────────

    def create_transfer_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/transfer-requests/{transfer_id}", headers=headers)

    def list_transfer_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def accept_transfer_request(
        self, transfer_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/transfer-requests/{transfer_id}/accept", payload, headers)

    def decline_transfer_request(
        self, transfer_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/transfer-requests/{transfer_id}/decline", payload, headers)

    # ─── Resale listings ──────────────────────────────────────────────────────

    def create_resale_listing(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/resale-listings", payload, headers)

    def get_resale_listing(self, listing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/resale-listings/{listing_id}", headers=headers)

    def list_resale_listings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/resale-listings", headers=headers, params=params)

    def purchase_resale_listing(
        self, listing_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/resale-listings/{listing_id}/purchase", payload, headers)

    def delist_resale_listing(
        self, listing_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/resale-listings/{listing_id}/delist", payload, headers)

    # ─── Credential requests ──────────────────────────────────────────────────

    def create_credential_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/credential-requests", payload, headers)

    def get_credential_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/credential-requests/{request_id}", headers=headers)

    def list_credential_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/credential-requests", headers=headers, params=params)

    def submit_credential_request(
        self, request_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/credential-requests/{request_id}/submit", payload, headers)

    def request_changes_credential_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/credential-requests/{request_id}/request-changes", payload, headers
        )

    def approve_credential_request(
        self, request_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/credential-requests/{request_id}/approve", payload, headers)

    def reject_credential_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/credential-requests/{request_id}/reject", payload, headers)

    # ─── Scan sessions and scanning ───────────────────────────────────────────

    def create_scan_session(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/scan-sessions", payload, headers)

    def get_scan_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/scan-sessions/{session_id}", headers=headers)

    def list_scan_sessions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/scan-sessions", headers=headers, params=params)

    def create_scan_event(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/scan-sessions/{session_id}/scan-events", payload, headers)

    def upload_offline_batch(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/scan-sessions/{session_id}/offline-batch", payload, headers)

    def close_scan_session(
        self, session_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/scan-sessions/{session_id}/close", payload, headers)

    # ─── Scan events ──────────────────────────────────────────────────────────

    def get_scan_event(self, scan_event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/scan-events/{scan_event_id}", headers=headers)

    def list_scan_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/scan-events", headers=headers, params=params)

    # ─── Denied-entry incidents ───────────────────────────────────────────────

    def get_denied_entry_incident(
        self, incident_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/denied-entry-incidents/{incident_id}", headers=headers)

    def list_denied_entry_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/denied-entry-incidents", headers=headers, params=params)

    def start_incident_review(
        self, incident_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/denied-entry-incidents/{incident_id}/start-review", payload, headers
        )

    def remediate_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/denied-entry-incidents/{incident_id}/remediate", payload, headers
        )

    def dismiss_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/denied-entry-incidents/{incident_id}/dismiss", payload, headers
        )

    # ─── Reconciliation reports ───────────────────────────────────────────────

    def create_reconciliation_report(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/events/{event_id}/reconciliation-reports", payload, headers
        )

    def get_reconciliation_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reconciliation-reports/{report_id}", headers=headers)

    def list_reconciliation_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/reconciliation-reports", headers=headers, params=params)

    def finalize_reconciliation_report(
        self, report_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/reconciliation-reports/{report_id}/finalize", payload, headers
        )

    def reopen_reconciliation_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/reconciliation-reports/{report_id}/reopen", payload, headers)
