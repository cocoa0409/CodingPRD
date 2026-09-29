"""API client: one method per endpoint defined in the PRD (mounted under /housing)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/housing"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- events
    def create_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/events/{event_id}", headers=headers)

    # ---------------------------------------------------------------- hotels
    def create_hotel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hotels", payload, headers)

    def get_hotel(self, hotel_id, headers):
        return self._request("GET", f"{PREFIX}/hotels/{hotel_id}", headers=headers)

    def list_hotels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hotels", headers=headers, params=params)

    def update_hotel_standing(self, hotel_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/hotels/{hotel_id}/standing", payload, headers
        )

    # ---------------------------------------------------------- hotel blocks
    def create_hotel_block(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hotel-blocks", payload, headers)

    def get_hotel_block(self, block_id, headers):
        return self._request("GET", f"{PREFIX}/hotel-blocks/{block_id}", headers=headers)

    def list_hotel_blocks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hotel-blocks", headers=headers, params=params
        )

    def submit_block_terms(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/terms", payload, headers
        )

    def request_block_changes(self, block_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/hotel-blocks/{block_id}/request-changes",
            payload or {},
            headers,
        )

    def contract_hotel_block(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/contract", payload, headers
        )

    def open_hotel_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/open", payload or {}, headers
        )

    def cutoff_hotel_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/cutoff", payload or {}, headers
        )

    def close_hotel_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/close", payload or {}, headers
        )

    def get_pickup_pace(self, block_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hotel-blocks/{block_id}/pickup-pace", headers=headers
        )

    # ------------------------------------------------------------ sub-blocks
    def carve_sub_block(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/sub-blocks", payload, headers
        )

    def get_sub_block(self, sub_block_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sub-blocks/{sub_block_id}", headers=headers
        )

    def list_sub_blocks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sub-blocks", headers=headers, params=params
        )

    def approve_sub_block(self, sub_block_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sub-blocks/{sub_block_id}/approve", payload or {}, headers
        )

    def reject_sub_block(self, sub_block_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sub-blocks/{sub_block_id}/reject", payload or {}, headers
        )

    def release_sub_block(self, sub_block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sub-blocks/{sub_block_id}/release", payload, headers
        )

    # -------------------------------------------------------------- attendees
    def create_attendee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/attendees", payload, headers)

    def get_attendee(self, attendee_id, headers):
        return self._request(
            "GET", f"{PREFIX}/attendees/{attendee_id}", headers=headers
        )

    def list_attendees(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/attendees", headers=headers, params=params
        )

    def list_attendee_poaching_incidents(self, attendee_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/attendees/{attendee_id}/poaching-incidents",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- reservations
    def create_reservation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reservations", headers=headers, params=params
        )

    def change_reservation(self, reservation_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/reservations/{reservation_id}", payload, headers
        )

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/reservations/{reservation_id}/cancel",
            payload or {},
            headers,
        )

    def no_show_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/reservations/{reservation_id}/no-show",
            payload or {},
            headers,
        )

    # --------------------------------------------------------- rooming lists
    def transmit_rooming_list(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/rooming-lists", payload, headers
        )

    def list_rooming_lists(self, block_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/hotel-blocks/{block_id}/rooming-lists",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------- pickup reports
    def create_pickup_report(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hotel-blocks/{block_id}/pickup-reports", payload, headers
        )

    def list_pickup_reports(self, block_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/hotel-blocks/{block_id}/pickup-reports",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------- attrition reductions
    def create_attrition_reduction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/attrition-reductions", payload, headers)

    def get_attrition_reduction(self, reduction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/attrition-reductions/{reduction_id}", headers=headers
        )

    def list_block_attrition_reductions(self, block_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/hotel-blocks/{block_id}/attrition-reductions",
            headers=headers,
            params=params,
        )

    def approve_attrition_reduction(self, reduction_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/attrition-reductions/{reduction_id}/approve",
            payload or {},
            headers,
        )

    def reject_attrition_reduction(self, reduction_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/attrition-reductions/{reduction_id}/reject",
            payload or {},
            headers,
        )

    def exercise_attrition_reduction(self, reduction_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/attrition-reductions/{reduction_id}/exercise",
            payload or {},
            headers,
        )

    # ---------------------------------------------------------- rogue vendors
    def create_rogue_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rogue-vendors", payload, headers)

    def get_rogue_vendor(self, vendor_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rogue-vendors/{vendor_id}", headers=headers
        )

    def list_rogue_vendors(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rogue-vendors", headers=headers, params=params
        )

    def create_poaching_incident(self, vendor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rogue-vendors/{vendor_id}/incidents", payload, headers
        )

    def list_vendor_incidents(self, vendor_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/rogue-vendors/{vendor_id}/incidents",
            headers=headers,
            params=params,
        )

    def confirm_rogue_vendor(self, vendor_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/rogue-vendors/{vendor_id}/confirm", payload or {}, headers
        )

    def clear_rogue_vendor(self, vendor_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/rogue-vendors/{vendor_id}/clear", payload or {}, headers
        )

    # ----------------------------------------------------- commission invoices
    def issue_commission_invoice(self, block_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hotel-blocks/{block_id}/commission-invoice",
            payload,
            headers,
        )

    def get_commission_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/commission-invoices/{invoice_id}", headers=headers
        )

    def list_block_commission_invoices(self, block_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/hotel-blocks/{block_id}/commission-invoices",
            headers=headers,
            params=params,
        )

    def pay_commission_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/commission-invoices/{invoice_id}/payments", payload, headers
        )

    def reverse_commission_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/commission-invoices/{invoice_id}/payment-reversals",
            payload,
            headers,
        )

    def dispute_commission_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/commission-invoices/{invoice_id}/dispute",
            payload or {},
            headers,
        )

    def adjust_commission_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/commission-invoices/{invoice_id}/adjust", payload, headers
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()

# This module-level client is a session-scoped singleton, but the server under
# test is restarted between tests (per-test-server isolation) on the same port.
# A pooled keep-alive socket left over from the previous server instance is dead
# by the time the next test reuses it, which surfaces as RemoteDisconnected /
# ConnectionResetError on the first request of a test. Asking for a fresh TCP
# connection per request removes that whole class of false failure.
api_client.session.headers["Connection"] = "close"
