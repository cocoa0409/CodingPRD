"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Governance programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/ig/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/ig/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/ig/programs/{program_id}", headers=headers)

    # ------------------------------------------------------------------
    # Record classes
    # ------------------------------------------------------------------
    def create_record_class(self, payload, headers):
        return self._request("POST", "/ig/record-classes", payload, headers)

    def list_record_classes(self, headers, params=None):
        return self._request("GET", "/ig/record-classes", headers=headers, params=params)

    def get_record_class(self, class_id, headers):
        return self._request("GET", f"/ig/record-classes/{class_id}", headers=headers)

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/ig/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/ig/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/ig/jurisdictions/{jurisdiction_id}", headers=headers)

    # ------------------------------------------------------------------
    # Custodians
    # ------------------------------------------------------------------
    def create_custodian(self, payload, headers):
        return self._request("POST", "/ig/custodians", payload, headers)

    def list_custodians(self, headers, params=None):
        return self._request("GET", "/ig/custodians", headers=headers, params=params)

    def get_custodian(self, custodian_id, headers):
        return self._request("GET", f"/ig/custodians/{custodian_id}", headers=headers)

    # ------------------------------------------------------------------
    # Retention rules
    # ------------------------------------------------------------------
    def create_retention_rule(self, payload, headers):
        return self._request("POST", "/ig/retention-rules", payload, headers)

    def supersede_retention_rule(self, rule_id, payload, headers):
        return self._request("POST", f"/ig/retention-rules/{rule_id}/supersede",
                             payload, headers)

    def list_retention_rules(self, headers, params=None):
        return self._request("GET", "/ig/retention-rules", headers=headers, params=params)

    def get_retention_rule(self, rule_id, headers):
        return self._request("GET", f"/ig/retention-rules/{rule_id}", headers=headers)

    def activate_retention_rule(self, rule_id, headers):
        return self._request("POST", f"/ig/retention-rules/{rule_id}/activate", {}, headers)

    def withdraw_retention_rule(self, rule_id, headers):
        return self._request("POST", f"/ig/retention-rules/{rule_id}/withdraw", {}, headers)

    def retire_retention_rule(self, rule_id, headers):
        return self._request("POST", f"/ig/retention-rules/{rule_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Retention conflicts
    # ------------------------------------------------------------------
    def list_retention_conflicts(self, headers, params=None):
        return self._request("GET", "/ig/retention-conflicts", headers=headers, params=params)

    def get_retention_conflict(self, conflict_id, headers):
        return self._request("GET", f"/ig/retention-conflicts/{conflict_id}", headers=headers)

    def resolve_retention_conflict(self, conflict_id, payload, headers):
        return self._request("POST", f"/ig/retention-conflicts/{conflict_id}/resolve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------
    def create_record(self, payload, headers):
        return self._request("POST", "/ig/records", payload, headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/ig/records", headers=headers, params=params)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/ig/records/{record_id}", headers=headers)

    def patch_record(self, record_id, payload, headers):
        return self._request("PATCH", f"/ig/records/{record_id}", payload, headers)

    # ------------------------------------------------------------------
    # Legal holds
    # ------------------------------------------------------------------
    def create_legal_hold(self, payload, headers):
        return self._request("POST", "/ig/legal-holds", payload, headers)

    def list_legal_holds(self, headers, params=None):
        return self._request("GET", "/ig/legal-holds", headers=headers, params=params)

    def get_legal_hold(self, hold_id, headers):
        return self._request("GET", f"/ig/legal-holds/{hold_id}", headers=headers)

    def issue_legal_hold(self, hold_id, headers):
        return self._request("POST", f"/ig/legal-holds/{hold_id}/issue", {}, headers)

    def cancel_legal_hold(self, hold_id, headers):
        return self._request("POST", f"/ig/legal-holds/{hold_id}/cancel", {}, headers)

    def release_legal_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/ig/legal-holds/{hold_id}/release", payload, headers)

    def add_scope_items(self, hold_id, payload, headers):
        return self._request("POST", f"/ig/legal-holds/{hold_id}/scope-items",
                             payload, headers)

    def delete_scope_item(self, hold_id, item_id, headers):
        return self._request("DELETE",
                             f"/ig/legal-holds/{hold_id}/scope-items/{item_id}",
                             headers=headers)

    def add_hold_custodians(self, hold_id, payload, headers):
        return self._request("POST", f"/ig/legal-holds/{hold_id}/custodians",
                             payload, headers)

    # ------------------------------------------------------------------
    # Hold custodian assignments
    # ------------------------------------------------------------------
    def list_hold_custodians(self, headers, params=None):
        return self._request("GET", "/ig/hold-custodians", headers=headers, params=params)

    def get_hold_custodian(self, assignment_id, headers):
        return self._request("GET", f"/ig/hold-custodians/{assignment_id}", headers=headers)

    def acknowledge_hold_custodian(self, assignment_id, headers):
        return self._request("POST",
                             f"/ig/hold-custodians/{assignment_id}/acknowledge",
                             {}, headers)

    # ------------------------------------------------------------------
    # Hold scope items (read)
    # ------------------------------------------------------------------
    def list_hold_scope_items(self, headers, params=None):
        return self._request("GET", "/ig/hold-scope-items", headers=headers, params=params)

    def get_hold_scope_item(self, item_id, headers):
        return self._request("GET", f"/ig/hold-scope-items/{item_id}", headers=headers)

    # ------------------------------------------------------------------
    # Disposition requests
    # ------------------------------------------------------------------
    def create_disposition_request(self, payload, headers):
        return self._request("POST", "/ig/disposition-requests", payload, headers)

    def list_disposition_requests(self, headers, params=None):
        return self._request("GET", "/ig/disposition-requests", headers=headers, params=params)

    def get_disposition_request(self, request_id, headers):
        return self._request("GET", f"/ig/disposition-requests/{request_id}",
                             headers=headers)

    def submit_disposition_request(self, request_id, headers):
        return self._request("POST", f"/ig/disposition-requests/{request_id}/submit",
                             {}, headers)

    def refresh_disposition_request(self, request_id, headers):
        return self._request("POST",
                             f"/ig/disposition-requests/{request_id}/refresh-snapshots",
                             {}, headers)

    def approve_disposition_request(self, request_id, headers):
        return self._request("POST", f"/ig/disposition-requests/{request_id}/approve",
                             {}, headers)

    def reject_disposition_request(self, request_id, payload, headers):
        return self._request("POST", f"/ig/disposition-requests/{request_id}/reject",
                             payload, headers)

    def revise_disposition_request(self, request_id, headers):
        return self._request("POST", f"/ig/disposition-requests/{request_id}/revise",
                             {}, headers)

    def withdraw_disposition_request(self, request_id, headers):
        return self._request("POST", f"/ig/disposition-requests/{request_id}/withdraw",
                             {}, headers)

    def execute_disposition_request(self, request_id, headers):
        return self._request("POST", f"/ig/disposition-requests/{request_id}/execute",
                             {}, headers)

    # ------------------------------------------------------------------
    # Disposition items (read)
    # ------------------------------------------------------------------
    def list_disposition_items(self, headers, params=None):
        return self._request("GET", "/ig/disposition-items", headers=headers, params=params)

    def get_disposition_item(self, item_id, headers):
        return self._request("GET", f"/ig/disposition-items/{item_id}", headers=headers)

    # ------------------------------------------------------------------
    # Destruction certificates (read-only)
    # ------------------------------------------------------------------
    def list_destruction_certificates(self, headers, params=None):
        return self._request("GET", "/ig/destruction-certificates",
                             headers=headers, params=params)

    def get_destruction_certificate(self, certificate_id, headers):
        return self._request("GET", f"/ig/destruction-certificates/{certificate_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Hold audits
    # ------------------------------------------------------------------
    def create_hold_audit(self, payload, headers):
        return self._request("POST", "/ig/hold-audits", payload, headers)

    def list_hold_audits(self, headers, params=None):
        return self._request("GET", "/ig/hold-audits", headers=headers, params=params)

    def get_hold_audit(self, audit_id, headers):
        return self._request("GET", f"/ig/hold-audits/{audit_id}", headers=headers)

    def close_hold_audit(self, audit_id, headers):
        return self._request("POST", f"/ig/hold-audits/{audit_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Reminder log (read-only)
    # ------------------------------------------------------------------
    def list_reminder_logs(self, headers, params=None):
        return self._request("GET", "/ig/reminder-logs", headers=headers, params=params)

    def get_reminder_log(self, log_id, headers):
        return self._request("GET", f"/ig/reminder-logs/{log_id}", headers=headers)

    # ------------------------------------------------------------------
    # Disposition freeze windows
    # ------------------------------------------------------------------
    def create_freeze_window(self, payload, headers):
        return self._request("POST", "/ig/disposition-freeze-windows", payload, headers)

    def list_freeze_windows(self, headers, params=None):
        return self._request("GET", "/ig/disposition-freeze-windows",
                             headers=headers, params=params)

    def get_freeze_window(self, window_id, headers):
        return self._request("GET", f"/ig/disposition-freeze-windows/{window_id}",
                             headers=headers)

    def cancel_freeze_window(self, window_id, headers):
        return self._request("POST",
                             f"/ig/disposition-freeze-windows/{window_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Sweeps (scheduled batch operations)
    # ------------------------------------------------------------------
    def run_reminder_sweep(self, program_id, headers):
        return self._request("POST", "/ig/sweeps/reminders",
                             {"program_id": program_id}, headers)

    def run_auto_delete_sweep(self, program_id, method, headers):
        return self._request("POST", "/ig/sweeps/auto-delete",
                             {"program_id": program_id, "method": method}, headers)


api_client = ApiClient()
