"""Typed HTTP client covering every endpoint declared by the PRD.

One method per endpoint row, in the PRD's own order. Every method returns the
raw ``requests.Response`` so that tests can assert on status codes and on the
response envelope themselves.

Reads and lists are issued as GET with the filter/pagination payload carried as
query parameters; every write is a POST with a JSON body.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH

BASE = "/homeownership"


class HomeownershipClient(GenericApiClient):
    """Endpoint-per-method wrapper over the generic runner client."""

    # -- 3.1 Programs and the subsidy pool ---------------------------------
    def create_program(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/programs", payload=payload, headers=headers)

    def list_programs(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/programs", payload=params, headers=headers)

    def get_program(self, program_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/programs/{program_id}", headers=headers)

    def adjust_subsidy_pool(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/subsidy-pool-adjustments", payload=payload, headers=headers
        )

    def promote_waitlist(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/waitlist-promotions", payload=payload, headers=headers
        )

    # -- 3.2 Households ----------------------------------------------------
    def create_household(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/households", payload=payload, headers=headers)

    def list_households(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/households", payload=params, headers=headers)

    def get_household(self, household_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/households/{household_id}", headers=headers)

    def submit_household(
        self, household_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{BASE}/households/{household_id}/submit", payload=payload, headers=headers)

    def screen_household(
        self, household_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{BASE}/households/{household_id}/screen", payload=payload, headers=headers)

    def refer_to_committee(
        self, household_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/households/{household_id}/committee-referral", payload=payload, headers=headers
        )

    def return_to_screening(
        self, household_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/households/{household_id}/return-to-screening", payload=payload, headers=headers
        )

    def record_selection_decision(
        self, household_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/households/{household_id}/selection-decision", payload=payload, headers=headers
        )

    # -- 3.2 Household members --------------------------------------------
    def create_member(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/household-members", payload=payload, headers=headers)

    def list_members(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/household-members", payload=params, headers=headers)

    def get_member(self, member_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/household-members/{member_id}", headers=headers)

    # -- 3.3 Selection reviews --------------------------------------------
    def create_review(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/selection-reviews", payload=payload, headers=headers)

    def list_reviews(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/selection-reviews", payload=params, headers=headers)

    def get_review(self, review_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/selection-reviews/{review_id}", headers=headers)

    def retract_review(
        self, review_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/selection-reviews/{review_id}/retract", payload=payload, headers=headers
        )

    # -- 3.4 Sweat equity entries -----------------------------------------
    def create_entry(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/sweat-equity-entries", payload=payload, headers=headers)

    def list_entries(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/sweat-equity-entries", payload=params, headers=headers)

    def get_entry(self, entry_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/sweat-equity-entries/{entry_id}", headers=headers)

    def verify_entry(self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/sweat-equity-entries/{entry_id}/verification", payload=payload, headers=headers
        )

    def resubmit_entry(self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/sweat-equity-entries/{entry_id}/resubmit", payload=payload, headers=headers
        )

    def credit_entry(
        self, entry_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/sweat-equity-entries/{entry_id}/credit", payload=payload or {}, headers=headers
        )

    def reverse_entry(self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/sweat-equity-entries/{entry_id}/reverse", payload=payload, headers=headers
        )

    # -- 3.6 Build sites and cost capture ---------------------------------
    def create_build_site(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/build-sites", payload=payload, headers=headers)

    def list_build_sites(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/build-sites", payload=params, headers=headers)

    def get_build_site(self, site_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/build-sites/{site_id}", headers=headers)

    def advance_readiness(self, site_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/build-sites/{site_id}/readiness-advance", payload=payload, headers=headers
        )

    def set_safety_posture(self, site_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/build-sites/{site_id}/safety-posture", payload=payload, headers=headers
        )

    def create_cost_entry(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/cost-entries", payload=payload, headers=headers)

    def list_cost_entries(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/cost-entries", payload=params, headers=headers)

    def get_cost_entry(self, cost_entry_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/cost-entries/{cost_entry_id}", headers=headers)

    def void_cost_entry(
        self, cost_entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/cost-entries/{cost_entry_id}/void", payload=payload, headers=headers
        )

    # -- 3.7 Construction shifts ------------------------------------------
    def create_shift(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/construction-shifts", payload=payload, headers=headers)

    def list_shifts(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/construction-shifts", payload=params, headers=headers)

    def get_shift(self, shift_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/construction-shifts/{shift_id}", headers=headers)

    def open_shift(
        self, shift_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/construction-shifts/{shift_id}/open", payload=payload or {}, headers=headers
        )

    def lock_shift(self, shift_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/construction-shifts/{shift_id}/lock", payload=payload, headers=headers
        )

    def complete_shift(
        self, shift_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/construction-shifts/{shift_id}/complete", payload=payload or {}, headers=headers
        )

    def cancel_shift(self, shift_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", f"{BASE}/construction-shifts/{shift_id}/cancel", payload=payload, headers=headers
        )

    # -- 3.7 Volunteers ----------------------------------------------------
    def create_volunteer(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/volunteers", payload=payload, headers=headers)

    def list_volunteers(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/volunteers", payload=params, headers=headers)

    def get_volunteer(self, volunteer_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/volunteers/{volunteer_id}", headers=headers)

    # -- 3.7 Shift assignments --------------------------------------------
    def create_assignment(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/shift-assignments", payload=payload, headers=headers)

    def list_assignments(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/shift-assignments", payload=params, headers=headers)

    def get_assignment(self, assignment_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/shift-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(
        self,
        assignment_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/shift-assignments/{assignment_id}/confirm", payload=payload or {}, headers=headers
        )

    def check_in_assignment(
        self,
        assignment_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"{BASE}/shift-assignments/{assignment_id}/check-in", payload=payload or {}, headers=headers
        )

    def cancel_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/shift-assignments/{assignment_id}/cancel", payload=payload, headers=headers
        )

    # -- 3.5 Education enrollments ----------------------------------------
    def create_enrollment(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/education-enrollments", payload=payload, headers=headers)

    def list_enrollments(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/education-enrollments", payload=params, headers=headers)

    def get_enrollment(self, enrollment_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/education-enrollments/{enrollment_id}", headers=headers)

    def record_module_completion(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/education-enrollments/{enrollment_id}/module-completions",
            payload=payload,
            headers=headers,
        )

    # -- 3.8 Mortgage applications ----------------------------------------
    def create_application(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/mortgage-applications", payload=payload, headers=headers)

    def list_applications(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/mortgage-applications", payload=params, headers=headers)

    def get_application(self, application_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/mortgage-applications/{application_id}", headers=headers)

    def get_structure_preview(self, application_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "GET", f"{BASE}/mortgage-applications/{application_id}/structure-preview", headers=headers
        )

    def submit_underwriting(
        self,
        application_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/mortgage-applications/{application_id}/submit-underwriting",
            payload=payload or {},
            headers=headers,
        )

    def return_application_to_draft(
        self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/mortgage-applications/{application_id}/return-to-draft",
            payload=payload,
            headers=headers,
        )

    def approve_application(
        self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/mortgage-applications/{application_id}/approve", payload=payload, headers=headers
        )

    def deny_application(
        self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/mortgage-applications/{application_id}/deny", payload=payload, headers=headers
        )

    def close_application(
        self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/mortgage-applications/{application_id}/close", payload=payload, headers=headers
        )

    def lien_action(
        self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/mortgage-applications/{application_id}/lien-actions", payload=payload, headers=headers
        )

    # -- 3.9 Grant awards --------------------------------------------------
    def create_grant_award(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{BASE}/grant-awards", payload=payload, headers=headers)

    def list_grant_awards(self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/grant-awards", payload=params, headers=headers)

    def get_grant_award(self, award_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{BASE}/grant-awards/{award_id}", headers=headers)

    def create_impact_report(
        self, award_id: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{BASE}/grant-awards/{award_id}/impact-reports", payload=payload or {}, headers=headers
        )

    # -- 2.5 The logical clock --------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", CLOCK_PATH, payload={"current_utc": current_utc}, headers=headers)
