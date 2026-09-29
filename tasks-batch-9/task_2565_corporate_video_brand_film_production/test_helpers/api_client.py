"""HTTP client with one method per endpoint in PRD §4.

"Every path below is absolute; there is no common prefix." — so the paths below
are exactly the 44 rows of the §4 table, in that table's order.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code (201 for the eleven creates, 200 for everything else) as well as the
body.
"""

from typing import Any, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the 44 endpoints PRD §4 declares."""

    # ─── Project reads (PRD §4) ────────────────────────────────────────────

    def get_project(self, project_id: str, headers: Optional[dict] = None) -> requests.Response:
        """Read one project with its live provisional and committed ledgers."""
        return self._request("GET", f"/projects/{project_id}", None, headers)

    def list_project_budget_lines(
        self, project_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/projects/{project_id}/budget-lines", params or None, headers
        )

    def list_project_deliverables(
        self, project_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/projects/{project_id}/deliverables", params or None, headers
        )

    def list_project_talent_engagements(
        self, project_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/projects/{project_id}/talent-engagements", params or None, headers
        )

    # ─── Deliverable and cut reads ─────────────────────────────────────────

    def get_deliverable(self, deliverable_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/deliverables/{deliverable_id}", None, headers)

    def list_deliverable_change_orders(
        self, deliverable_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        """The only channel through which a cascade-created change order is discoverable."""
        return self._request(
            "GET", f"/deliverables/{deliverable_id}/change-orders", params or None, headers
        )

    def get_deliverable_version(
        self, version_id: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/deliverable-versions/{version_id}", None, headers)

    def list_deliverable_versions(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/deliverable-versions", params or None, headers)

    # ─── Location, shoot-day and certificate reads ─────────────────────────

    def get_location(self, location_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/locations/{location_id}", None, headers)

    def get_shoot_day(self, shoot_day_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/shoot-days/{shoot_day_id}", None, headers)

    def list_shoot_days(self, headers: Optional[dict] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/shoot-days", params or None, headers)

    def list_shoot_day_equipment_reservations(
        self, shoot_day_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/shoot-days/{shoot_day_id}/equipment-reservations", params or None, headers
        )

    def get_compliance_cert(self, cert_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/compliance-certs/{cert_id}", None, headers)

    def list_compliance_certs(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/compliance-certs", params or None, headers)

    # ─── Crew reads ────────────────────────────────────────────────────────

    def get_crew_member(self, crew_member_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/crew-members/{crew_member_id}", None, headers)

    def get_crew_booking(self, booking_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/crew-bookings/{booking_id}", None, headers)

    def list_crew_bookings(self, headers: Optional[dict] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/crew-bookings", params or None, headers)

    # ─── Project writes (PRD §3.1, §3.2, §3.10) ────────────────────────────

    def create_project(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/projects", payload, headers)

    def lock_scope(
        self, project_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/projects/{project_id}/lock-scope", payload or {}, headers)

    def approve_budget(
        self, project_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/projects/{project_id}/approve-budget", payload, headers)

    def handover(
        self, project_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/projects/{project_id}/handover", payload, headers)

    def create_budget_line(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/budget-lines", payload, headers)

    def create_deliverable(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/deliverables", payload, headers)

    # ─── Cut writes (PRD §3.8) ─────────────────────────────────────────────

    def create_deliverable_version(
        self, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        """Upload a new cut. Carries the mandatory ``expected_deliverable_version``."""
        return self._request("POST", "/deliverable-versions", payload, headers)

    def record_qc(
        self, version_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/deliverable-versions/{version_id}/qc", payload or {}, headers
        )

    def submit_version(
        self, version_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/deliverable-versions/{version_id}/submit", payload or {}, headers
        )

    def review_decision(
        self, version_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/deliverable-versions/{version_id}/review-decision", payload, headers
        )

    def change_order_decision(
        self, change_order_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-orders/{change_order_id}/decision", payload, headers
        )

    # ─── Talent engagements (PRD §3.3) ─────────────────────────────────────

    def create_talent_engagement(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/talent-engagements", payload, headers)

    def confirm_talent_engagement(
        self, engagement_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/talent-engagements/{engagement_id}/confirm", payload or {}, headers
        )

    # ─── Locations and shoot days (PRD §3.4, §3.5, §3.7) ───────────────────

    def create_location(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/locations", payload, headers)

    def create_shoot_day(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/shoot-days", payload, headers)

    def confirm_shoot_day(
        self, shoot_day_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/shoot-days/{shoot_day_id}/confirm", payload or {}, headers
        )

    def publish_call_sheet(
        self, shoot_day_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/shoot-days/{shoot_day_id}/publish-call-sheet", payload or {}, headers
        )

    def cancel_shoot_day(
        self, shoot_day_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/shoot-days/{shoot_day_id}/cancel", payload, headers)

    def wrap_shoot_day(
        self, shoot_day_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/shoot-days/{shoot_day_id}/wrap", payload or {}, headers)

    # ─── Compliance certificates (PRD §3.5) ────────────────────────────────

    def create_compliance_cert(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/compliance-certs", payload, headers)

    def compliance_cert_decision(
        self, cert_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/compliance-certs/{cert_id}/decision", payload, headers)

    # ─── Crew and equipment (PRD §3.6) ─────────────────────────────────────

    def create_crew_member(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/crew-members", payload, headers)

    def create_crew_booking(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/crew-bookings", payload, headers)

    def confirm_crew_booking(
        self, booking_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/crew-bookings/{booking_id}/confirm", payload or {}, headers
        )

    def release_crew_booking(
        self, booking_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/crew-bookings/{booking_id}/release", payload or {}, headers
        )

    def create_equipment_reservation(
        self, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", "/equipment-reservations", payload, headers)

    # ─── The logical production clock (PRD §2.5) ───────────────────────────

    def set_clock(self, to_iso8601: str, headers: Optional[dict] = None) -> requests.Response:
        """Move the logical clock. "the response reports the new setting as `current_utc`"."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


# One shared client instance; the runner owns the server lifecycle.
api_client = ApiClient()
