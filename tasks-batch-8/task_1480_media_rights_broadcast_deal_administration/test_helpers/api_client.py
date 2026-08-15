"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Rights assets ---
    def create_rights_asset(self, payload, headers):
        return self._request("POST", "/rights-assets", payload, headers)

    def list_rights_assets(self, headers, params=None):
        return self._request("GET", "/rights-assets", headers=headers, params=params)

    def get_rights_asset(self, asset_id, headers):
        return self._request("GET", f"/rights-assets/{asset_id}", headers=headers)

    def lock_packages(self, asset_id, headers):
        return self._request(
            "POST", f"/rights-assets/{asset_id}/lock-packages", {}, headers
        )

    def close_awards(self, asset_id, headers):
        return self._request(
            "POST", f"/rights-assets/{asset_id}/close-awards", {}, headers
        )

    def retire_asset(self, asset_id, headers):
        return self._request("POST", f"/rights-assets/{asset_id}/retire", {}, headers)

    # --- Broadcasters ---
    def create_broadcaster(self, payload, headers):
        return self._request("POST", "/broadcasters", payload, headers)

    def list_broadcasters(self, headers, params=None):
        return self._request("GET", "/broadcasters", headers=headers, params=params)

    def get_broadcaster(self, broadcaster_id, headers):
        return self._request("GET", f"/broadcasters/{broadcaster_id}", headers=headers)

    def accredit_broadcaster(self, broadcaster_id, headers):
        return self._request(
            "POST", f"/broadcasters/{broadcaster_id}/accredit", {}, headers
        )

    def suspend_broadcaster(self, broadcaster_id, headers):
        return self._request(
            "POST", f"/broadcasters/{broadcaster_id}/suspend", {}, headers
        )

    def reinstate_broadcaster(self, broadcaster_id, headers):
        return self._request(
            "POST", f"/broadcasters/{broadcaster_id}/reinstate", {}, headers
        )

    def bar_broadcaster(self, broadcaster_id, headers):
        return self._request("POST", f"/broadcasters/{broadcaster_id}/bar", {}, headers)

    # --- Packages ---
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def withdraw_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/withdraw", {}, headers)

    # --- Bids (nested) ---
    def create_bid(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/bids", payload, headers)

    def list_bids(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/packages/{package_id}/bids", headers=headers, params=params
        )

    def get_bid(self, package_id, bid_id, headers):
        return self._request(
            "GET", f"/packages/{package_id}/bids/{bid_id}", headers=headers
        )

    def submit_bid(self, package_id, bid_id, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/submit", {}, headers
        )

    def start_review_bid(self, package_id, bid_id, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/start-review", {}, headers
        )

    def shortlist_bid(self, package_id, bid_id, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/shortlist", {}, headers
        )

    def counter_bid(self, package_id, bid_id, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/counter", {}, headers
        )

    def reject_bid(self, package_id, bid_id, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/reject", {}, headers
        )

    def withdraw_bid(self, package_id, bid_id, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/withdraw", {}, headers
        )

    def accept_bid(self, package_id, bid_id, payload, headers):
        return self._request(
            "POST", f"/packages/{package_id}/bids/{bid_id}/accept", payload, headers
        )

    # --- Bids (flat anchors) ---
    def list_all_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid_flat(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    # --- Deals ---
    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def execute_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/execute", payload, headers)

    def open_renewal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/open-renewal", {}, headers)

    def terminate_breach(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/terminate-breach", {}, headers)

    def terminate_convenience(self, deal_id, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/terminate-convenience", {}, headers
        )

    # --- Payment milestones ---
    def create_payment_milestone(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/payment-milestones", payload, headers
        )

    def list_payment_milestones(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/payment-milestones", headers=headers, params=params
        )

    def get_payment_milestone(self, deal_id, milestone_id, headers):
        return self._request(
            "GET",
            f"/deals/{deal_id}/payment-milestones/{milestone_id}",
            headers=headers,
        )

    def invoice_milestone(self, deal_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/payment-milestones/{milestone_id}/invoice",
            {},
            headers,
        )

    def record_payment(self, deal_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/payment-milestones/{milestone_id}/record-payment",
            {},
            headers,
        )

    def declare_default(self, deal_id, milestone_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/payment-milestones/{milestone_id}/declare-default",
            {},
            headers,
        )

    def list_all_payment_milestones(self, headers, params=None):
        return self._request("GET", "/payment-milestones", headers=headers, params=params)

    def get_payment_milestone_flat(self, milestone_id, headers):
        return self._request(
            "GET", f"/payment-milestones/{milestone_id}", headers=headers
        )

    # --- Production obligations ---
    def create_production_obligation(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/production-obligations", payload, headers
        )

    def list_production_obligations(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/deals/{deal_id}/production-obligations",
            headers=headers,
            params=params,
        )

    def get_production_obligation(self, deal_id, obligation_id, headers):
        return self._request(
            "GET",
            f"/deals/{deal_id}/production-obligations/{obligation_id}",
            headers=headers,
        )

    def declare_shortfall(self, deal_id, obligation_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/production-obligations/{obligation_id}/declare-shortfall",
            {},
            headers,
        )

    def apply_remedy(self, deal_id, obligation_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/production-obligations/{obligation_id}/apply-remedy",
            {},
            headers,
        )

    def forgive_credit(self, deal_id, obligation_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/production-obligations/{obligation_id}/forgive-credit",
            {},
            headers,
        )

    def list_all_production_obligations(self, headers, params=None):
        return self._request(
            "GET", "/production-obligations", headers=headers, params=params
        )

    def get_production_obligation_flat(self, obligation_id, headers):
        return self._request(
            "GET", f"/production-obligations/{obligation_id}", headers=headers
        )

    # --- Broadcast events ---
    def create_broadcast_event(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/broadcast-events", payload, headers
        )

    def list_broadcast_events(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/broadcast-events", headers=headers, params=params
        )

    def get_broadcast_event(self, deal_id, event_id, headers):
        return self._request(
            "GET", f"/deals/{deal_id}/broadcast-events/{event_id}", headers=headers
        )

    def mark_delivered(self, deal_id, event_id, payload, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/broadcast-events/{event_id}/mark-delivered",
            payload,
            headers,
        )

    def mark_no_show(self, deal_id, event_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/broadcast-events/{event_id}/mark-no-show",
            {},
            headers,
        )

    def cancel_by_league(self, deal_id, event_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/broadcast-events/{event_id}/cancel-by-league",
            {},
            headers,
        )

    def cancel_by_broadcaster(self, deal_id, event_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/broadcast-events/{event_id}/cancel-by-broadcaster",
            {},
            headers,
        )

    def list_all_broadcast_events(self, headers, params=None):
        return self._request("GET", "/broadcast-events", headers=headers, params=params)

    def get_broadcast_event_flat(self, event_id, headers):
        return self._request("GET", f"/broadcast-events/{event_id}", headers=headers)

    # --- Audience measurements ---
    def create_audience_measurement(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/audience-measurements", payload, headers
        )

    def list_audience_measurements(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/deals/{deal_id}/audience-measurements",
            headers=headers,
            params=params,
        )

    def get_audience_measurement(self, deal_id, measurement_id, headers):
        return self._request(
            "GET",
            f"/deals/{deal_id}/audience-measurements/{measurement_id}",
            headers=headers,
        )

    def confirm_measurement(self, deal_id, measurement_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/audience-measurements/{measurement_id}/confirm",
            {},
            headers,
        )

    def dispute_measurement(self, deal_id, measurement_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/audience-measurements/{measurement_id}/dispute",
            {},
            headers,
        )

    def exclude_measurement(self, deal_id, measurement_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/audience-measurements/{measurement_id}/exclude",
            {},
            headers,
        )

    def list_all_audience_measurements(self, headers, params=None):
        return self._request(
            "GET", "/audience-measurements", headers=headers, params=params
        )

    def get_audience_measurement_flat(self, measurement_id, headers):
        return self._request(
            "GET", f"/audience-measurements/{measurement_id}", headers=headers
        )

    # --- Sublicense requests ---
    def create_sublicense_request(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/sublicense-requests", payload, headers
        )

    def list_sublicense_requests(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/sublicense-requests", headers=headers, params=params
        )

    def get_sublicense_request(self, deal_id, request_id, headers):
        return self._request(
            "GET", f"/deals/{deal_id}/sublicense-requests/{request_id}", headers=headers
        )

    def approve_sublicense(self, deal_id, request_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/sublicense-requests/{request_id}/approve",
            {},
            headers,
        )

    def reject_sublicense(self, deal_id, request_id, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/sublicense-requests/{request_id}/reject",
            {},
            headers,
        )

    def revoke_sublicense(self, deal_id, request_id, payload, headers):
        return self._request(
            "POST",
            f"/deals/{deal_id}/sublicense-requests/{request_id}/revoke",
            payload,
            headers,
        )

    def list_all_sublicense_requests(self, headers, params=None):
        return self._request(
            "GET", "/sublicense-requests", headers=headers, params=params
        )

    def get_sublicense_request_flat(self, request_id, headers):
        return self._request("GET", f"/sublicense-requests/{request_id}", headers=headers)

    # --- Blackout windows ---
    def create_blackout_window(self, payload, headers):
        return self._request("POST", "/blackout-windows", payload, headers)

    def list_blackout_windows(self, headers, params=None):
        return self._request("GET", "/blackout-windows", headers=headers, params=params)

    def get_blackout_window(self, window_id, headers):
        return self._request("GET", f"/blackout-windows/{window_id}", headers=headers)

    # --- Renewal offers ---
    def create_renewal_offer(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/renewal-offers", payload, headers)

    def list_renewal_offers(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/renewal-offers", headers=headers, params=params
        )

    def get_renewal_offer(self, deal_id, offer_id, headers):
        return self._request(
            "GET", f"/deals/{deal_id}/renewal-offers/{offer_id}", headers=headers
        )

    def match_renewal_offer(self, deal_id, offer_id, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/renewal-offers/{offer_id}/match", {}, headers
        )

    def exercise_renewal_offer(self, deal_id, offer_id, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/renewal-offers/{offer_id}/exercise", {}, headers
        )

    def withdraw_renewal_offer(self, deal_id, offer_id, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/renewal-offers/{offer_id}/withdraw", {}, headers
        )

    def list_all_renewal_offers(self, headers, params=None):
        return self._request("GET", "/renewal-offers", headers=headers, params=params)

    def get_renewal_offer_flat(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)

    # --- Rights conflicts (append-only monitor) ---
    def list_rights_conflicts(self, headers, params=None):
        return self._request("GET", "/rights-conflicts", headers=headers, params=params)

    def get_rights_conflict(self, conflict_id, headers):
        return self._request("GET", f"/rights-conflicts/{conflict_id}", headers=headers)


api_client = ApiClient()
