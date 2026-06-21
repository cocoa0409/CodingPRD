"""API client: one method per endpoint defined in the Pension DB Administration PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- PensionPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def terminate_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/plans/{plan_id}/terminate", payload or {}, headers)

    # ---- Participant ----
    def create_participant(self, payload, headers):
        return self._request("POST", "/plans/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/plans/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/plans/participants", headers=headers, params=params)

    def terminate_participant(self, participant_id, headers, payload=None):
        return self._request(
            "POST", f"/plans/participants/{participant_id}/terminate", payload or {}, headers
        )

    def record_death(self, participant_id, headers, payload=None):
        return self._request(
            "POST", f"/plans/participants/{participant_id}/record-death", payload or {}, headers
        )

    # ---- AnnualCompensation ----
    def create_compensation(self, payload, headers):
        return self._request("POST", "/plans/compensation", payload, headers)

    def list_compensation(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/plans/participants/{participant_id}/compensation", headers=headers, params=params
        )

    # ---- ServiceCreditAdjustment ----
    def create_service_adjustment(self, payload, headers):
        return self._request("POST", "/plans/service-adjustments", payload, headers)

    def list_service_adjustments(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/plans/participants/{participant_id}/service-adjustments",
            headers=headers,
            params=params,
        )

    # ---- PlanYearFiling ----
    def create_filing(self, payload, headers):
        return self._request("POST", "/plans/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/plans/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/plans/filings", headers=headers, params=params)

    def certify_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/plans/filings/{filing_id}/certify", payload, headers)

    # ---- PbgcPremiumFiling ----
    def create_premium(self, payload, headers):
        return self._request("POST", "/plans/premiums", payload, headers)

    def get_premium(self, premium_id, headers):
        return self._request("GET", f"/plans/premiums/{premium_id}", headers=headers)

    def list_premiums(self, headers, params=None):
        return self._request("GET", "/plans/premiums", headers=headers, params=params)

    # ---- BenefitElection ----
    def create_election(self, payload, headers):
        return self._request("POST", "/plans/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/plans/elections/{election_id}", headers=headers)

    def list_participant_elections(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/plans/participants/{participant_id}/elections", headers=headers, params=params
        )

    def submit_election(self, election_id, headers, payload=None):
        return self._request("POST", f"/plans/elections/{election_id}/submit", payload or {}, headers)

    def approve_election(self, election_id, headers, payload=None):
        return self._request("POST", f"/plans/elections/{election_id}/approve", payload or {}, headers)

    def reject_election(self, election_id, headers, payload=None):
        return self._request("POST", f"/plans/elections/{election_id}/reject", payload or {}, headers)

    def reopen_election(self, election_id, headers, payload=None):
        return self._request("POST", f"/plans/elections/{election_id}/reopen", payload or {}, headers)

    def commence_election(self, election_id, headers, payload=None):
        return self._request("POST", f"/plans/elections/{election_id}/commence", payload or {}, headers)

    def create_spousal_consent(self, election_id, payload, headers):
        return self._request(
            "POST", f"/plans/elections/{election_id}/spousal-consent", payload, headers
        )

    def list_spousal_consents(self, election_id, headers, params=None):
        return self._request(
            "GET", f"/plans/elections/{election_id}/spousal-consent", headers=headers, params=params
        )

    # ---- QdroAward ----
    def create_qdro(self, payload, headers):
        return self._request("POST", "/plans/qdros", payload, headers)

    def list_participant_qdros(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/plans/participants/{participant_id}/qdros", headers=headers, params=params
        )

    def submit_qdro(self, qdro_id, headers, payload=None):
        return self._request("POST", f"/plans/qdros/{qdro_id}/submit", payload or {}, headers)

    def qualify_qdro(self, qdro_id, headers, payload=None):
        return self._request("POST", f"/plans/qdros/{qdro_id}/qualify", payload or {}, headers)

    def reject_qdro(self, qdro_id, headers, payload=None):
        return self._request("POST", f"/plans/qdros/{qdro_id}/reject", payload or {}, headers)

    def amend_qdro(self, qdro_id, headers, payload=None):
        return self._request("POST", f"/plans/qdros/{qdro_id}/amend", payload or {}, headers)

    # ---- BenefitPayment ----
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/plans/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/plans/payments", headers=headers, params=params)

    def activate_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/plans/payments/{payment_id}/activate", payload or {}, headers)

    def suspend_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/plans/payments/{payment_id}/suspend", payload or {}, headers)

    def resume_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/plans/payments/{payment_id}/resume", payload or {}, headers)

    def apply_cola(self, payment_id, headers, payload=None):
        return self._request("POST", f"/plans/payments/{payment_id}/apply-cola", payload or {}, headers)


api_client = ApiClient()
