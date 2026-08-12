"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    # ------------------------------------------------------- drop points ---
    def create_drop_point(self, payload, headers):
        return self._request("POST", "/drop-points", payload, headers)

    def list_drop_points(self, headers, params=None):
        return self._request("GET", "/drop-points", headers=headers, params=params)

    def get_drop_point(self, drop_point_id, headers):
        return self._request(
            "GET", f"/drop-points/{drop_point_id}", headers=headers
        )

    # ------------------------------------------------------------- items ---
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def discontinue_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/discontinue", {}, headers)

    # ---------------------------------------------------- price versions ---
    def create_price_version(self, payload, headers):
        return self._request("POST", "/price-versions", payload, headers)

    def list_price_versions(self, headers, params=None):
        return self._request("GET", "/price-versions", headers=headers, params=params)

    def get_price_version(self, price_version_id, headers):
        return self._request(
            "GET", f"/price-versions/{price_version_id}", headers=headers
        )

    # ----------------------------------------------------------- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def pay_dues(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/dues-payments", payload, headers
        )

    def change_tier(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/tier-changes", payload, headers
        )

    def lapse_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/lapse", {}, headers)

    # ------------------------------------------------------------ cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def lock_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/lock", {}, headers)

    def submit_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/submit", {}, headers)

    def receive_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/receive", {}, headers)

    def consolidate_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/consolidate", {}, headers)

    def deliver_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/deliver", {}, headers)

    def reconcile_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/reconcile", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/close", {}, headers)

    def cancel_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/cancel", {}, headers)

    # -------------------------------------------------------- route runs ---
    def list_route_runs(self, headers, params=None):
        return self._request("GET", "/route-runs", headers=headers, params=params)

    def get_route_run(self, route_run_id, headers):
        return self._request("GET", f"/route-runs/{route_run_id}", headers=headers)

    def record_supplier_invoice(self, route_run_id, payload, headers):
        return self._request(
            "POST", f"/route-runs/{route_run_id}/supplier-invoice", payload, headers
        )

    def build_pallets(self, route_run_id, headers):
        return self._request(
            "POST", f"/route-runs/{route_run_id}/build-pallets", {}, headers
        )

    # --------------------------------------------------------- drop runs ---
    def create_drop_run(self, payload, headers):
        return self._request("POST", "/drop-runs", payload, headers)

    def list_drop_runs(self, headers, params=None):
        return self._request("GET", "/drop-runs", headers=headers, params=params)

    def get_drop_run(self, drop_run_id, headers):
        return self._request("GET", f"/drop-runs/{drop_run_id}", headers=headers)

    def merge_drop_run(self, drop_run_id, payload, headers):
        return self._request(
            "POST", f"/drop-runs/{drop_run_id}/merge", payload, headers
        )

    def roll_forward_drop_run(self, drop_run_id, payload, headers):
        return self._request(
            "POST", f"/drop-runs/{drop_run_id}/roll-forward", payload, headers
        )

    # ----------------------------------------------------- member orders ---
    def create_member_order(self, payload, headers):
        return self._request("POST", "/member-orders", payload, headers)

    def list_member_orders(self, headers, params=None):
        return self._request("GET", "/member-orders", headers=headers, params=params)

    def get_member_order(self, member_order_id, headers):
        return self._request(
            "GET", f"/member-orders/{member_order_id}", headers=headers
        )

    def submit_member_order(self, member_order_id, headers):
        return self._request(
            "POST", f"/member-orders/{member_order_id}/submit", {}, headers
        )

    def cancel_member_order(self, member_order_id, headers):
        return self._request(
            "POST", f"/member-orders/{member_order_id}/cancel", {}, headers
        )

    def authorize_member_order(self, member_order_id, payload, headers):
        return self._request(
            "POST", f"/member-orders/{member_order_id}/authorize", payload, headers
        )

    def capture_member_order(self, member_order_id, payload, headers):
        return self._request(
            "POST", f"/member-orders/{member_order_id}/capture", payload, headers
        )

    def refund_member_order(self, member_order_id, payload, headers):
        return self._request(
            "POST", f"/member-orders/{member_order_id}/refund", payload, headers
        )

    # ------------------------------------------------------- order lines ---
    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def patch_order_line(self, order_line_id, payload, headers):
        return self._request(
            "PATCH", f"/order-lines/{order_line_id}", payload, headers
        )

    def cancel_order_line(self, order_line_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{order_line_id}/cancel", payload, headers
        )

    # --------------------------------------------------- case aggregates ---
    def list_case_aggregates(self, headers, params=None):
        return self._request("GET", "/case-aggregates", headers=headers, params=params)

    def get_case_aggregate(self, case_aggregate_id, headers):
        return self._request(
            "GET", f"/case-aggregates/{case_aggregate_id}", headers=headers
        )

    # ----------------------------------------------------- receipt lines ---
    def create_receipt_line(self, payload, headers):
        return self._request("POST", "/receipt-lines", payload, headers)

    def list_receipt_lines(self, headers, params=None):
        return self._request("GET", "/receipt-lines", headers=headers, params=params)

    def get_receipt_line(self, receipt_line_id, headers):
        return self._request(
            "GET", f"/receipt-lines/{receipt_line_id}", headers=headers
        )

    # ----------------------------------------------- substitution offers ---
    def list_substitution_offers(self, headers, params=None):
        return self._request(
            "GET", "/substitution-offers", headers=headers, params=params
        )

    def get_substitution_offer(self, substitution_offer_id, headers):
        return self._request(
            "GET", f"/substitution-offers/{substitution_offer_id}", headers=headers
        )

    def approve_substitution_offer(self, substitution_offer_id, headers):
        return self._request(
            "POST",
            f"/substitution-offers/{substitution_offer_id}/approve",
            {},
            headers,
        )

    def decline_substitution_offer(self, substitution_offer_id, headers):
        return self._request(
            "POST",
            f"/substitution-offers/{substitution_offer_id}/decline",
            {},
            headers,
        )

    # ----------------------------------------------------------- pallets ---
    def list_pallets(self, headers, params=None):
        return self._request("GET", "/pallets", headers=headers, params=params)

    def get_pallet(self, pallet_id, headers):
        return self._request("GET", f"/pallets/{pallet_id}", headers=headers)

    def seal_pallet(self, pallet_id, headers):
        return self._request("POST", f"/pallets/{pallet_id}/seal", {}, headers)

    # ---------------------------------------------------------- payments ---
    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ------------------------------------------------ drop reconciliations --
    def create_drop_reconciliation(self, payload, headers):
        return self._request("POST", "/drop-reconciliations", payload, headers)

    def list_drop_reconciliations(self, headers, params=None):
        return self._request(
            "GET", "/drop-reconciliations", headers=headers, params=params
        )

    def get_drop_reconciliation(self, drop_reconciliation_id, headers):
        return self._request(
            "GET", f"/drop-reconciliations/{drop_reconciliation_id}", headers=headers
        )

    def post_drop_reconciliation(self, drop_reconciliation_id, headers):
        return self._request(
            "POST",
            f"/drop-reconciliations/{drop_reconciliation_id}/post",
            {},
            headers,
        )

    def resolve_reconciliation_variance(self, drop_reconciliation_id, payload, headers):
        return self._request(
            "POST",
            f"/drop-reconciliations/{drop_reconciliation_id}/resolve-variance",
            payload,
            headers,
        )

    # ------------------------------------------------ commission accruals --
    def list_commission_accruals(self, headers, params=None):
        return self._request(
            "GET", "/commission-accruals", headers=headers, params=params
        )

    def get_commission_accrual(self, commission_accrual_id, headers):
        return self._request(
            "GET", f"/commission-accruals/{commission_accrual_id}", headers=headers
        )

    def payout_commission_accrual(self, commission_accrual_id, payload, headers):
        return self._request(
            "POST",
            f"/commission-accruals/{commission_accrual_id}/payout",
            payload,
            headers,
        )

    # -------------------------------------------------- volunteer shifts ---
    def create_volunteer_shift(self, payload, headers):
        return self._request("POST", "/volunteer-shifts", payload, headers)

    def list_volunteer_shifts(self, headers, params=None):
        return self._request(
            "GET", "/volunteer-shifts", headers=headers, params=params
        )

    def get_volunteer_shift(self, volunteer_shift_id, headers):
        return self._request(
            "GET", f"/volunteer-shifts/{volunteer_shift_id}", headers=headers
        )

    def verify_volunteer_shift(self, volunteer_shift_id, headers):
        return self._request(
            "POST", f"/volunteer-shifts/{volunteer_shift_id}/verify", {}, headers
        )

    def reject_volunteer_shift(self, volunteer_shift_id, headers):
        return self._request(
            "POST", f"/volunteer-shifts/{volunteer_shift_id}/reject", {}, headers
        )

    # ----------------------------------------------------- credit grants ---
    def create_credit_grant(self, payload, headers):
        return self._request("POST", "/credit-grants", payload, headers)

    def list_credit_grants(self, headers, params=None):
        return self._request("GET", "/credit-grants", headers=headers, params=params)

    def get_credit_grant(self, credit_grant_id, headers):
        return self._request(
            "GET", f"/credit-grants/{credit_grant_id}", headers=headers
        )

    # ------------------------------------------------------ logical clock --
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
