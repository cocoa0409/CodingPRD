"""API client: one method per endpoint defined in the PRD (§4 endpoint table
plus the logical-clock control of PRD §2.4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Households ---
    def create_household(self, payload, headers):
        return self._request("POST", "/assistance/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/assistance/households/{household_id}", headers=headers)

    def get_benefit_summary(self, household_id, headers):
        return self._request("GET", f"/assistance/households/{household_id}/benefit-summary", headers=headers)

    # --- Eligibility policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/assistance/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/assistance/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/assistance/policies", headers=headers, params=params)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/assistance/policies/{policy_id}/activate", {}, headers)

    # --- Vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/assistance/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/assistance/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/assistance/vendors/{vendor_id}/suspend", {}, headers)

    def reactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/assistance/vendors/{vendor_id}/reactivate", {}, headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/assistance/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/assistance/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/assistance/applications", headers=headers, params=params)

    def attach_document(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/documents", payload, headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/submit", {}, headers)

    def create_verification(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/verifications", payload, headers)

    def create_duplication_check(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/duplication-checks", payload, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/approve", {}, headers)

    def deny_application(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/deny", payload, headers)

    def waitlist_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/waitlist", {}, headers)

    def appeal_application(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/appeal", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/withdraw", {}, headers)

    def close_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/close", {}, headers)

    def create_case_note(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/case-notes", payload, headers)

    # --- Documents ---
    def get_document(self, document_id, headers):
        return self._request("GET", f"/assistance/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/assistance/documents", headers=headers, params=params)

    # --- Verifications ---
    def get_verification(self, verification_id, headers):
        return self._request("GET", f"/assistance/verifications/{verification_id}", headers=headers)

    def list_verifications(self, headers, params=None):
        return self._request("GET", "/assistance/verifications", headers=headers, params=params)

    def complete_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/assistance/verifications/{verification_id}/complete", payload, headers)

    # --- Duplication checks ---
    def get_duplication_check(self, check_id, headers):
        return self._request("GET", f"/assistance/duplication-checks/{check_id}", headers=headers)

    def list_duplication_checks(self, headers, params=None):
        return self._request("GET", "/assistance/duplication-checks", headers=headers, params=params)

    def resolve_duplication_check(self, check_id, payload, headers):
        return self._request("POST", f"/assistance/duplication-checks/{check_id}/resolve", payload, headers)

    def override_duplication_check(self, check_id, payload, headers):
        return self._request("POST", f"/assistance/duplication-checks/{check_id}/override", payload, headers)

    # --- Case notes ---
    def get_case_note(self, note_id, headers):
        return self._request("GET", f"/assistance/case-notes/{note_id}", headers=headers)

    def list_case_notes(self, headers, params=None):
        return self._request("GET", "/assistance/case-notes", headers=headers, params=params)

    # --- Awards ---
    def get_award(self, award_id, headers):
        return self._request("GET", f"/assistance/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/assistance/awards", headers=headers, params=params)

    def adjust_award(self, award_id, payload, headers):
        return self._request("POST", f"/assistance/awards/{award_id}/adjust", payload, headers)

    def void_award(self, award_id, headers):
        return self._request("POST", f"/assistance/awards/{award_id}/void", {}, headers)

    def create_payment(self, award_id, payload, headers):
        return self._request("POST", f"/assistance/awards/{award_id}/payments", payload, headers)

    # --- Allocations ---
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/assistance/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/assistance/allocations", headers=headers, params=params)

    # --- Funding sources ---
    def create_funding_source(self, payload, headers):
        return self._request("POST", "/assistance/funding-sources", payload, headers)

    def get_funding_source(self, source_id, headers):
        return self._request("GET", f"/assistance/funding-sources/{source_id}", headers=headers)

    def list_funding_sources(self, headers, params=None):
        return self._request("GET", "/assistance/funding-sources", headers=headers, params=params)

    def deposit_funding_source(self, source_id, payload, headers):
        return self._request("POST", f"/assistance/funding-sources/{source_id}/deposits", payload, headers)

    def close_funding_source(self, source_id, headers):
        return self._request("POST", f"/assistance/funding-sources/{source_id}/close", {}, headers)

    def get_funding_source_report(self, source_id, headers):
        return self._request("GET", f"/assistance/funding-sources/{source_id}/report", headers=headers)

    # --- Payments ---
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/assistance/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/assistance/payments", headers=headers, params=params)

    def clear_payment(self, payment_id, headers):
        return self._request("POST", f"/assistance/payments/{payment_id}/clear", {}, headers)

    def fail_payment(self, payment_id, headers):
        return self._request("POST", f"/assistance/payments/{payment_id}/fail", {}, headers)

    def reissue_payment(self, payment_id, headers):
        return self._request("POST", f"/assistance/payments/{payment_id}/reissue", {}, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/assistance/payments/{payment_id}/void", {}, headers)

    # --- Replenishment runs ---
    def create_replenishment_run(self, headers):
        return self._request("POST", "/assistance/replenishment-runs", {}, headers)

    def get_replenishment_run(self, run_id, headers):
        return self._request("GET", f"/assistance/replenishment-runs/{run_id}", headers=headers)


api_client = ApiClient()
