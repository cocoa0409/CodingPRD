"""API client: one method per endpoint defined in the PRD (§4).

Every path is absolute; there is no shared version prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ── Carriers ─────────────────────────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def suspend_carrier(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/carriers/{carrier_id}/suspend", payload, headers
        )

    # ── Stations ─────────────────────────────────────────────────────────
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    # ── Seasons ──────────────────────────────────────────────────────────
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/seasons", headers=headers, params=params)

    def transition_season(self, season_id, payload, headers):
        return self._request(
            "POST", f"/seasons/{season_id}/transition", payload, headers
        )

    def run_slot_audit(self, season_id, payload, headers):
        return self._request(
            "POST", f"/seasons/{season_id}/slot-audit", payload, headers
        )

    # ── Aircraft ─────────────────────────────────────────────────────────
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    def get_rotation_feasibility(self, aircraft_id, headers):
        return self._request(
            "GET", f"/aircraft/{aircraft_id}/rotation-feasibility", headers=headers
        )

    # ── Schedule versions ────────────────────────────────────────────────
    def create_schedule_version(self, payload, headers):
        return self._request("POST", "/schedule-versions", payload, headers)

    def get_schedule_version(self, schedule_version_id, headers):
        return self._request(
            "GET", f"/schedule-versions/{schedule_version_id}", headers=headers
        )

    def list_schedule_versions(self, headers, params=None):
        return self._request(
            "GET", "/schedule-versions", headers=headers, params=params
        )

    def supersede_schedule_version(self, schedule_version_id, payload, headers):
        return self._request(
            "POST",
            f"/schedule-versions/{schedule_version_id}/supersede",
            payload,
            headers,
        )

    def validate_schedule_version(self, schedule_version_id, headers, payload=None):
        return self._request(
            "POST",
            f"/schedule-versions/{schedule_version_id}/validate",
            payload,
            headers,
        )

    def withdraw_schedule_version(self, schedule_version_id, payload, headers):
        return self._request(
            "POST",
            f"/schedule-versions/{schedule_version_id}/withdraw",
            payload,
            headers,
        )

    # ── Flight legs ──────────────────────────────────────────────────────
    def create_flight_leg(self, payload, headers):
        return self._request("POST", "/flight-legs", payload, headers)

    def get_flight_leg(self, flight_leg_id, headers):
        return self._request("GET", f"/flight-legs/{flight_leg_id}", headers=headers)

    def list_flight_legs(self, headers, params=None):
        return self._request("GET", "/flight-legs", headers=headers, params=params)

    def patch_flight_leg(self, flight_leg_id, payload, headers):
        return self._request(
            "PATCH", f"/flight-legs/{flight_leg_id}", payload, headers
        )

    def assign_aircraft(self, flight_leg_id, payload, headers):
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/assign-aircraft", payload, headers
        )

    def attach_slot(self, flight_leg_id, payload, headers):
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/attach-slot", payload, headers
        )

    def cancel_flight_leg(self, flight_leg_id, payload, headers):
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/cancel", payload, headers
        )

    def booking_snapshot(self, flight_leg_id, payload, headers):
        return self._request(
            "POST", f"/flight-legs/{flight_leg_id}/booking-snapshot", payload, headers
        )

    # ── Slot holdings ────────────────────────────────────────────────────
    def create_slot_holding(self, payload, headers):
        return self._request("POST", "/slot-holdings", payload, headers)

    def get_slot_holding(self, slot_holding_id, headers):
        return self._request(
            "GET", f"/slot-holdings/{slot_holding_id}", headers=headers
        )

    def list_slot_holdings(self, headers, params=None):
        return self._request("GET", "/slot-holdings", headers=headers, params=params)

    def return_slot_holding(self, slot_holding_id, payload, headers):
        return self._request(
            "POST", f"/slot-holdings/{slot_holding_id}/return", payload, headers
        )

    # ── Slot utilization records ──────────────────────────────────────────
    def create_slot_utilization_record(self, payload, headers):
        return self._request("POST", "/slot-utilization-records", payload, headers)

    def get_slot_utilization_record(self, slot_utilization_record_id, headers):
        return self._request(
            "GET",
            f"/slot-utilization-records/{slot_utilization_record_id}",
            headers=headers,
        )

    def list_slot_utilization_records(self, headers, params=None):
        return self._request(
            "GET", "/slot-utilization-records", headers=headers, params=params
        )

    # ── Slot transactions ────────────────────────────────────────────────
    def create_slot_transaction(self, payload, headers):
        return self._request("POST", "/slot-transactions", payload, headers)

    def get_slot_transaction(self, slot_transaction_id, headers):
        return self._request(
            "GET", f"/slot-transactions/{slot_transaction_id}", headers=headers
        )

    def list_slot_transactions(self, headers, params=None):
        return self._request(
            "GET", "/slot-transactions", headers=headers, params=params
        )

    def respond_slot_transaction(self, slot_transaction_id, payload, headers):
        return self._request(
            "POST", f"/slot-transactions/{slot_transaction_id}/respond", payload, headers
        )

    def approve_slot_transaction(self, slot_transaction_id, payload, headers):
        return self._request(
            "POST", f"/slot-transactions/{slot_transaction_id}/approve", payload, headers
        )

    def withdraw_slot_transaction(self, slot_transaction_id, payload, headers):
        return self._request(
            "POST",
            f"/slot-transactions/{slot_transaction_id}/withdraw",
            payload,
            headers,
        )

    # ── Filing submissions ───────────────────────────────────────────────
    def create_filing_submission(self, payload, headers):
        return self._request("POST", "/filing-submissions", payload, headers)

    def get_filing_submission(self, filing_submission_id, headers):
        return self._request(
            "GET", f"/filing-submissions/{filing_submission_id}", headers=headers
        )

    def list_filing_submissions(self, headers, params=None):
        return self._request(
            "GET", "/filing-submissions", headers=headers, params=params
        )

    def codeshare_ack(self, filing_submission_id, payload, headers):
        return self._request(
            "POST",
            f"/filing-submissions/{filing_submission_id}/codeshare-ack",
            payload,
            headers,
        )

    def transmit_filing_submission(self, filing_submission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/filing-submissions/{filing_submission_id}/transmit",
            payload,
            headers,
        )

    def acknowledge_filing_submission(self, filing_submission_id, payload, headers):
        return self._request(
            "POST",
            f"/filing-submissions/{filing_submission_id}/acknowledge",
            payload,
            headers,
        )

    # ── Route authorities ────────────────────────────────────────────────
    def create_route_authority(self, payload, headers):
        return self._request("POST", "/route-authorities", payload, headers)

    def get_route_authority(self, route_authority_id, headers):
        return self._request(
            "GET", f"/route-authorities/{route_authority_id}", headers=headers
        )

    def list_route_authorities(self, headers, params=None):
        return self._request(
            "GET", "/route-authorities", headers=headers, params=params
        )

    def suspend_route_authority(self, route_authority_id, payload, headers):
        return self._request(
            "POST", f"/route-authorities/{route_authority_id}/suspend", payload, headers
        )

    # ── Notification obligations ─────────────────────────────────────────
    def create_notification_obligation(self, payload, headers):
        return self._request("POST", "/notification-obligations", payload, headers)

    def get_notification_obligation(self, notification_obligation_id, headers):
        return self._request(
            "GET",
            f"/notification-obligations/{notification_obligation_id}",
            headers=headers,
        )

    def list_notification_obligations(self, headers, params=None):
        return self._request(
            "GET", "/notification-obligations", headers=headers, params=params
        )

    def dispatch_notification_obligation(
        self, notification_obligation_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/notification-obligations/{notification_obligation_id}/dispatch",
            payload,
            headers,
        )

    # ── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
