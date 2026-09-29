"""API client: one method per endpoint the PRD declares.

Every business resource is mounted under ``/loyalty``; the logical clock lives at
``/_clock/set_current_utc``.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_hotel(self, payload, headers):
        return self._request("POST", "/loyalty/hotels", payload, headers)

    def activate_hotel(self, hotel_id, headers, payload=None):
        return self._request(
            "POST", f"/loyalty/hotels/{hotel_id}/activate", payload or {}, headers
        )

    def refresh_hotel_performance(self, hotel_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/hotels/{hotel_id}/performance-refresh", payload, headers
        )

    def terminate_hotel(self, hotel_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/hotels/{hotel_id}/terminate", payload, headers
        )

    def get_hotel(self, hotel_id, headers):
        return self._request("GET", f"/loyalty/hotels/{hotel_id}", headers=headers)

    def list_hotels(self, headers, params=None):
        return self._request("GET", "/loyalty/hotels", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Rate plans
    # ------------------------------------------------------------------
    def create_rate_plan(self, hotel_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/hotels/{hotel_id}/rate-plans", payload, headers
        )

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request(
            "GET", f"/loyalty/rate-plans/{rate_plan_id}", headers=headers
        )

    def list_rate_plans(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/rate-plans", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Award price windows
    # ------------------------------------------------------------------
    def create_redemption_pricing(self, hotel_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/hotels/{hotel_id}/redemption-pricing", payload, headers
        )

    def get_redemption_pricing(self, pricing_id, headers):
        return self._request(
            "GET", f"/loyalty/redemption-pricing/{pricing_id}", headers=headers
        )

    def list_redemption_pricing(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/redemption-pricing", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Blackout windows
    # ------------------------------------------------------------------
    def create_blackout_window(self, hotel_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/hotels/{hotel_id}/blackout-windows", payload, headers
        )

    def activate_blackout_window(self, window_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/blackout-windows/{window_id}/activate",
            payload or {},
            headers,
        )

    def revoke_blackout_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/blackout-windows/{window_id}/revoke", payload, headers
        )

    def get_blackout_window(self, window_id, headers):
        return self._request(
            "GET", f"/loyalty/blackout-windows/{window_id}", headers=headers
        )

    def list_blackout_windows(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/blackout-windows", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/loyalty/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/loyalty/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/loyalty/members", headers=headers, params=params)

    def create_point_adjustment(self, payload, headers):
        return self._request("POST", "/loyalty/point-adjustments", payload, headers)

    # ------------------------------------------------------------------
    # Paid stays
    # ------------------------------------------------------------------
    def create_stay(self, payload, headers):
        return self._request("POST", "/loyalty/stays", payload, headers)

    def post_stay(self, stay_id, headers, payload=None):
        return self._request(
            "POST", f"/loyalty/stays/{stay_id}/post", payload or {}, headers
        )

    def dispute_stay(self, stay_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/stays/{stay_id}/dispute", payload, headers
        )

    def adjust_stay(self, stay_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/stays/{stay_id}/adjust", payload or {}, headers
        )

    def void_stay(self, stay_id, payload, headers):
        return self._request("POST", f"/loyalty/stays/{stay_id}/void", payload, headers)

    def get_stay(self, stay_id, headers):
        return self._request("GET", f"/loyalty/stays/{stay_id}", headers=headers)

    def list_stays(self, headers, params=None):
        return self._request("GET", "/loyalty/stays", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Elite benefit obligations
    # ------------------------------------------------------------------
    def deliver_benefit(self, delivery_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/elite-benefit-deliveries/{delivery_id}/deliver",
            payload or {},
            headers,
        )

    def deny_benefit(self, delivery_id, payload, headers):
        return self._request(
            "POST",
            f"/loyalty/elite-benefit-deliveries/{delivery_id}/deny",
            payload,
            headers,
        )

    def get_benefit_delivery(self, delivery_id, headers):
        return self._request(
            "GET", f"/loyalty/elite-benefit-deliveries/{delivery_id}", headers=headers
        )

    def list_benefit_deliveries(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/elite-benefit-deliveries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Award bookings
    # ------------------------------------------------------------------
    def create_redemption(self, payload, headers):
        return self._request("POST", "/loyalty/redemptions", payload, headers)

    def confirm_redemption(self, redemption_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/redemptions/{redemption_id}/confirm",
            payload or {},
            headers,
        )

    def complete_redemption_stay(self, redemption_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/redemptions/{redemption_id}/complete-stay",
            payload or {},
            headers,
        )

    def no_show_redemption(self, redemption_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/redemptions/{redemption_id}/no-show",
            payload or {},
            headers,
        )

    def cancel_redemption(self, redemption_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/redemptions/{redemption_id}/cancel", payload, headers
        )

    def get_redemption(self, redemption_id, headers):
        return self._request(
            "GET", f"/loyalty/redemptions/{redemption_id}", headers=headers
        )

    def list_redemptions(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/redemptions", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Reimbursement batches
    # ------------------------------------------------------------------
    def create_reimbursement_batch(self, payload, headers):
        return self._request("POST", "/loyalty/reimbursement-batches", payload, headers)

    def release_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/reimbursement-batches/{batch_id}/release",
            payload or {},
            headers,
        )

    def approve_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/reimbursement-batches/{batch_id}/approve",
            payload or {},
            headers,
        )

    def reject_batch(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/loyalty/reimbursement-batches/{batch_id}/reject",
            payload,
            headers,
        )

    def pay_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/reimbursement-batches/{batch_id}/pay",
            payload or {},
            headers,
        )

    def get_reimbursement_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/loyalty/reimbursement-batches/{batch_id}", headers=headers
        )

    def list_reimbursement_batches(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/reimbursement-batches", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Point ledger
    # ------------------------------------------------------------------
    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/loyalty/point-ledger-entries/{entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/point-ledger-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Partners and point purchases
    # ------------------------------------------------------------------
    def create_partner(self, payload, headers):
        return self._request("POST", "/loyalty/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/loyalty/partners/{partner_id}", headers=headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", "/loyalty/partners", headers=headers, params=params)

    def create_point_purchase(self, payload, headers):
        return self._request("POST", "/loyalty/point-purchases", payload, headers)

    def settle_point_purchase(self, purchase_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/point-purchases/{purchase_id}/settle",
            payload or {},
            headers,
        )

    def refund_point_purchase(self, purchase_id, payload, headers):
        return self._request(
            "POST", f"/loyalty/point-purchases/{purchase_id}/refund", payload, headers
        )

    def get_point_purchase(self, purchase_id, headers):
        return self._request(
            "GET", f"/loyalty/point-purchases/{purchase_id}", headers=headers
        )

    def list_point_purchases(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/point-purchases", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Programme fund
    # ------------------------------------------------------------------
    def get_program_fund(self, headers):
        return self._request("GET", "/loyalty/program-fund", headers=headers)

    def revalue_program_fund(self, headers, payload=None):
        return self._request(
            "POST", "/loyalty/program-fund/revalue", payload or {}, headers
        )

    def set_breakage_rate(self, payload, headers):
        return self._request(
            "POST", "/loyalty/program-fund/breakage-rate", payload, headers
        )

    # ------------------------------------------------------------------
    # Member complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/loyalty/member-complaints", payload, headers)

    def review_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/member-complaints/{complaint_id}/review",
            payload or {},
            headers,
        )

    def request_complaint_info(self, complaint_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/member-complaints/{complaint_id}/request-info",
            payload or {},
            headers,
        )

    def provide_complaint_info(self, complaint_id, payload, headers):
        return self._request(
            "POST",
            f"/loyalty/member-complaints/{complaint_id}/provide-info",
            payload or {},
            headers,
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST",
            f"/loyalty/member-complaints/{complaint_id}/resolve",
            payload,
            headers,
        )

    def escalate_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loyalty/member-complaints/{complaint_id}/escalate",
            payload or {},
            headers,
        )

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST",
            f"/loyalty/member-complaints/{complaint_id}/adjudicate",
            payload,
            headers,
        )

    def get_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"/loyalty/member-complaints/{complaint_id}", headers=headers
        )

    def list_complaints(self, headers, params=None):
        return self._request(
            "GET", "/loyalty/member-complaints", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Logical programme clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()
