"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Rightsholders ----
    def create_rightsholder(self, payload, headers):
        return self._request("POST", "/rightsholders", payload, headers)

    def get_rightsholder(self, rightsholder_id, headers):
        return self._request("GET", f"/rightsholders/{rightsholder_id}", headers=headers)

    def suspend_rightsholder(self, rightsholder_id, headers):
        return self._request("POST", f"/rightsholders/{rightsholder_id}/suspend", headers=headers)

    # ---- Works ----
    def create_work(self, payload, headers):
        return self._request("POST", "/works", payload, headers)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/works/{work_id}", headers=headers)

    def register_work(self, work_id, headers):
        return self._request("POST", f"/works/{work_id}/register", headers=headers)

    # ---- Composition shares ----
    def create_composition_share(self, payload, headers):
        return self._request("POST", "/composition-shares", payload, headers)

    def get_composition_share(self, share_id, headers):
        return self._request("GET", f"/composition-shares/{share_id}", headers=headers)

    def list_composition_shares(self, headers, params=None):
        return self._request("GET", "/composition-shares", headers=headers, params=params)

    # ---- Recordings ----
    def create_recording(self, payload, headers):
        return self._request("POST", "/recordings", payload, headers)

    def get_recording(self, recording_id, headers):
        return self._request("GET", f"/recordings/{recording_id}", headers=headers)

    def list_recordings(self, headers, params=None):
        return self._request("GET", "/recordings", headers=headers, params=params)

    def lock_recording_shares(self, recording_id, headers):
        return self._request("POST", f"/recordings/{recording_id}/lock-shares", headers=headers)

    # ---- Recording shares ----
    def create_recording_share(self, payload, headers):
        return self._request("POST", "/recording-shares", payload, headers)

    def get_recording_share(self, share_id, headers):
        return self._request("GET", f"/recording-shares/{share_id}", headers=headers)

    def list_recording_shares(self, headers, params=None):
        return self._request("GET", "/recording-shares", headers=headers, params=params)

    # ---- Rights windows ----
    def create_rights_window(self, payload, headers):
        return self._request("POST", "/rights-windows", payload, headers)

    def get_rights_window(self, window_id, headers):
        return self._request("GET", f"/rights-windows/{window_id}", headers=headers)

    def list_rights_windows(self, headers, params=None):
        return self._request("GET", "/rights-windows", headers=headers, params=params)

    def revoke_rights_window(self, window_id, headers):
        return self._request("POST", f"/rights-windows/{window_id}/revoke", headers=headers)

    # ---- Usage events ----
    def create_usage_event(self, payload, headers):
        return self._request("POST", "/usage-events", payload, headers)

    def get_usage_event(self, event_id, headers):
        return self._request("GET", f"/usage-events/{event_id}", headers=headers)

    def list_usage_events(self, headers, params=None):
        return self._request("GET", "/usage-events", headers=headers, params=params)

    def allocate_usage_event(self, event_id, headers):
        return self._request("POST", f"/usage-events/{event_id}/allocate", headers=headers)

    def void_usage_event(self, event_id, headers):
        return self._request("POST", f"/usage-events/{event_id}/void", headers=headers)

    # ---- Sync licenses ----
    def create_sync_license(self, payload, headers):
        return self._request("POST", "/sync-licenses", payload, headers)

    def get_sync_license(self, license_id, headers):
        return self._request("GET", f"/sync-licenses/{license_id}", headers=headers)

    def list_sync_licenses(self, headers, params=None):
        return self._request("GET", "/sync-licenses", headers=headers, params=params)

    def counter_sync_license(self, license_id, payload, headers):
        return self._request("POST", f"/sync-licenses/{license_id}/counter", payload, headers)

    def requote_sync_license(self, license_id, payload, headers):
        return self._request("POST", f"/sync-licenses/{license_id}/requote", payload, headers)

    def accept_sync_license(self, license_id, headers):
        return self._request("POST", f"/sync-licenses/{license_id}/accept", headers=headers)

    def execute_sync_license(self, license_id, headers):
        return self._request("POST", f"/sync-licenses/{license_id}/execute", headers=headers)

    def decline_sync_license(self, license_id, headers):
        return self._request("POST", f"/sync-licenses/{license_id}/decline", headers=headers)

    # ---- Advances ----
    def create_advance(self, payload, headers):
        return self._request("POST", "/advances", payload, headers)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/advances/{advance_id}", headers=headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/advances", headers=headers, params=params)

    def write_off_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/write-off", headers=headers)

    # ---- Statements ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def get_statement_ledger(self, statement_id, headers, params=None):
        return self._request("GET", f"/statements/{statement_id}/ledger", headers=headers, params=params)

    def finalize_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/finalize", payload, headers)

    def reopen_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/statements/{statement_id}/reopen", payload, headers)

    # ---- Payouts ----
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_statement_payouts(self, statement_id, headers, params=None):
        return self._request("GET", f"/statements/{statement_id}/payouts", headers=headers, params=params)

    def settle_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/settle", headers=headers)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/reverse", headers=headers)


api_client = ApiClient()
