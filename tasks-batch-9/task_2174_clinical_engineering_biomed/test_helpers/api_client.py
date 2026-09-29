"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/clinical-engineering"


class ApiClient(GenericApiClient):
    # ─── Facility ──────────────────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    def set_facility_posture(self, facility_id, payload, headers):
        return self._request("POST", f"{PREFIX}/facilities/{facility_id}/posture", payload, headers)

    def run_pm_audit(self, facility_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/facilities/{facility_id}/pm-audit", payload or {}, headers)

    def get_replacement_plan(self, facility_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}/replacement-plan",
                             headers=headers, params=params)

    # ─── Department ────────────────────────────────────────────────────────
    def create_department(self, payload, headers):
        return self._request("POST", f"{PREFIX}/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"{PREFIX}/departments/{department_id}", headers=headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/departments", headers=headers, params=params)

    # ─── Vendor ────────────────────────────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    # ─── DeviceModel ───────────────────────────────────────────────────────
    def create_device_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/device-models", payload, headers)

    def get_device_model(self, model_id, headers):
        return self._request("GET", f"{PREFIX}/device-models/{model_id}", headers=headers)

    # ─── Device ────────────────────────────────────────────────────────────
    def create_device(self, payload, headers):
        return self._request("POST", f"{PREFIX}/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"{PREFIX}/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/devices", headers=headers, params=params)

    def update_device(self, device_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/devices/{device_id}", payload, headers)

    def set_device_security_state(self, device_id, payload, headers):
        return self._request("POST", f"{PREFIX}/devices/{device_id}/security-state", payload, headers)

    # ─── PMTask ────────────────────────────────────────────────────────────
    def create_pm_task(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pm-tasks", payload, headers)

    def get_pm_task(self, pm_task_id, headers):
        return self._request("GET", f"{PREFIX}/pm-tasks/{pm_task_id}", headers=headers)

    def list_pm_tasks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pm-tasks", headers=headers, params=params)

    def complete_pm_task(self, pm_task_id, payload, headers):
        return self._request("POST", f"{PREFIX}/pm-tasks/{pm_task_id}/complete", payload, headers)

    def defer_pm_task(self, pm_task_id, payload, headers):
        return self._request("POST", f"{PREFIX}/pm-tasks/{pm_task_id}/defer", payload, headers)

    # ─── WorkOrder ─────────────────────────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/assign", payload, headers)

    def parts_hold_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/parts-hold", payload or {}, headers)

    def resume_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/resume", payload or {}, headers)

    def complete_repair(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/complete-repair", payload, headers)

    def verify_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/verify", payload, headers)

    def close_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/close", payload, headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/cancel", payload, headers)

    # ─── LoanerAssignment ──────────────────────────────────────────────────
    def create_loaner_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loaner-assignments", payload, headers)

    def get_loaner_assignment(self, loaner_id, headers):
        return self._request("GET", f"{PREFIX}/loaner-assignments/{loaner_id}", headers=headers)

    def list_loaner_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loaner-assignments", headers=headers, params=params)

    def return_loaner_assignment(self, loaner_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/loaner-assignments/{loaner_id}/return", payload or {}, headers)

    # ─── RecallNotice ──────────────────────────────────────────────────────
    def create_recall_notice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/recall-notices", payload, headers)

    def get_recall_notice(self, notice_id, headers):
        return self._request("GET", f"{PREFIX}/recall-notices/{notice_id}", headers=headers)

    def list_recall_notices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/recall-notices", headers=headers, params=params)

    def publish_recall_notice(self, notice_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/recall-notices/{notice_id}/publish", payload or {}, headers)

    def close_recall_notice(self, notice_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/recall-notices/{notice_id}/close", payload or {}, headers)

    # ─── RecallMatch ───────────────────────────────────────────────────────
    def get_recall_match(self, match_id, headers):
        return self._request("GET", f"{PREFIX}/recall-matches/{match_id}", headers=headers)

    def list_recall_matches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/recall-matches", headers=headers, params=params)

    def disposition_recall_match(self, match_id, payload, headers):
        return self._request("POST", f"{PREFIX}/recall-matches/{match_id}/disposition", payload, headers)

    # ─── ServiceContract ───────────────────────────────────────────────────
    def create_service_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-contracts", payload, headers)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/service-contracts/{contract_id}", headers=headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-contracts", headers=headers, params=params)

    # ─── SecurityFinding ───────────────────────────────────────────────────
    def create_security_finding(self, payload, headers):
        return self._request("POST", f"{PREFIX}/security-findings", payload, headers)

    def get_security_finding(self, finding_id, headers):
        return self._request("GET", f"{PREFIX}/security-findings/{finding_id}", headers=headers)

    def list_security_findings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/security-findings", headers=headers, params=params)

    def resolve_security_finding(self, finding_id, payload, headers):
        return self._request("POST", f"{PREFIX}/security-findings/{finding_id}/resolve", payload, headers)

    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
