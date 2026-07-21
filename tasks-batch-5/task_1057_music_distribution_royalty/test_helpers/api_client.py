"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- subscription plans ----
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/api/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/api/subscription-plans/{plan_id}", headers=headers)

    def list_subscription_plans(self, headers, params=None):
        return self._request("GET", "/api/subscription-plans", headers=headers, params=params)

    # ---- stores ----
    def create_store(self, payload, headers):
        return self._request("POST", "/api/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/api/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/api/stores", headers=headers, params=params)

    # ---- artists ----
    def create_artist(self, payload, headers):
        return self._request("POST", "/api/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/api/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/api/artists", headers=headers, params=params)

    def update_artist(self, artist_id, payload, headers):
        return self._request("PATCH", f"/api/artists/{artist_id}", payload, headers)

    # ---- subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, payment_reference, headers):
        return self._request(
            "POST",
            f"/api/subscriptions/{subscription_id}/activate",
            {"payment_reference": payment_reference},
            headers,
        )

    def lapse_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/lapse", {}, headers)

    def expire_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/expire", {}, headers)

    # ---- releases ----
    def create_release(self, payload, headers):
        return self._request("POST", "/api/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/api/releases/{release_id}", headers=headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/api/releases", headers=headers, params=params)

    def update_release(self, release_id, payload, headers):
        return self._request("PATCH", f"/api/releases/{release_id}", payload, headers)

    def submit_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/submit", {}, headers)

    def withdraw_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/withdraw", {}, headers)

    def review_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/review", {}, headers)

    def approve_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/approve", {}, headers)

    def reject_release(self, release_id, reason_code, headers):
        return self._request(
            "POST", f"/api/releases/{release_id}/reject", {"reason_code": reason_code}, headers
        )

    def takedown_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/takedown", {}, headers)

    def go_live_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/go-live", {}, headers)

    def register_pre_save(self, release_id, fan_reference, headers):
        return self._request(
            "POST",
            f"/api/releases/{release_id}/pre-saves",
            {"fan_reference": fan_reference},
            headers,
        )

    # ---- tracks ----
    def add_track(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/tracks", payload, headers)

    def get_track(self, track_id, headers):
        return self._request("GET", f"/api/tracks/{track_id}", headers=headers)

    def list_tracks(self, headers, params=None):
        return self._request("GET", "/api/tracks", headers=headers, params=params)

    def update_track(self, track_id, payload, headers):
        return self._request("PATCH", f"/api/tracks/{track_id}", payload, headers)

    # ---- collaborators ----
    def create_collaborator(self, payload, headers):
        return self._request("POST", "/api/collaborators", payload, headers)

    def get_collaborator(self, collaborator_id, headers):
        return self._request("GET", f"/api/collaborators/{collaborator_id}", headers=headers)

    def list_collaborators(self, headers, params=None):
        return self._request("GET", "/api/collaborators", headers=headers, params=params)

    def update_collaborator(self, collaborator_id, payload, headers):
        return self._request("PATCH", f"/api/collaborators/{collaborator_id}", payload, headers)

    # ---- split sheets & shares ----
    def create_split_sheet(self, payload, headers):
        return self._request("POST", "/api/split-sheets", payload, headers)

    def get_split_sheet(self, sheet_id, headers):
        return self._request("GET", f"/api/split-sheets/{sheet_id}", headers=headers)

    def list_split_sheets(self, headers, params=None):
        return self._request("GET", "/api/split-sheets", headers=headers, params=params)

    def add_split_share(self, sheet_id, payload, headers):
        return self._request("POST", f"/api/split-sheets/{sheet_id}/shares", payload, headers)

    def get_split_share(self, share_id, headers):
        return self._request("GET", f"/api/split-shares/{share_id}", headers=headers)

    def list_split_shares(self, headers, params=None):
        return self._request("GET", "/api/split-shares", headers=headers, params=params)

    def send_split_sheet(self, sheet_id, headers):
        return self._request("POST", f"/api/split-sheets/{sheet_id}/send", {}, headers)

    def accept_split_share(self, share_id, headers):
        return self._request("POST", f"/api/split-shares/{share_id}/accept", {}, headers)

    def reject_split_share(self, share_id, reason_code, headers):
        return self._request(
            "POST", f"/api/split-shares/{share_id}/reject", {"reason_code": reason_code}, headers
        )

    def lock_split_sheet(self, sheet_id, headers):
        return self._request("POST", f"/api/split-sheets/{sheet_id}/lock", {}, headers)

    # ---- deliveries ----
    def queue_delivery(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/api/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/api/deliveries", headers=headers, params=params)

    def send_delivery(self, delivery_id, headers):
        return self._request("POST", f"/api/deliveries/{delivery_id}/send", {}, headers)

    def ack_delivery(self, delivery_id, outcome, headers, error_code=None):
        payload = {"outcome": outcome}
        if error_code is not None:
            payload["error_code"] = error_code
        return self._request("POST", f"/api/deliveries/{delivery_id}/ack", payload, headers)

    def retry_delivery(self, delivery_id, headers):
        return self._request("POST", f"/api/deliveries/{delivery_id}/retry", {}, headers)

    def confirm_takedown(self, delivery_id, headers):
        return self._request(
            "POST", f"/api/deliveries/{delivery_id}/confirm-takedown", {}, headers
        )

    # ---- royalty statements & lines ----
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/api/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/api/royalty-statements/{statement_id}", headers=headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/api/royalty-statements", headers=headers, params=params)

    def ingest_royalty_lines(self, statement_id, expected_statement_version, lines, headers):
        return self._request(
            "POST",
            f"/api/royalty-statements/{statement_id}/ingest",
            {"expected_statement_version": expected_statement_version, "lines": lines},
            headers,
        )

    def get_royalty_line(self, line_id, headers):
        return self._request("GET", f"/api/royalty-lines/{line_id}", headers=headers)

    def list_royalty_lines(self, headers, params=None):
        return self._request("GET", "/api/royalty-lines", headers=headers, params=params)

    def reconcile_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/royalty-statements/{statement_id}/reconcile", {}, headers
        )

    def close_statement(self, statement_id, headers):
        return self._request("POST", f"/api/royalty-statements/{statement_id}/close", {}, headers)

    def get_statement_summary(self, statement_id, headers):
        return self._request(
            "GET", f"/api/royalty-statements/{statement_id}/summary", headers=headers
        )

    # ---- payouts ----
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/api/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/api/payouts", headers=headers, params=params)

    def approve_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/approve", {}, headers)

    def pay_payout(self, payout_id, headers):
        return self._request("POST", f"/api/payouts/{payout_id}/pay", {}, headers)

    def reverse_payout(self, payout_id, reason_code, headers):
        return self._request(
            "POST", f"/api/payouts/{payout_id}/reverse", {"reason_code": reason_code}, headers
        )

    # ---- 1099 tax forms ----
    def create_tax_form(self, payload, headers):
        return self._request("POST", "/api/tax-forms", payload, headers)

    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/api/tax-forms/{form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/api/tax-forms", headers=headers, params=params)

    def issue_tax_form(self, form_id, headers):
        return self._request("POST", f"/api/tax-forms/{form_id}/issue", {}, headers)

    def void_tax_form(self, form_id, reason_code, headers):
        return self._request(
            "POST", f"/api/tax-forms/{form_id}/void", {"reason_code": reason_code}, headers
        )


api_client = ApiClient()
