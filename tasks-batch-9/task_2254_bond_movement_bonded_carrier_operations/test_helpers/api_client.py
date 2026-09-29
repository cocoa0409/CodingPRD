"""Typed wrapper around the In-Bond Movement & Bonded Carrier endpoints.

One method per endpoint in the API, each returning the raw ``requests.Response``
so that tests can assert on status codes and error identifiers as well as on
payloads. Every method takes explicit ``headers`` — the API rejects a request
whose identity headers are missing before it looks at anything else, so there is
no implicit default caller.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

JsonDict = Dict[str, Any]


class InBondApiClient(GenericApiClient):
    """Endpoint-per-method client for the ``/in-bond`` API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/in-bond/carriers", payload=payload, headers=headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/in-bond/carriers/{carrier_id}", headers=headers)

    def patch_carrier(
        self, carrier_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/in-bond/carriers/{carrier_id}", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Bonds
    # ------------------------------------------------------------------
    def create_bond(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/in-bond/bonds", payload=payload, headers=headers)

    def get_bond(self, bond_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/in-bond/bonds/{bond_id}", headers=headers)

    def list_bonds(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/in-bond/bonds", params=params, headers=headers)

    def patch_bond(
        self, bond_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/in-bond/bonds/{bond_id}", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Ports
    # ------------------------------------------------------------------
    def create_port(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/in-bond/ports", payload=payload, headers=headers)

    def get_port(self, port_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/in-bond/ports/{port_id}", headers=headers)

    # ------------------------------------------------------------------
    # Movements
    # ------------------------------------------------------------------
    def file_movement(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/movements", payload=payload, headers=headers
        )

    def get_movement(
        self, movement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/in-bond/movements/{movement_id}", headers=headers)

    def list_movements(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/in-bond/movements", params=params, headers=headers)

    def depart_movement(
        self, movement_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/movements/{movement_id}/departure",
            payload=payload,
            headers=headers,
        )

    def cancel_movement(
        self, movement_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/movements/{movement_id}/cancellation",
            payload=payload,
            headers=headers,
        )

    def release_cargo(
        self, movement_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/movements/{movement_id}/release",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------
    def get_ledger_entry(
        self, entry_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/in-bond/ledger-entries/{entry_id}", headers=headers
        )

    def list_ledger_entries(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/in-bond/ledger-entries", params=params, headers=headers
        )

    # ------------------------------------------------------------------
    # Seal events
    # ------------------------------------------------------------------
    def record_seal_event(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/seal-events", payload=payload, headers=headers
        )

    def list_seal_events(
        self,
        movement_id: str,
        headers: Dict[str, str],
        params: Optional[JsonDict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/in-bond/movements/{movement_id}/seal-events",
            params=params,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Examination holds
    # ------------------------------------------------------------------
    def place_hold(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/examination-holds", payload=payload, headers=headers
        )

    def get_hold(self, hold_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/in-bond/examination-holds/{hold_id}", headers=headers
        )

    def list_holds(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/in-bond/examination-holds", params=params, headers=headers
        )

    def release_hold(
        self, hold_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/examination-holds/{hold_id}/release",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Amendment requests
    # ------------------------------------------------------------------
    def submit_amendment(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/amendment-requests", payload=payload, headers=headers
        )

    def list_movement_amendments(
        self,
        movement_id: str,
        headers: Dict[str, str],
        params: Optional[JsonDict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/in-bond/movements/{movement_id}/amendment-requests",
            params=params,
            headers=headers,
        )

    def decide_amendment(
        self, amendment_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/amendment-requests/{amendment_id}/decision",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Movement reports
    # ------------------------------------------------------------------
    def file_report(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/in-bond/reports", payload=payload, headers=headers)

    def submit_export_proof(
        self, report_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/reports/{report_id}/proof",
            payload=payload,
            headers=headers,
        )

    def get_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/in-bond/reports/{report_id}", headers=headers)

    def list_reports(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/in-bond/reports", params=params, headers=headers)

    # ------------------------------------------------------------------
    # Liquidated-damages claims
    # ------------------------------------------------------------------
    def issue_claim(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/ld-claims", payload=payload, headers=headers
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/in-bond/ld-claims/{claim_id}", headers=headers)

    def list_claims(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/in-bond/ld-claims", params=params, headers=headers)

    def dispose_claim(
        self, claim_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/ld-claims/{claim_id}/disposition",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Mitigation petitions
    # ------------------------------------------------------------------
    def file_petition(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/petitions", payload=payload, headers=headers
        )

    def supplement_petition(
        self, petition_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/petitions/{petition_id}/supplement",
            payload=payload,
            headers=headers,
        )

    def decide_petition(
        self, petition_id: str, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/in-bond/petitions/{petition_id}/decision",
            payload=payload,
            headers=headers,
        )

    def list_claim_petitions(
        self, claim_id: str, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/in-bond/ld-claims/{claim_id}/petitions",
            params=params,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Compliance sweeps
    # ------------------------------------------------------------------
    def run_sweep(
        self, payload: JsonDict, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/in-bond/compliance-sweeps", payload=payload, headers=headers
        )

    def list_sweeps(
        self, headers: Dict[str, str], params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/in-bond/compliance-sweeps", params=params, headers=headers
        )
