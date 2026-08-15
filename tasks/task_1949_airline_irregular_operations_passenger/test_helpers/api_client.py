"""API client: one method per endpoint defined in PRD §4 (all under /irops)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/irops/_clock/set_current_utc", payload, headers)

    # --- passengers ---
    def create_passenger(self, payload, headers):
        return self._request("POST", "/irops/passengers", payload, headers)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/irops/passengers/{passenger_id}", headers=headers)

    def list_passengers(self, headers, params=None):
        return self._request("GET", "/irops/passengers", headers=headers, params=params)

    # --- flights ---
    def create_flight(self, payload, headers):
        return self._request("POST", "/irops/flights", payload, headers)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/irops/flights/{flight_id}", headers=headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/irops/flights", headers=headers, params=params)

    def list_cabin_inventories(self, flight_id, headers):
        return self._request("GET", f"/irops/flights/{flight_id}/cabin-inventories", headers=headers)

    def delay_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/irops/flights/{flight_id}/delay", payload, headers)

    def cancel_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/irops/flights/{flight_id}/cancel", payload, headers)

    def depart_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/irops/flights/{flight_id}/depart", payload, headers)

    def record_actuals(self, flight_id, payload, headers):
        return self._request("POST", f"/irops/flights/{flight_id}/record-actuals", payload, headers)

    # --- disruption events ---
    def create_disruption_event(self, payload, headers):
        return self._request("POST", "/irops/disruption-events", payload, headers)

    def get_disruption_event(self, event_id, headers):
        return self._request("GET", f"/irops/disruption-events/{event_id}", headers=headers)

    def list_disruption_events(self, headers, params=None):
        return self._request("GET", "/irops/disruption-events", headers=headers, params=params)

    def list_event_flights(self, event_id, headers):
        return self._request("GET", f"/irops/disruption-events/{event_id}/flights", headers=headers)

    def list_cost_entries(self, event_id, headers):
        return self._request("GET", f"/irops/disruption-events/{event_id}/cost-entries", headers=headers)

    def get_cost_summary(self, event_id, headers):
        return self._request("GET", f"/irops/disruption-events/{event_id}/cost-summary", headers=headers)

    def assess_event(self, event_id, headers):
        return self._request("POST", f"/irops/disruption-events/{event_id}/assess", {}, headers)

    def declare_recovery(self, event_id, headers):
        return self._request("POST", f"/irops/disruption-events/{event_id}/declare-recovery", {}, headers)

    def reopen_event(self, event_id, headers):
        return self._request("POST", f"/irops/disruption-events/{event_id}/reopen", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/irops/disruption-events/{event_id}/close", {}, headers)

    # --- bookings / segments ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/irops/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/irops/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/irops/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/irops/bookings/{booking_id}/cancel", {}, headers)

    def get_booking_segment(self, segment_id, headers):
        return self._request("GET", f"/irops/booking-segments/{segment_id}", headers=headers)

    def list_booking_segments(self, headers, params=None):
        return self._request("GET", "/irops/booking-segments", headers=headers, params=params)

    # --- reaccommodation cases / options ---
    def get_reaccommodation_case(self, case_id, headers):
        return self._request("GET", f"/irops/reaccommodation-cases/{case_id}", headers=headers)

    def list_reaccommodation_cases(self, headers, params=None):
        return self._request("GET", "/irops/reaccommodation-cases", headers=headers, params=params)

    def generate_options(self, case_id, payload, headers):
        return self._request("POST", f"/irops/reaccommodation-cases/{case_id}/generate-options", payload, headers)

    def list_case_options(self, case_id, headers):
        return self._request("GET", f"/irops/reaccommodation-cases/{case_id}/options", headers=headers)

    def get_reaccommodation_option(self, option_id, headers):
        return self._request("GET", f"/irops/reaccommodation-options/{option_id}", headers=headers)

    def list_reaccommodation_options(self, headers, params=None):
        return self._request("GET", "/irops/reaccommodation-options", headers=headers, params=params)

    def commit_case(self, case_id, payload, headers):
        return self._request("POST", f"/irops/reaccommodation-cases/{case_id}/commit", payload, headers)

    def escalate_case(self, case_id, headers):
        return self._request("POST", f"/irops/reaccommodation-cases/{case_id}/escalate", {}, headers)

    # --- interline agreements ---
    def create_interline_agreement(self, payload, headers):
        return self._request("POST", "/irops/interline-agreements", payload, headers)

    def get_interline_agreement(self, agreement_id, headers):
        return self._request("GET", f"/irops/interline-agreements/{agreement_id}", headers=headers)

    def list_interline_agreements(self, headers, params=None):
        return self._request("GET", "/irops/interline-agreements", headers=headers, params=params)

    def suspend_interline_agreement(self, agreement_id, headers):
        return self._request("POST", f"/irops/interline-agreements/{agreement_id}/suspend", {}, headers)

    # --- vouchers ---
    def issue_voucher(self, booking_id, payload, headers):
        return self._request("POST", f"/irops/bookings/{booking_id}/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/irops/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/irops/vouchers", headers=headers, params=params)

    def redeem_voucher(self, voucher_id, payload, headers):
        return self._request("POST", f"/irops/vouchers/{voucher_id}/redeem", payload, headers)

    def void_voucher(self, voucher_id, headers):
        return self._request("POST", f"/irops/vouchers/{voucher_id}/void", {}, headers)

    # --- crew assignments ---
    def create_crew_assignment(self, flight_id, payload, headers):
        return self._request("POST", f"/irops/flights/{flight_id}/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/irops/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/irops/crew-assignments", headers=headers, params=params)

    def release_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/irops/crew-assignments/{assignment_id}/release", {}, headers)

    # --- refund elections ---
    def create_refund_election(self, booking_id, payload, headers):
        return self._request("POST", f"/irops/bookings/{booking_id}/refund-elections", payload, headers)

    def get_refund_election(self, election_id, headers):
        return self._request("GET", f"/irops/refund-elections/{election_id}", headers=headers)

    def list_refund_elections(self, headers, params=None):
        return self._request("GET", "/irops/refund-elections", headers=headers, params=params)

    def process_refund_election(self, election_id, headers):
        return self._request("POST", f"/irops/refund-elections/{election_id}/process", {}, headers)

    # --- communication log / process-due batch ---
    def get_communication_log(self, log_id, headers):
        return self._request("GET", f"/irops/communication-logs/{log_id}", headers=headers)

    def list_communication_logs(self, headers, params=None):
        return self._request("GET", "/irops/communication-logs", headers=headers, params=params)

    def process_due(self, headers):
        return self._request("POST", "/irops/communications/process-due", {}, headers)


api_client = ApiClient()
