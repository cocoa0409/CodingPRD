"""
Typed HTTP client for the Digital Curriculum Rostering & Single Sign-On API.

One method per endpoint published by the contract. Every method returns the raw
requests.Response so that tests can assert status codes as well as payloads.
Query parameters are passed through **filters so a test can exercise any
declared filter or pagination parameter without a new method.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class RosteringApiClient(GenericApiClient):
    """Endpoint-level client for the rostering and single sign-on service."""

    # ── logical clock ────────────────────────────────────────────────────────
    def set_clock(self, now: str, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc"""
        return self._request("POST", "/_clock/set_current_utc", {"now": now}, headers)

    def set_clock_raw(self, payload: Any, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc with an arbitrary body."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── schools ──────────────────────────────────────────────────────────────
    def list_schools(self, headers=None, **filters):
        """GET /rostering/schools"""
        return self._request("GET", "/rostering/schools", filters, headers)

    def get_school(self, school_id: str, headers=None):
        """GET /rostering/schools/{school_id}"""
        return self._request("GET", f"/rostering/schools/{school_id}", None, headers)

    def create_school(self, payload: Any, headers=None):
        """POST /rostering/schools"""
        return self._request("POST", "/rostering/schools", payload, headers)

    def update_school(self, school_id: str, payload: Any, headers=None):
        """PATCH /rostering/schools/{school_id}"""
        return self._request(
            "PATCH", f"/rostering/schools/{school_id}", payload, headers
        )

    # ── terms ────────────────────────────────────────────────────────────────
    def list_terms(self, headers=None, **filters):
        """GET /rostering/terms"""
        return self._request("GET", "/rostering/terms", filters, headers)

    def get_term(self, term_id: str, headers=None):
        """GET /rostering/terms/{term_id}"""
        return self._request("GET", f"/rostering/terms/{term_id}", None, headers)

    def create_term(self, payload: Any, headers=None):
        """POST /rostering/terms"""
        return self._request("POST", "/rostering/terms", payload, headers)

    def activate_term(self, term_id: str, headers=None):
        """POST /rostering/terms/{term_id}/activate"""
        return self._request(
            "POST", f"/rostering/terms/{term_id}/activate", {}, headers
        )

    def rollover_term(self, term_id: str, headers=None):
        """POST /rostering/terms/{term_id}/rollover"""
        return self._request(
            "POST", f"/rostering/terms/{term_id}/rollover", {}, headers
        )

    # ── teachers ─────────────────────────────────────────────────────────────
    def list_teachers(self, headers=None, **filters):
        """GET /rostering/teachers"""
        return self._request("GET", "/rostering/teachers", filters, headers)

    def get_teacher(self, teacher_id: str, headers=None):
        """GET /rostering/teachers/{teacher_id}"""
        return self._request("GET", f"/rostering/teachers/{teacher_id}", None, headers)

    def create_teacher(self, payload: Any, headers=None):
        """POST /rostering/teachers"""
        return self._request("POST", "/rostering/teachers", payload, headers)

    def separate_teacher(self, teacher_id: str, payload: Any, headers=None):
        """POST /rostering/teachers/{teacher_id}/separate"""
        return self._request(
            "POST", f"/rostering/teachers/{teacher_id}/separate", payload, headers
        )

    # ── students ─────────────────────────────────────────────────────────────
    def list_students(self, headers=None, **filters):
        """GET /rostering/students"""
        return self._request("GET", "/rostering/students", filters, headers)

    def get_student(self, student_id: str, headers=None):
        """GET /rostering/students/{student_id}"""
        return self._request("GET", f"/rostering/students/{student_id}", None, headers)

    def create_student(self, payload: Any, headers=None):
        """POST /rostering/students"""
        return self._request("POST", "/rostering/students", payload, headers)

    def withdraw_student(self, student_id: str, payload: Any, headers=None):
        """POST /rostering/students/{student_id}/withdraw"""
        return self._request(
            "POST", f"/rostering/students/{student_id}/withdraw", payload, headers
        )

    # ── sections ─────────────────────────────────────────────────────────────
    def list_sections(self, headers=None, **filters):
        """GET /rostering/sections"""
        return self._request("GET", "/rostering/sections", filters, headers)

    def get_section(self, section_id: str, headers=None):
        """GET /rostering/sections/{section_id}"""
        return self._request("GET", f"/rostering/sections/{section_id}", None, headers)

    def create_section(self, payload: Any, headers=None):
        """POST /rostering/sections"""
        return self._request("POST", "/rostering/sections", payload, headers)

    def update_section(self, section_id: str, payload: Any, headers=None):
        """PATCH /rostering/sections/{section_id}"""
        return self._request(
            "PATCH", f"/rostering/sections/{section_id}", payload, headers
        )

    # ── enrollments ──────────────────────────────────────────────────────────
    def list_enrollments(self, headers=None, **filters):
        """GET /rostering/enrollments"""
        return self._request("GET", "/rostering/enrollments", filters, headers)

    def get_enrollment(self, enrollment_id: str, headers=None):
        """GET /rostering/enrollments/{enrollment_id}"""
        return self._request(
            "GET", f"/rostering/enrollments/{enrollment_id}", None, headers
        )

    def create_enrollment(self, payload: Any, headers=None):
        """POST /rostering/enrollments"""
        return self._request("POST", "/rostering/enrollments", payload, headers)

    def drop_enrollment(self, enrollment_id: str, payload: Any, headers=None):
        """POST /rostering/enrollments/{enrollment_id}/drop"""
        return self._request(
            "POST", f"/rostering/enrollments/{enrollment_id}/drop", payload, headers
        )

    # ── vendor apps (licences) ───────────────────────────────────────────────
    def list_vendor_apps(self, headers=None, **filters):
        """GET /rostering/vendor-apps"""
        return self._request("GET", "/rostering/vendor-apps", filters, headers)

    def get_vendor_app(self, vendor_app_id: str, headers=None):
        """GET /rostering/vendor-apps/{vendor_app_id}"""
        return self._request(
            "GET", f"/rostering/vendor-apps/{vendor_app_id}", None, headers
        )

    def create_vendor_app(self, payload: Any, headers=None):
        """POST /rostering/vendor-apps"""
        return self._request("POST", "/rostering/vendor-apps", payload, headers)

    def update_vendor_app(self, vendor_app_id: str, payload: Any, headers=None):
        """PATCH /rostering/vendor-apps/{vendor_app_id}"""
        return self._request(
            "PATCH", f"/rostering/vendor-apps/{vendor_app_id}", payload, headers
        )

    def activate_license(self, vendor_app_id: str, headers=None):
        """POST /rostering/vendor-apps/{vendor_app_id}/activate-license"""
        return self._request(
            "POST",
            f"/rostering/vendor-apps/{vendor_app_id}/activate-license",
            {},
            headers,
        )

    def get_roster_feed(self, vendor_app_id: str, headers=None, **filters):
        """GET /rostering/vendor-apps/{vendor_app_id}/roster-feed"""
        return self._request(
            "GET",
            f"/rostering/vendor-apps/{vendor_app_id}/roster-feed",
            filters,
            headers,
        )

    def get_renewal_summary(self, vendor_app_id: str, headers=None, **filters):
        """GET /rostering/vendor-apps/{vendor_app_id}/renewal-summary"""
        return self._request(
            "GET",
            f"/rostering/vendor-apps/{vendor_app_id}/renewal-summary",
            filters,
            headers,
        )

    # ── building allocations ─────────────────────────────────────────────────
    def list_building_allocations(self, headers=None, **filters):
        """GET /rostering/building-allocations"""
        return self._request(
            "GET", "/rostering/building-allocations", filters, headers
        )

    def get_building_allocation(self, building_allocation_id: str, headers=None):
        """GET /rostering/building-allocations/{building_allocation_id}"""
        return self._request(
            "GET",
            f"/rostering/building-allocations/{building_allocation_id}",
            None,
            headers,
        )

    def update_building_allocation(
        self, building_allocation_id: str, payload: Any, headers=None
    ):
        """PATCH /rostering/building-allocations/{building_allocation_id}"""
        return self._request(
            "PATCH",
            f"/rostering/building-allocations/{building_allocation_id}",
            payload,
            headers,
        )

    # ── app accounts ─────────────────────────────────────────────────────────
    def list_app_accounts(self, headers=None, **filters):
        """GET /rostering/app-accounts"""
        return self._request("GET", "/rostering/app-accounts", filters, headers)

    def get_app_account(self, app_account_id: str, headers=None):
        """GET /rostering/app-accounts/{app_account_id}"""
        return self._request(
            "GET", f"/rostering/app-accounts/{app_account_id}", None, headers
        )

    def create_app_account(self, payload: Any, headers=None):
        """POST /rostering/app-accounts"""
        return self._request("POST", "/rostering/app-accounts", payload, headers)

    def set_password(self, app_account_id: str, payload: Any, headers=None):
        """POST /rostering/app-accounts/{app_account_id}/password-set"""
        return self._request(
            "POST",
            f"/rostering/app-accounts/{app_account_id}/password-set",
            payload,
            headers,
        )

    def record_usage(self, app_account_id: str, payload: Any, headers=None):
        """POST /rostering/app-accounts/{app_account_id}/record-usage"""
        return self._request(
            "POST",
            f"/rostering/app-accounts/{app_account_id}/record-usage",
            payload,
            headers,
        )

    def release_seat(self, app_account_id: str, headers=None):
        """POST /rostering/app-accounts/{app_account_id}/release"""
        return self._request(
            "POST", f"/rostering/app-accounts/{app_account_id}/release", {}, headers
        )

    def deprovision_account(self, app_account_id: str, payload: Any, headers=None):
        """POST /rostering/app-accounts/{app_account_id}/deprovision"""
        return self._request(
            "POST",
            f"/rostering/app-accounts/{app_account_id}/deprovision",
            payload,
            headers,
        )

    # ── sync runs ────────────────────────────────────────────────────────────
    def list_sync_runs(self, headers=None, **filters):
        """GET /rostering/sync-runs"""
        return self._request("GET", "/rostering/sync-runs", filters, headers)

    def get_sync_run(self, sync_run_id: str, headers=None):
        """GET /rostering/sync-runs/{sync_run_id}"""
        return self._request(
            "GET", f"/rostering/sync-runs/{sync_run_id}", None, headers
        )

    def create_sync_run(self, payload: Any, headers=None):
        """POST /rostering/sync-runs"""
        return self._request("POST", "/rostering/sync-runs", payload, headers)

    def transform_sync_run(self, sync_run_id: str, headers=None):
        """POST /rostering/sync-runs/{sync_run_id}/transform"""
        return self._request(
            "POST", f"/rostering/sync-runs/{sync_run_id}/transform", {}, headers
        )

    def publish_sync_run(self, sync_run_id: str, headers=None):
        """POST /rostering/sync-runs/{sync_run_id}/publish"""
        return self._request(
            "POST", f"/rostering/sync-runs/{sync_run_id}/publish", {}, headers
        )

    # ── error queue items ────────────────────────────────────────────────────
    def list_error_queue_items(self, headers=None, **filters):
        """GET /rostering/error-queue-items"""
        return self._request("GET", "/rostering/error-queue-items", filters, headers)

    def get_error_queue_item(self, error_queue_item_id: str, headers=None):
        """GET /rostering/error-queue-items/{error_queue_item_id}"""
        return self._request(
            "GET", f"/rostering/error-queue-items/{error_queue_item_id}", None, headers
        )

    def resolve_match(self, error_queue_item_id: str, payload: Any, headers=None):
        """POST /rostering/error-queue-items/{error_queue_item_id}/resolve-match"""
        return self._request(
            "POST",
            f"/rostering/error-queue-items/{error_queue_item_id}/resolve-match",
            payload,
            headers,
        )

    def merge_duplicate(self, error_queue_item_id: str, payload: Any, headers=None):
        """POST /rostering/error-queue-items/{error_queue_item_id}/merge-duplicate"""
        return self._request(
            "POST",
            f"/rostering/error-queue-items/{error_queue_item_id}/merge-duplicate",
            payload,
            headers,
        )
