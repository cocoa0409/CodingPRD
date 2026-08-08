"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/palliative/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request(
            "GET", f"/palliative/patients/{patient_id}", headers=headers
        )

    def create_capacity_determination(self, patient_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/patients/{patient_id}/capacity-determinations",
            payload,
            headers,
        )

    def create_death_event(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/palliative/patients/{patient_id}/death-events", payload, headers
        )

    def list_patient_referrals(self, patient_id, headers, params=None):
        return self._request(
            "GET",
            f"/palliative/patients/{patient_id}/referrals",
            headers=headers,
            params=params,
        )

    def list_patient_surrogates(self, patient_id, headers, params=None):
        return self._request(
            "GET",
            f"/palliative/patients/{patient_id}/surrogates",
            headers=headers,
            params=params,
        )

    def list_patient_medication_orders(self, patient_id, headers, params=None):
        return self._request(
            "GET",
            f"/palliative/patients/{patient_id}/medication-orders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/palliative/referrals", payload, headers)

    def decide_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/palliative/referrals/{referral_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Surrogate designations
    # ------------------------------------------------------------------
    def create_surrogate(self, payload, headers):
        return self._request("POST", "/palliative/surrogates", payload, headers)

    def set_surrogate_status(self, surrogate_id, payload, headers):
        return self._request(
            "POST", f"/palliative/surrogates/{surrogate_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Advance care documents
    # ------------------------------------------------------------------
    def create_document(self, payload, headers):
        return self._request(
            "POST", "/palliative/advance-care-documents", payload, headers
        )

    def add_document_signature(self, document_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/advance-care-documents/{document_id}/signatures",
            payload,
            headers,
        )

    def execute_document(self, document_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/advance-care-documents/{document_id}/execute",
            payload,
            headers,
        )

    def revoke_document(self, document_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/advance-care-documents/{document_id}/revoke",
            payload,
            headers,
        )

    def get_document(self, document_id, headers):
        return self._request(
            "GET", f"/palliative/advance-care-documents/{document_id}", headers=headers
        )

    def list_documents(self, headers, params=None):
        return self._request(
            "GET", "/palliative/advance-care-documents", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Code-status orders
    # ------------------------------------------------------------------
    def create_code_status_order(self, payload, headers):
        return self._request(
            "POST", "/palliative/code-status-orders", payload, headers
        )

    def attest_code_status_order(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/code-status-orders/{order_id}/attestations",
            payload,
            headers,
        )

    def get_code_status_order(self, order_id, headers):
        return self._request(
            "GET", f"/palliative/code-status-orders/{order_id}", headers=headers
        )

    def list_code_status_orders(self, headers, params=None):
        return self._request(
            "GET", "/palliative/code-status-orders", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Care plans
    # ------------------------------------------------------------------
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/palliative/care-plans", payload, headers)

    def activate_care_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/palliative/care-plans/{plan_id}/activate", payload, headers
        )

    def revise_care_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/palliative/care-plans/{plan_id}/revisions", payload, headers
        )

    def get_care_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/palliative/care-plans/{plan_id}", headers=headers
        )

    def list_care_plans(self, headers, params=None):
        return self._request(
            "GET", "/palliative/care-plans", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Symptom assessments
    # ------------------------------------------------------------------
    def create_symptom_assessment(self, payload, headers):
        return self._request(
            "POST", "/palliative/symptom-assessments", payload, headers
        )

    def update_symptom_triage(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/symptom-assessments/{assessment_id}/triage-update",
            payload,
            headers,
        )

    def get_symptom_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/palliative/symptom-assessments/{assessment_id}", headers=headers
        )

    def list_symptom_assessments(self, headers, params=None):
        return self._request(
            "GET", "/palliative/symptom-assessments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Care conferences
    # ------------------------------------------------------------------
    def create_conference(self, payload, headers):
        return self._request("POST", "/palliative/conferences", payload, headers)

    def hold_conference(self, conference_id, payload, headers):
        return self._request(
            "POST", f"/palliative/conferences/{conference_id}/hold", payload, headers
        )

    def attest_conference(self, conference_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/conferences/{conference_id}/attestations",
            payload,
            headers,
        )

    def get_conference(self, conference_id, headers):
        return self._request(
            "GET", f"/palliative/conferences/{conference_id}", headers=headers
        )

    def list_conferences(self, headers, params=None):
        return self._request(
            "GET", "/palliative/conferences", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Medication orders
    # ------------------------------------------------------------------
    def create_medication_order(self, payload, headers):
        return self._request(
            "POST", "/palliative/medication-orders", payload, headers
        )

    def attest_medication_order(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/medication-orders/{order_id}/attestations",
            payload,
            headers,
        )

    def refill_medication_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/palliative/medication-orders/{order_id}/refills", payload, headers
        )

    def discontinue_medication_order(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/medication-orders/{order_id}/discontinue",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Equipment
    # ------------------------------------------------------------------
    def create_dme_inventory(self, payload, headers):
        return self._request("POST", "/palliative/dme-inventory", payload, headers)

    def get_dme_inventory(self, inventory_id, headers):
        return self._request(
            "GET", f"/palliative/dme-inventory/{inventory_id}", headers=headers
        )

    def create_dme_order(self, payload, headers):
        return self._request("POST", "/palliative/dme-orders", payload, headers)

    def authorize_dme_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/palliative/dme-orders/{order_id}/authorize", payload, headers
        )

    def fulfill_dme_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/palliative/dme-orders/{order_id}/fulfillment", payload, headers
        )

    def close_dme_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/palliative/dme-orders/{order_id}/close", payload, headers
        )

    def get_dme_order(self, order_id, headers):
        return self._request(
            "GET", f"/palliative/dme-orders/{order_id}", headers=headers
        )

    def list_dme_orders(self, headers, params=None):
        return self._request(
            "GET", "/palliative/dme-orders", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Hospice elections
    # ------------------------------------------------------------------
    def create_hospice_election(self, payload, headers):
        return self._request(
            "POST", "/palliative/hospice-elections", payload, headers
        )

    def certify_hospice_election(self, election_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/hospice-elections/{election_id}/certifications",
            payload,
            headers,
        )

    def open_hospice_period(self, election_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/hospice-elections/{election_id}/periods",
            payload,
            headers,
        )

    def revoke_hospice_election(self, election_id, payload, headers):
        return self._request(
            "POST",
            f"/palliative/hospice-elections/{election_id}/revoke",
            payload,
            headers,
        )

    def get_hospice_election(self, election_id, headers):
        return self._request(
            "GET", f"/palliative/hospice-elections/{election_id}", headers=headers
        )

    def list_hospice_elections(self, headers, params=None):
        return self._request(
            "GET", "/palliative/hospice-elections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # On-call escalations
    # ------------------------------------------------------------------
    def create_escalation(self, payload, headers):
        return self._request("POST", "/palliative/escalations", payload, headers)

    def promote_escalation(self, escalation_id, payload, headers):
        return self._request(
            "POST", f"/palliative/escalations/{escalation_id}/promote", payload, headers
        )

    def respond_escalation(self, escalation_id, payload, headers):
        return self._request(
            "POST", f"/palliative/escalations/{escalation_id}/response", payload, headers
        )

    def get_escalation(self, escalation_id, headers):
        return self._request(
            "GET", f"/palliative/escalations/{escalation_id}", headers=headers
        )

    def list_escalations(self, headers, params=None):
        return self._request(
            "GET", "/palliative/escalations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Advance-care-planning claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/palliative/claims", payload, headers)

    def attest_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/palliative/claims/{claim_id}/attest", payload, headers
        )

    def submit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/palliative/claims/{claim_id}/submit", payload, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/palliative/claims/{claim_id}/adjudicate", payload, headers
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/palliative/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request(
            "GET", "/palliative/claims", headers=headers, params=params
        )


api_client = ApiClient()
