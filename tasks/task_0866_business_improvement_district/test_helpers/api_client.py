"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- BusinessImprovementDistrict ----
    def create_bid(self, payload, headers):
        return self._request("POST", "/business-improvement-districts", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/business-improvement-districts/{bid_id}", headers=headers)

    def activate_bid(self, bid_id, headers):
        return self._request("POST", f"/business-improvement-districts/{bid_id}/activate", headers=headers)

    # ---- Parcel ----
    def create_parcel(self, bid_id, payload, headers):
        return self._request("POST", f"/business-improvement-districts/{bid_id}/parcels", payload, headers)

    def list_parcels(self, bid_id, headers, params=None):
        return self._request("GET", f"/business-improvement-districts/{bid_id}/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def withdraw_parcel(self, parcel_id, headers):
        return self._request("POST", f"/parcels/{parcel_id}/withdraw", headers=headers)

    # ---- FiscalYear ----
    def create_fiscal_year(self, bid_id, payload, headers):
        return self._request("POST", f"/business-improvement-districts/{bid_id}/fiscal-years", payload, headers)

    def list_fiscal_years(self, bid_id, headers, params=None):
        return self._request("GET", f"/business-improvement-districts/{bid_id}/fiscal-years", headers=headers, params=params)

    def get_fiscal_year(self, fy_id, headers):
        return self._request("GET", f"/fiscal-years/{fy_id}", headers=headers)

    def get_financial_report(self, fy_id, headers):
        return self._request("GET", f"/fiscal-years/{fy_id}/financial-report", headers=headers)

    # ---- Budget / WorkPlanLine ----
    def create_budget(self, fy_id, payload, headers):
        return self._request("POST", f"/fiscal-years/{fy_id}/budget", payload, headers)

    def get_fiscal_year_budget(self, fy_id, headers):
        return self._request("GET", f"/fiscal-years/{fy_id}/budget", headers=headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/budgets/{budget_id}", headers=headers)

    def create_work_plan_line(self, budget_id, payload, headers):
        return self._request("POST", f"/budgets/{budget_id}/work-plan-lines", payload, headers)

    def list_work_plan_lines(self, budget_id, headers, params=None):
        return self._request("GET", f"/budgets/{budget_id}/work-plan-lines", headers=headers, params=params)

    def create_reallocation(self, budget_id, payload, headers):
        return self._request("POST", f"/budgets/{budget_id}/reallocations", payload, headers)

    def propose_budget(self, budget_id, headers):
        return self._request("POST", f"/budgets/{budget_id}/propose", headers=headers)

    def adopt_budget(self, budget_id, headers):
        return self._request("POST", f"/budgets/{budget_id}/adopt", headers=headers)

    def revert_budget(self, budget_id, headers):
        return self._request("POST", f"/budgets/{budget_id}/revert", headers=headers)

    # ---- Assessment ----
    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    # ---- CollectionAccount / Payment ----
    def get_assessment_collection_account(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}/collection-account", headers=headers)

    def get_collection_account(self, account_id, headers):
        return self._request("GET", f"/collection-accounts/{account_id}", headers=headers)

    def get_payoff_quote(self, account_id, as_of_date, headers):
        return self._request("GET", f"/collection-accounts/{account_id}/payoff-quote",
                             headers=headers, params={"as_of_date": as_of_date})

    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/collection-accounts/{account_id}/payments", payload, headers)

    def list_payments(self, account_id, headers, params=None):
        return self._request("GET", f"/collection-accounts/{account_id}/payments", headers=headers, params=params)

    def assess_delinquency(self, account_id, headers):
        return self._request("POST", f"/collection-accounts/{account_id}/assess-delinquency", headers=headers)

    def write_off(self, account_id, headers):
        return self._request("POST", f"/collection-accounts/{account_id}/write-off", headers=headers)

    # ---- Dispute ----
    def create_dispute(self, assessment_id, payload, headers):
        return self._request("POST", f"/assessments/{assessment_id}/disputes", payload, headers)

    def list_disputes(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def transition_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/transition", payload, headers)

    # ---- RenewalPetition / signatures ----
    def create_renewal_petition(self, bid_id, payload, headers):
        return self._request("POST", f"/business-improvement-districts/{bid_id}/renewal-petitions", payload, headers)

    def list_renewal_petitions(self, bid_id, headers, params=None):
        return self._request("GET", f"/business-improvement-districts/{bid_id}/renewal-petitions", headers=headers, params=params)

    def get_renewal_petition(self, petition_id, headers):
        return self._request("GET", f"/renewal-petitions/{petition_id}", headers=headers)

    def create_signature(self, petition_id, payload, headers):
        return self._request("POST", f"/renewal-petitions/{petition_id}/signatures", payload, headers)

    def list_petition_signatures(self, headers, params=None):
        return self._request("GET", "/petition-signatures", headers=headers, params=params)

    def get_petition_signature(self, signature_id, headers):
        return self._request("GET", f"/petition-signatures/{signature_id}", headers=headers)

    def submit_petition(self, petition_id, headers):
        return self._request("POST", f"/renewal-petitions/{petition_id}/submit", headers=headers)

    def verify_petition(self, petition_id, headers):
        return self._request("POST", f"/renewal-petitions/{petition_id}/verify", headers=headers)

    def vote_petition(self, petition_id, payload, headers):
        return self._request("POST", f"/renewal-petitions/{petition_id}/vote", payload, headers)

    # ---- Ambassador / shifts ----
    def create_ambassador(self, bid_id, payload, headers):
        return self._request("POST", f"/business-improvement-districts/{bid_id}/ambassadors", payload, headers)

    def deactivate_ambassador(self, ambassador_id, headers):
        return self._request("POST", f"/ambassadors/{ambassador_id}/deactivate", headers=headers)

    def list_ambassadors(self, bid_id, headers, params=None):
        return self._request("GET", f"/business-improvement-districts/{bid_id}/ambassadors", headers=headers, params=params)

    def get_ambassador(self, ambassador_id, headers):
        return self._request("GET", f"/ambassadors/{ambassador_id}", headers=headers)

    def create_shift(self, ambassador_id, payload, headers):
        return self._request("POST", f"/ambassadors/{ambassador_id}/shifts", payload, headers)

    def list_shifts(self, ambassador_id, headers, params=None):
        return self._request("GET", f"/ambassadors/{ambassador_id}/shifts", headers=headers, params=params)

    # ---- ServiceRequest ----
    def create_service_request(self, bid_id, payload, headers):
        return self._request("POST", f"/business-improvement-districts/{bid_id}/service-requests", payload, headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def get_service_request(self, sr_id, headers):
        return self._request("GET", f"/service-requests/{sr_id}", headers=headers)

    def transition_service_request(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/transition", payload, headers)


api_client = ApiClient()
