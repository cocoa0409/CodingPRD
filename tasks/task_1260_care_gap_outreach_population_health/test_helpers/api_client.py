"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/population-health"


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # --- Registries ---
    def create_registry(self, payload, headers):
        return self._request("POST", f"{BASE}/registries", payload, headers)

    def list_registries(self, headers, params=None):
        return self._request("GET", f"{BASE}/registries", headers=headers, params=params)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"{BASE}/registries/{registry_id}", headers=headers)

    # --- Measure definitions ---
    def create_measure(self, registry_id, payload, headers):
        return self._request("POST", f"{BASE}/registries/{registry_id}/measure-definitions", payload, headers)

    def publish_measure(self, measure_id, headers):
        return self._request("POST", f"{BASE}/measure-definitions/{measure_id}/publish", {}, headers)

    def list_measures(self, registry_id, headers, params=None):
        return self._request("GET", f"{BASE}/registries/{registry_id}/measure-definitions", headers=headers, params=params)

    def get_measure(self, measure_id, headers):
        return self._request("GET", f"{BASE}/measure-definitions/{measure_id}", headers=headers)

    # --- Cohort definitions ---
    def create_cohort(self, registry_id, payload, headers):
        return self._request("POST", f"{BASE}/registries/{registry_id}/cohort-definitions", payload, headers)

    def activate_cohort(self, cohort_id, headers):
        return self._request("POST", f"{BASE}/cohort-definitions/{cohort_id}/activate", {}, headers)

    def list_cohorts(self, registry_id, headers, params=None):
        return self._request("GET", f"{BASE}/registries/{registry_id}/cohort-definitions", headers=headers, params=params)

    # --- Members ---
    def create_member(self, registry_id, payload, headers):
        return self._request("POST", f"{BASE}/registries/{registry_id}/members", payload, headers)

    def list_members(self, registry_id, headers, params=None):
        return self._request("GET", f"{BASE}/registries/{registry_id}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{BASE}/members/{member_id}", headers=headers)

    def disenroll_member(self, member_id, payload, headers):
        return self._request("POST", f"{BASE}/members/{member_id}/disenroll", payload, headers)

    # --- Registry panels ---
    def create_panel(self, registry_id, payload, headers):
        return self._request("POST", f"{BASE}/registries/{registry_id}/registry-panels", payload, headers)

    def activate_panel(self, panel_id, headers):
        return self._request("POST", f"{BASE}/registry-panels/{panel_id}/activate", {}, headers)

    def rebuild_panel(self, panel_id, payload, headers):
        return self._request("POST", f"{BASE}/registry-panels/{panel_id}/rebuild", payload, headers)

    def finalize_rebuild_panel(self, panel_id, headers):
        return self._request("POST", f"{BASE}/registry-panels/{panel_id}/finalize-rebuild", {}, headers)

    def retire_panel(self, panel_id, headers):
        return self._request("POST", f"{BASE}/registry-panels/{panel_id}/retire", {}, headers)

    def list_panels(self, registry_id, headers, params=None):
        return self._request("GET", f"{BASE}/registries/{registry_id}/registry-panels", headers=headers, params=params)

    def get_panel(self, panel_id, headers):
        return self._request("GET", f"{BASE}/registry-panels/{panel_id}", headers=headers)

    def list_panel_care_gaps(self, panel_id, headers, params=None):
        return self._request("GET", f"{BASE}/registry-panels/{panel_id}/care-gaps", headers=headers, params=params)

    def list_panels_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/registry-panels", headers=headers, params=params)

    # --- Care gaps ---
    def get_care_gap(self, gap_id, headers):
        return self._request("GET", f"{BASE}/care-gaps/{gap_id}", headers=headers)

    def list_member_care_gaps(self, member_id, headers, params=None):
        return self._request("GET", f"{BASE}/members/{member_id}/care-gaps", headers=headers, params=params)

    def list_care_gaps_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/care-gaps", headers=headers, params=params)

    def reopen_care_gap(self, gap_id, payload, headers):
        return self._request("POST", f"{BASE}/care-gaps/{gap_id}/reopen", payload, headers)

    # --- Outreach campaigns ---
    def create_campaign(self, registry_id, payload, headers):
        return self._request("POST", f"{BASE}/registries/{registry_id}/outreach-campaigns", payload, headers)

    def schedule_campaign(self, campaign_id, headers):
        return self._request("POST", f"{BASE}/outreach-campaigns/{campaign_id}/schedule", {}, headers)

    def launch_campaign(self, campaign_id, headers):
        return self._request("POST", f"{BASE}/outreach-campaigns/{campaign_id}/launch", {}, headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"{BASE}/outreach-campaigns/{campaign_id}/pause", {}, headers)

    def resume_campaign(self, campaign_id, headers):
        return self._request("POST", f"{BASE}/outreach-campaigns/{campaign_id}/resume", {}, headers)

    def complete_campaign(self, campaign_id, headers):
        return self._request("POST", f"{BASE}/outreach-campaigns/{campaign_id}/complete", {}, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"{BASE}/outreach-campaigns/{campaign_id}/cancel", {}, headers)

    def list_campaigns(self, registry_id, headers, params=None):
        return self._request("GET", f"{BASE}/registries/{registry_id}/outreach-campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{BASE}/outreach-campaigns/{campaign_id}", headers=headers)

    def list_campaigns_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/outreach-campaigns", headers=headers, params=params)

    # --- Outreach attempts ---
    def create_outreach_attempt(self, gap_id, payload, headers):
        return self._request("POST", f"{BASE}/care-gaps/{gap_id}/outreach-attempts", payload, headers)

    def list_gap_outreach_attempts(self, gap_id, headers, params=None):
        return self._request("GET", f"{BASE}/care-gaps/{gap_id}/outreach-attempts", headers=headers, params=params)

    def list_outreach_attempts_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/outreach-attempts", headers=headers, params=params)

    def get_outreach_attempt(self, attempt_id, headers):
        return self._request("GET", f"{BASE}/outreach-attempts/{attempt_id}", headers=headers)

    # --- Appointments ---
    def create_appointment(self, gap_id, payload, headers):
        return self._request("POST", f"{BASE}/care-gaps/{gap_id}/appointments", payload, headers)

    def list_gap_appointments(self, gap_id, headers, params=None):
        return self._request("GET", f"{BASE}/care-gaps/{gap_id}/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"{BASE}/appointments/{appointment_id}", headers=headers)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/confirm", {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/complete", {}, headers)

    def mark_no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/mark-no-show", {}, headers)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/cancel", payload, headers)

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/reschedule", payload, headers)

    def list_appointments_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/appointments", headers=headers, params=params)

    # --- Transportation assists ---
    def create_transportation_assist(self, appointment_id, payload, headers):
        return self._request("POST", f"{BASE}/appointments/{appointment_id}/transportation-assists", payload, headers)

    def arrange_transportation_assist(self, assist_id, headers):
        return self._request("POST", f"{BASE}/transportation-assists/{assist_id}/arrange", {}, headers)

    def complete_transportation_assist(self, assist_id, headers):
        return self._request("POST", f"{BASE}/transportation-assists/{assist_id}/complete", {}, headers)

    def cancel_transportation_assist(self, assist_id, payload, headers):
        return self._request("POST", f"{BASE}/transportation-assists/{assist_id}/cancel", payload, headers)

    def list_appointment_transportation_assists(self, appointment_id, headers, params=None):
        return self._request("GET", f"{BASE}/appointments/{appointment_id}/transportation-assists", headers=headers, params=params)

    def get_transportation_assist(self, assist_id, headers):
        return self._request("GET", f"{BASE}/transportation-assists/{assist_id}", headers=headers)

    def list_transportation_assists_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/transportation-assists", headers=headers, params=params)

    # --- Gap closure evidence ---
    def create_evidence(self, gap_id, payload, headers):
        return self._request("POST", f"{BASE}/care-gaps/{gap_id}/gap-closure-evidence", payload, headers)

    def approve_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"{BASE}/gap-closure-evidence/{evidence_id}/approve", payload, headers)

    def reject_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"{BASE}/gap-closure-evidence/{evidence_id}/reject", payload, headers)

    def list_gap_evidence(self, gap_id, headers, params=None):
        return self._request("GET", f"{BASE}/care-gaps/{gap_id}/gap-closure-evidence", headers=headers, params=params)

    def get_evidence(self, evidence_id, headers):
        return self._request("GET", f"{BASE}/gap-closure-evidence/{evidence_id}", headers=headers)

    def list_evidence_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/gap-closure-evidence", headers=headers, params=params)

    # --- Exclusion requests ---
    def create_exclusion_request(self, member_id, payload, headers):
        return self._request("POST", f"{BASE}/members/{member_id}/exclusion-requests", payload, headers)

    def start_review_exclusion(self, exclusion_id, headers):
        return self._request("POST", f"{BASE}/exclusion-requests/{exclusion_id}/start-review", {}, headers)

    def approve_exclusion(self, exclusion_id, payload, headers):
        return self._request("POST", f"{BASE}/exclusion-requests/{exclusion_id}/approve", payload, headers)

    def deny_exclusion(self, exclusion_id, payload, headers):
        return self._request("POST", f"{BASE}/exclusion-requests/{exclusion_id}/deny", payload, headers)

    def revoke_exclusion(self, exclusion_id, payload, headers):
        return self._request("POST", f"{BASE}/exclusion-requests/{exclusion_id}/revoke", payload, headers)

    def list_member_exclusion_requests(self, member_id, headers, params=None):
        return self._request("GET", f"{BASE}/members/{member_id}/exclusion-requests", headers=headers, params=params)

    def get_exclusion_request(self, exclusion_id, headers):
        return self._request("GET", f"{BASE}/exclusion-requests/{exclusion_id}", headers=headers)

    def list_exclusion_requests_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/exclusion-requests", headers=headers, params=params)

    # --- Panel manager workloads & payouts ---
    def create_workload(self, registry_id, payload, headers):
        return self._request("POST", f"{BASE}/registries/{registry_id}/panel-manager-workloads", payload, headers)

    def list_workloads(self, registry_id, headers, params=None):
        return self._request("GET", f"{BASE}/registries/{registry_id}/panel-manager-workloads", headers=headers, params=params)

    def get_workload(self, workload_id, headers):
        return self._request("GET", f"{BASE}/panel-manager-workloads/{workload_id}", headers=headers)

    def list_incentive_payouts(self, workload_id, headers, params=None):
        return self._request("GET", f"{BASE}/panel-manager-workloads/{workload_id}/incentive-payouts", headers=headers, params=params)

    def create_payout_projection(self, workload_id, headers):
        return self._request("POST", f"{BASE}/panel-manager-workloads/{workload_id}/incentive-payouts/projection", {}, headers)

    def approve_payout(self, payout_id, headers):
        return self._request("POST", f"{BASE}/incentive-payouts/{payout_id}/approve", {}, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"{BASE}/incentive-payouts/{payout_id}", headers=headers)

    # --- Measure performance reports ---
    def create_performance_report(self, measure_id, payload, headers):
        return self._request("POST", f"{BASE}/measure-definitions/{measure_id}/measure-performance-reports", payload, headers)

    def finalize_performance_report(self, report_id, headers):
        return self._request("POST", f"{BASE}/measure-performance-reports/{report_id}/finalize", {}, headers)

    def list_performance_reports(self, measure_id, headers, params=None):
        return self._request("GET", f"{BASE}/measure-definitions/{measure_id}/measure-performance-reports", headers=headers, params=params)

    def get_performance_report(self, report_id, headers):
        return self._request("GET", f"{BASE}/measure-performance-reports/{report_id}", headers=headers)

    def list_performance_reports_flat(self, headers, params=None):
        return self._request("GET", f"{BASE}/measure-performance-reports", headers=headers, params=params)


api_client = ApiClient()
