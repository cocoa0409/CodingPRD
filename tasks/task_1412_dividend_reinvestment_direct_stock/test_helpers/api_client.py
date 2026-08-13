"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/drip/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/drip/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/drip/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/drip/plans/{plan_id}", headers=headers)

    def patch_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/drip/plans/{plan_id}", payload, headers)

    def publish_plan(self, plan_id, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/publish", {}, headers)

    def suspend_plan(self, plan_id, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/suspend", {}, headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/resume", {}, headers)

    def terminate_plan(self, plan_id, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/drip/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/drip/participants/{participant_id}", headers=headers)

    def list_participant_enrollments(self, participant_id, headers, params=None):
        return self._request("GET", f"/drip/participants/{participant_id}/enrollments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Enrollments
    # ------------------------------------------------------------------
    def create_enrollment(self, plan_id, payload, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/enrollments", payload, headers)

    def list_plan_enrollments(self, plan_id, headers, params=None):
        return self._request("GET", f"/drip/plans/{plan_id}/enrollments",
                             headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/drip/enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/drip/enrollments/{enrollment_id}/activate", {}, headers)

    def change_election(self, enrollment_id, payload, headers):
        return self._request("PATCH", f"/drip/enrollments/{enrollment_id}/election",
                             payload, headers)

    def terminate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/drip/enrollments/{enrollment_id}/terminate",
                             payload, headers)

    def create_deposit(self, enrollment_id, payload, headers):
        return self._request("POST", f"/drip/enrollments/{enrollment_id}/deposits",
                             payload, headers)

    def list_ledger_entries(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/drip/enrollments/{enrollment_id}/ledger-entries",
                             headers=headers, params=params)

    def list_tax_lots(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/drip/enrollments/{enrollment_id}/tax-lots",
                             headers=headers, params=params)

    def list_fees(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/drip/enrollments/{enrollment_id}/fees",
                             headers=headers, params=params)

    def list_enrollment_transfers(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/drip/enrollments/{enrollment_id}/transfers",
                             headers=headers, params=params)

    def get_tax_report(self, enrollment_id, year, headers):
        return self._request("GET", f"/drip/enrollments/{enrollment_id}/tax-report",
                             payload={"year": year}, headers=headers)

    # ------------------------------------------------------------------
    # Fee assessments
    # ------------------------------------------------------------------
    def waive_fee(self, fee_id, reason, headers):
        return self._request("POST", f"/drip/fee-assessments/{fee_id}/waive",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Dividend events
    # ------------------------------------------------------------------
    def create_dividend_event(self, plan_id, payload, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/dividend-events",
                             payload, headers)

    def list_dividend_events(self, plan_id, headers, params=None):
        return self._request("GET", f"/drip/plans/{plan_id}/dividend-events",
                             headers=headers, params=params)

    def price_dividend_event(self, dividend_id, payload, headers):
        return self._request("POST", f"/drip/dividend-events/{dividend_id}/price",
                             payload, headers)

    def execute_dividend_event(self, dividend_id, headers):
        return self._request("POST", f"/drip/dividend-events/{dividend_id}/execute",
                             {}, headers)

    def settle_dividend_event(self, dividend_id, headers):
        return self._request("POST", f"/drip/dividend-events/{dividend_id}/settle",
                             {}, headers)

    # ------------------------------------------------------------------
    # Purchase windows
    # ------------------------------------------------------------------
    def create_purchase_window(self, plan_id, payload, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/purchase-windows",
                             payload, headers)

    def list_purchase_windows(self, plan_id, headers, params=None):
        return self._request("GET", f"/drip/plans/{plan_id}/purchase-windows",
                             headers=headers, params=params)

    def get_purchase_window(self, window_id, headers):
        return self._request("GET", f"/drip/purchase-windows/{window_id}", headers=headers)

    def open_purchase_window(self, window_id, headers):
        return self._request("POST", f"/drip/purchase-windows/{window_id}/open", {}, headers)

    def close_purchase_window(self, window_id, headers):
        return self._request("POST", f"/drip/purchase-windows/{window_id}/close", {}, headers)

    def settle_purchase_window(self, window_id, headers):
        return self._request("POST", f"/drip/purchase-windows/{window_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # Purchase orders
    # ------------------------------------------------------------------
    def create_purchase_order(self, window_id, payload, headers):
        return self._request("POST",
                             f"/drip/purchase-windows/{window_id}/purchase-orders",
                             payload, headers)

    def list_window_purchase_orders(self, window_id, headers, params=None):
        return self._request("GET", f"/drip/purchase-windows/{window_id}/purchase-orders",
                             headers=headers, params=params)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/drip/purchase-orders/{order_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/drip/purchase-orders", headers=headers, params=params)

    def cancel_purchase_order(self, order_id, headers):
        return self._request("POST", f"/drip/purchase-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Plan notices
    # ------------------------------------------------------------------
    def create_notice(self, plan_id, payload, headers):
        return self._request("POST", f"/drip/plans/{plan_id}/notices", payload, headers)

    def list_notices(self, plan_id, headers, params=None):
        return self._request("GET", f"/drip/plans/{plan_id}/notices",
                             headers=headers, params=params)

    def publish_notice(self, notice_id, headers):
        return self._request("POST", f"/drip/notices/{notice_id}/publish", {}, headers)

    def take_effect_notice(self, notice_id, headers):
        return self._request("POST", f"/drip/notices/{notice_id}/take-effect", {}, headers)

    # ------------------------------------------------------------------
    # Transfer instructions
    # ------------------------------------------------------------------
    def create_transfer(self, enrollment_id, payload, headers):
        return self._request("POST", f"/drip/enrollments/{enrollment_id}/transfers",
                             payload, headers)

    def get_transfer_instruction(self, instruction_id, headers):
        return self._request("GET", f"/drip/transfer-instructions/{instruction_id}",
                             headers=headers)

    def list_transfer_instructions(self, headers, params=None):
        return self._request("GET", "/drip/transfer-instructions",
                             headers=headers, params=params)

    def execute_transfer_instruction(self, instruction_id, fmv_per_share_cents, headers):
        return self._request("POST",
                             f"/drip/transfer-instructions/{instruction_id}/execute",
                             {"fmv_per_share_cents": fmv_per_share_cents}, headers)

    def cancel_transfer_instruction(self, instruction_id, headers):
        return self._request("POST",
                             f"/drip/transfer-instructions/{instruction_id}/cancel",
                             {}, headers)


api_client = ApiClient()
