"""API client: one method per endpoint defined in the Racquet Club PRD (§4).

All paths are mounted under the /racquet prefix. The base _request() method is
inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/racquet/_clock/set_current_utc", payload, headers)

    # ---- Court ----
    def create_court(self, payload, headers):
        return self._request("POST", "/racquet/courts", payload, headers)

    def get_court(self, court_id, headers):
        return self._request("GET", f"/racquet/courts/{court_id}", headers=headers)

    def list_courts(self, headers, params=None):
        return self._request("GET", "/racquet/courts", headers=headers, params=params)

    def court_maintenance(self, court_id, headers):
        return self._request("POST", f"/racquet/courts/{court_id}/maintenance", {}, headers)

    def court_reopen(self, court_id, headers):
        return self._request("POST", f"/racquet/courts/{court_id}/reopen", {}, headers)

    def court_retire(self, court_id, headers):
        return self._request("POST", f"/racquet/courts/{court_id}/retire", {}, headers)

    # ---- MembershipPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/racquet/membership-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/racquet/membership-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/racquet/membership-plans", headers=headers, params=params)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/racquet/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/racquet/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/racquet/members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/racquet/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/racquet/members/{member_id}/reinstate", {}, headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/racquet/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/racquet/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/racquet/subscriptions", headers=headers, params=params)

    def freeze_subscription(self, subscription_id, headers):
        return self._request("POST", f"/racquet/subscriptions/{subscription_id}/freeze", {}, headers)

    def unfreeze_subscription(self, subscription_id, headers):
        return self._request("POST", f"/racquet/subscriptions/{subscription_id}/unfreeze", {}, headers)

    def change_plan(self, subscription_id, payload, headers):
        return self._request("POST", f"/racquet/subscriptions/{subscription_id}/change-plan", payload, headers)

    def renew_subscription(self, subscription_id, headers):
        return self._request("POST", f"/racquet/subscriptions/{subscription_id}/renew", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/racquet/subscriptions/{subscription_id}/cancel", {}, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/racquet/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/racquet/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/racquet/reservations", headers=headers, params=params)

    def checkin_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/racquet/reservations/{reservation_id}/check-in", payload, headers)

    def complete_reservation(self, reservation_id, headers):
        return self._request("POST", f"/racquet/reservations/{reservation_id}/complete", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/racquet/reservations/{reservation_id}/cancel", {}, headers)

    def reschedule_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/racquet/reservations/{reservation_id}/reschedule", payload, headers)

    def mark_no_show(self, reservation_id, headers):
        return self._request("POST", f"/racquet/reservations/{reservation_id}/mark-no-show", {}, headers)

    # ---- Pro ----
    def create_pro(self, payload, headers):
        return self._request("POST", "/racquet/pros", payload, headers)

    def get_pro(self, pro_id, headers):
        return self._request("GET", f"/racquet/pros/{pro_id}", headers=headers)

    def list_pros(self, headers, params=None):
        return self._request("GET", "/racquet/pros", headers=headers, params=params)

    # ---- Lesson ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/racquet/lessons", payload, headers)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/racquet/lessons/{lesson_id}", headers=headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/racquet/lessons", headers=headers, params=params)

    def confirm_lesson(self, lesson_id, headers):
        return self._request("POST", f"/racquet/lessons/{lesson_id}/confirm", {}, headers)

    def complete_lesson(self, lesson_id, headers):
        return self._request("POST", f"/racquet/lessons/{lesson_id}/complete", {}, headers)

    def cancel_lesson(self, lesson_id, headers):
        return self._request("POST", f"/racquet/lessons/{lesson_id}/cancel", {}, headers)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/racquet/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/racquet/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/racquet/enrollments", headers=headers, params=params)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/racquet/enrollments/{enrollment_id}/cancel", {}, headers)

    # ---- Competition ----
    def create_competition(self, payload, headers):
        return self._request("POST", "/racquet/competitions", payload, headers)

    def get_competition(self, competition_id, headers):
        return self._request("GET", f"/racquet/competitions/{competition_id}", headers=headers)

    def list_competitions(self, headers, params=None):
        return self._request("GET", "/racquet/competitions", headers=headers, params=params)

    def start_competition(self, competition_id, headers):
        return self._request("POST", f"/racquet/competitions/{competition_id}/start", {}, headers)

    def report_competition(self, competition_id, payload, headers):
        return self._request("POST", f"/racquet/competitions/{competition_id}/report", payload, headers)

    def close_competition(self, competition_id, headers):
        return self._request("POST", f"/racquet/competitions/{competition_id}/close", {}, headers)

    # ---- Participant ----
    def create_participant(self, payload, headers):
        return self._request("POST", "/racquet/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/racquet/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/racquet/participants", headers=headers, params=params)

    # ---- StringingJob ----
    def create_stringing_job(self, payload, headers):
        return self._request("POST", "/racquet/stringing-jobs", payload, headers)

    def get_stringing_job(self, job_id, headers):
        return self._request("GET", f"/racquet/stringing-jobs/{job_id}", headers=headers)

    def list_stringing_jobs(self, headers, params=None):
        return self._request("GET", "/racquet/stringing-jobs", headers=headers, params=params)

    def advance_stringing_job(self, job_id, headers):
        return self._request("POST", f"/racquet/stringing-jobs/{job_id}/advance", {}, headers)

    def cancel_stringing_job(self, job_id, headers):
        return self._request("POST", f"/racquet/stringing-jobs/{job_id}/cancel", {}, headers)


api_client = ApiClient()
