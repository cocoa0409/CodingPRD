"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- Tenant requirements -------------------------------------------------
    def create_tenant_requirement(self, payload, headers):
        return self._request("POST", "/api/tenant-requirements", payload, headers)

    def get_tenant_requirement(self, requirement_id, headers):
        return self._request(
            "GET", f"/api/tenant-requirements/{requirement_id}", headers=headers
        )

    def withdraw_tenant_requirement(self, requirement_id, headers):
        return self._request(
            "POST",
            f"/api/tenant-requirements/{requirement_id}/withdraw",
            headers=headers,
        )

    # -- Match evaluations (stateless screening read) ------------------------
    def create_match_evaluation(self, payload, headers):
        return self._request("POST", "/api/match-evaluations", payload, headers)

    # -- Sites ---------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    # -- Tours ---------------------------------------------------------------
    def create_tour(self, payload, headers):
        return self._request("POST", "/api/tours", payload, headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/api/tours", headers=headers, params=params)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/api/tours/{tour_id}", headers=headers)

    def confirm_tour(self, tour_id, headers):
        return self._request("POST", f"/api/tours/{tour_id}/confirm", headers=headers)

    def complete_tour(self, tour_id, headers):
        return self._request("POST", f"/api/tours/{tour_id}/complete", headers=headers)

    def cancel_tour(self, tour_id, headers):
        return self._request("POST", f"/api/tours/{tour_id}/cancel", headers=headers)

    # -- LOIs ----------------------------------------------------------------
    def create_loi(self, payload, headers):
        return self._request("POST", "/api/lois", payload, headers)

    def list_lois(self, headers, params=None):
        return self._request("GET", "/api/lois", headers=headers, params=params)

    def get_loi(self, loi_id, headers):
        return self._request("GET", f"/api/lois/{loi_id}", headers=headers)

    def submit_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/api/lois/{loi_id}/submit", payload, headers)

    def counter_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/api/lois/{loi_id}/counter", payload, headers)

    def accept_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/accept", headers=headers)

    def reject_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/reject", headers=headers)

    def withdraw_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/withdraw", headers=headers)

    def execute_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/execute", headers=headers)

    # -- Build-to-suit plans ---------------------------------------------------
    def list_bts_plans(self, headers, params=None):
        return self._request("GET", "/api/bts-plans", headers=headers, params=params)

    def get_bts_plan(self, plan_id, headers):
        return self._request("GET", f"/api/bts-plans/{plan_id}", headers=headers)

    def price_bts_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/api/bts-plans/{plan_id}/price", payload, headers
        )

    def revise_bts_plan(self, plan_id, headers):
        return self._request("POST", f"/api/bts-plans/{plan_id}/revise", headers=headers)

    def approve_bts_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/bts-plans/{plan_id}/approve", headers=headers
        )

    # -- Delivery milestones ---------------------------------------------------
    def create_delivery_milestone(self, payload, headers):
        return self._request("POST", "/api/delivery-milestones", payload, headers)

    def list_delivery_milestones(self, headers, params=None):
        return self._request(
            "GET", "/api/delivery-milestones", headers=headers, params=params
        )

    def get_delivery_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/api/delivery-milestones/{milestone_id}", headers=headers
        )

    def complete_delivery_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"/api/delivery-milestones/{milestone_id}/complete",
            payload,
            headers,
        )

    # -- Expansion options -----------------------------------------------------
    def create_expansion_option(self, payload, headers):
        return self._request("POST", "/api/expansion-options", payload, headers)

    def list_expansion_options(self, headers, params=None):
        return self._request(
            "GET", "/api/expansion-options", headers=headers, params=params
        )

    def get_expansion_option(self, option_id, headers):
        return self._request(
            "GET", f"/api/expansion-options/{option_id}", headers=headers
        )

    def exercise_expansion_option(self, option_id, headers):
        return self._request(
            "POST", f"/api/expansion-options/{option_id}/exercise", headers=headers
        )

    def release_expansion_option(self, option_id, headers):
        return self._request(
            "POST", f"/api/expansion-options/{option_id}/release", headers=headers
        )

    # -- Compliance reviews ----------------------------------------------------
    def create_compliance_review(self, payload, headers):
        return self._request("POST", "/api/compliance-reviews", payload, headers)

    def list_compliance_reviews(self, headers, params=None):
        return self._request(
            "GET", "/api/compliance-reviews", headers=headers, params=params
        )

    def get_compliance_review(self, review_id, headers):
        return self._request(
            "GET", f"/api/compliance-reviews/{review_id}", headers=headers
        )

    def begin_compliance_review(self, review_id, headers):
        return self._request(
            "POST", f"/api/compliance-reviews/{review_id}/begin", headers=headers
        )

    def resolve_compliance_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/api/compliance-reviews/{review_id}/resolve", payload, headers
        )

    # -- Commission invoices ---------------------------------------------------
    def list_commission_invoices(self, headers, params=None):
        return self._request(
            "GET", "/api/commission-invoices", headers=headers, params=params
        )

    def get_commission_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/api/commission-invoices/{invoice_id}", headers=headers
        )

    def issue_commission_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/api/commission-invoices/{invoice_id}/issue", headers=headers
        )

    def pay_commission_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/api/commission-invoices/{invoice_id}/pay", payload, headers
        )

    def dispute_commission_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/api/commission-invoices/{invoice_id}/dispute", payload, headers
        )

    # -- Logical clock (test-driving capability, PRD §2.5) ---------------------
    def set_current_utc(self, payload, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
