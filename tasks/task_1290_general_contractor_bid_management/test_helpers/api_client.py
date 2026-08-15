"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- BidPackage ---
    def create_bid_package(self, payload, headers):
        return self._request("POST", "/bid-packages", payload, headers)

    def list_bid_packages(self, headers, params=None):
        return self._request("GET", "/bid-packages", headers=headers, params=params)

    def get_bid_package(self, package_id, headers):
        return self._request("GET", f"/bid-packages/{package_id}", headers=headers)

    def publish_bid_package(self, package_id, headers):
        return self._request("POST", f"/bid-packages/{package_id}/publish",
                             headers=headers)

    def close_bidding(self, package_id, headers):
        return self._request("POST", f"/bid-packages/{package_id}/close-bidding",
                             headers=headers)

    def tabulate_bid_package(self, package_id, headers):
        return self._request("POST", f"/bid-packages/{package_id}/tabulate",
                             headers=headers)

    def list_package_award_recommendations(self, package_id, headers, params=None):
        return self._request("GET",
                             f"/bid-packages/{package_id}/award-recommendations",
                             headers=headers, params=params)

    # --- Subcontractor ---
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/subcontractors", payload, headers)

    def list_subcontractors(self, headers, params=None):
        return self._request("GET", "/subcontractors", headers=headers, params=params)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request("GET", f"/subcontractors/{subcontractor_id}",
                             headers=headers)

    def list_subcontractor_acknowledgments(self, subcontractor_id, headers,
                                           params=None):
        return self._request("GET",
                             f"/subcontractors/{subcontractor_id}/acknowledgments",
                             headers=headers, params=params)

    # --- PrequalApplication ---
    def create_prequal_application(self, payload, headers):
        return self._request("POST", "/prequal-applications", payload, headers)

    def list_prequal_applications(self, headers, params=None):
        return self._request("GET", "/prequal-applications", headers=headers,
                             params=params)

    def get_prequal_application(self, application_id, headers):
        return self._request("GET", f"/prequal-applications/{application_id}",
                             headers=headers)

    def decide_prequal_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/prequal-applications/{application_id}/decision",
                             payload, headers)

    def resubmit_prequal_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/prequal-applications/{application_id}/resubmit",
                             payload, headers)

    # --- Invitation ---
    def create_invitation(self, payload, headers):
        return self._request("POST", "/invitations", payload, headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/invitations", headers=headers, params=params)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/invitations/{invitation_id}", headers=headers)

    def respond_invitation(self, invitation_id, payload, headers):
        return self._request("POST", f"/invitations/{invitation_id}/respond",
                             payload, headers)

    def plan_room_access(self, invitation_id, headers):
        return self._request("POST", f"/invitations/{invitation_id}/plan-room-access",
                             headers=headers)

    # --- Addendum / AddendumAcknowledgment ---
    def create_addendum(self, payload, headers):
        return self._request("POST", "/addendums", payload, headers)

    def list_addendums(self, headers, params=None):
        return self._request("GET", "/addendums", headers=headers, params=params)

    def get_addendum(self, addendum_id, headers):
        return self._request("GET", f"/addendums/{addendum_id}", headers=headers)

    def list_addendum_acknowledgments(self, addendum_id, headers, params=None):
        return self._request("GET", f"/addendums/{addendum_id}/acknowledgments",
                             headers=headers, params=params)

    def acknowledge_addendum(self, addendum_id, headers):
        return self._request("POST", f"/addendums/{addendum_id}/acknowledge",
                             headers=headers)

    def waive_addendum(self, addendum_id, payload, headers):
        return self._request("POST", f"/addendums/{addendum_id}/waive",
                             payload, headers)

    # --- Bid / BidRevision ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def create_bid_revision(self, bid_id, payload, headers):
        return self._request("POST", f"/bids/{bid_id}/revisions", payload, headers)

    def list_bid_revisions(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/revisions", headers=headers,
                             params=params)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/withdraw", headers=headers)

    def get_leveling_sheet(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}/leveling-sheet", headers=headers)

    def list_bid_leveling_adjustments(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/leveling-adjustments",
                             headers=headers, params=params)

    def list_bid_post_bid_interviews(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/post-bid-interviews",
                             headers=headers, params=params)

    def list_bid_award_recommendations(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/award-recommendations",
                             headers=headers, params=params)

    def list_bidder_feedbacks(self, bid_id, headers, params=None):
        return self._request("GET", f"/bids/{bid_id}/bidder-feedbacks",
                             headers=headers, params=params)

    # --- LevelingAdjustment ---
    def create_leveling_adjustment(self, payload, headers):
        return self._request("POST", "/leveling-adjustments", payload, headers)

    def update_leveling_adjustment(self, adjustment_id, payload, headers):
        return self._request("PATCH", f"/leveling-adjustments/{adjustment_id}",
                             payload, headers)

    def delete_leveling_adjustment(self, adjustment_id, headers):
        return self._request("DELETE", f"/leveling-adjustments/{adjustment_id}",
                             headers=headers)

    # --- PostBidInterview ---
    def create_post_bid_interview(self, payload, headers):
        return self._request("POST", "/post-bid-interviews", payload, headers)

    def complete_post_bid_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/post-bid-interviews/{interview_id}/complete",
                             payload, headers)

    # --- AwardRecommendation ---
    def create_award_recommendation(self, payload, headers):
        return self._request("POST", "/award-recommendations", payload, headers)

    def get_award_recommendation(self, recommendation_id, headers):
        return self._request("GET", f"/award-recommendations/{recommendation_id}",
                             headers=headers)

    def submit_award_recommendation(self, recommendation_id, headers):
        return self._request("POST",
                             f"/award-recommendations/{recommendation_id}/submit",
                             headers=headers)

    def decide_award_recommendation(self, recommendation_id, payload, headers):
        return self._request("POST",
                             f"/award-recommendations/{recommendation_id}/decide",
                             payload, headers)

    # --- BidderFeedback ---
    def send_bidder_feedback(self, feedback_id, payload, headers):
        return self._request("POST", f"/bidder-feedbacks/{feedback_id}/send",
                             payload, headers)


api_client = ApiClient()
