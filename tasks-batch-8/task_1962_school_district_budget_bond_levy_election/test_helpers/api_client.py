"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Fiscal years ---
    def create_fiscal_year(self, payload, headers):
        return self._request("POST", "/district/fiscal-years", payload, headers)

    def list_fiscal_years(self, headers, params=None):
        return self._request("GET", "/district/fiscal-years", headers=headers,
                             params=params)

    def get_fiscal_year(self, fy_id, headers):
        return self._request("GET", f"/district/fiscal-years/{fy_id}",
                             headers=headers)

    def open_fiscal_year(self, fy_id, headers):
        return self._request("POST", f"/district/fiscal-years/{fy_id}/open",
                             {}, headers)

    def close_fiscal_year(self, fy_id, headers):
        return self._request("POST", f"/district/fiscal-years/{fy_id}/close",
                             {}, headers)

    # --- Enrollment projections ---
    def create_enrollment_projection(self, fy_id, payload, headers):
        return self._request(
            "POST", f"/district/fiscal-years/{fy_id}/enrollment-projections",
            payload, headers)

    def list_enrollment_projections(self, fy_id, headers):
        return self._request(
            "GET", f"/district/fiscal-years/{fy_id}/enrollment-projections",
            headers=headers)

    def get_enrollment_projection(self, ep_id, headers):
        return self._request("GET", f"/district/enrollment-projections/{ep_id}",
                             headers=headers)

    def certify_enrollment_projection(self, ep_id, payload, headers):
        return self._request(
            "POST", f"/district/enrollment-projections/{ep_id}/certify",
            payload, headers)

    # --- Budget versions ---
    def create_budget_version(self, fy_id, payload, headers):
        return self._request(
            "POST", f"/district/fiscal-years/{fy_id}/budget-versions",
            payload, headers)

    def list_budget_versions(self, fy_id, headers, params=None):
        return self._request(
            "GET", f"/district/fiscal-years/{fy_id}/budget-versions",
            headers=headers, params=params)

    def get_budget_version(self, bv_id, headers):
        return self._request("GET", f"/district/budget-versions/{bv_id}",
                             headers=headers)

    def propose_budget_version(self, bv_id, headers):
        return self._request("POST", f"/district/budget-versions/{bv_id}/propose",
                             {}, headers)

    def return_budget_version_to_draft(self, bv_id, headers):
        return self._request(
            "POST", f"/district/budget-versions/{bv_id}/return-to-draft",
            {}, headers)

    def adopt_budget_version(self, bv_id, headers):
        return self._request("POST", f"/district/budget-versions/{bv_id}/adopt",
                             {}, headers)

    # --- Budget lines and transfers ---
    def create_budget_line(self, bv_id, payload, headers):
        return self._request(
            "POST", f"/district/budget-versions/{bv_id}/budget-lines",
            payload, headers)

    def list_budget_lines(self, bv_id, headers):
        return self._request(
            "GET", f"/district/budget-versions/{bv_id}/budget-lines",
            headers=headers)

    def create_transfer(self, bv_id, payload, headers):
        return self._request("POST", f"/district/budget-versions/{bv_id}/transfers",
                             payload, headers)

    # --- Staffing allocations ---
    def create_staffing_allocation(self, bv_id, payload, headers):
        return self._request(
            "POST", f"/district/budget-versions/{bv_id}/staffing-allocations",
            payload, headers)

    def list_staffing_allocations(self, bv_id, headers):
        return self._request(
            "GET", f"/district/budget-versions/{bv_id}/staffing-allocations",
            headers=headers)

    def list_allocations_for_projection(self, ep_id, headers):
        return self._request(
            "GET",
            f"/district/enrollment-projections/{ep_id}/staffing-allocations",
            headers=headers)

    def get_staffing_allocation(self, sa_id, headers):
        return self._request("GET", f"/district/staffing-allocations/{sa_id}",
                             headers=headers)

    # --- Positions ---
    def create_position(self, sa_id, payload, headers):
        return self._request(
            "POST", f"/district/staffing-allocations/{sa_id}/positions",
            payload, headers)

    def list_positions(self, sa_id, headers):
        return self._request(
            "GET", f"/district/staffing-allocations/{sa_id}/positions",
            headers=headers)

    def fill_position(self, p_id, payload, headers):
        return self._request("POST", f"/district/positions/{p_id}/fill",
                             payload, headers)

    def vacate_position(self, p_id, headers):
        return self._request("POST", f"/district/positions/{p_id}/vacate",
                             {}, headers)

    def eliminate_position(self, p_id, headers):
        return self._request("POST", f"/district/positions/{p_id}/eliminate",
                             {}, headers)

    # --- Revenue estimates ---
    def create_revenue_estimate(self, bv_id, payload, headers):
        return self._request(
            "POST", f"/district/budget-versions/{bv_id}/revenue-estimates",
            payload, headers)

    def list_revenue_estimates(self, bv_id, headers):
        return self._request(
            "GET", f"/district/budget-versions/{bv_id}/revenue-estimates",
            headers=headers)

    def recertify_revenue_estimate(self, re_id, headers):
        return self._request(
            "POST", f"/district/revenue-estimates/{re_id}/recertify",
            {}, headers)

    # --- Public hearings ---
    def create_hearing(self, bv_id, payload, headers):
        return self._request("POST", f"/district/budget-versions/{bv_id}/hearings",
                             payload, headers)

    def list_hearings(self, bv_id, headers):
        return self._request("GET", f"/district/budget-versions/{bv_id}/hearings",
                             headers=headers)

    def hold_hearing(self, h_id, headers):
        return self._request("POST", f"/district/public-hearings/{h_id}/hold",
                             {}, headers)

    def cancel_hearing(self, h_id, headers):
        return self._request("POST", f"/district/public-hearings/{h_id}/cancel",
                             {}, headers)

    # --- Elections ---
    def create_election(self, payload, headers):
        return self._request("POST", "/district/elections", payload, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/district/elections", headers=headers,
                             params=params)

    def get_election(self, e_id, headers):
        return self._request("GET", f"/district/elections/{e_id}", headers=headers)

    def canvass_election(self, e_id, payload, headers):
        return self._request("POST", f"/district/elections/{e_id}/canvass",
                             payload, headers)

    # --- Bond proposals ---
    def create_bond_proposal(self, fy_id, payload, headers):
        return self._request("POST", f"/district/fiscal-years/{fy_id}/bond-proposals",
                             payload, headers)

    def list_bond_proposals(self, fy_id, headers):
        return self._request("GET", f"/district/fiscal-years/{fy_id}/bond-proposals",
                             headers=headers)

    def get_bond_proposal(self, bp_id, headers):
        return self._request("GET", f"/district/bond-proposals/{bp_id}",
                             headers=headers)

    def approve_bond_proposal_board(self, bp_id, headers):
        return self._request(
            "POST", f"/district/bond-proposals/{bp_id}/approve-board", {}, headers)

    def revise_bond_proposal(self, bp_id, headers):
        return self._request("POST", f"/district/bond-proposals/{bp_id}/revise",
                             {}, headers)

    # --- Bond projects ---
    def create_bond_project(self, bp_id, payload, headers):
        return self._request("POST", f"/district/bond-proposals/{bp_id}/projects",
                             payload, headers)

    def list_bond_projects(self, bp_id, headers):
        return self._request("GET", f"/district/bond-proposals/{bp_id}/projects",
                             headers=headers)

    def get_bond_project(self, prj_id, headers):
        return self._request("GET", f"/district/bond-projects/{prj_id}",
                             headers=headers)

    def activate_bond_project(self, prj_id, headers):
        return self._request("POST", f"/district/bond-projects/{prj_id}/activate",
                             {}, headers)

    def complete_bond_project(self, prj_id, headers):
        return self._request("POST", f"/district/bond-projects/{prj_id}/complete",
                             {}, headers)

    def cancel_bond_project(self, prj_id, headers):
        return self._request("POST", f"/district/bond-projects/{prj_id}/cancel",
                             {}, headers)

    # --- Ballot measures and publications ---
    def create_ballot_measure(self, el_id, payload, headers):
        return self._request("POST", f"/district/elections/{el_id}/ballot-measures",
                             payload, headers)

    def list_ballot_measures(self, el_id, headers):
        return self._request("GET", f"/district/elections/{el_id}/ballot-measures",
                             headers=headers)

    def list_ballot_measures_for_proposal(self, bp_id, headers):
        return self._request(
            "GET", f"/district/bond-proposals/{bp_id}/ballot-measures",
            headers=headers)

    def get_ballot_measure(self, bm_id, headers):
        return self._request("GET", f"/district/ballot-measures/{bm_id}",
                             headers=headers)

    def certify_ballot_measure(self, bm_id, headers):
        return self._request("POST", f"/district/ballot-measures/{bm_id}/certify",
                             {}, headers)

    def create_publication(self, bm_id, payload, headers):
        return self._request(
            "POST", f"/district/ballot-measures/{bm_id}/publications",
            payload, headers)

    def list_publications(self, bm_id, headers):
        return self._request(
            "GET", f"/district/ballot-measures/{bm_id}/publications",
            headers=headers)

    # --- Bond sales ---
    def create_bond_sale(self, bp_id, payload, headers):
        return self._request("POST", f"/district/bond-proposals/{bp_id}/bond-sales",
                             payload, headers)

    def list_bond_sales(self, bp_id, headers):
        return self._request("GET", f"/district/bond-proposals/{bp_id}/bond-sales",
                             headers=headers)

    def close_bond_sale(self, bs_id, headers):
        return self._request("POST", f"/district/bond-sales/{bs_id}/close",
                             {}, headers)

    def cancel_bond_sale(self, bs_id, headers):
        return self._request("POST", f"/district/bond-sales/{bs_id}/cancel",
                             {}, headers)

    # --- Project expenditures ---
    def create_expenditure(self, prj_id, payload, headers):
        return self._request("POST", f"/district/bond-projects/{prj_id}/expenditures",
                             payload, headers)

    def list_expenditures(self, prj_id, headers):
        return self._request("GET", f"/district/bond-projects/{prj_id}/expenditures",
                             headers=headers)

    def review_expenditure(self, pe_id, payload, headers):
        return self._request(
            "POST", f"/district/project-expenditures/{pe_id}/review",
            payload, headers)

    def disburse_expenditure(self, pe_id, headers):
        return self._request(
            "POST", f"/district/project-expenditures/{pe_id}/disburse",
            {}, headers)

    def void_expenditure(self, pe_id, headers):
        return self._request("POST", f"/district/project-expenditures/{pe_id}/void",
                             {}, headers)

    # --- Capital-plan amendments ---
    def create_amendment(self, bp_id, payload, headers):
        return self._request("POST", f"/district/bond-proposals/{bp_id}/amendments",
                             payload, headers)

    def list_amendments(self, bp_id, headers):
        return self._request("GET", f"/district/bond-proposals/{bp_id}/amendments",
                             headers=headers)

    def submit_amendment(self, ca_id, headers):
        return self._request(
            "POST", f"/district/capital-plan-amendments/{ca_id}/submit",
            {}, headers)

    def approve_amendment(self, ca_id, headers):
        return self._request(
            "POST", f"/district/capital-plan-amendments/{ca_id}/approve",
            {}, headers)

    def reject_amendment(self, ca_id, headers):
        return self._request(
            "POST", f"/district/capital-plan-amendments/{ca_id}/reject",
            {}, headers)

    def revise_amendment(self, ca_id, headers):
        return self._request(
            "POST", f"/district/capital-plan-amendments/{ca_id}/revise",
            {}, headers)


api_client = ApiClient()
