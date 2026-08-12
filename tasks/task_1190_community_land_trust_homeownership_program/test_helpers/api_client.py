"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- CLTProgram ----
    def create_program(self, payload: dict, headers: dict):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers: dict, params: dict | None = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: dict):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def update_program(self, program_id: str, payload: dict, headers: dict):
        return self._request("PUT", f"/programs/{program_id}", payload, headers)

    def suspend_program(self, program_id: str, headers: dict):
        return self._request("POST", f"/programs/{program_id}/suspend", {}, headers)

    def reinstate_program(self, program_id: str, headers: dict):
        return self._request("POST", f"/programs/{program_id}/reinstate", {}, headers)

    def close_program(self, program_id: str, headers: dict):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    # ---- Household ----
    def create_household(self, program_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/programs/{program_id}/households", payload, headers)

    def list_households(self, program_id: str, headers: dict, params: dict | None = None):
        return self._request("GET", f"/programs/{program_id}/households", headers=headers, params=params)

    def get_household(self, program_id: str, household_id: str, headers: dict):
        return self._request(
            "GET", f"/programs/{program_id}/households/{household_id}", headers=headers
        )

    def suspend_household(self, program_id: str, household_id: str, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/households/{household_id}/suspend", {}, headers
        )

    def reinstate_household(self, program_id: str, household_id: str, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/households/{household_id}/reinstate", {}, headers
        )

    # ---- IncomeCertification ----
    def create_income_certification(self, program_id: str, household_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/households/{household_id}/income-certifications",
            payload,
            headers,
        )

    def list_income_certifications(self, program_id: str, household_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/households/{household_id}/income-certifications",
            headers=headers,
            params=params,
        )

    def get_income_certification(self, program_id: str, household_id: str, cert_id: str, headers: dict):
        return self._request(
            "GET",
            f"/programs/{program_id}/households/{household_id}/income-certifications/{cert_id}",
            headers=headers,
        )

    def start_review_income_certification(self, program_id: str, household_id: str, cert_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/households/{household_id}/income-certifications/{cert_id}/start-review",
            {},
            headers,
        )

    def approve_income_certification(self, program_id: str, household_id: str, cert_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/households/{household_id}/income-certifications/{cert_id}/approve",
            {},
            headers,
        )

    def reject_income_certification(self, program_id: str, household_id: str, cert_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/households/{household_id}/income-certifications/{cert_id}/reject",
            payload,
            headers,
        )

    # ---- EducationCourse ----
    def create_education_course(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/education-courses", payload, headers
        )

    def list_education_courses(self, program_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET", f"/programs/{program_id}/education-courses", headers=headers, params=params
        )

    def get_education_course(self, program_id: str, course_id: str, headers: dict):
        return self._request(
            "GET", f"/programs/{program_id}/education-courses/{course_id}", headers=headers
        )

    def retire_education_course(self, program_id: str, course_id: str, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/education-courses/{course_id}/retire", {}, headers
        )

    # ---- EducationCompletion ----
    def create_education_completion(self, program_id: str, household_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/households/{household_id}/education-completions",
            payload,
            headers,
        )

    def list_education_completions(self, program_id: str, household_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/households/{household_id}/education-completions",
            headers=headers,
            params=params,
        )

    # ---- Unit ----
    def create_unit(self, program_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/programs/{program_id}/units", payload, headers)

    def list_units(self, program_id: str, headers: dict, params: dict | None = None):
        return self._request("GET", f"/programs/{program_id}/units", headers=headers, params=params)

    def get_unit(self, program_id: str, unit_id: str, headers: dict):
        return self._request("GET", f"/programs/{program_id}/units/{unit_id}", headers=headers)

    # ---- GroundLease ----
    def create_lease(self, program_id: str, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/units/{unit_id}/leases", payload, headers
        )

    def list_leases(self, program_id: str, unit_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET", f"/programs/{program_id}/units/{unit_id}/leases", headers=headers, params=params
        )

    def get_lease(self, program_id: str, unit_id: str, lease_id: str, headers: dict):
        return self._request(
            "GET", f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}", headers=headers
        )

    def activate_lease(self, program_id: str, unit_id: str, lease_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/activate",
            payload,
            headers,
        )

    def terminate_lease(self, program_id: str, unit_id: str, lease_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/terminate",
            payload,
            headers,
        )

    def foreclose_lease(self, program_id: str, unit_id: str, lease_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/foreclose",
            payload,
            headers,
        )

    # ---- LeaseFee ----
    def list_fees(self, program_id: str, unit_id: str, lease_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/fees",
            headers=headers,
            params=params,
        )

    def get_fee(self, program_id: str, unit_id: str, lease_id: str, fee_id: str, headers: dict):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/fees/{fee_id}",
            headers=headers,
        )

    def pay_fee(self, program_id: str, unit_id: str, lease_id: str, fee_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/fees/{fee_id}/pay",
            payload,
            headers,
        )

    def waive_fee(self, program_id: str, unit_id: str, lease_id: str, fee_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/fees/{fee_id}/waive",
            {},
            headers,
        )

    # ---- DefaultNotice ----
    def create_default_notice(self, program_id: str, unit_id: str, lease_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/default-notices",
            payload,
            headers,
        )

    def list_default_notices(self, program_id: str, unit_id: str, lease_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/default-notices",
            headers=headers,
            params=params,
        )

    def get_default_notice(self, program_id: str, unit_id: str, lease_id: str, notice_id: str, headers: dict):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/default-notices/{notice_id}",
            headers=headers,
        )

    def cure_default_notice(self, program_id: str, unit_id: str, lease_id: str, notice_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/default-notices/{notice_id}/cure",
            payload,
            headers,
        )

    def escalate_default_notice(self, program_id: str, unit_id: str, lease_id: str, notice_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/default-notices/{notice_id}/escalate",
            {},
            headers,
        )

    def dismiss_default_notice(self, program_id: str, unit_id: str, lease_id: str, notice_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/default-notices/{notice_id}/dismiss",
            {},
            headers,
        )

    # ---- InspectionRecord ----
    def create_inspection(self, program_id: str, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/units/{unit_id}/inspections", payload, headers
        )

    def list_inspections(self, program_id: str, unit_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET", f"/programs/{program_id}/units/{unit_id}/inspections", headers=headers, params=params
        )

    def get_inspection(self, program_id: str, unit_id: str, inspection_id: str, headers: dict):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/inspections/{inspection_id}",
            headers=headers,
        )

    def record_inspection_result(self, program_id: str, unit_id: str, inspection_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    # ---- WaitlistEntry ----
    def create_waitlist_entry(self, program_id: str, household_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/households/{household_id}/waitlist-entries",
            payload,
            headers,
        )

    def list_waitlist_entries_program(self, program_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET", f"/programs/{program_id}/waitlist-entries", headers=headers, params=params
        )

    def list_waitlist_entries_household(self, program_id: str, household_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/households/{household_id}/waitlist-entries",
            headers=headers,
            params=params,
        )

    def get_waitlist_entry(self, program_id: str, entry_id: str, headers: dict):
        return self._request(
            "GET", f"/programs/{program_id}/waitlist-entries/{entry_id}", headers=headers
        )

    def withdraw_waitlist_entry(self, program_id: str, entry_id: str, headers: dict):
        return self._request(
            "POST", f"/programs/{program_id}/waitlist-entries/{entry_id}/withdraw", {}, headers
        )

    # ---- ResaleListing ----
    def create_resale_listing(self, program_id: str, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/resale-listings",
            payload,
            headers,
        )

    def list_resale_listings(self, program_id: str, unit_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/resale-listings",
            headers=headers,
            params=params,
        )

    def get_resale_listing(self, program_id: str, unit_id: str, listing_id: str, headers: dict):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/resale-listings/{listing_id}",
            headers=headers,
        )

    def run_matching(self, program_id: str, unit_id: str, listing_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/resale-listings/{listing_id}/run-matching",
            payload,
            headers,
        )

    def open_contract(self, program_id: str, unit_id: str, listing_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/resale-listings/{listing_id}/open-contract",
            payload,
            headers,
        )

    def close_resale_listing(self, program_id: str, unit_id: str, listing_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/resale-listings/{listing_id}/close",
            payload,
            headers,
        )

    def cancel_resale_listing(self, program_id: str, unit_id: str, listing_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/resale-listings/{listing_id}/cancel",
            {},
            headers,
        )

    # ---- RefinanceRequest ----
    def create_refinance_request(self, program_id: str, unit_id: str, lease_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests",
            payload,
            headers,
        )

    def list_refinance_requests(self, program_id: str, unit_id: str, lease_id: str, headers: dict, params: dict | None = None):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests",
            headers=headers,
            params=params,
        )

    def get_refinance_request(self, program_id: str, unit_id: str, lease_id: str, refi_id: str, headers: dict):
        return self._request(
            "GET",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests/{refi_id}",
            headers=headers,
        )

    def submit_refi_to_lender(self, program_id: str, unit_id: str, lease_id: str, refi_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests/{refi_id}/submit-to-lender",
            {},
            headers,
        )

    def approve_refinance(self, program_id: str, unit_id: str, lease_id: str, refi_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests/{refi_id}/approve",
            {},
            headers,
        )

    def reject_refinance(self, program_id: str, unit_id: str, lease_id: str, refi_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests/{refi_id}/reject",
            payload,
            headers,
        )

    def withdraw_refinance(self, program_id: str, unit_id: str, lease_id: str, refi_id: str, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests/{refi_id}/withdraw",
            {},
            headers,
        )

    def record_refinance(self, program_id: str, unit_id: str, lease_id: str, refi_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/programs/{program_id}/units/{unit_id}/leases/{lease_id}/refinance-requests/{refi_id}/record",
            payload,
            headers,
        )


api_client = ApiClient()
