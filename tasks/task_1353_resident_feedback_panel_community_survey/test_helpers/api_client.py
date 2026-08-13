"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- PanelCell ---
    def create_panel_cell(self, payload, headers):
        return self._request("POST", "/feedback-panel/panel-cells", payload, headers)

    def list_panel_cells(self, headers, params=None):
        return self._request("GET", "/feedback-panel/panel-cells", headers=headers, params=params)

    def get_panel_cell(self, cell_id, headers):
        return self._request("GET", f"/feedback-panel/panel-cells/{cell_id}", headers=headers)

    def adjust_cell_target(self, cell_id, payload, headers):
        return self._request("POST", f"/feedback-panel/panel-cells/{cell_id}/targets", payload, headers)

    # --- Panelist ---
    def create_panelist(self, payload, headers):
        return self._request("POST", "/feedback-panel/panelists", payload, headers)

    def list_panelists(self, headers, params=None):
        return self._request("GET", "/feedback-panel/panelists", headers=headers, params=params)

    def get_panelist(self, panelist_id, headers):
        return self._request("GET", f"/feedback-panel/panelists/{panelist_id}", headers=headers)

    def enroll_panelist(self, panelist_id, headers):
        return self._request("POST", f"/feedback-panel/panelists/{panelist_id}/enroll", {}, headers)

    def reactivate_panelist(self, panelist_id, headers):
        return self._request("POST", f"/feedback-panel/panelists/{panelist_id}/reactivate", {}, headers)

    def withdraw_panelist(self, panelist_id, headers):
        return self._request("POST", f"/feedback-panel/panelists/{panelist_id}/withdraw", {}, headers)

    # --- Instrument ---
    def create_instrument(self, payload, headers):
        return self._request("POST", "/feedback-panel/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/feedback-panel/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/feedback-panel/instruments/{instrument_id}", headers=headers)

    def submit_instrument_review(self, instrument_id, headers):
        return self._request("POST", f"/feedback-panel/instruments/{instrument_id}/submit-review", {}, headers)

    def approve_instrument(self, instrument_id, headers):
        return self._request("POST", f"/feedback-panel/instruments/{instrument_id}/approve", {}, headers)

    def revise_instrument(self, instrument_id, headers):
        return self._request("POST", f"/feedback-panel/instruments/{instrument_id}/revise", {}, headers)

    def lock_instrument(self, instrument_id, headers):
        return self._request("POST", f"/feedback-panel/instruments/{instrument_id}/lock", {}, headers)

    # --- Translation ---
    def create_translation(self, payload, headers):
        return self._request("POST", "/feedback-panel/translations", payload, headers)

    def list_translations(self, headers, params=None):
        return self._request("GET", "/feedback-panel/translations", headers=headers, params=params)

    def get_translation(self, translation_id, headers):
        return self._request("GET", f"/feedback-panel/translations/{translation_id}", headers=headers)

    def certify_translation(self, translation_id, headers):
        return self._request("POST", f"/feedback-panel/translations/{translation_id}/certify", {}, headers)

    def reject_translation(self, translation_id, headers):
        return self._request("POST", f"/feedback-panel/translations/{translation_id}/reject", {}, headers)

    def resubmit_translation(self, translation_id, headers):
        return self._request("POST", f"/feedback-panel/translations/{translation_id}/resubmit", {}, headers)

    # --- SurveyWave ---
    def create_wave(self, payload, headers):
        return self._request("POST", "/feedback-panel/survey-waves", payload, headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/feedback-panel/survey-waves", headers=headers, params=params)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/feedback-panel/survey-waves/{wave_id}", headers=headers)

    def arm_wave(self, wave_id, headers):
        return self._request("POST", f"/feedback-panel/survey-waves/{wave_id}/arm", {}, headers)

    def open_fielding(self, wave_id, headers):
        return self._request("POST", f"/feedback-panel/survey-waves/{wave_id}/open-fielding", {}, headers)

    def close_wave(self, wave_id, headers):
        return self._request("POST", f"/feedback-panel/survey-waves/{wave_id}/close", {}, headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/feedback-panel/survey-waves/{wave_id}/cancel", {}, headers)

    def get_wave_analysis(self, wave_id, headers):
        return self._request("GET", f"/feedback-panel/survey-waves/{wave_id}/analysis", headers=headers)

    # --- Invitation ---
    def create_invitation(self, payload, headers):
        return self._request("POST", "/feedback-panel/invitations", payload, headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/feedback-panel/invitations", headers=headers, params=params)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/feedback-panel/invitations/{invitation_id}", headers=headers)

    def decline_invitation(self, invitation_id, headers):
        return self._request("POST", f"/feedback-panel/invitations/{invitation_id}/decline", {}, headers)

    def remind_invitation(self, invitation_id, headers):
        return self._request("POST", f"/feedback-panel/invitations/{invitation_id}/remind", {}, headers)

    # --- Response ---
    def create_response(self, payload, headers):
        return self._request("POST", "/feedback-panel/responses", payload, headers)

    def list_responses(self, headers, params=None):
        return self._request("GET", "/feedback-panel/responses", headers=headers, params=params)

    def get_response(self, response_id, headers):
        return self._request("GET", f"/feedback-panel/responses/{response_id}", headers=headers)

    def accept_response(self, response_id, headers):
        return self._request("POST", f"/feedback-panel/responses/{response_id}/accept", {}, headers)

    def quarantine_response(self, response_id, headers):
        return self._request("POST", f"/feedback-panel/responses/{response_id}/quarantine", {}, headers)

    def discard_response(self, response_id, headers):
        return self._request("POST", f"/feedback-panel/responses/{response_id}/discard", {}, headers)

    # --- IncentiveAward ---
    def list_awards(self, headers, params=None):
        return self._request("GET", "/feedback-panel/incentive-awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/feedback-panel/incentive-awards/{award_id}", headers=headers)

    def authorize_award(self, award_id, headers):
        return self._request("POST", f"/feedback-panel/incentive-awards/{award_id}/authorize", {}, headers)

    def pay_award(self, award_id, headers):
        return self._request("POST", f"/feedback-panel/incentive-awards/{award_id}/pay", {}, headers)

    def forfeit_award(self, award_id, headers):
        return self._request("POST", f"/feedback-panel/incentive-awards/{award_id}/forfeit", {}, headers)

    # --- WeightSnapshot ---
    def create_weight_snapshot(self, wave_id, payload, headers):
        return self._request("POST", f"/feedback-panel/survey-waves/{wave_id}/weight-snapshots", payload, headers)

    def list_weight_snapshots(self, headers, params=None):
        return self._request("GET", "/feedback-panel/weight-snapshots", headers=headers, params=params)

    def get_weight_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/feedback-panel/weight-snapshots/{snapshot_id}", headers=headers)

    def finalize_weight_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/feedback-panel/weight-snapshots/{snapshot_id}/finalize", {}, headers)

    # --- Publication ---
    def create_publication(self, payload, headers):
        return self._request("POST", "/feedback-panel/publications", payload, headers)

    def list_publications(self, headers, params=None):
        return self._request("GET", "/feedback-panel/publications", headers=headers, params=params)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/feedback-panel/publications/{publication_id}", headers=headers)

    def publish_publication(self, publication_id, headers):
        return self._request("POST", f"/feedback-panel/publications/{publication_id}/publish", {}, headers)

    def retract_publication(self, publication_id, headers):
        return self._request("POST", f"/feedback-panel/publications/{publication_id}/retract", {}, headers)

    # --- FollowUpCommitment ---
    def create_commitment(self, payload, headers):
        return self._request("POST", "/feedback-panel/follow-up-commitments", payload, headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", "/feedback-panel/follow-up-commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/feedback-panel/follow-up-commitments/{commitment_id}", headers=headers)

    def start_commitment(self, commitment_id, headers):
        return self._request("POST", f"/feedback-panel/follow-up-commitments/{commitment_id}/start", {}, headers)

    def fulfill_commitment(self, commitment_id, headers):
        return self._request("POST", f"/feedback-panel/follow-up-commitments/{commitment_id}/fulfill", {}, headers)

    def mark_breached_commitment(self, commitment_id, headers):
        return self._request("POST", f"/feedback-panel/follow-up-commitments/{commitment_id}/mark-breached", {}, headers)

    def renegotiate_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"/feedback-panel/follow-up-commitments/{commitment_id}/renegotiate", payload, headers)

    # --- PrivacyHold ---
    def create_privacy_hold(self, payload, headers):
        return self._request("POST", "/feedback-panel/privacy-holds", payload, headers)

    def list_privacy_holds(self, headers, params=None):
        return self._request("GET", "/feedback-panel/privacy-holds", headers=headers, params=params)

    def get_privacy_hold(self, hold_id, headers):
        return self._request("GET", f"/feedback-panel/privacy-holds/{hold_id}", headers=headers)

    def release_privacy_hold(self, hold_id, headers):
        return self._request("POST", f"/feedback-panel/privacy-holds/{hold_id}/release", {}, headers)

    # --- RefreshRun ---
    def create_refresh_run(self, payload, headers):
        return self._request("POST", "/feedback-panel/refresh-runs", payload, headers)

    def get_refresh_run(self, run_id, headers):
        return self._request("GET", f"/feedback-panel/refresh-runs/{run_id}", headers=headers)

    def apply_refresh_run(self, run_id, headers):
        return self._request("POST", f"/feedback-panel/refresh-runs/{run_id}/apply", {}, headers)

    def abort_refresh_run(self, run_id, headers):
        return self._request("POST", f"/feedback-panel/refresh-runs/{run_id}/abort", {}, headers)


api_client = ApiClient()
