"""Typed HTTP client covering every endpoint the PRD defines.

Each method is a thin, named wrapper over one route. Nothing here validates a
response: callers pass the raw response to ``validate_success`` /
``validate_error`` / ``validate_paginated`` so that the expected outcome stays
visible in the test body.
"""

from typing import Any, Optional

from prd_bench_local_runner.testing import GenericApiClient

Json = dict[str, Any]
Headers = dict[str, str]


class ApiClient(GenericApiClient):
    """Contractor-licensing API surface."""

    # ------------------------------------------------------------- clock -----
    def set_clock(self, current_utc: str, headers: Headers):
        return self.post(
            "/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers
        )

    # ------------------------------------------- trade classifications ------
    def create_trade_classification(self, payload: Json, headers: Headers):
        return self.post("/licensing/trade-classifications", payload, headers=headers)

    def get_trade_classification(self, classification_id: str, headers: Headers):
        return self.get(
            f"/licensing/trade-classifications/{classification_id}", headers=headers
        )

    # ------------------------------------------ recovery fund accounts ------
    def create_fund_account(self, payload: Json, headers: Headers):
        return self.post("/licensing/recovery-fund-accounts", payload, headers=headers)

    def get_fund_account(self, fund_account_id: str, headers: Headers):
        return self.get(
            f"/licensing/recovery-fund-accounts/{fund_account_id}", headers=headers
        )

    # -------------------------------------------------------- licensees -----
    def create_licensee(self, payload: Json, headers: Headers):
        return self.post("/licensing/licensees", payload, headers=headers)

    def get_licensee(self, licensee_id: str, headers: Headers):
        return self.get(f"/licensing/licensees/{licensee_id}", headers=headers)

    # -------------------------------------------- qualifying individuals ----
    def create_qualifying_individual(self, payload: Json, headers: Headers):
        return self.post("/licensing/qualifying-individuals", payload, headers=headers)

    def get_qualifying_individual(self, individual_id: str, headers: Headers):
        return self.get(
            f"/licensing/qualifying-individuals/{individual_id}", headers=headers
        )

    def create_exam_result(self, individual_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/qualifying-individuals/{individual_id}/exam-results",
            payload,
            headers=headers,
        )

    def list_exam_results(
        self, individual_id: str, headers: Headers, params: Optional[Json] = None
    ):
        return self.get(
            f"/licensing/qualifying-individuals/{individual_id}/exam-results",
            params=params or {},
            headers=headers,
        )

    # -------------------------------------------------------- consumers -----
    def create_consumer(self, payload: Json, headers: Headers):
        return self.post("/licensing/consumers", payload, headers=headers)

    def get_consumer(self, consumer_id: str, headers: Headers):
        return self.get(f"/licensing/consumers/{consumer_id}", headers=headers)

    # ----------------------------------------------------- applications -----
    def create_application(self, payload: Json, headers: Headers):
        return self.post("/licensing/license-applications", payload, headers=headers)

    def get_application(self, application_id: str, headers: Headers):
        return self.get(
            f"/licensing/license-applications/{application_id}", headers=headers
        )

    def list_applications(self, headers: Headers, params: Optional[Json] = None):
        return self.get(
            "/licensing/license-applications", params=params or {}, headers=headers
        )

    def submit_application(self, application_id: str, headers: Headers):
        return self.post(
            f"/licensing/license-applications/{application_id}/submit",
            {},
            headers=headers,
        )

    def cure_application(self, application_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/license-applications/{application_id}/cure",
            payload,
            headers=headers,
        )

    def decide_application(self, application_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/license-applications/{application_id}/decision",
            payload,
            headers=headers,
        )

    def withdraw_application(self, application_id: str, headers: Headers):
        return self.post(
            f"/licensing/license-applications/{application_id}/withdraw",
            {},
            headers=headers,
        )

    # --------------------------------------------------------- licences -----
    def get_license(self, license_id: str, headers: Headers):
        return self.get(f"/licensing/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers: Headers, params: Optional[Json] = None):
        return self.get("/licensing/licenses", params=params or {}, headers=headers)

    def bank_ce_credits(self, license_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/licenses/{license_id}/ce-credits", payload, headers=headers
        )

    def renew_license(self, license_id: str, headers: Headers):
        return self.post(
            f"/licensing/licenses/{license_id}/renew", {}, headers=headers
        )

    def reinstate_license(self, license_id: str, headers: Headers):
        return self.post(
            f"/licensing/licenses/{license_id}/reinstate", {}, headers=headers
        )

    def credit_recovery_repayment(
        self, license_id: str, payload: Json, headers: Headers
    ):
        return self.post(
            f"/licensing/licenses/{license_id}/recovery-repayments",
            payload,
            headers=headers,
        )

    def run_compliance_sweep(self, headers: Headers):
        return self.post("/licensing/compliance-sweeps", {}, headers=headers)

    # -------------------------------------------------- coverage records ----
    def create_coverage_record(self, payload: Json, headers: Headers):
        return self.post("/licensing/coverage-records", payload, headers=headers)

    def get_coverage_record(self, coverage_id: str, headers: Headers):
        return self.get(f"/licensing/coverage-records/{coverage_id}", headers=headers)

    def list_coverage_records(self, headers: Headers, params: Optional[Json] = None):
        return self.get("/licensing/coverage-records", params=params or {}, headers=headers)

    def verify_coverage_record(self, coverage_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/coverage-records/{coverage_id}/verification",
            payload,
            headers=headers,
        )

    def cancel_coverage_record(self, coverage_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/coverage-records/{coverage_id}/cancel", payload, headers=headers
        )

    # --------------------------------------------- qualifier assignments ----
    def create_qualifier_assignment(self, payload: Json, headers: Headers):
        return self.post("/licensing/qualifier-assignments", payload, headers=headers)

    def get_qualifier_assignment(self, assignment_id: str, headers: Headers):
        return self.get(
            f"/licensing/qualifier-assignments/{assignment_id}", headers=headers
        )

    def list_qualifier_assignments(
        self, headers: Headers, params: Optional[Json] = None
    ):
        return self.get(
            "/licensing/qualifier-assignments", params=params or {}, headers=headers
        )

    def withdraw_qualifier_assignment(
        self, assignment_id: str, payload: Json, headers: Headers
    ):
        return self.post(
            f"/licensing/qualifier-assignments/{assignment_id}/withdraw",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------- complaints -----
    def create_complaint(self, payload: Json, headers: Headers):
        return self.post("/licensing/complaints", payload, headers=headers)

    def get_complaint(self, complaint_id: str, headers: Headers):
        return self.get(f"/licensing/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers: Headers, params: Optional[Json] = None):
        return self.get("/licensing/complaints", params=params or {}, headers=headers)

    def screen_complaint(self, complaint_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/complaints/{complaint_id}/screen", payload, headers=headers
        )

    def record_mediation_outcome(
        self, complaint_id: str, payload: Json, headers: Headers
    ):
        return self.post(
            f"/licensing/complaints/{complaint_id}/mediation-outcome",
            payload,
            headers=headers,
        )

    def remand_to_mediation(self, complaint_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/complaints/{complaint_id}/remand-to-mediation",
            payload,
            headers=headers,
        )

    def withdraw_complaint(self, complaint_id: str, headers: Headers):
        return self.post(
            f"/licensing/complaints/{complaint_id}/withdraw", {}, headers=headers
        )

    # ---------------------------------------------------- investigations ----
    def create_investigation(self, payload: Json, headers: Headers):
        return self.post("/licensing/investigations", payload, headers=headers)

    def get_investigation(self, investigation_id: str, headers: Headers):
        return self.get(f"/licensing/investigations/{investigation_id}", headers=headers)

    def list_investigations(self, headers: Headers, params: Optional[Json] = None):
        return self.get("/licensing/investigations", params=params or {}, headers=headers)

    def close_investigation(
        self, investigation_id: str, payload: Json, headers: Headers
    ):
        return self.post(
            f"/licensing/investigations/{investigation_id}/close",
            payload,
            headers=headers,
        )

    # --------------------------------------------------------- citations ----
    def create_citation(self, payload: Json, headers: Headers):
        return self.post("/licensing/citations", payload, headers=headers)

    def get_citation(self, citation_id: str, headers: Headers):
        return self.get(f"/licensing/citations/{citation_id}", headers=headers)

    def list_citations(self, headers: Headers, params: Optional[Json] = None):
        return self.get("/licensing/citations", params=params or {}, headers=headers)

    def appeal_citation(self, citation_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/citations/{citation_id}/appeal", payload, headers=headers
        )

    def finalize_citation(self, citation_id: str, headers: Headers):
        return self.post(
            f"/licensing/citations/{citation_id}/finalize", {}, headers=headers
        )

    def comply_with_citation(self, citation_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/citations/{citation_id}/comply", payload, headers=headers
        )

    # ---------------------------------------------------------- hearings ----
    def create_hearing(self, payload: Json, headers: Headers):
        return self.post("/licensing/disciplinary-hearings", payload, headers=headers)

    def get_hearing(self, hearing_id: str, headers: Headers):
        return self.get(
            f"/licensing/disciplinary-hearings/{hearing_id}", headers=headers
        )

    def list_hearings(self, headers: Headers, params: Optional[Json] = None):
        return self.get(
            "/licensing/disciplinary-hearings", params=params or {}, headers=headers
        )

    def decide_hearing(self, hearing_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/disciplinary-hearings/{hearing_id}/decide",
            payload,
            headers=headers,
        )

    # ---------------------------------------------- recovery fund claims ----
    def create_claim(self, payload: Json, headers: Headers):
        return self.post("/licensing/recovery-fund-claims", payload, headers=headers)

    def get_claim(self, claim_id: str, headers: Headers):
        return self.get(f"/licensing/recovery-fund-claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Headers, params: Optional[Json] = None):
        return self.get("/licensing/recovery-fund-claims", params=params or {}, headers=headers)

    def adjudicate_claim(self, claim_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/recovery-fund-claims/{claim_id}/adjudicate",
            payload,
            headers=headers,
        )

    def pay_claim(self, claim_id: str, payload: Json, headers: Headers):
        return self.post(
            f"/licensing/recovery-fund-claims/{claim_id}/pay", payload, headers=headers
        )


# Module-level singleton the conftest fixture hands to every test.
api_client = ApiClient()
