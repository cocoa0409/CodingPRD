"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Catalog / configuration ---
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/subscription-plans/{plan_id}", headers=headers)

    def list_plan_accounts(self, plan_id, headers, params=None):
        return self._request("GET", f"/subscription-plans/{plan_id}/accounts", headers=headers, params=params)

    def list_plan_plan_changes(self, plan_id, headers, params=None):
        return self._request("GET", f"/subscription-plans/{plan_id}/plan-changes", headers=headers, params=params)

    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", payload, headers)

    def reactivate_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/reactivate", payload, headers)

    def close_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/close", payload, headers)

    def invoice_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/invoice", payload, headers)

    # --- Plan changes ---
    def create_plan_change(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/plan-changes", payload, headers)

    def list_account_plan_changes(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/plan-changes", headers=headers, params=params)

    # --- Profiles ---
    def create_profile(self, payload, headers):
        return self._request("POST", "/profiles", payload, headers)

    def get_profile(self, profile_id, headers):
        return self._request("GET", f"/profiles/{profile_id}", headers=headers)

    def archive_profile(self, profile_id, headers, payload=None):
        return self._request("POST", f"/profiles/{profile_id}/archive", payload, headers)

    def set_parental_control(self, profile_id, payload, headers):
        return self._request("POST", f"/profiles/{profile_id}/parental-control", payload, headers)

    def get_parental_control(self, profile_id, headers):
        return self._request("GET", f"/profiles/{profile_id}/parental-control", headers=headers)

    def list_account_profiles(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/profiles", headers=headers, params=params)

    # --- Invites ---
    def create_invite(self, payload, headers):
        return self._request("POST", "/invites", payload, headers)

    def list_account_invites(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/invites", headers=headers, params=params)

    def accept_invite(self, invite_id, payload, headers):
        return self._request("POST", f"/invites/{invite_id}/accept", payload, headers)

    def decline_invite(self, invite_id, payload, headers):
        return self._request("POST", f"/invites/{invite_id}/decline", payload, headers)

    def revoke_invite(self, invite_id, headers, payload=None):
        return self._request("POST", f"/invites/{invite_id}/revoke", payload, headers)

    # --- Devices ---
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def list_account_devices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/devices", headers=headers, params=params)

    def deregister_device(self, device_id, headers, payload=None):
        return self._request("POST", f"/devices/{device_id}/deregister", payload, headers)

    # --- Stream sessions ---
    def create_stream_session(self, payload, headers):
        return self._request("POST", "/stream-sessions", payload, headers)

    def stop_stream_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/stream-sessions/{session_id}/stop", payload, headers)

    def get_stream_session(self, session_id, headers):
        return self._request("GET", f"/stream-sessions/{session_id}", headers=headers)

    def list_stream_sessions(self, headers, params=None):
        return self._request("GET", "/stream-sessions", headers=headers, params=params)

    # --- Downloads ---
    def create_download(self, payload, headers):
        return self._request("POST", "/downloads", payload, headers)

    def complete_download(self, download_id, headers, payload=None):
        return self._request("POST", f"/downloads/{download_id}/complete", payload, headers)

    def delete_download(self, download_id, headers):
        return self._request("DELETE", f"/downloads/{download_id}", headers=headers)

    def get_download(self, download_id, headers):
        return self._request("GET", f"/downloads/{download_id}", headers=headers)

    def list_downloads(self, headers, params=None):
        return self._request("GET", "/downloads", headers=headers, params=params)

    # --- Watch progress ---
    def upsert_watch_progress(self, payload, headers):
        return self._request("PUT", "/watch-progress", payload, headers)

    def get_watch_progress(self, wp_id, headers):
        return self._request("GET", f"/watch-progress/{wp_id}", headers=headers)

    def list_watch_progress(self, headers, params=None):
        return self._request("GET", "/watch-progress", headers=headers, params=params)

    # --- Clock seam ---
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
