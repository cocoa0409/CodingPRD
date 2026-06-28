"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; only PRD-specific endpoint methods are defined
here. The base _request() handles the envelope and HTTP transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (test-driving) ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Member ───────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    # ─── Waiver ───────────────────────────────────────────────────────────
    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    # ─── Membership ───────────────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def freeze_quote(self, membership_id, headers):
        return self._request(
            "GET", f"/memberships/{membership_id}/freeze-quote", headers=headers)

    def freeze_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/freeze", payload, headers)

    def resume_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/resume", payload, headers)

    def run_billing(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/run-billing", payload, headers)

    def cancel_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/cancel", payload, headers)

    # ─── Certification ────────────────────────────────────────────────────
    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def grade_certification(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/certifications/{cert_id}/grade", payload, headers)

    def refresh_certification(self, cert_id, headers):
        return self._request(
            "POST", f"/certifications/{cert_id}/refresh-status", headers=headers)

    # ─── Facility ─────────────────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def list_facility_routes(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/routes", headers=headers, params=params)

    def list_facility_checkins(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/check-ins", headers=headers, params=params)

    def list_facility_incidents(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/incidents", headers=headers, params=params)

    def setter_report(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/setter-report", headers=headers, params=params)

    # ─── Route ────────────────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def strip_route(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/strip", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    # ─── CheckIn ──────────────────────────────────────────────────────────
    def create_checkin(self, payload, headers):
        return self._request("POST", "/check-ins", payload, headers)

    def get_checkin(self, checkin_id, headers):
        return self._request("GET", f"/check-ins/{checkin_id}", headers=headers)

    def list_checkins(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    def check_out(self, checkin_id, headers):
        return self._request("POST", f"/check-ins/{checkin_id}/check-out", headers=headers)

    # ─── Clinic ───────────────────────────────────────────────────────────
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    def cancel_clinic(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/cancel", payload, headers)

    def list_clinic_enrollments(self, clinic_id, headers, params=None):
        return self._request(
            "GET", f"/clinics/{clinic_id}/enrollments", headers=headers, params=params)

    # ─── Enrollment ───────────────────────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", headers=headers)

    # ─── Rental ───────────────────────────────────────────────────────────
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def return_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rentals/{rental_id}/return", payload, headers)

    def report_lost_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rentals/{rental_id}/report-lost", payload, headers)

    # ─── Incident ─────────────────────────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def resolve_incident(self, incident_id, headers):
        return self._request("POST", f"/incidents/{incident_id}/resolve", headers=headers)


api_client = ApiClient()
