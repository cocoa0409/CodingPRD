"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/casting/_clock/set_current_utc", payload, headers)

    # --- productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/casting/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/casting/productions/{production_id}", headers=headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/casting/productions", headers=headers, params=params)

    def open_casting(self, production_id, headers):
        return self._request("POST", f"/casting/productions/{production_id}/open-casting", headers=headers)

    def lock_production(self, production_id, headers):
        return self._request("POST", f"/casting/productions/{production_id}/lock", headers=headers)

    def complete_production(self, production_id, headers):
        return self._request("POST", f"/casting/productions/{production_id}/complete", headers=headers)

    # --- roles ---
    def create_role(self, production_id, payload, headers):
        return self._request("POST", f"/casting/productions/{production_id}/roles", payload, headers)

    def get_role(self, role_id, headers):
        return self._request("GET", f"/casting/roles/{role_id}", headers=headers)

    def list_roles(self, production_id, headers, params=None):
        return self._request("GET", f"/casting/productions/{production_id}/roles", headers=headers, params=params)

    # --- breakdowns ---
    def create_breakdown(self, production_id, payload, headers):
        return self._request("POST", f"/casting/productions/{production_id}/breakdowns", payload, headers)

    def get_breakdown(self, breakdown_id, headers):
        return self._request("GET", f"/casting/breakdowns/{breakdown_id}", headers=headers)

    def list_production_breakdowns(self, production_id, headers, params=None):
        return self._request("GET", f"/casting/productions/{production_id}/breakdowns", headers=headers, params=params)

    def list_breakdowns(self, headers, params=None):
        return self._request("GET", "/casting/breakdowns", headers=headers, params=params)

    def release_breakdown(self, breakdown_id, payload, headers):
        return self._request("POST", f"/casting/breakdowns/{breakdown_id}/release", payload, headers)

    def widen_breakdown(self, breakdown_id, headers):
        return self._request("POST", f"/casting/breakdowns/{breakdown_id}/widen", headers=headers)

    def close_breakdown(self, breakdown_id, headers):
        return self._request("POST", f"/casting/breakdowns/{breakdown_id}/close", headers=headers)

    def cancel_breakdown(self, breakdown_id, headers):
        return self._request("POST", f"/casting/breakdowns/{breakdown_id}/cancel", headers=headers)

    # --- agents / guardians / talents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/casting/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/casting/agents/{agent_id}", headers=headers)

    def create_guardian(self, payload, headers):
        return self._request("POST", "/casting/guardians", payload, headers)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/casting/guardians/{guardian_id}", headers=headers)

    def create_talent(self, payload, headers):
        return self._request("POST", "/casting/talents", payload, headers)

    def get_talent(self, talent_id, headers):
        return self._request("GET", f"/casting/talents/{talent_id}", headers=headers)

    def list_talents(self, headers, params=None):
        return self._request("GET", "/casting/talents", headers=headers, params=params)

    # --- submissions ---
    def create_submission(self, breakdown_id, payload, headers):
        return self._request("POST", f"/casting/breakdowns/{breakdown_id}/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/casting/submissions/{submission_id}", headers=headers)

    def list_breakdown_submissions(self, breakdown_id, headers, params=None):
        return self._request("GET", f"/casting/breakdowns/{breakdown_id}/submissions", headers=headers, params=params)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/casting/submissions", headers=headers, params=params)

    def start_review(self, submission_id, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/start-review", headers=headers)

    def shortlist_submission(self, submission_id, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/shortlist", headers=headers)

    def reject_submission(self, submission_id, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/reject", headers=headers)

    def withdraw_submission(self, submission_id, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/withdraw", headers=headers)

    # --- self tapes ---
    def create_self_tape(self, submission_id, payload, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/self-tapes", payload, headers)

    def get_self_tape(self, tape_id, headers):
        return self._request("GET", f"/casting/self-tapes/{tape_id}", headers=headers)

    def list_self_tapes(self, submission_id, headers, params=None):
        return self._request("GET", f"/casting/submissions/{submission_id}/self-tapes", headers=headers, params=params)

    def accept_self_tape(self, tape_id, headers):
        return self._request("POST", f"/casting/self-tapes/{tape_id}/accept", headers=headers)

    def reject_self_tape(self, tape_id, headers):
        return self._request("POST", f"/casting/self-tapes/{tape_id}/reject", headers=headers)

    # --- sessions ---
    def create_session(self, breakdown_id, payload, headers):
        return self._request("POST", f"/casting/breakdowns/{breakdown_id}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/casting/sessions/{session_id}", headers=headers)

    def list_sessions(self, breakdown_id, headers, params=None):
        return self._request("GET", f"/casting/breakdowns/{breakdown_id}/sessions", headers=headers, params=params)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/casting/sessions/{session_id}/complete", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/casting/sessions/{session_id}/cancel", headers=headers)

    # --- appointments ---
    def create_appointment(self, session_id, payload, headers):
        return self._request("POST", f"/casting/sessions/{session_id}/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/casting/appointments/{appointment_id}", headers=headers)

    def list_session_appointments(self, session_id, headers, params=None):
        return self._request("GET", f"/casting/sessions/{session_id}/appointments", headers=headers, params=params)

    def list_submission_appointments(self, submission_id, headers, params=None):
        return self._request("GET", f"/casting/submissions/{submission_id}/appointments", headers=headers, params=params)

    def confirm_appointment(self, appointment_id, headers):
        return self._request("POST", f"/casting/appointments/{appointment_id}/confirm", headers=headers)

    def decline_appointment(self, appointment_id, headers):
        return self._request("POST", f"/casting/appointments/{appointment_id}/decline", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/casting/appointments/{appointment_id}/cancel", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/casting/appointments/{appointment_id}/complete", headers=headers)

    # --- availability holds ---
    def create_hold(self, submission_id, payload, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/holds", payload, headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/casting/holds", headers=headers, params=params)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/casting/holds/{hold_id}", headers=headers)

    def list_submission_holds(self, submission_id, headers, params=None):
        return self._request("GET", f"/casting/submissions/{submission_id}/holds", headers=headers, params=params)

    def confirm_hold(self, hold_id, headers):
        return self._request("POST", f"/casting/holds/{hold_id}/confirm", headers=headers)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/casting/holds/{hold_id}/release", headers=headers)

    # --- offers ---
    def create_offer(self, submission_id, payload, headers):
        return self._request("POST", f"/casting/submissions/{submission_id}/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/casting/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/casting/offers/{offer_id}", headers=headers)

    def list_submission_offers(self, submission_id, headers, params=None):
        return self._request("GET", f"/casting/submissions/{submission_id}/offers", headers=headers, params=params)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/casting/offers/{offer_id}/counter", payload, headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/casting/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/casting/offers/{offer_id}/decline", headers=headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/casting/offers/{offer_id}/withdraw", headers=headers)

    # --- deal memos ---
    def get_deal_memo(self, memo_id, headers):
        return self._request("GET", f"/casting/deal-memos/{memo_id}", headers=headers)

    def list_offer_deal_memos(self, offer_id, headers):
        return self._request("GET", f"/casting/offers/{offer_id}/deal-memos", headers=headers)

    def void_deal_memo(self, memo_id, headers):
        return self._request("POST", f"/casting/deal-memos/{memo_id}/void", headers=headers)

    # --- minor work permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/casting/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/casting/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/casting/permits/{permit_id}", headers=headers)

    def list_talent_permits(self, talent_id, headers, params=None):
        return self._request("GET", f"/casting/talents/{talent_id}/permits", headers=headers, params=params)

    def verify_permit(self, permit_id, headers):
        return self._request("POST", f"/casting/permits/{permit_id}/verify", headers=headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/casting/permits/{permit_id}/revoke", headers=headers)

    # --- bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/casting/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/casting/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/casting/bookings", headers=headers, params=params)

    def list_submission_bookings(self, submission_id, headers, params=None):
        return self._request("GET", f"/casting/submissions/{submission_id}/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/casting/bookings/{booking_id}/confirm", headers=headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/casting/bookings/{booking_id}/cancel", payload, headers)

    # --- Taft-Hartley reports ---
    def get_taft_hartley_report(self, report_id, headers):
        return self._request("GET", f"/casting/taft-hartley/{report_id}", headers=headers)

    def list_production_taft_hartley(self, production_id, headers, params=None):
        return self._request("GET", f"/casting/productions/{production_id}/taft-hartley", headers=headers, params=params)

    def list_taft_hartley(self, headers, params=None):
        return self._request("GET", "/casting/taft-hartley", headers=headers, params=params)

    def file_taft_hartley(self, report_id, headers):
        return self._request("POST", f"/casting/taft-hartley/{report_id}/file", headers=headers)


api_client = ApiClient()
