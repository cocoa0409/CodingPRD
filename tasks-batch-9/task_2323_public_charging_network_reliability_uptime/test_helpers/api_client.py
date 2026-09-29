"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the charging-network reliability HTTP API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Host sites
    # ------------------------------------------------------------------
    def create_host_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/host-sites", payload, headers)

    def list_host_sites(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/host-sites", headers=headers, params=params)

    def get_host_site(self, host_site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/host-sites/{host_site_id}", headers=headers)

    def list_host_site_stations(
        self, host_site_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"/host-sites/{host_site_id}/stations", headers=headers, params=params
        )

    def update_host_site(
        self, host_site_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/host-sites/{host_site_id}", payload, headers)

    # ------------------------------------------------------------------
    # Stations
    # ------------------------------------------------------------------
    def create_station(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_station_charging_ports(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/charging-ports", headers=headers, params=params
        )

    def list_station_uptime_reports(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/uptime-reports", headers=headers, params=params
        )

    def transition_station_status(
        self, station_id: str, target_status: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/stations/{station_id}/status-transitions",
            {"target_status": target_status},
            headers,
        )

    def commission_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/stations/{station_id}/commission", {}, headers)

    # ------------------------------------------------------------------
    # Charging ports
    # ------------------------------------------------------------------
    def create_charging_port(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/charging-ports", payload, headers)

    def get_charging_port(self, port_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/charging-ports/{port_id}", headers=headers)

    def list_port_outage_events(
        self, port_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"/charging-ports/{port_id}/outage-events", headers=headers, params=params
        )

    def update_charging_port(
        self, port_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/charging-ports/{port_id}", payload, headers)

    def record_terminal_certification(
        self, port_id: str, certification_status: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/charging-ports/{port_id}/terminal-certification",
            {"certification_status": certification_status},
            headers,
        )

    def retire_charging_port(self, port_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/charging-ports/{port_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Outage events
    # ------------------------------------------------------------------
    def create_outage_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/outage-events", payload, headers)

    def get_outage_event(self, outage_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outage-events/{outage_event_id}", headers=headers)

    def classify_outage_event(
        self, outage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/outage-events/{outage_event_id}/classify", payload, headers
        )

    def submit_exclusion_action(
        self, outage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/outage-events/{outage_event_id}/exclusion-actions", payload, headers
        )

    def submit_resolution_review(
        self, outage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/outage-events/{outage_event_id}/resolution-reviews", payload, headers
        )

    # ------------------------------------------------------------------
    # Maintenance dispatches
    # ------------------------------------------------------------------
    def create_maintenance_dispatch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/maintenance-dispatches", payload, headers)

    def list_maintenance_dispatches(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/maintenance-dispatches", headers=headers, params=params)

    def get_maintenance_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/maintenance-dispatches/{dispatch_id}", headers=headers)

    def post_dispatch_progress(self, dispatch_id: str, event: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/maintenance-dispatches/{dispatch_id}/progress", {"event": event}, headers
        )

    def place_parts_hold(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/maintenance-dispatches/{dispatch_id}/parts-hold", {}, headers
        )

    def complete_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/maintenance-dispatches/{dispatch_id}/complete", {}, headers
        )

    # ------------------------------------------------------------------
    # Spare parts
    # ------------------------------------------------------------------
    def create_spare_part(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/spare-parts", payload, headers)

    def list_spare_parts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/spare-parts", headers=headers, params=params)

    def get_spare_part(self, spare_part_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/spare-parts/{spare_part_id}", headers=headers)

    def restock_spare_part(self, spare_part_id: str, qty: int, headers: Dict[str, str]):
        return self._request(
            "POST", f"/spare-parts/{spare_part_id}/restock", {"qty": qty}, headers
        )

    # ------------------------------------------------------------------
    # Part reservations
    # ------------------------------------------------------------------
    def create_part_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/part-reservations", payload, headers)

    def list_part_reservations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/part-reservations", headers=headers, params=params)

    def get_part_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/part-reservations/{reservation_id}", headers=headers)

    def dispose_part_reservation(
        self, reservation_id: str, action: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/part-reservations/{reservation_id}/disposition",
            {"action": action},
            headers,
        )

    # ------------------------------------------------------------------
    # Uptime reports
    # ------------------------------------------------------------------
    def create_uptime_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/uptime-reports", payload, headers)

    def get_uptime_report(self, uptime_report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/uptime-reports/{uptime_report_id}", headers=headers)

    def list_report_reimbursement_claims(
        self,
        uptime_report_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/uptime-reports/{uptime_report_id}/reimbursement-claims",
            headers=headers,
            params=params,
        )

    def compute_provisional_uptime(self, uptime_report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/uptime-reports/{uptime_report_id}/compute-provisional", {}, headers
        )

    def finalize_uptime_report(self, uptime_report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/uptime-reports/{uptime_report_id}/finalize", {}, headers
        )

    def submit_uptime_report(self, uptime_report_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/uptime-reports/{uptime_report_id}/submit", {}, headers)

    def program_review_uptime_report(
        self, uptime_report_id: str, outcome: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/uptime-reports/{uptime_report_id}/program-review",
            {"outcome": outcome},
            headers,
        )

    # ------------------------------------------------------------------
    # Reimbursement claims
    # ------------------------------------------------------------------
    def create_reimbursement_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reimbursement-claims/{claim_id}", headers=headers)

    def review_reimbursement_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/review", {}, headers)

    def decide_reimbursement_claim(
        self, claim_id: str, decision: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/decision", {"decision": decision}, headers
        )

    def file_claim_remediation(
        self, claim_id: str, remediation_credit_pp: float, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/reimbursement-claims/{claim_id}/remediation",
            {"remediation_credit_pp": remediation_credit_pp},
            headers,
        )

    # ------------------------------------------------------------------
    # Customer complaints
    # ------------------------------------------------------------------
    def create_customer_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/customer-complaints", payload, headers)

    def list_customer_complaints(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/customer-complaints", headers=headers, params=params)

    def get_customer_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/customer-complaints/{complaint_id}", headers=headers)

    def triage_customer_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/customer-complaints/{complaint_id}/triage", payload, headers
        )

    def close_customer_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/customer-complaints/{complaint_id}/close", {}, headers)

    def request_session_refund(
        self, complaint_id: str, refund_basis: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/customer-complaints/{complaint_id}/refund-requests",
            {"refund_basis": refund_basis},
            headers,
        )

    def decide_session_refund(self, complaint_id: str, decision: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customer-complaints/{complaint_id}/refund-decisions",
            {"decision": decision},
            headers,
        )

    def act_on_refund_ledger(self, complaint_id: str, action: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customer-complaints/{complaint_id}/refund-ledger-actions",
            {"action": action},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches — used by tests that must send malformed payloads or
    # omit headers entirely.
    # ------------------------------------------------------------------
    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request("POST", path, payload if payload is not None else {}, headers)

    def raw_patch(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request("PATCH", path, payload if payload is not None else {}, headers)


api_client = ApiClient()
