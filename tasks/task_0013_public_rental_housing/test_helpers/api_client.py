"""API client for the Public Rental Housing API.

One method per endpoint mounted under /housing-programs (PRD §4).
Inherits _request from GenericApiClient.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client; every method returns the raw requests.Response."""

    # ──────────────── Housing programs ────────────────

    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/housing-programs", payload, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/housing-programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/housing-programs/{program_id}", headers=headers)

    def advance_clock(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/clock/advance",
            payload,
            headers,
        )

    # ──────────────── Sync events ────────────────

    def emit_sync_event(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/housing-programs/{program_id}/sync-events", payload, headers
        )

    def list_sync_events(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/sync-events",
            headers=headers,
            params=params,
        )

    # ──────────────── Applications ────────────────

    def create_application(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/housing-programs/{program_id}/applications", payload, headers
        )

    def list_applications(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/applications",
            headers=headers,
            params=params,
        )

    def get_application(self, program_id: str, app_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/applications/{app_id}",
            headers=headers,
        )

    def submit_application(
        self,
        program_id: str,
        app_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/applications/{app_id}/submit",
            payload or {},
            headers,
        )

    def cross_check_application(self, program_id: str, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/applications/{app_id}/cross-check",
            {},
            headers,
        )

    def enqueue_application(self, program_id: str, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/applications/{app_id}/enqueue",
            {},
            headers,
        )

    def finalize_exit(self, program_id: str, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/applications/{app_id}/finalize-exit",
            {},
            headers,
        )

    def create_annual_review(
        self,
        program_id: str,
        app_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/applications/{app_id}/annual-reviews",
            payload,
            headers,
        )

    def finalize_annual_review(
        self,
        program_id: str,
        app_id: str,
        review_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/applications/{app_id}/annual-reviews/{review_id}/finalize",
            {},
            headers,
        )

    # ──────────────── Housing units ────────────────

    def create_housing_unit(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/housing-programs/{program_id}/housing-units", payload, headers
        )

    def list_housing_units(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/housing-units",
            headers=headers,
            params=params,
        )

    def get_housing_unit(self, program_id: str, unit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/housing-units/{unit_id}",
            headers=headers,
        )

    # ──────────────── Allocations ────────────────

    def create_allocation(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/housing-programs/{program_id}/allocations", payload, headers
        )

    def list_allocations(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/allocations",
            headers=headers,
            params=params,
        )

    def get_allocation(self, program_id: str, alloc_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/allocations/{alloc_id}",
            headers=headers,
        )

    def confirm_allocation(
        self,
        program_id: str,
        alloc_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/allocations/{alloc_id}/confirm",
            payload or {},
            headers,
        )

    def reject_allocation(self, program_id: str, alloc_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/allocations/{alloc_id}/reject",
            {},
            headers,
        )

    # ──────────────── Objections ────────────────

    def create_objection(
        self,
        program_id: str,
        alloc_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/allocations/{alloc_id}/objections",
            payload,
            headers,
        )

    def sustain_objection(
        self,
        program_id: str,
        alloc_id: str,
        obj_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/allocations/{alloc_id}/objections/{obj_id}/sustain",
            payload or {},
            headers,
        )

    def dismiss_objection(
        self,
        program_id: str,
        alloc_id: str,
        obj_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/allocations/{alloc_id}/objections/{obj_id}/dismiss",
            payload or {},
            headers,
        )

    # ──────────────── Contracts ────────────────

    def get_contract(self, program_id: str, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/contracts/{contract_id}",
            headers=headers,
        )

    def pay_deposit(self, program_id: str, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/contracts/{contract_id}/pay-deposit",
            {},
            headers,
        )

    def sign_contract(
        self,
        program_id: str,
        contract_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/contracts/{contract_id}/sign",
            payload,
            headers,
        )

    def handover_contract(self, program_id: str, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/contracts/{contract_id}/handover",
            {},
            headers,
        )

    # ──────────────── Rent reductions ────────────────

    def create_rent_reduction(
        self,
        program_id: str,
        contract_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/contracts/{contract_id}/rent-reductions",
            payload,
            headers,
        )

    def get_rent_reduction(self, program_id: str, rr_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/housing-programs/{program_id}/rent-reductions/{rr_id}",
            headers=headers,
        )

    def advance_rent_reduction_to_primary(
        self, program_id: str, rr_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/rent-reductions/{rr_id}/advance-to-primary",
            {},
            headers,
        )

    def advance_rent_reduction_to_secondary(
        self, program_id: str, rr_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/rent-reductions/{rr_id}/advance-to-secondary",
            {},
            headers,
        )

    def final_approve_rent_reduction(
        self, program_id: str, rr_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/rent-reductions/{rr_id}/final-approve",
            {},
            headers,
        )

    def reject_rent_reduction(self, program_id: str, rr_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/rent-reductions/{rr_id}/reject",
            {},
            headers,
        )

    def resubmit_rent_reduction(
        self,
        program_id: str,
        rr_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST",
            f"/housing-programs/{program_id}/rent-reductions/{rr_id}/resubmit",
            payload or {},
            headers,
        )


api_client = ApiClient()
