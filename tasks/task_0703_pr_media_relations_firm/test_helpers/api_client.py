"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/agency/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/agency/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/agency/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/agency/clients", headers=headers, params=params)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/agency/clients/{client_id}/suspend", headers=headers)

    # ---- Outlet ----
    def create_outlet(self, payload, headers):
        return self._request("POST", "/agency/outlets", payload, headers)

    def get_outlet(self, outlet_id, headers):
        return self._request("GET", f"/agency/outlets/{outlet_id}", headers=headers)

    def list_outlets(self, headers, params=None):
        return self._request("GET", "/agency/outlets", headers=headers, params=params)

    # ---- Journalist ----
    def create_journalist(self, payload, headers):
        return self._request("POST", "/agency/journalists", payload, headers)

    def get_journalist(self, journalist_id, headers):
        return self._request("GET", f"/agency/journalists/{journalist_id}", headers=headers)

    def list_journalists(self, headers, params=None):
        return self._request("GET", "/agency/journalists", headers=headers, params=params)

    def blocklist_journalist(self, journalist_id, headers):
        return self._request("POST", f"/agency/journalists/{journalist_id}/blocklist", headers=headers)

    # ---- Campaign ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/agency/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/agency/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/agency/campaigns", headers=headers, params=params)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/agency/campaigns/{campaign_id}/activate", headers=headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/agency/campaigns/{campaign_id}/pause", headers=headers)

    def complete_campaign(self, campaign_id, headers):
        return self._request("POST", f"/agency/campaigns/{campaign_id}/complete", headers=headers)

    def archive_campaign(self, campaign_id, headers):
        return self._request("POST", f"/agency/campaigns/{campaign_id}/archive", headers=headers)

    # ---- RetainerPeriod ----
    def create_retainer_period(self, payload, headers):
        return self._request("POST", "/agency/retainer-periods", payload, headers)

    def get_retainer_period(self, period_id, headers):
        return self._request("GET", f"/agency/retainer-periods/{period_id}", headers=headers)

    def list_retainer_periods(self, headers, params=None):
        return self._request("GET", "/agency/retainer-periods", headers=headers, params=params)

    def close_retainer_period(self, period_id, payload, headers):
        return self._request("POST", f"/agency/retainer-periods/{period_id}/close", payload, headers)

    # ---- TimeEntry ----
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/agency/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/agency/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/agency/time-entries", headers=headers, params=params)

    def approve_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/agency/time-entries/{time_entry_id}/approve", headers=headers)

    def void_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/agency/time-entries/{time_entry_id}/void", headers=headers)

    # ---- Spokesperson ----
    def create_spokesperson(self, payload, headers):
        return self._request("POST", "/agency/spokespersons", payload, headers)

    def get_spokesperson(self, spokesperson_id, headers):
        return self._request("GET", f"/agency/spokespersons/{spokesperson_id}", headers=headers)

    def list_spokespersons(self, headers, params=None):
        return self._request("GET", "/agency/spokespersons", headers=headers, params=params)

    def deactivate_spokesperson(self, spokesperson_id, headers):
        return self._request("POST", f"/agency/spokespersons/{spokesperson_id}/deactivate", headers=headers)

    # ---- MediaList ----
    def create_media_list(self, payload, headers):
        return self._request("POST", "/agency/media-lists", payload, headers)

    def get_media_list(self, media_list_id, headers):
        return self._request("GET", f"/agency/media-lists/{media_list_id}", headers=headers)

    def list_media_lists(self, headers, params=None):
        return self._request("GET", "/agency/media-lists", headers=headers, params=params)

    # ---- Pitch ----
    def create_pitch(self, payload, headers):
        return self._request("POST", "/agency/pitches", payload, headers)

    def get_pitch(self, pitch_id, headers):
        return self._request("GET", f"/agency/pitches/{pitch_id}", headers=headers)

    def list_pitches(self, headers, params=None):
        return self._request("GET", "/agency/pitches", headers=headers, params=params)

    def send_pitch(self, pitch_id, headers):
        return self._request("POST", f"/agency/pitches/{pitch_id}/send", headers=headers)

    def respond_pitch(self, pitch_id, headers):
        return self._request("POST", f"/agency/pitches/{pitch_id}/respond", headers=headers)

    def accept_pitch(self, pitch_id, headers):
        return self._request("POST", f"/agency/pitches/{pitch_id}/accept", headers=headers)

    def reject_pitch(self, pitch_id, headers):
        return self._request("POST", f"/agency/pitches/{pitch_id}/reject", headers=headers)

    def decline_pitch(self, pitch_id, headers):
        return self._request("POST", f"/agency/pitches/{pitch_id}/decline", headers=headers)

    # ---- PressRelease ----
    def create_press_release(self, payload, headers):
        return self._request("POST", "/agency/press-releases", payload, headers)

    def get_press_release(self, press_release_id, headers):
        return self._request("GET", f"/agency/press-releases/{press_release_id}", headers=headers)

    def list_press_releases(self, headers, params=None):
        return self._request("GET", "/agency/press-releases", headers=headers, params=params)

    def schedule_press_release(self, press_release_id, headers):
        return self._request("POST", f"/agency/press-releases/{press_release_id}/schedule", headers=headers)

    def release_press_release(self, press_release_id, headers):
        return self._request("POST", f"/agency/press-releases/{press_release_id}/release", headers=headers)

    def withdraw_press_release(self, press_release_id, headers):
        return self._request("POST", f"/agency/press-releases/{press_release_id}/withdraw", headers=headers)

    # ---- Distribution ----
    def create_distribution(self, payload, headers):
        return self._request("POST", "/agency/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/agency/distributions/{distribution_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/agency/distributions", headers=headers, params=params)

    # ---- Coverage ----
    def create_coverage(self, payload, headers):
        return self._request("POST", "/agency/coverage", payload, headers)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"/agency/coverage/{coverage_id}", headers=headers)

    def list_coverage(self, headers, params=None):
        return self._request("GET", "/agency/coverage", headers=headers, params=params)

    def verify_coverage(self, coverage_id, headers):
        return self._request("POST", f"/agency/coverage/{coverage_id}/verify", headers=headers)

    def retract_coverage(self, coverage_id, headers):
        return self._request("POST", f"/agency/coverage/{coverage_id}/retract", headers=headers)

    # ---- Interview ----
    def create_interview(self, payload, headers):
        return self._request("POST", "/agency/interviews", payload, headers)

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/agency/interviews/{interview_id}", headers=headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/agency/interviews", headers=headers, params=params)

    def reschedule_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/agency/interviews/{interview_id}/reschedule", payload, headers)

    def confirm_interview(self, interview_id, headers):
        return self._request("POST", f"/agency/interviews/{interview_id}/confirm", headers=headers)

    def complete_interview(self, interview_id, headers):
        return self._request("POST", f"/agency/interviews/{interview_id}/complete", headers=headers)

    def no_show_interview(self, interview_id, headers):
        return self._request("POST", f"/agency/interviews/{interview_id}/no-show", headers=headers)

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"/agency/interviews/{interview_id}/cancel", headers=headers)

    # ---- CrisisEvent ----
    def create_crisis_event(self, payload, headers):
        return self._request("POST", "/agency/crisis-events", payload, headers)

    def get_crisis_event(self, crisis_id, headers):
        return self._request("GET", f"/agency/crisis-events/{crisis_id}", headers=headers)

    def list_crisis_events(self, headers, params=None):
        return self._request("GET", "/agency/crisis-events", headers=headers, params=params)

    def escalate_crisis(self, crisis_id, headers):
        return self._request("POST", f"/agency/crisis-events/{crisis_id}/escalate", headers=headers)

    def contain_crisis(self, crisis_id, headers):
        return self._request("POST", f"/agency/crisis-events/{crisis_id}/contain", headers=headers)

    def approve_response_crisis(self, crisis_id, headers, payload=None):
        return self._request(
            "POST", f"/agency/crisis-events/{crisis_id}/approve-response",
            payload if payload is not None else {}, headers,
        )

    def publish_response_crisis(self, crisis_id, headers):
        return self._request("POST", f"/agency/crisis-events/{crisis_id}/publish-response", headers=headers)


api_client = ApiClient()
