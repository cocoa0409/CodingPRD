"""API client: one method per endpoint defined in the Community Solar PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- SolarProject ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def create_carve_out_adjustment(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/carve-out-adjustments", payload, headers
        )

    def list_carve_out_adjustments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/carve-out-adjustments",
            headers=headers, params=params,
        )

    # ---- Subscriber ----
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def submit_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/submit", {}, headers
        )

    def approve_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/approve", {}, headers
        )

    def reject_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/reject", payload, headers
        )

    def activate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/activate", {}, headers
        )

    # ---- Subscription ----
    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers
        )

    def suspend_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/suspend", {}, headers
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resume", {}, headers
        )

    def transfer_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/transfer", payload, headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers
        )

    # ---- WaitlistEntry ----
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/waitlist-entries/{entry_id}/withdraw", {}, headers
        )

    # ---- BillingPeriod ----
    def create_period(self, payload, headers):
        return self._request("POST", "/periods", payload, headers)

    def list_periods(self, headers, params=None):
        return self._request("GET", "/periods", headers=headers, params=params)

    def get_period(self, period_id, headers):
        return self._request("GET", f"/periods/{period_id}", headers=headers)

    def meter_period(self, period_id, payload, headers):
        return self._request("POST", f"/periods/{period_id}/meter", payload, headers)

    def reconcile_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/periods/{period_id}/reconcile", payload, headers
        )

    def true_up_period(self, period_id, headers):
        return self._request("POST", f"/periods/{period_id}/true-up", {}, headers)

    def reopen_period(self, period_id, headers):
        return self._request("POST", f"/periods/{period_id}/reopen", {}, headers)

    def close_period(self, period_id, headers):
        return self._request("POST", f"/periods/{period_id}/close", {}, headers)

    # ---- Allocation ----
    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    # ---- Reconciliation ----
    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/reconciliations", headers=headers, params=params)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "GET", f"/reconciliations/{reconciliation_id}", headers=headers
        )

    def issue_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "POST", f"/reconciliations/{reconciliation_id}/issue", {}, headers
        )

    def apply_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "POST", f"/reconciliations/{reconciliation_id}/apply", {}, headers
        )

    def dispute_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "POST", f"/reconciliations/{reconciliation_id}/dispute", {}, headers
        )

    def resolve_dispute(self, reconciliation_id, headers):
        return self._request(
            "POST", f"/reconciliations/{reconciliation_id}/resolve-dispute", {}, headers
        )

    # ---- RECBatch ----
    def list_rec_batches(self, headers, params=None):
        return self._request("GET", "/rec-batches", headers=headers, params=params)

    def get_rec_batch(self, batch_id, headers):
        return self._request("GET", f"/rec-batches/{batch_id}", headers=headers)

    def allocate_rec_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/rec-batches/{batch_id}/allocate", {}, headers
        )

    def retire_rec_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/rec-batches/{batch_id}/retire", payload, headers
        )

    def transfer_rec_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/rec-batches/{batch_id}/transfer", payload, headers
        )


api_client = ApiClient()
