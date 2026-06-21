"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles URL construction,
JSON bodies, query params, and returns the raw requests.Response so tests can
assert status codes.
"""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Connection hygiene under per-test-server isolation -------------- #
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Override the base client's keep-alive request with a close-on-each
        connection and a single retry on ConnectionError.

        The runner restarts the server (start.sh) before EVERY test, so the
        session's pooled keep-alive socket can point at a just-killed process.
        Reusing it surfaces as an intermittent ConnectionError / BadStatusLine
        unrelated to the API's behaviour. Forcing `Connection: close` stops a
        stale socket from being pooled, and one retry covers the race where the
        old connection is discovered dead on the first send after a restart.
        """
        merged = dict(headers or {})
        merged.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, merged, params)
        except requests.ConnectionError:
            return super()._request(method, path, payload, merged, params)

    # ---- Clock (test-driving) ------------------------------------------- #
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Berth ----------------------------------------------------------- #
    def create_berth(self, payload, headers):
        return self._request("POST", "/berths", payload, headers)

    def get_berth(self, berth_id, headers):
        return self._request("GET", f"/berths/{berth_id}", headers=headers)

    def list_berths(self, headers, params=None):
        return self._request("GET", "/berths", headers=headers, params=params)

    def list_berth_windows_for_berth(self, berth_id, headers, params=None):
        return self._request(
            "GET", f"/berths/{berth_id}/berth-windows", headers=headers, params=params
        )

    # ---- Vessel ---------------------------------------------------------- #
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def list_vessel_containers(self, vessel_id, headers, params=None):
        return self._request(
            "GET", f"/vessels/{vessel_id}/containers", headers=headers, params=params
        )

    # ---- BerthWindow ----------------------------------------------------- #
    def create_berth_window(self, payload, headers):
        return self._request("POST", "/berth-windows", payload, headers)

    def get_berth_window(self, window_id, headers):
        return self._request("GET", f"/berth-windows/{window_id}", headers=headers)

    def list_berth_windows(self, headers, params=None):
        return self._request("GET", "/berth-windows", headers=headers, params=params)

    def berth_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/berth-windows/{window_id}/berth", payload, headers
        )

    def unberth_window(self, window_id, headers):
        return self._request(
            "POST", f"/berth-windows/{window_id}/unberth", {}, headers
        )

    def depart_window(self, window_id, headers):
        return self._request("POST", f"/berth-windows/{window_id}/depart", {}, headers)

    def cancel_window(self, window_id, headers):
        return self._request("POST", f"/berth-windows/{window_id}/cancel", {}, headers)

    # ---- Container ------------------------------------------------------- #
    def create_container(self, payload, headers):
        return self._request("POST", "/containers", payload, headers)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/containers/{container_id}", headers=headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/containers", headers=headers, params=params)

    def ground_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/containers/{container_id}/ground", payload, headers
        )

    def customs_clear_container(self, container_id, payload, headers):
        return self._request(
            "POST", f"/containers/{container_id}/customs-clear", payload, headers
        )

    def get_demurrage_quote(self, container_id, headers):
        return self._request(
            "GET", f"/containers/{container_id}/demurrage-quote", headers=headers
        )

    def get_dwell(self, container_id, headers):
        return self._request(
            "GET", f"/containers/{container_id}/dwell", headers=headers
        )

    def list_container_eirs(self, container_id, headers, params=None):
        return self._request(
            "GET", f"/containers/{container_id}/eirs", headers=headers, params=params
        )

    def list_container_customs_holds(self, container_id, headers, params=None):
        return self._request(
            "GET",
            f"/containers/{container_id}/customs-holds",
            headers=headers,
            params=params,
        )

    def list_reefer_readings(self, container_id, headers, params=None):
        return self._request(
            "GET",
            f"/containers/{container_id}/reefer-readings",
            headers=headers,
            params=params,
        )

    def get_reefer_summary(self, container_id, headers):
        return self._request(
            "GET", f"/containers/{container_id}/reefer-summary", headers=headers
        )

    def record_reefer_reading(self, container_id, payload, headers):
        return self._request(
            "POST", f"/containers/{container_id}/reefer-readings", payload, headers
        )

    def list_container_demurrage_invoices(self, container_id, headers, params=None):
        return self._request(
            "GET",
            f"/containers/{container_id}/demurrage-invoices",
            headers=headers,
            params=params,
        )

    # ---- YardSlot -------------------------------------------------------- #
    def create_yard_slot(self, payload, headers):
        return self._request("POST", "/yard-slots", payload, headers)

    def get_yard_slot(self, slot_id, headers):
        return self._request("GET", f"/yard-slots/{slot_id}", headers=headers)

    def list_yard_slots(self, headers, params=None):
        return self._request("GET", "/yard-slots", headers=headers, params=params)

    # ---- GateAppointment ------------------------------------------------- #
    def create_gate_appointment(self, payload, headers):
        return self._request("POST", "/gate-appointments", payload, headers)

    def get_gate_appointment(self, appt_id, headers):
        return self._request("GET", f"/gate-appointments/{appt_id}", headers=headers)

    def list_gate_appointments(self, headers, params=None):
        return self._request(
            "GET", "/gate-appointments", headers=headers, params=params
        )

    def check_in_gate_appointment(self, appt_id, headers):
        return self._request(
            "POST", f"/gate-appointments/{appt_id}/check-in", {}, headers
        )

    def mark_no_show(self, appt_id, headers):
        return self._request(
            "POST", f"/gate-appointments/{appt_id}/mark-no-show", {}, headers
        )

    def reschedule_gate_appointment(self, appt_id, payload, headers):
        return self._request(
            "POST", f"/gate-appointments/{appt_id}/reschedule", payload, headers
        )

    def fulfill_gate_appointment(self, appt_id, payload, headers):
        return self._request(
            "POST", f"/gate-appointments/{appt_id}/fulfill", payload, headers
        )

    def cancel_gate_appointment(self, appt_id, headers):
        return self._request(
            "POST", f"/gate-appointments/{appt_id}/cancel", {}, headers
        )

    def list_gate_appointment_eirs(self, appt_id, headers, params=None):
        return self._request(
            "GET", f"/gate-appointments/{appt_id}/eirs", headers=headers, params=params
        )

    # ---- CustomsHold ----------------------------------------------------- #
    def create_customs_hold(self, payload, headers):
        return self._request("POST", "/customs-holds", payload, headers)

    def get_customs_hold(self, hold_id, headers):
        return self._request("GET", f"/customs-holds/{hold_id}", headers=headers)

    def release_customs_hold(self, hold_id, headers):
        return self._request(
            "POST", f"/customs-holds/{hold_id}/release", {}, headers
        )

    # ---- DemurrageInvoice ------------------------------------------------ #
    def get_demurrage_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/demurrage-invoices/{invoice_id}", headers=headers
        )

    def pay_demurrage_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/demurrage-invoices/{invoice_id}/pay", {}, headers
        )

    def waive_demurrage_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/demurrage-invoices/{invoice_id}/waive", {}, headers
        )


api_client = ApiClient()
