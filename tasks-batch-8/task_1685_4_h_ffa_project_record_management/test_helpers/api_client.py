"""API client: one method per endpoint defined in the PRD (all under /api)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Clubs ---
    def create_club(self, payload, headers):
        return self._request("POST", "/api/clubs", payload, headers)

    def get_club(self, club_id, headers):
        return self._request("GET", f"/api/clubs/{club_id}", headers=headers)

    def list_clubs(self, headers, params=None):
        return self._request("GET", "/api/clubs", headers=headers, params=params)

    def list_club_members(self, club_id, headers, params=None):
        return self._request("GET", f"/api/clubs/{club_id}/members", headers=headers, params=params)

    def list_club_volunteers(self, club_id, headers, params=None):
        return self._request("GET", f"/api/clubs/{club_id}/volunteers", headers=headers, params=params)

    def list_club_meetings(self, club_id, headers, params=None):
        return self._request("GET", f"/api/clubs/{club_id}/meetings", headers=headers, params=params)

    def list_club_treasury_transactions(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/api/clubs/{club_id}/treasury-transactions", headers=headers, params=params
        )

    # --- Volunteers & screening ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/api/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/api/volunteers/{volunteer_id}", headers=headers)

    def clear_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/clear", headers=headers)

    def deny_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/api/volunteers/{volunteer_id}/deny", headers=headers)

    def list_volunteer_screening_events(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/api/volunteers/{volunteer_id}/screening-events", headers=headers, params=params
        )

    def create_screening_event(self, payload, headers):
        return self._request("POST", "/api/screening-events", payload, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/activate", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/suspend", headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/reinstate", headers=headers)

    def graduate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/graduate", headers=headers)

    def list_member_projects(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/projects", headers=headers, params=params)

    def list_member_attendance(self, member_id, headers, params=None):
        return self._request("GET", f"/api/members/{member_id}/attendance", headers=headers, params=params)

    def list_member_fair_entries(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/api/members/{member_id}/fair-entries", headers=headers, params=params
        )

    def list_member_award_applications(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/api/members/{member_id}/award-applications", headers=headers, params=params
        )

    def list_member_scholarship_apps(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/api/members/{member_id}/scholarship-apps", headers=headers, params=params
        )

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def start_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/start", headers=headers)

    def complete_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/complete", payload, headers)

    def drop_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/drop", headers=headers)

    def list_project_animal_tags(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/animal-tags", headers=headers, params=params
        )

    def list_project_record_books(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/record-books", headers=headers, params=params
        )

    # --- Animal tags ---
    def create_animal_tag(self, payload, headers):
        return self._request("POST", "/api/animal-tags", payload, headers)

    def verify_animal_tag(self, tag_id, headers):
        return self._request("POST", f"/api/animal-tags/{tag_id}/verify", headers=headers)

    def reject_animal_tag(self, tag_id, headers):
        return self._request("POST", f"/api/animal-tags/{tag_id}/reject", headers=headers)

    # --- Record books & ledger ---
    def create_record_book(self, payload, headers):
        return self._request("POST", "/api/record-books", payload, headers)

    def get_record_book(self, record_book_id, headers):
        return self._request("GET", f"/api/record-books/{record_book_id}", headers=headers)

    def list_record_book_ledger_entries(self, record_book_id, headers, params=None):
        return self._request(
            "GET", f"/api/record-books/{record_book_id}/ledger-entries", headers=headers, params=params
        )

    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/api/ledger-entries", payload, headers)

    def void_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/api/ledger-entries/{entry_id}/void", headers=headers)

    def submit_record_book(self, record_book_id, payload, headers):
        return self._request("POST", f"/api/record-books/{record_book_id}/submit", payload, headers)

    def begin_review_record_book(self, record_book_id, headers):
        return self._request("POST", f"/api/record-books/{record_book_id}/begin-review", headers=headers)

    def return_record_book(self, record_book_id, headers):
        return self._request("POST", f"/api/record-books/{record_book_id}/return", headers=headers)

    def approve_record_book(self, record_book_id, headers):
        return self._request("POST", f"/api/record-books/{record_book_id}/approve", headers=headers)

    def reject_record_book(self, record_book_id, headers):
        return self._request("POST", f"/api/record-books/{record_book_id}/reject", headers=headers)

    # --- Rooms & meetings ---
    def create_room(self, payload, headers):
        return self._request("POST", "/api/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/api/rooms/{room_id}", headers=headers)

    def create_meeting(self, payload, headers):
        return self._request("POST", "/api/meetings", payload, headers)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/api/meetings/{meeting_id}", headers=headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/api/meetings", headers=headers, params=params)

    def mark_meeting_held(self, meeting_id, headers):
        return self._request("POST", f"/api/meetings/{meeting_id}/mark-held", headers=headers)

    def cancel_meeting(self, meeting_id, headers):
        return self._request("POST", f"/api/meetings/{meeting_id}/cancel", headers=headers)

    def list_meeting_attendance(self, meeting_id, headers, params=None):
        return self._request(
            "GET", f"/api/meetings/{meeting_id}/attendance", headers=headers, params=params
        )

    def create_attendance(self, payload, headers):
        return self._request("POST", "/api/attendance", payload, headers)

    # --- Pens & stalls ---
    def create_pen(self, payload, headers):
        return self._request("POST", "/api/pens", payload, headers)

    def get_pen(self, pen_id, headers):
        return self._request("GET", f"/api/pens/{pen_id}", headers=headers)

    def list_pen_stall_assignments(self, pen_id, headers, params=None):
        return self._request(
            "GET", f"/api/pens/{pen_id}/stall-assignments", headers=headers, params=params
        )

    def create_stall_assignment(self, payload, headers):
        return self._request("POST", "/api/stall-assignments", payload, headers)

    def release_stall_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/stall-assignments/{assignment_id}/release", headers=headers)

    # --- Fair entries ---
    def create_fair_entry(self, payload, headers):
        return self._request("POST", "/api/fair-entries", payload, headers)

    def list_fair_entries(self, headers, params=None):
        return self._request("GET", "/api/fair-entries", headers=headers, params=params)

    def get_fair_entry(self, entry_id, headers):
        return self._request("GET", f"/api/fair-entries/{entry_id}", headers=headers)

    def confirm_fair_entry(self, entry_id, headers):
        return self._request("POST", f"/api/fair-entries/{entry_id}/confirm", headers=headers)

    def mark_fair_entry_exhibited(self, entry_id, headers):
        return self._request("POST", f"/api/fair-entries/{entry_id}/mark-exhibited", headers=headers)

    def scratch_fair_entry(self, entry_id, headers):
        return self._request("POST", f"/api/fair-entries/{entry_id}/scratch", headers=headers)

    def list_fair_entry_stall_assignments(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/api/fair-entries/{entry_id}/stall-assignments", headers=headers, params=params
        )

    # --- Award applications ---
    def create_award_application(self, payload, headers):
        return self._request("POST", "/api/award-applications", payload, headers)

    def list_award_applications(self, headers, params=None):
        return self._request("GET", "/api/award-applications", headers=headers, params=params)

    def get_award_application(self, application_id, headers):
        return self._request("GET", f"/api/award-applications/{application_id}", headers=headers)

    def nominate_award_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/award-applications/{application_id}/nominate", payload, headers
        )

    def endorse_award_application(self, application_id, headers):
        return self._request("POST", f"/api/award-applications/{application_id}/endorse", headers=headers)

    def evaluate_award_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/api/award-applications/{application_id}/evaluate", payload, headers
        )

    def award_award_application(self, application_id, headers):
        return self._request("POST", f"/api/award-applications/{application_id}/award", headers=headers)

    def deny_award_application(self, application_id, headers):
        return self._request("POST", f"/api/award-applications/{application_id}/deny", headers=headers)

    def withdraw_award_application(self, application_id, headers):
        return self._request("POST", f"/api/award-applications/{application_id}/withdraw", headers=headers)

    # --- Scholarship applications ---
    def create_scholarship_app(self, payload, headers):
        return self._request("POST", "/api/scholarship-apps", payload, headers)

    def list_scholarship_apps(self, headers, params=None):
        return self._request("GET", "/api/scholarship-apps", headers=headers, params=params)

    def get_scholarship_app(self, app_id, headers):
        return self._request("GET", f"/api/scholarship-apps/{app_id}", headers=headers)

    def submit_scholarship_app(self, app_id, headers):
        return self._request("POST", f"/api/scholarship-apps/{app_id}/submit", headers=headers)

    def grant_scholarship_app(self, app_id, headers):
        return self._request("POST", f"/api/scholarship-apps/{app_id}/grant", headers=headers)

    def decline_scholarship_app(self, app_id, headers):
        return self._request("POST", f"/api/scholarship-apps/{app_id}/decline", headers=headers)

    # --- Treasury ---
    def create_treasury_transaction(self, payload, headers):
        return self._request("POST", "/api/treasury-transactions", payload, headers)

    def void_treasury_transaction(self, txn_id, headers):
        return self._request("POST", f"/api/treasury-transactions/{txn_id}/void", headers=headers)

    def get_treasury_transaction(self, txn_id, headers):
        return self._request("GET", f"/api/treasury-transactions/{txn_id}", headers=headers)

    def approve_treasury_transaction(self, txn_id, headers):
        return self._request("POST", f"/api/treasury-transactions/{txn_id}/approve", headers=headers)


api_client = ApiClient()
