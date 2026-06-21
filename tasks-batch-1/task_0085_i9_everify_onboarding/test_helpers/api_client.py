"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Onboardings ---------------------------------------------------
    def create_onboarding(self, payload, headers):
        return self._request("POST", "/onboardings", payload, headers)

    def list_onboardings(self, headers, params=None):
        return self._request("GET", "/onboardings", headers=headers, params=params)

    def get_onboarding(self, onboarding_id, headers):
        return self._request("GET", f"/onboardings/{onboarding_id}", headers=headers)

    def get_onboarding_risk(self, onboarding_id, headers):
        return self._request("GET", f"/onboardings/{onboarding_id}/risk", headers=headers)

    def section1_attest(self, onboarding_id, payload, headers):
        return self._request(
            "POST", f"/onboardings/{onboarding_id}/section1-attest", payload, headers
        )

    def section2_complete(self, onboarding_id, payload, headers):
        return self._request(
            "POST", f"/onboardings/{onboarding_id}/section2-complete", payload, headers
        )

    def finalize_onboarding(self, onboarding_id, payload, headers):
        return self._request(
            "POST", f"/onboardings/{onboarding_id}/finalize", payload, headers
        )

    def override_onboarding(self, onboarding_id, payload, headers):
        return self._request(
            "POST", f"/onboardings/{onboarding_id}/override", payload, headers
        )

    def advance_lifecycle(self, onboarding_id, payload, headers):
        return self._request(
            "POST", f"/onboardings/{onboarding_id}/advance-lifecycle", payload, headers
        )

    # ----- Identity Documents -------------------------------------------
    def create_identity_document(self, payload, headers):
        return self._request("POST", "/identity-documents", payload, headers)

    def list_identity_documents(self, headers, params=None):
        return self._request(
            "GET", "/identity-documents", headers=headers, params=params
        )

    def get_identity_document(self, document_id, headers):
        return self._request(
            "GET", f"/identity-documents/{document_id}", headers=headers
        )

    # ----- I9 Forms ------------------------------------------------------
    def list_i9_forms(self, headers, params=None):
        return self._request("GET", "/i9-forms", headers=headers, params=params)

    def get_i9_form(self, form_id, headers):
        return self._request("GET", f"/i9-forms/{form_id}", headers=headers)

    def list_section3(self, form_id, headers, params=None):
        return self._request(
            "GET", f"/i9-forms/{form_id}/section3", headers=headers, params=params
        )

    def create_section3(self, form_id, payload, headers):
        return self._request(
            "POST", f"/i9-forms/{form_id}/section3", payload, headers
        )

    # ----- Reverification Events ----------------------------------------
    def list_reverification_events(self, headers, params=None):
        return self._request(
            "GET", "/reverification-events", headers=headers, params=params
        )

    def get_reverification_event(self, event_id, headers):
        return self._request(
            "GET", f"/reverification-events/{event_id}", headers=headers
        )

    # ----- E-Verify Cases -----------------------------------------------
    def create_everify_case(self, payload, headers):
        return self._request("POST", "/everify-cases", payload, headers)

    def list_everify_cases(self, headers, params=None):
        return self._request("GET", "/everify-cases", headers=headers, params=params)

    def get_everify_case(self, case_id, headers):
        return self._request("GET", f"/everify-cases/{case_id}", headers=headers)

    def everify_result(self, case_id, payload, headers):
        return self._request(
            "POST", f"/everify-cases/{case_id}/result", payload, headers
        )

    def everify_refer(self, case_id, payload, headers):
        return self._request(
            "POST", f"/everify-cases/{case_id}/refer", payload, headers
        )

    # ----- Work Authorizations ------------------------------------------
    def create_work_authorization(self, payload, headers):
        return self._request("POST", "/work-authorizations", payload, headers)

    def list_work_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/work-authorizations", headers=headers, params=params
        )

    def get_work_authorization(self, auth_id, headers):
        return self._request(
            "GET", f"/work-authorizations/{auth_id}", headers=headers
        )

    # ----- Audit Entries -------------------------------------------------
    def list_audit_entries(self, headers, params=None):
        return self._request("GET", "/audit-entries", headers=headers, params=params)

    def get_audit_entry(self, entry_id, headers):
        return self._request("GET", f"/audit-entries/{entry_id}", headers=headers)

    # ----- Test-driving clock -------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
