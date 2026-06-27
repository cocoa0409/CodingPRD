"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (administrative; outside the /gc mount) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- ProtectedPerson ----
    def create_protected_person(self, payload, headers):
        return self._request("POST", "/gc/protected-persons", payload, headers)

    def get_protected_person(self, person_id, headers):
        return self._request(
            "GET", f"/gc/protected-persons/{person_id}", headers=headers
        )

    def list_protected_persons(self, headers, params=None):
        return self._request(
            "GET", "/gc/protected-persons", headers=headers, params=params
        )

    # ---- Fiduciary ----
    def create_fiduciary(self, payload, headers):
        return self._request("POST", "/gc/fiduciaries", payload, headers)

    def get_fiduciary(self, fiduciary_id, headers):
        return self._request("GET", f"/gc/fiduciaries/{fiduciary_id}", headers=headers)

    def list_fiduciaries(self, headers, params=None):
        return self._request("GET", "/gc/fiduciaries", headers=headers, params=params)

    # ---- GuardianshipCase ----
    def create_case(self, payload, headers):
        return self._request("POST", "/gc/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/gc/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/gc/cases", headers=headers, params=params)

    def open_review(self, case_id, headers):
        return self._request(
            "POST", f"/gc/cases/{case_id}/open-review", {}, headers
        )

    def close_review(self, case_id, headers):
        return self._request(
            "POST", f"/gc/cases/{case_id}/close-review", {}, headers
        )

    def terminate_case(self, case_id, headers):
        return self._request("POST", f"/gc/cases/{case_id}/terminate", {}, headers)

    def restore_case(self, case_id, headers):
        return self._request("POST", f"/gc/cases/{case_id}/restore", {}, headers)

    # ---- Petition ----
    def create_petition(self, payload, headers):
        return self._request("POST", "/gc/petitions", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/gc/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/gc/petitions", headers=headers, params=params)

    def find_probable_cause(self, petition_id, headers):
        return self._request(
            "POST", f"/gc/petitions/{petition_id}/find-probable-cause", {}, headers
        )

    def order_evaluation(self, petition_id, headers):
        return self._request(
            "POST", f"/gc/petitions/{petition_id}/order-evaluation", {}, headers
        )

    def grant_petition(self, petition_id, headers):
        return self._request(
            "POST", f"/gc/petitions/{petition_id}/grant", {}, headers
        )

    def dismiss_petition(self, petition_id, headers):
        return self._request(
            "POST", f"/gc/petitions/{petition_id}/dismiss", {}, headers
        )

    # ---- CapacityEvaluation ----
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/gc/evaluations", payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/gc/evaluations/{evaluation_id}", headers=headers
        )

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/gc/evaluations", headers=headers, params=params)

    def file_evaluation(self, evaluation_id, headers):
        return self._request(
            "POST", f"/gc/evaluations/{evaluation_id}/file", {}, headers
        )

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/gc/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/gc/appointments/{appointment_id}", headers=headers
        )

    def list_appointments(self, headers, params=None):
        return self._request(
            "GET", "/gc/appointments", headers=headers, params=params
        )

    def qualify_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/gc/appointments/{appointment_id}/qualify", {}, headers
        )

    def suspend_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/gc/appointments/{appointment_id}/suspend", {}, headers
        )

    def reinstate_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/gc/appointments/{appointment_id}/reinstate", {}, headers
        )

    def remove_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/gc/appointments/{appointment_id}/remove", payload, headers
        )

    # ---- Bond ----
    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/gc/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/gc/bonds", headers=headers, params=params)

    def post_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/gc/bonds/{bond_id}/post", payload, headers)

    def approve_bond(self, bond_id, headers):
        return self._request("POST", f"/gc/bonds/{bond_id}/approve", {}, headers)

    def reject_bond(self, bond_id, headers):
        return self._request("POST", f"/gc/bonds/{bond_id}/reject", {}, headers)

    # ---- RestrictedAccount ----
    def create_restricted_account(self, payload, headers):
        return self._request("POST", "/gc/restricted-accounts", payload, headers)

    def get_restricted_account(self, account_id, headers):
        return self._request(
            "GET", f"/gc/restricted-accounts/{account_id}", headers=headers
        )

    def list_restricted_accounts(self, headers, params=None):
        return self._request(
            "GET", "/gc/restricted-accounts", headers=headers, params=params
        )

    # ---- Inventory ----
    def create_inventory(self, payload, headers):
        return self._request("POST", "/gc/inventories", payload, headers)

    def get_inventory(self, inventory_id, headers):
        return self._request(
            "GET", f"/gc/inventories/{inventory_id}", headers=headers
        )

    def list_inventories(self, headers, params=None):
        return self._request("GET", "/gc/inventories", headers=headers, params=params)

    def file_inventory(self, inventory_id, headers):
        return self._request(
            "POST", f"/gc/inventories/{inventory_id}/file", {}, headers
        )

    def approve_inventory(self, inventory_id, headers):
        return self._request(
            "POST", f"/gc/inventories/{inventory_id}/approve", {}, headers
        )

    # ---- Budget ----
    def create_budget(self, payload, headers):
        return self._request("POST", "/gc/budgets", payload, headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/gc/budgets/{budget_id}", headers=headers)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/gc/budgets", headers=headers, params=params)

    def submit_budget(self, budget_id, headers):
        return self._request("POST", f"/gc/budgets/{budget_id}/submit", {}, headers)

    def approve_budget(self, budget_id, payload, headers):
        return self._request(
            "POST", f"/gc/budgets/{budget_id}/approve", payload, headers
        )

    # ---- Expenditure ----
    def create_expenditure(self, payload, headers):
        return self._request("POST", "/gc/expenditures", payload, headers)

    def get_expenditure(self, expenditure_id, headers):
        return self._request(
            "GET", f"/gc/expenditures/{expenditure_id}", headers=headers
        )

    def list_expenditures(self, headers, params=None):
        return self._request(
            "GET", "/gc/expenditures", headers=headers, params=params
        )

    def approve_expenditure(self, expenditure_id, headers):
        return self._request(
            "POST", f"/gc/expenditures/{expenditure_id}/approve", {}, headers
        )

    def deny_expenditure(self, expenditure_id, headers):
        return self._request(
            "POST", f"/gc/expenditures/{expenditure_id}/deny", {}, headers
        )

    def disburse_expenditure(self, expenditure_id, headers):
        return self._request(
            "POST", f"/gc/expenditures/{expenditure_id}/disburse", {}, headers
        )

    # ---- AccountingReport ----
    def create_accounting(self, payload, headers):
        return self._request("POST", "/gc/accountings", payload, headers)

    def get_accounting(self, accounting_id, headers):
        return self._request(
            "GET", f"/gc/accountings/{accounting_id}", headers=headers
        )

    def list_accountings(self, headers, params=None):
        return self._request("GET", "/gc/accountings", headers=headers, params=params)

    def submit_accounting(self, accounting_id, headers):
        return self._request(
            "POST", f"/gc/accountings/{accounting_id}/submit", {}, headers
        )

    def return_accounting(self, accounting_id, headers):
        return self._request(
            "POST", f"/gc/accountings/{accounting_id}/return", {}, headers
        )

    def resubmit_accounting(self, accounting_id, payload, headers):
        return self._request(
            "POST", f"/gc/accountings/{accounting_id}/resubmit", payload, headers
        )

    def approve_accounting(self, accounting_id, headers):
        return self._request(
            "POST", f"/gc/accountings/{accounting_id}/approve", {}, headers
        )

    # ---- CarePlan ----
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/gc/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/gc/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/gc/care-plans", headers=headers, params=params)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request(
            "POST", f"/gc/care-plans/{care_plan_id}/activate", {}, headers
        )

    def replace_care_plan(self, care_plan_id, headers):
        return self._request(
            "POST", f"/gc/care-plans/{care_plan_id}/replace", {}, headers
        )

    # ---- CourtReview ----
    def create_review(self, payload, headers):
        return self._request("POST", "/gc/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/gc/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/gc/reviews", headers=headers, params=params)

    def hold_review(self, review_id, headers):
        return self._request("POST", f"/gc/reviews/{review_id}/hold", {}, headers)

    def dispose_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/gc/reviews/{review_id}/dispose", payload, headers
        )


api_client = ApiClient()
