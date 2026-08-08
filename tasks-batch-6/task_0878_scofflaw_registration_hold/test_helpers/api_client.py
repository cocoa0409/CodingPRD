"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Owner ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- HearingOfficer ----
    def create_hearing_officer(self, payload, headers):
        return self._request("POST", "/hearing-officers", payload, headers)

    def list_hearing_officers(self, headers, params=None):
        return self._request("GET", "/hearing-officers", headers=headers, params=params)

    # ---- TowYard ----
    def create_tow_yard(self, payload, headers):
        return self._request("POST", "/tow-yards", payload, headers)

    def list_tow_yards(self, headers, params=None):
        return self._request("GET", "/tow-yards", headers=headers, params=params)

    # ---- ScofflawCase ----
    def create_case(self, payload, headers):
        return self._request("POST", "/scofflaw-cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/scofflaw-cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/scofflaw-cases", headers=headers, params=params)

    def place_hold(self, case_id, headers, payload=None):
        return self._request("POST", f"/scofflaw-cases/{case_id}/place-hold", payload or {}, headers)

    def release_hold(self, case_id, headers, payload=None):
        return self._request("POST", f"/scofflaw-cases/{case_id}/release-hold", payload or {}, headers)

    # ---- Violation ----
    def create_violation(self, case_id, payload, headers):
        return self._request("POST", f"/scofflaw-cases/{case_id}/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    # ---- Dispute ----
    def create_dispute(self, violation_id, payload, headers):
        return self._request("POST", f"/violations/{violation_id}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def schedule_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/schedule", payload, headers)

    def reschedule_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reschedule", payload, headers)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/decide", payload, headers)

    def withdraw_dispute(self, dispute_id, headers, payload=None):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", payload or {}, headers)

    # ---- Payment ----
    def create_payment(self, case_id, payload, headers):
        return self._request("POST", f"/scofflaw-cases/{case_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---- PaymentPlan ----
    def create_payment_plan(self, case_id, payload, headers):
        return self._request("POST", f"/scofflaw-cases/{case_id}/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def record_installment(self, plan_id, payload, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/record-installment", payload, headers)

    def default_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/payment-plans/{plan_id}/default", payload or {}, headers)

    def reinstate_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/payment-plans/{plan_id}/reinstate", payload or {}, headers)

    # ---- BootTowOrder ----
    def create_boot_tow_order(self, case_id, payload, headers):
        return self._request("POST", f"/scofflaw-cases/{case_id}/boot-tow-orders", payload, headers)

    def get_boot_tow_order(self, order_id, headers):
        return self._request("GET", f"/boot-tow-orders/{order_id}", headers=headers)

    def list_boot_tow_orders(self, headers, params=None):
        return self._request("GET", "/boot-tow-orders", headers=headers, params=params)

    def apply_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/boot-tow-orders/{order_id}/apply", payload or {}, headers)

    def pay_release_fee(self, order_id, payload, headers):
        return self._request("POST", f"/boot-tow-orders/{order_id}/pay-release-fee", payload, headers)

    def release_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/boot-tow-orders/{order_id}/release", payload or {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/boot-tow-orders/{order_id}/cancel", payload or {}, headers)

    # ---- HardshipWaiver ----
    def create_hardship_waiver(self, case_id, payload, headers):
        return self._request("POST", f"/scofflaw-cases/{case_id}/hardship-waivers", payload, headers)

    def get_hardship_waiver(self, waiver_id, headers):
        return self._request("GET", f"/hardship-waivers/{waiver_id}", headers=headers)

    def list_hardship_waivers(self, headers, params=None):
        return self._request("GET", "/hardship-waivers", headers=headers, params=params)

    def decide_hardship_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/hardship-waivers/{waiver_id}/decide", payload, headers)

    # ---- CollectionsReferral ----
    def create_collections_referral(self, case_id, payload, headers):
        return self._request("POST", f"/scofflaw-cases/{case_id}/collections-referrals", payload, headers)

    def get_collections_referral(self, referral_id, headers):
        return self._request("GET", f"/collections-referrals/{referral_id}", headers=headers)

    def list_collections_referrals(self, headers, params=None):
        return self._request("GET", "/collections-referrals", headers=headers, params=params)

    def recall_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/collections-referrals/{referral_id}/recall", payload or {}, headers)

    def settle_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/collections-referrals/{referral_id}/settle", payload, headers)

    # ---- Reporting ----
    def get_scofflaw_summary(self, headers, params=None):
        return self._request("GET", "/reports/scofflaw-summary", headers=headers, params=params)


api_client = ApiClient()
