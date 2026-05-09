"""API client: one method per endpoint defined by the community property PRD.

Endpoint paths follow the PRD's `/communities` mount-point — every endpoint listed
in PRD §4 is mounted under this prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


_PREFIX = "/communities"


class ApiClient(GenericApiClient):
    """Concrete client. Every method returns the raw requests.Response."""

    # ──────────────── Owners ────────────────

    def create_owner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/owners", payload, headers)

    def list_owners(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{_PREFIX}/owners", headers=headers, params=params)

    def get_owner(self, owner_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/owners/{owner_id}", headers=headers)

    # ──────────────── Properties ────────────────

    def create_property(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/properties", payload, headers)

    def get_property(self, property_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/properties/{property_id}", headers=headers)

    # ──────────────── Residents ────────────────

    def create_resident(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/residents", payload, headers)

    def move_in_resident(self, resident_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/residents/{resident_id}/move-in", headers=headers)

    def move_out_resident(self, resident_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/residents/{resident_id}/move-out", headers=headers)

    # ──────────────── Work Orders ────────────────

    def create_work_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders", payload, headers)

    def dispatch_work_order(self, wo_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/dispatch", payload, headers)

    def start_work_order(self, wo_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/start", headers=headers)

    def reject_work_order(self, wo_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/reject", payload, headers)

    def resolve_work_order(self, wo_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/resolve", headers=headers)

    def confirm_work_order(self, wo_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/confirm", payload, headers)

    def reopen_work_order(self, wo_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/reopen", headers=headers)

    def cancel_work_order(self, wo_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/work-orders/{wo_id}/cancel", headers=headers)

    # ──────────────── Fee billing rules ────────────────

    def create_fee_billing_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/fee-billing-rules", payload, headers)

    def patch_fee_billing_rule(self, rule_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"{_PREFIX}/fee-billing-rules/{rule_id}", payload, headers)

    # ──────────────── Fee bills ────────────────

    def issue_fee_bills(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/fee-bills/issue", payload, headers)

    def get_fee_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/fee-bills/{bill_id}", headers=headers)

    def list_fee_bills(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{_PREFIX}/fee-bills", headers=headers, params=params)

    def waive_fee_bill(self, bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/fee-bills/{bill_id}/waive", payload, headers)

    # ──────────────── Payments ────────────────

    def create_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/payments", payload, headers)

    # ──────────────── Facilities & reservations ────────────────

    def create_facility(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/facilities", payload, headers)

    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/reservations", payload, headers)

    def check_in_reservation(self, res_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/reservations/{res_id}/check-in", headers=headers)

    def cancel_reservation(self, res_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/reservations/{res_id}/cancel", headers=headers)

    def close_reservation(self, res_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/reservations/{res_id}/close", payload, headers)

    # ──────────────── Proposals & votes ────────────────

    def create_proposal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/proposals", payload, headers)

    def open_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/proposals/{proposal_id}/open", headers=headers)

    def cast_vote(self, proposal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/proposals/{proposal_id}/votes", payload, headers
        )

    def tally_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/proposals/{proposal_id}/tally", headers=headers)

    def publish_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/proposals/{proposal_id}/publish", headers=headers)

    def cancel_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/proposals/{proposal_id}/cancel", headers=headers)

    def get_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{_PREFIX}/proposals/{proposal_id}", headers=headers)

    # ──────────────── Parking ────────────────

    def create_parking_space(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/parking-spaces", payload, headers)

    def create_parking_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/parking-applications", payload, headers)

    def approve_parking_application(self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/parking-applications/{app_id}/approve", payload, headers
        )

    def reject_parking_application(self, app_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/parking-applications/{app_id}/reject", payload, headers
        )

    def terminate_parking_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/parking-applications/{app_id}/terminate", headers=headers
        )

    # ──────────────── Access logs ────────────────

    def create_access_log(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/access-logs", payload, headers)

    # ──────────────── Audit ────────────────

    def list_audit_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{_PREFIX}/audit-entries", headers=headers, params=params)

    # ──────────────── Test-driving endpoints ────────────────

    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request("POST", f"{_PREFIX}/_clock/advance", {"to": to_iso}, headers)

    def emit_event(self, source: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{_PREFIX}/_events/emit", {"source": source, "payload": payload}, headers
        )


api_client = ApiClient()
