"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock / sweeps (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    def run_sweeps(self, payload, headers):
        return self._request("POST", "/v1/_sweeps/run", payload, headers)

    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/plans/{plan_id}", headers=headers)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/archive", headers=headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/v1/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/v1/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/v1/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/v1/accounts/{account_id}/suspend", headers=headers)

    def unsuspend_account(self, account_id, headers):
        return self._request("POST", f"/v1/accounts/{account_id}/unsuspend", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/v1/accounts/{account_id}/close", headers=headers)

    def get_winback_eligibility(self, account_id, headers):
        return self._request(
            "GET", f"/v1/accounts/{account_id}/winback-eligibility", headers=headers
        )

    def winback_enroll(self, account_id, payload, headers):
        return self._request(
            "POST", f"/v1/accounts/{account_id}/winback-enroll", payload, headers
        )

    # --- Profiles ---
    def create_profile(self, payload, headers):
        return self._request("POST", "/v1/profiles", payload, headers)

    def list_profiles(self, headers, params=None):
        return self._request("GET", "/v1/profiles", headers=headers, params=params)

    def get_profile(self, profile_id, headers):
        return self._request("GET", f"/v1/profiles/{profile_id}", headers=headers)

    def deactivate_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/v1/profiles/{profile_id}/deactivate", headers=headers
        )

    def reactivate_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/v1/profiles/{profile_id}/reactivate", headers=headers
        )

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/v1/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/v1/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/v1/subscriptions/{subscription_id}", headers=headers
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/cancel", payload, headers
        )

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/pause", payload, headers
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/resume", headers=headers
        )

    def recover_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/recover", payload, headers
        )

    def change_plan(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/v1/subscriptions/{subscription_id}/change-plan", payload, headers
        )

    def proration_preview(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/subscriptions/{subscription_id}/proration-preview",
            headers=headers,
            params=params,
        )

    # --- Save offers ---
    def create_save_offer(self, payload, headers):
        return self._request("POST", "/v1/save-offers", payload, headers)

    def list_save_offers(self, headers, params=None):
        return self._request("GET", "/v1/save-offers", headers=headers, params=params)

    def get_save_offer(self, save_offer_id, headers):
        return self._request("GET", f"/v1/save-offers/{save_offer_id}", headers=headers)

    def accept_save_offer(self, save_offer_id, headers):
        return self._request(
            "POST", f"/v1/save-offers/{save_offer_id}/accept", headers=headers
        )

    def decline_save_offer(self, save_offer_id, headers):
        return self._request(
            "POST", f"/v1/save-offers/{save_offer_id}/decline", headers=headers
        )

    # --- Billing events ---
    def list_billing_events(self, headers, params=None):
        return self._request("GET", "/v1/billing-events", headers=headers, params=params)

    def get_billing_event(self, billing_event_id, headers):
        return self._request(
            "GET", f"/v1/billing-events/{billing_event_id}", headers=headers
        )

    def create_billing_event(self, payload, headers):
        return self._request("POST", "/v1/billing-events", payload, headers)

    # --- Price change notices ---
    def create_price_change_notice(self, payload, headers):
        return self._request("POST", "/v1/price-change-notices", payload, headers)

    def list_price_change_notices(self, headers, params=None):
        return self._request(
            "GET", "/v1/price-change-notices", headers=headers, params=params
        )

    def get_price_change_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/v1/price-change-notices/{notice_id}", headers=headers
        )

    def cancel_price_change_notice(self, notice_id, headers):
        return self._request(
            "POST", f"/v1/price-change-notices/{notice_id}/cancel", headers=headers
        )

    # --- Win-back campaigns ---
    def create_winback_campaign(self, payload, headers):
        return self._request("POST", "/v1/winback-campaigns", payload, headers)

    def list_winback_campaigns(self, headers, params=None):
        return self._request("GET", "/v1/winback-campaigns", headers=headers, params=params)

    def get_winback_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/v1/winback-campaigns/{campaign_id}", headers=headers
        )

    def activate_winback_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/v1/winback-campaigns/{campaign_id}/activate", headers=headers
        )

    def close_winback_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/v1/winback-campaigns/{campaign_id}/close", headers=headers
        )

    # --- Partner billing ---
    def create_partner_billing_record(self, payload, headers):
        return self._request("POST", "/v1/partner-billing-records", payload, headers)

    def list_partner_billing_records(self, headers, params=None):
        return self._request(
            "GET", "/v1/partner-billing-records", headers=headers, params=params
        )

    def get_partner_billing_record(self, record_id, headers):
        return self._request(
            "GET", f"/v1/partner-billing-records/{record_id}", headers=headers
        )

    def report_partner_receipt(self, record_id, payload, headers):
        return self._request(
            "POST",
            f"/v1/partner-billing-records/{record_id}/report-receipt",
            payload,
            headers,
        )

    def reconcile_partner_record(self, record_id, payload, headers):
        return self._request(
            "POST",
            f"/v1/partner-billing-records/{record_id}/reconcile",
            payload,
            headers,
        )

    def write_off_partner_record(self, record_id, headers):
        return self._request(
            "POST", f"/v1/partner-billing-records/{record_id}/write-off", headers=headers
        )

    # --- Signup attributions ---
    def list_signup_attributions(self, headers, params=None):
        return self._request(
            "GET", "/v1/signup-attributions", headers=headers, params=params
        )

    def get_signup_attribution(self, attribution_id, headers):
        return self._request(
            "GET", f"/v1/signup-attributions/{attribution_id}", headers=headers
        )


api_client = ApiClient()
