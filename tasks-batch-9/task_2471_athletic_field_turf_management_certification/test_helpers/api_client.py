"""Typed client covering every endpoint of the turf management API.

Each method returns the raw `requests.Response` so that tests can assert both
the envelope and the HTTP status through the framework validators.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/turf"


def _clean(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is the sentinel ``...`` so callers can omit fields."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not ...}


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD endpoint table."""

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    def create_field(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(f"{API_PREFIX}/fields", json=_clean(payload), headers=headers)

    def list_fields(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get(f"{API_PREFIX}/fields", headers=headers, params=params)

    def get_field(self, field_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/fields/{field_id}", headers=headers)

    def place_closure_order(
        self, field_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/fields/{field_id}/closure-order",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Staff members
    # ------------------------------------------------------------------

    def create_staff_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/staff-members", json=_clean(payload), headers=headers
        )

    def get_staff_member(self, staff_member_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/staff-members/{staff_member_id}", headers=headers)

    # ------------------------------------------------------------------
    # Maintenance tasks
    # ------------------------------------------------------------------

    def create_maintenance_task(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/maintenance-tasks", json=_clean(payload), headers=headers
        )

    def list_maintenance_tasks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/maintenance-tasks", headers=headers, params=params)

    def get_maintenance_task(self, task_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/maintenance-tasks/{task_id}", headers=headers)

    def transition_maintenance_task(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/maintenance-tasks/{task_id}/transition",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Safety assessments
    # ------------------------------------------------------------------

    def record_safety_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/safety-assessments", json=_clean(payload), headers=headers
        )

    def list_safety_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/safety-assessments", headers=headers, params=params)

    def get_safety_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self.get(
            f"{API_PREFIX}/safety-assessments/{assessment_id}", headers=headers
        )

    def void_safety_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/safety-assessments/{assessment_id}/void",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Remediation orders
    # ------------------------------------------------------------------

    def list_remediation_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/remediation-orders", headers=headers, params=params)

    def get_remediation_order(self, order_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/remediation-orders/{order_id}", headers=headers)

    def submit_verification(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/remediation-orders/{order_id}/submit-verification",
            json=_clean(payload),
            headers=headers,
        )

    def decide_verification(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/remediation-orders/{order_id}/decide-verification",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Usage bookings
    # ------------------------------------------------------------------

    def create_usage_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/usage-bookings", json=_clean(payload), headers=headers
        )

    def list_usage_bookings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/usage-bookings", headers=headers, params=params)

    def get_usage_booking(self, booking_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/usage-bookings/{booking_id}", headers=headers)

    def confirm_usage_booking(
        self,
        booking_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self.post(
            f"{API_PREFIX}/usage-bookings/{booking_id}/confirm",
            json=_clean(payload) if payload is not None else {},
            headers=headers,
        )

    def close_out_usage_booking(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/usage-bookings/{booking_id}/close-out",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Usage ledger entries
    # ------------------------------------------------------------------

    def list_usage_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/usage-ledger-entries", headers=headers, params=params
        )

    def get_usage_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/usage-ledger-entries/{entry_id}", headers=headers)

    # ------------------------------------------------------------------
    # Certification packets
    # ------------------------------------------------------------------

    def create_certification_packet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/certification-packets", json=_clean(payload), headers=headers
        )

    def list_certification_packets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(
            f"{API_PREFIX}/certification-packets", headers=headers, params=params
        )

    def get_certification_packet(self, packet_id: str, headers: Dict[str, str]):
        return self.get(
            f"{API_PREFIX}/certification-packets/{packet_id}", headers=headers
        )

    def submit_certification_packet(
        self, packet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/certification-packets/{packet_id}/submit",
            json=_clean(payload),
            headers=headers,
        )

    def decide_certification_packet(
        self, packet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/certification-packets/{packet_id}/decide",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Capital budgets
    # ------------------------------------------------------------------

    def create_capital_budget(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/capital-budgets", json=_clean(payload), headers=headers
        )

    def get_capital_budget(self, budget_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/capital-budgets/{budget_id}", headers=headers)

    # ------------------------------------------------------------------
    # Replacement plans
    # ------------------------------------------------------------------

    def create_replacement_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            f"{API_PREFIX}/replacement-plans", json=_clean(payload), headers=headers
        )

    def list_replacement_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get(f"{API_PREFIX}/replacement-plans", headers=headers, params=params)

    def get_replacement_plan(self, plan_id: str, headers: Dict[str, str]):
        return self.get(f"{API_PREFIX}/replacement-plans/{plan_id}", headers=headers)

    def submit_replacement_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/replacement-plans/{plan_id}/submit",
            json=_clean(payload),
            headers=headers,
        )

    def decide_replacement_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/replacement-plans/{plan_id}/decide",
            json=_clean(payload),
            headers=headers,
        )

    def record_disposal_manifest(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/replacement-plans/{plan_id}/disposal-manifest",
            json=_clean(payload),
            headers=headers,
        )

    def complete_disposal(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            f"{API_PREFIX}/replacement-plans/{plan_id}/complete",
            json=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self.post(
            "/_clock/set_current_utc", json={"to_iso8601": to_iso8601}, headers=headers
        )
