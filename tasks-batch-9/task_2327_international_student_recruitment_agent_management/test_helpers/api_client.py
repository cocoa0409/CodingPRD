"""Typed endpoint wrapper for the recruitment-agent management API.

One method per documented operation.  Every method returns the raw
``requests.Response`` so that tests can assert on the status code and the
envelope themselves; nothing here validates or unwraps.

All domain paths live under ``/recruitment``.  The logical-clock capability is
mounted outside that prefix, directly at ``/_clock/set_current_utc``.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH

BASE = "/recruitment"


class RecruitmentApiClient(GenericApiClient):
    """Thin, explicit wrapper around every operation in the contract."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ------------------------------------------------------------------
    # Agencies
    # ------------------------------------------------------------------
    def register_agency(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(f"{BASE}/agencies", json=payload, headers=headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/agencies/{agency_id}", headers=headers)

    def list_agencies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self.get(f"{BASE}/agencies", headers=headers, params=params)

    def patch_agency(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{BASE}/agencies/{agency_id}", payload=payload, headers=headers
        )

    def agency_vetting_action(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/agencies/{agency_id}/vetting", json=payload, headers=headers
        )

    def agency_posture_action(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/agencies/{agency_id}/posture-actions",
            json=payload,
            headers=headers,
        )

    def get_risk_profile(
        self, agency_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/agencies/{agency_id}/risk-profile", headers=headers)

    def record_certification(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/agencies/{agency_id}/training-certifications",
            json=payload,
            headers=headers,
        )

    def list_certifications(
        self,
        agency_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get(
            f"{BASE}/agencies/{agency_id}/training-certifications",
            headers=headers,
            params=params,
        )

    def run_scorecard(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/agencies/{agency_id}/scorecards", json=payload, headers=headers
        )

    def list_scorecards(
        self,
        agency_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get(
            f"{BASE}/agencies/{agency_id}/scorecards", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(f"{BASE}/programs", json=payload, headers=headers)

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self.get(f"{BASE}/programs/{program_id}", headers=headers)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def draft_contract(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(f"{BASE}/contracts", json=payload, headers=headers)

    def get_contract(
        self, contract_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/contracts/{contract_id}", headers=headers)

    def list_contracts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self.get(f"{BASE}/contracts", headers=headers, params=params)

    def contract_lifecycle_action(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/contracts/{contract_id}/lifecycle", json=payload, headers=headers
        )

    def terminate_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/contracts/{contract_id}/terminate", json=payload, headers=headers
        )

    def assign_territory(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/contracts/{contract_id}/territory-assignments",
            json=payload,
            headers=headers,
        )

    def list_territory_assignments(
        self,
        contract_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get(
            f"{BASE}/contracts/{contract_id}/territory-assignments",
            headers=headers,
            params=params,
        )

    def release_territory(
        self, contract_id: str, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/contracts/{contract_id}/territory-assignments/"
            f"{assignment_id}/release",
            json={},
            headers=headers,
        )

    def append_commission_schedule(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/contracts/{contract_id}/commission-schedules",
            json=payload,
            headers=headers,
        )

    def list_commission_schedules(
        self,
        contract_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get(
            f"{BASE}/contracts/{contract_id}/commission-schedules",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Territory occupancy (computed read)
    # ------------------------------------------------------------------
    def get_territory_occupancy(
        self, country_code: str, at_date: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(
            f"{BASE}/territory-occupancy",
            headers=headers,
            params={"country_code": country_code, "at_date": at_date},
        )

    # ------------------------------------------------------------------
    # Student applications
    # ------------------------------------------------------------------
    def create_application(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(f"{BASE}/applications", json=payload, headers=headers)

    def get_application(
        self, application_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/applications/{application_id}", headers=headers)

    def list_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self.get(f"{BASE}/applications", headers=headers, params=params)

    def application_disclosure(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/applications/{application_id}/disclosure",
            json=payload,
            headers=headers,
        )

    def submit_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.post(
            f"{BASE}/applications/{application_id}/submit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def application_decision(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/applications/{application_id}/decision",
            json=payload,
            headers=headers,
        )

    def register_milestone(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/applications/{application_id}/milestones",
            json=payload,
            headers=headers,
        )

    def withdraw_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/applications/{application_id}/withdraw",
            json=payload,
            headers=headers,
        )

    def get_commission_projection(
        self, application_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(
            f"{BASE}/applications/{application_id}/commission-projection",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Supporting documents
    # ------------------------------------------------------------------
    def upload_document(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/applications/{application_id}/documents",
            json=payload,
            headers=headers,
        )

    def list_application_documents(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get(
            f"{BASE}/applications/{application_id}/documents",
            headers=headers,
            params=params,
        )

    def get_document(
        self, document_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/documents/{document_id}", headers=headers)

    def document_verification(
        self, document_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/documents/{document_id}/verification",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Integrity incidents
    # ------------------------------------------------------------------
    def file_incident(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(f"{BASE}/integrity-incidents", json=payload, headers=headers)

    def get_incident(
        self, incident_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/integrity-incidents/{incident_id}", headers=headers)

    def list_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self.get(f"{BASE}/integrity-incidents", headers=headers, params=params)

    def incident_resolution(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/integrity-incidents/{incident_id}/resolution",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Commission ledger
    # ------------------------------------------------------------------
    def get_commission_entry(
        self, entry_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/commission-entries/{entry_id}", headers=headers)

    def list_commission_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self.get(f"{BASE}/commission-entries", headers=headers, params=params)

    def entry_disposition(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self.post(
            f"{BASE}/commission-entries/{entry_id}/disposition",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Student-file transitions
    # ------------------------------------------------------------------
    def get_file_transition(
        self, transition_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self.get(f"{BASE}/file-transitions/{transition_id}", headers=headers)

    def list_file_transitions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self.get(f"{BASE}/file-transitions", headers=headers, params=params)
