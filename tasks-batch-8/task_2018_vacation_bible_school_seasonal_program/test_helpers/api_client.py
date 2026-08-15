"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program lifecycle ---
    def create_program(self, payload, headers):
        return self._request("POST", "/vbs/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/vbs/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/vbs/programs/{program_id}", headers=headers)

    def open_registration(self, program_id, headers):
        return self._request(
            "POST", f"/vbs/programs/{program_id}/open-registration", {}, headers
        )

    def close_registration(self, program_id, headers):
        return self._request(
            "POST", f"/vbs/programs/{program_id}/close-registration", {}, headers
        )

    def start_session(self, program_id, headers):
        return self._request(
            "POST", f"/vbs/programs/{program_id}/start-session", {}, headers
        )

    def complete_program(self, program_id, headers):
        return self._request("POST", f"/vbs/programs/{program_id}/complete", {}, headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/vbs/programs/{program_id}/archive", {}, headers)

    def sweep_expired_offers(self, program_id, payload, headers):
        return self._request(
            "POST", f"/vbs/programs/{program_id}/sweep-expired-offers", payload, headers
        )

    def get_supply_plan(self, program_id, headers):
        return self._request(
            "GET", f"/vbs/programs/{program_id}/supply-plan", headers=headers
        )

    def get_attendance_summary(self, program_id, child_id, headers):
        return self._request(
            "GET",
            f"/vbs/programs/{program_id}/attendance-summaries/{child_id}",
            headers=headers,
        )

    def generate_retention_list(self, program_id, payload, headers):
        return self._request(
            "POST",
            f"/vbs/programs/{program_id}/retention-list/generate",
            payload,
            headers,
        )

    # --- Classrooms ---
    def create_classroom(self, payload, headers):
        return self._request("POST", "/vbs/classrooms", payload, headers)

    def get_classroom(self, classroom_id, headers):
        return self._request("GET", f"/vbs/classrooms/{classroom_id}", headers=headers)

    def list_classrooms(self, headers, params=None):
        return self._request("GET", "/vbs/classrooms", headers=headers, params=params)

    def patch_classroom(self, classroom_id, payload, headers):
        return self._request("PATCH", f"/vbs/classrooms/{classroom_id}", payload, headers)

    def close_classroom(self, classroom_id, headers):
        return self._request("POST", f"/vbs/classrooms/{classroom_id}/close", {}, headers)

    # --- Families ---
    def create_family(self, payload, headers):
        return self._request("POST", "/vbs/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/vbs/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/vbs/families", headers=headers, params=params)

    def archive_family(self, family_id, headers):
        return self._request("POST", f"/vbs/families/{family_id}/archive", {}, headers)

    # --- Children ---
    def create_child(self, payload, headers):
        return self._request("POST", "/vbs/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/vbs/children/{child_id}", headers=headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/vbs/children", headers=headers, params=params)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/vbs/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/vbs/registrations/{registration_id}", headers=headers
        )

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/vbs/registrations", headers=headers, params=params)

    def cancel_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/vbs/registrations/{registration_id}/cancel", {}, headers
        )

    def accept_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/vbs/registrations/{registration_id}/accept", {}, headers
        )

    def decline_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/vbs/registrations/{registration_id}/decline", {}, headers
        )

    # --- Volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/vbs/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/vbs/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/vbs/volunteers", headers=headers, params=params)

    # --- Screening checks ---
    def create_screening_check(self, payload, headers):
        return self._request("POST", "/vbs/screening-checks", payload, headers)

    def decide_screening_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/vbs/screening-checks/{check_id}/decide", payload, headers
        )

    def resubmit_screening_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/vbs/screening-checks/{check_id}/resubmit", payload, headers
        )

    def get_screening_check(self, check_id, headers):
        return self._request(
            "GET", f"/vbs/screening-checks/{check_id}", headers=headers
        )

    def list_screening_checks(self, headers, params=None):
        return self._request(
            "GET", "/vbs/screening-checks", headers=headers, params=params
        )

    # --- Role assignments ---
    def create_role_assignment(self, payload, headers):
        return self._request("POST", "/vbs/role-assignments", payload, headers)

    def confirm_role_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/vbs/role-assignments/{assignment_id}/confirm", {}, headers
        )

    def release_role_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/vbs/role-assignments/{assignment_id}/release", {}, headers
        )

    def get_role_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/vbs/role-assignments/{assignment_id}", headers=headers
        )

    def list_role_assignments(self, headers, params=None):
        return self._request(
            "GET", "/vbs/role-assignments", headers=headers, params=params
        )

    # --- Accommodation plans ---
    def create_accommodation_plan(self, payload, headers):
        return self._request("POST", "/vbs/accommodation-plans", payload, headers)

    def submit_accommodation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/vbs/accommodation-plans/{plan_id}/submit", {}, headers
        )

    def approve_accommodation_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/vbs/accommodation-plans/{plan_id}/approve", payload, headers
        )

    def request_plan_revision(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/vbs/accommodation-plans/{plan_id}/request-revision",
            payload, headers,
        )

    def get_accommodation_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/vbs/accommodation-plans/{plan_id}", headers=headers
        )

    def list_accommodation_plans(self, headers, params=None):
        return self._request(
            "GET", "/vbs/accommodation-plans", headers=headers, params=params
        )

    # --- Supply orders ---
    def create_supply_order(self, payload, headers):
        return self._request("POST", "/vbs/supply-orders", payload, headers)

    def patch_supply_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/vbs/supply-orders/{order_id}", payload, headers)

    def submit_supply_order(self, order_id, headers):
        return self._request(
            "POST", f"/vbs/supply-orders/{order_id}/submit", {}, headers
        )

    def return_supply_order_for_revision(self, order_id, headers):
        return self._request(
            "POST", f"/vbs/supply-orders/{order_id}/return-for-revision", {}, headers
        )

    def approve_supply_order(self, order_id, headers):
        return self._request(
            "POST", f"/vbs/supply-orders/{order_id}/approve", {}, headers
        )

    def cancel_supply_order(self, order_id, headers):
        return self._request(
            "POST", f"/vbs/supply-orders/{order_id}/cancel", {}, headers
        )

    def get_supply_order(self, order_id, headers):
        return self._request("GET", f"/vbs/supply-orders/{order_id}", headers=headers)

    def list_supply_orders(self, headers, params=None):
        return self._request("GET", "/vbs/supply-orders", headers=headers, params=params)

    # --- Supply items ---
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/vbs/supply-items", payload, headers)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/vbs/supply-items/{item_id}", headers=headers)

    def list_supply_items(self, headers, params=None):
        return self._request("GET", "/vbs/supply-items", headers=headers, params=params)

    def restock_supply_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/vbs/supply-items/{item_id}/restock", payload, headers
        )

    # --- Supply distributions ---
    def create_supply_distribution(self, payload, headers):
        return self._request("POST", "/vbs/supply-distributions", payload, headers)

    def issue_supply_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/vbs/supply-distributions/{distribution_id}/issue", {}, headers
        )

    def cancel_supply_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/vbs/supply-distributions/{distribution_id}/cancel", {}, headers
        )

    def get_supply_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/vbs/supply-distributions/{distribution_id}", headers=headers
        )

    def list_supply_distributions(self, headers, params=None):
        return self._request(
            "GET", "/vbs/supply-distributions", headers=headers, params=params
        )

    # --- Program days ---
    def create_program_day(self, payload, headers):
        return self._request("POST", "/vbs/days", payload, headers)

    def open_program_day(self, day_id, headers):
        return self._request("POST", f"/vbs/days/{day_id}/open", {}, headers)

    def close_program_day(self, day_id, headers):
        return self._request("POST", f"/vbs/days/{day_id}/close", {}, headers)

    def get_program_day(self, day_id, headers):
        return self._request("GET", f"/vbs/days/{day_id}", headers=headers)

    def list_program_days(self, headers, params=None):
        return self._request("GET", "/vbs/days", headers=headers, params=params)

    # --- Attendance & security tags ---
    def check_in(self, payload, headers):
        return self._request("POST", "/vbs/attendance/check-in", payload, headers)

    def check_out(self, payload, headers):
        return self._request("POST", "/vbs/attendance/check-out", payload, headers)

    def reprint_tag(self, payload, headers):
        return self._request("POST", "/vbs/attendance/reprint-tag", payload, headers)

    def get_attendance_record(self, record_id, headers):
        return self._request("GET", f"/vbs/attendance/{record_id}", headers=headers)

    def list_attendance(self, headers, params=None):
        return self._request("GET", "/vbs/attendance", headers=headers, params=params)

    def get_security_tag(self, tag_id, headers):
        return self._request("GET", f"/vbs/security-tags/{tag_id}", headers=headers)

    def list_security_tags(self, headers, params=None):
        return self._request("GET", "/vbs/security-tags", headers=headers, params=params)

    # --- Family messages ---
    def create_message(self, payload, headers):
        return self._request("POST", "/vbs/messages", payload, headers)

    def send_message(self, message_id, headers):
        return self._request("POST", f"/vbs/messages/{message_id}/send", {}, headers)

    def cancel_message(self, message_id, headers):
        return self._request("POST", f"/vbs/messages/{message_id}/cancel", {}, headers)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/vbs/messages/{message_id}", headers=headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/vbs/messages", headers=headers, params=params)

    # --- Retention entries ---
    def get_retention_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/vbs/retention-entries/{entry_id}", headers=headers
        )

    def list_retention_entries(self, headers, params=None):
        return self._request(
            "GET", "/vbs/retention-entries", headers=headers, params=params
        )

    def invite_retention_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/vbs/retention-entries/{entry_id}/invite", {}, headers
        )

    def record_retention_response(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"/vbs/retention-entries/{entry_id}/record-response",
            payload, headers,
        )

    # --- Logical clock (test-driving endpoint) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/vbs/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
