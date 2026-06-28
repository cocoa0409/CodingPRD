"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock (test-driving) ──────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Policyholder ──────────────────────────────────────────────────────
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/policyholders/{policyholder_id}", headers=headers)

    # ── RiskZone ──────────────────────────────────────────────────────────
    def create_risk_zone(self, payload, headers):
        return self._request("POST", "/risk-zones", payload, headers)

    def get_risk_zone(self, risk_zone_id, headers):
        return self._request("GET", f"/risk-zones/{risk_zone_id}", headers=headers)

    # ── RepairShop ────────────────────────────────────────────────────────
    def create_repair_shop(self, payload, headers):
        return self._request("POST", "/repair-shops", payload, headers)

    def get_repair_shop(self, repair_shop_id, headers):
        return self._request("GET", f"/repair-shops/{repair_shop_id}", headers=headers)

    def suspend_repair_shop(self, repair_shop_id, headers):
        return self._request(
            "POST", f"/repair-shops/{repair_shop_id}/suspend", headers=headers
        )

    # ── Appraisal ─────────────────────────────────────────────────────────
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    # ── Policy ────────────────────────────────────────────────────────────
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/bind", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", headers=headers)

    # ── ScheduledItem ─────────────────────────────────────────────────────
    def create_scheduled_item(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/scheduled-items", payload, headers
        )

    def get_scheduled_item(self, item_id, headers):
        return self._request("GET", f"/scheduled-items/{item_id}", headers=headers)

    def list_scheduled_items(self, headers, params=None):
        return self._request("GET", "/scheduled-items", headers=headers, params=params)

    # ── Endorsement ───────────────────────────────────────────────────────
    def create_endorsement(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/endorsements", payload, headers
        )

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/endorsements/{endorsement_id}", headers=headers)

    def list_endorsements(self, headers, params=None):
        return self._request("GET", "/endorsements", headers=headers, params=params)

    def apply_endorsement(self, policy_id, endorsement_id, payload, headers):
        return self._request(
            "POST",
            f"/policies/{policy_id}/endorsements/{endorsement_id}/apply",
            payload,
            headers,
        )

    def reject_endorsement(self, policy_id, endorsement_id, headers):
        return self._request(
            "POST",
            f"/policies/{policy_id}/endorsements/{endorsement_id}/reject",
            headers=headers,
        )

    # ── Claim ─────────────────────────────────────────────────────────────
    def create_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def start_review_claim(self, policy_id, claim_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/start_review", headers=headers
        )

    def request_info_claim(self, policy_id, claim_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/request_info", headers=headers
        )

    def provide_info_claim(self, policy_id, claim_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/provide_info", headers=headers
        )

    def approve_claim(self, policy_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/approve", payload, headers
        )

    def deny_claim(self, policy_id, claim_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/deny", headers=headers
        )

    def settle_claim(self, policy_id, claim_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/settle", headers=headers
        )

    def close_claim(self, policy_id, claim_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/close", headers=headers
        )

    # ── RepairOrder ───────────────────────────────────────────────────────
    def assign_repair_order(self, policy_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims/{claim_id}/repair-order", payload, headers
        )

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def accept_repair_order(self, policy_id, claim_id, headers):
        return self._request(
            "POST",
            f"/policies/{policy_id}/claims/{claim_id}/repair-order/accept",
            headers=headers,
        )

    def complete_repair_order(self, policy_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/policies/{policy_id}/claims/{claim_id}/repair-order/complete",
            payload,
            headers,
        )

    def deem_total_loss_repair_order(self, policy_id, claim_id, headers):
        return self._request(
            "POST",
            f"/policies/{policy_id}/claims/{claim_id}/repair-order/deem_total_loss",
            headers=headers,
        )

    # ── PremiumPayment ────────────────────────────────────────────────────
    def create_payment(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/premium-payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/premium-payments", headers=headers, params=params)

    def reverse_payment(self, policy_id, payment_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/payments/{payment_id}/reverse", headers=headers
        )


api_client = ApiClient()
