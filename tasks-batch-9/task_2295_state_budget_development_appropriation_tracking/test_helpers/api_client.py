"""API client: one method per endpoint defined in the PRD (all paths under /fiscal)."""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/fiscal"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- agencies
    def create_agency(self, payload, headers):
        return self._request("POST", f"{BASE}/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"{BASE}/agencies/{agency_id}", headers=headers)

    # ----------------------------------------------------------- budget cycles
    def create_budget_cycle(self, payload, headers):
        return self._request("POST", f"{BASE}/budget-cycles", payload, headers)

    def get_budget_cycle(self, cycle_id, headers):
        return self._request("GET", f"{BASE}/budget-cycles/{cycle_id}", headers=headers)

    def advance_cycle_phase(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/budget-cycles/{cycle_id}/advance-phase", payload, headers
        )

    def certify_cycle_balance(self, cycle_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/budget-cycles/{cycle_id}/certify-balance",
            payload if payload is not None else {},
            headers,
        )

    def close_budget_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/budget-cycles/{cycle_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------- revenue forecasts
    def create_revenue_forecast(self, payload, headers):
        return self._request("POST", f"{BASE}/revenue-forecasts", payload, headers)

    def adopt_revenue_forecast(self, forecast_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/revenue-forecasts/{forecast_id}/adopt",
            payload if payload is not None else {},
            headers,
        )

    def list_cycle_revenue_forecasts(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/budget-cycles/{cycle_id}/revenue-forecasts",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------- agency requests
    def create_agency_request(self, payload, headers):
        return self._request("POST", f"{BASE}/agency-requests", payload, headers)

    def get_agency_request(self, request_id, headers):
        return self._request(
            "GET", f"{BASE}/agency-requests/{request_id}", headers=headers
        )

    def list_agency_requests(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/agency-requests", headers=headers, params=params
        )

    def submit_agency_request(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/agency-requests/{request_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def begin_review_agency_request(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/agency-requests/{request_id}/begin-review",
            payload if payload is not None else {},
            headers,
        )

    def return_agency_request_for_revision(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/agency-requests/{request_id}/return-for-revision",
            payload,
            headers,
        )

    def accept_agency_request(self, request_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/agency-requests/{request_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------- decision packages
    def create_decision_package(self, payload, headers):
        return self._request("POST", f"{BASE}/decision-packages", payload, headers)

    def get_decision_package(self, package_id, headers):
        return self._request(
            "GET", f"{BASE}/decision-packages/{package_id}", headers=headers
        )

    def list_decision_packages(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/decision-packages", headers=headers, params=params
        )

    def recommend_decision_package(self, package_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/decision-packages/{package_id}/recommend",
            payload if payload is not None else {},
            headers,
        )

    def defer_decision_package(self, package_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/decision-packages/{package_id}/defer",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------ performance measures
    def create_performance_measure(self, payload, headers):
        return self._request("POST", f"{BASE}/performance-measures", payload, headers)

    def list_package_performance_measures(self, package_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/decision-packages/{package_id}/performance-measures",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------- executive recommendations
    def create_executive_recommendation(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/executive-recommendations", payload, headers
        )

    def approve_executive_recommendation(self, recommendation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/executive-recommendations/{recommendation_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def list_request_executive_recommendations(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/agency-requests/{request_id}/executive-recommendations",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------- reduction scenarios
    def create_reduction_scenario(self, payload, headers):
        return self._request("POST", f"{BASE}/reduction-scenarios", payload, headers)

    def list_cycle_reduction_scenarios(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/budget-cycles/{cycle_id}/reduction-scenarios",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- appropriations
    def create_appropriation(self, payload, headers):
        return self._request("POST", f"{BASE}/appropriations", payload, headers)

    def get_appropriation(self, appropriation_id, headers):
        return self._request(
            "GET", f"{BASE}/appropriations/{appropriation_id}", headers=headers
        )

    def list_appropriations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/appropriations", headers=headers, params=params
        )

    def enact_appropriation(self, appropriation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/appropriations/{appropriation_id}/enact",
            payload if payload is not None else {},
            headers,
        )

    def create_emergency_appropriation(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/appropriations/emergency", payload, headers
        )

    def freeze_appropriation_cash(self, appropriation_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/appropriations/{appropriation_id}/freeze-cash",
            payload,
            headers,
        )

    def unfreeze_appropriation_cash(self, appropriation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/appropriations/{appropriation_id}/unfreeze-cash",
            payload if payload is not None else {},
            headers,
        )

    def get_appropriation_balance_summary(self, appropriation_id, headers):
        return self._request(
            "GET",
            f"{BASE}/appropriations/{appropriation_id}/balance-summary",
            headers=headers,
        )

    # --------------------------------------------------------- committee actions
    def create_committee_action(self, payload, headers):
        return self._request("POST", f"{BASE}/committee-actions", payload, headers)

    def list_appropriation_committee_actions(self, appropriation_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/appropriations/{appropriation_id}/committee-actions",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------------- allotments
    def create_allotment(self, payload, headers):
        return self._request("POST", f"{BASE}/allotments", payload, headers)

    def get_allotment(self, allotment_id, headers):
        return self._request("GET", f"{BASE}/allotments/{allotment_id}", headers=headers)

    def list_appropriation_allotments(self, appropriation_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/appropriations/{appropriation_id}/allotments",
            headers=headers,
            params=params,
        )

    def prepare_allotment(self, allotment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/allotments/{allotment_id}/prepare",
            payload if payload is not None else {},
            headers,
        )

    def approve_allotment(self, allotment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/allotments/{allotment_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def release_allotment(self, allotment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/allotments/{allotment_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def recall_allotment(self, allotment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/allotments/{allotment_id}/recall", payload, headers
        )

    def cancel_allotment(self, allotment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/allotments/{allotment_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ----------------------------------------------------------- budget transfers
    def create_budget_transfer(self, payload, headers):
        return self._request("POST", f"{BASE}/budget-transfers", payload, headers)

    def list_appropriation_budget_transfers(self, appropriation_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/appropriations/{appropriation_id}/budget-transfers",
            headers=headers,
            params=params,
        )

    def approve_budget_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/budget-transfers/{transfer_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def reject_budget_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/budget-transfers/{transfer_id}/reject", payload, headers
        )

    def execute_budget_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/budget-transfers/{transfer_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    def reverse_budget_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/budget-transfers/{transfer_id}/reverse", payload, headers
        )

    # -------------------------------------------------------------- expenditures
    def create_expenditure(self, payload, headers):
        return self._request("POST", f"{BASE}/expenditures", payload, headers)

    def void_expenditure(self, expenditure_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/expenditures/{expenditure_id}/void", payload, headers
        )

    def list_appropriation_expenditures(self, appropriation_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/appropriations/{appropriation_id}/expenditures",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ federal grants
    def create_federal_grant(self, payload, headers):
        return self._request("POST", f"{BASE}/federal-grants", payload, headers)

    def get_federal_grant(self, grant_id, headers):
        return self._request(
            "GET", f"{BASE}/federal-grants/{grant_id}", headers=headers
        )

    def list_federal_grants(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/federal-grants", headers=headers, params=params
        )

    def assess_grant_moe(self, grant_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/federal-grants/{grant_id}/moe-assessment", payload, headers
        )

    # -------------------------------------------------------- match commitments
    def create_match_commitment(self, payload, headers):
        return self._request("POST", f"{BASE}/match-commitments", payload, headers)

    def get_match_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{BASE}/match-commitments/{commitment_id}", headers=headers
        )

    def list_match_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/match-commitments", headers=headers, params=params
        )

    # -------------------------------------------------------------- logical clock
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
