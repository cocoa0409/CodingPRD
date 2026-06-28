"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Practice ---
    def create_practice(self, payload, headers):
        return self._request("POST", "/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/practices/{practice_id}", headers=headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def list_provider_members(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/members", headers=headers, params=params)

    def list_provider_visit_slots(self, provider_id, headers, params=None):
        return self._request("GET", f"/providers/{provider_id}/visit-slots", headers=headers, params=params)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/employers", headers=headers, params=params)

    def create_seat(self, employer_id, payload, headers):
        return self._request("POST", f"/employers/{employer_id}/seats", payload, headers)

    def list_employer_seats(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/seats", headers=headers, params=params)

    def get_employer_seat(self, seat_id, headers):
        return self._request("GET", f"/employer-seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/employer-seats", headers=headers, params=params)

    def occupy_seat(self, employer_id, seat_id, payload, headers):
        return self._request("POST", f"/employers/{employer_id}/seats/{seat_id}/occupy", payload, headers)

    # --- Member + Membership ---
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def assign_pcp(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/assign-pcp", payload, headers)

    def cancel_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/cancel", headers=headers)

    def list_member_memberships(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def charge_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/charge", payload, headers)

    # --- VisitSlot + Visit ---
    def create_visit_slot(self, provider_id, payload, headers):
        return self._request("POST", f"/providers/{provider_id}/visit-slots", payload, headers)

    def get_visit_slot(self, slot_id, headers):
        return self._request("GET", f"/visit-slots/{slot_id}", headers=headers)

    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def check_in_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/check-in", headers=headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", headers=headers)

    def no_show_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/no-show", headers=headers)

    def invoice_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/invoice", headers=headers)

    def write_off_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/write-off", headers=headers)

    # --- CarePlan ---
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/care-plans", headers=headers, params=params)

    def patch_care_plan(self, care_plan_id, payload, headers):
        return self._request("PATCH", f"/care-plans/{care_plan_id}", payload, headers)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/activate", headers=headers)

    def reopen_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/reopen", headers=headers)

    def archive_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/archive", headers=headers)

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def authorize_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/authorize", headers=headers)

    def deny_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/deny", headers=headers)

    def send_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/send", headers=headers)

    # --- MessageThread ---
    def create_message_thread(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/message-threads", payload, headers)

    def get_message_thread(self, thread_id, headers):
        return self._request("GET", f"/message-threads/{thread_id}", headers=headers)

    def list_message_threads(self, headers, params=None):
        return self._request("GET", "/message-threads", headers=headers, params=params)

    def list_member_message_threads(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/message-threads", headers=headers, params=params)

    def reply_message_thread(self, thread_id, payload, headers):
        return self._request("POST", f"/message-threads/{thread_id}/reply", payload, headers)

    def close_message_thread(self, thread_id, headers):
        return self._request("POST", f"/message-threads/{thread_id}/close", headers=headers)

    # --- Invoice ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def charge_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/charge", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    # --- Payment ---
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # --- Test-driving endpoints ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_suspension_sweep(self, headers):
        return self._request("POST", "/_billing/run_suspension_sweep", headers=headers)


api_client = ApiClient()
