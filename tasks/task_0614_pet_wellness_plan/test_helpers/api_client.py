"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP envelope. All paths are mounted under the /wellness prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plan catalog ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/wellness/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/wellness/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/wellness/plans/{plan_id}", headers=headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/wellness/plans/{plan_id}/retire", headers=headers)

    # --- Plan services ---
    def create_plan_service(self, payload, headers):
        return self._request("POST", "/wellness/plan-services", payload, headers)

    def list_plan_services(self, headers, params=None):
        return self._request("GET", "/wellness/plan-services", headers=headers, params=params)

    def get_plan_service(self, plan_service_id, headers):
        return self._request("GET", f"/wellness/plan-services/{plan_service_id}", headers=headers)

    def retire_plan_service(self, plan_service_id, headers):
        return self._request("POST", f"/wellness/plan-services/{plan_service_id}/retire", headers=headers)

    # --- Clinics ---
    def create_clinic(self, payload, headers):
        return self._request("POST", "/wellness/clinics", payload, headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/wellness/clinics", headers=headers, params=params)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/wellness/clinics/{clinic_id}", headers=headers)

    def close_clinic(self, clinic_id, headers):
        return self._request("POST", f"/wellness/clinics/{clinic_id}/close", headers=headers)

    # --- Member accounts ---
    def create_member_account(self, payload, headers):
        return self._request("POST", "/wellness/member-accounts", payload, headers)

    def list_member_accounts(self, headers, params=None):
        return self._request("GET", "/wellness/member-accounts", headers=headers, params=params)

    def get_member_account(self, account_id, headers):
        return self._request("GET", f"/wellness/member-accounts/{account_id}", headers=headers)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/wellness/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/wellness/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/wellness/memberships/{membership_id}", headers=headers)

    def add_pet(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/pets", payload, headers)

    def list_pets(self, membership_id, headers, params=None):
        return self._request("GET", f"/wellness/memberships/{membership_id}/pets", headers=headers, params=params)

    def get_pet(self, membership_id, pet_id, headers):
        return self._request("GET", f"/wellness/memberships/{membership_id}/pets/{pet_id}", headers=headers)

    def remove_pet(self, membership_id, pet_id, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/pets/{pet_id}/remove", headers=headers)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/activate", headers=headers)

    def suspend_membership(self, membership_id, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/suspend", headers=headers)

    def resume_membership(self, membership_id, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/resume", headers=headers)

    def plan_change(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/plan-change", payload, headers)

    def list_membership_plan_changes(self, membership_id, headers, params=None):
        return self._request("GET", f"/wellness/memberships/{membership_id}/plan-changes", headers=headers, params=params)

    def list_plan_changes(self, headers, params=None):
        return self._request("GET", "/wellness/plan-changes", headers=headers, params=params)

    def get_plan_change(self, plan_change_id, headers):
        return self._request("GET", f"/wellness/plan-changes/{plan_change_id}", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/cancel", headers=headers)

    def finalize_cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/finalize-cancel", headers=headers)

    # --- Contract terms ---
    def list_contract_terms(self, headers, params=None):
        return self._request("GET", "/wellness/contract-terms", headers=headers, params=params)

    def get_contract_term(self, term_id, headers):
        return self._request("GET", f"/wellness/contract-terms/{term_id}", headers=headers)

    def list_term_credits(self, term_id, headers, params=None):
        return self._request("GET", f"/wellness/contract-terms/{term_id}/credits", headers=headers, params=params)

    def get_service_credit(self, credit_id, headers):
        return self._request("GET", f"/wellness/service-credits/{credit_id}", headers=headers)

    # --- Visits ---
    def record_visit(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/wellness/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/wellness/visits/{visit_id}", headers=headers)

    def void_visit(self, visit_id, headers):
        return self._request("POST", f"/wellness/visits/{visit_id}/void", headers=headers)

    # --- Billing cycles ---
    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/wellness/billing-cycles", headers=headers, params=params)

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/wellness/billing-cycles/{cycle_id}", headers=headers)

    # --- System / billing epoch / clock ---
    def run_epoch(self, headers):
        return self._request("POST", "/wellness/_billing/run-epoch", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/wellness/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/wellness/_clock", headers=headers)


api_client = ApiClient()
