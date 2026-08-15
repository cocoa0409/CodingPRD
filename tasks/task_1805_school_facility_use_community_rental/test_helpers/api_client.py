"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/district/_clock/set_current_utc", payload, headers)

    # --- Sites & facilities ---
    def create_site(self, payload, headers):
        return self._request("POST", "/district/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/district/sites/{site_id}", headers=headers)

    def close_site(self, site_id, payload, headers):
        return self._request("POST", f"/district/sites/{site_id}/close", payload, headers)

    def list_site_facilities(self, site_id, headers, params=None):
        return self._request("GET", f"/district/sites/{site_id}/facilities", headers=headers, params=params)

    def create_facility(self, site_id, payload, headers):
        return self._request("POST", f"/district/sites/{site_id}/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/district/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/district/facilities/{facility_id}", headers=headers)

    def hold_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/district/facilities/{facility_id}/hold", payload, headers)

    def release_facility_hold(self, facility_id, headers):
        return self._request("POST", f"/district/facilities/{facility_id}/release_hold", headers=headers)

    def retire_facility(self, facility_id, headers):
        return self._request("POST", f"/district/facilities/{facility_id}/retire", headers=headers)

    # --- Rate policies ---
    def create_rate_policy(self, payload, headers):
        return self._request("POST", "/district/rate_policies", payload, headers)

    def list_rate_policies(self, headers, params=None):
        return self._request("GET", "/district/rate_policies", headers=headers, params=params)

    def get_rate_policy(self, policy_id, headers):
        return self._request("GET", f"/district/rate_policies/{policy_id}", headers=headers)

    # --- Renters ---
    def create_renter(self, payload, headers):
        return self._request("POST", "/district/renters", payload, headers)

    def get_renter(self, org_id, headers):
        return self._request("GET", f"/district/renters/{org_id}", headers=headers)

    def list_renters(self, headers, params=None):
        return self._request("GET", "/district/renters", headers=headers, params=params)

    def bar_renter(self, org_id, payload, headers):
        return self._request("POST", f"/district/renters/{org_id}/bar", payload, headers)

    def list_renter_requests(self, org_id, headers, params=None):
        return self._request("GET", f"/district/renters/{org_id}/requests", headers=headers, params=params)

    def list_renter_insurance_certificates(self, org_id, headers, params=None):
        return self._request("GET", f"/district/renters/{org_id}/insurance_certificates", headers=headers, params=params)

    def list_renter_seasonal_permits(self, org_id, headers, params=None):
        return self._request("GET", f"/district/renters/{org_id}/seasonal_permits", headers=headers, params=params)

    # --- Insurance ---
    def upload_insurance_certificate(self, org_id, payload, headers):
        return self._request("POST", f"/district/renters/{org_id}/insurance_certificates", payload, headers)

    def list_insurance_certificates(self, headers, params=None):
        return self._request("GET", "/district/insurance_certificates", headers=headers, params=params)

    def get_insurance_certificate(self, cert_id, headers):
        return self._request("GET", f"/district/insurance_certificates/{cert_id}", headers=headers)

    def revoke_insurance_certificate(self, cert_id, payload, headers):
        return self._request("POST", f"/district/insurance_certificates/{cert_id}/revoke", payload, headers)

    # --- Calendar events ---
    def create_calendar_event(self, site_id, payload, headers):
        return self._request("POST", f"/district/sites/{site_id}/calendar_events", payload, headers)

    def list_site_calendar_events(self, site_id, headers, params=None):
        return self._request("GET", f"/district/sites/{site_id}/calendar_events", headers=headers, params=params)

    def list_calendar_events(self, headers, params=None):
        return self._request("GET", "/district/calendar_events", headers=headers, params=params)

    def get_calendar_event(self, event_id, headers):
        return self._request("GET", f"/district/calendar_events/{event_id}", headers=headers)

    def cancel_calendar_event(self, event_id, headers):
        return self._request("POST", f"/district/calendar_events/{event_id}/cancel", headers=headers)

    # --- Rental requests ---
    def create_request(self, org_id, payload, headers):
        return self._request("POST", f"/district/renters/{org_id}/requests", payload, headers)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/district/requests/{request_id}", headers=headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/district/requests", headers=headers, params=params)

    def submit_request(self, org_id, request_id, headers):
        return self._request("POST", f"/district/renters/{org_id}/requests/{request_id}/submit", {}, headers)

    def resubmit_request(self, org_id, request_id, payload, headers):
        return self._request("POST", f"/district/renters/{org_id}/requests/{request_id}/resubmit", payload, headers)

    def withdraw_request(self, org_id, request_id, headers):
        return self._request("POST", f"/district/renters/{org_id}/requests/{request_id}/withdraw", {}, headers)

    def begin_review(self, request_id, headers):
        return self._request("POST", f"/district/requests/{request_id}/begin_review", {}, headers)

    def request_revision(self, request_id, payload, headers):
        return self._request("POST", f"/district/requests/{request_id}/request_revision", payload, headers)

    def approve_request(self, request_id, payload, headers):
        return self._request("POST", f"/district/requests/{request_id}/approve", payload, headers)

    def deny_request(self, request_id, payload, headers):
        return self._request("POST", f"/district/requests/{request_id}/deny", payload, headers)

    def waitlist_request(self, request_id, payload, headers):
        return self._request("POST", f"/district/requests/{request_id}/waitlist", payload, headers)

    # --- Permits ---
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/district/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/district/permits", headers=headers, params=params)

    def list_request_permits(self, request_id, headers):
        return self._request("GET", f"/district/requests/{request_id}/permits", headers=headers)

    def cancel_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/district/permits/{permit_id}/cancel", payload, headers)

    def complete_permit(self, permit_id, headers):
        return self._request("POST", f"/district/permits/{permit_id}/complete", {}, headers)

    def list_permit_work_orders(self, permit_id, headers):
        return self._request("GET", f"/district/permits/{permit_id}/work_orders", headers=headers)

    def list_permit_invoices(self, permit_id, headers, params=None):
        return self._request("GET", f"/district/permits/{permit_id}/invoices", headers=headers, params=params)

    def list_permit_payments(self, permit_id, headers, params=None):
        return self._request("GET", f"/district/permits/{permit_id}/payments", headers=headers, params=params)

    def list_permit_damage_assessments(self, permit_id, headers, params=None):
        return self._request("GET", f"/district/permits/{permit_id}/damage_assessments", headers=headers, params=params)

    # --- Payments ---
    def post_payment(self, permit_id, payload, headers):
        return self._request("POST", f"/district/permits/{permit_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/district/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/district/payments", headers=headers, params=params)

    # --- Work orders ---
    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/district/work_orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/district/work_orders", headers=headers, params=params)

    def verify_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/district/work_orders/{wo_id}/verify", payload, headers)

    # --- Invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/district/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/district/invoices", headers=headers, params=params)

    # --- Damage assessments ---
    def create_damage_assessment(self, permit_id, payload, headers):
        return self._request("POST", f"/district/permits/{permit_id}/damage_assessments", payload, headers)

    def list_damage_assessments(self, headers, params=None):
        return self._request("GET", "/district/damage_assessments", headers=headers, params=params)

    def get_damage_assessment(self, assessment_id, headers):
        return self._request("GET", f"/district/damage_assessments/{assessment_id}", headers=headers)

    def adjudicate_damage_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/district/damage_assessments/{assessment_id}/adjudicate", payload, headers)

    def accept_damage_assessment(self, assessment_id, headers):
        return self._request("POST", f"/district/damage_assessments/{assessment_id}/accept", {}, headers)

    def appeal_damage_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/district/damage_assessments/{assessment_id}/appeal", payload, headers)

    def resolve_damage_appeal(self, assessment_id, payload, headers):
        return self._request("POST", f"/district/damage_assessments/{assessment_id}/resolve_appeal", payload, headers)

    # --- Seasonal permits ---
    def create_seasonal_permit(self, payload, headers):
        return self._request("POST", "/district/seasonal_permits", payload, headers)

    def get_seasonal_permit(self, series_id, headers):
        return self._request("GET", f"/district/seasonal_permits/{series_id}", headers=headers)

    def list_seasonal_permits(self, headers, params=None):
        return self._request("GET", "/district/seasonal_permits", headers=headers, params=params)

    def cancel_seasonal_permit(self, series_id, payload, headers):
        return self._request("POST", f"/district/seasonal_permits/{series_id}/cancel", payload, headers)


api_client = ApiClient()
