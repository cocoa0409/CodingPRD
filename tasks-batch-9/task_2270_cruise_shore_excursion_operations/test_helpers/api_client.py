"""API client: one method per endpoint defined in the PRD.

Every method returns the raw ``requests.Response`` so tests can assert both the
status code and the envelope.  ``headers`` is always explicit — there is no
implicit caller identity.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/shore-excursions"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers=None):
        """The logical clock every temporal rule reads. Requires no identity."""
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"current_utc": current_utc}, headers or {},
        )

    # ---------------------------------------------------------------- ports
    def create_port(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ports", payload, headers)

    def get_port(self, port_id, headers):
        return self._request("GET", f"{PREFIX}/ports/{port_id}", headers=headers)

    def list_ports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ports", headers=headers, params=params)

    def get_port_revenue_report(self, port_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ports/{port_id}/revenue-report",
            headers=headers, params=params,
        )

    # ------------------------------------------------------- meeting points
    def create_meeting_point(self, port_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ports/{port_id}/meeting-points", payload, headers,
        )

    def get_meeting_point(self, meeting_point_id, headers):
        return self._request(
            "GET", f"{PREFIX}/meeting-points/{meeting_point_id}", headers=headers,
        )

    def list_meeting_points(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/meeting-points", headers=headers, params=params,
        )

    # ------------------------------------------------------- tour operators
    def create_operator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request(
            "GET", f"{PREFIX}/operators/{operator_id}", headers=headers,
        )

    def list_operators(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/operators", headers=headers, params=params,
        )

    def create_safety_audit(self, operator_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operators/{operator_id}/safety-audits", payload, headers,
        )

    def vetting_action(self, operator_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/operators/{operator_id}/vetting-actions", payload, headers,
        )

    def get_safety_audit(self, audit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/safety-audits/{audit_id}", headers=headers,
        )

    def list_safety_audits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/safety-audits", headers=headers, params=params,
        )

    # ----------------------------------------------------------- port calls
    def create_port_call(self, payload, headers):
        return self._request("POST", f"{PREFIX}/port-calls", payload, headers)

    def get_port_call(self, port_call_id, headers):
        return self._request(
            "GET", f"{PREFIX}/port-calls/{port_call_id}", headers=headers,
        )

    def list_port_calls(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/port-calls", headers=headers, params=params,
        )

    def port_call_transition(self, port_call_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-calls/{port_call_id}/transitions", payload, headers,
        )

    def record_delay(self, port_call_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-calls/{port_call_id}/delays", payload, headers,
        )

    def create_tender_wave(self, port_call_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-calls/{port_call_id}/tender-waves", payload, headers,
        )

    def get_tender_wave(self, tender_wave_id, headers):
        return self._request(
            "GET", f"{PREFIX}/tender-waves/{tender_wave_id}", headers=headers,
        )

    def list_tender_waves(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/tender-waves", headers=headers, params=params,
        )

    # ------------------------------------------------------------- catalog
    def create_excursion(self, payload, headers):
        return self._request("POST", f"{PREFIX}/excursions", payload, headers)

    def get_excursion(self, excursion_id, headers):
        return self._request(
            "GET", f"{PREFIX}/excursions/{excursion_id}", headers=headers,
        )

    def list_excursions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/excursions", headers=headers, params=params,
        )

    def amend_excursion(self, excursion_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/excursions/{excursion_id}", payload, headers,
        )

    def catalog_action(self, excursion_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/excursions/{excursion_id}/catalog-actions", payload, headers,
        )

    # ---------------------------------------------------------- departures
    def create_departure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/departures", payload, headers)

    def get_departure(self, departure_id, headers):
        return self._request(
            "GET", f"{PREFIX}/departures/{departure_id}", headers=headers,
        )

    def list_departures(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/departures", headers=headers, params=params,
        )

    def rebalance_allocation(self, departure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/departures/{departure_id}/allocation", payload, headers,
        )

    def assign_tender_wave(self, departure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/departures/{departure_id}/tender-assignment",
            payload, headers,
        )

    def reschedule_meeting(self, departure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/departures/{departure_id}/reschedule-meeting",
            payload, headers,
        )

    def cancel_departure(self, departure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/departures/{departure_id}/cancel", payload, headers,
        )

    def departure_operation(self, departure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/departures/{departure_id}/operations", payload, headers,
        )

    # -------------------------------------------------------------- guests
    def create_guest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"{PREFIX}/guests/{guest_id}", headers=headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/guests", headers=headers, params=params)

    # ------------------------------------------------------------ bookings
    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings", headers=headers, params=params)

    def fulfillment_action(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/fulfillment-actions", payload, headers,
        )

    def cancel_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/cancel", payload, headers,
        )

    def file_incident(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/incidents", payload, headers,
        )

    # ------------------------------------------------------- refund ledger
    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/refund-ledger-entries/{entry_id}", headers=headers,
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/refund-ledger-entries", headers=headers, params=params,
        )

    # ----------------------------------------------------------- incidents
    def get_incident(self, incident_id, headers):
        return self._request(
            "GET", f"{PREFIX}/incidents/{incident_id}", headers=headers,
        )

    def list_incidents(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/incidents", headers=headers, params=params,
        )

    def open_claim(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incidents/{incident_id}/claims", payload, headers,
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incidents/{incident_id}/close", payload, headers,
        )

    # -------------------------------------------------------------- claims
    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def claim_action(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/actions", payload, headers,
        )

    # ------------------------------------------------- commission statements
    def create_commission_statement(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/commission-statements", payload, headers,
        )

    def get_commission_statement(self, statement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/commission-statements/{statement_id}", headers=headers,
        )

    def list_commission_statements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/commission-statements", headers=headers, params=params,
        )

    def statement_transition(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/commission-statements/{statement_id}/transitions",
            payload, headers,
        )


api_client = ApiClient()
