"""API client: one method per endpoint defined in the PRD (all paths under
the /vendor-office mount)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/vendor-office/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendor-office/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendor-office/vendors", headers=headers,
                             params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendor-office/vendors/{vendor_id}",
                             headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendor-office/vendors/{vendor_id}/suspend",
                             {}, headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendor-office/vendors/{vendor_id}/reinstate",
                             {}, headers)

    def terminate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendor-office/vendors/{vendor_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Vendor representatives
    # ------------------------------------------------------------------
    def create_rep(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendor-office/vendors/{vendor_id}/reps",
                             payload, headers)

    def list_reps(self, headers, params=None):
        return self._request("GET", "/vendor-office/reps", headers=headers,
                             params=params)

    def get_rep(self, rep_id, headers):
        return self._request("GET", f"/vendor-office/reps/{rep_id}", headers=headers)

    def approve_credential(self, rep_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/reps/{rep_id}/approve-credential",
                             payload, headers)

    def revoke_credential(self, rep_id, headers):
        return self._request("POST",
                             f"/vendor-office/reps/{rep_id}/revoke-credential",
                             {}, headers)

    # ------------------------------------------------------------------
    # OR rooms
    # ------------------------------------------------------------------
    def create_or_room(self, payload, headers):
        return self._request("POST", "/vendor-office/or-rooms", payload, headers)

    def list_or_rooms(self, headers, params=None):
        return self._request("GET", "/vendor-office/or-rooms", headers=headers,
                             params=params)

    def get_or_room(self, room_id, headers):
        return self._request("GET", f"/vendor-office/or-rooms/{room_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Sterilizer units
    # ------------------------------------------------------------------
    def create_sterilizer_unit(self, payload, headers):
        return self._request("POST", "/vendor-office/sterilizer-units", payload,
                             headers)

    def list_sterilizer_units(self, headers, params=None):
        return self._request("GET", "/vendor-office/sterilizer-units",
                             headers=headers, params=params)

    def get_sterilizer_unit(self, unit_id, headers):
        return self._request("GET", f"/vendor-office/sterilizer-units/{unit_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Surgical cases and delay events
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/vendor-office/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/vendor-office/cases", headers=headers,
                             params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/vendor-office/cases/{case_id}",
                             headers=headers)

    def reschedule_case(self, case_id, payload, headers):
        return self._request("POST", f"/vendor-office/cases/{case_id}/reschedule",
                             payload, headers)

    def start_case(self, case_id, payload, headers):
        return self._request("POST", f"/vendor-office/cases/{case_id}/start",
                             payload, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/vendor-office/cases/{case_id}/complete",
                             {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/vendor-office/cases/{case_id}/cancel",
                             {}, headers)

    def create_delay_event(self, case_id, payload, headers):
        return self._request("POST", f"/vendor-office/cases/{case_id}/delay-events",
                             payload, headers)

    def list_delay_events(self, headers, params=None):
        return self._request("GET", "/vendor-office/delay-events", headers=headers,
                             params=params)

    def get_delay_event(self, event_id, headers):
        return self._request("GET", f"/vendor-office/delay-events/{event_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Loaner requests and trays
    # ------------------------------------------------------------------
    def create_request(self, payload, headers):
        return self._request("POST", "/vendor-office/requests", payload, headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/vendor-office/requests", headers=headers,
                             params=params)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/vendor-office/requests/{request_id}",
                             headers=headers)

    def add_tray(self, request_id, payload, headers):
        return self._request("POST", f"/vendor-office/requests/{request_id}/trays",
                             payload, headers)

    def list_request_trays(self, request_id, headers, params=None):
        return self._request("GET",
                             f"/vendor-office/requests/{request_id}/trays",
                             headers=headers, params=params)

    def submit_request(self, request_id, headers):
        return self._request("POST", f"/vendor-office/requests/{request_id}/submit",
                             {}, headers)

    def decide_request(self, request_id, payload, headers):
        return self._request("POST", f"/vendor-office/requests/{request_id}/decide",
                             payload, headers)

    def cancel_request(self, request_id, headers):
        return self._request("POST", f"/vendor-office/requests/{request_id}/cancel",
                             {}, headers)

    def list_trays(self, headers, params=None):
        return self._request("GET", "/vendor-office/trays", headers=headers,
                             params=params)

    def get_tray(self, tray_id, headers):
        return self._request("GET", f"/vendor-office/trays/{tray_id}",
                             headers=headers)

    def mark_tray_missing(self, tray_id, headers):
        return self._request("POST",
                             f"/vendor-office/trays/{tray_id}/mark-missing",
                             {}, headers)

    def stage_tray(self, tray_id, headers):
        return self._request("POST", f"/vendor-office/trays/{tray_id}/stage",
                             {}, headers)

    # ------------------------------------------------------------------
    # Delivery check-ins
    # ------------------------------------------------------------------
    def create_check_in(self, request_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/requests/{request_id}/check-ins",
                             payload, headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", "/vendor-office/check-ins", headers=headers,
                             params=params)

    def get_check_in(self, check_in_id, headers):
        return self._request("GET", f"/vendor-office/check-ins/{check_in_id}",
                             headers=headers)

    def verify_check_in(self, check_in_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/check-ins/{check_in_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # Sterilization turns
    # ------------------------------------------------------------------
    def create_turn(self, tray_id, headers):
        return self._request("POST", f"/vendor-office/trays/{tray_id}/turns",
                             {}, headers)

    def list_turns(self, headers, params=None):
        return self._request("GET", "/vendor-office/turns", headers=headers,
                             params=params)

    def get_turn(self, turn_id, headers):
        return self._request("GET", f"/vendor-office/turns/{turn_id}",
                             headers=headers)

    def start_cycle(self, turn_id, payload, headers):
        return self._request("POST", f"/vendor-office/turns/{turn_id}/start-cycle",
                             payload, headers)

    def release_turn(self, turn_id, headers):
        return self._request("POST", f"/vendor-office/turns/{turn_id}/release",
                             {}, headers)

    def fail_qa(self, turn_id, payload, headers):
        return self._request("POST", f"/vendor-office/turns/{turn_id}/fail-qa",
                             payload, headers)

    # ------------------------------------------------------------------
    # Escalations
    # ------------------------------------------------------------------
    def create_escalation(self, request_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/requests/{request_id}/escalations",
                             payload, headers)

    def list_escalations(self, headers, params=None):
        return self._request("GET", "/vendor-office/escalations", headers=headers,
                             params=params)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/vendor-office/escalations/{escalation_id}",
                             headers=headers)

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request("POST",
                             f"/vendor-office/escalations/{escalation_id}/acknowledge",
                             {}, headers)

    def resolve_escalation(self, escalation_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/escalations/{escalation_id}/resolve",
                             payload, headers)

    # ------------------------------------------------------------------
    # OR access passes
    # ------------------------------------------------------------------
    def create_access_pass(self, payload, headers):
        return self._request("POST", "/vendor-office/access-passes", payload,
                             headers)

    def list_access_passes(self, headers, params=None):
        return self._request("GET", "/vendor-office/access-passes", headers=headers,
                             params=params)

    def get_access_pass(self, pass_id, headers):
        return self._request("GET", f"/vendor-office/access-passes/{pass_id}",
                             headers=headers)

    def decide_access_pass(self, pass_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/access-passes/{pass_id}/decide",
                             payload, headers)

    def admit_access_pass(self, pass_id, headers):
        return self._request("POST",
                             f"/vendor-office/access-passes/{pass_id}/admit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Pickups
    # ------------------------------------------------------------------
    def create_pickup(self, request_id, payload, headers):
        return self._request("POST", f"/vendor-office/requests/{request_id}/pickups",
                             payload, headers)

    def list_pickups(self, headers, params=None):
        return self._request("GET", "/vendor-office/pickups", headers=headers,
                             params=params)

    def get_pickup(self, pickup_id, headers):
        return self._request("GET", f"/vendor-office/pickups/{pickup_id}",
                             headers=headers)

    def reconcile_pickup(self, pickup_id, headers):
        return self._request("POST",
                             f"/vendor-office/pickups/{pickup_id}/reconcile",
                             {}, headers)

    def dispute_pickup(self, pickup_id, payload, headers):
        return self._request("POST",
                             f"/vendor-office/pickups/{pickup_id}/dispute",
                             payload, headers)

    # ------------------------------------------------------------------
    # Damage / loss claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/vendor-office/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/vendor-office/claims", headers=headers,
                             params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/vendor-office/claims/{claim_id}",
                             headers=headers)

    def apportion_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/vendor-office/claims/{claim_id}/apportion",
                             payload, headers)

    def dispute_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/vendor-office/claims/{claim_id}/dispute",
                             payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/vendor-office/claims/{claim_id}/settle",
                             {}, headers)

    # ------------------------------------------------------------------
    # Penalty assessments
    # ------------------------------------------------------------------
    def list_penalties(self, headers, params=None):
        return self._request("GET", "/vendor-office/penalties", headers=headers,
                             params=params)

    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/vendor-office/penalties/{penalty_id}",
                             headers=headers)

    def assess_penalty(self, penalty_id, headers):
        return self._request("POST",
                             f"/vendor-office/penalties/{penalty_id}/assess",
                             {}, headers)

    def waive_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/vendor-office/penalties/{penalty_id}/waive",
                             payload, headers)

    def settle_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/vendor-office/penalties/{penalty_id}/settle",
                             payload, headers)


api_client = ApiClient()
