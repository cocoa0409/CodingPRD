"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- RepairEvent ----
    def create_repair_event(self, payload, headers):
        return self._request("POST", "/api/repair-events", payload, headers)

    def list_repair_events(self, headers, params=None):
        return self._request("GET", "/api/repair-events", headers=headers, params=params)

    def get_repair_event(self, event_id, headers):
        return self._request("GET", f"/api/repair-events/{event_id}", headers=headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/publish", headers=headers)

    def open_intake(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/open-intake", headers=headers)

    def close_intake(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/close-intake", headers=headers)

    def begin_repairs(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/begin-repairs", headers=headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/close", headers=headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/cancel", headers=headers)

    def report_event(self, event_id, headers):
        return self._request("POST", f"/api/repair-events/{event_id}/report", headers=headers)

    # ---- Station ----
    def create_station(self, payload, headers):
        return self._request("POST", "/api/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/api/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/api/stations/{station_id}", headers=headers)

    def open_station(self, station_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/open", headers=headers)

    def pause_station(self, station_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/pause", headers=headers)

    def resume_station(self, station_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/resume", headers=headers)

    def close_station(self, station_id, headers):
        return self._request("POST", f"/api/stations/{station_id}/close", headers=headers)

    # ---- FixerProfile ----
    def create_fixer_profile(self, payload, headers):
        return self._request("POST", "/api/fixer-profiles", payload, headers)

    def list_fixer_profiles(self, headers, params=None):
        return self._request("GET", "/api/fixer-profiles", headers=headers, params=params)

    def get_fixer_profile(self, fixer_id, headers):
        return self._request("GET", f"/api/fixer-profiles/{fixer_id}", headers=headers)

    def suspend_fixer(self, fixer_id, headers):
        return self._request("POST", f"/api/fixer-profiles/{fixer_id}/suspend", headers=headers)

    def reinstate_fixer(self, fixer_id, headers):
        return self._request("POST", f"/api/fixer-profiles/{fixer_id}/reinstate", headers=headers)

    def deactivate_fixer(self, fixer_id, headers):
        return self._request("POST", f"/api/fixer-profiles/{fixer_id}/deactivate", headers=headers)

    # ---- FixerSkill ----
    def create_fixer_skill(self, payload, headers):
        return self._request("POST", "/api/fixer-skills", payload, headers)

    def list_fixer_skills(self, headers, params=None):
        return self._request("GET", "/api/fixer-skills", headers=headers, params=params)

    def get_fixer_skill(self, skill_id, headers):
        return self._request("GET", f"/api/fixer-skills/{skill_id}", headers=headers)

    def delete_fixer_skill(self, skill_id, headers):
        return self._request("DELETE", f"/api/fixer-skills/{skill_id}", headers=headers)

    # ---- FixerShift ----
    def create_fixer_shift(self, payload, headers):
        return self._request("POST", "/api/fixer-shifts", payload, headers)

    def list_fixer_shifts(self, headers, params=None):
        return self._request("GET", "/api/fixer-shifts", headers=headers, params=params)

    def get_fixer_shift(self, shift_id, headers):
        return self._request("GET", f"/api/fixer-shifts/{shift_id}", headers=headers)

    def confirm_shift(self, shift_id, headers):
        return self._request("POST", f"/api/fixer-shifts/{shift_id}/confirm", headers=headers)

    def check_in_shift(self, shift_id, headers):
        return self._request("POST", f"/api/fixer-shifts/{shift_id}/check-in", headers=headers)

    def check_out_shift(self, shift_id, completion, headers):
        return self._request("POST", f"/api/fixer-shifts/{shift_id}/check-out",
                             {"completion": completion}, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/api/fixer-shifts/{shift_id}/cancel", headers=headers)

    # ---- Visitor / Waiver ----
    def create_visitor(self, payload, headers):
        return self._request("POST", "/api/visitors", payload, headers)

    def list_visitors(self, headers, params=None):
        return self._request("GET", "/api/visitors", headers=headers, params=params)

    def get_visitor(self, visitor_id, headers):
        return self._request("GET", f"/api/visitors/{visitor_id}", headers=headers)

    def create_waiver(self, payload, headers):
        return self._request("POST", "/api/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/api/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/api/waivers/{waiver_id}", headers=headers)

    def revoke_waiver(self, waiver_id, headers):
        return self._request("POST", f"/api/waivers/{waiver_id}/revoke", headers=headers)

    # ---- RepairItem / Triage ----
    def create_repair_item(self, payload, headers):
        return self._request("POST", "/api/repair-items", payload, headers)

    def list_repair_items(self, headers, params=None):
        return self._request("GET", "/api/repair-items", headers=headers, params=params)

    def get_repair_item(self, item_id, headers):
        return self._request("GET", f"/api/repair-items/{item_id}", headers=headers)

    def create_triage_record(self, item_id, payload, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/triage-records", payload, headers)

    def list_triage_records(self, headers, params=None):
        return self._request("GET", "/api/triage-records", headers=headers, params=params)

    def get_triage_record(self, triage_id, headers):
        return self._request("GET", f"/api/triage-records/{triage_id}", headers=headers)

    def enqueue_item(self, item_id, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/enqueue", headers=headers)

    def assign_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/assign", payload, headers)

    def start_repair(self, item_id, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/start-repair", headers=headers)

    def return_to_queue(self, item_id, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/return-to-queue", headers=headers)

    def unassign_item(self, item_id, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/unassign", headers=headers)

    def reopen_item(self, item_id, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/reopen", headers=headers)

    def withdraw_item(self, item_id, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/withdraw", headers=headers)

    # ---- RepairOutcome ----
    def record_outcome(self, item_id, payload, headers):
        return self._request("POST", f"/api/repair-items/{item_id}/outcomes", payload, headers)

    def list_outcomes(self, headers, params=None):
        return self._request("GET", "/api/repair-outcomes", headers=headers, params=params)

    def get_outcome(self, outcome_id, headers):
        return self._request("GET", f"/api/repair-outcomes/{outcome_id}", headers=headers)

    def verify_outcome(self, outcome_id, headers):
        return self._request("POST", f"/api/repair-outcomes/{outcome_id}/verify", headers=headers)

    def reject_outcome(self, outcome_id, headers):
        return self._request("POST", f"/api/repair-outcomes/{outcome_id}/reject", headers=headers)

    # ---- Parts ----
    def create_part_stock(self, payload, headers):
        return self._request("POST", "/api/part-stocks", payload, headers)

    def list_part_stocks(self, headers, params=None):
        return self._request("GET", "/api/part-stocks", headers=headers, params=params)

    def get_part_stock(self, stock_id, headers):
        return self._request("GET", f"/api/part-stocks/{stock_id}", headers=headers)

    def adjust_part_stock(self, stock_id, payload, headers):
        return self._request("PATCH", f"/api/part-stocks/{stock_id}", payload, headers)

    def create_part_reservation(self, payload, headers):
        return self._request("POST", "/api/part-reservations", payload, headers)

    def list_part_reservations(self, headers, params=None):
        return self._request("GET", "/api/part-reservations", headers=headers, params=params)

    def get_part_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/part-reservations/{reservation_id}", headers=headers)

    def commit_reservation(self, reservation_id, headers):
        return self._request("POST", f"/api/part-reservations/{reservation_id}/commit", headers=headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/api/part-reservations/{reservation_id}/release", headers=headers)

    # ---- SafetyIncident ----
    def create_safety_incident(self, payload, headers):
        return self._request("POST", "/api/safety-incidents", payload, headers)

    def list_safety_incidents(self, headers, params=None):
        return self._request("GET", "/api/safety-incidents", headers=headers, params=params)

    def get_safety_incident(self, incident_id, headers):
        return self._request("GET", f"/api/safety-incidents/{incident_id}", headers=headers)

    def resolve_incident(self, incident_id, resolution_action, headers):
        return self._request("POST", f"/api/safety-incidents/{incident_id}/resolve",
                             {"resolution_action": resolution_action}, headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/api/safety-incidents/{incident_id}/dismiss", headers=headers)

    # ---- Donation ----
    def create_donation(self, payload, headers):
        return self._request("POST", "/api/donations", payload, headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/api/donations", headers=headers, params=params)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/api/donations/{donation_id}", headers=headers)

    def receive_donation(self, donation_id, headers):
        return self._request("POST", f"/api/donations/{donation_id}/receive", headers=headers)

    def receipt_donation(self, donation_id, headers):
        return self._request("POST", f"/api/donations/{donation_id}/receipt", headers=headers)

    def refund_donation(self, donation_id, headers):
        return self._request("POST", f"/api/donations/{donation_id}/refund", headers=headers)

    # ---- EventReport ----
    def list_event_reports(self, headers, params=None):
        return self._request("GET", "/api/event-reports", headers=headers, params=params)

    def get_event_report(self, report_id, headers):
        return self._request("GET", f"/api/event-reports/{report_id}", headers=headers)


api_client = ApiClient()
