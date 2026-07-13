"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/idp"


class ApiClient(GenericApiClient):
    # ---- Plans -------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/plans/{plan_id}", headers=headers)

    # ---- Subscribers -------------------------------------------------------
    def enroll_subscriber(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscribers", payload, headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"{PREFIX}/subscribers/{subscriber_id}", headers=headers)

    def verify_subscriber(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscribers/{subscriber_id}/verify", payload, headers
        )

    def suspend_subscriber(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscribers/{subscriber_id}/suspend", payload, headers
        )

    def reactivate_subscriber(self, subscriber_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subscribers/{subscriber_id}/reactivate", {}, headers
        )

    def get_credit_summary(self, subscriber_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscribers/{subscriber_id}/credit-summary", headers=headers
        )

    # ---- Family members ----------------------------------------------------
    def create_family_member(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscribers/{subscriber_id}/family-members", payload, headers
        )

    def list_family_members(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscribers/{subscriber_id}/family-members",
            headers=headers,
            params=params,
        )

    # ---- Bureau profiles ---------------------------------------------------
    def list_bureau_profiles(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscribers/{subscriber_id}/bureau-profiles",
            headers=headers,
            params=params,
        )

    def get_bureau_profile(self, profile_id, headers):
        return self._request("GET", f"{PREFIX}/bureau-profiles/{profile_id}", headers=headers)

    def score_refresh(self, profile_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bureau-profiles/{profile_id}/score-refresh", payload, headers
        )

    def freeze_request(self, profile_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bureau-profiles/{profile_id}/freeze-request", payload, headers
        )

    def confirm_bureau_profile(self, profile_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bureau-profiles/{profile_id}/confirm", {}, headers
        )

    def create_thaw_window(self, profile_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bureau-profiles/{profile_id}/thaw-windows", payload, headers
        )

    def list_thaw_windows(self, profile_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/bureau-profiles/{profile_id}/thaw-windows",
            headers=headers,
            params=params,
        )

    # ---- Wallet ------------------------------------------------------------
    def create_wallet_item(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscribers/{subscriber_id}/wallet-items", payload, headers
        )

    def list_wallet_items(self, subscriber_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscribers/{subscriber_id}/wallet-items",
            headers=headers,
            params=params,
        )

    def report_wallet_item_lost(self, wallet_item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/wallet-items/{wallet_item_id}/report-lost", {}, headers
        )

    # ---- Alerts ------------------------------------------------------------
    def create_alert(self, payload, headers):
        return self._request("POST", f"{PREFIX}/alerts", payload, headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"{PREFIX}/alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, alert_id, headers):
        return self._request("POST", f"{PREFIX}/alerts/{alert_id}/acknowledge", {}, headers)

    def confirm_fraud_alert(self, alert_id, headers):
        return self._request("POST", f"{PREFIX}/alerts/{alert_id}/confirm-fraud", {}, headers)

    def dismiss_alert(self, alert_id, payload, headers):
        return self._request("POST", f"{PREFIX}/alerts/{alert_id}/dismiss", payload, headers)

    def escalate_alert(self, alert_id, headers):
        return self._request("POST", f"{PREFIX}/alerts/{alert_id}/escalate", {}, headers)

    # ---- Restoration cases -------------------------------------------------
    def list_restoration_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/restoration-cases", headers=headers, params=params
        )

    def get_restoration_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/restoration-cases/{case_id}", headers=headers)

    def assign_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/restoration-cases/{case_id}/assign", payload, headers
        )

    def request_info(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/restoration-cases/{case_id}/request-info", payload, headers
        )

    def provide_info(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/restoration-cases/{case_id}/provide-info", payload, headers
        )

    def resolve_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/restoration-cases/{case_id}/resolve", payload, headers
        )

    # ---- Specialists -------------------------------------------------------
    def create_specialist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specialists", payload, headers)

    def get_specialist(self, specialist_id, headers):
        return self._request("GET", f"{PREFIX}/specialists/{specialist_id}", headers=headers)

    def create_engagement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specialist-engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/specialist-engagements", headers=headers, params=params
        )

    def get_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/specialist-engagements/{engagement_id}", headers=headers
        )

    # ---- Insurance claims --------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insurance-claims", headers=headers, params=params
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/insurance-claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-claims/{claim_id}/submit", {}, headers
        )

    def approve_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-claims/{claim_id}/approve", {}, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-claims/{claim_id}/deny", payload, headers
        )

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/insurance-claims/{claim_id}/pay", {}, headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-claims/{claim_id}/reverse", payload, headers
        )

    # ---- Logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()