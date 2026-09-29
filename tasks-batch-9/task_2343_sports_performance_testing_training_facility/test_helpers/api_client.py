"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ──────────────────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Athletes ───────────────────────────────────────────────────────────
    def create_athlete(self, payload, headers):
        return self._request("POST", "/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}", headers=headers)

    def list_athletes(self, headers, params=None):
        return self._request("GET", "/athletes", headers=headers, params=params)

    def suspend_athlete(self, athlete_id, payload, headers):
        return self._request("POST", f"/athletes/{athlete_id}/suspend", payload, headers)

    def reinstate_athlete(self, athlete_id, headers, payload=None):
        return self._request("POST", f"/athletes/{athlete_id}/reinstate", payload or {}, headers)

    def medical_hold_athlete(self, athlete_id, payload, headers):
        return self._request("POST", f"/athletes/{athlete_id}/medical-hold", payload, headers)

    def get_progress_report(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}/progress-report", headers=headers)

    # ─── Injury records ─────────────────────────────────────────────────────
    def create_injury_record(self, payload, headers):
        return self._request("POST", "/injury-records", payload, headers)

    def get_injury_record(self, injury_record_id, headers):
        return self._request("GET", f"/injury-records/{injury_record_id}", headers=headers)

    def list_injury_records(self, headers, params=None):
        return self._request("GET", "/injury-records", headers=headers, params=params)

    def resolve_injury_record(self, injury_record_id, headers, payload=None):
        return self._request("POST", f"/injury-records/{injury_record_id}/resolve",
                             payload or {}, headers)

    # ─── Test sessions ──────────────────────────────────────────────────────
    def create_test_session(self, payload, headers):
        return self._request("POST", "/test-sessions", payload, headers)

    def submit_test_results(self, test_session_id, payload, headers):
        return self._request("POST", f"/test-sessions/{test_session_id}/results",
                             payload, headers)

    def finalize_test_session(self, test_session_id, headers, payload=None):
        return self._request("POST", f"/test-sessions/{test_session_id}/finalize",
                             payload or {}, headers)

    def get_test_session(self, test_session_id, headers):
        return self._request("GET", f"/test-sessions/{test_session_id}", headers=headers)

    def list_test_sessions(self, headers, params=None):
        return self._request("GET", "/test-sessions", headers=headers, params=params)

    # ─── Training programs and blocks ───────────────────────────────────────
    def create_training_program(self, payload, headers):
        return self._request("POST", "/training-programs", payload, headers)

    def get_training_program(self, training_program_id, headers):
        return self._request("GET", f"/training-programs/{training_program_id}", headers=headers)

    def list_training_programs(self, headers, params=None):
        return self._request("GET", "/training-programs", headers=headers, params=params)

    def create_program_block(self, training_program_id, payload, headers):
        return self._request("POST", f"/training-programs/{training_program_id}/blocks",
                             payload, headers)

    def activate_training_program(self, training_program_id, headers, payload=None):
        return self._request("POST", f"/training-programs/{training_program_id}/activate",
                             payload or {}, headers)

    def get_program_block(self, program_block_id, headers):
        return self._request("GET", f"/program-blocks/{program_block_id}", headers=headers)

    def list_program_blocks(self, headers, params=None):
        return self._request("GET", "/program-blocks", headers=headers, params=params)

    # ─── Group sessions ─────────────────────────────────────────────────────
    def create_group_session(self, payload, headers):
        return self._request("POST", "/group-sessions", payload, headers)

    def get_group_session(self, group_session_id, headers):
        return self._request("GET", f"/group-sessions/{group_session_id}", headers=headers)

    def list_group_sessions(self, headers, params=None):
        return self._request("GET", "/group-sessions", headers=headers, params=params)

    def assign_coach(self, group_session_id, payload, headers):
        return self._request("POST", f"/group-sessions/{group_session_id}/coaches",
                             payload, headers)

    def lock_roster(self, group_session_id, headers, payload=None):
        return self._request("POST", f"/group-sessions/{group_session_id}/lock-roster",
                             payload or {}, headers)

    def start_group_session(self, group_session_id, headers, payload=None):
        return self._request("POST", f"/group-sessions/{group_session_id}/start",
                             payload or {}, headers)

    def complete_group_session(self, group_session_id, headers, payload=None):
        return self._request("POST", f"/group-sessions/{group_session_id}/complete",
                             payload or {}, headers)

    def void_completion(self, group_session_id, payload, headers):
        return self._request("POST", f"/group-sessions/{group_session_id}/void-completion",
                             payload, headers)

    def cancel_group_session(self, group_session_id, payload, headers):
        return self._request("POST", f"/group-sessions/{group_session_id}/cancel",
                             payload, headers)

    # ─── Enrollments ────────────────────────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def cancel_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel",
                             payload or {}, headers)

    def attend_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/attend",
                             payload or {}, headers)

    def no_show_enrollment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/no-show",
                             payload or {}, headers)

    # ─── Staff members ──────────────────────────────────────────────────────
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_member_id, headers):
        return self._request("GET", f"/staff-members/{staff_member_id}", headers=headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def credential_review(self, staff_member_id, headers, payload=None):
        return self._request("POST", f"/staff-members/{staff_member_id}/credential-review",
                             payload or {}, headers)

    # ─── Certifications ─────────────────────────────────────────────────────
    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def log_ceu_credits(self, certification_id, payload, headers):
        return self._request("POST", f"/certifications/{certification_id}/ceu-credits",
                             payload, headers)

    def renew_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/certifications/{certification_id}/renew",
                             payload, headers)

    # ─── Membership packages ────────────────────────────────────────────────
    def create_membership_package(self, payload, headers):
        return self._request("POST", "/membership-packages", payload, headers)

    def get_membership_package(self, membership_package_id, headers):
        return self._request("GET", f"/membership-packages/{membership_package_id}",
                             headers=headers)

    def list_membership_packages(self, headers, params=None):
        return self._request("GET", "/membership-packages", headers=headers, params=params)

    def freeze_membership_package(self, membership_package_id, headers, payload=None):
        return self._request("POST", f"/membership-packages/{membership_package_id}/freeze",
                             payload or {}, headers)

    def unfreeze_membership_package(self, membership_package_id, headers, payload=None):
        return self._request("POST", f"/membership-packages/{membership_package_id}/unfreeze",
                             payload or {}, headers)

    # ─── Team contracts ─────────────────────────────────────────────────────
    def create_team_contract(self, payload, headers):
        return self._request("POST", "/team-contracts", payload, headers)

    def get_team_contract(self, team_contract_id, headers):
        return self._request("GET", f"/team-contracts/{team_contract_id}", headers=headers)

    def list_team_contracts(self, headers, params=None):
        return self._request("GET", "/team-contracts", headers=headers, params=params)

    def activate_team_contract(self, team_contract_id, headers, payload=None):
        return self._request("POST", f"/team-contracts/{team_contract_id}/activate",
                             payload or {}, headers)

    def link_contract_athlete(self, team_contract_id, payload, headers):
        return self._request("POST", f"/team-contracts/{team_contract_id}/athletes",
                             payload, headers)

    # ─── Return-to-sport plans ──────────────────────────────────────────────
    def create_rts_plan(self, payload, headers):
        return self._request("POST", "/rts-plans", payload, headers)

    def get_rts_plan(self, rts_plan_id, headers):
        return self._request("GET", f"/rts-plans/{rts_plan_id}", headers=headers)

    def list_rts_plans(self, headers, params=None):
        return self._request("GET", "/rts-plans", headers=headers, params=params)

    def open_stage_test(self, rts_plan_id, headers, payload=None):
        return self._request("POST", f"/rts-plans/{rts_plan_id}/stage-test",
                             payload or {}, headers)

    def record_stage_decision(self, rts_plan_id, payload, headers):
        return self._request("POST", f"/rts-plans/{rts_plan_id}/stage-decision",
                             payload, headers)

    def abort_rts_plan(self, rts_plan_id, payload, headers):
        return self._request("POST", f"/rts-plans/{rts_plan_id}/abort", payload, headers)

    # ─── Clearance documents ────────────────────────────────────────────────
    def create_clearance_document(self, payload, headers):
        return self._request("POST", "/clearance-documents", payload, headers)

    def get_clearance_document(self, clearance_document_id, headers):
        return self._request("GET", f"/clearance-documents/{clearance_document_id}",
                             headers=headers)

    def list_clearance_documents(self, headers, params=None):
        return self._request("GET", "/clearance-documents", headers=headers, params=params)

    def sign_clearance_document(self, clearance_document_id, payload, headers):
        return self._request("POST", f"/clearance-documents/{clearance_document_id}/sign",
                             payload, headers)

    def revoke_clearance_document(self, clearance_document_id, payload, headers):
        return self._request("POST", f"/clearance-documents/{clearance_document_id}/revoke",
                             payload, headers)


api_client = ApiClient()
