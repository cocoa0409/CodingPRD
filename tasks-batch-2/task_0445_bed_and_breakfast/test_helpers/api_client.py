"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) --------------------------------------
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Inn ---------------------------------------------------------------
    def create_inn(self, payload, headers):
        return self._request("POST", "/inns", payload, headers)

    def get_inn(self, inn_id, headers):
        return self._request("GET", f"/inns/{inn_id}", headers=headers)

    # ---- Room --------------------------------------------------------------
    def create_room(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/rooms", payload, headers)

    def list_rooms(self, inn_id, headers, params=None):
        return self._request("GET", f"/inns/{inn_id}/rooms", headers=headers, params=params)

    def get_room(self, inn_id, room_id, headers):
        return self._request("GET", f"/inns/{inn_id}/rooms/{room_id}", headers=headers)

    def retire_room(self, inn_id, room_id, payload, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/rooms/{room_id}/retire", payload, headers
        )

    # ---- RatePeriod --------------------------------------------------------
    def create_rate_period(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/rate-periods", payload, headers)

    def list_rate_periods(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/rate-periods", headers=headers, params=params
        )

    def get_rate_period(self, inn_id, rate_period_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/rate-periods/{rate_period_id}", headers=headers
        )

    # ---- Package -----------------------------------------------------------
    def create_package(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/packages", payload, headers)

    def list_packages(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/packages", headers=headers, params=params
        )

    def get_package(self, inn_id, package_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/packages/{package_id}", headers=headers
        )

    def retire_package(self, inn_id, package_id, payload, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/packages/{package_id}/retire", payload, headers
        )

    # ---- Guest -------------------------------------------------------------
    def create_guest(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/guests", payload, headers)

    def list_guests(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/guests", headers=headers, params=params
        )

    def get_guest(self, inn_id, guest_id, headers):
        return self._request("GET", f"/inns/{inn_id}/guests/{guest_id}", headers=headers)

    # ---- GiftCertificate ---------------------------------------------------
    def create_gift_certificate(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/gift-certificates", payload, headers)

    def list_gift_certificates(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/gift-certificates", headers=headers, params=params
        )

    def get_gift_certificate(self, inn_id, gift_certificate_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/gift-certificates/{gift_certificate_id}", headers=headers
        )

    def list_gift_certificate_redemptions(self, inn_id, gift_certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/inns/{inn_id}/gift-certificates/{gift_certificate_id}/redemptions",
            headers=headers,
            params=params,
        )

    def void_gift_certificate(self, inn_id, gift_certificate_id, payload, headers):
        return self._request(
            "POST",
            f"/inns/{inn_id}/gift-certificates/{gift_certificate_id}/void",
            payload,
            headers,
        )

    # ---- Booking -----------------------------------------------------------
    def create_booking(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/bookings", payload, headers)

    def list_bookings(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/bookings", headers=headers, params=params
        )

    def get_booking(self, inn_id, booking_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/bookings/{booking_id}", headers=headers
        )

    def pay_deposit(self, inn_id, booking_id, payload, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/pay-deposit", payload, headers
        )

    def redeem_gift(self, inn_id, booking_id, payload, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/redeem-gift", payload, headers
        )

    def refund_quote(self, inn_id, booking_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/bookings/{booking_id}/refund-quote", headers=headers
        )

    def confirm_booking(self, inn_id, booking_id, payload, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/confirm", payload, headers
        )

    def check_in(self, inn_id, booking_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/check-in", {}, headers
        )

    def check_out(self, inn_id, booking_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/check-out", {}, headers
        )

    def cancel_booking(self, inn_id, booking_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/cancel", {}, headers
        )

    def mark_no_show(self, inn_id, booking_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/bookings/{booking_id}/mark-no-show", {}, headers
        )

    def list_booking_ledger(self, inn_id, booking_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/bookings/{booking_id}/ledger", headers=headers, params=params
        )

    # ---- PaymentLedgerEntry ------------------------------------------------
    def list_payment_ledger_entries(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/payment-ledger-entries", headers=headers, params=params
        )

    def get_payment_ledger_entry(self, inn_id, payment_ledger_entry_id, headers):
        return self._request(
            "GET",
            f"/inns/{inn_id}/payment-ledger-entries/{payment_ledger_entry_id}",
            headers=headers,
        )

    # ---- BreakfastPlan -----------------------------------------------------
    def create_breakfast_plan(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/breakfast-plans", payload, headers)

    def list_breakfast_plans(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/breakfast-plans", headers=headers, params=params
        )

    def get_breakfast_plan(self, inn_id, breakfast_plan_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/breakfast-plans/{breakfast_plan_id}", headers=headers
        )

    def confirm_breakfast_plan(self, inn_id, breakfast_plan_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/breakfast-plans/{breakfast_plan_id}/confirm", {}, headers
        )

    def cancel_breakfast_plan(self, inn_id, breakfast_plan_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/breakfast-plans/{breakfast_plan_id}/cancel", {}, headers
        )

    # ---- HousekeepingTask --------------------------------------------------
    def list_housekeeping_tasks(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/housekeeping-tasks", headers=headers, params=params
        )

    def get_housekeeping_task(self, inn_id, housekeeping_task_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}", headers=headers
        )

    def start_housekeeping_task(self, inn_id, housekeeping_task_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}/start", {}, headers
        )

    def complete_housekeeping_task(self, inn_id, housekeeping_task_id, headers):
        return self._request(
            "POST",
            f"/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}/complete",
            {},
            headers,
        )

    def skip_housekeeping_task(self, inn_id, housekeeping_task_id, headers):
        return self._request(
            "POST", f"/inns/{inn_id}/housekeeping-tasks/{housekeeping_task_id}/skip", {}, headers
        )

    # ---- TaxRemittance -----------------------------------------------------
    def create_tax_remittance(self, inn_id, payload, headers):
        return self._request("POST", f"/inns/{inn_id}/tax-remittances", payload, headers)

    def list_tax_remittances(self, inn_id, headers, params=None):
        return self._request(
            "GET", f"/inns/{inn_id}/tax-remittances", headers=headers, params=params
        )

    def get_tax_remittance(self, inn_id, tax_remittance_id, headers):
        return self._request(
            "GET", f"/inns/{inn_id}/tax-remittances/{tax_remittance_id}", headers=headers
        )

    def file_tax_remittance(self, inn_id, tax_remittance_id, payload, headers):
        return self._request(
            "POST",
            f"/inns/{inn_id}/tax-remittances/{tax_remittance_id}/file",
            payload,
            headers,
        )


api_client = ApiClient()
