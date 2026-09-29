"""Typed client for the hotel pre-opening program management API.

One method per documented endpoint. Every method returns the raw
``requests.Response`` so tests can assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class PreOpeningApiClient(GenericApiClient):
    """HTTP client covering every pre-opening endpoint."""

    # ─── Test-driving clock ───────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ─── Programs ─────────────────────────────────────────────────────────────

    def create_program(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/programs", payload, headers)

    def list_programs(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/programs", params, headers)

    def get_program(self, program_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/programs/{program_id}", None, headers)

    def get_readiness(self, program_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/programs/{program_id}/readiness", None, headers
        )

    def baseline_schedule(
        self, program_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/programs/{program_id}/baseline-schedule",
            payload if payload is not None else {},
            headers,
        )

    def recompute_schedule(
        self, program_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/programs/{program_id}/recompute-schedule",
            payload if payload is not None else {},
            headers,
        )

    def open_booking(
        self, program_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/programs/{program_id}/open-booking",
            payload if payload is not None else {},
            headers,
        )

    def suspend_booking(
        self, program_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/programs/{program_id}/suspend-booking",
            payload if payload is not None else {},
            headers,
        )

    def authorize_soft_opening(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/programs/{program_id}/authorize-soft-opening",
            payload,
            headers,
        )

    def transition_to_stabilized(
        self, program_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/programs/{program_id}/transition-to-stabilized",
            payload if payload is not None else {},
            headers,
        )

    # ─── Milestones ───────────────────────────────────────────────────────────

    def create_milestone(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/milestones", payload, headers)

    def list_milestones(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/milestones", params, headers)

    def get_milestone(self, milestone_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/milestones/{milestone_id}", None, headers
        )

    def start_milestone(
        self, milestone_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/milestones/{milestone_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def complete_milestone(
        self, milestone_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/milestones/{milestone_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def reopen_milestone(
        self, milestone_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/milestones/{milestone_id}/reopen", payload, headers
        )

    # ─── Milestone dependencies ───────────────────────────────────────────────

    def create_dependency(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/milestone-dependencies", payload, headers
        )

    def list_dependencies(self, milestone_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/milestones/{milestone_id}/dependencies", params, headers
        )

    # ─── Permit applications ──────────────────────────────────────────────────

    def create_permit_application(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/permit-applications", payload, headers
        )

    def list_permit_applications(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/permit-applications", params, headers)

    def get_permit_application(self, permit_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/permit-applications/{permit_id}", None, headers
        )

    def submit_permit_application(
        self, permit_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/permit-applications/{permit_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def record_permit_review(
        self, permit_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/permit-applications/{permit_id}/record-review",
            payload,
            headers,
        )

    # ─── System implementations ───────────────────────────────────────────────

    def create_system_implementation(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/system-implementations", payload, headers
        )

    def list_system_implementations(self, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/system-implementations", params, headers
        )

    def get_system_implementation(self, system_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/system-implementations/{system_id}", None, headers
        )

    def create_test_run(
        self, system_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/system-implementations/{system_id}/test-runs",
            payload,
            headers,
        )

    def list_test_runs(self, system_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/system-implementations/{system_id}/test-runs",
            params,
            headers,
        )

    def certify_system(
        self, system_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/system-implementations/{system_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    # ─── Hiring plans, hires ──────────────────────────────────────────────────

    def create_hiring_plan(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/hiring-plans", payload, headers)

    def list_hiring_plans(self, program_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/programs/{program_id}/hiring-plans", params, headers
        )

    def create_hire(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/hires", payload, headers)

    def list_hires(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/hires", params, headers)

    def get_hire(self, hire_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/hires/{hire_id}", None, headers)

    def respond_to_offer(
        self, hire_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/hires/{hire_id}/respond", payload, headers
        )

    def assign_orientation(
        self, hire_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/hires/{hire_id}/assign-orientation", payload, headers
        )

    def onboard_hire(
        self, hire_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/hires/{hire_id}/onboard",
            payload if payload is not None else {},
            headers,
        )

    # ─── Training sessions ────────────────────────────────────────────────────

    def create_training_session(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/training-sessions", payload, headers)

    def list_training_sessions(self, program_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/programs/{program_id}/training-sessions",
            params,
            headers,
        )

    def complete_training_session(
        self, session_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/training-sessions/{session_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_training_session(
        self, session_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/training-sessions/{session_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Budget lines and OS&E orders ─────────────────────────────────────────

    def create_budget_line(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/budget-lines", payload, headers)

    def list_budget_lines(self, program_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/programs/{program_id}/budget-lines", params, headers
        )

    def create_ose_order(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/ose-orders", payload, headers)

    def list_ose_orders(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/ose-orders", params, headers)

    def get_ose_order(self, order_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/ose-orders/{order_id}", None, headers)

    def receive_ose_order(
        self, order_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/ose-orders/{order_id}/receive", payload, headers
        )

    def cancel_ose_order(
        self, order_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/ose-orders/{order_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Reservation blocks ───────────────────────────────────────────────────

    def create_reservation_block(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/reservation-blocks", payload, headers)

    def list_reservation_blocks(self, program_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/programs/{program_id}/reservation-blocks",
            params,
            headers,
        )

    def guarantee_block(
        self, block_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/reservation-blocks/{block_id}/guarantee",
            payload if payload is not None else {},
            headers,
        )

    def resolve_contingency(
        self, block_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/reservation-blocks/{block_id}/resolve-contingency",
            payload,
            headers,
        )

    # ─── Punch-list items ─────────────────────────────────────────────────────

    def create_punch_item(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/punch-list-items", payload, headers)

    def list_punch_items(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/punch-list-items", params, headers)

    def get_punch_item(self, item_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/punch-list-items/{item_id}", None, headers
        )

    def submit_punch_verification(
        self, item_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/punch-list-items/{item_id}/submit-verification",
            payload if payload is not None else {},
            headers,
        )

    def verify_punch_item(
        self, item_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/punch-list-items/{item_id}/verify", payload, headers
        )

    def reopen_punch_item(
        self, item_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/punch-list-items/{item_id}/reopen", payload, headers
        )


# Backwards-friendly alias: tests may refer to either name.
ApiClient = PreOpeningApiClient
