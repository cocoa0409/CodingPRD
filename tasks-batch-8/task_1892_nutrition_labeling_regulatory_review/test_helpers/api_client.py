"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the `/api` prefix (PRD endpoint section).
"""
from prd_bench_local_runner.testing import GenericApiClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The harness restarts the server before every test (per-test-server
        # isolation) on the same port, while this client's Session pools
        # keep-alive connections across tests. A pooled connection to the
        # just-killed server occasionally passes urllib3's staleness check and
        # then fails mid-write with RemoteDisconnected. Retry transport-level
        # connection/protocol errors on every method; response status codes
        # are never retried (a 4xx must reach the assertion layer untouched).
        retry = Retry(
            total=5, connect=5, read=5, backoff_factor=0.05,
            allowed_methods=None, raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/api/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}", headers=headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, client_id, payload, headers):
        return self._request("POST", f"/api/clients/{client_id}/products",
                             payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    def list_products(self, client_id, headers, params=None):
        return self._request("GET", f"/api/clients/{client_id}/products",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Ingredients
    # ------------------------------------------------------------------
    def create_ingredient(self, client_id, payload, headers):
        return self._request("POST", f"/api/clients/{client_id}/ingredients",
                             payload, headers)

    def list_ingredients(self, client_id, headers, params=None):
        return self._request("GET", f"/api/clients/{client_id}/ingredients",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------
    def create_recipe(self, product_id, payload, headers):
        return self._request("POST", f"/api/products/{product_id}/recipes",
                             payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/api/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, product_id, headers, params=None):
        return self._request("GET", f"/api/products/{product_id}/recipes",
                             headers=headers, params=params)

    def list_all_recipes(self, headers, params=None):
        return self._request("GET", "/api/recipes", headers=headers, params=params)

    def lock_recipe(self, recipe_id, headers):
        return self._request("POST", f"/api/recipes/{recipe_id}/lock", {}, headers)

    def get_ingredient_statement(self, recipe_id, headers):
        return self._request("GET", f"/api/recipes/{recipe_id}/ingredient-statement",
                             headers=headers)

    # ------------------------------------------------------------------
    # Lab analyses
    # ------------------------------------------------------------------
    def create_lab_analysis(self, recipe_id, payload, headers):
        return self._request("POST", f"/api/recipes/{recipe_id}/lab-analyses",
                             payload, headers)

    def list_lab_analyses(self, recipe_id, headers, params=None):
        return self._request("GET", f"/api/recipes/{recipe_id}/lab-analyses",
                             headers=headers, params=params)

    def review_lab_analysis(self, lab_analysis_id, payload, headers):
        return self._request("POST", f"/api/lab-analyses/{lab_analysis_id}/review",
                             payload, headers)

    # ------------------------------------------------------------------
    # Nutrient panels
    # ------------------------------------------------------------------
    def create_nutrient_panel(self, recipe_id, payload, headers):
        return self._request("POST", f"/api/recipes/{recipe_id}/nutrient-panels",
                             payload, headers)

    def list_nutrient_panels(self, recipe_id, headers, params=None):
        return self._request("GET", f"/api/recipes/{recipe_id}/nutrient-panels",
                             headers=headers, params=params)

    def get_nutrient_panel(self, panel_id, headers):
        return self._request("GET", f"/api/nutrient-panels/{panel_id}", headers=headers)

    def list_all_nutrient_panels(self, headers, params=None):
        return self._request("GET", "/api/nutrient-panels", headers=headers, params=params)

    # ------------------------------------------------------------------
    # RACC assignments
    # ------------------------------------------------------------------
    def create_racc_assignment(self, product_id, payload, headers):
        return self._request("POST", f"/api/products/{product_id}/racc-assignments",
                             payload, headers)

    def list_racc_assignments(self, product_id, headers, params=None):
        return self._request("GET", f"/api/products/{product_id}/racc-assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Label versions
    # ------------------------------------------------------------------
    def create_label_version(self, product_id, payload, headers):
        return self._request("POST", f"/api/products/{product_id}/label-versions",
                             payload, headers)

    def get_label_version(self, label_version_id, headers):
        return self._request("GET", f"/api/label-versions/{label_version_id}",
                             headers=headers)

    def list_label_versions(self, product_id, headers, params=None):
        return self._request("GET", f"/api/products/{product_id}/label-versions",
                             headers=headers, params=params)

    def list_all_label_versions(self, headers, params=None):
        return self._request("GET", "/api/label-versions", headers=headers, params=params)

    def submit_label_review(self, label_version_id, headers):
        return self._request("POST", f"/api/label-versions/{label_version_id}/submit-review",
                             {}, headers)

    def approve_label(self, label_version_id, headers):
        return self._request("POST", f"/api/label-versions/{label_version_id}/approve",
                             {}, headers)

    def reject_label(self, label_version_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/api/label-versions/{label_version_id}/reject",
                             payload, headers)

    def release_label(self, label_version_id, payload, headers):
        return self._request("POST", f"/api/label-versions/{label_version_id}/release",
                             payload, headers)

    def withdraw_label(self, label_version_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/api/label-versions/{label_version_id}/withdraw",
                             payload, headers)

    # ------------------------------------------------------------------
    # Claim assessments
    # ------------------------------------------------------------------
    def create_claim(self, label_version_id, payload, headers):
        return self._request("POST", f"/api/label-versions/{label_version_id}/claims",
                             payload, headers)

    def list_claims(self, label_version_id, headers, params=None):
        return self._request("GET", f"/api/label-versions/{label_version_id}/claims",
                             headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_all_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Market variants
    # ------------------------------------------------------------------
    def create_market_variant(self, label_version_id, payload, headers):
        return self._request("POST",
                             f"/api/label-versions/{label_version_id}/market-variants",
                             payload, headers)

    def list_market_variants(self, label_version_id, headers, params=None):
        return self._request("GET",
                             f"/api/label-versions/{label_version_id}/market-variants",
                             headers=headers, params=params)

    def activate_market_variant(self, market_variant_id, headers):
        return self._request("POST",
                             f"/api/market-variants/{market_variant_id}/activate",
                             {}, headers)

    def retire_market_variant(self, market_variant_id, headers):
        return self._request("POST",
                             f"/api/market-variants/{market_variant_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Format checks
    # ------------------------------------------------------------------
    def list_format_checks(self, label_version_id, headers, params=None):
        return self._request("GET",
                             f"/api/label-versions/{label_version_id}/format-checks",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Artwork audits and findings
    # ------------------------------------------------------------------
    def create_artwork_audit(self, client_id, payload, headers):
        return self._request("POST", f"/api/clients/{client_id}/artwork-audits",
                             payload, headers)

    def get_artwork_audit(self, audit_id, headers):
        return self._request("GET", f"/api/artwork-audits/{audit_id}", headers=headers)

    def list_artwork_audits(self, headers, params=None):
        return self._request("GET", "/api/artwork-audits", headers=headers, params=params)

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/api/artwork-audits/{audit_id}/findings",
                             payload, headers)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request("GET", f"/api/artwork-audits/{audit_id}/findings",
                             headers=headers, params=params)

    def close_artwork_audit(self, audit_id, headers):
        return self._request("POST", f"/api/artwork-audits/{audit_id}/close",
                             {}, headers)


api_client = ApiClient()
