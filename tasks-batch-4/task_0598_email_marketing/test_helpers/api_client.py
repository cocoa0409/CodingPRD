"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Accounts ───────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def create_account_user(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/users", payload, headers)

    def list_account_users(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/users", headers=headers, params=params)

    def list_billing_cycles(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/billing-cycles", headers=headers, params=params
        )

    def list_suppressions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/suppressions", headers=headers, params=params
        )

    # ─── Audiences ──────────────────────────────────────────────────────────
    def create_audience(self, payload, headers):
        return self._request("POST", "/audiences", payload, headers)

    def get_audience(self, audience_id, headers):
        return self._request("GET", f"/audiences/{audience_id}", headers=headers)

    def list_audiences(self, headers, params=None):
        return self._request("GET", "/audiences", headers=headers, params=params)

    # ─── Subscribers ────────────────────────────────────────────────────────
    def create_subscriber(self, audience_id, payload, headers):
        return self._request("POST", f"/audiences/{audience_id}/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", "/subscribers", headers=headers, params=params)

    def confirm_subscriber(self, subscriber_id, payload, headers):
        return self._request("POST", f"/subscribers/{subscriber_id}/confirm", payload, headers)

    def unsubscribe_subscriber(self, subscriber_id, payload, headers):
        return self._request("POST", f"/subscribers/{subscriber_id}/unsubscribe", payload, headers)

    def list_subscriber_enrollments(self, subscriber_id, headers, params=None):
        return self._request(
            "GET", f"/subscribers/{subscriber_id}/enrollments", headers=headers, params=params
        )

    # ─── Imports ────────────────────────────────────────────────────────────
    def create_import_job(self, audience_id, payload, headers):
        return self._request("POST", f"/audiences/{audience_id}/import-jobs", payload, headers)

    def list_import_jobs(self, audience_id, headers, params=None):
        return self._request(
            "GET", f"/audiences/{audience_id}/import-jobs", headers=headers, params=params
        )

    def rollback_import_job(self, import_job_id, headers):
        return self._request("POST", f"/import-jobs/{import_job_id}/rollback", {}, headers)

    # ─── Segments ───────────────────────────────────────────────────────────
    def create_segment(self, audience_id, payload, headers):
        return self._request("POST", f"/audiences/{audience_id}/segments", payload, headers)

    def list_segments(self, audience_id, headers, params=None):
        return self._request(
            "GET", f"/audiences/{audience_id}/segments", headers=headers, params=params
        )

    # ─── Templates ──────────────────────────────────────────────────────────
    def create_template(self, payload, headers):
        return self._request("POST", "/templates", payload, headers)

    def publish_template(self, template_id, headers):
        return self._request("POST", f"/templates/{template_id}/publish", {}, headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/templates/{template_id}", headers=headers)

    def list_templates(self, headers, params=None):
        return self._request("GET", "/templates", headers=headers, params=params)

    # ─── Campaigns ──────────────────────────────────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def submit_campaign_review(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/submit-review", {}, headers)

    def review_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/review", payload, headers)

    def schedule_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/schedule", payload, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/cancel", {}, headers)

    def select_winner(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/select-winner", {}, headers)

    # ─── Sends ──────────────────────────────────────────────────────────────
    def get_send(self, send_id, headers):
        return self._request("GET", f"/sends/{send_id}", headers=headers)

    def list_sends(self, headers, params=None):
        return self._request("GET", "/sends", headers=headers, params=params)

    # ─── Journeys ───────────────────────────────────────────────────────────
    def create_journey(self, payload, headers):
        return self._request("POST", "/journeys", payload, headers)

    def get_journey(self, journey_id, headers):
        return self._request("GET", f"/journeys/{journey_id}", headers=headers)

    def list_journeys(self, headers, params=None):
        return self._request("GET", "/journeys", headers=headers, params=params)

    def activate_journey(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/activate", {}, headers)

    def pause_journey(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/pause", {}, headers)

    def list_journey_enrollments(self, journey_id, headers, params=None):
        return self._request(
            "GET", f"/journeys/{journey_id}/enrollments", headers=headers, params=params
        )

    # ─── Operator-driven endpoints ──────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def ops_run(self, headers):
        return self._request("POST", "/_ops/run", {}, headers)

    def emit_event(self, payload, headers):
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()
