"""API client: one method per endpoint of the Police Evidence Room API (PRD section 4).

Every resource is addressed at the API root and path templates carry at most one
identifier, exactly as PRD section 2.4 requires.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    api_prefix = "/"

    # ─── Logical clock (PRD section 2.5) ─────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Property rooms ─────────────────────────────────────────────────────

    def create_property_room(self, payload, headers):
        return self._request("POST", "/property-rooms", payload, headers)

    def get_property_room(self, room_id: str, headers):
        return self._request("GET", f"/property-rooms/{room_id}", headers=headers)

    def daily_sweep(self, room_id: str, headers):
        return self._request("POST", f"/property-rooms/{room_id}/daily-sweep", {}, headers)

    # ─── Offense statutes ───────────────────────────────────────────────────

    def create_offense_statute(self, payload, headers):
        return self._request("POST", "/offense-statutes", payload, headers)

    def get_offense_statute(self, statute_id: str, headers):
        return self._request("GET", f"/offense-statutes/{statute_id}", headers=headers)

    # ─── Storage locations ──────────────────────────────────────────────────

    def create_storage_location(self, payload, headers):
        return self._request("POST", "/storage-locations", payload, headers)

    def get_storage_location(self, location_id: str, headers):
        return self._request("GET", f"/storage-locations/{location_id}", headers=headers)

    def list_storage_locations(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/storage-locations", headers=headers, params=params)

    # ─── Custodians ─────────────────────────────────────────────────────────

    def create_custodian(self, payload, headers):
        return self._request("POST", "/custodians", payload, headers)

    def get_custodian(self, custodian_id: str, headers):
        return self._request("GET", f"/custodians/{custodian_id}", headers=headers)

    def list_custodians(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/custodians", headers=headers, params=params)

    def suspend_custodian(self, custodian_id: str, payload, headers):
        return self._request(
            "POST", f"/custodians/{custodian_id}/suspend", payload, headers
        )

    # ─── Cases ──────────────────────────────────────────────────────────────

    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id: str, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def charge_case(self, case_id: str, headers):
        return self._request("POST", f"/cases/{case_id}/charge", {}, headers)

    def adjudicate_case(self, case_id: str, headers):
        return self._request("POST", f"/cases/{case_id}/adjudicate", {}, headers)

    def appeal_case(self, case_id: str, headers):
        return self._request("POST", f"/cases/{case_id}/appeal", {}, headers)

    def resolve_appeal_case(self, case_id: str, headers):
        return self._request("POST", f"/cases/{case_id}/resolve-appeal", {}, headers)

    def close_case(self, case_id: str, headers):
        return self._request("POST", f"/cases/{case_id}/close", {}, headers)

    # ─── Evidence items ─────────────────────────────────────────────────────

    def create_evidence_item(self, payload, headers):
        return self._request("POST", "/evidence-items", payload, headers)

    def get_evidence_item(self, item_id: str, headers):
        return self._request("GET", f"/evidence-items/{item_id}", headers=headers)

    def list_evidence_items(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/evidence-items", headers=headers, params=params)

    def assign_storage(self, item_id: str, payload, headers):
        return self._request(
            "POST", f"/evidence-items/{item_id}/storage-assignment", payload, headers
        )

    # ─── Retention determinations ───────────────────────────────────────────

    def create_retention_determination(self, payload, headers):
        return self._request("POST", "/retention-determinations", payload, headers)

    def get_retention_determination(self, determination_id: str, headers):
        return self._request(
            "GET", f"/retention-determinations/{determination_id}", headers=headers
        )

    def list_retention_determinations(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/retention-determinations", headers=headers, params=params
        )

    # ─── Custody transfers ──────────────────────────────────────────────────

    def create_custody_transfer(self, payload, headers):
        return self._request("POST", "/custody-transfers", payload, headers)

    def get_custody_transfer(self, transfer_id: str, headers):
        return self._request("GET", f"/custody-transfers/{transfer_id}", headers=headers)

    def list_custody_transfers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/custody-transfers", headers=headers, params=params)

    def release_transfer(self, transfer_id: str, payload, headers):
        return self._request(
            "POST", f"/custody-transfers/{transfer_id}/release", payload, headers
        )

    def return_transfer(self, transfer_id: str, payload, headers):
        return self._request(
            "POST", f"/custody-transfers/{transfer_id}/return", payload, headers
        )

    def report_transfer_lost(self, transfer_id: str, payload, headers):
        return self._request(
            "POST", f"/custody-transfers/{transfer_id}/report-lost", payload, headers
        )

    # ─── Disposition orders ─────────────────────────────────────────────────

    def create_disposition_order(self, payload, headers):
        return self._request("POST", "/disposition-orders", payload, headers)

    def get_disposition_order(self, order_id: str, headers):
        return self._request("GET", f"/disposition-orders/{order_id}", headers=headers)

    def list_disposition_orders(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/disposition-orders", headers=headers, params=params)

    def authorize_order(self, order_id: str, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/authorize", payload, headers
        )

    def reject_order(self, order_id: str, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/reject", payload, headers
        )

    def execute_order(self, order_id: str, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/execute", payload, headers
        )

    def settle_order(self, order_id: str, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/settle", payload, headers
        )

    def disburse_order(self, order_id: str, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/disburse", payload, headers
        )

    # ─── Owner claims ───────────────────────────────────────────────────────

    def create_owner_claim(self, payload, headers):
        return self._request("POST", "/owner-claims", payload, headers)

    def get_owner_claim(self, claim_id: str, headers):
        return self._request("GET", f"/owner-claims/{claim_id}", headers=headers)

    def list_owner_claims(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/owner-claims", headers=headers, params=params)

    def file_claim(self, claim_id: str, payload, headers):
        return self._request("POST", f"/owner-claims/{claim_id}/file", payload, headers)

    def verify_claim(self, claim_id: str, headers):
        return self._request("POST", f"/owner-claims/{claim_id}/verify", {}, headers)

    # ─── Audit sessions ─────────────────────────────────────────────────────

    def create_audit_session(self, payload, headers):
        return self._request("POST", "/audit-sessions", payload, headers)

    def get_audit_session(self, session_id: str, headers):
        return self._request("GET", f"/audit-sessions/{session_id}", headers=headers)

    def list_audit_sessions(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/audit-sessions", headers=headers, params=params)

    def start_audit_session(self, session_id: str, headers):
        return self._request("POST", f"/audit-sessions/{session_id}/start", {}, headers)

    def scan_audit_session(self, session_id: str, payload, headers):
        return self._request(
            "POST", f"/audit-sessions/{session_id}/scan", payload, headers
        )

    def reconcile_audit_session(self, session_id: str, headers):
        return self._request(
            "POST", f"/audit-sessions/{session_id}/reconcile", {}, headers
        )

    def close_audit_session(self, session_id: str, headers):
        return self._request("POST", f"/audit-sessions/{session_id}/close", {}, headers)

    # ─── Discrepancies ──────────────────────────────────────────────────────

    def get_discrepancy(self, discrepancy_id: str, headers):
        return self._request("GET", f"/discrepancies/{discrepancy_id}", headers=headers)

    def list_discrepancies(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/discrepancies", headers=headers, params=params)

    def investigate_discrepancy(self, discrepancy_id: str, headers):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/investigate", {}, headers
        )

    def resolve_discrepancy(self, discrepancy_id: str, payload, headers):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/resolve", payload, headers
        )

    # ─── Chain of custody entries ───────────────────────────────────────────

    def get_chain_event(self, event_id: str, headers):
        return self._request("GET", f"/chain-events/{event_id}", headers=headers)

    def list_chain_events(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/chain-events", headers=headers, params=params)


api_client = ApiClient()
