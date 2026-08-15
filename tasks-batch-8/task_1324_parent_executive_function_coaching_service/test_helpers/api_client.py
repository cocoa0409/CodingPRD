"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock & ops sweep ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_daily_sweep(self, headers):
        return self._request("POST", "/api/admin/run-daily-sweep", {}, headers)

    # --- Family ---
    def create_family(self, payload, headers):
        return self._request("POST", "/api/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/api/families", headers=headers, params=params)

    def transition_family(self, family_id, to_state, headers):
        return self._request(
            "POST", f"/api/families/{family_id}/transition", {"to_state": to_state}, headers
        )

    def record_payment(self, family_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/api/families/{family_id}/payments",
            {"amount_cents": amount_cents},
            headers,
        )

    # --- Client ---
    def create_client(self, family_id, payload, headers):
        return self._request("POST", f"/api/families/{family_id}/clients", payload, headers)

    def list_clients(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}/clients", headers=headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}", headers=headers)

    def transition_client(self, client_id, to_state, headers):
        return self._request(
            "POST", f"/api/clients/{client_id}/transition", {"to_state": to_state}, headers
        )

    # --- Coach ---
    def create_coach(self, payload, headers):
        return self._request("POST", "/api/coaches", payload, headers)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}", headers=headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/api/coaches", headers=headers, params=params)

    def transition_coach(self, coach_id, to_state, headers):
        return self._request(
            "POST", f"/api/coaches/{coach_id}/transition", {"to_state": to_state}, headers
        )

    def list_coach_plans(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}/plans", headers=headers)

    def list_coach_sessions(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}/sessions", headers=headers)

    def list_coach_notes(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}/notes", headers=headers)

    def list_coach_workshops(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}/workshops", headers=headers)

    # --- IntakeAssessment ---
    def create_intake(self, client_id, payload, headers):
        return self._request("POST", f"/api/clients/{client_id}/intakes", payload, headers)

    def list_intakes(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}/intakes", headers=headers)

    def get_intake(self, intake_id, headers):
        return self._request("GET", f"/api/intakes/{intake_id}", headers=headers)

    def transition_intake(self, intake_id, to_state, headers, review_notes=None):
        payload = {"to_state": to_state}
        if review_notes is not None:
            payload["review_notes"] = review_notes
        return self._request(
            "POST", f"/api/intakes/{intake_id}/transition", payload, headers
        )

    def list_intake_plans(self, intake_id, headers):
        return self._request("GET", f"/api/intakes/{intake_id}/plans", headers=headers)

    # --- CoachingPlan ---
    def create_plan(self, client_id, payload, headers):
        return self._request("POST", f"/api/clients/{client_id}/plans", payload, headers)

    def list_plans(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}/plans", headers=headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}", headers=headers)

    def transition_plan(self, plan_id, to_state, headers):
        return self._request(
            "POST", f"/api/plans/{plan_id}/transition", {"to_state": to_state}, headers
        )

    # --- Goal ---
    def create_goal(self, plan_id, payload, headers):
        return self._request("POST", f"/api/plans/{plan_id}/goals", payload, headers)

    def list_goals(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}/goals", headers=headers)

    def transition_goal(self, goal_id, to_state, headers):
        return self._request(
            "POST", f"/api/goals/{goal_id}/transition", {"to_state": to_state}, headers
        )

    # --- Package ---
    def purchase_package(self, family_id, payload, headers):
        return self._request(
            "POST", f"/api/families/{family_id}/packages", payload, headers
        )

    def list_packages(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}/packages", headers=headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/api/packages/{package_id}", headers=headers)

    def refund_package(self, package_id, headers):
        return self._request("POST", f"/api/packages/{package_id}/refund", {}, headers)

    def list_package_sessions(self, package_id, headers):
        return self._request(
            "GET", f"/api/packages/{package_id}/sessions", headers=headers
        )

    # --- Session ---
    def create_session(self, plan_id, payload, headers):
        return self._request("POST", f"/api/plans/{plan_id}/sessions", payload, headers)

    def list_plan_sessions(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}/sessions", headers=headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/sessions/{session_id}", headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/cancel", {}, headers)

    def mark_no_show(self, session_id, headers):
        return self._request("POST", f"/api/sessions/{session_id}/mark-no-show", {}, headers)

    # --- CheckIn ---
    def create_checkin(self, plan_id, payload, headers):
        return self._request("POST", f"/api/plans/{plan_id}/checkins", payload, headers)

    def list_checkins(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}/checkins", headers=headers)

    def submit_checkin(self, checkin_id, headers, outcome_note=None):
        payload = {}
        if outcome_note is not None:
            payload["outcome_note"] = outcome_note
        return self._request(
            "POST", f"/api/checkins/{checkin_id}/submit", payload, headers
        )

    def acknowledge_checkin(self, checkin_id, headers):
        return self._request(
            "POST", f"/api/checkins/{checkin_id}/acknowledge", {}, headers
        )

    # --- ProgressSnapshot ---
    def create_progress_snapshot(self, client_id, headers):
        return self._request(
            "POST", f"/api/clients/{client_id}/progress-snapshots", {}, headers
        )

    def list_progress_snapshots(self, client_id, headers):
        return self._request(
            "GET", f"/api/clients/{client_id}/progress-snapshots", headers=headers
        )

    # --- CoordinationContact / ConsentGrant / CoordinationNote ---
    def create_contact(self, family_id, payload, headers):
        return self._request("POST", f"/api/families/{family_id}/contacts", payload, headers)

    def list_contacts(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}/contacts", headers=headers)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/api/contacts/{contact_id}", headers=headers)

    def transition_contact(self, contact_id, to_state, headers):
        return self._request(
            "POST", f"/api/contacts/{contact_id}/transition", {"to_state": to_state}, headers
        )

    def create_consent(self, family_id, payload, headers):
        return self._request("POST", f"/api/families/{family_id}/consents", payload, headers)

    def list_consents(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}/consents", headers=headers)

    def list_contact_consents(self, contact_id, headers):
        return self._request("GET", f"/api/contacts/{contact_id}/consents", headers=headers)

    def transition_consent(self, consent_id, to_state, headers):
        return self._request(
            "POST", f"/api/consents/{consent_id}/transition", {"to_state": to_state}, headers
        )

    def create_note(self, client_id, payload, headers):
        return self._request("POST", f"/api/clients/{client_id}/notes", payload, headers)

    def list_client_notes(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}/notes", headers=headers)

    def transition_note(self, note_id, to_state, headers):
        return self._request(
            "POST", f"/api/notes/{note_id}/transition", {"to_state": to_state}, headers
        )

    def share_note(self, note_id, contact_id, headers):
        return self._request(
            "POST", f"/api/notes/{note_id}/share", {"contact_id": contact_id}, headers
        )

    def list_shared_notes(self, contact_id, headers):
        return self._request(
            "GET", f"/api/contacts/{contact_id}/shared-notes", headers=headers
        )

    # --- Workshop / WorkshopEnrollment ---
    def create_workshop(self, payload, headers):
        return self._request("POST", "/api/workshops", payload, headers)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"/api/workshops/{workshop_id}", headers=headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", "/api/workshops", headers=headers, params=params)

    def transition_workshop(self, workshop_id, to_state, headers):
        return self._request(
            "POST",
            f"/api/workshops/{workshop_id}/transition",
            {"to_state": to_state},
            headers,
        )

    def create_enrollment(self, workshop_id, payload, headers):
        return self._request(
            "POST", f"/api/workshops/{workshop_id}/enrollments", payload, headers
        )

    def list_enrollments(self, workshop_id, headers):
        return self._request(
            "GET", f"/api/workshops/{workshop_id}/enrollments", headers=headers
        )

    def list_client_enrollments(self, client_id, headers):
        return self._request(
            "GET", f"/api/clients/{client_id}/enrollments", headers=headers
        )

    def drop_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/drop", {}, headers)

    # --- SupervisionRecord ---
    def create_supervision_record(self, coach_id, payload, headers):
        return self._request(
            "POST", f"/api/coaches/{coach_id}/supervision-records", payload, headers
        )

    def list_supervision_records(self, coach_id, headers):
        return self._request(
            "GET", f"/api/coaches/{coach_id}/supervision-records", headers=headers
        )

    def transition_supervision_record(self, record_id, to_state, headers):
        return self._request(
            "POST",
            f"/api/supervision-records/{record_id}/transition",
            {"to_state": to_state},
            headers,
        )


api_client = ApiClient()
