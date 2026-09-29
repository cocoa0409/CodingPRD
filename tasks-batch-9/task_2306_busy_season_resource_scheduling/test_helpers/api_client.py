"""HTTP client with one method per endpoint of the scheduling service."""

from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import Headers, JsonDict


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is ``None`` so callers can pass sparse kwargs."""

    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


class ApiClient(GenericApiClient):
    """Endpoint-per-method wrapper around the generic request client."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    def create_client(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/clients", payload, headers)

    def get_client(self, client_id: str, headers: Headers):
        return self._request("GET", f"{API_PREFIX}/clients/{client_id}", None, headers)

    def list_clients(self, headers: Headers, **params: Any):
        return self._request("GET", f"{API_PREFIX}/clients", _clean(params), headers)

    # ------------------------------------------------------------------
    # Staff members
    # ------------------------------------------------------------------

    def create_staff_member(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/staff-members", payload, headers)

    def get_staff_member(self, staff_member_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/staff-members/{staff_member_id}", None, headers
        )

    def list_staff_members(self, headers: Headers, **params: Any):
        return self._request(
            "GET", f"{API_PREFIX}/staff-members", _clean(params), headers
        )

    def get_staff_workload(
        self,
        staff_member_id: str,
        headers: Headers,
        week_start_date: Optional[str] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/staff-members/{staff_member_id}/workload",
            _clean({"week_start_date": week_start_date}),
            headers,
        )

    def list_staff_availability_exceptions(
        self, staff_member_id: str, headers: Headers, **params: Any
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/staff-members/{staff_member_id}/availability-exceptions",
            _clean(params),
            headers,
        )

    # ------------------------------------------------------------------
    # Engagements
    # ------------------------------------------------------------------

    def create_engagement(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/engagements", payload, headers)

    def get_engagement(self, engagement_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/engagements/{engagement_id}", None, headers
        )

    def list_engagements(self, headers: Headers, **params: Any):
        return self._request("GET", f"{API_PREFIX}/engagements", _clean(params), headers)

    def get_engagement_realization(self, engagement_id: str, headers: Headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/engagements/{engagement_id}/realization",
            None,
            headers,
        )

    def schedule_engagement(self, engagement_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/engagements/{engagement_id}/schedule", {}, headers
        )

    def start_fieldwork(self, engagement_id: str, headers: Headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/start-fieldwork",
            {},
            headers,
        )

    def report_client_block(
        self,
        engagement_id: str,
        headers: Headers,
        reason_note: str,
        blocked_until_date: Optional[str] = None,
    ):
        payload: JsonDict = {"reason_note": reason_note}
        if blocked_until_date is not None:
            payload["blocked_until_date"] = blocked_until_date
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/report-client-block",
            payload,
            headers,
        )

    def clear_client_block(self, engagement_id: str, headers: Headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/engagements/{engagement_id}/clear-client-block",
            {},
            headers,
        )

    def deliver_engagement(self, engagement_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/engagements/{engagement_id}/deliver", {}, headers
        )

    # ------------------------------------------------------------------
    # Engagement phases
    # ------------------------------------------------------------------

    def create_engagement_phase(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/engagement-phases", payload, headers)

    def get_engagement_phase(self, phase_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/engagement-phases/{phase_id}", None, headers
        )

    def list_engagement_phases(self, headers: Headers, **params: Any):
        return self._request(
            "GET", f"{API_PREFIX}/engagement-phases", _clean(params), headers
        )

    def expand_phase_scope(
        self,
        phase_id: str,
        headers: Headers,
        additional_expected_hours: float,
        reason_note: Optional[str] = None,
    ):
        payload: JsonDict = {"additional_expected_hours": additional_expected_hours}
        if reason_note is not None:
            payload["reason_note"] = reason_note
        return self._request(
            "POST",
            f"{API_PREFIX}/engagement-phases/{phase_id}/expand-scope",
            payload,
            headers,
        )

    def start_phase(self, phase_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/engagement-phases/{phase_id}/start", {}, headers
        )

    def complete_phase(self, phase_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/engagement-phases/{phase_id}/complete", {}, headers
        )

    def auto_staff_phase(
        self,
        phase_id: str,
        headers: Headers,
        start_date: str,
        end_date: str,
        allocated_hours: float,
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/engagement-phases/{phase_id}/auto-staff",
            {
                "start_date": start_date,
                "end_date": end_date,
                "allocated_hours": allocated_hours,
            },
            headers,
        )

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    def create_assignment(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/assignments/{assignment_id}", None, headers
        )

    def list_assignments(self, headers: Headers, **params: Any):
        return self._request("GET", f"{API_PREFIX}/assignments", _clean(params), headers)

    def list_assignment_time_entries(
        self, assignment_id: str, headers: Headers, **params: Any
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/assignments/{assignment_id}/time-entries",
            _clean(params),
            headers,
        )

    def confirm_assignment(self, assignment_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/assignments/{assignment_id}/confirm", {}, headers
        )

    def activate_assignment(self, assignment_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/assignments/{assignment_id}/activate", {}, headers
        )

    def release_assignment(
        self, assignment_id: str, headers: Headers, reason_note: Optional[str] = None
    ):
        payload: JsonDict = {}
        if reason_note is not None:
            payload["reason_note"] = reason_note
        return self._request(
            "POST",
            f"{API_PREFIX}/assignments/{assignment_id}/release",
            payload,
            headers,
        )

    def reassign_assignment(self, assignment_id: str, payload: JsonDict, headers: Headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/assignments/{assignment_id}/reassign",
            payload,
            headers,
        )

    def start_review(self, assignment_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/assignments/{assignment_id}/start-review", {}, headers
        )

    def request_rework(
        self, assignment_id: str, headers: Headers, reason_note: Optional[str] = None
    ):
        payload: JsonDict = {}
        if reason_note is not None:
            payload["reason_note"] = reason_note
        return self._request(
            "POST",
            f"{API_PREFIX}/assignments/{assignment_id}/request-rework",
            payload,
            headers,
        )

    def accept_review(self, assignment_id: str, headers: Headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/assignments/{assignment_id}/accept-review",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Availability exceptions and time entries
    # ------------------------------------------------------------------

    def create_availability_exception(self, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/availability-exceptions", payload, headers
        )

    def create_time_entry(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/time-entries", payload, headers)

    # ------------------------------------------------------------------
    # Independence restrictions
    # ------------------------------------------------------------------

    def create_independence_restriction(self, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/independence-restrictions", payload, headers
        )

    def get_independence_restriction(self, restriction_id: str, headers: Headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/independence-restrictions/{restriction_id}",
            None,
            headers,
        )

    def list_independence_restrictions(self, headers: Headers, **params: Any):
        return self._request(
            "GET", f"{API_PREFIX}/independence-restrictions", _clean(params), headers
        )

    def lift_independence_restriction(self, restriction_id: str, headers: Headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/independence-restrictions/{restriction_id}/lift",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Review capacity windows
    # ------------------------------------------------------------------

    def create_review_capacity_window(self, payload: JsonDict, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/review-capacity-windows", payload, headers
        )

    def get_review_capacity_window(self, window_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/review-capacity-windows/{window_id}", None, headers
        )

    def list_review_capacity_windows(self, headers: Headers, **params: Any):
        return self._request(
            "GET", f"{API_PREFIX}/review-capacity-windows", _clean(params), headers
        )

    # ------------------------------------------------------------------
    # Reschedule plans
    # ------------------------------------------------------------------

    def create_reschedule_plan(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/reschedule-plans", payload, headers)

    def get_reschedule_plan(self, plan_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/reschedule-plans/{plan_id}", None, headers
        )

    def list_reschedule_plans(self, headers: Headers, **params: Any):
        return self._request(
            "GET", f"{API_PREFIX}/reschedule-plans", _clean(params), headers
        )

    def simulate_reschedule_plan(self, plan_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/reschedule-plans/{plan_id}/simulate", {}, headers
        )

    def apply_reschedule_plan(
        self, plan_id: str, headers: Headers, expected_engagement_version: Any
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/reschedule-plans/{plan_id}/apply",
            {"expected_engagement_version": expected_engagement_version},
            headers,
        )

    # ------------------------------------------------------------------
    # Workload waivers
    # ------------------------------------------------------------------

    def create_workload_waiver(self, payload: JsonDict, headers: Headers):
        return self._request("POST", f"{API_PREFIX}/workload-waivers", payload, headers)

    def get_workload_waiver(self, waiver_id: str, headers: Headers):
        return self._request(
            "GET", f"{API_PREFIX}/workload-waivers/{waiver_id}", None, headers
        )

    def list_workload_waivers(self, headers: Headers, **params: Any):
        return self._request(
            "GET", f"{API_PREFIX}/workload-waivers", _clean(params), headers
        )

    def approve_workload_waiver(self, waiver_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/workload-waivers/{waiver_id}/approve", {}, headers
        )

    def deny_workload_waiver(self, waiver_id: str, headers: Headers):
        return self._request(
            "POST", f"{API_PREFIX}/workload-waivers/{waiver_id}/deny", {}, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for header-shape and path-shape probes
    # ------------------------------------------------------------------

    def raw_get(self, path: str, headers: Headers, params: Optional[JsonDict] = None):
        return self._request("GET", path, _clean(params), headers)

    def raw_post(self, path: str, payload: Optional[JsonDict], headers: Headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
