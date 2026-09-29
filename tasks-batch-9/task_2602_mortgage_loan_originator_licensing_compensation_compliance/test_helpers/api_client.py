"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the MLO licensing and compensation compliance API."""

    # ------------------------------------------------------------------
    # Originators
    # ------------------------------------------------------------------
    def create_originator(self, payload, headers):
        return self._request("POST", "/originators", payload, headers)

    def list_originators(self, headers, params=None):
        return self._request("GET", "/originators", headers=headers, params=params)

    def get_originator(self, originator_id, headers):
        return self._request("GET", f"/originators/{originator_id}", headers=headers)

    def update_originator(self, originator_id, payload, headers):
        return self._request("PATCH", f"/originators/{originator_id}", payload, headers)

    def get_originator_authority(self, originator_id, headers, params=None):
        return self._request(
            "GET", f"/originators/{originator_id}/authority", headers=headers, params=params
        )

    def get_originator_ce_compliance(self, originator_id, headers, params=None):
        return self._request(
            "GET", f"/originators/{originator_id}/ce-compliance", headers=headers, params=params
        )

    def assign_compensation_plan(self, originator_id, payload, headers):
        return self._request(
            "POST", f"/originators/{originator_id}/compensation-plan-assignments", payload, headers
        )

    def run_compensation_reconciliation(self, originator_id, headers, payload=None):
        return self._request(
            "POST",
            f"/originators/{originator_id}/compensation-reconciliations",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Licence registrations
    # ------------------------------------------------------------------
    def create_license_registration(self, payload, headers):
        return self._request("POST", "/license-registrations", payload, headers)

    def list_license_registrations(self, headers, params=None):
        return self._request("GET", "/license-registrations", headers=headers, params=params)

    def get_license_registration(self, license_id, headers):
        return self._request("GET", f"/license-registrations/{license_id}", headers=headers)

    def activate_license_registration(self, license_id, headers, payload=None):
        return self._request(
            "POST",
            f"/license-registrations/{license_id}/activations",
            payload if payload is not None else {},
            headers,
        )

    def create_renewal_request(self, license_id, headers, payload=None):
        return self._request(
            "POST",
            f"/license-registrations/{license_id}/renewal-requests",
            payload if payload is not None else {},
            headers,
        )

    def create_renewal_completion(self, license_id, headers, payload=None):
        return self._request(
            "POST",
            f"/license-registrations/{license_id}/renewal-completions",
            payload if payload is not None else {},
            headers,
        )

    def create_license_status_action(self, license_id, payload, headers):
        return self._request(
            "POST", f"/license-registrations/{license_id}/status-actions", payload, headers
        )

    def create_sponsorship_transfer(self, license_id, payload, headers):
        return self._request(
            "POST", f"/license-registrations/{license_id}/sponsorship-transfers", payload, headers
        )

    # ------------------------------------------------------------------
    # Sponsorship transfers
    # ------------------------------------------------------------------
    def list_sponsorship_transfers(self, headers, params=None):
        return self._request("GET", "/sponsorship-transfers", headers=headers, params=params)

    def get_sponsorship_transfer(self, sponsorship_id, headers):
        return self._request("GET", f"/sponsorship-transfers/{sponsorship_id}", headers=headers)

    def relinquish_sponsorship_transfer(self, sponsorship_id, headers, payload=None):
        return self._request(
            "POST",
            f"/sponsorship-transfers/{sponsorship_id}/relinquish",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Continuing education
    # ------------------------------------------------------------------
    def create_ce_course(self, payload, headers):
        return self._request("POST", "/ce-courses", payload, headers)

    def rescind_ce_course(self, course_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ce-courses/{course_id}/rescind",
            payload if payload is not None else {},
            headers,
        )

    def create_ce_credit(self, payload, headers):
        return self._request("POST", "/ce-credits", payload, headers)

    def list_ce_credits(self, headers, params=None):
        return self._request("GET", "/ce-credits", headers=headers, params=params)

    def get_ce_credit(self, credit_id, headers):
        return self._request("GET", f"/ce-credits/{credit_id}", headers=headers)

    def void_ce_credit(self, credit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/ce-credits/{credit_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Compensation plans
    # ------------------------------------------------------------------
    def create_compensation_plan(self, payload, headers):
        return self._request("POST", "/compensation-plans", payload, headers)

    def list_compensation_plans(self, headers, params=None):
        return self._request("GET", "/compensation-plans", headers=headers, params=params)

    def get_compensation_plan(self, plan_id, headers):
        return self._request("GET", f"/compensation-plans/{plan_id}", headers=headers)

    def create_compensation_variable(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/compensation-plans/{plan_id}/variables", payload, headers
        )

    def list_compensation_variables(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/compensation-plans/{plan_id}/variables", headers=headers, params=params
        )

    def create_plan_approval(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/compensation-plans/{plan_id}/approvals", payload, headers
        )

    # ------------------------------------------------------------------
    # Loan applications
    # ------------------------------------------------------------------
    def create_loan_application(self, payload, headers):
        return self._request("POST", "/loan-applications", payload, headers)

    def list_loan_applications(self, headers, params=None):
        return self._request("GET", "/loan-applications", headers=headers, params=params)

    def get_loan_application(self, loan_id, headers):
        return self._request("GET", f"/loan-applications/{loan_id}", headers=headers)

    def lock_loan_application(self, loan_id, payload, headers):
        return self._request("POST", f"/loan-applications/{loan_id}/lock", payload, headers)

    def close_loan_application(self, loan_id, payload, headers):
        return self._request("POST", f"/loan-applications/{loan_id}/close", payload, headers)

    def payoff_loan_application(self, loan_id, payload, headers):
        return self._request("POST", f"/loan-applications/{loan_id}/payoff", payload, headers)

    def withdraw_loan_application(self, loan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loan-applications/{loan_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    def release_loan_compensation(self, loan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loan-applications/{loan_id}/compensation-release",
            payload if payload is not None else {},
            headers,
        )

    def create_pricing_exception(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loan-applications/{loan_id}/pricing-exceptions", payload, headers
        )

    # ------------------------------------------------------------------
    # Pricing exceptions
    # ------------------------------------------------------------------
    def list_pricing_exceptions(self, headers, params=None):
        return self._request("GET", "/pricing-exceptions", headers=headers, params=params)

    def get_pricing_exception(self, exception_id, headers):
        return self._request("GET", f"/pricing-exceptions/{exception_id}", headers=headers)

    def create_pricing_exception_decision(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/pricing-exceptions/{exception_id}/decisions", payload, headers
        )

    def withdraw_pricing_exception(self, exception_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pricing-exceptions/{exception_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Compensation records
    # ------------------------------------------------------------------
    def list_compensation_records(self, headers, params=None):
        return self._request("GET", "/compensation-records", headers=headers, params=params)

    def get_compensation_record(self, record_id, headers):
        return self._request("GET", f"/compensation-records/{record_id}", headers=headers)

    # ------------------------------------------------------------------
    # Advertisements
    # ------------------------------------------------------------------
    def create_advertisement(self, payload, headers):
        return self._request("POST", "/advertisements", payload, headers)

    def list_advertisements(self, headers, params=None):
        return self._request("GET", "/advertisements", headers=headers, params=params)

    def get_advertisement(self, advertisement_id, headers):
        return self._request("GET", f"/advertisements/{advertisement_id}", headers=headers)

    def submit_advertisement(self, advertisement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/advertisements/{advertisement_id}/submissions",
            payload if payload is not None else {},
            headers,
        )

    def create_advertisement_review(self, advertisement_id, payload, headers):
        return self._request(
            "POST", f"/advertisements/{advertisement_id}/reviews", payload, headers
        )

    def revise_advertisement(self, advertisement_id, payload, headers):
        return self._request(
            "POST", f"/advertisements/{advertisement_id}/revisions", payload, headers
        )

    def publish_advertisement(self, advertisement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/advertisements/{advertisement_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_advertisement(self, advertisement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/advertisements/{advertisement_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Examination inquiries
    # ------------------------------------------------------------------
    def create_examination_inquiry(self, payload, headers):
        return self._request("POST", "/examination-inquiries", payload, headers)

    def list_examination_inquiries(self, headers, params=None):
        return self._request("GET", "/examination-inquiries", headers=headers, params=params)

    def get_examination_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/examination-inquiries/{inquiry_id}", headers=headers)

    def create_examination_response(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/examination-inquiries/{inquiry_id}/responses", payload, headers
        )

    def create_examination_info_request(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/examination-inquiries/{inquiry_id}/info-requests", payload, headers
        )

    def close_examination_inquiry(self, inquiry_id, headers, payload=None):
        return self._request(
            "POST",
            f"/examination-inquiries/{inquiry_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Unlicensed-activity investigations
    # ------------------------------------------------------------------
    def create_investigation(self, payload, headers):
        return self._request("POST", "/unlicensed-activity-investigations", payload, headers)

    def list_investigations(self, headers, params=None):
        return self._request(
            "GET", "/unlicensed-activity-investigations", headers=headers, params=params
        )

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"/unlicensed-activity-investigations/{investigation_id}", headers=headers
        )

    def create_investigation_finding(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"/unlicensed-activity-investigations/{investigation_id}/findings",
            payload,
            headers,
        )

    def remediate_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST",
            f"/unlicensed-activity-investigations/{investigation_id}/remediate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Operator surface
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_license_sweep(self, headers, payload=None):
        return self._request(
            "POST",
            "/_ops/daily-license-sweep",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
