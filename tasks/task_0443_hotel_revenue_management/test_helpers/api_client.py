"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property_kpis(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}/kpis", headers=headers)

    # --- RoomType ---
    def create_room_type(self, payload, headers):
        return self._request("POST", "/room-types", payload, headers)

    def get_room_type(self, room_type_id, headers):
        return self._request("GET", f"/room-types/{room_type_id}", headers=headers)

    def list_room_types(self, headers, params=None):
        return self._request("GET", "/room-types", headers=headers, params=params)

    # --- RatePlan ---
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/rate-plans", payload, headers)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/rate-plans/{rate_plan_id}", headers=headers)

    def list_rate_plans(self, headers, params=None):
        return self._request("GET", "/rate-plans", headers=headers, params=params)

    def close_rate_plan(self, rate_plan_id, headers):
        return self._request(
            "POST", f"/rate-plans/{rate_plan_id}/close", headers=headers
        )

    # --- InventoryDay ---
    def create_inventory_day(self, payload, headers):
        return self._request("POST", "/inventory-days", payload, headers)

    def get_inventory_day(self, inventory_day_id, headers):
        return self._request(
            "GET", f"/inventory-days/{inventory_day_id}", headers=headers
        )

    def list_inventory_days(self, headers, params=None):
        return self._request("GET", "/inventory-days", headers=headers, params=params)

    def update_inventory_day(self, inventory_day_id, payload, headers):
        return self._request(
            "PATCH", f"/inventory-days/{inventory_day_id}", payload, headers
        )

    def forecast_inventory_day(self, inventory_day_id, headers, params=None):
        return self._request(
            "GET",
            f"/inventory-days/{inventory_day_id}/forecast",
            headers=headers,
            params=params,
        )

    # --- YieldRule ---
    def create_yield_rule(self, payload, headers):
        return self._request("POST", "/yield-rules", payload, headers)

    def get_yield_rule(self, yield_rule_id, headers):
        return self._request("GET", f"/yield-rules/{yield_rule_id}", headers=headers)

    def list_yield_rules(self, headers, params=None):
        return self._request("GET", "/yield-rules", headers=headers, params=params)

    # --- RateDecision ---
    def create_rate_decision(self, payload, headers):
        return self._request("POST", "/rate-decisions", payload, headers)

    def get_rate_decision(self, rate_decision_id, headers):
        return self._request(
            "GET", f"/rate-decisions/{rate_decision_id}", headers=headers
        )

    def list_rate_decisions(self, headers, params=None):
        return self._request("GET", "/rate-decisions", headers=headers, params=params)

    def publish_rate_decision(self, rate_decision_id, payload, headers):
        return self._request(
            "POST", f"/rate-decisions/{rate_decision_id}/publish", payload, headers
        )

    def reject_rate_decision(self, rate_decision_id, payload, headers):
        return self._request(
            "POST", f"/rate-decisions/{rate_decision_id}/reject", payload, headers
        )

    # --- ChannelMapping ---
    def create_channel_mapping(self, payload, headers):
        return self._request("POST", "/channel-mappings", payload, headers)

    def get_channel_mapping(self, channel_mapping_id, headers):
        return self._request(
            "GET", f"/channel-mappings/{channel_mapping_id}", headers=headers
        )

    def list_channel_mappings(self, headers, params=None):
        return self._request(
            "GET", "/channel-mappings", headers=headers, params=params
        )

    def update_channel_mapping(self, channel_mapping_id, payload, headers):
        return self._request(
            "PATCH", f"/channel-mappings/{channel_mapping_id}", payload, headers
        )

    # --- GroupBlock ---
    def create_group_block(self, payload, headers):
        return self._request("POST", "/group-blocks", payload, headers)

    def get_group_block(self, group_block_id, headers):
        return self._request("GET", f"/group-blocks/{group_block_id}", headers=headers)

    def list_group_blocks(self, headers, params=None):
        return self._request("GET", "/group-blocks", headers=headers, params=params)

    def revise_group_block(self, group_block_id, payload, headers):
        return self._request(
            "PATCH", f"/group-blocks/{group_block_id}", payload, headers
        )

    def evaluate_group_block(self, group_block_id, payload, headers):
        # PRD §3.7: the displacement analysis "accepts a `method` query
        # parameter" — so the method selector travels in the query string, not
        # the JSON body. `payload` here is {"method": ...}.
        return self._request(
            "POST",
            f"/group-blocks/{group_block_id}/evaluate",
            headers=headers,
            params=payload,
        )

    def request_revision_group_block(self, group_block_id, headers):
        return self._request(
            "POST", f"/group-blocks/{group_block_id}/request-revision", headers=headers
        )

    def commit_group_block(self, group_block_id, payload, headers):
        return self._request(
            "POST", f"/group-blocks/{group_block_id}/commit", payload, headers
        )

    def cancel_group_block(self, group_block_id, headers):
        return self._request(
            "POST", f"/group-blocks/{group_block_id}/cancel", headers=headers
        )

    # --- CompetitorRate ---
    def create_competitor_rate(self, payload, headers):
        return self._request("POST", "/competitor-rates", payload, headers)

    def get_competitor_rate(self, competitor_rate_id, headers):
        return self._request(
            "GET", f"/competitor-rates/{competitor_rate_id}", headers=headers
        )

    def list_competitor_rates(self, headers, params=None):
        return self._request(
            "GET", "/competitor-rates", headers=headers, params=params
        )

    # --- TransientReservation ---
    def create_transient_reservation(self, payload, headers):
        return self._request("POST", "/transient-reservations", payload, headers)

    def get_transient_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/transient-reservations/{reservation_id}", headers=headers
        )

    def list_transient_reservations(self, headers, params=None):
        return self._request(
            "GET", "/transient-reservations", headers=headers, params=params
        )

    def confirm_transient_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/transient-reservations/{reservation_id}/confirm", headers=headers
        )

    def check_out_transient_reservation(self, reservation_id, headers):
        return self._request(
            "POST",
            f"/transient-reservations/{reservation_id}/check-out",
            headers=headers,
        )

    def cancel_transient_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/transient-reservations/{reservation_id}/cancel", headers=headers
        )


api_client = ApiClient()
