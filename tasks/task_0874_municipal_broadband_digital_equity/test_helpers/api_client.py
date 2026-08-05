"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Grant ----
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def create_grant_claim(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/claims", payload, headers)

    def list_grant_claims(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/claims", headers=headers, params=params)

    # ---- ServiceArea ----
    def create_service_area(self, payload, headers):
        return self._request("POST", "/service-areas", payload, headers)

    def get_service_area(self, area_id, headers):
        return self._request("GET", f"/service-areas/{area_id}", headers=headers)

    def list_service_areas(self, headers, params=None):
        return self._request("GET", "/service-areas", headers=headers, params=params)

    def advance_service_area(self, area_id, headers):
        return self._request("POST", f"/service-areas/{area_id}/advance", {}, headers)

    def suspend_service_area(self, area_id, headers, payload=None):
        return self._request("POST", f"/service-areas/{area_id}/suspend", payload or {}, headers)

    def reinstate_service_area(self, area_id, headers):
        return self._request("POST", f"/service-areas/{area_id}/reinstate", {}, headers)

    # ---- ServicePlan ----
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    # ---- SubsidyProgram ----
    def create_subsidy_program(self, payload, headers):
        return self._request("POST", "/subsidy-programs", payload, headers)

    def get_subsidy_program(self, program_id, headers):
        return self._request("GET", f"/subsidy-programs/{program_id}", headers=headers)

    # ---- Subscriber ----
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/subscribers", headers=headers, params=params)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/activate", {}, headers)

    def suspend_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/suspend", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    def generate_invoice(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/invoices", payload, headers)

    def list_invoices(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/invoices", headers=headers, params=params)

    # ---- Invoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def verify_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/verify", {}, headers)

    def recertify_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/recertify", payload or {}, headers)

    def terminate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/terminate", payload or {}, headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"/technicians/{technician_id}/deactivate", {}, headers)

    # ---- InstallOrder ----
    def create_install_order(self, payload, headers):
        return self._request("POST", "/install-orders", payload, headers)

    def get_install_order(self, install_id, headers):
        return self._request("GET", f"/install-orders/{install_id}", headers=headers)

    def list_install_orders(self, headers, params=None):
        return self._request("GET", "/install-orders", headers=headers, params=params)

    def reschedule_install_order(self, install_id, payload, headers):
        return self._request("POST", f"/install-orders/{install_id}/reschedule", payload, headers)

    def complete_install_order(self, install_id, headers, payload=None):
        return self._request("POST", f"/install-orders/{install_id}/complete", payload or {}, headers)

    def cancel_install_order(self, install_id, headers):
        return self._request("POST", f"/install-orders/{install_id}/cancel", {}, headers)

    # ---- Device ----
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def assign_device(self, device_id, payload, headers):
        return self._request("POST", f"/devices/{device_id}/assign", payload, headers)

    def return_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/return", {}, headers)

    # ---- OutageEvent ----
    def report_outage(self, payload, headers):
        return self._request("POST", "/outages", payload, headers)

    def get_outage(self, outage_id, headers):
        return self._request("GET", f"/outages/{outage_id}", headers=headers)

    def list_outages(self, headers, params=None):
        return self._request("GET", "/outages", headers=headers, params=params)

    def resolve_outage(self, outage_id, payload, headers):
        return self._request("POST", f"/outages/{outage_id}/resolve", payload, headers)

    # ---- SlaCredit ----
    def get_sla_credit(self, credit_id, headers):
        return self._request("GET", f"/sla-credits/{credit_id}", headers=headers)

    def list_sla_credits(self, headers, params=None):
        return self._request("GET", "/sla-credits", headers=headers, params=params)

    # ---- GrantClaim ----
    def get_grant_claim(self, claim_id, headers):
        return self._request("GET", f"/grant-claims/{claim_id}", headers=headers)

    def submit_grant_claim(self, claim_id, headers):
        return self._request("POST", f"/grant-claims/{claim_id}/submit", {}, headers)

    def approve_grant_claim(self, claim_id, headers):
        return self._request("POST", f"/grant-claims/{claim_id}/approve", {}, headers)

    def reject_grant_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/grant-claims/{claim_id}/reject", payload or {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
