"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Test harness (PRD §3.9 logical clock)
    # =======================================================================
    def advance_clock(self, seconds: int, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"seconds": seconds}, headers,
        )

    # =======================================================================
    # Advertisers (PRD §3.1)
    # =======================================================================
    def create_advertiser(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/advertisers", payload, headers)

    def list_advertisers(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/advertisers", headers=headers, params=params,
        )

    def get_advertiser(self, advertiser_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/advertisers/{advertiser_id}", headers=headers,
        )

    def update_advertiser(self, advertiser_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PUT", f"/advertisers/{advertiser_id}", payload, headers,
        )

    def suspend_advertiser(self, advertiser_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/advertisers/{advertiser_id}/suspend", {}, headers,
        )

    def reinstate_advertiser(self, advertiser_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/advertisers/{advertiser_id}/reinstate", {}, headers,
        )

    def close_advertiser(self, advertiser_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/advertisers/{advertiser_id}/close", {}, headers,
        )

    # =======================================================================
    # Qualification documents (PRD §3.1)
    # =======================================================================
    def upload_qualification(self, advertiser_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/qualifications",
            payload, headers,
        )

    def review_qualification(self, advertiser_id: str, doc_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/qualifications/{doc_id}/review",
            payload, headers,
        )

    # =======================================================================
    # Account users (PRD §3.2)
    # =======================================================================
    def create_account_user(self, advertiser_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/advertisers/{advertiser_id}/users", payload, headers,
        )

    def list_account_users(self, advertiser_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/advertisers/{advertiser_id}/users",
            headers=headers, params=params,
        )

    def patch_account_user(self, advertiser_id: str, user_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/advertisers/{advertiser_id}/users/{user_id}",
            payload, headers,
        )

    # =======================================================================
    # Campaigns (PRD §3.3)
    # =======================================================================
    def create_campaign(self, advertiser_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/advertisers/{advertiser_id}/campaigns",
            payload, headers,
        )

    def list_campaigns(self, advertiser_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/advertisers/{advertiser_id}/campaigns",
            headers=headers, params=params,
        )

    def update_campaign(self, advertiser_id: str, campaign_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PUT",
            f"/advertisers/{advertiser_id}/campaigns/{campaign_id}",
            payload, headers,
        )

    def activate_campaign(self, advertiser_id: str, campaign_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/{campaign_id}/activate",
            {}, headers,
        )

    def pause_campaign(self, advertiser_id: str, campaign_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/{campaign_id}/pause",
            {}, headers,
        )

    def end_campaign(self, advertiser_id: str, campaign_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/{campaign_id}/end",
            {}, headers,
        )

    # =======================================================================
    # Ad-groups (PRD §3.3)
    # =======================================================================
    def create_ad_group(self, advertiser_id: str, campaign_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups",
            payload, headers,
        )

    def list_ad_groups(self, advertiser_id: str, campaign_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups",
            headers=headers, params=params,
        )

    def update_ad_group(self, advertiser_id: str, campaign_id: str,
                        ad_group_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PUT",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups/{ad_group_id}",
            payload, headers,
        )

    def activate_ad_group(self, advertiser_id: str, campaign_id: str,
                          ad_group_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups/{ad_group_id}/activate",
            {}, headers,
        )

    def pause_ad_group(self, advertiser_id: str, campaign_id: str,
                       ad_group_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups/{ad_group_id}/pause",
            {}, headers,
        )

    def archive_ad_group(self, advertiser_id: str, campaign_id: str,
                         ad_group_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups/{ad_group_id}/archive",
            {}, headers,
        )

    # =======================================================================
    # Creatives (PRD §3.4)
    # =======================================================================
    def create_creative(self, advertiser_id: str, campaign_id: str,
                        ad_group_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups/{ad_group_id}/creatives",
            payload, headers,
        )

    def list_creatives(self, advertiser_id: str, campaign_id: str,
                       ad_group_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/advertisers/{advertiser_id}/campaigns/"
            f"{campaign_id}/ad-groups/{ad_group_id}/creatives",
            headers=headers, params=params,
        )

    def prescreen_creative(self, creative_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/creatives/{creative_id}/prescreen",
            payload, headers,
        )

    def human_review_creative(self, creative_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/creatives/{creative_id}/human-review",
            payload, headers,
        )

    def appeal_creative(self, creative_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/creatives/{creative_id}/appeal",
            payload, headers,
        )

    def start_review_appeal(self, creative_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/creatives/{creative_id}/appeal/start-review",
            {}, headers,
        )

    def decide_appeal(self, creative_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/creatives/{creative_id}/appeal/decide",
            payload, headers,
        )

    def archive_creative(self, creative_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/creatives/{creative_id}/archive",
            {}, headers,
        )

    def list_review_decisions(self, creative_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/creatives/{creative_id}/review-decisions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Auctions (PRD §3.5)
    # =======================================================================
    def run_auction(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/auctions", payload, headers)

    def get_auction(self, auction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/auctions/{auction_id}", headers=headers,
        )

    # =======================================================================
    # Billing events (PRD §3.6)
    # =======================================================================
    def create_billing_event(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/billing-events", payload, headers)

    def reverse_billing_event(self, event_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/billing-events/{event_id}/reverse",
            payload, headers,
        )

    def list_billing_events(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/billing-events", headers=headers, params=params,
        )

    # =======================================================================
    # Conversions / attribution (PRD §3.7)
    # =======================================================================
    def create_conversion(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/conversions", payload, headers)

    def attribute_conversion(self, conversion_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/conversions/{conversion_id}/attribute",
            {}, headers,
        )

    def attribution_report(self, advertiser_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/advertisers/{advertiser_id}/reports/attribution",
            headers=headers, params=params,
        )

    # =======================================================================
    # Wallet (PRD §3.8)
    # =======================================================================
    def create_wallet_tx(self, advertiser_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/wallet/transactions",
            payload, headers,
        )

    def list_wallet_tx(self, advertiser_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/advertisers/{advertiser_id}/wallet/transactions",
            headers=headers, params=params,
        )

    def reverse_wallet_tx(self, advertiser_id: str, tx_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/advertisers/{advertiser_id}/wallet/"
            f"transactions/{tx_id}/reverse",
            payload, headers,
        )

    def wallet_statement(self, advertiser_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/advertisers/{advertiser_id}/wallet/statement",
            headers=headers, params=params,
        )

    # =======================================================================
    # Risk score / audit (PRD §3.10)
    # =======================================================================
    def get_risk_score(self, advertiser_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/advertisers/{advertiser_id}/risk-score",
            headers=headers, params=params,
        )

    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
