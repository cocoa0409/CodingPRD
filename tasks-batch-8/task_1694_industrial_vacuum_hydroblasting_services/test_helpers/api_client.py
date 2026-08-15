"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/v1/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/v1/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/v1/sites/{site_id}", headers=headers)

    def update_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/v1/sites/{site_id}", payload, headers)

    def daily_close(self, site_id, headers):
        return self._request("POST", f"/v1/sites/{site_id}/daily-close", {}, headers)

    # --- Rate schedules ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/v1/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/v1/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/v1/rate-schedules/{schedule_id}", headers=headers)

    def activate_rate_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/v1/rate-schedules/{schedule_id}/activate", payload, headers
        )

    # --- Jobs ---
    def create_job(self, payload, headers):
        return self._request("POST", "/v1/jobs", payload, headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/v1/jobs", headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/v1/jobs/{job_id}", headers=headers)

    def schedule_job(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/schedule", {}, headers)

    def mobilize_job(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/mobilize", {}, headers)

    def start_work(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/start-work", {}, headers)

    def complete_field_work(self, job_id, payload, headers):
        return self._request(
            "POST", f"/v1/jobs/{job_id}/complete-field-work", payload, headers
        )

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/cancel", {}, headers)

    def stop_work(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/stop-work", {}, headers)

    def resume_work(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/resume-work", {}, headers)

    def close_job(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/close", {}, headers)

    def generate_invoice(self, job_id, headers):
        return self._request("POST", f"/v1/jobs/{job_id}/generate-invoice", {}, headers)

    # --- Job hazard analyses ---
    def create_jha(self, payload, headers):
        return self._request("POST", "/v1/jhas", payload, headers)

    def list_jhas(self, headers, params=None):
        return self._request("GET", "/v1/jhas", headers=headers, params=params)

    def get_jha(self, jha_id, headers):
        return self._request("GET", f"/v1/jhas/{jha_id}", headers=headers)

    def submit_jha(self, jha_id, headers):
        return self._request("POST", f"/v1/jhas/{jha_id}/submit", {}, headers)

    def approve_jha(self, jha_id, payload, headers):
        return self._request("POST", f"/v1/jhas/{jha_id}/approve", payload, headers)

    def reject_jha(self, jha_id, headers):
        return self._request("POST", f"/v1/jhas/{jha_id}/reject", {}, headers)

    def revise_jha(self, jha_id, headers):
        return self._request("POST", f"/v1/jhas/{jha_id}/revise", {}, headers)

    # --- Permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/v1/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/v1/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/v1/permits/{permit_id}", headers=headers)

    def activate_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/activate", {}, headers)

    def suspend_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/suspend", {}, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/close", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/revoke", {}, headers)

    # --- Equipment units ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/v1/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/v1/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/v1/equipment-units/{unit_id}", headers=headers)

    # --- Operators ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/v1/operators", payload, headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/v1/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/v1/operators/{operator_id}", headers=headers)

    # --- Assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/v1/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/v1/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/v1/assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/v1/assignments/{assignment_id}/confirm", {}, headers
        )

    def release_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/v1/assignments/{assignment_id}/release", {}, headers
        )

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/v1/assignments/{assignment_id}/cancel", {}, headers
        )

    # --- Waste profiles ---
    def create_waste_profile(self, payload, headers):
        return self._request("POST", "/v1/waste-profiles", payload, headers)

    def list_waste_profiles(self, headers, params=None):
        return self._request("GET", "/v1/waste-profiles", headers=headers, params=params)

    def get_waste_profile(self, profile_id, headers):
        return self._request("GET", f"/v1/waste-profiles/{profile_id}", headers=headers)

    def submit_waste_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/v1/waste-profiles/{profile_id}/submit", {}, headers
        )

    def approve_waste_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/v1/waste-profiles/{profile_id}/approve", {}, headers
        )

    def suspend_waste_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/v1/waste-profiles/{profile_id}/suspend", {}, headers
        )

    def reinstate_waste_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/v1/waste-profiles/{profile_id}/reinstate", {}, headers
        )

    # --- Disposal facilities ---
    def create_disposal_facility(self, payload, headers):
        return self._request("POST", "/v1/disposal-facilities", payload, headers)

    def list_disposal_facilities(self, headers, params=None):
        return self._request(
            "GET", "/v1/disposal-facilities", headers=headers, params=params
        )

    def get_disposal_facility(self, facility_id, headers):
        return self._request(
            "GET", f"/v1/disposal-facilities/{facility_id}", headers=headers
        )

    # --- Disposal manifests ---
    def create_manifest(self, payload, headers):
        return self._request("POST", "/v1/manifests", payload, headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/v1/manifests", headers=headers, params=params)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/v1/manifests/{manifest_id}", headers=headers)

    def issue_manifest(self, manifest_id, headers):
        return self._request("POST", f"/v1/manifests/{manifest_id}/issue", {}, headers)

    def depart_manifest(self, manifest_id, headers):
        return self._request("POST", f"/v1/manifests/{manifest_id}/depart", {}, headers)

    def receive_manifest(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/v1/manifests/{manifest_id}/receive", payload, headers
        )

    def reconcile_manifest(self, manifest_id, headers):
        return self._request(
            "POST", f"/v1/manifests/{manifest_id}/reconcile", {}, headers
        )

    def resolve_manifest_exception(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"/v1/manifests/{manifest_id}/resolve-exception", payload, headers
        )

    def void_manifest(self, manifest_id, headers):
        return self._request("POST", f"/v1/manifests/{manifest_id}/void", {}, headers)

    # --- Containment records ---
    def create_containment_record(self, payload, headers):
        return self._request("POST", "/v1/containment-records", payload, headers)

    def list_containment_records(self, headers, params=None):
        return self._request(
            "GET", "/v1/containment-records", headers=headers, params=params
        )

    def get_containment_record(self, record_id, headers):
        return self._request(
            "GET", f"/v1/containment-records/{record_id}", headers=headers
        )

    def verify_containment_record(self, record_id, headers):
        return self._request(
            "POST", f"/v1/containment-records/{record_id}/verify", {}, headers
        )

    # --- Downtime events ---
    def create_downtime_event(self, payload, headers):
        return self._request("POST", "/v1/downtime-events", payload, headers)

    def list_downtime_events(self, headers, params=None):
        return self._request("GET", "/v1/downtime-events", headers=headers, params=params)

    def get_downtime_event(self, event_id, headers):
        return self._request("GET", f"/v1/downtime-events/{event_id}", headers=headers)

    def close_downtime_event(self, event_id, headers):
        return self._request(
            "POST", f"/v1/downtime-events/{event_id}/close", {}, headers
        )

    # --- Invoices ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/issue", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/mark-paid", {}, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/void", {}, headers)

    def add_invoice_line(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/lines", payload, headers
        )

    def void_invoice_line(self, invoice_id, line_id, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/lines/{line_id}/void", {}, headers
        )

    # --- Incident reports ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/v1/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/v1/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/v1/incidents/{incident_id}", headers=headers)

    def start_incident_review(self, incident_id, headers):
        return self._request(
            "POST", f"/v1/incidents/{incident_id}/start-review", {}, headers
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/v1/incidents/{incident_id}/close", payload, headers
        )

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
