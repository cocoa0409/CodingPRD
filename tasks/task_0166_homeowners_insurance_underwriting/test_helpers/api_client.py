"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Underwriter ----
    def create_underwriter(self, payload, headers):
        return self._request("POST", "/underwriters", payload, headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def estimate_replacement_cost(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/estimate-replacement-cost", payload, headers
        )

    # ---- RiskAssessment ----
    def create_risk_assessment(self, payload, headers):
        return self._request("POST", "/risk-assessments", payload, headers)

    def list_risk_assessments(self, headers, params=None):
        return self._request("GET", "/risk-assessments", headers=headers, params=params)

    def get_risk_assessment(self, ra_id, headers):
        return self._request("GET", f"/risk-assessments/{ra_id}", headers=headers)

    # ---- Inspector ----
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/complete", payload, headers
        )

    def reschedule_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/reschedule", payload, headers
        )

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def take_review_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/take-review", {}, headers
        )

    def return_to_queue_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/return-to-queue", {}, headers
        )

    def bind_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/bind", payload, headers
        )

    def decline_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decline", payload, headers
        )

    # ---- Endorsement ----
    def create_endorsement(self, payload, headers):
        return self._request("POST", "/endorsements", payload, headers)

    def list_endorsements(self, headers, params=None):
        return self._request("GET", "/endorsements", headers=headers, params=params)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/endorsements/{endorsement_id}", headers=headers)

    def attach_endorsement(self, endorsement_id, headers):
        return self._request(
            "POST", f"/endorsements/{endorsement_id}/attach", {}, headers
        )

    def remove_endorsement(self, endorsement_id, headers):
        return self._request(
            "POST", f"/endorsements/{endorsement_id}/remove", {}, headers
        )

    # ---- Quote ----
    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    # ---- Policy ----
    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def lapse_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", payload, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)


api_client = ApiClient()
