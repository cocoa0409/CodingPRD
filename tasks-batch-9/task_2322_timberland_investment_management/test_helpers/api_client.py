"""Typed client for every endpoint of the Timberland Investment Management API.

All paths are mounted under `/timberland`, as PRD §1 states. Every method takes
an explicit `headers` mapping so that each call can declare the acting user and
role required by PRD §2.1.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/timberland"

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


def _clean(payload: Payload) -> Payload:
    """Drop keys whose value is the sentinel `...` so callers can omit fields."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not ...}


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD endpoint table."""

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        return self.post(
            f"{BASE}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post(f"{BASE}/_clock/set_current_utc", _clean(payload), headers)

    # ---- Funds ----------------------------------------------------------
    def create_fund(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post(f"{BASE}/funds", _clean(payload), headers)

    def get_fund(self, fund_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"{BASE}/funds/{fund_id}", headers)

    def list_fund_properties(
        self, fund_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/funds/{fund_id}/properties", headers, params)

    def get_investor_report(
        self, fund_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/funds/{fund_id}/investor-report", headers)

    # ---- Properties -----------------------------------------------------
    def create_property(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/properties", _clean(payload), headers)

    def get_property(self, property_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"{BASE}/properties/{property_id}", headers)

    def list_property_stands(
        self, property_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/properties/{property_id}/stands", headers, params)

    def appraisal_action(
        self, property_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/properties/{property_id}/appraisal", _clean(payload), headers
        )

    def risk_review(
        self, property_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/properties/{property_id}/risk-review", _clean(payload), headers
        )

    def acquire_property(
        self, property_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/properties/{property_id}/acquire", _clean(payload), headers
        )

    def list_property_underwriting_cases(
        self, property_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(
            f"{BASE}/properties/{property_id}/underwriting-cases", headers, params
        )

    def list_property_carbon_projects(
        self, property_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(
            f"{BASE}/properties/{property_id}/carbon-projects", headers, params
        )

    def list_property_recreational_leases(
        self, property_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(
            f"{BASE}/properties/{property_id}/recreational-leases", headers, params
        )

    def list_property_certification_audits(
        self, property_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(
            f"{BASE}/properties/{property_id}/certification-audits", headers, params
        )

    # ---- Underwriting cases ---------------------------------------------
    def create_underwriting_case(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/underwriting-cases", _clean(payload), headers)

    def get_underwriting_case(
        self, case_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/underwriting-cases/{case_id}", headers)

    def submit_underwriting_case(
        self, case_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/underwriting-cases/{case_id}/submit", _clean(payload) or {}, headers
        )

    def decide_underwriting_case(
        self, case_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/underwriting-cases/{case_id}/decide", _clean(payload), headers
        )

    # ---- Stands ---------------------------------------------------------
    def create_stand(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post(f"{BASE}/stands", _clean(payload), headers)

    def get_stand(self, stand_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}", headers)

    def close_cruise(
        self, stand_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/stands/{stand_id}/cruise-close", _clean(payload) or {}, headers
        )

    def list_stand_cruise_plots(
        self, stand_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}/cruise-plots", headers, params)

    def list_stand_harvest_blocks(
        self, stand_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}/harvest-blocks", headers, params)

    def list_stand_carbon_dedications(
        self, stand_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}/carbon-dedications", headers, params)

    def list_stand_hbu_parcels(
        self, stand_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}/hbu-parcels", headers, params)

    def list_stand_hazard_events(
        self, stand_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}/hazard-events", headers, params)

    def list_stand_derived_stands(
        self, stand_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(f"{BASE}/stands/{stand_id}/derived-stands", headers, params)

    # ---- Cruise plots ---------------------------------------------------
    def create_cruise_plot(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/cruise-plots", _clean(payload), headers)

    # ---- Harvest blocks -------------------------------------------------
    def create_harvest_block(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/harvest-blocks", _clean(payload), headers)

    def get_harvest_block(
        self, block_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/harvest-blocks/{block_id}", headers)

    def commit_harvest_block(
        self, block_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/harvest-blocks/{block_id}/commit", _clean(payload) or {}, headers
        )

    def close_harvest_block(
        self, block_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/harvest-blocks/{block_id}/close", _clean(payload), headers
        )

    # ---- Carbon projects ------------------------------------------------
    def create_carbon_project(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/carbon-projects", _clean(payload), headers)

    def get_carbon_project(
        self, project_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/carbon-projects/{project_id}", headers)

    def advance_carbon_project(
        self, project_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/carbon-projects/{project_id}/advance", _clean(payload), headers
        )

    def list_carbon_project_dedications(
        self, project_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(
            f"{BASE}/carbon-projects/{project_id}/dedications", headers, params
        )

    # ---- Carbon dedications ---------------------------------------------
    def create_carbon_dedication(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/carbon-dedications", _clean(payload), headers)

    def get_carbon_dedication(
        self, dedication_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/carbon-dedications/{dedication_id}", headers)

    def release_carbon_dedication(
        self, dedication_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/carbon-dedications/{dedication_id}/release",
            _clean(payload) or {},
            headers,
        )

    # ---- HBU parcels ----------------------------------------------------
    def create_hbu_parcel(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/hbu-parcels", _clean(payload), headers)

    def get_hbu_parcel(self, parcel_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"{BASE}/hbu-parcels/{parcel_id}", headers)

    def advance_hbu_parcel(
        self, parcel_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/hbu-parcels/{parcel_id}/advance", _clean(payload), headers
        )

    # ---- Recreational leases --------------------------------------------
    def create_recreational_lease(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/recreational-leases", _clean(payload), headers)

    def get_recreational_lease(
        self, lease_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/recreational-leases/{lease_id}", headers)

    def activate_recreational_lease(
        self, lease_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/recreational-leases/{lease_id}/activate",
            _clean(payload) or {},
            headers,
        )

    def terminate_recreational_lease(
        self, lease_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/recreational-leases/{lease_id}/terminate", _clean(payload), headers
        )

    # ---- Certification audits -------------------------------------------
    def create_certification_audit(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/certification-audits", _clean(payload), headers)

    def get_certification_audit(
        self, audit_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/certification-audits/{audit_id}", headers)

    def advance_certification_audit(
        self, audit_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/certification-audits/{audit_id}/advance", _clean(payload), headers
        )

    def create_audit_finding(
        self, audit_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/certification-audits/{audit_id}/findings", _clean(payload), headers
        )

    def list_audit_findings(
        self, audit_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self.get(
            f"{BASE}/certification-audits/{audit_id}/findings", headers, params
        )

    def get_audit_finding(
        self, finding_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/audit-findings/{finding_id}", headers)

    def transition_audit_finding(
        self, finding_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/audit-findings/{finding_id}/transition", _clean(payload), headers
        )

    # ---- Hazard events --------------------------------------------------
    def create_hazard_event(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"{BASE}/hazard-events", _clean(payload), headers)

    def get_hazard_event(
        self, event_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"{BASE}/hazard-events/{event_id}", headers)

    def settle_hazard_event(
        self, event_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"{BASE}/hazard-events/{event_id}/salvage-settle", _clean(payload), headers
        )


api_client = ApiClient()
