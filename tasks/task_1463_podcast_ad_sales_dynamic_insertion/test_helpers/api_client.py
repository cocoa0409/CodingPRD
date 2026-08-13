"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Logical clock ----------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------- Show ----------
    def create_show(self, payload, headers):
        return self._request("POST", "/adnet/shows", payload, headers)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/adnet/shows/{show_id}", headers=headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/adnet/shows", headers=headers, params=params)

    def patch_show(self, show_id, payload, headers):
        return self._request("PATCH", f"/adnet/shows/{show_id}", payload, headers)

    def transition_show(self, show_id, payload, headers):
        return self._request("POST", f"/adnet/shows/{show_id}/transition", payload, headers)

    # ---------- Episode ----------
    def create_episode(self, payload, headers):
        return self._request("POST", "/adnet/episodes", payload, headers)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/adnet/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/adnet/episodes", headers=headers, params=params)

    def transition_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/adnet/episodes/{episode_id}/transition", payload, headers)

    def list_episode_downloads(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/adnet/episodes/{episode_id}/downloads", headers=headers, params=params
        )

    # ---------- Agency ----------
    def create_agency(self, payload, headers):
        return self._request("POST", "/adnet/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/adnet/agencies/{agency_id}", headers=headers)

    # ---------- Advertiser ----------
    def create_advertiser(self, payload, headers):
        return self._request("POST", "/adnet/advertisers", payload, headers)

    def get_advertiser(self, advertiser_id, headers):
        return self._request("GET", f"/adnet/advertisers/{advertiser_id}", headers=headers)

    def list_advertisers(self, headers, params=None):
        return self._request("GET", "/adnet/advertisers", headers=headers, params=params)

    def transition_advertiser(self, advertiser_id, payload, headers):
        return self._request(
            "POST", f"/adnet/advertisers/{advertiser_id}/transition", payload, headers
        )

    # ---------- Campaign ----------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/adnet/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/adnet/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/adnet/campaigns", headers=headers, params=params)

    def patch_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/adnet/campaigns/{campaign_id}", payload, headers)

    def transition_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/adnet/campaigns/{campaign_id}/transition", payload, headers
        )

    def get_campaign_report(self, campaign_id, headers):
        return self._request("GET", f"/adnet/campaigns/{campaign_id}/report", headers=headers)

    def list_campaign_attribution_events(self, campaign_id, headers, params=None):
        return self._request(
            "GET",
            f"/adnet/campaigns/{campaign_id}/attribution-events",
            headers=headers,
            params=params,
        )

    # ---------- LineItem ----------
    def create_line_item(self, payload, headers):
        return self._request("POST", "/adnet/line-items", payload, headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/adnet/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/adnet/line-items", headers=headers, params=params)

    def transition_line_item(self, line_item_id, payload, headers):
        return self._request(
            "POST", f"/adnet/line-items/{line_item_id}/transition", payload, headers
        )

    # ---------- AdCopy ----------
    def create_ad_copy(self, payload, headers):
        return self._request("POST", "/adnet/ad-copies", payload, headers)

    def get_ad_copy(self, copy_id, headers):
        return self._request("GET", f"/adnet/ad-copies/{copy_id}", headers=headers)

    def list_ad_copies(self, headers, params=None):
        return self._request("GET", "/adnet/ad-copies", headers=headers, params=params)

    def submit_ad_copy(self, copy_id, headers):
        return self._request("POST", f"/adnet/ad-copies/{copy_id}/submit", {}, headers)

    def review_ad_copy(self, copy_id, payload, headers):
        return self._request("POST", f"/adnet/ad-copies/{copy_id}/review", payload, headers)

    # ---------- Download / Impression ----------
    def create_downloads(self, payload, headers):
        return self._request("POST", "/adnet/downloads", payload, headers)

    def get_impression(self, impression_id, headers):
        return self._request("GET", f"/adnet/impressions/{impression_id}", headers=headers)

    def list_impressions(self, headers, params=None):
        return self._request("GET", "/adnet/impressions", headers=headers, params=params)

    # ---------- Attribution ----------
    def create_attribution_event(self, payload, headers):
        return self._request("POST", "/adnet/attribution-events", payload, headers)

    # ---------- Invoice ----------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/adnet/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/adnet/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/adnet/invoices", headers=headers, params=params)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/adnet/invoices/{invoice_id}/transition", payload, headers
        )

    # ---------- MakeGood ----------
    def get_make_good(self, make_good_id, headers):
        return self._request("GET", f"/adnet/make-goods/{make_good_id}", headers=headers)

    def list_make_goods(self, headers, params=None):
        return self._request("GET", "/adnet/make-goods", headers=headers, params=params)

    def transition_make_good(self, make_good_id, payload, headers):
        return self._request(
            "POST", f"/adnet/make-goods/{make_good_id}/transition", payload, headers
        )


api_client = ApiClient()
