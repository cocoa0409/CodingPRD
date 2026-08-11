"""API client: one method per endpoint defined in the PRD (all mounted under /stairlift-ops)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/stairlift-ops"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    # --- Home assessments ---
    def create_home_assessment(self, customer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/customers/{customer_id}/home-assessments",
                             payload, headers)

    def list_home_assessments(self, customer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}/home-assessments",
                             headers=headers, params=params)

    def get_home_assessment(self, assessment_id, headers):
        return self._request("GET", f"{PREFIX}/home-assessments/{assessment_id}", headers=headers)

    def measure_home_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/home-assessments/{assessment_id}/measure",
                             payload, headers)

    def approve_home_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/home-assessments/{assessment_id}/approve",
                             payload, headers)

    def reject_home_assessment(self, assessment_id, headers):
        return self._request("POST", f"{PREFIX}/home-assessments/{assessment_id}/reject",
                             {}, headers)

    # --- Product catalog ---
    def create_product_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/product-models", payload, headers)

    def list_product_models(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/product-models", headers=headers, params=params)

    def get_product_model(self, model_code, headers):
        return self._request("GET", f"{PREFIX}/product-models/{model_code}", headers=headers)

    # --- Equipment inventory ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/equipment-units/{unit_id}", headers=headers)

    def restock_equipment_unit(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-units/{unit_id}/restock", {}, headers)

    def retire_equipment_unit(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/equipment-units/{unit_id}/retire", {}, headers)

    # --- Quotes ---
    def create_quote(self, customer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/customers/{customer_id}/quotes", payload, headers)

    def list_quotes_for_customer(self, customer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}/quotes",
                             headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/quotes", headers=headers, params=params)

    def list_agreements_for_quote(self, quote_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}/agreements",
                             headers=headers, params=params)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/issue", {}, headers)

    def revise_quote(self, quote_id, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/revise", {}, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/accept", payload, headers)

    # --- Funding applications ---
    def create_funding_application(self, quote_id, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/funding-applications",
                             payload, headers)

    def list_funding_applications(self, quote_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}/funding-applications",
                             headers=headers, params=params)

    def get_funding_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/funding-applications/{application_id}",
                             headers=headers)

    def decide_funding_application(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/funding-applications/{application_id}/decide",
                             payload, headers)

    # --- Agreements ---
    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def skip_funding(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/skip-funding",
                             {}, headers)

    def record_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/payments",
                             payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/activate", {}, headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/cancel", {}, headers)

    def close_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/close", {}, headers)

    # --- Install jobs ---
    def create_install_job(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/install-jobs",
                             payload, headers)

    def list_install_jobs(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}/install-jobs",
                             headers=headers, params=params)

    def get_install_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/install-jobs/{job_id}", headers=headers)

    def start_install_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/install-jobs/{job_id}/start", {}, headers)

    def complete_install_job(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/install-jobs/{job_id}/complete", payload, headers)

    def fail_install_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/install-jobs/{job_id}/fail", {}, headers)

    def cancel_install_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/install-jobs/{job_id}/cancel", {}, headers)

    # --- Service plans ---
    def create_service_plan(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/service-plans",
                             payload, headers)

    def list_service_plans(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}/service-plans",
                             headers=headers, params=params)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/service-plans/{plan_id}", headers=headers)

    def cancel_service_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/service-plans/{plan_id}/cancel", {}, headers)

    def list_warranty_claims_for_service_plan(self, plan_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-plans/{plan_id}/warranty-claims",
                             headers=headers, params=params)

    # --- Warranty claims ---
    def create_warranty_claim(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/warranty-claims",
                             payload, headers)

    def list_warranty_claims(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}/warranty-claims",
                             headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers)

    def review_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/review", {}, headers)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/adjudicate",
                             payload, headers)

    def pay_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/pay", {}, headers)

    # --- Removal jobs ---
    def create_removal_job(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/removal-jobs",
                             payload, headers)

    def list_removal_jobs(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}/removal-jobs",
                             headers=headers, params=params)

    def get_removal_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/removal-jobs/{job_id}", headers=headers)

    def complete_removal_job(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/removal-jobs/{job_id}/complete", payload, headers)

    def cancel_removal_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/removal-jobs/{job_id}/cancel", {}, headers)

    # --- Equipment reverse lookup ---
    def list_agreements_for_equipment_unit(self, unit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/equipment-units/{unit_id}/agreements",
                             headers=headers, params=params)

    # --- Audit trail ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audit-events", headers=headers, params=params)


api_client = ApiClient()
