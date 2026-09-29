"""API client: one method per endpoint of the Recruitment Marketing & Employer Brand API."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every collection is mounted at the URL root; parentage travels in request bodies."""

    # ------------------------------------------------------------- logical clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ----------------------------------------------------------------- programs
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def update_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/programs/{program_id}", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    # -------------------------------------------------------------- job families
    def create_job_family(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/job-families", payload, headers)

    def get_job_family(self, family_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/job-families/{family_id}", headers=headers)

    def list_job_families(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/job-families", headers=headers, params=params)

    # ------------------------------------------------------------------ channels
    def create_channel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/channels", payload, headers)

    def get_channel(self, channel_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    def list_channels(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/channels", headers=headers, params=params)

    # ---------------------------------------------------------- candidate personas
    def create_candidate_persona(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/candidate-personas", payload, headers)

    def submit_candidate_persona(self, persona_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/candidate-personas/{persona_id}/submit", None, headers
        )

    def review_candidate_persona(
        self, persona_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/candidate-personas/{persona_id}/review", payload, headers
        )

    def retire_candidate_persona(self, persona_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/candidate-personas/{persona_id}/retire", None, headers
        )

    def get_candidate_persona(self, persona_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/candidate-personas/{persona_id}", headers=headers)

    def list_candidate_personas(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/candidate-personas", headers=headers, params=params)

    # ------------------------------------------------- channel preference signals
    def create_channel_preference_signal(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/channel-preference-signals", payload, headers)

    def get_channel_preference_signal(self, signal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/channel-preference-signals/{signal_id}", headers=headers
        )

    def list_channel_preference_signals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/channel-preference-signals", headers=headers, params=params
        )

    # -------------------------------------------------------------- job postings
    def create_job_posting(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/job-postings", payload, headers)

    def optimize_job_posting(
        self, posting_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/job-postings/{posting_id}/optimize", payload, headers
        )

    def compliance_review_job_posting(
        self, posting_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/job-postings/{posting_id}/compliance-review", payload, headers
        )

    def publish_job_posting(self, posting_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/job-postings/{posting_id}/publish", None, headers)

    def archive_job_posting(self, posting_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/job-postings/{posting_id}/archive", None, headers)

    def get_job_posting(self, posting_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/job-postings/{posting_id}", headers=headers)

    def get_job_posting_conversion(self, posting_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/job-postings/{posting_id}/conversion", headers=headers
        )

    def list_job_postings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/job-postings", headers=headers, params=params)

    # ------------------------------------------------------------- media flights
    def create_media_flight(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/media-flights", payload, headers)

    def activate_media_flight(self, flight_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/media-flights/{flight_id}/activate", None, headers
        )

    def resume_media_flight(self, flight_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/media-flights/{flight_id}/resume", None, headers)

    def spend_media_flight(
        self, flight_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/media-flights/{flight_id}/spend", payload, headers
        )

    def complete_media_flight(self, flight_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/media-flights/{flight_id}/complete", None, headers
        )

    def cancel_media_flight(
        self, flight_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/media-flights/{flight_id}/cancel", payload, headers
        )

    def get_media_flight(self, flight_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/media-flights/{flight_id}", headers=headers)

    def list_media_flights(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/media-flights", headers=headers, params=params)

    # -------------------------------------------------------------- applications
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def submit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/submit", None, headers
        )

    def screen_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/screen", None, headers
        )

    def decide_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applications/{application_id}/decide", payload, headers
        )

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/applications", headers=headers, params=params)

    # --------------------------------------------------------------- touchpoints
    def create_touchpoint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/touchpoints", payload, headers)

    def get_touchpoint(self, touchpoint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/touchpoints/{touchpoint_id}", headers=headers)

    def list_touchpoints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/touchpoints", headers=headers, params=params)

    # ------------------------------------------------- talent community members
    def create_talent_community_member(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/talent-community-members", payload, headers)

    def confirm_consent(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/talent-community-members/{member_id}/confirm-consent", payload, headers
        )

    def change_consent(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/talent-community-members/{member_id}/consent-change", payload, headers
        )

    def get_talent_community_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/talent-community-members/{member_id}", headers=headers
        )

    def list_talent_community_members(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/talent-community-members", headers=headers, params=params
        )

    # ---------------------------------------------------------- nurture campaigns
    def create_nurture_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/nurture-campaigns", payload, headers)

    def schedule_nurture_campaign(
        self, campaign_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/nurture-campaigns/{campaign_id}/schedule", payload, headers
        )

    def dispatch_nurture_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/nurture-campaigns/{campaign_id}/dispatch", None, headers
        )

    def cancel_nurture_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/nurture-campaigns/{campaign_id}/cancel", None, headers
        )

    def get_nurture_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/nurture-campaigns/{campaign_id}", headers=headers)

    def list_nurture_campaigns(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/nurture-campaigns", headers=headers, params=params)

    # -------------------------------------------------------------- nurture sends
    def get_nurture_send(self, send_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/nurture-sends/{send_id}", headers=headers)

    def list_nurture_sends(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/nurture-sends", headers=headers, params=params)

    # ----------------------------------------------------------- employer reviews
    def create_employer_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/employer-reviews", payload, headers)

    def triage_employer_review(
        self,
        review_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/employer-reviews/{review_id}/triage", payload, headers
        )

    def draft_response(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/employer-reviews/{review_id}/draft-response", payload, headers
        )

    def submit_legal(self, review_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/employer-reviews/{review_id}/submit-legal", None, headers
        )

    def legal_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/employer-reviews/{review_id}/legal-review", payload, headers
        )

    def close_employer_review(self, review_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/employer-reviews/{review_id}/close", None, headers
        )

    def get_employer_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/employer-reviews/{review_id}", headers=headers)

    def list_employer_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/employer-reviews", headers=headers, params=params)

    # ------------------------------------------------------------ event presences
    def create_event_presence(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/event-presences", payload, headers)

    def confirm_event_presence(
        self, presence_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/event-presences/{presence_id}/confirm", payload, headers
        )

    def complete_event_presence(self, presence_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/event-presences/{presence_id}/complete", None, headers
        )

    def cancel_event_presence(self, presence_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/event-presences/{presence_id}/cancel", None, headers
        )

    def get_event_presence(self, presence_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/event-presences/{presence_id}", headers=headers)

    def list_event_presences(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/event-presences", headers=headers, params=params)

    # ------------------------------------------------------ budget ledger entries
    def get_budget_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/budget-ledger-entries/{entry_id}", headers=headers
        )

    def list_budget_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/budget-ledger-entries", headers=headers, params=params
        )


#: Shared client instance; base URL comes from the API_BASE_URL environment variable.
api_client = ApiClient()
