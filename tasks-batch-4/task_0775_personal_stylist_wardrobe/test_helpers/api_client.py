"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Provisioning / identity ----
    def create_stylist(self, payload, headers):
        return self._request("POST", "/styling/stylists", payload, headers)

    def get_stylist(self, stylist_id, headers):
        return self._request("GET", f"/styling/stylists/{stylist_id}", headers=headers)

    def register_client(self, payload, headers):
        return self._request("POST", "/styling/clients/register", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/styling/clients/{client_id}", headers=headers)

    # ---- Style assessment ----
    def create_assessment(self, client_id, payload, headers):
        return self._request("POST", f"/styling/clients/{client_id}/assessments", payload, headers)

    def list_assessments(self, client_id, headers, params=None):
        return self._request("GET", f"/styling/clients/{client_id}/assessments", headers=headers, params=params)

    def complete_assessment(self, assessment_id, headers):
        return self._request("POST", f"/styling/assessments/{assessment_id}/complete", {}, headers)

    # ---- Engagements ----
    def create_engagement(self, payload, headers):
        return self._request("POST", "/styling/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/styling/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/styling/engagements", headers=headers, params=params)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/styling/engagements/{engagement_id}/activate", {}, headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request("POST", f"/styling/engagements/{engagement_id}/cancel", {}, headers)

    # ---- Sessions ----
    def create_session(self, engagement_id, payload, headers):
        return self._request("POST", f"/styling/engagements/{engagement_id}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/styling/sessions/{session_id}", headers=headers)

    def list_sessions(self, engagement_id, headers, params=None):
        return self._request("GET", f"/styling/engagements/{engagement_id}/sessions", headers=headers, params=params)

    def confirm_session(self, session_id, headers):
        return self._request("POST", f"/styling/sessions/{session_id}/confirm", {}, headers)

    def reschedule_session(self, session_id, payload, headers):
        return self._request("POST", f"/styling/sessions/{session_id}/reschedule", payload, headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/styling/sessions/{session_id}/complete", payload, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/styling/sessions/{session_id}/cancel", {}, headers)

    # ---- Purchases ----
    def create_item(self, session_id, payload, headers):
        return self._request("POST", f"/styling/sessions/{session_id}/items", payload, headers)

    def list_items(self, session_id, headers, params=None):
        return self._request("GET", f"/styling/sessions/{session_id}/items", headers=headers, params=params)

    def return_item(self, item_id, headers):
        return self._request("POST", f"/styling/purchase-items/{item_id}/return", {}, headers)

    # ---- Lookbooks & outfits ----
    def create_lookbook(self, engagement_id, payload, headers):
        return self._request("POST", f"/styling/engagements/{engagement_id}/lookbooks", payload, headers)

    def get_lookbook(self, lookbook_id, headers):
        return self._request("GET", f"/styling/lookbooks/{lookbook_id}", headers=headers)

    def list_lookbooks(self, engagement_id, headers, params=None):
        return self._request("GET", f"/styling/engagements/{engagement_id}/lookbooks", headers=headers, params=params)

    def add_outfit(self, lookbook_id, payload, headers):
        return self._request("POST", f"/styling/lookbooks/{lookbook_id}/outfits", payload, headers)

    def deliver_lookbook(self, lookbook_id, headers):
        return self._request("POST", f"/styling/lookbooks/{lookbook_id}/deliver", {}, headers)

    def accept_lookbook(self, lookbook_id, headers):
        return self._request("POST", f"/styling/lookbooks/{lookbook_id}/accept", {}, headers)

    def request_revision(self, lookbook_id, payload, headers):
        return self._request("POST", f"/styling/lookbooks/{lookbook_id}/request-revision", payload, headers)

    # ---- Subscriptions ----
    def create_subscription(self, client_id, payload, headers):
        return self._request("POST", f"/styling/clients/{client_id}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/styling/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, client_id, headers, params=None):
        return self._request("GET", f"/styling/clients/{client_id}/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/styling/subscriptions/{subscription_id}/activate", {}, headers)

    def redeem_refresh(self, subscription_id, headers):
        return self._request("POST", f"/styling/subscriptions/{subscription_id}/redeem-refresh", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/styling/subscriptions/{subscription_id}/cancel", {}, headers)

    # ---- Referrals ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/styling/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/styling/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/styling/referrals", headers=headers, params=params)

    def signup_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/styling/referrals/{referral_id}/signup", payload, headers)

    # ---- Invoices ----
    def create_invoice(self, engagement_id, headers):
        return self._request("POST", f"/styling/engagements/{engagement_id}/invoices", {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/styling/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, engagement_id, headers, params=None):
        return self._request("GET", f"/styling/engagements/{engagement_id}/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/styling/invoices/{invoice_id}/pay", {}, headers)

    # ---- Admin / test-driving ----
    def adjust_wallet(self, client_id, payload, headers):
        return self._request("POST", f"/styling/clients/{client_id}/wallet/adjustments", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
