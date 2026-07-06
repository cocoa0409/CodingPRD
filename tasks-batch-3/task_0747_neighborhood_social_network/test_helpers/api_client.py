"""API client: one method per endpoint defined in the PRD.

Paths are prefixed with /neighborhood per the PRD's api_prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Neighborhoods ----
    def create_neighborhood(self, payload, headers):
        return self._request("POST", "/neighborhood/neighborhoods", payload, headers)

    def get_neighborhood(self, neighborhood_id, headers):
        return self._request("GET", f"/neighborhood/neighborhoods/{neighborhood_id}", headers=headers)

    def list_neighborhoods(self, headers, params=None):
        return self._request("GET", "/neighborhood/neighborhoods", headers=headers, params=params)

    def list_neighborhood_memberships(self, neighborhood_id, headers, params=None):
        return self._request("GET", f"/neighborhood/neighborhoods/{neighborhood_id}/memberships",
                             headers=headers, params=params)

    # ---- Residents ----
    def create_resident(self, payload, headers):
        return self._request("POST", "/neighborhood/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/neighborhood/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/neighborhood/residents", headers=headers, params=params)

    def promote_moderator(self, resident_id, headers):
        return self._request("POST", f"/neighborhood/residents/{resident_id}/promote-moderator", {}, headers)

    def list_resident_memberships(self, resident_id, headers, params=None):
        return self._request("GET", f"/neighborhood/residents/{resident_id}/memberships",
                             headers=headers, params=params)

    # ---- Verification requests ----
    def create_verification_request(self, payload, headers):
        return self._request("POST", "/neighborhood/verification-requests", payload, headers)

    def get_verification_request(self, vr_id, headers):
        return self._request("GET", f"/neighborhood/verification-requests/{vr_id}", headers=headers)

    def list_verification_requests(self, headers, params=None):
        return self._request("GET", "/neighborhood/verification-requests", headers=headers, params=params)

    def claim_verification_request(self, vr_id, headers):
        return self._request("POST", f"/neighborhood/verification-requests/{vr_id}/claim", {}, headers)

    def request_resubmission(self, vr_id, headers):
        return self._request("POST", f"/neighborhood/verification-requests/{vr_id}/request-resubmission", {}, headers)

    def resubmit_verification(self, vr_id, payload, headers):
        return self._request("POST", f"/neighborhood/verification-requests/{vr_id}/resubmit", payload, headers)

    def approve_verification(self, vr_id, headers):
        return self._request("POST", f"/neighborhood/verification-requests/{vr_id}/approve", {}, headers)

    def reject_verification(self, vr_id, headers):
        return self._request("POST", f"/neighborhood/verification-requests/{vr_id}/reject", {}, headers)

    def list_verification_memberships(self, vr_id, headers, params=None):
        return self._request("GET", f"/neighborhood/verification-requests/{vr_id}/memberships",
                             headers=headers, params=params)

    # ---- Posts ----
    def create_post(self, payload, headers):
        return self._request("POST", "/neighborhood/posts", payload, headers)

    def get_post(self, post_id, headers):
        return self._request("GET", f"/neighborhood/posts/{post_id}", headers=headers)

    def list_posts(self, headers, params=None):
        return self._request("GET", "/neighborhood/posts", headers=headers, params=params)

    def delete_post(self, post_id, headers):
        return self._request("DELETE", f"/neighborhood/posts/{post_id}", headers=headers)

    # ---- Marketplace listings ----
    def create_marketplace_listing(self, payload, headers):
        return self._request("POST", "/neighborhood/marketplace-listings", payload, headers)

    def get_marketplace_listing(self, listing_id, headers):
        return self._request("GET", f"/neighborhood/marketplace-listings/{listing_id}", headers=headers)

    def list_marketplace_listings(self, headers, params=None):
        return self._request("GET", "/neighborhood/marketplace-listings", headers=headers, params=params)

    def reserve_listing(self, listing_id, headers):
        return self._request("POST", f"/neighborhood/marketplace-listings/{listing_id}/reserve", {}, headers)

    def confirm_sold_listing(self, listing_id, headers):
        return self._request("POST", f"/neighborhood/marketplace-listings/{listing_id}/confirm-sold", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/neighborhood/marketplace-listings/{listing_id}/withdraw", {}, headers)

    # ---- Incidents ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/neighborhood/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/neighborhood/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/neighborhood/incidents", headers=headers, params=params)

    def acknowledge_incident(self, incident_id, headers):
        return self._request("POST", f"/neighborhood/incidents/{incident_id}/acknowledge", {}, headers)

    def resolve_incident(self, incident_id, headers):
        return self._request("POST", f"/neighborhood/incidents/{incident_id}/resolve", {}, headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/neighborhood/incidents/{incident_id}/dismiss", {}, headers)

    # ---- Civic notices ----
    def create_civic_notice(self, payload, headers):
        return self._request("POST", "/neighborhood/civic-notices", payload, headers)

    def get_civic_notice(self, notice_id, headers):
        return self._request("GET", f"/neighborhood/civic-notices/{notice_id}", headers=headers)

    def list_civic_notices(self, headers, params=None):
        return self._request("GET", "/neighborhood/civic-notices", headers=headers, params=params)

    def retract_civic_notice(self, notice_id, headers):
        return self._request("POST", f"/neighborhood/civic-notices/{notice_id}/retract", {}, headers)

    # ---- Flag reports ----
    def create_flag_report(self, payload, headers):
        return self._request("POST", "/neighborhood/flag-reports", payload, headers)

    def get_flag_report(self, flag_id, headers):
        return self._request("GET", f"/neighborhood/flag-reports/{flag_id}", headers=headers)

    def list_flag_reports(self, headers, params=None):
        return self._request("GET", "/neighborhood/flag-reports", headers=headers, params=params)

    # ---- Moderation decisions ----
    def create_moderation_decision(self, payload, headers):
        return self._request("POST", "/neighborhood/moderation-decisions", payload, headers)

    def get_moderation_decision(self, decision_id, headers):
        return self._request("GET", f"/neighborhood/moderation-decisions/{decision_id}", headers=headers)

    def list_moderation_decisions(self, headers, params=None):
        return self._request("GET", "/neighborhood/moderation-decisions", headers=headers, params=params)

    # ---- Businesses ----
    def create_business(self, payload, headers):
        return self._request("POST", "/neighborhood/businesses", payload, headers)

    def get_business(self, business_id, headers):
        return self._request("GET", f"/neighborhood/businesses/{business_id}", headers=headers)

    def list_businesses(self, headers, params=None):
        return self._request("GET", "/neighborhood/businesses", headers=headers, params=params)

    def verify_business(self, business_id, headers):
        return self._request("POST", f"/neighborhood/businesses/{business_id}/verify", {}, headers)

    # ---- Local ads ----
    def create_local_ad(self, payload, headers):
        return self._request("POST", "/neighborhood/local-ads", payload, headers)

    def get_local_ad(self, ad_id, headers):
        return self._request("GET", f"/neighborhood/local-ads/{ad_id}", headers=headers)

    def list_local_ads(self, headers, params=None):
        return self._request("GET", "/neighborhood/local-ads", headers=headers, params=params)

    def start_local_ad(self, ad_id, headers):
        return self._request("POST", f"/neighborhood/local-ads/{ad_id}/start", {}, headers)

    def pause_local_ad(self, ad_id, headers):
        return self._request("POST", f"/neighborhood/local-ads/{ad_id}/pause", {}, headers)

    def resume_local_ad(self, ad_id, headers):
        return self._request("POST", f"/neighborhood/local-ads/{ad_id}/resume", {}, headers)

    def serve_impression(self, ad_id, payload, headers):
        return self._request("POST", f"/neighborhood/local-ads/{ad_id}/serve-impression", payload, headers)

    # ---- Groups ----
    def create_group(self, payload, headers):
        return self._request("POST", "/neighborhood/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/neighborhood/groups/{group_id}", headers=headers)

    def list_groups(self, headers, params=None):
        return self._request("GET", "/neighborhood/groups", headers=headers, params=params)

    # ---- Events ----
    def create_event(self, payload, headers):
        return self._request("POST", "/neighborhood/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/neighborhood/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/neighborhood/events", headers=headers, params=params)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/neighborhood/events/{event_id}/cancel", {}, headers)

    # ---- Event RSVPs ----
    def create_event_rsvp(self, payload, headers):
        return self._request("POST", "/neighborhood/event-rsvps", payload, headers)

    def get_event_rsvp(self, rsvp_id, headers):
        return self._request("GET", f"/neighborhood/event-rsvps/{rsvp_id}", headers=headers)

    def list_event_rsvps(self, headers, params=None):
        return self._request("GET", "/neighborhood/event-rsvps", headers=headers, params=params)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/neighborhood/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/neighborhood/_clock/now", headers=headers)


api_client = ApiClient()
