"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def transition_site(self, site_id, to_status, headers):
        return self._request(
            "POST", f"/sites/{site_id}/state", {"to_status": to_status}, headers
        )

    def list_site_volunteers(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}/volunteers", headers=headers)

    def create_site_report(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/reports", payload, headers)

    def list_site_reports(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}/reports", headers=headers)

    def transition_site_report(self, report_id, to_status, headers):
        return self._request(
            "POST", f"/site-reports/{report_id}/state", {"to_status": to_status}, headers
        )

    # ------------------------------------------------------------------
    # Volunteers and certifications
    # ------------------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def transition_volunteer(self, volunteer_id, to_status, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/state", {"to_status": to_status}, headers
        )

    def record_certification(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/certifications", payload, headers
        )

    def list_certifications(self, volunteer_id, headers):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/certifications", headers=headers
        )

    # ------------------------------------------------------------------
    # Taxpayers
    # ------------------------------------------------------------------
    def create_taxpayer(self, payload, headers):
        return self._request("POST", "/taxpayers", payload, headers)

    def get_taxpayer(self, taxpayer_id, headers):
        return self._request("GET", f"/taxpayers/{taxpayer_id}", headers=headers)

    def verify_identity(self, taxpayer_id, id_document_type, headers):
        return self._request(
            "POST",
            f"/taxpayers/{taxpayer_id}/verify-identity",
            {"id_document_type": id_document_type},
            headers,
        )

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def patch_appointment(self, appointment_id, payload, headers):
        return self._request(
            "PATCH", f"/appointments/{appointment_id}", payload, headers
        )

    def transition_appointment(self, appointment_id, to_status, headers):
        return self._request(
            "POST",
            f"/appointments/{appointment_id}/state",
            {"to_status": to_status},
            headers,
        )

    # ------------------------------------------------------------------
    # Tax returns
    # ------------------------------------------------------------------
    def create_tax_return(self, payload, headers):
        return self._request("POST", "/tax-returns", payload, headers)

    def list_tax_returns(self, headers, params=None):
        return self._request("GET", "/tax-returns", headers=headers, params=params)

    def get_tax_return(self, return_id, headers):
        return self._request("GET", f"/tax-returns/{return_id}", headers=headers)

    def patch_tax_return(self, return_id, payload, headers):
        return self._request("PATCH", f"/tax-returns/{return_id}", payload, headers)

    def transition_tax_return(self, return_id, payload, headers):
        return self._request("POST", f"/tax-returns/{return_id}/state", payload, headers)

    # ------------------------------------------------------------------
    # Refund allocations
    # ------------------------------------------------------------------
    def create_refund_allocation(self, payload, headers):
        return self._request("POST", "/refund-allocations", payload, headers)

    def delete_refund_allocation(self, allocation_id, headers):
        return self._request(
            "DELETE", f"/refund-allocations/{allocation_id}", headers=headers
        )

    def list_refund_allocations(self, return_id, headers):
        return self._request(
            "GET", f"/tax-returns/{return_id}/refund-allocations", headers=headers
        )

    # ------------------------------------------------------------------
    # E-file rejections
    # ------------------------------------------------------------------
    def list_efile_rejections(self, return_id, headers):
        return self._request(
            "GET", f"/tax-returns/{return_id}/rejections", headers=headers
        )

    def record_follow_up(self, rejection_id, payload, headers):
        return self._request(
            "POST", f"/efile-rejections/{rejection_id}/follow-up", payload, headers
        )

    # ------------------------------------------------------------------
    # Financial-service referrals
    # ------------------------------------------------------------------
    def create_financial_referral(self, return_id, service_type, headers):
        return self._request(
            "POST",
            f"/tax-returns/{return_id}/financial-referrals",
            {"service_type": service_type},
            headers,
        )

    def list_financial_referrals(self, return_id, headers):
        return self._request(
            "GET", f"/tax-returns/{return_id}/financial-referrals", headers=headers
        )

    def transition_financial_referral(self, referral_id, to_status, headers):
        return self._request(
            "POST",
            f"/financial-referrals/{referral_id}/state",
            {"to_status": to_status},
            headers,
        )


api_client = ApiClient()
