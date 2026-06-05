"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the HTTP envelope.
List endpoints accept an optional `params` dict for query filters and pagination.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Registries ──────────────────────────────────────────────────────
    def create_debtor(self, payload, headers):
        return self._request("POST", "/debtors", payload, headers)

    def get_debtor(self, debtor_id, headers):
        return self._request("GET", f"/debtors/{debtor_id}", headers=headers)

    def create_creditor(self, payload, headers):
        return self._request("POST", "/creditors", payload, headers)

    def get_creditor(self, creditor_id, headers):
        return self._request("GET", f"/creditors/{creditor_id}", headers=headers)

    def create_trustee(self, payload, headers):
        return self._request("POST", "/trustees", payload, headers)

    def get_trustee(self, trustee_id, headers):
        return self._request("GET", f"/trustees/{trustee_id}", headers=headers)

    # ─── Case lifecycle ──────────────────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def petition_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/petition", {}, headers)

    def confirm_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/confirm", {}, headers)

    def discharge_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/discharge", {}, headers)

    def dismiss_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/dismiss", {}, headers)

    # ─── Means test ──────────────────────────────────────────────────────
    def create_means_test(self, payload, headers):
        return self._request("POST", "/means-tests", payload, headers)

    def get_means_test(self, means_test_id, headers):
        return self._request("GET", f"/means-tests/{means_test_id}", headers=headers)

    def list_means_tests(self, headers, params=None):
        return self._request("GET", "/means-tests", headers=headers, params=params)

    # ─── 341 meeting ─────────────────────────────────────────────────────
    def create_meeting(self, payload, headers):
        return self._request("POST", "/meetings", payload, headers)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/meetings/{meeting_id}", headers=headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/meetings", headers=headers, params=params)

    def hold_meeting(self, meeting_id, headers):
        return self._request("POST", f"/meetings/{meeting_id}/hold", {}, headers)

    # ─── Schedules ───────────────────────────────────────────────────────
    def create_schedule(self, payload, headers):
        return self._request("POST", "/schedules", payload, headers)

    def get_schedule(self, schedule_id, headers):
        return self._request("GET", f"/schedules/{schedule_id}", headers=headers)

    def list_schedules(self, headers, params=None):
        return self._request("GET", "/schedules", headers=headers, params=params)

    # ─── Debts ───────────────────────────────────────────────────────────
    def create_debt(self, payload, headers):
        return self._request("POST", "/debts", payload, headers)

    def get_debt(self, debt_id, headers):
        return self._request("GET", f"/debts/{debt_id}", headers=headers)

    def list_debts(self, headers, params=None):
        return self._request("GET", "/debts", headers=headers, params=params)

    # ─── Claims ──────────────────────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def allow_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/allow", {}, headers)

    def disallow_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/disallow", {}, headers)

    # ─── Plans ───────────────────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def file_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/file-plan", {}, headers)

    def confirm_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/confirm-plan", {}, headers)

    def deny_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/deny-plan", {}, headers)

    def get_distribution(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}/distribution", headers=headers)

    # ─── Plan payments ───────────────────────────────────────────────────
    def create_plan_payment(self, payload, headers):
        return self._request("POST", "/plan-payments", payload, headers)

    def get_plan_payment(self, payment_id, headers):
        return self._request("GET", f"/plan-payments/{payment_id}", headers=headers)

    def list_plan_payments(self, headers, params=None):
        return self._request("GET", "/plan-payments", headers=headers, params=params)

    # ─── Stay relief motions ─────────────────────────────────────────────
    def create_stay_relief_motion(self, payload, headers):
        return self._request("POST", "/stay-relief-motions", payload, headers)

    def get_stay_relief_motion(self, motion_id, headers):
        return self._request("GET", f"/stay-relief-motions/{motion_id}", headers=headers)

    def list_stay_relief_motions(self, headers, params=None):
        return self._request("GET", "/stay-relief-motions", headers=headers, params=params)

    def grant_stay_relief_motion(self, motion_id, headers):
        return self._request("POST", f"/stay-relief-motions/{motion_id}/grant", {}, headers)

    def deny_stay_relief_motion(self, motion_id, headers):
        return self._request("POST", f"/stay-relief-motions/{motion_id}/deny", {}, headers)


api_client = ApiClient()
