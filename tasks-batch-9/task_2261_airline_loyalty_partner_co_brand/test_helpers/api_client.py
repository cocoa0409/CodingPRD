"""API client: one method per endpoint declared by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -------------------------------------------------- loyalty programmes #
    def create_loyalty_program(self, payload, headers):
        return self._request("POST", "/loyalty-programs", payload, headers)

    def list_loyalty_programs(self, headers, params=None):
        return self._request("GET", "/loyalty-programs", headers=headers, params=params)

    def get_loyalty_program(self, program_id, headers):
        return self._request("GET", f"/loyalty-programs/{program_id}", headers=headers)

    def create_recognition_transition(self, program_id, payload, headers):
        return self._request(
            "POST", f"/loyalty-programs/{program_id}/recognition-transitions",
            payload, headers,
        )

    # ------------------------------------------------------ co-brand issuers #
    def create_co_brand_issuer(self, payload, headers):
        return self._request("POST", "/co-brand-issuers", payload, headers)

    def list_co_brand_issuers(self, headers, params=None):
        return self._request("GET", "/co-brand-issuers", headers=headers, params=params)

    def get_co_brand_issuer(self, issuer_id, headers):
        return self._request("GET", f"/co-brand-issuers/{issuer_id}", headers=headers)

    # -------------------------------------------------- mile sale agreements #
    def create_mile_sale_agreement(self, payload, headers):
        return self._request("POST", "/mile-sale-agreements", payload, headers)

    def list_mile_sale_agreements(self, headers, params=None):
        return self._request(
            "GET", "/mile-sale-agreements", headers=headers, params=params
        )

    def get_mile_sale_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/mile-sale-agreements/{agreement_id}", headers=headers
        )

    def submit_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/mile-sale-agreements/{agreement_id}/submit",
            payload or {}, headers,
        )

    def counter_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/mile-sale-agreements/{agreement_id}/counter", payload, headers
        )

    def revise_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/mile-sale-agreements/{agreement_id}/revise", payload, headers
        )

    def ratify_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/mile-sale-agreements/{agreement_id}/ratify",
            payload or {}, headers,
        )

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/mile-sale-agreements/{agreement_id}/activate",
            payload or {}, headers,
        )

    # ------------------------------------------------ mile purchase orders #
    def create_mile_purchase_order(self, payload, headers):
        return self._request("POST", "/mile-purchase-orders", payload, headers)

    def list_mile_purchase_orders(self, headers, params=None):
        return self._request(
            "GET", "/mile-purchase-orders", headers=headers, params=params
        )

    def get_mile_purchase_order(self, order_id, headers):
        return self._request(
            "GET", f"/mile-purchase-orders/{order_id}", headers=headers
        )

    def issue_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/mile-purchase-orders/{order_id}/issue", payload or {}, headers
        )

    def invoice_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/mile-purchase-orders/{order_id}/invoice", payload or {}, headers
        )

    def settle_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/mile-purchase-orders/{order_id}/settle", payload or {}, headers
        )

    def reverse_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/mile-purchase-orders/{order_id}/reverse", payload, headers
        )

    # ----------------------------------------------------- member accounts #
    def create_member_account(self, payload, headers):
        return self._request("POST", "/member-accounts", payload, headers)

    def list_member_accounts(self, headers, params=None):
        return self._request("GET", "/member-accounts", headers=headers, params=params)

    def get_member_account(self, member_id, headers):
        return self._request("GET", f"/member-accounts/{member_id}", headers=headers)

    def grant_status_match(self, member_id, payload, headers):
        return self._request(
            "POST", f"/member-accounts/{member_id}/status-match", payload, headers
        )

    def resolve_status_match(self, member_id, payload, headers):
        return self._request(
            "POST", f"/member-accounts/{member_id}/status-match/resolve",
            payload, headers,
        )

    def close_qualification_cycle(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/member-accounts/{member_id}/qualification-cycle/close",
            payload or {}, headers,
        )

    def restate_qualification_cycle(self, member_id, payload, headers):
        return self._request(
            "POST", f"/member-accounts/{member_id}/qualification-cycle/restate",
            payload, headers,
        )

    # ---------------------------------------------------- mile transactions #
    def create_mile_transaction(self, payload, headers):
        return self._request("POST", "/mile-transactions", payload, headers)

    def list_mile_transactions(self, headers, params=None):
        return self._request(
            "GET", "/mile-transactions", headers=headers, params=params
        )

    def get_mile_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/mile-transactions/{transaction_id}", headers=headers
        )

    # -------------------------------------------------- promotion campaigns #
    def create_promotion_campaign(self, payload, headers):
        return self._request("POST", "/promotion-campaigns", payload, headers)

    def list_promotion_campaigns(self, headers, params=None):
        return self._request(
            "GET", "/promotion-campaigns", headers=headers, params=params
        )

    def get_promotion_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/promotion-campaigns/{campaign_id}", headers=headers
        )

    def cancel_promotion_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/promotion-campaigns/{campaign_id}/cancel", payload, headers
        )

    # --------------------------------------------- award inventory windows #
    def create_award_inventory_window(self, payload, headers):
        return self._request("POST", "/award-inventory-windows", payload, headers)

    def list_award_inventory_windows(self, headers, params=None):
        return self._request(
            "GET", "/award-inventory-windows", headers=headers, params=params
        )

    def get_award_inventory_window(self, window_id, headers):
        return self._request(
            "GET", f"/award-inventory-windows/{window_id}", headers=headers
        )

    def patch_capacity_control(self, window_id, payload, headers):
        return self._request(
            "PATCH", f"/award-inventory-windows/{window_id}/capacity-control",
            payload, headers,
        )

    # ------------------------------------------------------ award bookings #
    def create_award_booking(self, payload, headers):
        return self._request("POST", "/award-bookings", payload, headers)

    def list_award_bookings(self, headers, params=None):
        return self._request("GET", "/award-bookings", headers=headers, params=params)

    def get_award_booking(self, booking_id, headers):
        return self._request("GET", f"/award-bookings/{booking_id}", headers=headers)

    def ticket_award_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/award-bookings/{booking_id}/ticket", payload or {}, headers
        )

    def cancel_award_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/award-bookings/{booking_id}/cancel", payload or {}, headers
        )

    def refund_award_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/award-bookings/{booking_id}/refund", payload or {}, headers
        )

    # ----------------------------------------------------- partner airlines #
    def create_partner_airline(self, payload, headers):
        return self._request("POST", "/partner-airlines", payload, headers)

    def list_partner_airlines(self, headers, params=None):
        return self._request("GET", "/partner-airlines", headers=headers, params=params)

    def get_partner_airline(self, airline_id, headers):
        return self._request("GET", f"/partner-airlines/{airline_id}", headers=headers)

    def create_settlement_run(self, airline_id, headers, payload=None):
        return self._request(
            "POST", f"/partner-airlines/{airline_id}/settlement-runs",
            payload or {}, headers,
        )

    # ----------------------------------------------- program change notices #
    def create_program_change_notice(self, payload, headers):
        return self._request("POST", "/program-change-notices", payload, headers)

    def list_program_change_notices(self, headers, params=None):
        return self._request(
            "GET", "/program-change-notices", headers=headers, params=params
        )

    def get_program_change_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/program-change-notices/{notice_id}", headers=headers
        )

    def announce_notice(self, notice_id, headers, payload=None):
        return self._request(
            "POST", f"/program-change-notices/{notice_id}/announce",
            payload or {}, headers,
        )

    def rollback_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/program-change-notices/{notice_id}/rollback", payload, headers
        )

    # ---------------------------------------------------------- fraud cases #
    def create_fraud_case(self, payload, headers):
        return self._request("POST", "/fraud-cases", payload, headers)

    def list_fraud_cases(self, headers, params=None):
        return self._request("GET", "/fraud-cases", headers=headers, params=params)

    def get_fraud_case(self, case_id, headers):
        return self._request("GET", f"/fraud-cases/{case_id}", headers=headers)

    def investigate_fraud_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/fraud-cases/{case_id}/investigate", payload or {}, headers
        )

    def substantiate_fraud_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/fraud-cases/{case_id}/substantiate", payload or {}, headers
        )

    def dismiss_fraud_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/fraud-cases/{case_id}/dismiss", payload or {}, headers
        )

    # ---------------------------------------------- deferred revenue postings #
    def create_deferred_revenue_posting(self, payload, headers):
        return self._request("POST", "/deferred-revenue-postings", payload, headers)

    def list_deferred_revenue_postings(self, headers, params=None):
        return self._request(
            "GET", "/deferred-revenue-postings", headers=headers, params=params
        )

    def get_deferred_revenue_posting(self, posting_id, headers):
        return self._request(
            "GET", f"/deferred-revenue-postings/{posting_id}", headers=headers
        )

    # ------------------------------------------ logical clock and epoch runner #
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_epoch(self, program_id, headers):
        return self._request(
            "POST", "/_ops/run-epoch", {"program_id": program_id}, headers
        )


api_client = ApiClient()
