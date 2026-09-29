"""HTTP client for the Single-Family Rental Portfolio Operations API.

One method per endpoint in the PRD endpoint table (SS4).  Every method returns the raw
``requests.Response`` so that tests can assert on HTTP status codes as well as bodies.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, total wrapper over the sixty-eight documented endpoints."""

    # --- logical clock (PRD SS2.4) ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # --- markets ----------------------------------------------------------------------
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", "/markets/{}".format(market_id), headers=headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/markets", headers=headers, params=params)

    # --- scope templates --------------------------------------------------------------
    def create_scope_template(self, payload, headers):
        return self._request("POST", "/scope-templates", payload, headers)

    def get_scope_template(self, scope_template_id, headers):
        return self._request(
            "GET", "/scope-templates/{}".format(scope_template_id), headers=headers
        )

    def list_scope_templates(self, headers, params=None):
        return self._request("GET", "/scope-templates", headers=headers, params=params)

    # --- homes ------------------------------------------------------------------------
    def create_home(self, payload, headers):
        return self._request("POST", "/homes", payload, headers)

    def get_home(self, home_id, headers):
        return self._request("GET", "/homes/{}".format(home_id), headers=headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/homes", headers=headers, params=params)

    def patch_home(self, home_id, payload, headers):
        return self._request("PATCH", "/homes/{}".format(home_id), payload, headers)

    def get_leasing_posture(self, home_id, headers):
        return self._request(
            "GET", "/homes/{}/leasing-posture".format(home_id), headers=headers
        )

    def disposition_decision(self, home_id, payload, headers):
        return self._request(
            "POST", "/homes/{}/disposition-decision".format(home_id), payload, headers
        )

    # --- underwriting cases -----------------------------------------------------------
    def create_underwriting_case(self, payload, headers):
        return self._request("POST", "/underwriting-cases", payload, headers)

    def get_underwriting_case(self, case_id, headers):
        return self._request(
            "GET", "/underwriting-cases/{}".format(case_id), headers=headers
        )

    def list_underwriting_cases(self, headers, params=None):
        return self._request(
            "GET", "/underwriting-cases", headers=headers, params=params
        )

    def submit_underwriting_case(self, case_id, payload, headers):
        return self._request(
            "POST", "/underwriting-cases/{}/submit".format(case_id), payload, headers
        )

    def decide_underwriting_case(self, case_id, payload, headers):
        return self._request(
            "POST", "/underwriting-cases/{}/decision".format(case_id), payload, headers
        )

    def revise_underwriting_case(self, case_id, payload, headers):
        return self._request(
            "POST", "/underwriting-cases/{}/revise".format(case_id), payload, headers
        )

    # --- vendors ----------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", "/vendors/{}".format(vendor_id), headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def patch_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", "/vendors/{}".format(vendor_id), payload, headers)

    def set_vendor_status(self, vendor_id, payload, headers):
        return self._request(
            "POST", "/vendors/{}/status".format(vendor_id), payload, headers
        )

    # --- vendor certifications --------------------------------------------------------
    def create_vendor_certification(self, payload, headers):
        return self._request("POST", "/vendor-certifications", payload, headers)

    def get_vendor_certification(self, certification_id, headers):
        return self._request(
            "GET", "/vendor-certifications/{}".format(certification_id), headers=headers
        )

    def list_vendor_certifications(self, headers, params=None):
        return self._request(
            "GET", "/vendor-certifications", headers=headers, params=params
        )

    def revoke_vendor_certification(self, certification_id, payload, headers):
        return self._request(
            "POST",
            "/vendor-certifications/{}/revoke".format(certification_id),
            payload,
            headers,
        )

    # --- renovation projects ----------------------------------------------------------
    def create_renovation_project(self, payload, headers):
        return self._request("POST", "/renovation-projects", payload, headers)

    def get_renovation_project(self, project_id, headers):
        return self._request(
            "GET", "/renovation-projects/{}".format(project_id), headers=headers
        )

    def list_renovation_projects(self, headers, params=None):
        return self._request(
            "GET", "/renovation-projects", headers=headers, params=params
        )

    def set_project_budget(self, project_id, payload, headers):
        return self._request(
            "POST", "/renovation-projects/{}/budget".format(project_id), payload, headers
        )

    def lock_project_scope(self, project_id, payload, headers):
        return self._request(
            "POST",
            "/renovation-projects/{}/lock-scope".format(project_id),
            payload,
            headers,
        )

    def get_benchmark_summary(self, project_id, headers):
        return self._request(
            "GET",
            "/renovation-projects/{}/benchmark-summary".format(project_id),
            headers=headers,
        )

    # --- work orders ------------------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", "/work-orders/{}".format(work_order_id), headers=headers
        )

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_vendor_ranking(self, work_order_id, headers):
        return self._request(
            "GET",
            "/work-orders/{}/vendor-ranking".format(work_order_id),
            headers=headers,
        )

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", "/work-orders/{}/dispatch".format(work_order_id), payload, headers
        )

    def accept_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", "/work-orders/{}/accept".format(work_order_id), payload, headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", "/work-orders/{}/complete".format(work_order_id), payload, headers
        )

    def void_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", "/work-orders/{}/void".format(work_order_id), payload, headers
        )

    # --- prospects --------------------------------------------------------------------
    def create_prospect(self, payload, headers):
        return self._request("POST", "/prospects", payload, headers)

    def get_prospect(self, prospect_id, headers):
        return self._request(
            "GET", "/prospects/{}".format(prospect_id), headers=headers
        )

    def list_prospects(self, headers, params=None):
        return self._request("GET", "/prospects", headers=headers, params=params)

    def verify_identity(self, prospect_id, payload, headers):
        return self._request(
            "POST",
            "/prospects/{}/identity-verifications".format(prospect_id),
            payload,
            headers,
        )

    # --- showing slots ----------------------------------------------------------------
    def create_showing_slot(self, payload, headers):
        return self._request("POST", "/showing-slots", payload, headers)

    def get_showing_slot(self, slot_id, headers):
        return self._request("GET", "/showing-slots/{}".format(slot_id), headers=headers)

    def list_showing_slots(self, headers, params=None):
        return self._request("GET", "/showing-slots", headers=headers, params=params)

    def book_showing_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", "/showing-slots/{}/book".format(slot_id), payload, headers
        )

    def cancel_showing_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", "/showing-slots/{}/cancel".format(slot_id), payload, headers
        )

    # --- rental applications ----------------------------------------------------------
    def create_rental_application(self, payload, headers):
        return self._request("POST", "/rental-applications", payload, headers)

    def get_rental_application(self, application_id, headers):
        return self._request(
            "GET", "/rental-applications/{}".format(application_id), headers=headers
        )

    def list_rental_applications(self, headers, params=None):
        return self._request(
            "GET", "/rental-applications", headers=headers, params=params
        )

    def screen_rental_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            "/rental-applications/{}/screen".format(application_id),
            payload,
            headers,
        )

    # --- leases -----------------------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", "/leases/{}".format(lease_id), headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def pay_deposit(self, lease_id, payload, headers):
        return self._request(
            "POST", "/leases/{}/deposit-payments".format(lease_id), payload, headers
        )

    def execute_lease(self, lease_id, payload, headers):
        return self._request(
            "POST", "/leases/{}/execute".format(lease_id), payload, headers
        )

    def void_lease(self, lease_id, payload, headers):
        return self._request(
            "POST", "/leases/{}/void".format(lease_id), payload, headers
        )

    # --- compliance obligations -------------------------------------------------------
    def create_compliance_obligation(self, payload, headers):
        return self._request("POST", "/compliance-obligations", payload, headers)

    def get_compliance_obligation(self, obligation_id, headers):
        return self._request(
            "GET", "/compliance-obligations/{}".format(obligation_id), headers=headers
        )

    def list_compliance_obligations(self, headers, params=None):
        return self._request(
            "GET", "/compliance-obligations", headers=headers, params=params
        )

    def plan_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST",
            "/compliance-obligations/{}/plan".format(obligation_id),
            payload,
            headers,
        )

    def submit_obligation_resolution(self, obligation_id, payload, headers):
        return self._request(
            "POST",
            "/compliance-obligations/{}/submit-resolution".format(obligation_id),
            payload,
            headers,
        )

    def review_obligation_resolution(self, obligation_id, payload, headers):
        return self._request(
            "POST",
            "/compliance-obligations/{}/review-resolution".format(obligation_id),
            payload,
            headers,
        )
