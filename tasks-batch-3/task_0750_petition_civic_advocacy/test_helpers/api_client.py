"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Users ----
    def create_user(self, payload, headers):
        return self._request("POST", "/users", payload, headers)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    # ---- Petitions ----
    def create_petition(self, payload, headers):
        return self._request("POST", "/petitions", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/petitions", headers=headers, params=params)

    def edit_petition(self, petition_id, payload, headers):
        return self._request("PATCH", f"/petitions/{petition_id}", payload, headers)

    def submit_petition(self, petition_id, headers, payload=None):
        return self._request("POST", f"/petitions/{petition_id}/submit", payload or {}, headers)

    def moderate_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/moderate", payload, headers)

    def close_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/close", payload, headers)

    def set_target(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/target", payload, headers)

    # ---- Targets ----
    def get_target(self, target_id, headers):
        return self._request("GET", f"/targets/{target_id}", headers=headers)

    def list_targets(self, headers, params=None):
        return self._request("GET", "/targets", headers=headers, params=params)

    def deactivate_target(self, target_id, headers, payload=None):
        return self._request("POST", f"/targets/{target_id}/deactivate", payload or {}, headers)

    # ---- Representatives ----
    def create_representative(self, payload, headers):
        return self._request("POST", "/representatives", payload, headers)

    def get_representative(self, rep_id, headers):
        return self._request("GET", f"/representatives/{rep_id}", headers=headers)

    def list_representatives(self, headers, params=None):
        return self._request("GET", "/representatives", headers=headers, params=params)

    # ---- Signatures ----
    def sign_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/signatures", payload, headers)

    def get_signature(self, signature_id, headers):
        return self._request("GET", f"/signatures/{signature_id}", headers=headers)

    def list_signatures(self, headers, params=None):
        return self._request("GET", "/signatures", headers=headers, params=params)

    def verify_signature(self, signature_id, payload, headers):
        return self._request("POST", f"/signatures/{signature_id}/verify", payload, headers)

    def revoke_signature(self, signature_id, payload, headers):
        return self._request("POST", f"/signatures/{signature_id}/revoke", payload, headers)

    # ---- Comments & Updates ----
    def create_comment(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/comments", payload, headers)

    def get_comment(self, comment_id, headers):
        return self._request("GET", f"/comments/{comment_id}", headers=headers)

    def list_comments(self, headers, params=None):
        return self._request("GET", "/comments", headers=headers, params=params)

    def moderate_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/comments/{comment_id}/moderate", payload, headers)

    def flag_comment(self, comment_id, headers, payload=None):
        return self._request("POST", f"/comments/{comment_id}/flag", payload or {}, headers)

    def deliver_comment(self, comment_id, headers, payload=None):
        return self._request("POST", f"/comments/{comment_id}/deliver", payload or {}, headers)

    # ---- Campaign & Donations ----
    def create_campaign(self, petition_id, payload, headers):
        return self._request("POST", f"/petitions/{petition_id}/campaign", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def moderate_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/moderate", payload, headers)

    def create_donation(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    def transition_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/donations/{donation_id}/transition", payload, headers)

    # ---- Promotions ----
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/promotions", headers=headers, params=params)

    def cancel_promotion(self, promotion_id, headers, payload=None):
        return self._request("POST", f"/promotions/{promotion_id}/cancel", payload or {}, headers)

    # ---- Delivery Meetings ----
    def create_delivery_meeting(self, payload, headers):
        return self._request("POST", "/delivery-meetings", payload, headers)

    def get_delivery_meeting(self, meeting_id, headers):
        return self._request("GET", f"/delivery-meetings/{meeting_id}", headers=headers)

    def list_delivery_meetings(self, headers, params=None):
        return self._request("GET", "/delivery-meetings", headers=headers, params=params)

    def transition_delivery_meeting(self, meeting_id, payload, headers):
        return self._request("POST", f"/delivery-meetings/{meeting_id}/transition", payload, headers)

    # ---- Test-driving ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
