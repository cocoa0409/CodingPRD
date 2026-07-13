"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Contributors ---
    def create_contributor(self, payload, headers=None):
        # Self-registration requires no authentication headers (PRD §3.1).
        return self._request("POST", "/contributors", payload, headers=headers)

    def get_contributor(self, contributor_id, headers):
        return self._request("GET", f"/contributors/{contributor_id}", headers=headers)

    def list_contributors(self, headers, params=None):
        return self._request("GET", "/contributors", headers=headers, params=params)

    # --- Tax forms ---
    def create_tax_form(self, contributor_id, payload, headers):
        return self._request("POST", f"/contributors/{contributor_id}/tax-forms", payload, headers=headers)

    def list_tax_forms(self, contributor_id, headers):
        return self._request("GET", f"/contributors/{contributor_id}/tax-forms", headers=headers)

    def decide_tax_form(self, tax_form_id, payload, headers):
        return self._request("POST", f"/tax-forms/{tax_form_id}/decision", payload, headers=headers)

    # --- Model releases ---
    def create_model_release(self, contributor_id, payload, headers):
        return self._request("POST", f"/contributors/{contributor_id}/model-releases", payload, headers=headers)

    def list_model_releases(self, contributor_id, headers):
        return self._request("GET", f"/contributors/{contributor_id}/model-releases", headers=headers)

    def decide_model_release(self, release_id, payload, headers):
        return self._request("POST", f"/model-releases/{release_id}/decision", payload, headers=headers)

    # --- Exclusivity windows ---
    def create_exclusivity_window(self, contributor_id, payload, headers):
        return self._request("POST", f"/contributors/{contributor_id}/exclusivity-windows", payload, headers=headers)

    def list_exclusivity_windows(self, contributor_id, headers):
        return self._request("GET", f"/contributors/{contributor_id}/exclusivity-windows", headers=headers)

    # --- Earning adjustments ---
    def create_earning_adjustment(self, contributor_id, payload, headers):
        return self._request("POST", f"/contributors/{contributor_id}/earning-adjustments", payload, headers=headers)

    def list_earning_adjustments(self, contributor_id, headers):
        return self._request("GET", f"/contributors/{contributor_id}/earning-adjustments", headers=headers)

    # --- Payouts (contributor-owned) ---
    def create_payout(self, contributor_id, payload, headers):
        return self._request("POST", f"/contributors/{contributor_id}/payouts", payload, headers=headers)

    def list_payouts(self, contributor_id, headers):
        return self._request("GET", f"/contributors/{contributor_id}/payouts", headers=headers)

    # --- Assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers=headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def update_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/assets/{asset_id}", payload, headers=headers)

    def submit_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/submit", {}, headers=headers)

    def claim_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/claim", {}, headers=headers)

    def create_review(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/reviews", payload, headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    # --- License tiers ---
    def create_license_tier(self, payload, headers):
        return self._request("POST", "/license-tiers", payload, headers=headers)

    def list_license_tiers(self, headers, params=None):
        return self._request("GET", "/license-tiers", headers=headers, params=params)

    # --- Downloads ---
    def create_download(self, payload, headers):
        return self._request("POST", "/downloads", payload, headers=headers)

    def list_downloads(self, headers, params=None):
        return self._request("GET", "/downloads", headers=headers, params=params)

    def get_download(self, download_id, headers):
        return self._request("GET", f"/downloads/{download_id}", headers=headers)

    def settle_download(self, download_id, headers):
        return self._request("POST", f"/downloads/{download_id}/settle", {}, headers=headers)

    def reverse_download(self, download_id, payload, headers):
        return self._request("POST", f"/downloads/{download_id}/reverse", payload, headers=headers)

    # --- Payout lifecycle ---
    def process_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/process", {}, headers=headers)

    def complete_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/complete", payload, headers=headers)

    # --- Takedowns ---
    def create_takedown(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/takedowns", payload, headers=headers)

    def list_takedowns(self, headers, params=None):
        return self._request("GET", "/takedowns", headers=headers, params=params)

    def get_takedown(self, takedown_id, headers):
        return self._request("GET", f"/takedowns/{takedown_id}", headers=headers)

    def decide_takedown(self, takedown_id, payload, headers):
        return self._request("POST", f"/takedowns/{takedown_id}/decision", payload, headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
