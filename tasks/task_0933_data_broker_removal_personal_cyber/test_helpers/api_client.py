"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---------------- plans ----------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    # ---------------- accounts ----------------
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def resume_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/resume", {}, headers)

    def cancel_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/cancel", {}, headers)

    def set_legal_hold(self, account_id, hold_state, headers):
        return self._request("POST", f"/accounts/{account_id}/legal-hold",
                             {"hold_state": hold_state}, headers)

    def change_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/plan-changes", payload, headers)

    def list_account_members(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/members",
                             headers=headers, params=params)

    def invite_member(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/members", payload, headers)

    def list_account_addons(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/addons",
                             headers=headers, params=params)

    def create_addon(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/addons", payload, headers)

    def list_billing_cycles(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/billing-cycles",
                             headers=headers, params=params)

    def get_entitlement_statement(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/entitlement-statement",
                             headers=headers)

    # ---------------- members ----------------
    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def activate_member(self, member_id, invitation_token, headers):
        return self._request("POST", f"/members/{member_id}/activate",
                             {"invitation_token": invitation_token}, headers)

    def set_member_authorization(self, member_id, action, headers):
        return self._request("POST", f"/members/{member_id}/authorization",
                             {"action": action}, headers)

    def remove_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/remove", {}, headers)

    def list_member_profiles(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/monitored-profiles",
                             headers=headers, params=params)

    def list_member_identity_documents(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/identity-documents",
                             headers=headers, params=params)

    def create_identity_document(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/identity-documents",
                             payload, headers)

    def get_exposure_summary(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/exposure-summary", headers=headers)

    # ---------------- identity documents ----------------
    def verify_identity_document(self, document_id, headers):
        return self._request("POST", f"/identity-documents/{document_id}/verify", {}, headers)

    def reject_identity_document(self, document_id, rejection_reason_code, headers):
        return self._request("POST", f"/identity-documents/{document_id}/reject",
                             {"rejection_reason_code": rejection_reason_code}, headers)

    # ---------------- monitored profiles ----------------
    def create_monitored_profile(self, payload, headers):
        return self._request("POST", "/monitored-profiles", payload, headers)

    def get_monitored_profile(self, profile_id, headers):
        return self._request("GET", f"/monitored-profiles/{profile_id}", headers=headers)

    def patch_monitored_profile(self, profile_id, payload, headers):
        return self._request("PATCH", f"/monitored-profiles/{profile_id}", payload, headers)

    def activate_profile(self, profile_id, headers):
        return self._request("POST", f"/monitored-profiles/{profile_id}/activate", {}, headers)

    def pause_profile(self, profile_id, headers):
        return self._request("POST", f"/monitored-profiles/{profile_id}/pause", {}, headers)

    def retire_profile(self, profile_id, headers):
        return self._request("POST", f"/monitored-profiles/{profile_id}/retire", {}, headers)

    def add_identifier(self, profile_id, payload, headers):
        return self._request("POST", f"/monitored-profiles/{profile_id}/identifiers",
                             payload, headers)

    def list_identifiers(self, profile_id, headers, params=None):
        return self._request("GET", f"/monitored-profiles/{profile_id}/identifiers",
                             headers=headers, params=params)

    def get_hygiene_score(self, profile_id, headers):
        return self._request("GET", f"/monitored-profiles/{profile_id}/hygiene-score",
                             headers=headers)

    # ---------------- brokers ----------------
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def retire_broker(self, broker_id, headers):
        return self._request("POST", f"/brokers/{broker_id}/retire", {}, headers)

    def get_compliance_report(self, broker_id, headers, params=None):
        return self._request("GET", f"/brokers/{broker_id}/compliance-report",
                             headers=headers, params=params)

    # ---------------- scan runs ----------------
    def create_scan_run(self, payload, headers):
        return self._request("POST", "/scan-runs", payload, headers)

    def list_scan_runs(self, headers, params=None):
        return self._request("GET", "/scan-runs", headers=headers, params=params)

    def get_scan_run(self, scan_id, headers):
        return self._request("GET", f"/scan-runs/{scan_id}", headers=headers)

    def start_scan(self, scan_id, headers):
        return self._request("POST", f"/scan-runs/{scan_id}/start", {}, headers)

    def record_finding(self, scan_id, payload, headers):
        return self._request("POST", f"/scan-runs/{scan_id}/findings", payload, headers)

    def complete_scan(self, scan_id, headers):
        return self._request("POST", f"/scan-runs/{scan_id}/complete", {}, headers)

    def fail_scan(self, scan_id, failure_reason, headers):
        return self._request("POST", f"/scan-runs/{scan_id}/fail",
                             {"failure_reason": failure_reason}, headers)

    def retry_scan(self, scan_id, headers):
        return self._request("POST", f"/scan-runs/{scan_id}/retry", {}, headers)

    def cancel_scan(self, scan_id, headers):
        return self._request("POST", f"/scan-runs/{scan_id}/cancel", {}, headers)

    # ---------------- exposures ----------------
    def list_exposures(self, headers, params=None):
        return self._request("GET", "/exposures", headers=headers, params=params)

    def get_exposure(self, exposure_id, headers):
        return self._request("GET", f"/exposures/{exposure_id}", headers=headers)

    # ---------------- removal requests ----------------
    def create_removal_request(self, exposure_id, headers):
        return self._request("POST", "/removal-requests", {"exposure_id": exposure_id}, headers)

    def list_removal_requests(self, headers, params=None):
        return self._request("GET", "/removal-requests", headers=headers, params=params)

    def get_removal_request(self, request_id, headers):
        return self._request("GET", f"/removal-requests/{request_id}", headers=headers)

    def submit_removal_request(self, request_id, headers):
        return self._request("POST", f"/removal-requests/{request_id}/submit", {}, headers)

    def acknowledge_removal_request(self, request_id, broker_reference, headers):
        return self._request("POST", f"/removal-requests/{request_id}/acknowledge",
                             {"broker_reference": broker_reference}, headers)

    def complete_removal_request(self, request_id, headers):
        return self._request("POST", f"/removal-requests/{request_id}/complete", {}, headers)

    def reject_removal_request(self, request_id, rejection_reason_code, headers):
        return self._request("POST", f"/removal-requests/{request_id}/reject",
                             {"rejection_reason_code": rejection_reason_code}, headers)

    def expire_removal_request(self, request_id, headers):
        return self._request("POST", f"/removal-requests/{request_id}/expire", {}, headers)

    def escalate_removal_request(self, request_id, headers):
        return self._request("POST", f"/removal-requests/{request_id}/escalate", {}, headers)

    def void_removal_request(self, request_id, headers):
        return self._request("POST", f"/removal-requests/{request_id}/void", {}, headers)

    # ---------------- breach events / alerts ----------------
    def create_breach_event(self, payload, headers):
        return self._request("POST", "/breach-events", payload, headers)

    def ingest_breach_event(self, breach_event_id, matched_identifier_values, headers):
        return self._request("POST", f"/breach-events/{breach_event_id}/ingest",
                             {"matched_identifier_values": matched_identifier_values}, headers)

    def list_breach_alerts(self, headers, params=None):
        return self._request("GET", "/breach-alerts", headers=headers, params=params)

    def get_breach_alert(self, alert_id, headers):
        return self._request("GET", f"/breach-alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, alert_id, headers):
        return self._request("POST", f"/breach-alerts/{alert_id}/acknowledge", {}, headers)

    def resolve_alert(self, alert_id, headers):
        return self._request("POST", f"/breach-alerts/{alert_id}/resolve", {}, headers)

    # ---------------- credential findings ----------------
    def create_credential_finding(self, payload, headers):
        return self._request("POST", "/credential-findings", payload, headers)

    def list_credential_findings(self, headers, params=None):
        return self._request("GET", "/credential-findings", headers=headers, params=params)

    def get_credential_finding(self, finding_id, headers):
        return self._request("GET", f"/credential-findings/{finding_id}", headers=headers)

    def remediate_finding(self, finding_id, headers):
        return self._request("POST", f"/credential-findings/{finding_id}/remediate", {}, headers)

    def reopen_finding(self, finding_id, headers):
        return self._request("POST", f"/credential-findings/{finding_id}/reopen", {}, headers)

    # ---------------- add-ons and seats ----------------
    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/addons/{addon_id}", headers=headers)

    def suspend_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/suspend", {}, headers)

    def resume_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/resume", {}, headers)

    def create_device_seat(self, payload, headers):
        return self._request("POST", "/device-seats", payload, headers)

    def list_device_seats(self, headers, params=None):
        return self._request("GET", "/device-seats", headers=headers, params=params)

    def get_device_seat(self, seat_id, headers):
        return self._request("GET", f"/device-seats/{seat_id}", headers=headers)

    def release_seat(self, seat_id, headers):
        return self._request("POST", f"/device-seats/{seat_id}/release", {}, headers)

    def rebind_seat(self, seat_id, device_label, headers):
        return self._request("POST", f"/device-seats/{seat_id}/rebind",
                             {"device_label": device_label}, headers)

    # ---------------- billing cycles ----------------
    def close_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/billing-cycles/{cycle_id}/close", {}, headers)

    # ---------------- entitlement ledger ----------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/entitlement-ledger", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/entitlement-ledger/{entry_id}", headers=headers)

    # ---------------- raw escape hatch ----------------
    def raw(self, method, path, payload=None, headers=None, params=None):
        """Direct call for negative tests that must send a malformed or
        header-less request the typed helpers would not permit."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
