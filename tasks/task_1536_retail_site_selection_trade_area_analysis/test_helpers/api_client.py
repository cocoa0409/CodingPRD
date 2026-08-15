"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/api/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/api/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/api/markets/{market_id}", headers=headers)

    def evaluate_market(self, market_id, headers):
        return self._request("POST", f"/api/markets/{market_id}/evaluate", {}, headers)

    def close_market(self, market_id, headers):
        return self._request("POST", f"/api/markets/{market_id}/close", {}, headers)

    # --- Existing stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/api/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/api/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/api/stores/{store_id}", headers=headers)

    def close_store(self, store_id, headers):
        return self._request("POST", f"/api/stores/{store_id}/close", {}, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def run_site_screening(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/run-screening", {}, headers)

    def submit_site_to_committee(self, site_id, payload, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/submit-committee", payload, headers
        )

    def withdraw_site(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/withdraw", {}, headers)

    def revise_site(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/revise", {}, headers)

    def open_site(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/open", {}, headers)

    def close_out_site(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/close-out", {}, headers)

    # --- Trade area models ---
    def create_trade_area_model(self, payload, headers):
        return self._request("POST", "/api/trade-area-models", payload, headers)

    def list_trade_area_models(self, headers, params=None):
        return self._request(
            "GET", "/api/trade-area-models", headers=headers, params=params
        )

    def get_trade_area_model(self, model_id, headers):
        return self._request(
            "GET", f"/api/trade-area-models/{model_id}", headers=headers
        )

    def lock_trade_area_model(self, model_id, payload, headers):
        return self._request(
            "POST", f"/api/trade-area-models/{model_id}/lock", payload, headers
        )

    # --- Competitor listings ---
    def create_competitor_listing(self, payload, headers):
        return self._request("POST", "/api/competitor-listings", payload, headers)

    def list_competitor_listings(self, headers, params=None):
        return self._request(
            "GET", "/api/competitor-listings", headers=headers, params=params
        )

    def get_competitor_listing(self, listing_id, headers):
        return self._request(
            "GET", f"/api/competitor-listings/{listing_id}", headers=headers
        )

    def delete_competitor_listing(self, listing_id, headers):
        return self._request(
            "DELETE", f"/api/competitor-listings/{listing_id}", headers=headers
        )

    # --- Site visits ---
    def create_site_visit(self, payload, headers):
        return self._request("POST", "/api/site-visits", payload, headers)

    def list_site_visits(self, headers, params=None):
        return self._request("GET", "/api/site-visits", headers=headers, params=params)

    def get_site_visit(self, visit_id, headers):
        return self._request("GET", f"/api/site-visits/{visit_id}", headers=headers)

    # --- Sales forecasts ---
    def create_sales_forecast(self, payload, headers):
        return self._request("POST", "/api/sales-forecasts", payload, headers)

    def list_sales_forecasts(self, headers, params=None):
        return self._request(
            "GET", "/api/sales-forecasts", headers=headers, params=params
        )

    def get_sales_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/api/sales-forecasts/{forecast_id}", headers=headers
        )

    def lock_sales_forecast(self, forecast_id, headers):
        return self._request(
            "POST", f"/api/sales-forecasts/{forecast_id}/lock", {}, headers
        )

    # --- Committee members ---
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/api/committee-members", payload, headers)

    def list_committee_members(self, headers, params=None):
        return self._request(
            "GET", "/api/committee-members", headers=headers, params=params
        )

    def get_committee_member(self, member_id, headers):
        return self._request(
            "GET", f"/api/committee-members/{member_id}", headers=headers
        )

    def deactivate_committee_member(self, member_id, headers):
        return self._request(
            "POST", f"/api/committee-members/{member_id}/deactivate", {}, headers
        )

    # --- Committee reviews & votes ---
    def list_committee_reviews(self, headers, params=None):
        return self._request(
            "GET", "/api/committee-reviews", headers=headers, params=params
        )

    def get_committee_review(self, review_id, headers):
        return self._request(
            "GET", f"/api/committee-reviews/{review_id}", headers=headers
        )

    def cast_vote(self, review_id, payload, headers):
        return self._request(
            "POST", f"/api/committee-reviews/{review_id}/votes", payload, headers
        )

    def ratify_review(self, review_id, headers):
        return self._request(
            "POST", f"/api/committee-reviews/{review_id}/ratify", {}, headers
        )

    def list_votes(self, headers, params=None):
        return self._request("GET", "/api/votes", headers=headers, params=params)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"/api/votes/{vote_id}", headers=headers)

    # --- LOIs ---
    def create_loi(self, payload, headers):
        return self._request("POST", "/api/lois", payload, headers)

    def list_lois(self, headers, params=None):
        return self._request("GET", "/api/lois", headers=headers, params=params)

    def get_loi(self, loi_id, headers):
        return self._request("GET", f"/api/lois/{loi_id}", headers=headers)

    def send_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/send", {}, headers)

    def counter_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/api/lois/{loi_id}/counter", payload, headers)

    def resend_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/api/lois/{loi_id}/resend", payload, headers)

    def accept_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/accept", {}, headers)

    def withdraw_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/withdraw", {}, headers)

    # --- Leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/api/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/api/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/api/leases/{lease_id}", headers=headers)

    def execute_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/execute", {}, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/terminate", {}, headers)

    # --- Construction crews ---
    def create_construction_crew(self, payload, headers):
        return self._request("POST", "/api/construction-crews", payload, headers)

    def list_construction_crews(self, headers, params=None):
        return self._request(
            "GET", "/api/construction-crews", headers=headers, params=params
        )

    def get_construction_crew(self, crew_id, headers):
        return self._request(
            "GET", f"/api/construction-crews/{crew_id}", headers=headers
        )

    def retire_construction_crew(self, crew_id, headers):
        return self._request(
            "POST", f"/api/construction-crews/{crew_id}/retire", {}, headers
        )

    # --- Permit milestones ---
    def create_permit_milestone(self, payload, headers):
        return self._request("POST", "/api/permit-milestones", payload, headers)

    def list_permit_milestones(self, headers, params=None):
        return self._request(
            "GET", "/api/permit-milestones", headers=headers, params=params
        )

    def get_permit_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/api/permit-milestones/{milestone_id}", headers=headers
        )

    def complete_permit_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"/api/permit-milestones/{milestone_id}/complete",
            payload,
            headers,
        )

    # --- Performance snapshots ---
    def create_performance_snapshot(self, payload, headers):
        return self._request("POST", "/api/performance-snapshots", payload, headers)

    def list_performance_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/api/performance-snapshots", headers=headers, params=params
        )

    def get_performance_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/api/performance-snapshots/{snapshot_id}", headers=headers
        )

    def finalize_performance_snapshot(self, snapshot_id, headers):
        return self._request(
            "POST", f"/api/performance-snapshots/{snapshot_id}/finalize", {}, headers
        )

    # --- Logical clock ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
