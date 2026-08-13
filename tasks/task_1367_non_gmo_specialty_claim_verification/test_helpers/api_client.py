"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Claim standards ---
    def create_claim_standard(self, payload, headers):
        return self._request("POST", "/claim-standards", payload, headers)

    def list_claim_standards(self, headers, params=None):
        return self._request("GET", "/claim-standards", headers=headers, params=params)

    # --- Brands ---
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def submit_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/submit", headers=headers)

    def begin_evaluation(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/begin-evaluation", headers=headers)

    def decide_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/decide", payload, headers)

    def resubmit_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/resubmit", headers=headers)

    def renew_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/renew", headers=headers)

    def reinstate_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/reinstate", headers=headers)

    # --- Ingredients ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/ingredients/{ingredient_id}", headers=headers)

    # --- Affidavits ---
    def create_affidavit(self, payload, headers):
        return self._request("POST", "/affidavits", payload, headers)

    def list_affidavits(self, headers, params=None):
        return self._request("GET", "/affidavits", headers=headers, params=params)

    def get_affidavit(self, affidavit_id, headers):
        return self._request("GET", f"/affidavits/{affidavit_id}", headers=headers)

    def review_affidavit(self, affidavit_id, payload, headers):
        return self._request("POST", f"/affidavits/{affidavit_id}/review", payload, headers)

    # --- Sampling plans ---
    def create_sampling_plan(self, payload, headers):
        return self._request("POST", "/sampling-plans", payload, headers)

    def list_sampling_plans(self, headers, params=None):
        return self._request("GET", "/sampling-plans", headers=headers, params=params)

    def get_sampling_plan(self, plan_id, headers):
        return self._request("GET", f"/sampling-plans/{plan_id}", headers=headers)

    # --- Test samples ---
    def create_sample(self, payload, headers):
        return self._request("POST", "/samples", payload, headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/samples", headers=headers, params=params)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/samples/{sample_id}", headers=headers)

    def record_sample_result(self, sample_id, payload, headers):
        return self._request("POST", f"/samples/{sample_id}/record-result", payload, headers)

    def confirm_sample(self, sample_id, headers):
        return self._request("POST", f"/samples/{sample_id}/confirm", headers=headers)

    def invalidate_sample(self, sample_id, headers):
        return self._request("POST", f"/samples/{sample_id}/invalidate", headers=headers)

    # --- Facility audits ---
    def create_facility_audit(self, payload, headers):
        return self._request("POST", "/facility-audits", payload, headers)

    def list_facility_audits(self, headers, params=None):
        return self._request("GET", "/facility-audits", headers=headers, params=params)

    def get_facility_audit(self, audit_id, headers):
        return self._request("GET", f"/facility-audits/{audit_id}", headers=headers)

    def submit_audit_report(self, audit_id, payload, headers):
        return self._request("POST", f"/facility-audits/{audit_id}/submit-report", payload, headers)

    def decide_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/facility-audits/{audit_id}/decide", payload, headers)

    # --- Label licenses (read-only) ---
    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    # --- Enforcement cases ---
    def create_enforcement_case(self, payload, headers):
        return self._request("POST", "/enforcement-cases", payload, headers)

    def list_enforcement_cases(self, headers, params=None):
        return self._request("GET", "/enforcement-cases", headers=headers, params=params)

    def get_enforcement_case(self, case_id, headers):
        return self._request("GET", f"/enforcement-cases/{case_id}", headers=headers)

    def resolve_enforcement_case(self, case_id, payload, headers):
        return self._request("POST", f"/enforcement-cases/{case_id}/resolve", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
