"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Convention ----
    def create_convention(self, payload, headers):
        return self._request("POST", "/conventions", payload, headers)

    def get_convention(self, convention_id, headers):
        return self._request("GET", f"/conventions/{convention_id}", headers=headers)

    def update_convention(self, convention_id, payload, headers):
        return self._request("PUT", f"/conventions/{convention_id}", payload, headers)

    def advance_phase(self, convention_id, headers):
        return self._request(
            "POST", f"/conventions/{convention_id}/advance-phase", {}, headers
        )

    def run_ops(self, convention_id, headers):
        return self._request("POST", f"/conventions/{convention_id}/run-ops", {}, headers)

    # ---- CategoryQuota ----
    def list_category_quotas(self, headers, params=None):
        return self._request("GET", "/category-quotas", headers=headers, params=params)

    def get_category_quota(self, category_quota_id, headers):
        return self._request(
            "GET", f"/category-quotas/{category_quota_id}", headers=headers
        )

    def patch_category_quota(self, category_quota_id, payload, headers):
        return self._request(
            "PATCH", f"/category-quotas/{category_quota_id}", payload, headers
        )

    # ---- SpaceUnit ----
    def create_space_unit(self, payload, headers):
        return self._request("POST", "/space-units", payload, headers)

    def list_space_units(self, headers, params=None):
        return self._request("GET", "/space-units", headers=headers, params=params)

    def get_space_unit(self, space_unit_id, headers):
        return self._request("GET", f"/space-units/{space_unit_id}", headers=headers)

    # ---- Exhibitor ----
    def create_exhibitor(self, payload, headers):
        return self._request("POST", "/exhibitors", payload, headers)

    def get_exhibitor(self, exhibitor_id, headers):
        return self._request("GET", f"/exhibitors/{exhibitor_id}", headers=headers)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def patch_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"/applications/{application_id}", payload, headers
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", {}, headers
        )

    def request_revision(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/request-revision", {}, headers
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decide", payload, headers
        )

    def accept_offer(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/accept-offer", payload, headers
        )

    def decline_offer(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decline", {}, headers
        )

    def cancel_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/cancel", {}, headers
        )

    def purchase_badge_extras(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/badge-extras", payload, headers
        )

    def submit_permit(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit-permit", payload, headers
        )

    def verify_permit(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/verify-permit", {}, headers
        )

    def reject_permit(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/reject-permit", {}, headers
        )

    def claim_exemption(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/claim-exemption", {}, headers
        )

    # ---- JuryScore ----
    def create_jury_score(self, payload, headers):
        return self._request("POST", "/jury-scores", payload, headers)

    def list_jury_scores(self, headers, params=None):
        return self._request("GET", "/jury-scores", headers=headers, params=params)

    def get_jury_score(self, jury_score_id, headers):
        return self._request("GET", f"/jury-scores/{jury_score_id}", headers=headers)

    # ---- Placement ----
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def confirm_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/confirm", {}, headers
        )

    def release_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/release", {}, headers
        )

    # ---- NeighborRequest ----
    def create_neighbor_request(self, payload, headers):
        return self._request("POST", "/neighbor-requests", payload, headers)

    def list_neighbor_requests(self, headers, params=None):
        return self._request("GET", "/neighbor-requests", headers=headers, params=params)

    def get_neighbor_request(self, neighbor_request_id, headers):
        return self._request(
            "GET", f"/neighbor-requests/{neighbor_request_id}", headers=headers
        )

    def withdraw_neighbor_request(self, neighbor_request_id, headers):
        return self._request(
            "POST", f"/neighbor-requests/{neighbor_request_id}/withdraw", {}, headers
        )

    # ---- StaffMember / badges ----
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_member_id, headers):
        return self._request("GET", f"/staff-members/{staff_member_id}", headers=headers)

    def issue_badge(self, staff_member_id, headers):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/issue-badge", {}, headers
        )

    def revoke_badge(self, staff_member_id, headers):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/revoke-badge", {}, headers
        )

    # ---- LoadSlot / DockDoor ----
    def create_load_slot(self, payload, headers):
        return self._request("POST", "/load-slots", payload, headers)

    def list_load_slots(self, headers, params=None):
        return self._request("GET", "/load-slots", headers=headers, params=params)

    def get_load_slot(self, load_slot_id, headers):
        return self._request("GET", f"/load-slots/{load_slot_id}", headers=headers)

    def list_dock_doors(self, headers, params=None):
        return self._request("GET", "/dock-doors", headers=headers, params=params)

    def get_dock_door(self, dock_door_id, headers):
        return self._request("GET", f"/dock-doors/{dock_door_id}", headers=headers)

    # ---- FreightBooking ----
    def create_freight_booking(self, payload, headers):
        return self._request("POST", "/freight-bookings", payload, headers)

    def list_freight_bookings(self, headers, params=None):
        return self._request("GET", "/freight-bookings", headers=headers, params=params)

    def get_freight_booking(self, freight_booking_id, headers):
        return self._request(
            "GET", f"/freight-bookings/{freight_booking_id}", headers=headers
        )

    def confirm_freight_booking(self, freight_booking_id, headers):
        return self._request(
            "POST", f"/freight-bookings/{freight_booking_id}/confirm", {}, headers
        )

    def cancel_freight_booking(self, freight_booking_id, headers):
        return self._request(
            "POST", f"/freight-bookings/{freight_booking_id}/cancel", {}, headers
        )

    def check_in_freight_booking(self, freight_booking_id, headers):
        return self._request(
            "POST", f"/freight-bookings/{freight_booking_id}/check-in", {}, headers
        )

    # ---- IssueTicket ----
    def create_issue_ticket(self, payload, headers):
        return self._request("POST", "/issue-tickets", payload, headers)

    def list_issue_tickets(self, headers, params=None):
        return self._request("GET", "/issue-tickets", headers=headers, params=params)

    def get_issue_ticket(self, issue_ticket_id, headers):
        return self._request("GET", f"/issue-tickets/{issue_ticket_id}", headers=headers)

    def triage_issue(self, issue_ticket_id, headers):
        return self._request(
            "POST", f"/issue-tickets/{issue_ticket_id}/triage", {}, headers
        )

    def escalate_issue(self, issue_ticket_id, headers):
        return self._request(
            "POST", f"/issue-tickets/{issue_ticket_id}/escalate", {}, headers
        )

    def resolve_issue(self, issue_ticket_id, payload, headers):
        return self._request(
            "POST", f"/issue-tickets/{issue_ticket_id}/resolve", payload, headers
        )

    # ---- SalesReport ----
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/sales-reports", payload, headers)

    def list_sales_reports(self, headers, params=None):
        return self._request("GET", "/sales-reports", headers=headers, params=params)

    def get_sales_report(self, sales_report_id, headers):
        return self._request("GET", f"/sales-reports/{sales_report_id}", headers=headers)

    def submit_sales_report(self, sales_report_id, headers):
        return self._request(
            "POST", f"/sales-reports/{sales_report_id}/submit", {}, headers
        )


api_client = ApiClient()
