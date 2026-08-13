"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- DataField / dictionary ---
    def create_data_field(self, payload, headers):
        return self._request("POST", "/hris/data-fields", payload, headers)

    def list_data_fields(self, headers, params=None):
        return self._request("GET", "/hris/data-fields", headers=headers, params=params)

    def get_data_field(self, data_field_id, headers):
        return self._request("GET", f"/hris/data-fields/{data_field_id}", headers=headers)

    def activate_data_field(self, data_field_id, headers):
        return self._request("POST", f"/hris/data-fields/{data_field_id}/activate", {}, headers)

    def deprecate_data_field(self, data_field_id, headers):
        return self._request("POST", f"/hris/data-fields/{data_field_id}/deprecate", {}, headers)

    def list_field_dq_rules(self, data_field_id, headers, params=None):
        return self._request(
            "GET", f"/hris/data-fields/{data_field_id}/data-quality-rules",
            headers=headers, params=params,
        )

    # --- DataQualityRule ---
    def create_data_quality_rule(self, payload, headers):
        return self._request("POST", "/hris/data-quality-rules", payload, headers)

    def patch_data_quality_rule(self, rule_id, payload, headers):
        return self._request("PATCH", f"/hris/data-quality-rules/{rule_id}", payload, headers)

    # --- Position ---
    def create_position(self, payload, headers):
        return self._request("POST", "/hris/positions", payload, headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/hris/positions", headers=headers, params=params)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/hris/positions/{position_id}", headers=headers)

    def close_position(self, position_id, headers):
        return self._request("POST", f"/hris/positions/{position_id}/close", {}, headers)

    def get_subtree_metrics(self, position_id, headers, params=None):
        return self._request(
            "GET", f"/hris/positions/{position_id}/subtree-metrics",
            headers=headers, params=params,
        )

    # --- Worker ---
    def create_worker(self, payload, headers):
        return self._request("POST", "/hris/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/hris/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/hris/workers/{worker_id}", headers=headers)

    def terminate_worker(self, worker_id, payload, headers):
        return self._request("POST", f"/hris/workers/{worker_id}/terminate", payload, headers)

    def get_field_history(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/hris/workers/{worker_id}/field-history",
            headers=headers, params=params,
        )

    # --- PositionAssignment (read-only) ---
    def list_position_assignments(self, headers, params=None):
        return self._request("GET", "/hris/position-assignments", headers=headers, params=params)

    def get_position_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/hris/position-assignments/{assignment_id}", headers=headers
        )

    # --- ChangeRequest ---
    def create_worker_change_request(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/hris/workers/{worker_id}/change-requests", payload, headers
        )

    def create_position_change_request(self, position_id, payload, headers):
        return self._request(
            "POST", f"/hris/positions/{position_id}/change-requests", payload, headers
        )

    def list_change_requests(self, headers, params=None):
        return self._request("GET", "/hris/change-requests", headers=headers, params=params)

    def get_change_request(self, change_request_id, headers):
        return self._request(
            "GET", f"/hris/change-requests/{change_request_id}", headers=headers
        )

    def approve_change_request(self, change_request_id, headers):
        return self._request(
            "POST", f"/hris/change-requests/{change_request_id}/approve", {}, headers
        )

    def reject_change_request(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"/hris/change-requests/{change_request_id}/reject", payload, headers
        )

    def apply_change_request(self, change_request_id, headers):
        return self._request(
            "POST", f"/hris/change-requests/{change_request_id}/apply", {}, headers
        )

    def void_change_request(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"/hris/change-requests/{change_request_id}/void", payload, headers
        )

    # --- MassChangeBatch / BatchLine ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/hris/mass-change-batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/hris/mass-change-batches/{batch_id}", headers=headers)

    def add_batch_line(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/hris/mass-change-batches/{batch_id}/lines", payload, headers
        )

    def list_batch_lines(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/hris/mass-change-batches/{batch_id}/lines",
            headers=headers, params=params,
        )

    def list_all_batch_lines(self, headers, params=None):
        return self._request("GET", "/hris/batch-lines", headers=headers, params=params)

    def get_batch_line(self, line_id, headers):
        return self._request("GET", f"/hris/batch-lines/{line_id}", headers=headers)

    def submit_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/hris/mass-change-batches/{batch_id}/submit", payload, headers
        )

    def reopen_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/hris/mass-change-batches/{batch_id}/reopen", {}, headers
        )

    def schedule_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/hris/mass-change-batches/{batch_id}/schedule", payload, headers
        )

    def execute_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/hris/mass-change-batches/{batch_id}/execute", {}, headers
        )

    def rollback_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/hris/mass-change-batches/{batch_id}/rollback", {}, headers
        )

    # --- IntegrationEvent ---
    def list_integration_events(self, headers, params=None):
        return self._request("GET", "/hris/integration-events", headers=headers, params=params)

    def get_integration_event(self, event_id, headers):
        return self._request("GET", f"/hris/integration-events/{event_id}", headers=headers)

    def dispatch_integration_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/hris/integration-events/{event_id}/dispatch", payload, headers
        )

    def retry_integration_event(self, event_id, headers):
        return self._request(
            "POST", f"/hris/integration-events/{event_id}/retry", {}, headers
        )

    def resolve_integration_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/hris/integration-events/{event_id}/resolve", payload, headers
        )

    # --- ExceptionRecord ---
    def list_exception_records(self, headers, params=None):
        return self._request("GET", "/hris/exception-records", headers=headers, params=params)

    def get_exception_record(self, exception_id, headers):
        return self._request("GET", f"/hris/exception-records/{exception_id}", headers=headers)

    def resolve_exception_record(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/hris/exception-records/{exception_id}/resolve", payload, headers
        )

    def waive_exception_record(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/hris/exception-records/{exception_id}/waive", payload, headers
        )

    # --- SecurityRoleAssignment ---
    def create_security_role_assignment(self, payload, headers):
        return self._request("POST", "/hris/security-role-assignments", payload, headers)

    def list_security_role_assignments(self, headers, params=None):
        return self._request(
            "GET", "/hris/security-role-assignments", headers=headers, params=params
        )

    def approve_security_role_assignment(self, grant_id, headers):
        return self._request(
            "POST", f"/hris/security-role-assignments/{grant_id}/approve", {}, headers
        )

    def revoke_security_role_assignment(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/hris/security-role-assignments/{grant_id}/revoke", payload, headers
        )

    # --- AuditEntry ---
    def list_audit_entries(self, headers, params=None):
        return self._request("GET", "/hris/audit-entries", headers=headers, params=params)

    def get_audit_entry(self, audit_entry_id, headers):
        return self._request("GET", f"/hris/audit-entries/{audit_entry_id}", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
