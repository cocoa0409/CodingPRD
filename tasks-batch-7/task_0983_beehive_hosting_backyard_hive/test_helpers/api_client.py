"""API client: one method per endpoint defined in the PRD (§4).

All methods accept an optional ``headers`` argument; passing ``{}`` (or
``None``) sends the request without auth context headers, which the missing-
header test relies on.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Seasons ---
    def create_season(self, payload, headers=None):
        return self._request("POST", "/api/seasons", payload, headers)

    def get_season(self, season_id, headers=None):
        return self._request("GET", f"/api/seasons/{season_id}", headers=headers)

    def rollover_season(self, season_id, payload, headers=None):
        return self._request(
            "POST", f"/api/seasons/{season_id}/rollover", payload, headers,
        )

    # --- Hosts ---
    def create_host(self, payload, headers=None):
        return self._request("POST", "/api/hosts", payload, headers)

    def get_host(self, host_id, headers=None):
        return self._request("GET", f"/api/hosts/{host_id}", headers=headers)

    def sign_waiver(self, host_id, payload, headers=None):
        return self._request(
            "POST", f"/api/hosts/{host_id}/sign-waiver", payload, headers,
        )

    def suspend_host(self, host_id, headers=None):
        return self._request(
            "POST", f"/api/hosts/{host_id}/suspend", {}, headers,
        )

    def reactivate_host(self, host_id, headers=None):
        return self._request(
            "POST", f"/api/hosts/{host_id}/reactivate", {}, headers,
        )

    # --- Sites ---
    def create_site(self, payload, headers=None):
        return self._request("POST", "/api/sites", payload, headers)

    def get_site(self, site_id, headers=None):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def list_sites(self, headers=None, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def unblock_site(self, site_id, headers=None):
        return self._request("POST", f"/api/sites/{site_id}/unblock", {}, headers)

    # --- Agreements ---
    def create_agreement(self, payload, headers=None):
        return self._request("POST", "/api/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers=None):
        return self._request(
            "GET", f"/api/agreements/{agreement_id}", headers=headers,
        )

    def list_agreements(self, headers=None, params=None):
        return self._request(
            "GET", "/api/agreements", headers=headers, params=params,
        )

    def sign_agreement(self, agreement_id, headers=None):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/sign", {}, headers,
        )

    def propose_amendment(self, agreement_id, payload, headers=None):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/propose-amendment",
            payload, headers,
        )

    def accept_amendment(self, agreement_id, headers=None):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/accept-amendment", {},
            headers,
        )

    def reject_amendment(self, agreement_id, headers=None):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/reject-amendment", {},
            headers,
        )

    def terminate_agreement(self, agreement_id, headers=None):
        return self._request(
            "POST", f"/api/agreements/{agreement_id}/terminate", {}, headers,
        )

    # --- Hives ---
    def create_hive(self, payload, headers=None):
        return self._request("POST", "/api/hives", payload, headers)

    def get_hive(self, hive_id, headers=None):
        return self._request("GET", f"/api/hives/{hive_id}", headers=headers)

    def list_hives(self, headers=None, params=None):
        return self._request("GET", "/api/hives", headers=headers, params=params)

    def split_hive(self, hive_id, headers=None):
        return self._request("POST", f"/api/hives/{hive_id}/split", {}, headers)

    def mark_hive_dead(self, hive_id, headers=None):
        return self._request(
            "POST", f"/api/hives/{hive_id}/mark-dead", {}, headers,
        )

    # --- Inspections ---
    def create_inspection(self, payload, headers=None):
        return self._request("POST", "/api/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers=None):
        return self._request(
            "GET", f"/api/inspections/{inspection_id}", headers=headers,
        )

    def list_inspections(self, headers=None, params=None):
        return self._request(
            "GET", "/api/inspections", headers=headers, params=params,
        )

    def submit_inspection(self, inspection_id, headers=None):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/submit", {}, headers,
        )

    def verify_inspection(self, inspection_id, headers=None):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/verify", {}, headers,
        )

    def return_inspection(self, inspection_id, payload, headers=None):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/return", payload, headers,
        )

    # --- Treatments ---
    def create_treatment(self, payload, headers=None):
        return self._request("POST", "/api/treatments", payload, headers)

    def get_treatment(self, treatment_id, headers=None):
        return self._request(
            "GET", f"/api/treatments/{treatment_id}", headers=headers,
        )

    def list_treatments(self, headers=None, params=None):
        return self._request(
            "GET", "/api/treatments", headers=headers, params=params,
        )

    def start_treatment(self, treatment_id, headers=None):
        return self._request(
            "POST", f"/api/treatments/{treatment_id}/start", {}, headers,
        )

    def complete_treatment(self, treatment_id, headers=None):
        return self._request(
            "POST", f"/api/treatments/{treatment_id}/complete", {}, headers,
        )

    # --- Harvests ---
    def create_harvest(self, payload, headers=None):
        return self._request("POST", "/api/harvests", payload, headers)

    def get_harvest(self, harvest_id, headers=None):
        return self._request("GET", f"/api/harvests/{harvest_id}", headers=headers)

    def list_harvests(self, headers=None, params=None):
        return self._request(
            "GET", "/api/harvests", headers=headers, params=params,
        )

    def approve_harvest(self, harvest_id, headers=None):
        return self._request(
            "POST", f"/api/harvests/{harvest_id}/approve", {}, headers,
        )

    def void_harvest(self, harvest_id, headers=None):
        return self._request(
            "POST", f"/api/harvests/{harvest_id}/void", {}, headers,
        )

    # --- Honey allocations ---
    def get_allocation(self, allocation_id, headers=None):
        return self._request(
            "GET", f"/api/allocations/{allocation_id}", headers=headers,
        )

    def list_allocations(self, headers=None, params=None):
        return self._request(
            "GET", "/api/allocations", headers=headers, params=params,
        )

    def distribute_allocation(self, allocation_id, headers=None):
        return self._request(
            "POST", f"/api/allocations/{allocation_id}/distribute", {}, headers,
        )

    # --- Swarm events ---
    def create_swarm_event(self, payload, headers=None):
        return self._request("POST", "/api/swarm-events", payload, headers)

    def get_swarm_event(self, swarm_id, headers=None):
        return self._request(
            "GET", f"/api/swarm-events/{swarm_id}", headers=headers,
        )

    def list_swarm_events(self, headers=None, params=None):
        return self._request(
            "GET", "/api/swarm-events", headers=headers, params=params,
        )

    def dispatch_swarm_event(self, swarm_id, headers=None):
        return self._request(
            "POST", f"/api/swarm-events/{swarm_id}/dispatch", {}, headers,
        )

    def capture_swarm_event(self, swarm_id, headers=None):
        return self._request(
            "POST", f"/api/swarm-events/{swarm_id}/capture", {}, headers,
        )

    def mark_swarm_lost(self, swarm_id, headers=None):
        return self._request(
            "POST", f"/api/swarm-events/{swarm_id}/mark-lost", {}, headers,
        )

    # --- Removal jobs ---
    def create_removal_job(self, payload, headers=None):
        return self._request("POST", "/api/removal-jobs", payload, headers)

    def get_removal_job(self, job_id, headers=None):
        return self._request(
            "GET", f"/api/removal-jobs/{job_id}", headers=headers,
        )

    def list_removal_jobs(self, headers=None, params=None):
        return self._request(
            "GET", "/api/removal-jobs", headers=headers, params=params,
        )

    def decide_removal_job(self, job_id, payload, headers=None):
        return self._request(
            "POST", f"/api/removal-jobs/{job_id}/approve", payload, headers,
        )

    def schedule_removal_job(self, job_id, payload, headers=None):
        return self._request(
            "POST", f"/api/removal-jobs/{job_id}/schedule", payload, headers,
        )

    def complete_removal_job(self, job_id, headers=None):
        return self._request(
            "POST", f"/api/removal-jobs/{job_id}/complete", {}, headers,
        )

    def cancel_removal_job(self, job_id, headers=None):
        return self._request(
            "POST", f"/api/removal-jobs/{job_id}/cancel", {}, headers,
        )

    # --- Subscriptions ---
    def create_subscription(self, payload, headers=None):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers=None):
        return self._request(
            "GET", f"/api/subscriptions/{subscription_id}", headers=headers,
        )

    def list_subscriptions(self, headers=None, params=None):
        return self._request(
            "GET", "/api/subscriptions", headers=headers, params=params,
        )

    def change_plan(self, subscription_id, payload, headers=None):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/change-plan",
            payload, headers,
        )

    def cancel_subscription(self, subscription_id, headers=None):
        return self._request(
            "POST", f"/api/subscriptions/{subscription_id}/cancel", {}, headers,
        )

    # --- Invoices ---
    def get_invoice(self, invoice_id, headers=None):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers=None, params=None):
        return self._request(
            "GET", "/api/invoices", headers=headers, params=params,
        )

    def pay_invoice(self, invoice_id, headers=None):
        return self._request(
            "POST", f"/api/invoices/{invoice_id}/pay", {}, headers,
        )

    def void_invoice(self, invoice_id, headers=None):
        return self._request(
            "POST", f"/api/invoices/{invoice_id}/void", {}, headers,
        )

    # --- Enrollments ---
    def create_enrollment(self, payload, headers=None):
        return self._request("POST", "/api/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers=None):
        return self._request(
            "GET", f"/api/enrollments/{enrollment_id}", headers=headers,
        )

    def list_enrollments(self, headers=None, params=None):
        return self._request(
            "GET", "/api/enrollments", headers=headers, params=params,
        )

    def complete_enrollment(self, enrollment_id, payload, headers=None):
        return self._request(
            "POST", f"/api/enrollments/{enrollment_id}/complete", payload,
            headers,
        )

    # --- Incidents ---
    def create_incident(self, payload, headers=None):
        return self._request("POST", "/api/incidents", payload, headers)

    def get_incident(self, incident_id, headers=None):
        return self._request("GET", f"/api/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers=None, params=None):
        return self._request(
            "GET", "/api/incidents", headers=headers, params=params,
        )

    def resolve_incident(self, incident_id, payload, headers=None):
        return self._request(
            "POST", f"/api/incidents/{incident_id}/resolve", payload, headers,
        )


api_client = ApiClient()
