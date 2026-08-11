"""API client: one method per endpoint of the Community-Supported Fishery service."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Seasons ─────────────────────────────────────────────────────────────
    def create_season(self, payload, headers):
        return self._request("POST", "/csf/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/csf/seasons/{season_id}", headers=headers)

    def open_season(self, season_id, headers, payload=None):
        return self._request("POST", f"/csf/seasons/{season_id}/open", payload or {}, headers)

    def close_landings(self, season_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/seasons/{season_id}/close-landings", payload or {}, headers
        )

    def run_true_up(self, season_id, headers, payload=None):
        return self._request("POST", f"/csf/seasons/{season_id}/true-up", payload or {}, headers)

    # ─── Share plans ─────────────────────────────────────────────────────────
    def create_share_plan(self, payload, headers):
        return self._request("POST", "/csf/share-plans", payload, headers)

    def get_share_plan(self, plan_id, headers):
        return self._request("GET", f"/csf/share-plans/{plan_id}", headers=headers)

    def list_share_plans(self, headers, params=None):
        return self._request("GET", "/csf/share-plans", params, headers)

    # ─── Delivery zones and pickup hubs ──────────────────────────────────────
    def create_delivery_zone(self, payload, headers):
        return self._request("POST", "/csf/delivery-zones", payload, headers)

    def create_pickup_hub(self, payload, headers):
        return self._request("POST", "/csf/pickup-hubs", payload, headers)

    def create_pickup_window(self, hub_id, payload, headers):
        return self._request("POST", f"/csf/pickup-hubs/{hub_id}/windows", payload, headers)

    def get_pickup_window(self, window_id, headers):
        return self._request("GET", f"/csf/pickup-windows/{window_id}", headers=headers)

    def list_pickup_windows(self, headers, params=None):
        return self._request("GET", "/csf/pickup-windows", params, headers)

    def open_pickup_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/pickup-windows/{window_id}/open", payload or {}, headers
        )

    def close_pickup_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/pickup-windows/{window_id}/close", payload or {}, headers
        )

    # ─── Members ─────────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/csf/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/csf/members/{member_id}", headers=headers)

    def update_member_preferences(self, member_id, payload, headers):
        return self._request("PATCH", f"/csf/members/{member_id}/preferences", payload, headers)

    # ─── Subscriptions ───────────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/csf/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/csf/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/csf/subscriptions", params, headers)

    def activate_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/subscriptions/{subscription_id}/activate", payload or {}, headers
        )

    def pause_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/subscriptions/{subscription_id}/pause", payload or {}, headers
        )

    def resume_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/subscriptions/{subscription_id}/resume", payload or {}, headers
        )

    def cancel_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/subscriptions/{subscription_id}/cancel", payload or {}, headers
        )

    def record_payment(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/csf/subscriptions/{subscription_id}/payments", payload, headers
        )

    def get_subscription_ledger(self, subscription_id, headers):
        return self._request(
            "GET", f"/csf/subscriptions/{subscription_id}/ledger", headers=headers
        )

    # ─── Vessels and quota ledgers ───────────────────────────────────────────
    def create_vessel(self, payload, headers):
        return self._request("POST", "/csf/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/csf/vessels/{vessel_id}", headers=headers)

    def set_vessel_compliance(self, vessel_id, payload, headers):
        return self._request("POST", f"/csf/vessels/{vessel_id}/compliance", payload, headers)

    def create_quota_ledger(self, payload, headers):
        return self._request("POST", "/csf/quota-ledgers", payload, headers)

    def get_quota_ledger(self, ledger_id, headers):
        return self._request("GET", f"/csf/quota-ledgers/{ledger_id}", headers=headers)

    def list_quota_ledgers(self, headers, params=None):
        return self._request("GET", "/csf/quota-ledgers", params, headers)

    # ─── Trips, landings and settlements ─────────────────────────────────────
    def create_trip(self, payload, headers):
        return self._request("POST", "/csf/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/csf/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/csf/trips", params, headers)

    def record_landing(self, trip_id, payload, headers):
        return self._request("POST", f"/csf/trips/{trip_id}/land", payload, headers)

    def verify_landing(self, trip_id, payload, headers):
        return self._request("POST", f"/csf/trips/{trip_id}/verify", payload, headers)

    def create_settlement(self, trip_id, payload, headers):
        return self._request("POST", f"/csf/trips/{trip_id}/settlements", payload, headers)

    # ─── Landing lots and sub-lots ───────────────────────────────────────────
    def get_landing_lot(self, lot_id, headers):
        return self._request("GET", f"/csf/landing-lots/{lot_id}", headers=headers)

    def list_landing_lots(self, headers, params=None):
        return self._request("GET", "/csf/landing-lots", params, headers)

    def run_allocation(self, lot_id, payload, headers):
        return self._request("POST", f"/csf/landing-lots/{lot_id}/allocations", payload, headers)

    def split_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/csf/landing-lots/{lot_id}/splits", payload, headers)

    def disposition_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/csf/landing-lots/{lot_id}/disposition", payload, headers)

    def get_sub_lot(self, sub_lot_id, headers):
        return self._request("GET", f"/csf/sub-lots/{sub_lot_id}", headers=headers)

    def list_sub_lots(self, headers, params=None):
        return self._request("GET", "/csf/sub-lots", params, headers)

    def arrive_sub_lot(self, sub_lot_id, headers, payload=None):
        return self._request("POST", f"/csf/sub-lots/{sub_lot_id}/arrive", payload or {}, headers)

    # ─── Share deliveries ────────────────────────────────────────────────────
    def get_share_delivery(self, delivery_id, headers):
        return self._request("GET", f"/csf/share-deliveries/{delivery_id}", headers=headers)

    def list_share_deliveries(self, headers, params=None):
        return self._request("GET", "/csf/share-deliveries", params, headers)

    def pack_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/share-deliveries/{delivery_id}/pack", payload or {}, headers
        )

    def dispatch_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/share-deliveries/{delivery_id}/dispatch", payload or {}, headers
        )

    def complete_delivery(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/share-deliveries/{delivery_id}/deliver", payload or {}, headers
        )

    def stage_at_hub(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/csf/share-deliveries/{delivery_id}/stage-at-hub", payload, headers
        )

    def record_pickup(self, delivery_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/share-deliveries/{delivery_id}/pickup", payload or {}, headers
        )

    def propose_substitution(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/csf/share-deliveries/{delivery_id}/substitutions", payload, headers
        )

    # ─── Substitution offers ─────────────────────────────────────────────────
    def get_substitution(self, substitution_id, headers):
        return self._request(
            "GET", f"/csf/substitution-events/{substitution_id}", headers=headers
        )

    def list_substitutions(self, headers, params=None):
        return self._request("GET", "/csf/substitution-events", params, headers)

    def accept_substitution(self, substitution_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/substitution-events/{substitution_id}/accept", payload or {}, headers
        )

    def reject_substitution(self, substitution_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/substitution-events/{substitution_id}/reject", payload or {}, headers
        )

    # ─── Cold chain ──────────────────────────────────────────────────────────
    def log_cold_chain_event(self, payload, headers):
        return self._request("POST", "/csf/cold-chain-events", payload, headers)

    def get_cold_chain_event(self, event_id, headers):
        return self._request("GET", f"/csf/cold-chain-events/{event_id}", headers=headers)

    def list_cold_chain_events(self, headers, params=None):
        return self._request("GET", "/csf/cold-chain-events", params, headers)

    # ─── Skips ───────────────────────────────────────────────────────────────
    def create_skip_request(self, payload, headers):
        return self._request("POST", "/csf/skip-requests", payload, headers)

    def get_skip_request(self, skip_id, headers):
        return self._request("GET", f"/csf/skip-requests/{skip_id}", headers=headers)

    def list_skip_requests(self, headers, params=None):
        return self._request("GET", "/csf/skip-requests", params, headers)

    def revoke_skip_request(self, skip_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/skip-requests/{skip_id}/revoke", payload or {}, headers
        )

    # ─── Settlement statements ───────────────────────────────────────────────
    def get_settlement(self, statement_id, headers):
        return self._request(
            "GET", f"/csf/settlement-statements/{statement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/csf/settlement-statements", params, headers)

    def finalize_settlement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/settlement-statements/{statement_id}/finalize", payload or {}, headers
        )

    def pay_settlement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/settlement-statements/{statement_id}/pay", payload or {}, headers
        )

    # ─── Share transfers ─────────────────────────────────────────────────────
    def create_share_transfer(self, payload, headers):
        return self._request("POST", "/csf/share-transfers", payload, headers)

    def get_share_transfer(self, transfer_id, headers):
        return self._request("GET", f"/csf/share-transfers/{transfer_id}", headers=headers)

    def list_share_transfers(self, headers, params=None):
        return self._request("GET", "/csf/share-transfers", params, headers)

    def accept_share_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/share-transfers/{transfer_id}/accept", payload or {}, headers
        )

    def decline_share_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/share-transfers/{transfer_id}/decline", payload or {}, headers
        )

    # ─── Recall notices ──────────────────────────────────────────────────────
    def create_recall_notice(self, payload, headers):
        return self._request("POST", "/csf/recall-notices", payload, headers)

    def get_recall_notice(self, recall_id, headers):
        return self._request("GET", f"/csf/recall-notices/{recall_id}", headers=headers)

    def list_recall_notices(self, headers, params=None):
        return self._request("GET", "/csf/recall-notices", params, headers)

    def remediate_recall_notice(self, recall_id, headers, payload=None):
        return self._request(
            "POST", f"/csf/recall-notices/{recall_id}/remediate", payload or {}, headers
        )

    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/csf/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
