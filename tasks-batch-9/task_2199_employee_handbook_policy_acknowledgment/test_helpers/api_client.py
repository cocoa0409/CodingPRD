"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Jurisdictions ---------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # --- Legal reviewers -------------------------------------------------
    def create_legal_reviewer(self, payload, headers):
        return self._request("POST", "/legal-reviewers", payload, headers)

    def list_legal_reviewers(self, headers, params=None):
        return self._request("GET", "/legal-reviewers", headers=headers, params=params)

    def get_legal_reviewer(self, legal_reviewer_id, headers):
        return self._request(
            "GET", f"/legal-reviewers/{legal_reviewer_id}", headers=headers
        )

    # --- Employees -------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def patch_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"/employees/{employee_id}", payload, headers)

    # --- Policy documents ------------------------------------------------
    def create_policy_document(self, payload, headers):
        return self._request("POST", "/policy-documents", payload, headers)

    def list_policy_documents(self, headers, params=None):
        return self._request("GET", "/policy-documents", headers=headers, params=params)

    def get_policy_document(self, policy_document_id, headers):
        return self._request(
            "GET", f"/policy-documents/{policy_document_id}", headers=headers
        )

    # --- Policy versions -------------------------------------------------
    def create_policy_version(self, policy_document_id, payload, headers):
        return self._request(
            "POST", f"/policy-documents/{policy_document_id}/versions", payload, headers
        )

    def list_policy_versions(self, headers, params=None):
        return self._request("GET", "/policy-versions", headers=headers, params=params)

    def get_policy_version(self, policy_version_id, headers):
        return self._request(
            "GET", f"/policy-versions/{policy_version_id}", headers=headers
        )

    def submit_version_for_review(self, policy_version_id, headers):
        return self._request(
            "POST",
            f"/policy-versions/{policy_version_id}/submit-for-review",
            {},
            headers,
        )

    def approve_policy_version(self, policy_version_id, headers):
        return self._request(
            "POST", f"/policy-versions/{policy_version_id}/approve", {}, headers
        )

    def reopen_policy_version(self, policy_version_id, headers):
        return self._request(
            "POST", f"/policy-versions/{policy_version_id}/reopen", {}, headers
        )

    def withdraw_policy_version(self, policy_version_id, headers):
        return self._request(
            "POST", f"/policy-versions/{policy_version_id}/withdraw", {}, headers
        )

    # --- Addenda ---------------------------------------------------------
    def create_addendum(self, policy_version_id, payload, headers):
        return self._request(
            "POST", f"/policy-versions/{policy_version_id}/addenda", payload, headers
        )

    def list_addenda(self, headers, params=None):
        return self._request("GET", "/addenda", headers=headers, params=params)

    def get_addendum(self, addendum_id, headers):
        return self._request("GET", f"/addenda/{addendum_id}", headers=headers)

    def approve_addendum(self, addendum_id, headers):
        return self._request("POST", f"/addenda/{addendum_id}/approve", {}, headers)

    # --- Legal reviews ---------------------------------------------------
    def create_legal_review(self, policy_version_id, payload, headers):
        return self._request(
            "POST",
            f"/policy-versions/{policy_version_id}/legal-reviews",
            payload,
            headers,
        )

    def list_legal_reviews(self, headers, params=None):
        return self._request("GET", "/legal-reviews", headers=headers, params=params)

    def get_legal_review(self, legal_review_id, headers):
        return self._request(
            "GET", f"/legal-reviews/{legal_review_id}", headers=headers
        )

    def start_legal_review(self, legal_review_id, headers):
        return self._request(
            "POST", f"/legal-reviews/{legal_review_id}/start", {}, headers
        )

    def decide_legal_review(self, legal_review_id, payload, headers):
        return self._request(
            "POST", f"/legal-reviews/{legal_review_id}/decision", payload, headers
        )

    def re_request_legal_review(self, legal_review_id, payload, headers):
        return self._request(
            "POST", f"/legal-reviews/{legal_review_id}/re-request", payload, headers
        )

    # --- Translations ----------------------------------------------------
    def create_translation(self, policy_version_id, payload, headers):
        return self._request(
            "POST",
            f"/policy-versions/{policy_version_id}/translations",
            payload,
            headers,
        )

    def list_translations(self, headers, params=None):
        return self._request("GET", "/translations", headers=headers, params=params)

    def get_translation(self, translation_id, headers):
        return self._request("GET", f"/translations/{translation_id}", headers=headers)

    def start_translation(self, translation_id, headers):
        return self._request(
            "POST", f"/translations/{translation_id}/start", {}, headers
        )

    def submit_a11y(self, translation_id, payload, headers):
        return self._request(
            "POST", f"/translations/{translation_id}/submit-a11y", payload, headers
        )

    def rework_translation(self, translation_id, headers):
        return self._request(
            "POST", f"/translations/{translation_id}/rework", {}, headers
        )

    def publish_translation(self, translation_id, headers):
        return self._request(
            "POST", f"/translations/{translation_id}/publish", {}, headers
        )

    def abandon_translation(self, translation_id, headers):
        return self._request(
            "POST", f"/translations/{translation_id}/abandon", {}, headers
        )

    # --- Release packages ------------------------------------------------
    def create_release_package(self, payload, headers):
        return self._request("POST", "/release-packages", payload, headers)

    def list_release_packages(self, headers, params=None):
        return self._request("GET", "/release-packages", headers=headers, params=params)

    def get_release_package(self, release_package_id, headers):
        return self._request(
            "GET", f"/release-packages/{release_package_id}", headers=headers
        )

    def add_release_item(self, release_package_id, payload, headers):
        return self._request(
            "POST", f"/release-packages/{release_package_id}/items", payload, headers
        )

    def list_release_items(self, headers, params=None):
        return self._request("GET", "/release-items", headers=headers, params=params)

    def get_release_item(self, release_item_id, headers):
        return self._request("GET", f"/release-items/{release_item_id}", headers=headers)

    def schedule_release_package(self, release_package_id, headers):
        return self._request(
            "POST", f"/release-packages/{release_package_id}/schedule", {}, headers
        )

    def unschedule_release_package(self, release_package_id, headers):
        return self._request(
            "POST", f"/release-packages/{release_package_id}/unschedule", {}, headers
        )

    def release_release_package(self, release_package_id, payload, headers):
        return self._request(
            "POST", f"/release-packages/{release_package_id}/release", payload, headers
        )

    def cancel_release_package(self, release_package_id, headers):
        return self._request(
            "POST", f"/release-packages/{release_package_id}/cancel", {}, headers
        )

    def get_coverage(self, release_package_id, headers):
        return self._request(
            "GET", f"/release-packages/{release_package_id}/coverage", headers=headers
        )

    # --- Assignments -----------------------------------------------------
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def deliver_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/deliver", {}, headers
        )

    # --- Acknowledgments -------------------------------------------------
    def create_acknowledgment(self, payload, headers):
        return self._request("POST", "/acknowledgments", payload, headers)

    def list_acknowledgments(self, headers, params=None):
        return self._request("GET", "/acknowledgments", headers=headers, params=params)

    def get_acknowledgment(self, acknowledgment_id, headers):
        return self._request(
            "GET", f"/acknowledgments/{acknowledgment_id}", headers=headers
        )

    def revoke_acknowledgment(self, acknowledgment_id, payload, headers):
        return self._request(
            "POST", f"/acknowledgments/{acknowledgment_id}/revoke", payload, headers
        )

    # --- Retention records -----------------------------------------------
    def list_retention_records(self, headers, params=None):
        return self._request(
            "GET", "/retention-records", headers=headers, params=params
        )

    def get_retention_record(self, retention_record_id, headers):
        return self._request(
            "GET", f"/retention-records/{retention_record_id}", headers=headers
        )

    def place_legal_hold(self, retention_record_id, payload, headers):
        return self._request(
            "POST",
            f"/retention-records/{retention_record_id}/legal-hold",
            payload,
            headers,
        )

    # --- Escalations -----------------------------------------------------
    def list_escalations(self, headers, params=None):
        return self._request("GET", "/escalations", headers=headers, params=params)

    def get_escalation(self, escalation_case_id, headers):
        return self._request(
            "GET", f"/escalations/{escalation_case_id}", headers=headers
        )

    def notify_escalation(self, escalation_case_id, headers):
        return self._request(
            "POST", f"/escalations/{escalation_case_id}/notify", {}, headers
        )

    def escalate_hr(self, escalation_case_id, headers):
        return self._request(
            "POST", f"/escalations/{escalation_case_id}/escalate-hr", {}, headers
        )

    def close_escalation(self, escalation_case_id, payload, headers):
        return self._request(
            "POST", f"/escalations/{escalation_case_id}/close", payload, headers
        )

    # --- Policy exceptions -----------------------------------------------
    def create_policy_exception(self, payload, headers):
        return self._request("POST", "/policy-exceptions", payload, headers)

    def list_policy_exceptions(self, headers, params=None):
        return self._request(
            "GET", "/policy-exceptions", headers=headers, params=params
        )

    def get_policy_exception(self, policy_exception_id, headers):
        return self._request(
            "GET", f"/policy-exceptions/{policy_exception_id}", headers=headers
        )

    def manager_decision(self, policy_exception_id, payload, headers):
        return self._request(
            "POST",
            f"/policy-exceptions/{policy_exception_id}/manager-decision",
            payload,
            headers,
        )

    def legal_decision(self, policy_exception_id, payload, headers):
        return self._request(
            "POST",
            f"/policy-exceptions/{policy_exception_id}/legal-decision",
            payload,
            headers,
        )

    def revoke_policy_exception(self, policy_exception_id, payload, headers):
        return self._request(
            "POST",
            f"/policy-exceptions/{policy_exception_id}/revoke",
            payload,
            headers,
        )

    # --- Operator endpoints ----------------------------------------------
    def escalation_sweep(self, headers):
        return self._request("POST", "/_ops/escalation-sweep", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
