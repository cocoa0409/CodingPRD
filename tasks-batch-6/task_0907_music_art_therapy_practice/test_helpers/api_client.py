"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Therapist ----
    def create_therapist(self, payload, headers):
        return self._request("POST", "/therapists", payload, headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def discharge_client(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/discharge", payload, headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def assess_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/assess", payload, headers)

    # ---- TreatmentPlan ----
    def create_treatment_plan(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def activate_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/treatment-plans/{plan_id}/activate", payload or {}, headers)

    def revise_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/revise", payload, headers)

    # ---- Goal ----
    def create_goal(self, plan_id, payload, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/goals", payload, headers)

    def list_goals(self, plan_id, headers, params=None):
        return self._request("GET", f"/treatment-plans/{plan_id}/goals", headers=headers, params=params)

    # ---- Room ----
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    # ---- MaterialItem ----
    def create_material(self, payload, headers):
        return self._request("POST", "/materials", payload, headers)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/materials/{material_id}", headers=headers)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    # ---- Session ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", payload, headers)

    def cancel_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", payload, headers)

    def enroll_client(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/enrollments", payload, headers)

    # ---- Enrollment ----
    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    # ---- ProgressNote ----
    def create_progress_note(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/progress-notes", payload, headers)

    def list_progress_notes(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/progress-notes", headers=headers, params=params)

    def sign_progress_note(self, note_id, headers):
        return self._request("POST", f"/progress-notes/{note_id}/sign", {}, headers)

    # ---- Superbill ----
    def create_superbill(self, payload, headers):
        return self._request("POST", "/superbills", payload, headers)

    def list_superbills(self, headers, params=None):
        return self._request("GET", "/superbills", headers=headers, params=params)

    def get_superbill(self, superbill_id, headers):
        return self._request("GET", f"/superbills/{superbill_id}", headers=headers)

    def adjudicate_superbill(self, superbill_id, payload, headers):
        return self._request("POST", f"/superbills/{superbill_id}/adjudicate", payload, headers)

    def void_superbill(self, superbill_id, headers):
        return self._request("POST", f"/superbills/{superbill_id}/void", {}, headers)


api_client = ApiClient()
