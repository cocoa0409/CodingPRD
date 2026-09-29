"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the pro desk API."""

    # ------------------------------------------------------------------ #
    # Logical clock                                                       #
    # ------------------------------------------------------------------ #

    def set_current_utc(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/pro/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------ #
    # Stores                                                              #
    # ------------------------------------------------------------------ #

    def create_store(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/stores", payload, headers)

    def get_store(self, store_id: str, headers=None):
        return self._request("GET", f"/pro/stores/{store_id}", headers=headers)

    def list_stores(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/stores", headers=headers, params=params)

    def run_will_call_sweep(self, store_id: str, headers=None):
        return self._request(
            "POST", f"/pro/stores/{store_id}/will-call-sweep", {}, headers
        )

    # ------------------------------------------------------------------ #
    # Store stock                                                         #
    # ------------------------------------------------------------------ #

    def create_store_stock(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/store-stocks", payload, headers)

    def get_store_stock(self, store_stock_id: str, headers=None):
        return self._request(
            "GET", f"/pro/store-stocks/{store_stock_id}", headers=headers
        )

    def list_store_stocks(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/store-stocks", headers=headers, params=params)

    # ------------------------------------------------------------------ #
    # Delivery trucks                                                     #
    # ------------------------------------------------------------------ #

    def create_delivery_truck(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/delivery-trucks", payload, headers)

    def get_delivery_truck(self, delivery_truck_id: str, headers=None):
        return self._request(
            "GET", f"/pro/delivery-trucks/{delivery_truck_id}", headers=headers
        )

    def list_delivery_trucks(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/pro/delivery-trucks", headers=headers, params=params
        )

    def take_truck_out_of_service(
        self, delivery_truck_id: str, reason_code: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/delivery-trucks/{delivery_truck_id}/out-of-service",
            {"reason_code": reason_code},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Pro accounts                                                        #
    # ------------------------------------------------------------------ #

    def create_pro_account(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/pro-accounts", payload, headers)

    def get_pro_account(self, pro_account_id: str, headers=None):
        return self._request(
            "GET", f"/pro/pro-accounts/{pro_account_id}", headers=headers
        )

    def list_pro_accounts(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/pro-accounts", headers=headers, params=params)

    def adjust_pro_account_volume(
        self, pro_account_id: str, delta_cents: int, memo: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/pro-accounts/{pro_account_id}/volume-adjustments",
            {"delta_cents": delta_cents, "memo": memo},
            headers,
        )

    def reinstate_pro_account(self, pro_account_id: str, headers=None):
        return self._request(
            "POST", f"/pro/pro-accounts/{pro_account_id}/reinstate", {}, headers
        )

    # ------------------------------------------------------------------ #
    # Credit lines                                                        #
    # ------------------------------------------------------------------ #

    def create_credit_line(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/credit-lines", payload, headers)

    def get_credit_line(self, credit_line_id: str, headers=None):
        return self._request(
            "GET", f"/pro/credit-lines/{credit_line_id}", headers=headers
        )

    def list_credit_lines(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/credit-lines", headers=headers, params=params)

    def freeze_credit_line(self, credit_line_id: str, reason_code: str, headers=None):
        return self._request(
            "POST",
            f"/pro/credit-lines/{credit_line_id}/freeze",
            {"reason_code": reason_code},
            headers,
        )

    def reinstate_credit_line(self, credit_line_id: str, headers=None):
        return self._request(
            "POST", f"/pro/credit-lines/{credit_line_id}/reinstate", {}, headers
        )

    # ------------------------------------------------------------------ #
    # Tax exempt certificates                                             #
    # ------------------------------------------------------------------ #

    def create_tax_exempt_certificate(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/tax-exempt-certificates", payload, headers)

    def get_tax_exempt_certificate(
        self, tax_exempt_certificate_id: str, headers=None
    ):
        return self._request(
            "GET",
            f"/pro/tax-exempt-certificates/{tax_exempt_certificate_id}",
            headers=headers,
        )

    def list_tax_exempt_certificates(
        self, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/pro/tax-exempt-certificates", headers=headers, params=params
        )

    def verify_tax_exempt_certificate(
        self, tax_exempt_certificate_id: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/tax-exempt-certificates/{tax_exempt_certificate_id}/verify",
            {},
            headers,
        )

    def revoke_tax_exempt_certificate(
        self, tax_exempt_certificate_id: str, reason_code: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/tax-exempt-certificates/{tax_exempt_certificate_id}/revoke",
            {"reason_code": reason_code},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Job quotes                                                          #
    # ------------------------------------------------------------------ #

    def create_job_quote(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/job-quotes", payload, headers)

    def get_job_quote(self, job_quote_id: str, headers=None):
        return self._request("GET", f"/pro/job-quotes/{job_quote_id}", headers=headers)

    def list_job_quotes(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/job-quotes", headers=headers, params=params)

    def create_quote_line(self, job_quote_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/pro/job-quotes/{job_quote_id}/lines", payload, headers
        )

    def list_quote_lines_of_quote(
        self, job_quote_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/pro/job-quotes/{job_quote_id}/lines", headers=headers, params=params
        )

    def get_quote_line(self, quote_line_id: str, headers=None):
        return self._request("GET", f"/pro/quote-lines/{quote_line_id}", headers=headers)

    def list_quote_lines(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/quote-lines", headers=headers, params=params)

    def submit_job_quote(self, job_quote_id: str, headers=None):
        return self._request("POST", f"/pro/job-quotes/{job_quote_id}/submit", {}, headers)

    def counter_offer_job_quote(
        self,
        job_quote_id: str,
        line_prices: List[Dict[str, Any]],
        term_days: int,
        expected_job_quote_version: int,
        headers=None,
    ):
        return self._request(
            "POST",
            f"/pro/job-quotes/{job_quote_id}/counter-offers",
            {
                "line_prices": line_prices,
                "term_days": term_days,
                "expected_job_quote_version": expected_job_quote_version,
            },
            headers,
        )

    def counter_offer_job_quote_raw(
        self, job_quote_id: str, payload: Dict[str, Any], headers=None
    ):
        """Counter-offer with a caller-supplied body (for malformed-payload probes)."""
        return self._request(
            "POST", f"/pro/job-quotes/{job_quote_id}/counter-offers", payload, headers
        )

    def revise_job_quote(self, job_quote_id: str, revision_note: str, headers=None):
        return self._request(
            "POST",
            f"/pro/job-quotes/{job_quote_id}/revise",
            {"revision_note": revision_note},
            headers,
        )

    def approve_job_quote(self, job_quote_id: str, headers=None):
        return self._request(
            "POST", f"/pro/job-quotes/{job_quote_id}/approve", {}, headers
        )

    def accept_job_quote(self, job_quote_id: str, headers=None):
        return self._request("POST", f"/pro/job-quotes/{job_quote_id}/accept", {}, headers)

    def withdraw_job_quote(self, job_quote_id: str, reason_code: str, headers=None):
        return self._request(
            "POST",
            f"/pro/job-quotes/{job_quote_id}/withdraw",
            {"reason_code": reason_code},
            headers,
        )

    def expire_job_quote(self, job_quote_id: str, headers=None):
        return self._request("POST", f"/pro/job-quotes/{job_quote_id}/expire", {}, headers)

    # ------------------------------------------------------------------ #
    # Pro orders                                                          #
    # ------------------------------------------------------------------ #

    def create_pro_order(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/pro-orders", payload, headers)

    def get_pro_order(self, pro_order_id: str, headers=None):
        return self._request("GET", f"/pro/pro-orders/{pro_order_id}", headers=headers)

    def list_pro_orders(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/pro-orders", headers=headers, params=params)

    def create_order_line(self, pro_order_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/pro/pro-orders/{pro_order_id}/lines", payload, headers
        )

    def list_order_lines_of_order(
        self, pro_order_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/pro/pro-orders/{pro_order_id}/lines", headers=headers, params=params
        )

    def get_order_line(self, order_line_id: str, headers=None):
        return self._request("GET", f"/pro/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/order-lines", headers=headers, params=params)

    def get_pricing_preview(self, pro_order_id: str, headers=None):
        return self._request(
            "GET", f"/pro/pro-orders/{pro_order_id}/pricing-preview", headers=headers
        )

    def submit_pro_order(self, pro_order_id: str, headers=None):
        return self._request("POST", f"/pro/pro-orders/{pro_order_id}/submit", {}, headers)

    def reserve_pro_order(self, pro_order_id: str, headers=None):
        return self._request(
            "POST", f"/pro/pro-orders/{pro_order_id}/reserve", {}, headers
        )

    def cancel_pro_order(self, pro_order_id: str, reason_code: str, headers=None):
        return self._request(
            "POST",
            f"/pro/pro-orders/{pro_order_id}/cancel",
            {"reason_code": reason_code},
            headers,
        )

    def invoice_pro_order(self, pro_order_id: str, headers=None):
        return self._request(
            "POST", f"/pro/pro-orders/{pro_order_id}/invoice", {}, headers
        )

    def pay_pro_order(self, pro_order_id: str, amount_cents: int, headers=None):
        return self._request(
            "POST",
            f"/pro/pro-orders/{pro_order_id}/pay",
            {"amount_cents": amount_cents},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Reservations                                                        #
    # ------------------------------------------------------------------ #

    def get_reservation(self, reservation_id: str, headers=None):
        return self._request("GET", f"/pro/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/pro/reservations", headers=headers, params=params)

    def allocate_reservation(self, reservation_id: str, headers=None):
        return self._request(
            "POST", f"/pro/reservations/{reservation_id}/allocate", {}, headers
        )

    def release_reservation(self, reservation_id: str, reason_code: str, headers=None):
        return self._request(
            "POST",
            f"/pro/reservations/{reservation_id}/release",
            {"reason_code": reason_code},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Will-call stagings                                                  #
    # ------------------------------------------------------------------ #

    def create_will_call_staging(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/will-call-stagings", payload, headers)

    def get_will_call_staging(self, will_call_staging_id: str, headers=None):
        return self._request(
            "GET", f"/pro/will-call-stagings/{will_call_staging_id}", headers=headers
        )

    def list_will_call_stagings(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/pro/will-call-stagings", headers=headers, params=params
        )

    def stage_will_call_staging(self, will_call_staging_id: str, headers=None):
        return self._request(
            "POST", f"/pro/will-call-stagings/{will_call_staging_id}/stage", {}, headers
        )

    def pick_up_will_call_staging(
        self, will_call_staging_id: str, picked_up_by: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/will-call-stagings/{will_call_staging_id}/pick-up",
            {"picked_up_by": picked_up_by},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Delivery appointments                                               #
    # ------------------------------------------------------------------ #

    def create_delivery_appointment(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/delivery-appointments", payload, headers)

    def get_delivery_appointment(self, delivery_appointment_id: str, headers=None):
        return self._request(
            "GET",
            f"/pro/delivery-appointments/{delivery_appointment_id}",
            headers=headers,
        )

    def list_delivery_appointments(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/pro/delivery-appointments", headers=headers, params=params
        )

    def confirm_delivery_appointment(self, delivery_appointment_id: str, headers=None):
        return self._request(
            "POST",
            f"/pro/delivery-appointments/{delivery_appointment_id}/confirm",
            {},
            headers,
        )

    def complete_delivery_appointment(self, delivery_appointment_id: str, headers=None):
        return self._request(
            "POST",
            f"/pro/delivery-appointments/{delivery_appointment_id}/complete",
            {},
            headers,
        )

    def cancel_delivery_appointment(
        self, delivery_appointment_id: str, reason_code: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/delivery-appointments/{delivery_appointment_id}/cancel",
            {"reason_code": reason_code},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Rebate accruals                                                     #
    # ------------------------------------------------------------------ #

    def get_rebate_accrual(self, rebate_accrual_id: str, headers=None):
        return self._request(
            "GET", f"/pro/rebate-accruals/{rebate_accrual_id}", headers=headers
        )

    def list_rebate_accruals(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/pro/rebate-accruals", headers=headers, params=params
        )

    def close_rebate_accrual(self, rebate_accrual_id: str, headers=None):
        return self._request(
            "POST", f"/pro/rebate-accruals/{rebate_accrual_id}/close", {}, headers
        )

    def pay_out_rebate_accrual(
        self, rebate_accrual_id: str, payout_reference: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/rebate-accruals/{rebate_accrual_id}/pay-out",
            {"payout_reference": payout_reference},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Return requests                                                     #
    # ------------------------------------------------------------------ #

    def create_return_request(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/pro/return-requests", payload, headers)

    def get_return_request(self, return_request_id: str, headers=None):
        return self._request(
            "GET", f"/pro/return-requests/{return_request_id}", headers=headers
        )

    def list_return_requests(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/pro/return-requests", headers=headers, params=params
        )

    def approve_return_request(self, return_request_id: str, headers=None):
        return self._request(
            "POST", f"/pro/return-requests/{return_request_id}/approve", {}, headers
        )

    def deny_return_request(
        self, return_request_id: str, reason_code: str, headers=None
    ):
        return self._request(
            "POST",
            f"/pro/return-requests/{return_request_id}/deny",
            {"reason_code": reason_code},
            headers,
        )

    def credit_return_request(self, return_request_id: str, headers=None):
        return self._request(
            "POST", f"/pro/return-requests/{return_request_id}/credit", {}, headers
        )


api_client = ApiClient()
