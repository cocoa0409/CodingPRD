"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving (logical clock and time-based sweep) ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request("POST", "/rollout/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_time_sweep(self, headers=None):
        return self._request("POST", "/rollout/_sweeps/time-based", {}, headers)

    # --- RolloutProgram ---
    def create_program(self, payload, headers=None):
        return self._request("POST", "/rollout/programs", payload, headers)

    def list_programs(self, headers=None, params=None):
        return self._request("GET", "/rollout/programs", headers=headers, params=params)

    def get_program(self, program_id, headers=None):
        return self._request("GET", f"/rollout/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers=None):
        return self._request("POST", f"/rollout/programs/{program_id}/activate", {}, headers)

    def complete_program(self, program_id, headers=None):
        return self._request("POST", f"/rollout/programs/{program_id}/complete", {}, headers)

    # --- Market ---
    def create_market(self, payload, headers=None):
        return self._request("POST", "/rollout/markets", payload, headers)

    def list_markets(self, headers=None, params=None):
        return self._request("GET", "/rollout/markets", headers=headers, params=params)

    def get_market(self, market_id, headers=None):
        return self._request("GET", f"/rollout/markets/{market_id}", headers=headers)

    def open_market_bidding(self, market_id, headers=None):
        return self._request("POST", f"/rollout/markets/{market_id}/open-bidding", {}, headers)

    # --- MunicipalityProfile ---
    def create_municipality_profile(self, payload, headers=None):
        return self._request("POST", "/rollout/municipality-profiles", payload, headers)

    def list_municipality_profiles(self, headers=None, params=None):
        return self._request("GET", "/rollout/municipality-profiles", headers=headers, params=params)

    # --- Site ---
    def create_site(self, payload, headers=None):
        return self._request("POST", "/rollout/sites", payload, headers)

    def list_sites(self, headers=None, params=None):
        return self._request("GET", "/rollout/sites", headers=headers, params=params)

    def get_site(self, site_id, headers=None):
        return self._request("GET", f"/rollout/sites/{site_id}", headers=headers)

    def patch_site(self, site_id, payload, headers=None):
        return self._request("PATCH", f"/rollout/sites/{site_id}", payload, headers)

    def advance_site_design(self, site_id, headers=None):
        return self._request("POST", f"/rollout/sites/{site_id}/advance-design", {}, headers)

    def submit_site_design(self, site_id, headers=None):
        return self._request("POST", f"/rollout/sites/{site_id}/submit-design", {}, headers)

    def mark_site_permitted(self, site_id, headers=None):
        return self._request("POST", f"/rollout/sites/{site_id}/mark-permitted", {}, headers)

    def start_site_build(self, site_id, headers=None):
        return self._request("POST", f"/rollout/sites/{site_id}/start-build", {}, headers)

    def open_site(self, site_id, headers=None):
        return self._request("POST", f"/rollout/sites/{site_id}/open", {}, headers)

    def remove_site(self, site_id, headers=None):
        return self._request("POST", f"/rollout/sites/{site_id}/remove", {}, headers)

    # --- DrawingSet ---
    def create_drawing_set(self, payload, headers=None):
        return self._request("POST", "/rollout/drawing-sets", payload, headers)

    def list_drawing_sets(self, headers=None, params=None):
        return self._request("GET", "/rollout/drawing-sets", headers=headers, params=params)

    def get_drawing_set(self, drawing_set_id, headers=None):
        return self._request("GET", f"/rollout/drawing-sets/{drawing_set_id}", headers=headers)

    def submit_drawing_set(self, drawing_set_id, headers=None):
        return self._request("POST", f"/rollout/drawing-sets/{drawing_set_id}/submit", {}, headers)

    def approve_drawing_set(self, drawing_set_id, headers=None):
        return self._request("POST", f"/rollout/drawing-sets/{drawing_set_id}/approve", {}, headers)

    def reject_drawing_set(self, drawing_set_id, payload, headers=None):
        return self._request("POST", f"/rollout/drawing-sets/{drawing_set_id}/reject", payload, headers)

    def revise_drawing_set(self, drawing_set_id, headers=None):
        return self._request("POST", f"/rollout/drawing-sets/{drawing_set_id}/revise", {}, headers)

    # --- Permit ---
    def create_permit(self, payload, headers=None):
        return self._request("POST", "/rollout/permits", payload, headers)

    def list_permits(self, headers=None, params=None):
        return self._request("GET", "/rollout/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers=None):
        return self._request("GET", f"/rollout/permits/{permit_id}", headers=headers)

    def file_permit(self, permit_id, headers=None):
        return self._request("POST", f"/rollout/permits/{permit_id}/file", {}, headers)

    def start_permit_review(self, permit_id, headers=None):
        return self._request("POST", f"/rollout/permits/{permit_id}/start-review", {}, headers)

    def issue_permit(self, permit_id, headers=None):
        return self._request("POST", f"/rollout/permits/{permit_id}/issue", {}, headers)

    def reject_permit(self, permit_id, payload, headers=None):
        return self._request("POST", f"/rollout/permits/{permit_id}/reject", payload, headers)

    def refile_permit(self, permit_id, payload, headers=None):
        return self._request("POST", f"/rollout/permits/{permit_id}/refile", payload, headers)

    def withdraw_permit(self, permit_id, headers=None):
        return self._request("POST", f"/rollout/permits/{permit_id}/withdraw", {}, headers)

    # --- Contractor ---
    def create_contractor(self, payload, headers=None):
        return self._request("POST", "/rollout/contractors", payload, headers)

    def list_contractors(self, headers=None, params=None):
        return self._request("GET", "/rollout/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers=None):
        return self._request("GET", f"/rollout/contractors/{contractor_id}", headers=headers)

    def suspend_contractor(self, contractor_id, headers=None):
        return self._request("POST", f"/rollout/contractors/{contractor_id}/suspend", {}, headers)

    # --- BidPackage ---
    def create_bid_package(self, payload, headers=None):
        return self._request("POST", "/rollout/bid-packages", payload, headers)

    def list_bid_packages(self, headers=None, params=None):
        return self._request("GET", "/rollout/bid-packages", headers=headers, params=params)

    def get_bid_package(self, bid_package_id, headers=None):
        return self._request("GET", f"/rollout/bid-packages/{bid_package_id}", headers=headers)

    def open_bid_package(self, bid_package_id, headers=None):
        return self._request("POST", f"/rollout/bid-packages/{bid_package_id}/open", {}, headers)

    def close_bid_package(self, bid_package_id, headers=None):
        return self._request("POST", f"/rollout/bid-packages/{bid_package_id}/close", {}, headers)

    def award_bid_package(self, bid_package_id, headers=None):
        return self._request("POST", f"/rollout/bid-packages/{bid_package_id}/award", {}, headers)

    # --- Bid ---
    def create_bid(self, payload, headers=None):
        return self._request("POST", "/rollout/bids", payload, headers)

    def list_bids(self, headers=None, params=None):
        return self._request("GET", "/rollout/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers=None):
        return self._request("GET", f"/rollout/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, bid_id, headers=None):
        return self._request("POST", f"/rollout/bids/{bid_id}/withdraw", {}, headers)

    # --- VendorMobilization ---
    def create_vendor_mobilization(self, payload, headers=None):
        return self._request("POST", "/rollout/vendor-mobilizations", payload, headers)

    def list_vendor_mobilizations(self, headers=None, params=None):
        return self._request("GET", "/rollout/vendor-mobilizations", headers=headers, params=params)

    def get_vendor_mobilization(self, mobilization_id, headers=None):
        return self._request("GET", f"/rollout/vendor-mobilizations/{mobilization_id}", headers=headers)

    def schedule_mobilization(self, mobilization_id, headers=None):
        return self._request("POST", f"/rollout/vendor-mobilizations/{mobilization_id}/schedule", {}, headers)

    def arrive_mobilization(self, mobilization_id, headers=None):
        return self._request("POST", f"/rollout/vendor-mobilizations/{mobilization_id}/arrive", {}, headers)

    def complete_mobilization(self, mobilization_id, headers=None):
        return self._request("POST", f"/rollout/vendor-mobilizations/{mobilization_id}/complete", {}, headers)

    def cancel_mobilization(self, mobilization_id, headers=None):
        return self._request("POST", f"/rollout/vendor-mobilizations/{mobilization_id}/cancel", {}, headers)

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers=None):
        return self._request("POST", "/rollout/change-orders", payload, headers)

    def list_change_orders(self, headers=None, params=None):
        return self._request("GET", "/rollout/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers=None):
        return self._request("GET", f"/rollout/change-orders/{change_order_id}", headers=headers)

    def approve_change_order(self, change_order_id, payload, headers=None):
        return self._request("POST", f"/rollout/change-orders/{change_order_id}/approve", payload, headers)

    def reject_change_order(self, change_order_id, payload, headers=None):
        return self._request("POST", f"/rollout/change-orders/{change_order_id}/reject", payload, headers)

    def rescind_change_order(self, change_order_id, payload, headers=None):
        return self._request("POST", f"/rollout/change-orders/{change_order_id}/rescind", payload, headers)

    def cancel_change_order(self, change_order_id, headers=None):
        return self._request("POST", f"/rollout/change-orders/{change_order_id}/cancel", {}, headers)

    # --- PunchItem ---
    def create_punch_item(self, payload, headers=None):
        return self._request("POST", "/rollout/punch-items", payload, headers)

    def list_punch_items(self, headers=None, params=None):
        return self._request("GET", "/rollout/punch-items", headers=headers, params=params)

    def get_punch_item(self, punch_item_id, headers=None):
        return self._request("GET", f"/rollout/punch-items/{punch_item_id}", headers=headers)

    def resolve_punch_item(self, punch_item_id, headers=None):
        return self._request("POST", f"/rollout/punch-items/{punch_item_id}/resolve", {}, headers)

    def verify_punch_item(self, punch_item_id, headers=None):
        return self._request("POST", f"/rollout/punch-items/{punch_item_id}/verify", {}, headers)

    def fail_punch_item_verification(self, punch_item_id, payload, headers=None):
        return self._request("POST", f"/rollout/punch-items/{punch_item_id}/fail-verification", payload, headers)

    def waive_punch_item(self, punch_item_id, headers=None):
        return self._request("POST", f"/rollout/punch-items/{punch_item_id}/waive", {}, headers)

    # --- Turnover ---
    def create_turnover(self, payload, headers=None):
        return self._request("POST", "/rollout/turnovers", payload, headers)

    def list_turnovers(self, headers=None, params=None):
        return self._request("GET", "/rollout/turnovers", headers=headers, params=params)

    def get_turnover(self, turnover_id, headers=None):
        return self._request("GET", f"/rollout/turnovers/{turnover_id}", headers=headers)

    def accept_turnover(self, turnover_id, payload, headers=None):
        return self._request("POST", f"/rollout/turnovers/{turnover_id}/accept", payload, headers)

    def reject_turnover(self, turnover_id, payload, headers=None):
        return self._request("POST", f"/rollout/turnovers/{turnover_id}/reject", payload, headers)

    # --- OpeningCommitment ---
    def list_opening_commitments(self, headers=None, params=None):
        return self._request("GET", "/rollout/opening-commitments", headers=headers, params=params)

    def get_opening_commitment(self, commitment_id, headers=None):
        return self._request("GET", f"/rollout/opening-commitments/{commitment_id}", headers=headers)

    def recalculate_opening_commitment(self, commitment_id, headers=None):
        return self._request("POST", f"/rollout/opening-commitments/{commitment_id}/recalculate", {}, headers)


api_client = ApiClient()
