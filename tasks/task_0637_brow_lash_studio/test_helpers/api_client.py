"""API client: one method per endpoint defined in the PRD (flat topology)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (test-driving) ───
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ─── Studio ───
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/studios", headers=headers, params=params)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    # ─── ServiceType ───
    def create_service_type(self, payload, headers):
        return self._request("POST", "/service-types", payload, headers)

    def list_service_types(self, headers, params=None):
        return self._request("GET", "/service-types", headers=headers, params=params)

    def get_service_type(self, service_type_id, headers):
        return self._request("GET", f"/service-types/{service_type_id}", headers=headers)

    def retire_service_type(self, service_type_id, headers):
        return self._request("POST", f"/service-types/{service_type_id}/retire", {}, headers)

    # ─── MembershipPlan ───
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    # ─── LashTech ───
    def create_lash_tech(self, payload, headers):
        return self._request("POST", "/lash-techs", payload, headers)

    def list_lash_techs(self, headers, params=None):
        return self._request("GET", "/lash-techs", headers=headers, params=params)

    def get_lash_tech(self, tech_id, headers):
        return self._request("GET", f"/lash-techs/{tech_id}", headers=headers)

    def set_lash_tech_status(self, tech_id, status, headers):
        return self._request("POST", f"/lash-techs/{tech_id}/set-status", {"status": status}, headers)

    def list_tech_sanitation_logs(self, tech_id, headers, params=None):
        return self._request("GET", f"/lash-techs/{tech_id}/sanitation-logs", headers=headers, params=params)

    # ─── SanitationLog ───
    def create_sanitation_log(self, payload, headers):
        return self._request("POST", "/sanitation-logs", payload, headers)

    def list_sanitation_logs(self, headers, params=None):
        return self._request("GET", "/sanitation-logs", headers=headers, params=params)

    def get_sanitation_log(self, log_id, headers):
        return self._request("GET", f"/sanitation-logs/{log_id}", headers=headers)

    def void_sanitation_log(self, log_id, headers):
        return self._request("POST", f"/sanitation-logs/{log_id}/void", {}, headers)

    # ─── Member ───
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_member_patch_tests(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/patch-tests", headers=headers, params=params)

    # ─── Membership ───
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_credit_ledger(self, membership_id, headers, params=None):
        return self._request("GET", f"/memberships/{membership_id}/credit-ledger", headers=headers, params=params)

    def close_cycle(self, membership_id, expected_membership_version, headers):
        return self._request("POST", f"/memberships/{membership_id}/close-cycle",
                             {"expected_membership_version": expected_membership_version}, headers)

    def flag_past_due(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/flag-past-due", {}, headers)

    def settle_dues(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/settle-dues", {}, headers)

    def reactivate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/reactivate", {}, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel-membership", {}, headers)

    # ─── ConsentPatchTest ───
    def create_patch_test(self, payload, headers):
        return self._request("POST", "/patch-tests", payload, headers)

    def list_patch_tests(self, headers, params=None):
        return self._request("GET", "/patch-tests", headers=headers, params=params)

    def get_patch_test(self, patch_test_id, headers):
        return self._request("GET", f"/patch-tests/{patch_test_id}", headers=headers)

    def revoke_patch_test(self, patch_test_id, headers):
        return self._request("POST", f"/patch-tests/{patch_test_id}/revoke", {}, headers)

    # ─── Appointment ───
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    def mark_no_show(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/mark-no-show", {}, headers)

    def list_appointment_retail_orders(self, appointment_id, headers, params=None):
        return self._request("GET", f"/appointments/{appointment_id}/retail-orders", headers=headers, params=params)

    # ─── RetailOrder ───
    def create_retail_order(self, payload, headers):
        return self._request("POST", "/retail-orders", payload, headers)

    def list_retail_orders(self, headers, params=None):
        return self._request("GET", "/retail-orders", headers=headers, params=params)

    def get_retail_order(self, order_id, headers):
        return self._request("GET", f"/retail-orders/{order_id}", headers=headers)

    def void_retail_order(self, order_id, headers):
        return self._request("POST", f"/retail-orders/{order_id}/void", {}, headers)

    # ─── RecurringFillSchedule ───
    def create_recurring_schedule(self, payload, headers):
        return self._request("POST", "/recurring-schedules", payload, headers)

    def list_recurring_schedules(self, headers, params=None):
        return self._request("GET", "/recurring-schedules", headers=headers, params=params)

    def get_recurring_schedule(self, schedule_id, headers):
        return self._request("GET", f"/recurring-schedules/{schedule_id}", headers=headers)

    def spawn_next(self, schedule_id, expected_membership_version, headers):
        return self._request("POST", f"/recurring-schedules/{schedule_id}/spawn-next",
                             {"expected_membership_version": expected_membership_version}, headers)

    def pause_schedule(self, schedule_id, headers):
        return self._request("POST", f"/recurring-schedules/{schedule_id}/pause", {}, headers)

    def resume_schedule(self, schedule_id, headers):
        return self._request("POST", f"/recurring-schedules/{schedule_id}/resume", {}, headers)

    def end_schedule(self, schedule_id, headers):
        return self._request("POST", f"/recurring-schedules/{schedule_id}/end", {}, headers)


api_client = ApiClient()
