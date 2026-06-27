"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- MembershipPlan ----------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"/membership-plans/{plan_id}/archive", {}, headers)

    def list_plan_memberships(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/membership-plans/{plan_id}/memberships", headers=headers, params=params
        )

    # ---------------- Member ----------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def exit_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/exit", {}, headers)

    # ---------------- Screening ----------------
    def create_screening(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/screenings", payload, headers)

    def list_screenings(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/screenings", headers=headers, params=params
        )

    def decide_screening(self, member_id, screening_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/screenings/{screening_id}/decide", payload, headers
        )

    # ---------------- Preference ----------------
    def put_preferences(self, member_id, payload, headers):
        return self._request("PUT", f"/members/{member_id}/preferences", payload, headers)

    def get_preferences(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/preferences", headers=headers)

    # ---------------- Membership ----------------
    def activate_membership(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/memberships", payload, headers)

    def list_member_memberships(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/memberships", headers=headers, params=params
        )

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", {}, headers)

    # ---------------- Freeze ----------------
    def create_freeze(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/freezes", payload, headers
        )

    def list_freezes(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"/memberships/{membership_id}/freezes", headers=headers, params=params
        )

    def resume_freeze(self, membership_id, freeze_id, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/freezes/{freeze_id}/resume", {}, headers
        )

    def cancel_freeze(self, membership_id, freeze_id, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/freezes/{freeze_id}/cancel", {}, headers
        )

    # ---------------- Introduction ----------------
    def create_introduction(self, payload, headers):
        return self._request("POST", "/introductions", payload, headers)

    def list_introductions(self, headers, params=None):
        return self._request("GET", "/introductions", headers=headers, params=params)

    def get_introduction(self, introduction_id, headers):
        return self._request("GET", f"/introductions/{introduction_id}", headers=headers)

    def respond_introduction(self, introduction_id, payload, headers):
        return self._request(
            "POST", f"/introductions/{introduction_id}/respond", payload, headers
        )

    def close_introduction(self, introduction_id, headers):
        return self._request(
            "POST", f"/introductions/{introduction_id}/close", {}, headers
        )

    # ---------------- Feedback ----------------
    def create_feedback(self, introduction_id, payload, headers):
        return self._request(
            "POST", f"/introductions/{introduction_id}/feedback", payload, headers
        )

    def list_feedback(self, introduction_id, headers, params=None):
        return self._request(
            "GET", f"/introductions/{introduction_id}/feedback", headers=headers, params=params
        )

    # ---------------- DateEvent ----------------
    def create_date_event(self, introduction_id, payload, headers):
        return self._request(
            "POST", f"/introductions/{introduction_id}/date-events", payload, headers
        )

    def list_date_events(self, introduction_id, headers, params=None):
        return self._request(
            "GET", f"/introductions/{introduction_id}/date-events", headers=headers, params=params
        )

    def get_date_event(self, date_event_id, headers):
        return self._request("GET", f"/date-events/{date_event_id}", headers=headers)

    def date_event_outcome(self, date_event_id, payload, headers):
        return self._request(
            "POST", f"/date-events/{date_event_id}/outcome", payload, headers
        )

    def cancel_date_event(self, date_event_id, headers):
        return self._request("POST", f"/date-events/{date_event_id}/cancel", {}, headers)

    # ---------------- CoachingSession ----------------
    def create_coaching_session(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/coaching-sessions", payload, headers
        )

    def list_coaching_sessions(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/coaching-sessions", headers=headers, params=params
        )

    def get_coaching_session(self, session_id, headers):
        return self._request("GET", f"/coaching-sessions/{session_id}", headers=headers)

    def coaching_session_outcome(self, session_id, payload, headers):
        return self._request(
            "POST", f"/coaching-sessions/{session_id}/outcome", payload, headers
        )

    def cancel_coaching_session(self, session_id, headers):
        return self._request(
            "POST", f"/coaching-sessions/{session_id}/cancel", {}, headers
        )

    # ---------------- BackgroundCheck ----------------
    def order_background_check(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/background-checks", payload, headers
        )

    def list_background_checks(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/background-checks", headers=headers, params=params
        )

    def complete_background_check(self, member_id, check_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/background-checks/{check_id}/complete", payload, headers
        )

    def cancel_background_check(self, member_id, check_id, headers):
        return self._request(
            "POST", f"/members/{member_id}/background-checks/{check_id}/cancel", {}, headers
        )


api_client = ApiClient()
