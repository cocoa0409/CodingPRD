"""One method per endpoint declared in PRD §4.

Every method returns the raw ``requests.Response`` so tests can assert status
codes.  Path ids are always taken as plain strings and interpolated verbatim,
which lets tests probe unknown-id behaviour with values the API never issues.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Typed access to the cloud cost allocation & chargeback API."""

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    # ─── Business units ───────────────────────────────────────────────────
    def create_business_unit(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/business-units", payload, headers)

    def list_business_units(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/business-units", params, headers)

    def get_business_unit(self, bu_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/business-units/{bu_id}", None, headers)

    def patch_business_unit(self, bu_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "PATCH", f"{API_PREFIX}/business-units/{bu_id}", payload, headers
        )

    # ─── Tagging policies ─────────────────────────────────────────────────
    def create_tagging_policy(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/tagging-policies", payload, headers)

    def list_tagging_policies(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/tagging-policies", params, headers)

    def get_tagging_policy(self, policy_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/tagging-policies/{policy_id}", None, headers
        )

    def amend_tagging_policy(self, policy_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "PUT", f"{API_PREFIX}/tagging-policies/{policy_id}", payload, headers
        )

    def activate_tagging_policy(self, policy_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/tagging-policies/{policy_id}/activate", {}, headers
        )

    def retire_tagging_policy(self, policy_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/tagging-policies/{policy_id}/retire", {}, headers
        )

    # ─── Provisioning requests ────────────────────────────────────────────
    def create_provisioning_request(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/provisioning-requests", payload, headers
        )

    def list_provisioning_requests(self, headers: Headers = None, params: Params = None):
        return self._request(
            "GET", f"{API_PREFIX}/provisioning-requests", params, headers
        )

    def get_provisioning_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/provisioning-requests/{request_id}", None, headers
        )

    def retag_provisioning_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/provisioning-requests/{request_id}/retag",
            payload,
            headers,
        )

    def approve_provisioning_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/provisioning-requests/{request_id}/approve", {}, headers
        )

    def provision_provisioning_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/provisioning-requests/{request_id}/provision",
            {},
            headers,
        )

    # ─── Cloud resources ──────────────────────────────────────────────────
    def list_cloud_resources(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/cloud-resources", params, headers)

    def get_cloud_resource(self, resource_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/cloud-resources/{resource_id}", None, headers
        )

    def patch_cloud_resource_telemetry(
        self, resource_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "PATCH",
            f"{API_PREFIX}/cloud-resources/{resource_id}/telemetry",
            payload,
            headers,
        )

    # ─── Cost records ─────────────────────────────────────────────────────
    def create_cost_record(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/cost-records", payload, headers)

    def list_cost_records(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/cost-records", params, headers)

    def get_cost_record(self, record_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/cost-records/{record_id}", None, headers
        )

    # ─── Allocation runs ──────────────────────────────────────────────────
    def create_allocation_run(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/allocation-runs", payload, headers)

    def list_allocation_runs(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/allocation-runs", params, headers)

    def get_allocation_run(self, run_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/allocation-runs/{run_id}", None, headers
        )

    def create_shared_cost_pool(self, run_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/allocation-runs/{run_id}/shared-cost-pools",
            payload,
            headers,
        )

    def list_shared_cost_pools(self, run_id: str, headers: Headers = None, params: Params = None):
        return self._request(
            "GET",
            f"{API_PREFIX}/allocation-runs/{run_id}/shared-cost-pools",
            params,
            headers,
        )

    def compute_allocation_run(self, run_id: str, variant: str, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/allocation-runs/{run_id}/compute",
            {"variant": variant},
            headers,
        )

    def create_manual_adjustment(self, run_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/allocation-runs/{run_id}/manual-adjustments",
            payload,
            headers,
        )

    def publish_allocation_run(self, run_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/allocation-runs/{run_id}/publish", {}, headers
        )

    def reopen_allocation_run(self, run_id: str, reason: str, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/allocation-runs/{run_id}/reopen",
            {"reason": reason},
            headers,
        )

    def close_allocation_run(self, run_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/allocation-runs/{run_id}/close", {}, headers
        )

    # ─── Shared cost pools ────────────────────────────────────────────────
    def get_shared_cost_pool(self, pool_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/shared-cost-pools/{pool_id}", None, headers
        )

    def absorb_untagged(self, pool_id: str, cost_record_ids, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shared-cost-pools/{pool_id}/absorb-untagged",
            {"cost_record_ids": list(cost_record_ids)},
            headers,
        )

    def seal_shared_cost_pool(self, pool_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/shared-cost-pools/{pool_id}/seal", {}, headers
        )

    # ─── Allocation lines ─────────────────────────────────────────────────
    def list_allocation_lines(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/allocation-lines", params, headers)

    def get_allocation_line(self, line_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/allocation-lines/{line_id}", None, headers
        )

    # ─── Chargeback invoices ──────────────────────────────────────────────
    def list_chargeback_invoices(self, headers: Headers = None, params: Params = None):
        return self._request(
            "GET", f"{API_PREFIX}/chargeback-invoices", params, headers
        )

    def get_chargeback_invoice(self, invoice_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/chargeback-invoices/{invoice_id}", None, headers
        )

    def issue_invoice(self, invoice_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/chargeback-invoices/{invoice_id}/issue", {}, headers
        )

    def settle_invoice(self, invoice_id: str, payment_cents: int, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/chargeback-invoices/{invoice_id}/settle",
            {"payment_cents": payment_cents},
            headers,
        )

    def write_off_invoice(
        self, invoice_id: str, memo: str = "uncollectable", headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/chargeback-invoices/{invoice_id}/write-off",
            {"memo": memo},
            headers,
        )

    # ─── Disputes ─────────────────────────────────────────────────────────
    def create_dispute(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/disputes", payload, headers)

    def list_disputes(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/disputes", params, headers)

    def get_dispute(self, dispute_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/disputes/{dispute_id}", None, headers)

    def start_review_dispute(self, dispute_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/disputes/{dispute_id}/start-review", {}, headers
        )

    def request_info_dispute(self, dispute_id: str, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/disputes/{dispute_id}/request-info",
            payload if payload is not None else {},
            headers,
        )

    def respond_dispute(self, dispute_id: str, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/disputes/{dispute_id}/respond",
            payload if payload is not None else {},
            headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/disputes/{dispute_id}/resolve", payload, headers
        )

    def withdraw_dispute(self, dispute_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/disputes/{dispute_id}/withdraw", {}, headers
        )

    # ─── Commitments ──────────────────────────────────────────────────────
    def create_commitment(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/commitments", payload, headers)

    def list_commitments(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/commitments", params, headers)

    def get_commitment(self, commitment_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/commitments/{commitment_id}", None, headers
        )

    def activate_commitment(self, commitment_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/commitments/{commitment_id}/activate", {}, headers
        )

    def evaluate_commitment(self, commitment_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/commitments/{commitment_id}/evaluate", {}, headers
        )

    # ─── Remediation ──────────────────────────────────────────────────────
    def run_idle_detection_scan(self, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/scans/idle-detection",
            payload if payload is not None else {},
            headers,
        )

    def create_remediation_task(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/remediation-tasks", payload, headers
        )

    def list_remediation_tasks(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/remediation-tasks", params, headers)

    def get_remediation_task(self, task_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/remediation-tasks/{task_id}", None, headers
        )

    def notify_owner(self, task_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/remediation-tasks/{task_id}/notify-owner", {}, headers
        )

    def snooze_remediation_task(self, task_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/remediation-tasks/{task_id}/snooze", {}, headers
        )

    def approve_remediation_task(self, task_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/remediation-tasks/{task_id}/approve", {}, headers
        )

    def cancel_remediation_task(
        self, task_id: str, reason: str = "no longer needed", headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/remediation-tasks/{task_id}/cancel",
            {"reason": reason},
            headers,
        )

    def run_remediation_window_sweep(self, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/scans/remediation-window-sweep", {}, headers
        )

    # ─── Anomaly detection ────────────────────────────────────────────────
    def run_anomaly_scan(self, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/anomaly-scans",
            payload if payload is not None else {},
            headers,
        )

    def list_anomaly_alerts(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/anomaly-alerts", params, headers)

    def get_anomaly_alert(self, alert_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/anomaly-alerts/{alert_id}", None, headers
        )

    def acknowledge_anomaly_alert(self, alert_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/anomaly-alerts/{alert_id}/acknowledge", {}, headers
        )

    def attribute_anomaly_alert(self, alert_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/anomaly-alerts/{alert_id}/attribute", payload, headers
        )

    def close_anomaly_alert(self, alert_id: str, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/anomaly-alerts/{alert_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ─── Budgets ──────────────────────────────────────────────────────────
    def create_budget(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/budgets", payload, headers)

    def list_budgets(self, headers: Headers = None, params: Params = None):
        return self._request("GET", f"{API_PREFIX}/budgets", params, headers)

    def get_budget(self, budget_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/budgets/{budget_id}", None, headers)

    def activate_budget(self, budget_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/activate", {}, headers
        )

    def revise_budget(self, budget_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/revise", payload, headers
        )

    def evaluate_budget(self, budget_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/evaluate", {}, headers
        )

    def explain_budget_variance(self, budget_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/budgets/{budget_id}/variance-explanation",
            payload,
            headers,
        )

    def close_budget(self, budget_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/close", {}, headers
        )

    # ─── Unit economics ───────────────────────────────────────────────────
    def create_unit_economics_driver(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/unit-economics-drivers", payload, headers
        )

    def list_unit_economics_drivers(self, headers: Headers = None, params: Params = None):
        return self._request(
            "GET", f"{API_PREFIX}/unit-economics-drivers", params, headers
        )

    def get_unit_economics_driver(self, driver_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/unit-economics-drivers/{driver_id}", None, headers
        )

    def compute_unit_economics_driver(self, driver_id: str, headers: Headers = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/unit-economics-drivers/{driver_id}/compute",
            {},
            headers,
        )


# Module-level singleton reused by every test.
api_client = ApiClient()
