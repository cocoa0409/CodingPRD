"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Community ---
    def create_community(self, payload, headers):
        return self._request("POST", "/homebuilder/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request(
            "GET", f"/homebuilder/communities/{community_id}", headers=headers
        )

    def open_community_sales(self, community_id, headers):
        return self._request(
            "POST", f"/homebuilder/communities/{community_id}/open-sales", {}, headers
        )

    # --- PricePhase ---
    def create_price_phase(self, payload, headers):
        return self._request("POST", "/homebuilder/price-phases", payload, headers)

    def list_price_phases(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/homebuilder/communities/{community_id}/price-phases",
            headers=headers,
            params=params,
        )

    # --- HomePlan ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/homebuilder/plans", payload, headers)

    def list_plans(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/homebuilder/communities/{community_id}/plans",
            headers=headers,
            params=params,
        )

    # --- OptionCatalogItem ---
    def create_option_catalog_item(self, payload, headers):
        return self._request(
            "POST", "/homebuilder/option-catalog-items", payload, headers
        )

    def list_option_catalog_items(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/homebuilder/communities/{community_id}/option-catalog-items",
            headers=headers,
            params=params,
        )

    # --- Lot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/homebuilder/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/homebuilder/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/homebuilder/lots/{lot_id}", headers=headers)

    def release_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/homebuilder/lots/{lot_id}/release", {}, headers
        )

    def reserve_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/homebuilder/lots/{lot_id}/reserve", payload, headers
        )

    def release_lot_reservation(self, lot_id, headers):
        return self._request(
            "POST", f"/homebuilder/lots/{lot_id}/release-reservation", {}, headers
        )

    # --- Buyer ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/homebuilder/buyers", payload, headers)

    # --- PurchaseAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/homebuilder/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/homebuilder/agreements", headers=headers, params=params
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/homebuilder/agreements/{agreement_id}", headers=headers
        )

    def sign_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/homebuilder/agreements/{agreement_id}/sign", {}, headers
        )

    def clear_contingency(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/homebuilder/agreements/{agreement_id}/contingency-clearance",
            payload,
            headers,
        )

    def cancel_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/homebuilder/agreements/{agreement_id}/cancel", payload, headers
        )

    def close_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/homebuilder/agreements/{agreement_id}/close", {}, headers
        )

    def acknowledge_warranty(self, agreement_id, headers):
        return self._request(
            "POST",
            f"/homebuilder/agreements/{agreement_id}/acknowledge-warranty",
            {},
            headers,
        )

    # --- OptionSelection ---
    def create_option_selection(self, payload, headers):
        return self._request("POST", "/homebuilder/option-selections", payload, headers)

    def list_option_selections(self, headers, params=None):
        return self._request(
            "GET", "/homebuilder/option-selections", headers=headers, params=params
        )

    def get_option_selection(self, selection_id, headers):
        return self._request(
            "GET", f"/homebuilder/option-selections/{selection_id}", headers=headers
        )

    def confirm_selection(self, selection_id, headers):
        return self._request(
            "POST", f"/homebuilder/option-selections/{selection_id}/confirm", {}, headers
        )

    def unconfirm_selection(self, selection_id, headers):
        return self._request(
            "POST",
            f"/homebuilder/option-selections/{selection_id}/unconfirm",
            {},
            headers,
        )

    def cancel_selection(self, selection_id, headers):
        return self._request(
            "POST", f"/homebuilder/option-selections/{selection_id}/cancel", {}, headers
        )

    # --- ConstructionMilestone ---
    def list_milestones(self, headers, params=None):
        return self._request(
            "GET", "/homebuilder/milestones", headers=headers, params=params
        )

    def get_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/homebuilder/milestones/{milestone_id}", headers=headers
        )

    def complete_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/homebuilder/milestones/{milestone_id}/complete", {}, headers
        )

    # --- IncentiveRequest ---
    def create_incentive_request(self, payload, headers):
        return self._request(
            "POST", "/homebuilder/incentive-requests", payload, headers
        )

    def list_incentive_requests(self, headers, params=None):
        return self._request(
            "GET", "/homebuilder/incentive-requests", headers=headers, params=params
        )

    def get_incentive_request(self, request_id, headers):
        return self._request(
            "GET", f"/homebuilder/incentive-requests/{request_id}", headers=headers
        )

    def decide_incentive_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/homebuilder/incentive-requests/{request_id}/decide",
            payload,
            headers,
        )

    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
