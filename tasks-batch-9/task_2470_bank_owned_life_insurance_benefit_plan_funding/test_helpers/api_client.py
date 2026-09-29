"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- capital positions ----------------
    def create_capital_position(self, payload, headers):
        return self._request("POST", "/capital-positions", payload, headers)

    def get_capital_position(self, capital_position_id, headers):
        return self._request(
            "GET", f"/capital-positions/{capital_position_id}", headers=headers
        )

    # ---------------- carriers ----------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/suspend", {}, headers)

    def reinstate_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/reinstate", {}, headers)

    def terminate_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/terminate", {}, headers)

    # ---------------- product types ----------------
    def create_product_type(self, payload, headers):
        return self._request("POST", "/product-types", payload, headers)

    def list_product_types(self, headers, params=None):
        return self._request("GET", "/product-types", headers=headers, params=params)

    def get_product_type(self, product_type_id, headers):
        return self._request("GET", f"/product-types/{product_type_id}", headers=headers)

    def clear_product_watch(self, product_type_id, headers):
        return self._request(
            "POST", f"/product-types/{product_type_id}/clear-watch", {}, headers
        )

    # ---------------- diligence reviews ----------------
    def create_diligence_review(self, payload, headers):
        return self._request("POST", "/diligence-reviews", payload, headers)

    def list_diligence_reviews(self, headers, params=None):
        return self._request("GET", "/diligence-reviews", headers=headers, params=params)

    def get_diligence_review(self, review_id, headers):
        return self._request("GET", f"/diligence-reviews/{review_id}", headers=headers)

    def submit_diligence_review(self, review_id, headers):
        return self._request(
            "POST", f"/diligence-reviews/{review_id}/submit", {}, headers
        )

    def request_diligence_info(self, review_id, headers):
        return self._request(
            "POST", f"/diligence-reviews/{review_id}/request-info", {}, headers
        )

    def approve_diligence_review(self, review_id, headers):
        return self._request(
            "POST", f"/diligence-reviews/{review_id}/approve", {}, headers
        )

    def decline_diligence_review(self, review_id, headers):
        return self._request(
            "POST", f"/diligence-reviews/{review_id}/decline", {}, headers
        )

    # ---------------- employees ----------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def set_employment_status(self, employee_id, payload, headers):
        return self._request(
            "POST", f"/employees/{employee_id}/employment-status", payload, headers
        )

    # ---------------- consent records ----------------
    def create_consent_record(self, payload, headers):
        return self._request("POST", "/consent-records", payload, headers)

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/consent-records", headers=headers, params=params)

    def get_consent_record(self, consent_record_id, headers):
        return self._request(
            "GET", f"/consent-records/{consent_record_id}", headers=headers
        )

    def execute_consent_record(self, consent_record_id, headers):
        return self._request(
            "POST", f"/consent-records/{consent_record_id}/execute", {}, headers
        )

    def revoke_consent_record(self, consent_record_id, headers):
        return self._request(
            "POST", f"/consent-records/{consent_record_id}/revoke", {}, headers
        )

    # ---------------- purchase requests ----------------
    def create_purchase_request(self, payload, headers):
        return self._request("POST", "/purchase-requests", payload, headers)

    def list_purchase_requests(self, headers, params=None):
        return self._request("GET", "/purchase-requests", headers=headers, params=params)

    def get_purchase_request(self, request_id, headers):
        return self._request("GET", f"/purchase-requests/{request_id}", headers=headers)

    def get_capacity_projection(self, request_id, headers):
        return self._request(
            "GET", f"/purchase-requests/{request_id}/capacity-projection", headers=headers
        )

    def submit_purchase_request(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/submit", {}, headers
        )

    def clear_purchase_request_diligence(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/clear-diligence", {}, headers
        )

    def reserve_purchase_request_capacity(self, request_id, payload, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/reserve-capacity", payload, headers
        )

    def file_purchase_request_notice(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/file-notice", {}, headers
        )

    def request_purchase_request_concurrence(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/request-concurrence", {}, headers
        )

    def approve_purchase_request(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/approve", {}, headers
        )

    def reject_purchase_request(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/reject", {}, headers
        )

    def withdraw_purchase_request(self, request_id, headers):
        return self._request(
            "POST", f"/purchase-requests/{request_id}/withdraw", {}, headers
        )

    # ---------------- policies ----------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    # ---------------- policy valuations ----------------
    def create_policy_valuation(self, payload, headers):
        return self._request("POST", "/policy-valuations", payload, headers)

    def list_policy_valuations(self, headers, params=None):
        return self._request("GET", "/policy-valuations", headers=headers, params=params)

    def get_policy_valuation(self, valuation_id, headers):
        return self._request("GET", f"/policy-valuations/{valuation_id}", headers=headers)

    # ---------------- nqdc plans ----------------
    def create_nqdc_plan(self, payload, headers):
        return self._request("POST", "/nqdc-plans", payload, headers)

    def get_nqdc_plan(self, plan_id, headers):
        return self._request("GET", f"/nqdc-plans/{plan_id}", headers=headers)

    def get_nqdc_funding_summary(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/nqdc-plans/{plan_id}/funding-summary", headers=headers, params=params
        )

    def revalue_nqdc_plan(self, plan_id, headers):
        return self._request("POST", f"/nqdc-plans/{plan_id}/revalue", {}, headers)

    def freeze_nqdc_plan(self, plan_id, headers):
        return self._request("POST", f"/nqdc-plans/{plan_id}/freeze", {}, headers)

    def unfreeze_nqdc_plan(self, plan_id, headers):
        return self._request("POST", f"/nqdc-plans/{plan_id}/unfreeze", {}, headers)

    def terminate_nqdc_plan(self, plan_id, headers):
        return self._request("POST", f"/nqdc-plans/{plan_id}/terminate", {}, headers)

    # ---------------- nqdc participant liabilities ----------------
    def create_nqdc_liability(self, payload, headers):
        return self._request("POST", "/nqdc-liabilities", payload, headers)

    def list_nqdc_liabilities(self, headers, params=None):
        return self._request("GET", "/nqdc-liabilities", headers=headers, params=params)

    def get_nqdc_liability(self, liability_id, headers):
        return self._request("GET", f"/nqdc-liabilities/{liability_id}", headers=headers)

    def settle_nqdc_liability(self, liability_id, headers):
        return self._request(
            "POST", f"/nqdc-liabilities/{liability_id}/settle", {}, headers
        )

    # ---------------- death benefit claims ----------------
    def create_death_claim(self, payload, headers):
        return self._request("POST", "/death-claims", payload, headers)

    def list_death_claims(self, headers, params=None):
        return self._request("GET", "/death-claims", headers=headers, params=params)

    def get_death_claim(self, claim_id, headers):
        return self._request("GET", f"/death-claims/{claim_id}", headers=headers)

    def start_claim_adjudication(self, claim_id, headers):
        return self._request(
            "POST", f"/death-claims/{claim_id}/start-adjudication", {}, headers
        )

    def approve_death_claim(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/approve", {}, headers)

    def deny_death_claim(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/deny", {}, headers)

    def void_death_claim(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/void", {}, headers)

    def seal_claim_allocations(self, claim_id, headers):
        return self._request(
            "POST", f"/death-claims/{claim_id}/seal-allocations", {}, headers
        )

    def distribute_death_claim(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/distribute", {}, headers)

    # ---------------- beneficiary allocations ----------------
    def create_beneficiary_allocation(self, payload, headers):
        return self._request("POST", "/beneficiary-allocations", payload, headers)

    def list_beneficiary_allocations(self, headers, params=None):
        return self._request(
            "GET", "/beneficiary-allocations", headers=headers, params=params
        )

    def get_beneficiary_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/beneficiary-allocations/{allocation_id}", headers=headers
        )

    def void_beneficiary_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/beneficiary-allocations/{allocation_id}/void", {}, headers
        )

    # ---------------- exchange / surrender analyses ----------------
    def create_exchange_analysis(self, payload, headers):
        return self._request("POST", "/exchange-analyses", payload, headers)

    def list_exchange_analyses(self, headers, params=None):
        return self._request("GET", "/exchange-analyses", headers=headers, params=params)

    def get_exchange_analysis(self, analysis_id, headers):
        return self._request("GET", f"/exchange-analyses/{analysis_id}", headers=headers)

    def review_exchange_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/exchange-analyses/{analysis_id}/review", {}, headers
        )

    def reject_exchange_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/exchange-analyses/{analysis_id}/reject", {}, headers
        )

    def commit_exchange_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/exchange-analyses/{analysis_id}/commit", {}, headers
        )

    def abandon_exchange_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/exchange-analyses/{analysis_id}/abandon", {}, headers
        )

    def execute_exchange(self, analysis_id, payload, headers):
        return self._request(
            "POST", f"/exchange-analyses/{analysis_id}/execute-exchange", payload, headers
        )

    def execute_surrender(self, analysis_id, headers):
        return self._request(
            "POST", f"/exchange-analyses/{analysis_id}/execute-surrender", {}, headers
        )

    # ---------------- risk assessments ----------------
    def create_risk_assessment(self, payload, headers):
        return self._request("POST", "/risk-assessments", payload, headers)

    def list_risk_assessments(self, headers, params=None):
        return self._request("GET", "/risk-assessments", headers=headers, params=params)

    def get_risk_assessment(self, assessment_id, headers):
        return self._request("GET", f"/risk-assessments/{assessment_id}", headers=headers)

    def submit_risk_assessment_to_board(self, assessment_id, headers):
        return self._request(
            "POST", f"/risk-assessments/{assessment_id}/submit-to-board", {}, headers
        )

    def accept_risk_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/risk-assessments/{assessment_id}/accept", payload, headers
        )

    def return_risk_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/risk-assessments/{assessment_id}/return", payload, headers
        )


api_client = ApiClient()
