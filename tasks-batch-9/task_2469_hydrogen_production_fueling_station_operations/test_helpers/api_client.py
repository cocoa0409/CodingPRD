"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Hydrogen production and fuelling station API client."""

    # ─── Funding agreements ───────────────────────────────────────────────

    def create_funding_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/funding-agreements", payload, headers)

    def get_funding_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/funding-agreements/{agreement_id}", headers=headers)

    def list_funding_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/funding-agreements", headers=headers, params=params)

    # ─── Stations ─────────────────────────────────────────────────────────

    def create_station(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def list_station_pressure_vessels(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/pressure-vessels", headers=headers, params=params
        )

    def list_station_inventory_ledger(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/inventory-ledger", headers=headers, params=params
        )

    def list_station_safety_events(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/safety-events", headers=headers, params=params
        )

    def list_station_responder_certifications(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/stations/{station_id}/responder-certifications",
            headers=headers,
            params=params,
        )

    def list_station_dispense_sessions(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/dispense-sessions", headers=headers, params=params
        )

    def list_station_incentive_claims(
        self, station_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/stations/{station_id}/incentive-claims", headers=headers, params=params
        )

    # ─── Pressure vessels ─────────────────────────────────────────────────

    def create_pressure_vessel(
        self, station_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stations/{station_id}/pressure-vessels", payload, headers
        )

    def get_pressure_vessel(self, vessel_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pressure-vessels/{vessel_id}", headers=headers)

    def record_vessel_inspection(
        self, vessel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/pressure-vessels/{vessel_id}/inspections", payload, headers
        )

    # ─── Responder certifications ─────────────────────────────────────────

    def create_responder_certification(
        self, station_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stations/{station_id}/responder-certifications", payload, headers
        )

    # ─── Production assets and power supply contracts ─────────────────────

    def create_production_asset(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/production-assets", payload, headers)

    def get_production_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/production-assets/{asset_id}", headers=headers)

    def create_power_supply_contract(
        self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/production-assets/{asset_id}/power-supply-contracts", payload, headers
        )

    def list_power_supply_contracts(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/production-assets/{asset_id}/power-supply-contracts",
            headers=headers,
            params=params,
        )

    # ─── Production lots ──────────────────────────────────────────────────

    def create_production_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/production-lots", payload, headers)

    def get_production_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/production-lots/{lot_id}", headers=headers)

    def list_production_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/production-lots", headers=headers, params=params)

    def create_purity_test(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/production-lots/{lot_id}/purity-tests", payload, headers)

    def list_purity_tests(
        self, lot_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/production-lots/{lot_id}/purity-tests", headers=headers, params=params
        )

    def certify_lot_ci(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/production-lots/{lot_id}/certify-ci", {}, headers)

    def release_production_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/production-lots/{lot_id}/release", {}, headers)

    # ─── Deliveries ───────────────────────────────────────────────────────

    def create_delivery(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def arrive_delivery(self, delivery_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/deliveries/{delivery_id}/arrive", {}, headers)

    def offload_delivery(self, delivery_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/deliveries/{delivery_id}/offload", {}, headers)

    def reject_delivery(
        self, delivery_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/deliveries/{delivery_id}/reject", payload, headers)

    def reschedule_delivery(
        self, delivery_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/deliveries/{delivery_id}/reschedule", payload, headers)

    # ─── Dispense sessions ────────────────────────────────────────────────

    def create_dispense_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dispense-sessions", payload, headers)

    def get_dispense_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dispense-sessions/{session_id}", headers=headers)

    def fuel_dispense_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/dispense-sessions/{session_id}/fuel", payload, headers)

    def complete_dispense_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dispense-sessions/{session_id}/complete", payload, headers
        )

    def abort_dispense_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dispense-sessions/{session_id}/abort", {}, headers)

    def settle_dispense_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dispense-sessions/{session_id}/meter-settlement", {}, headers
        )

    def void_dispense_session_meter(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dispense-sessions/{session_id}/void-meter", payload, headers
        )

    # ─── Safety events ────────────────────────────────────────────────────

    def create_safety_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/safety-events", payload, headers)

    def get_safety_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/safety-events/{event_id}", headers=headers)

    def acknowledge_safety_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/safety-events/{event_id}/acknowledge", {}, headers)

    def clear_safety_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/safety-events/{event_id}/clear", payload, headers)

    # ─── Incentive claims ─────────────────────────────────────────────────

    def create_incentive_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/incentive-claims", payload, headers)

    def get_incentive_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/incentive-claims/{claim_id}", headers=headers)

    def request_claim_revision(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/incentive-claims/{claim_id}/request-revision", payload, headers
        )

    def resubmit_incentive_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/incentive-claims/{claim_id}/resubmit", payload, headers)

    def certify_incentive_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/incentive-claims/{claim_id}/certify", {}, headers)

    def issue_claim_credits(self, claim_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/incentive-claims/{claim_id}/issue-credits", {}, headers)

    # ─── Uptime reports ───────────────────────────────────────────────────

    def create_uptime_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/uptime-reports", payload, headers)

    def get_uptime_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/uptime-reports/{report_id}", headers=headers)

    def list_uptime_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/uptime-reports", headers=headers, params=params)

    def finalize_uptime_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/uptime-reports/{report_id}/finalize", {}, headers)

    def amend_uptime_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/uptime-reports/{report_id}/amend", payload, headers)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
