"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Customer ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---------------- Designer ----------------
    def create_designer(self, payload, headers):
        return self._request("POST", "/designers", payload, headers)

    def get_designer(self, designer_id, headers):
        return self._request("GET", f"/designers/{designer_id}", headers=headers)

    # ---------------- Crew ----------------
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ---------------- Project ----------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def resolve_permit(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/resolve-permit", payload, headers)

    def cancel_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", payload, headers)

    # ---------------- DesignAppointment ----------------
    def create_design_appointment(self, payload, headers):
        return self._request("POST", "/design-appointments", payload, headers)

    def list_design_appointments(self, headers, params=None):
        return self._request("GET", "/design-appointments", headers=headers, params=params)

    def get_design_appointment(self, appointment_id, headers):
        return self._request("GET", f"/design-appointments/{appointment_id}", headers=headers)

    def complete_design_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/design-appointments/{appointment_id}/complete", payload, headers)

    def cancel_design_appointment(self, appointment_id, headers):
        return self._request("POST", f"/design-appointments/{appointment_id}/cancel", {}, headers)

    # ---------------- Quote ----------------
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def present_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/present", {}, headers)

    def request_revision(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/request-revision", {}, headers)

    def finance_decide(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/finance-decide", payload, headers)

    def accept_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", {}, headers)

    # ---------------- InstallBooking ----------------
    def create_install_booking(self, payload, headers):
        return self._request("POST", "/install-bookings", payload, headers)

    def list_install_bookings(self, headers, params=None):
        return self._request("GET", "/install-bookings", headers=headers, params=params)

    def get_install_booking(self, booking_id, headers):
        return self._request("GET", f"/install-bookings/{booking_id}", headers=headers)

    def complete_install_booking(self, booking_id, headers):
        return self._request("POST", f"/install-bookings/{booking_id}/complete", {}, headers)

    def cancel_install_booking(self, booking_id, headers):
        return self._request("POST", f"/install-bookings/{booking_id}/cancel", {}, headers)

    # ---------------- WarrantyClaim ----------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/decide", payload, headers)

    # ---------------- Referral ----------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def void_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/void", {}, headers)

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
