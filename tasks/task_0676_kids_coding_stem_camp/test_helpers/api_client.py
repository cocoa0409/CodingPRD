"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Center ───────────────────────────────────────────────────────
    def create_center(self, payload, headers):
        return self._request("POST", "/centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/centers/{center_id}", headers=headers)

    # ─── Program ──────────────────────────────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    # ─── BeltLevel ────────────────────────────────────────────────────
    def create_belt_level(self, payload, headers):
        return self._request("POST", "/belt-levels", payload, headers)

    def get_belt_level(self, belt_level_id, headers):
        return self._request("GET", f"/belt-levels/{belt_level_id}", headers=headers)

    def list_belt_levels(self, headers, params=None):
        return self._request("GET", "/belt-levels", headers=headers, params=params)

    # ─── Badge ────────────────────────────────────────────────────────
    def create_badge(self, payload, headers):
        return self._request("POST", "/badges", payload, headers)

    def get_badge(self, badge_id, headers):
        return self._request("GET", f"/badges/{badge_id}", headers=headers)

    def list_badges(self, headers, params=None):
        return self._request("GET", "/badges", headers=headers, params=params)

    def retire_badge(self, badge_id, headers):
        return self._request("POST", f"/badges/{badge_id}/retire", headers=headers)

    # ─── Guardian ─────────────────────────────────────────────────────
    def create_guardian(self, payload, headers):
        return self._request("POST", "/guardians", payload, headers)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/guardians/{guardian_id}", headers=headers)

    def adjust_wallet(self, guardian_id, payload, headers):
        return self._request(
            "POST", f"/guardians/{guardian_id}/wallet/adjustments", payload, headers
        )

    # ─── Member ───────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member_progress(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/progress", headers=headers)

    def promote_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/promote", headers=headers)

    # ─── Membership ───────────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/activate", headers=headers)

    def pause_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/pause", headers=headers)

    def resume_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/resume", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", headers=headers)

    # ─── Session ──────────────────────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session_quote(self, session_id, payload, headers):
        # Read-only price preview; member_ids carried in the body.
        return self._request("GET", f"/sessions/{session_id}/quote", payload, headers)

    def open_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/open", headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", headers=headers)

    # ─── Enrollment ───────────────────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def check_in_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/check-in", headers=headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel", headers=headers)

    # ─── BadgeAward ───────────────────────────────────────────────────
    def create_badge_award(self, payload, headers):
        return self._request("POST", "/badge-awards", payload, headers)

    def get_badge_award(self, badge_award_id, headers):
        return self._request("GET", f"/badge-awards/{badge_award_id}", headers=headers)

    def list_badge_awards(self, headers, params=None):
        return self._request("GET", "/badge-awards", headers=headers, params=params)

    def revoke_badge_award(self, badge_award_id, headers):
        return self._request("POST", f"/badge-awards/{badge_award_id}/revoke", headers=headers)

    # ─── Showcase ─────────────────────────────────────────────────────
    def create_showcase(self, payload, headers):
        return self._request("POST", "/showcases", payload, headers)

    def get_showcase(self, showcase_id, headers):
        return self._request("GET", f"/showcases/{showcase_id}", headers=headers)

    def list_showcases(self, headers, params=None):
        return self._request("GET", "/showcases", headers=headers, params=params)

    def open_showcase(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/open", headers=headers)

    def close_showcase_entries(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/close-entries", headers=headers)

    def post_showcase_results(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/post-results", headers=headers)

    def cancel_showcase(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/cancel", headers=headers)

    # ─── ShowcaseEntry ────────────────────────────────────────────────
    def create_showcase_entry(self, payload, headers):
        return self._request("POST", "/showcase-entries", payload, headers)

    def get_showcase_entry(self, entry_id, headers):
        return self._request("GET", f"/showcase-entries/{entry_id}", headers=headers)

    def list_showcase_entries(self, headers, params=None):
        return self._request("GET", "/showcase-entries", headers=headers, params=params)

    def accept_showcase_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/showcase-entries/{entry_id}/accept", payload, headers)

    def reject_showcase_entry(self, entry_id, headers):
        return self._request("POST", f"/showcase-entries/{entry_id}/reject", headers=headers)

    def score_showcase_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/showcase-entries/{entry_id}/score", payload, headers)

    def withdraw_showcase_entry(self, entry_id, headers):
        return self._request("POST", f"/showcase-entries/{entry_id}/withdraw", headers=headers)

    # ─── Test-driving endpoints ───────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_cycle(self, payload, headers):
        return self._request("POST", "/_billing/advance-cycle", payload, headers)


api_client = ApiClient()
