"""API client: one method per endpoint defined in the Reward Crowdfunding PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Creator ----
    def create_creator(self, payload, headers):
        return self._request("POST", "/creators", payload, headers)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"/creators/{creator_id}", headers=headers)

    # ---- Backer ----
    def create_backer(self, payload, headers):
        return self._request("POST", "/backers", payload, headers)

    def get_backer(self, backer_id, headers):
        return self._request("GET", f"/backers/{backer_id}", headers=headers)

    # ---- Campaign ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def launch_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/launch", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/close", {}, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/cancel", {}, headers)

    def get_settlement(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}/settlement", headers=headers)

    # ---- RewardTier ----
    def create_tier(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/tiers", headers=headers, params=params)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/tiers/{tier_id}", headers=headers)

    # ---- StretchGoal ----
    def create_stretch_goal(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/stretch-goals", payload, headers)

    def list_stretch_goals(self, headers, params=None):
        return self._request("GET", "/stretch-goals", headers=headers, params=params)

    def get_stretch_goal(self, stretch_goal_id, headers):
        return self._request("GET", f"/stretch-goals/{stretch_goal_id}", headers=headers)

    # ---- AddOn ----
    def create_addon_product(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/add-on-products", payload, headers)

    def list_addon_products(self, headers, params=None):
        return self._request("GET", "/add-on-products", headers=headers, params=params)

    def get_addon_product(self, addon_id, headers):
        return self._request("GET", f"/add-on-products/{addon_id}", headers=headers)

    # ---- Pledge ----
    def create_pledge(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/pledges", payload, headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def attach_addon(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/add-ons", payload, headers)

    def cancel_pledge(self, pledge_id, headers):
        return self._request("POST", f"/pledges/{pledge_id}/cancel", {}, headers)

    def complete_survey(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/survey", payload, headers)

    def ship_pledge(self, pledge_id, headers):
        return self._request("POST", f"/pledges/{pledge_id}/ship", {}, headers)

    # ---- PledgeAddOn (junction line) ----
    def list_pledge_add_ons(self, headers, params=None):
        return self._request("GET", "/pledge-add-ons", headers=headers, params=params)

    def get_pledge_add_on(self, pledge_addon_id, headers):
        return self._request("GET", f"/pledge-add-ons/{pledge_addon_id}", headers=headers)

    # ---- PaymentAuthorization ----
    def queue_authorization(self, pledge_id, payload, headers):
        return self._request("POST", f"/pledges/{pledge_id}/authorization", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    # ---- Refund ----
    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    # ---- FulfillmentSurvey ----
    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
