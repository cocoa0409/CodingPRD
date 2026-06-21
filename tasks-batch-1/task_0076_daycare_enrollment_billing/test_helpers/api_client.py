"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Test-driving clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- Center / config -----
    def create_center(self, payload, headers):
        return self._request("POST", "/centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/centers/{center_id}", headers=headers)

    def add_sliding_scale(self, center_id, payload, headers):
        return self._request("POST", f"/centers/{center_id}/sliding-scale", payload, headers)

    def list_sliding_scale(self, center_id, headers, params=None):
        return self._request("GET", f"/centers/{center_id}/sliding-scale",
                             headers=headers, params=params)

    # ----- Classroom -----
    def create_classroom(self, center_id, payload, headers):
        return self._request("POST", f"/centers/{center_id}/classrooms", payload, headers)

    def list_classrooms(self, center_id, headers, params=None):
        return self._request("GET", f"/centers/{center_id}/classrooms",
                             headers=headers, params=params)

    def get_classroom(self, classroom_id, headers):
        return self._request("GET", f"/classrooms/{classroom_id}", headers=headers)

    # ----- Family / Child -----
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def patch_family(self, family_id, payload, headers):
        return self._request("PATCH", f"/families/{family_id}", payload, headers)

    def create_child(self, payload, headers):
        return self._request("POST", "/children", payload, headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/children", headers=headers, params=params)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}", headers=headers)

    # ----- Waitlist -----
    def add_to_waitlist(self, classroom_id, payload, headers):
        return self._request("POST", f"/classrooms/{classroom_id}/waitlist", payload, headers)

    def list_classroom_waitlist(self, classroom_id, headers, params=None):
        return self._request("GET", f"/classrooms/{classroom_id}/waitlist",
                             headers=headers, params=params)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def promote_waitlist(self, classroom_id, headers):
        return self._request("POST", f"/classrooms/{classroom_id}/waitlist/promote", {}, headers)

    def expire_stale_waitlist(self, classroom_id, headers):
        return self._request("POST", f"/classrooms/{classroom_id}/waitlist/expire-stale", {}, headers)

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/withdraw", {}, headers)

    # ----- Enrollment -----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def accept_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/accept", {}, headers)

    def decline_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/decline", {}, headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    def graduate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/graduate", {}, headers)

    # ----- Attendance / check-in app -----
    def create_attendance(self, payload, headers):
        return self._request("POST", "/attendance-records", payload, headers)

    def list_attendance(self, headers, params=None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/attendance-records/{attendance_id}", headers=headers)

    def check_out(self, attendance_id, headers):
        return self._request("POST", f"/attendance-records/{attendance_id}/check-out", {}, headers)

    # ----- Invoice / Payment -----
    def create_invoice(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/invoices", payload, headers)

    def list_invoices(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments", headers=headers, params=params)

    # ----- Tax statement -----
    def create_tax_statement(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/tax-statements", payload, headers)

    def list_tax_statements(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/tax-statements", headers=headers, params=params)


api_client = ApiClient()
