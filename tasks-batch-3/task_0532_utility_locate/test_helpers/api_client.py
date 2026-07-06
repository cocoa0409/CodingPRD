"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Excavator ----
    def create_excavator(self, payload, headers):
        return self._request("POST", "/excavators", payload, headers)

    def list_excavators(self, headers, params=None):
        return self._request("GET", "/excavators", headers=headers, params=params)

    def get_excavator(self, excavator_id, headers):
        return self._request("GET", f"/excavators/{excavator_id}", headers=headers)

    def suspend_excavator(self, excavator_id, headers):
        return self._request("POST", f"/excavators/{excavator_id}/suspend", headers=headers)

    # ---- MemberUtility ----
    def create_member_utility(self, payload, headers):
        return self._request("POST", "/member-utilities", payload, headers)

    def list_member_utilities(self, headers, params=None):
        return self._request("GET", "/member-utilities", headers=headers, params=params)

    def get_member_utility(self, member_utility_id, headers):
        return self._request("GET", f"/member-utilities/{member_utility_id}", headers=headers)

    def deactivate_member_utility(self, member_utility_id, headers):
        return self._request("POST", f"/member-utilities/{member_utility_id}/deactivate", headers=headers)

    # ---- LocateTech ----
    def create_locate_tech(self, payload, headers):
        return self._request("POST", "/locate-techs", payload, headers)

    def list_locate_techs(self, headers, params=None):
        return self._request("GET", "/locate-techs", headers=headers, params=params)

    def get_locate_tech(self, locate_tech_id, headers):
        return self._request("GET", f"/locate-techs/{locate_tech_id}", headers=headers)

    def set_tech_off_duty(self, locate_tech_id, headers):
        return self._request("POST", f"/locate-techs/{locate_tech_id}/set-off-duty", headers=headers)

    # ---- LocateTicket ----
    def create_locate_ticket(self, payload, headers):
        return self._request("POST", "/locate-tickets", payload, headers)

    def list_locate_tickets(self, headers, params=None):
        return self._request("GET", "/locate-tickets", headers=headers, params=params)

    def get_locate_ticket(self, ticket_id, headers):
        return self._request("GET", f"/locate-tickets/{ticket_id}", headers=headers)

    def submit_ticket(self, ticket_id, headers):
        return self._request("POST", f"/locate-tickets/{ticket_id}/submit", headers=headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/locate-tickets/{ticket_id}/close", headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/locate-tickets/{ticket_id}/cancel", headers=headers)

    def list_ticket_notifications(self, ticket_id, headers, params=None):
        return self._request("GET", f"/locate-tickets/{ticket_id}/notifications", headers=headers, params=params)

    def list_ticket_mark_outs(self, ticket_id, headers, params=None):
        return self._request("GET", f"/locate-tickets/{ticket_id}/mark-outs", headers=headers, params=params)

    def list_ticket_meet_requests(self, ticket_id, headers, params=None):
        return self._request("GET", f"/locate-tickets/{ticket_id}/meet-requests", headers=headers, params=params)

    def list_ticket_damage_reports(self, ticket_id, headers, params=None):
        return self._request("GET", f"/locate-tickets/{ticket_id}/damage-reports", headers=headers, params=params)

    # ---- UtilityNotification ----
    def list_utility_notifications(self, headers, params=None):
        return self._request("GET", "/utility-notifications", headers=headers, params=params)

    def get_utility_notification(self, notification_id, headers):
        return self._request("GET", f"/utility-notifications/{notification_id}", headers=headers)

    # ---- PositiveResponse ----
    def create_positive_response(self, payload, headers):
        return self._request("POST", "/positive-responses", payload, headers)

    def list_positive_responses(self, headers, params=None):
        return self._request("GET", "/positive-responses", headers=headers, params=params)

    def get_positive_response(self, positive_response_id, headers):
        return self._request("GET", f"/positive-responses/{positive_response_id}", headers=headers)

    # ---- LocateAssignment ----
    def create_locate_assignment(self, payload, headers):
        return self._request("POST", "/locate-assignments", payload, headers)

    def list_locate_assignments(self, headers, params=None):
        return self._request("GET", "/locate-assignments", headers=headers, params=params)

    def get_locate_assignment(self, assignment_id, headers):
        return self._request("GET", f"/locate-assignments/{assignment_id}", headers=headers)

    def assignment_en_route(self, assignment_id, headers):
        return self._request("POST", f"/locate-assignments/{assignment_id}/en-route", headers=headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/locate-assignments/{assignment_id}/complete", headers=headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/locate-assignments/{assignment_id}/cancel", headers=headers)

    # ---- MarkOut ----
    def create_mark_out(self, payload, headers):
        return self._request("POST", "/mark-outs", payload, headers)

    def list_mark_outs(self, headers, params=None):
        return self._request("GET", "/mark-outs", headers=headers, params=params)

    def get_mark_out(self, mark_out_id, headers):
        return self._request("GET", f"/mark-outs/{mark_out_id}", headers=headers)

    def complete_mark_out(self, mark_out_id, headers):
        return self._request("POST", f"/mark-outs/{mark_out_id}/complete", headers=headers)

    # ---- MeetRequest ----
    def create_meet_request(self, payload, headers):
        return self._request("POST", "/meet-requests", payload, headers)

    def list_meet_requests(self, headers, params=None):
        return self._request("GET", "/meet-requests", headers=headers, params=params)

    def get_meet_request(self, meet_request_id, headers):
        return self._request("GET", f"/meet-requests/{meet_request_id}", headers=headers)

    def schedule_meet_request(self, meet_request_id, headers):
        return self._request("POST", f"/meet-requests/{meet_request_id}/schedule", headers=headers)

    def complete_meet_request(self, meet_request_id, headers):
        return self._request("POST", f"/meet-requests/{meet_request_id}/complete", headers=headers)

    def decline_meet_request(self, meet_request_id, headers):
        return self._request("POST", f"/meet-requests/{meet_request_id}/decline", headers=headers)

    # ---- DamageReport ----
    def create_damage_report(self, payload, headers):
        return self._request("POST", "/damage-reports", payload, headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/damage-reports", headers=headers, params=params)

    def get_damage_report(self, damage_report_id, headers):
        return self._request("GET", f"/damage-reports/{damage_report_id}", headers=headers)

    def review_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/damage-reports/{damage_report_id}/review", headers=headers)

    def settle_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/damage-reports/{damage_report_id}/settle", headers=headers)

    def dispute_damage_report(self, damage_report_id, headers):
        return self._request("POST", f"/damage-reports/{damage_report_id}/dispute", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
