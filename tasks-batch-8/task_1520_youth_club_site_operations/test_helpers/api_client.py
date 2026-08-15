"""API client: one method per endpoint defined in PRD Section 4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def list_staff(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/staff", headers=headers, params=params)

    def post_staff_credential(self, staff_id, payload, headers):
        return self._request("POST", f"/staff/{staff_id}/credentials", payload, headers)

    def list_staff_rotation_assignments(self, staff_id, headers, params=None):
        return self._request(
            "GET", f"/staff/{staff_id}/rotation-assignments", headers=headers, params=params
        )

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/members", headers=headers, params=params)

    def decide_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/decide", payload, headers)

    def withdraw_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/withdraw", {}, headers)

    def post_fee_payment(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/fee-payments", payload, headers)

    # --- Guardians ---
    def create_guardian(self, payload, headers):
        return self._request("POST", "/guardians", payload, headers)

    def list_guardians(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/guardians", headers=headers, params=params)

    def revoke_guardian(self, guardian_id, headers):
        return self._request("POST", f"/guardians/{guardian_id}/revoke", {}, headers)

    # --- Scholarship funds & awards ---
    def create_scholarship_fund(self, payload, headers):
        return self._request("POST", "/scholarship-funds", payload, headers)

    def get_scholarship_fund(self, fund_id, headers):
        return self._request("GET", f"/scholarship-funds/{fund_id}", headers=headers)

    def list_scholarship_funds(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/scholarship-funds", headers=headers, params=params
        )

    def close_scholarship_fund(self, fund_id, headers):
        return self._request("POST", f"/scholarship-funds/{fund_id}/close", {}, headers)

    def list_fund_awards(self, fund_id, headers, params=None):
        return self._request(
            "GET", f"/scholarship-funds/{fund_id}/awards", headers=headers, params=params
        )

    def create_scholarship_award(self, payload, headers):
        return self._request("POST", "/scholarship-awards", payload, headers)

    def list_member_awards(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/scholarship-awards", headers=headers, params=params
        )

    def activate_scholarship_award(self, award_id, payload, headers):
        return self._request("POST", f"/scholarship-awards/{award_id}/activate", payload, headers)

    def revoke_scholarship_award(self, award_id, headers):
        return self._request("POST", f"/scholarship-awards/{award_id}/revoke", {}, headers)

    # --- Club days ---
    def create_club_day(self, payload, headers):
        return self._request("POST", "/club-days", payload, headers)

    def get_club_day(self, day_id, headers):
        return self._request("GET", f"/club-days/{day_id}", headers=headers)

    def list_club_days(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/club-days", headers=headers, params=params)

    def close_club_day(self, day_id, headers):
        return self._request("POST", f"/club-days/{day_id}/close", {}, headers)

    def reconcile_club_day(self, day_id, headers):
        return self._request("POST", f"/club-days/{day_id}/reconcile", {}, headers)

    def upsert_meal_counts(self, day_id, payload, headers):
        return self._request("POST", f"/club-days/{day_id}/meal-counts", payload, headers)

    # --- Attendance ---
    def create_attendance_record(self, payload, headers):
        return self._request("POST", "/attendance-records", payload, headers)

    def sign_out_attendance(self, attendance_id, payload, headers):
        return self._request("POST", f"/attendance-records/{attendance_id}/sign-out", payload, headers)

    def list_day_attendance(self, day_id, headers, params=None):
        return self._request(
            "GET", f"/club-days/{day_id}/attendance-records", headers=headers, params=params
        )

    def list_member_attendance(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/attendance-records", headers=headers, params=params
        )

    # --- Program areas & rotation ---
    def create_program_area(self, payload, headers):
        return self._request("POST", "/program-areas", payload, headers)

    def get_program_area(self, area_id, headers):
        return self._request("GET", f"/program-areas/{area_id}", headers=headers)

    def list_program_areas(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/program-areas", headers=headers, params=params)

    def list_area_rotation_assignments(self, area_id, headers, params=None):
        return self._request(
            "GET", f"/program-areas/{area_id}/rotation-assignments", headers=headers, params=params
        )

    def create_rotation_assignment(self, payload, headers):
        return self._request("POST", "/rotation-assignments", payload, headers)

    def check_in_rotation_assignment(self, assignment_id, headers):
        return self._request("POST", f"/rotation-assignments/{assignment_id}/check-in", {}, headers)

    def move_rotation_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/rotation-assignments/{assignment_id}/move", payload, headers)

    def list_day_rotation_assignments(self, day_id, headers, params=None):
        return self._request(
            "GET", f"/club-days/{day_id}/rotation-assignments", headers=headers, params=params
        )

    def list_member_rotation_assignments(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/rotation-assignments", headers=headers, params=params
        )

    # --- Transport ---
    def create_transport_route(self, payload, headers):
        return self._request("POST", "/transport-routes", payload, headers)

    def get_transport_route(self, route_id, headers):
        return self._request("GET", f"/transport-routes/{route_id}", headers=headers)

    def list_transport_routes(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/transport-routes", headers=headers, params=params
        )

    def list_route_ride_assignments(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/transport-routes/{route_id}/ride-assignments", headers=headers, params=params
        )

    def create_ride_assignment(self, payload, headers):
        return self._request("POST", "/ride-assignments", payload, headers)

    def end_ride_assignment(self, ride_id, payload, headers):
        return self._request("POST", f"/ride-assignments/{ride_id}/end", payload, headers)

    def list_member_ride_assignments(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/ride-assignments", headers=headers, params=params
        )

    # --- Meal claims ---
    def create_meal_claim(self, payload, headers):
        return self._request("POST", "/meal-claims", payload, headers)

    def list_meal_claims(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/meal-claims", headers=headers, params=params)

    def submit_meal_claim(self, claim_id, headers):
        return self._request("POST", f"/meal-claims/{claim_id}/submit", {}, headers)

    def approve_meal_claim(self, claim_id, headers):
        return self._request("POST", f"/meal-claims/{claim_id}/approve", {}, headers)

    # --- Behavior incidents ---
    def create_behavior_incident(self, payload, headers):
        return self._request("POST", "/behavior-incidents", payload, headers)

    def list_member_incidents(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/behavior-incidents", headers=headers, params=params
        )

    def adjudicate_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/behavior-incidents/{incident_id}/adjudicate", payload, headers)

    def appeal_incident(self, incident_id, headers):
        return self._request("POST", f"/behavior-incidents/{incident_id}/appeal", {}, headers)

    def resolve_appeal(self, incident_id, payload, headers):
        return self._request("POST", f"/behavior-incidents/{incident_id}/resolve-appeal", payload, headers)

    # --- Funder reports ---
    def create_funder_report(self, payload, headers):
        return self._request("POST", "/funder-reports", payload, headers)

    def list_funder_reports(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/sites/{site_id}/funder-reports", headers=headers, params=params
        )

    def submit_funder_report(self, report_id, headers):
        return self._request("POST", f"/funder-reports/{report_id}/submit", {}, headers)

    def accept_funder_report(self, report_id, headers):
        return self._request("POST", f"/funder-reports/{report_id}/accept", {}, headers)


api_client = ApiClient()
