"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the /jansan URL prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and daily ops checkpoint
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/jansan/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily_ops(self, headers):
        return self._request("POST", "/jansan/ops/run-daily", {}, headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/jansan/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/jansan/facilities/{facility_id}",
                             headers=headers)

    def suspend_facility(self, facility_id, headers):
        return self._request("POST", f"/jansan/facilities/{facility_id}/suspend",
                             {}, headers)

    def reinstate_facility(self, facility_id, headers):
        return self._request("POST", f"/jansan/facilities/{facility_id}/reinstate",
                             {}, headers)

    def archive_facility(self, facility_id, headers):
        return self._request("POST", f"/jansan/facilities/{facility_id}/archive",
                             {}, headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/jansan/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/jansan/products/{product_id}",
                             headers=headers)

    def declare_shortage(self, product_id, headers):
        return self._request("POST",
                             f"/jansan/products/{product_id}/declare-shortage",
                             {}, headers)

    def resolve_shortage(self, product_id, headers):
        return self._request("POST",
                             f"/jansan/products/{product_id}/resolve-shortage",
                             {}, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST",
                             f"/jansan/products/{product_id}/discontinue",
                             {}, headers)

    # ------------------------------------------------------------------
    # Usage records
    # ------------------------------------------------------------------
    def create_usage_record(self, payload, headers):
        return self._request("POST", "/jansan/usage-records", payload, headers)

    def get_usage_record(self, usage_record_id, headers):
        return self._request("GET", f"/jansan/usage-records/{usage_record_id}",
                             headers=headers)

    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/jansan/usage-records", headers=headers,
                             params=params)

    def post_usage_record(self, usage_record_id, headers):
        return self._request("POST",
                             f"/jansan/usage-records/{usage_record_id}/post",
                             {}, headers)

    # ------------------------------------------------------------------
    # Forecast profiles
    # ------------------------------------------------------------------
    def create_forecast_profile(self, payload, headers):
        return self._request("POST", "/jansan/forecast-profiles", payload, headers)

    def get_forecast_profile(self, forecast_profile_id, headers):
        return self._request(
            "GET", f"/jansan/forecast-profiles/{forecast_profile_id}",
            headers=headers)

    def list_forecast_profiles(self, headers, params=None):
        return self._request("GET", "/jansan/forecast-profiles", headers=headers,
                             params=params)

    def patch_forecast_profile(self, forecast_profile_id, payload, headers):
        return self._request(
            "PATCH", f"/jansan/forecast-profiles/{forecast_profile_id}",
            payload, headers)

    def recompute_forecast_profile(self, forecast_profile_id, variant, headers):
        return self._request(
            "POST", f"/jansan/forecast-profiles/{forecast_profile_id}/recompute",
            {"variant": variant}, headers)

    # ------------------------------------------------------------------
    # Technicians
    # ------------------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/jansan/technicians", payload, headers)

    # ------------------------------------------------------------------
    # Dispensers
    # ------------------------------------------------------------------
    def create_dispenser(self, payload, headers):
        return self._request("POST", "/jansan/dispensers", payload, headers)

    def get_dispenser(self, dispenser_id, headers):
        return self._request("GET", f"/jansan/dispensers/{dispenser_id}",
                             headers=headers)

    def list_dispensers(self, headers, params=None):
        return self._request("GET", "/jansan/dispensers", headers=headers,
                             params=params)

    def complete_dispenser(self, dispenser_id, headers):
        return self._request("POST",
                             f"/jansan/dispensers/{dispenser_id}/complete",
                             {}, headers)

    def decommission_dispenser(self, dispenser_id, headers):
        return self._request("POST",
                             f"/jansan/dispensers/{dispenser_id}/decommission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Training records
    # ------------------------------------------------------------------
    def create_training_record(self, payload, headers):
        return self._request("POST", "/jansan/training-records", payload, headers)

    def get_training_record(self, training_record_id, headers):
        return self._request("GET",
                             f"/jansan/training-records/{training_record_id}",
                             headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/jansan/training-records", headers=headers,
                             params=params)

    def certify_training_record(self, training_record_id, score_pct, headers):
        return self._request(
            "POST", f"/jansan/training-records/{training_record_id}/certify",
            {"score_pct": score_pct}, headers)

    # ------------------------------------------------------------------
    # Standing orders
    # ------------------------------------------------------------------
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/jansan/standing-orders", payload, headers)

    def get_standing_order(self, standing_order_id, headers):
        return self._request("GET",
                             f"/jansan/standing-orders/{standing_order_id}",
                             headers=headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/jansan/standing-orders", headers=headers,
                             params=params)

    def activate_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/jansan/standing-orders/{standing_order_id}/activate",
            {}, headers)

    def pause_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/jansan/standing-orders/{standing_order_id}/pause",
            {}, headers)

    def resume_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/jansan/standing-orders/{standing_order_id}/resume",
            {}, headers)

    def cancel_standing_order(self, standing_order_id, headers):
        return self._request(
            "POST", f"/jansan/standing-orders/{standing_order_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/jansan/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/jansan/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/jansan/orders", headers=headers,
                             params=params)

    def place_order(self, order_id, headers):
        return self._request("POST", f"/jansan/orders/{order_id}/place",
                             {}, headers)

    def confirm_delivery(self, order_id, fuel_index_at_delivery, headers):
        return self._request(
            "POST", f"/jansan/orders/{order_id}/confirm-delivery",
            {"fuel_index_at_delivery": fuel_index_at_delivery}, headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/jansan/orders/{order_id}/invoice",
                             {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/jansan/orders/{order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Order lines
    # ------------------------------------------------------------------
    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/jansan/order-lines/{order_line_id}",
                             headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/jansan/order-lines", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Substitution proposals
    # ------------------------------------------------------------------
    def get_substitution_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"/jansan/substitution-proposals/{proposal_id}",
            headers=headers)

    def list_substitution_proposals(self, headers, params=None):
        return self._request("GET", "/jansan/substitution-proposals",
                             headers=headers, params=params)

    def accept_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/jansan/substitution-proposals/{proposal_id}/accept",
            {}, headers)

    def decline_proposal(self, proposal_id, headers):
        return self._request(
            "POST", f"/jansan/substitution-proposals/{proposal_id}/decline",
            {}, headers)

    # ------------------------------------------------------------------
    # Contract bids
    # ------------------------------------------------------------------
    def create_contract_bid(self, payload, headers):
        return self._request("POST", "/jansan/contract-bids", payload, headers)

    def get_contract_bid(self, bid_id, headers):
        return self._request("GET", f"/jansan/contract-bids/{bid_id}",
                             headers=headers)

    def list_contract_bids(self, headers, params=None):
        return self._request("GET", "/jansan/contract-bids", headers=headers,
                             params=params)

    def submit_bid(self, bid_id, headers):
        return self._request("POST", f"/jansan/contract-bids/{bid_id}/submit",
                             {}, headers)

    def open_review_bid(self, bid_id, headers):
        return self._request("POST",
                             f"/jansan/contract-bids/{bid_id}/open-review",
                             {}, headers)

    def return_bid_for_revision(self, bid_id, headers):
        return self._request(
            "POST", f"/jansan/contract-bids/{bid_id}/return-for-revision",
            {}, headers)

    def award_bid(self, bid_id, headers):
        return self._request("POST", f"/jansan/contract-bids/{bid_id}/award",
                             {}, headers)

    def mark_bid_lost(self, bid_id, headers):
        return self._request("POST", f"/jansan/contract-bids/{bid_id}/mark-lost",
                             {}, headers)

    def terminate_bid(self, bid_id, headers):
        return self._request("POST",
                             f"/jansan/contract-bids/{bid_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Trial programs
    # ------------------------------------------------------------------
    def create_trial_program(self, payload, headers):
        return self._request("POST", "/jansan/trial-programs", payload, headers)

    def get_trial_program(self, trial_program_id, headers):
        return self._request("GET", f"/jansan/trial-programs/{trial_program_id}",
                             headers=headers)

    def list_trial_programs(self, headers, params=None):
        return self._request("GET", "/jansan/trial-programs", headers=headers,
                             params=params)

    def convert_trial(self, trial_program_id, qty, delivery_date, fuel_index,
                      headers):
        return self._request(
            "POST", f"/jansan/trial-programs/{trial_program_id}/convert",
            {"qty": qty, "delivery_date": delivery_date,
             "fuel_index": fuel_index}, headers)


api_client = ApiClient()
