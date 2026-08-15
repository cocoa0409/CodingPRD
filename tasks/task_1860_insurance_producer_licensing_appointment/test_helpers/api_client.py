"""API client: one method per endpoint defined in the PRD (all under /api,
plus the CarrierAdmin logical-clock endpoint)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Agencies ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/api/agencies", payload, headers)

    # --- Producers ---
    def create_producer(self, payload, headers):
        return self._request("POST", "/api/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/api/producers/{producer_id}", headers=headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", "/api/producers", headers=headers, params=params)

    def reinstate_producer(self, producer_id, headers):
        return self._request("POST", f"/api/producers/{producer_id}/reinstate", {}, headers)

    def get_producer_eligibility(self, producer_id, headers, params=None):
        return self._request(
            "GET", f"/api/producers/{producer_id}/eligibility",
            headers=headers, params=params,
        )

    # --- Licenses ---
    def create_license(self, payload, headers):
        return self._request("POST", "/api/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/api/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/api/licenses", headers=headers, params=params)

    def renew_license(self, license_id, payload, headers):
        return self._request("POST", f"/api/licenses/{license_id}/renew", payload, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/api/licenses/{license_id}/reinstate", {}, headers)

    # --- CE credits ---
    def create_ce_credit(self, payload, headers):
        return self._request("POST", "/api/ce-credits", payload, headers)

    def get_ce_credit(self, ce_credit_id, headers):
        return self._request("GET", f"/api/ce-credits/{ce_credit_id}", headers=headers)

    def list_ce_credits(self, headers, params=None):
        return self._request("GET", "/api/ce-credits", headers=headers, params=params)

    def review_ce_credit(self, ce_credit_id, payload, headers):
        return self._request("POST", f"/api/ce-credits/{ce_credit_id}/review", payload, headers)

    # --- Appointments ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/api/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/api/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/api/appointments", headers=headers, params=params)

    def file_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/appointments/{appointment_id}/file", {}, headers)

    def terminate_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/terminate", payload, headers
        )

    def file_termination(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/file-termination", {}, headers
        )

    def rescind_termination(self, appointment_id, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/rescind-termination", {}, headers
        )

    # --- Policy applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/api/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/api/applications", headers=headers, params=params)

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/decide", payload, headers
        )

    def issue_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/issue", {}, headers)

    def rescind_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/applications/{application_id}/rescind", {}, headers
        )

    # --- Commission entries ---
    def get_commission_entry(self, commission_entry_id, headers):
        return self._request(
            "GET", f"/api/commission-entries/{commission_entry_id}", headers=headers
        )

    def list_commission_entries(self, headers, params=None):
        return self._request("GET", "/api/commission-entries", headers=headers, params=params)

    def release_commission_entry(self, commission_entry_id, headers):
        return self._request(
            "POST", f"/api/commission-entries/{commission_entry_id}/release", {}, headers
        )

    def pay_commission_entry(self, commission_entry_id, headers):
        return self._request(
            "POST", f"/api/commission-entries/{commission_entry_id}/pay", {}, headers
        )

    # --- Regulatory actions ---
    def create_regulatory_action(self, payload, headers):
        return self._request("POST", "/api/regulatory-actions", payload, headers)

    def get_regulatory_action(self, regulatory_action_id, headers):
        return self._request(
            "GET", f"/api/regulatory-actions/{regulatory_action_id}", headers=headers
        )

    def list_regulatory_actions(self, headers, params=None):
        return self._request("GET", "/api/regulatory-actions", headers=headers, params=params)

    def confirm_regulatory_action(self, regulatory_action_id, headers):
        return self._request(
            "POST", f"/api/regulatory-actions/{regulatory_action_id}/confirm", {}, headers
        )

    def dismiss_regulatory_action(self, regulatory_action_id, headers):
        return self._request(
            "POST", f"/api/regulatory-actions/{regulatory_action_id}/dismiss", {}, headers
        )

    # --- Regulatory inquiries ---
    def create_inquiry(self, payload, headers):
        return self._request("POST", "/api/inquiries", payload, headers)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/api/inquiries/{inquiry_id}", headers=headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/api/inquiries", headers=headers, params=params)

    def respond_to_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/api/inquiries/{inquiry_id}/response", payload, headers)

    def close_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/api/inquiries/{inquiry_id}/close", {}, headers)

    # --- Logical clock (CarrierAdmin only) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
