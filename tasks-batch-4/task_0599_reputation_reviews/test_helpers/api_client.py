"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/reputation"


class ApiClient(GenericApiClient):
    # ---------------- Businesses ----------------
    def create_business(self, payload, headers):
        return self._request("POST", f"{PREFIX}/businesses", payload, headers)

    def get_business(self, business_id, headers):
        return self._request("GET", f"{PREFIX}/businesses/{business_id}", headers=headers)

    def create_location(self, business_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/businesses/{business_id}/locations", payload, headers
        )

    def list_locations(self, business_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/businesses/{business_id}/locations", headers=headers, params=params
        )

    def create_contact(self, business_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/businesses/{business_id}/contacts", payload, headers
        )

    def list_contacts(self, business_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/businesses/{business_id}/contacts", headers=headers, params=params
        )

    def create_template(self, business_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/businesses/{business_id}/templates", payload, headers
        )

    def list_templates(self, business_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/businesses/{business_id}/templates", headers=headers, params=params
        )

    # ---------------- Locations ----------------
    def get_location(self, location_id, headers):
        return self._request("GET", f"{PREFIX}/locations/{location_id}", headers=headers)

    def update_nap(self, location_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/locations/{location_id}/nap", payload, headers)

    def set_compliance_hold(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/compliance-hold", payload, headers
        )

    def certify_location(self, location_id, headers):
        return self._request("POST", f"{PREFIX}/locations/{location_id}/certify", {}, headers)

    def get_dashboard(self, location_id, headers):
        return self._request(
            "GET", f"{PREFIX}/locations/{location_id}/dashboard", headers=headers
        )

    def list_alerts(self, location_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/locations/{location_id}/alerts", headers=headers, params=params
        )

    # ---------------- Listings ----------------
    def create_listing(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/listings", payload, headers
        )

    def list_listings(self, location_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/locations/{location_id}/listings", headers=headers, params=params
        )

    def sync_listing(self, listing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/sync", payload, headers)

    # ---------------- Competitors ----------------
    def create_competitor(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/competitors", payload, headers
        )

    def list_competitors(self, location_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/locations/{location_id}/competitors", headers=headers, params=params
        )

    # ---------------- Widget ----------------
    def create_widget(self, location_id, payload, headers):
        return self._request("POST", f"{PREFIX}/locations/{location_id}/widget", payload, headers)

    def get_widget(self, location_id, headers):
        return self._request("GET", f"{PREFIX}/locations/{location_id}/widget", headers=headers)

    def publish_widget(self, widget_id, headers):
        return self._request("POST", f"{PREFIX}/widgets/{widget_id}/publish", {}, headers)

    # ---------------- Contacts ----------------
    def opt_out_contact(self, contact_id, headers):
        return self._request("POST", f"{PREFIX}/contacts/{contact_id}/opt-out", {}, headers)

    # ---------------- Campaigns ----------------
    def create_campaign(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/campaigns", payload, headers
        )

    def list_campaigns(self, location_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/locations/{location_id}/campaigns", headers=headers, params=params
        )

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/campaigns/{campaign_id}", headers=headers)

    def schedule_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/schedule", {}, headers)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/activate", {}, headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/pause", {}, headers)

    def complete_campaign(self, campaign_id, headers):
        return self._request("POST", f"{PREFIX}/campaigns/{campaign_id}/complete", {}, headers)

    def create_review_request(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/requests", payload, headers
        )

    def send_batch(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaigns/{campaign_id}/send-batch", payload, headers
        )

    def get_campaign_metrics(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/campaigns/{campaign_id}/metrics", headers=headers)

    # ---------------- Review requests ----------------
    def list_review_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/review-requests", headers=headers, params=params)

    def get_review_request(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/review-requests/{request_id}", headers=headers)

    def send_request_event(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/review-requests/{request_id}/events", payload, headers
        )

    def cancel_review_request(self, request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/review-requests/{request_id}/cancel", {}, headers
        )

    # ---------------- Reviews ----------------
    def ingest_review(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/reviews", payload, headers
        )

    def list_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"{PREFIX}/reviews/{review_id}", headers=headers)

    def verify_review(self, review_id, headers):
        return self._request("POST", f"{PREFIX}/reviews/{review_id}/verify", {}, headers)

    def flag_review(self, review_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reviews/{review_id}/flag", payload, headers)

    def list_review_escalations(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reviews/{review_id}/escalations", headers=headers
        )

    # ---------------- Review responses ----------------
    def create_review_response(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reviews/{review_id}/responses", payload, headers
        )

    def list_review_responses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/review-responses", headers=headers, params=params)

    def get_review_response(self, response_id, headers):
        return self._request(
            "GET", f"{PREFIX}/review-responses/{response_id}", headers=headers
        )

    def submit_review_response(self, response_id, headers):
        return self._request(
            "POST", f"{PREFIX}/review-responses/{response_id}/submit", {}, headers
        )

    def approve_review_response(self, response_id, headers):
        return self._request(
            "POST", f"{PREFIX}/review-responses/{response_id}/approve", {}, headers
        )

    def reject_review_response(self, response_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/review-responses/{response_id}/reject", payload, headers
        )

    def revise_review_response(self, response_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/review-responses/{response_id}/revise", payload, headers
        )

    def publish_review_response(self, response_id, headers):
        return self._request(
            "POST", f"{PREFIX}/review-responses/{response_id}/publish", {}, headers
        )

    # ---------------- Escalations ----------------
    def acknowledge_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/acknowledge", {}, headers
        )

    def resolve_escalation(self, escalation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/escalations/{escalation_id}/resolve", {}, headers
        )

    # ---------------- Surveys ----------------
    def create_survey(self, location_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/locations/{location_id}/surveys", payload, headers
        )

    def list_surveys(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"{PREFIX}/surveys/{survey_id}", headers=headers)

    def submit_survey(self, survey_id, payload, headers):
        return self._request("POST", f"{PREFIX}/surveys/{survey_id}/submit", payload, headers)

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
