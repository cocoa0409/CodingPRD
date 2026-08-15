"""API client: one method per endpoint defined in the PRD §4 address map."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    def patch_staff(self, staff_id, payload, headers):
        return self._request("PATCH", f"/staff/{staff_id}", payload, headers)

    # --- Athletes ---
    def create_athlete(self, payload, headers):
        return self._request("POST", "/athletes", payload, headers)

    def list_athletes(self, headers, params=None):
        return self._request("GET", "/athletes", headers=headers, params=params)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}", headers=headers)

    def get_athlete_clearance(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}/clearance",
                             headers=headers)

    # --- Pre-participation physicals ---
    def create_physical(self, payload, headers):
        return self._request("POST", "/physicals", payload, headers)

    def list_physicals(self, headers, params=None):
        return self._request("GET", "/physicals", headers=headers, params=params)

    def get_physical(self, physical_id, headers):
        return self._request("GET", f"/physicals/{physical_id}", headers=headers)

    def verify_physical(self, physical_id, headers):
        return self._request("POST", f"/physicals/{physical_id}/verify",
                             {}, headers)

    def void_physical(self, physical_id, headers):
        return self._request("POST", f"/physicals/{physical_id}/void",
                             {}, headers)

    # --- Baseline concussion tests ---
    def create_baseline_test(self, payload, headers):
        return self._request("POST", "/baseline-tests", payload, headers)

    def list_baseline_tests(self, headers, params=None):
        return self._request("GET", "/baseline-tests", headers=headers,
                             params=params)

    def get_baseline_test(self, test_id, headers):
        return self._request("GET", f"/baseline-tests/{test_id}", headers=headers)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def get_venue_activity_status(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}/activity-status",
                             headers=headers)

    # --- Emergency action plans ---
    def create_eap(self, payload, headers):
        return self._request("POST", "/emergency-action-plans", payload, headers)

    def list_eaps(self, headers, params=None):
        return self._request("GET", "/emergency-action-plans", headers=headers,
                             params=params)

    def get_eap(self, eap_id, headers):
        return self._request("GET", f"/emergency-action-plans/{eap_id}",
                             headers=headers)

    def submit_eap(self, eap_id, headers):
        return self._request("POST", f"/emergency-action-plans/{eap_id}/submit",
                             {}, headers)

    def approve_eap(self, eap_id, headers):
        return self._request("POST", f"/emergency-action-plans/{eap_id}/approve",
                             {}, headers)

    def reject_eap(self, eap_id, headers):
        return self._request("POST", f"/emergency-action-plans/{eap_id}/reject",
                             {}, headers)

    def activate_eap(self, eap_id, payload, headers):
        return self._request("POST", f"/emergency-action-plans/{eap_id}/activate",
                             payload, headers)

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def get_event_coverage_status(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/coverage-status",
                             headers=headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/start", {}, headers)

    def suspend_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/suspend", {}, headers)

    def resume_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/resume", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    # --- Coverage assignments ---
    def create_coverage_assignment(self, payload, headers):
        return self._request("POST", "/coverage-assignments", payload, headers)

    def list_coverage_assignments(self, headers, params=None):
        return self._request("GET", "/coverage-assignments", headers=headers,
                             params=params)

    def get_coverage_assignment(self, assignment_id, headers):
        return self._request("GET", f"/coverage-assignments/{assignment_id}",
                             headers=headers)

    def acknowledge_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/acknowledge",
            {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/decline",
            {}, headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/check-in",
            {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/complete",
            {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/cancel",
            {}, headers)

    # --- Weather readings ---
    def create_weather_reading(self, payload, headers):
        return self._request("POST", "/weather-readings", payload, headers)

    def list_weather_readings(self, headers, params=None):
        return self._request("GET", "/weather-readings", headers=headers,
                             params=params)

    def get_weather_reading(self, reading_id, headers):
        return self._request("GET", f"/weather-readings/{reading_id}",
                             headers=headers)

    # --- Injuries ---
    def create_injury(self, payload, headers):
        return self._request("POST", "/injuries", payload, headers)

    def list_injuries(self, headers, params=None):
        return self._request("GET", "/injuries", headers=headers, params=params)

    def get_injury(self, injury_id, headers):
        return self._request("GET", f"/injuries/{injury_id}", headers=headers)

    def begin_care_injury(self, injury_id, headers):
        return self._request("POST", f"/injuries/{injury_id}/begin-care",
                             {}, headers)

    def resolve_injury(self, injury_id, headers):
        return self._request("POST", f"/injuries/{injury_id}/resolve",
                             {}, headers)

    def reopen_injury(self, injury_id, payload, headers):
        return self._request("POST", f"/injuries/{injury_id}/reopen",
                             payload, headers)

    def close_injury(self, injury_id, headers):
        return self._request("POST", f"/injuries/{injury_id}/close", {}, headers)

    # --- Physician referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def schedule_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/schedule",
                             payload, headers)

    def complete_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/complete",
                             payload, headers)

    def request_addendum_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/request-addendum",
            payload, headers)

    def close_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/close",
                             {}, headers)

    def cancel_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/cancel",
                             {}, headers)

    # --- Return-to-play protocols ---
    def create_rtp_protocol(self, injury_id, payload, headers):
        return self._request("POST", f"/injuries/{injury_id}/rtp-protocols",
                             payload, headers)

    def list_rtp_protocols(self, headers, params=None):
        return self._request("GET", "/rtp-protocols", headers=headers,
                             params=params)

    def get_rtp_protocol(self, protocol_id, headers):
        return self._request("GET", f"/rtp-protocols/{protocol_id}",
                             headers=headers)

    def advance_rtp_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/rtp-protocols/{protocol_id}/advance",
                             payload, headers)

    def regress_rtp_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/rtp-protocols/{protocol_id}/regress",
                             payload, headers)

    def clear_rtp_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/rtp-protocols/{protocol_id}/clear",
                             payload, headers)

    def terminate_rtp_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/rtp-protocols/{protocol_id}/terminate",
                             payload, headers)

    # --- Guardian notifications ---
    def list_guardian_notifications(self, headers, params=None):
        return self._request("GET", "/guardian-notifications", headers=headers,
                             params=params)

    def get_guardian_notification(self, notification_id, headers):
        return self._request("GET",
                             f"/guardian-notifications/{notification_id}",
                             headers=headers)

    def send_guardian_notification(self, notification_id, headers):
        return self._request(
            "POST", f"/guardian-notifications/{notification_id}/send",
            {}, headers)

    def acknowledge_guardian_notification(self, notification_id, headers):
        return self._request(
            "POST", f"/guardian-notifications/{notification_id}/acknowledge",
            {}, headers)

    def retry_guardian_notification(self, notification_id, headers):
        return self._request(
            "POST", f"/guardian-notifications/{notification_id}/retry",
            {}, headers)

    # --- Supply inventory ---
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/supply-items", payload, headers)

    def list_supply_items(self, headers, params=None):
        return self._request("GET", "/supply-items", headers=headers,
                             params=params)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/supply-items/{item_id}", headers=headers)

    def patch_supply_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/supply-items/{item_id}", payload,
                             headers)

    def get_supply_item_valuation(self, item_id, policy, headers):
        return self._request("GET", f"/supply-items/{item_id}/valuation",
                             headers=headers, params={"policy": policy})

    def get_reorder_suggestion(self, item_id, headers):
        return self._request("GET",
                             f"/supply-items/{item_id}/reorder-suggestion",
                             headers=headers)

    def create_inventory_transaction(self, payload, headers):
        return self._request("POST", "/inventory-transactions", payload, headers)

    def list_inventory_transactions(self, headers, params=None):
        return self._request("GET", "/inventory-transactions", headers=headers,
                             params=params)

    def get_inventory_transaction(self, txn_id, headers):
        return self._request("GET", f"/inventory-transactions/{txn_id}",
                             headers=headers)

    # --- Restock orders ---
    def create_restock_order(self, payload, headers):
        return self._request("POST", "/restock-orders", payload, headers)

    def list_restock_orders(self, headers, params=None):
        return self._request("GET", "/restock-orders", headers=headers,
                             params=params)

    def get_restock_order(self, order_id, headers):
        return self._request("GET", f"/restock-orders/{order_id}",
                             headers=headers)

    def submit_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/submit",
                             {}, headers)

    def approve_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/approve",
                             {}, headers)

    def reject_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/reject",
                             {}, headers)

    def receive_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/receive",
                             {}, headers)

    def cancel_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/cancel",
                             {}, headers)

    # --- Supply budgets ---
    def create_supply_budget(self, payload, headers):
        return self._request("POST", "/supply-budgets", payload, headers)

    def list_supply_budgets(self, headers, params=None):
        return self._request("GET", "/supply-budgets", headers=headers,
                             params=params)

    def get_supply_budget(self, budget_id, headers):
        return self._request("GET", f"/supply-budgets/{budget_id}",
                             headers=headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
