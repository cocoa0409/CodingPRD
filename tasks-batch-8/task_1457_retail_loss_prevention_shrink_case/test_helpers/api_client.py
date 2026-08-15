"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def retention_sweep(self, headers):
        return self._request("POST", "/ops/retention-sweep", {}, headers)

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def close_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/close", {}, headers)

    # --- Employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def suspend_employee(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/suspend", {}, headers)

    def reinstate_employee(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/reinstate", {}, headers)

    # --- POS exception events ---
    def create_exception_event(self, payload, headers):
        return self._request("POST", "/exception-events", payload, headers)

    def list_exception_events(self, headers, params=None):
        return self._request("GET", "/exception-events", headers=headers, params=params)

    def get_exception_event(self, event_id, headers):
        return self._request("GET", f"/exception-events/{event_id}", headers=headers)

    # --- Alerts ---
    def list_alerts(self, headers, params=None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    def dismiss_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/dismiss", payload, headers)

    def convert_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/convert", payload, headers)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def get_case_summary(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/summary", headers=headers)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assign", payload, headers)

    def advance_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/advance", payload, headers)

    def dismiss_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/dismiss", payload, headers)

    def adjudicate_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/adjudicate", payload, headers)

    def reopen_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/reopen", payload, headers)

    def merge_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/merge", payload, headers)

    def resolve_case_subject(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/resolve-subject", payload, headers)

    def close_case_referred(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/close-referred", {}, headers)

    # --- Interviews ---
    def create_interview(self, payload, headers):
        return self._request("POST", "/interviews", payload, headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/interviews", headers=headers, params=params)

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/interviews/{interview_id}", headers=headers)

    def record_interview_outcome(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/interviews/{interview_id}/record-outcome", payload, headers
        )

    def document_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/interviews/{interview_id}/document", payload, headers
        )

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"/interviews/{interview_id}/cancel", {}, headers)

    # --- Evidence items & custody ---
    def create_evidence_item(self, payload, headers):
        return self._request("POST", "/evidence-items", payload, headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, evidence_id, headers):
        return self._request("GET", f"/evidence-items/{evidence_id}", headers=headers)

    def seal_evidence(self, evidence_id, headers):
        return self._request("POST", f"/evidence-items/{evidence_id}/seal", {}, headers)

    def unseal_evidence(self, evidence_id, headers):
        return self._request("POST", f"/evidence-items/{evidence_id}/unseal", {}, headers)

    def release_evidence(self, evidence_id, headers):
        return self._request("POST", f"/evidence-items/{evidence_id}/release", {}, headers)

    def create_custody_event(self, evidence_id, payload, headers):
        return self._request(
            "POST", f"/evidence-items/{evidence_id}/custody-events", payload, headers
        )

    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/custody-events", headers=headers, params=params)

    def get_custody_event(self, custody_event_id, headers):
        return self._request("GET", f"/custody-events/{custody_event_id}", headers=headers)

    # --- Civil demands ---
    def create_civil_demand(self, payload, headers):
        return self._request("POST", "/civil-demands", payload, headers)

    def list_civil_demands(self, headers, params=None):
        return self._request("GET", "/civil-demands", headers=headers, params=params)

    def get_civil_demand(self, demand_id, headers):
        return self._request("GET", f"/civil-demands/{demand_id}", headers=headers)

    def issue_civil_demand(self, demand_id, headers):
        return self._request("POST", f"/civil-demands/{demand_id}/issue", {}, headers)

    def write_off_civil_demand(self, demand_id, headers):
        return self._request("POST", f"/civil-demands/{demand_id}/write-off", {}, headers)

    def cancel_civil_demand(self, demand_id, headers):
        return self._request("POST", f"/civil-demands/{demand_id}/cancel", {}, headers)

    # --- Restitution payments ---
    def create_restitution_payment(self, payload, headers):
        return self._request("POST", "/restitution-payments", payload, headers)

    def list_restitution_payments(self, headers, params=None):
        return self._request("GET", "/restitution-payments", headers=headers, params=params)

    def get_restitution_payment(self, payment_id, headers):
        return self._request("GET", f"/restitution-payments/{payment_id}", headers=headers)

    def post_restitution_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/restitution-payments/{payment_id}/post", {}, headers
        )

    def return_restitution_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/restitution-payments/{payment_id}/return", {}, headers
        )

    # --- ORC groups & case links ---
    def create_orc_group(self, payload, headers):
        return self._request("POST", "/orc-groups", payload, headers)

    def list_orc_groups(self, headers, params=None):
        return self._request("GET", "/orc-groups", headers=headers, params=params)

    def get_orc_group(self, group_id, headers):
        return self._request("GET", f"/orc-groups/{group_id}", headers=headers)

    def disrupt_orc_group(self, group_id, headers):
        return self._request("POST", f"/orc-groups/{group_id}/disrupt", {}, headers)

    def dismiss_orc_group(self, group_id, headers):
        return self._request("POST", f"/orc-groups/{group_id}/dismiss", {}, headers)

    def create_case_link(self, payload, headers):
        return self._request("POST", "/case-links", payload, headers)

    def list_case_links(self, headers, params=None):
        return self._request("GET", "/case-links", headers=headers, params=params)

    def get_case_link(self, link_id, headers):
        return self._request("GET", f"/case-links/{link_id}", headers=headers)

    def confirm_case_link(self, link_id, headers):
        return self._request("POST", f"/case-links/{link_id}/confirm", {}, headers)

    def reject_case_link(self, link_id, headers):
        return self._request("POST", f"/case-links/{link_id}/reject", {}, headers)

    # --- Shrink periods ---
    def create_shrink_period(self, payload, headers):
        return self._request("POST", "/shrink-periods", payload, headers)

    def list_shrink_periods(self, headers, params=None):
        return self._request("GET", "/shrink-periods", headers=headers, params=params)

    def get_shrink_period(self, period_id, headers):
        return self._request("GET", f"/shrink-periods/{period_id}", headers=headers)

    def record_shrink_count(self, period_id, payload, headers):
        return self._request(
            "POST", f"/shrink-periods/{period_id}/record-count", payload, headers
        )

    def reconcile_shrink_period(self, period_id, headers):
        return self._request("POST", f"/shrink-periods/{period_id}/reconcile", {}, headers)

    def close_shrink_period(self, period_id, headers):
        return self._request("POST", f"/shrink-periods/{period_id}/close", {}, headers)

    # --- Referral packets ---
    def create_referral_packet(self, payload, headers):
        return self._request("POST", "/referral-packets", payload, headers)

    def list_referral_packets(self, headers, params=None):
        return self._request("GET", "/referral-packets", headers=headers, params=params)

    def get_referral_packet(self, packet_id, headers):
        return self._request("GET", f"/referral-packets/{packet_id}", headers=headers)

    def seal_referral_packet(self, packet_id, headers):
        return self._request("POST", f"/referral-packets/{packet_id}/seal", {}, headers)

    def submit_referral_packet(self, packet_id, headers):
        return self._request("POST", f"/referral-packets/{packet_id}/submit", {}, headers)

    def acknowledge_referral_packet(self, packet_id, payload, headers):
        return self._request(
            "POST", f"/referral-packets/{packet_id}/acknowledge", payload, headers
        )

    def revise_referral_packet(self, packet_id, headers):
        return self._request("POST", f"/referral-packets/{packet_id}/revise", {}, headers)


api_client = ApiClient()
