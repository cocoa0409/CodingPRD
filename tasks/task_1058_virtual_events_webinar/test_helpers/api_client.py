"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- events ----------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def update_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/api/events/{event_id}", payload, headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/publish", {}, headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/start", {}, headers)

    def end_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/end", {}, headers)

    def cancel_event(self, event_id, reason, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/cancel", {"reason": reason}, headers
        )

    def get_event_analytics(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}/analytics", headers=headers)

    # ---- ticket types ----------------------------------------------------
    def create_ticket_type(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/ticket-types", payload, headers
        )

    def list_event_ticket_types(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/api/events/{event_id}/ticket-types", headers=headers, params=params
        )

    def list_ticket_types(self, headers, params=None):
        return self._request("GET", "/api/ticket-types", headers=headers, params=params)

    def get_ticket_type(self, ticket_type_id, headers):
        return self._request(
            "GET", f"/api/ticket-types/{ticket_type_id}", headers=headers
        )

    # ---- registrations ---------------------------------------------------
    def create_registration(self, payload, headers):
        return self._request("POST", "/api/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/api/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/api/registrations/{registration_id}", headers=headers
        )

    def pay_registration(self, registration_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/api/registrations/{registration_id}/pay",
            {"amount_cents": amount_cents},
            headers,
        )

    def refund_registration(self, registration_id, reason, headers):
        return self._request(
            "POST",
            f"/api/registrations/{registration_id}/refund",
            {"reason": reason},
            headers,
        )

    def check_in_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/check-in", {}, headers
        )

    def withdraw_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/api/registrations/{registration_id}/withdraw", {}, headers
        )

    # ---- tracks ----------------------------------------------------------
    def create_track(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/tracks", payload, headers)

    def list_event_tracks(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/api/events/{event_id}/tracks", headers=headers, params=params
        )

    def list_tracks(self, headers, params=None):
        return self._request("GET", "/api/tracks", headers=headers, params=params)

    def get_track(self, track_id, headers):
        return self._request("GET", f"/api/tracks/{track_id}", headers=headers)

    # ---- sessions --------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/api/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/api/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/sessions/{session_id}", headers=headers)

    def schedule_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/schedule", {}, headers)

    def cancel_session(self, session_id, reason, headers):
        return self._request(
            "POST", f"/api/sessions/{session_id}/cancel", {"reason": reason}, headers
        )

    def record_session_attendance(self, session_id, registration_id, watched_minutes, headers):
        return self._request(
            "POST",
            f"/api/sessions/{session_id}/attendance",
            {"registration_id": registration_id, "watched_minutes": watched_minutes},
            headers,
        )

    # ---- speakers --------------------------------------------------------
    def create_speaker(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/speakers", payload, headers)

    def list_event_speakers(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/api/events/{event_id}/speakers", headers=headers, params=params
        )

    def list_speakers(self, headers, params=None):
        return self._request("GET", "/api/speakers", headers=headers, params=params)

    def get_speaker(self, speaker_id, headers):
        return self._request("GET", f"/api/speakers/{speaker_id}", headers=headers)

    # ---- session-speaker junction ---------------------------------------
    def create_session_speaker(self, payload, headers):
        return self._request("POST", "/api/session-speakers", payload, headers)

    def list_session_speakers(self, headers, params=None):
        return self._request(
            "GET", "/api/session-speakers", headers=headers, params=params
        )

    def get_session_speaker(self, session_speaker_id, headers):
        return self._request(
            "GET", f"/api/session-speakers/{session_speaker_id}", headers=headers
        )

    def accept_session_speaker(self, session_speaker_id, headers):
        return self._request(
            "POST", f"/api/session-speakers/{session_speaker_id}/accept", {}, headers
        )

    def decline_session_speaker(self, session_speaker_id, headers):
        return self._request(
            "POST", f"/api/session-speakers/{session_speaker_id}/decline", {}, headers
        )

    def withdraw_session_speaker(self, session_speaker_id, headers):
        return self._request(
            "POST", f"/api/session-speakers/{session_speaker_id}/withdraw", {}, headers
        )

    def reinvite_session_speaker(self, session_speaker_id, headers):
        return self._request(
            "POST", f"/api/session-speakers/{session_speaker_id}/reinvite", {}, headers
        )

    # ---- broadcasts ------------------------------------------------------
    def create_broadcast(self, payload, headers):
        return self._request("POST", "/api/broadcasts", payload, headers)

    def list_broadcasts(self, headers, params=None):
        return self._request("GET", "/api/broadcasts", headers=headers, params=params)

    def get_broadcast(self, broadcast_id, headers):
        return self._request("GET", f"/api/broadcasts/{broadcast_id}", headers=headers)

    def preview_broadcast(self, broadcast_id, headers):
        return self._request(
            "POST", f"/api/broadcasts/{broadcast_id}/preview", {}, headers
        )

    def go_live_broadcast(self, broadcast_id, headers):
        return self._request(
            "POST", f"/api/broadcasts/{broadcast_id}/go-live", {}, headers
        )

    def end_broadcast(self, broadcast_id, headers):
        return self._request("POST", f"/api/broadcasts/{broadcast_id}/end", {}, headers)

    def abort_broadcast(self, broadcast_id, reason, headers):
        return self._request(
            "POST", f"/api/broadcasts/{broadcast_id}/abort", {"reason": reason}, headers
        )

    # ---- recordings ------------------------------------------------------
    def list_recordings(self, headers, params=None):
        return self._request("GET", "/api/recordings", headers=headers, params=params)

    def get_recording(self, recording_id, headers):
        return self._request("GET", f"/api/recordings/{recording_id}", headers=headers)

    def complete_recording(self, recording_id, duration_seconds, headers):
        return self._request(
            "POST",
            f"/api/recordings/{recording_id}/complete",
            {"duration_seconds": duration_seconds},
            headers,
        )

    def publish_recording(self, recording_id, gating_level, headers):
        return self._request(
            "POST",
            f"/api/recordings/{recording_id}/publish",
            {"gating_level": gating_level},
            headers,
        )

    def retract_recording(self, recording_id, reason, headers):
        return self._request(
            "POST", f"/api/recordings/{recording_id}/retract", {"reason": reason}, headers
        )

    def reprocess_recording(self, recording_id, headers):
        return self._request(
            "POST", f"/api/recordings/{recording_id}/reprocess", {}, headers
        )

    def record_recording_view(self, recording_id, registration_id, headers):
        return self._request(
            "POST",
            f"/api/recordings/{recording_id}/views",
            {"registration_id": registration_id},
            headers,
        )

    def delete_recording(self, recording_id, headers):
        return self._request("DELETE", f"/api/recordings/{recording_id}", headers=headers)

    # ---- sponsors --------------------------------------------------------
    def create_sponsor(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/sponsors", payload, headers)

    def list_event_sponsors(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/api/events/{event_id}/sponsors", headers=headers, params=params
        )

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/api/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/api/sponsors/{sponsor_id}", headers=headers)

    def sign_sponsor_contract(self, sponsor_id, signed_by, headers):
        return self._request(
            "POST",
            f"/api/sponsors/{sponsor_id}/sign-contract",
            {"signed_by": signed_by},
            headers,
        )

    # ---- booths ----------------------------------------------------------
    def create_booth(self, payload, headers):
        return self._request("POST", "/api/booths", payload, headers)

    def list_booths(self, headers, params=None):
        return self._request("GET", "/api/booths", headers=headers, params=params)

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/api/booths/{booth_id}", headers=headers)

    def submit_booth(self, booth_id, headers):
        return self._request("POST", f"/api/booths/{booth_id}/submit", {}, headers)

    def approve_booth(self, booth_id, headers):
        return self._request("POST", f"/api/booths/{booth_id}/approve", {}, headers)

    def request_booth_changes(self, booth_id, reason, headers):
        return self._request(
            "POST", f"/api/booths/{booth_id}/request-changes", {"reason": reason}, headers
        )

    def suspend_booth(self, booth_id, reason, headers):
        return self._request(
            "POST", f"/api/booths/{booth_id}/suspend", {"reason": reason}, headers
        )

    def report_booth_stream_usage(self, booth_id, minutes, headers):
        return self._request(
            "POST", f"/api/booths/{booth_id}/stream-usage", {"minutes": minutes}, headers
        )

    # ---- leads -----------------------------------------------------------
    def capture_lead(self, booth_id, registration_id, marketing_consent, headers):
        return self._request(
            "POST",
            f"/api/booths/{booth_id}/leads",
            {"registration_id": registration_id, "marketing_consent": marketing_consent},
            headers,
        )

    def list_leads(self, headers, params=None):
        return self._request("GET", "/api/leads", headers=headers, params=params)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/api/leads/{lead_id}", headers=headers)

    def log_lead_interaction(self, lead_id, interaction_type, headers):
        return self._request(
            "POST",
            f"/api/leads/{lead_id}/interactions",
            {"interaction_type": interaction_type},
            headers,
        )

    def rescore_event_leads(self, event_id, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/leads/rescore", {}, headers
        )

    # ---- matchmaking -----------------------------------------------------
    def create_match_request(self, payload, headers):
        return self._request("POST", "/api/match-requests", payload, headers)

    def list_match_requests(self, headers, params=None):
        return self._request("GET", "/api/match-requests", headers=headers, params=params)

    def get_match_request(self, match_request_id, headers):
        return self._request(
            "GET", f"/api/match-requests/{match_request_id}", headers=headers
        )

    def accept_match_request(self, match_request_id, headers):
        return self._request(
            "POST", f"/api/match-requests/{match_request_id}/accept", {}, headers
        )

    def decline_match_request(self, match_request_id, headers):
        return self._request(
            "POST", f"/api/match-requests/{match_request_id}/decline", {}, headers
        )

    def sweep_matchmaking(self, event_id, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/matchmaking/sweep", {}, headers
        )

    # ---- settlements -----------------------------------------------------
    def create_event_settlement(self, event_id, expected_event_version, headers):
        return self._request(
            "POST",
            f"/api/events/{event_id}/settlements",
            {"expected_event_version": expected_event_version},
            headers,
        )

    def create_sponsor_settlement(self, sponsor_id, headers):
        return self._request(
            "POST", f"/api/sponsors/{sponsor_id}/settlements", {}, headers
        )

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/api/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/settlements/{settlement_id}", headers=headers)

    def issue_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/api/settlements/{settlement_id}/issue", {}, headers
        )

    def pay_settlement(self, settlement_id, paid_amount_cents, headers):
        return self._request(
            "POST",
            f"/api/settlements/{settlement_id}/pay",
            {"paid_amount_cents": paid_amount_cents},
            headers,
        )

    def void_settlement(self, settlement_id, reason, headers):
        return self._request(
            "POST", f"/api/settlements/{settlement_id}/void", {"reason": reason}, headers
        )


api_client = ApiClient()
