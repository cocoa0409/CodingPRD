"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/labor-relations"


class ApiClient(GenericApiClient):
    # ---------------- logical clock (PRD §2.4) ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- collective agreements ----------------
    def create_bargaining_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bargaining-units", payload, headers)

    def get_bargaining_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/bargaining-units/{unit_id}", headers=headers)

    def create_contract_clause(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bargaining-units/{unit_id}/contract-clauses", payload, headers
        )

    def list_contract_clauses(self, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/bargaining-units/{unit_id}/contract-clauses",
            headers=headers,
            params=params,
        )

    # ---------------- people ----------------
    def create_employee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"{PREFIX}/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/employees", headers=headers, params=params)

    def list_employee_witness_assignments(self, employee_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/employees/{employee_id}/witness-assignments",
            headers=headers,
            params=params,
        )

    # ---------------- grievance intake and the step ladder ----------------
    def create_grievance(self, payload, headers):
        return self._request("POST", f"{PREFIX}/grievances", payload, headers)

    def get_grievance(self, grievance_id, headers):
        return self._request("GET", f"{PREFIX}/grievances/{grievance_id}", headers=headers)

    def list_grievances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/grievances", headers=headers, params=params)

    def create_grievance_step(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/steps", payload, headers
        )

    def list_grievance_steps(self, grievance_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/grievances/{grievance_id}/steps", headers=headers, params=params
        )

    def hold_grievance_step(self, step_id, headers):
        return self._request("POST", f"{PREFIX}/grievance-steps/{step_id}/hold", {}, headers)

    def respond_grievance_step(self, step_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievance-steps/{step_id}/respond", payload, headers
        )

    def appeal_grievance(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/appeal", payload, headers
        )

    def withdraw_grievance(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/withdraw", payload, headers
        )

    # ---------------- precedent library ----------------
    def create_precedent_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/precedent-cases", payload, headers)

    def get_precedent_case(self, precedent_id, headers):
        return self._request(
            "GET", f"{PREFIX}/precedent-cases/{precedent_id}", headers=headers
        )

    def list_precedent_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/precedent-cases", headers=headers, params=params
        )

    # ---------------- settlement offers ----------------
    def create_settlement_offer(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/settlement-offers", payload, headers
        )

    def get_settlement_offer(self, offer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlement-offers/{offer_id}", headers=headers
        )

    def list_settlement_offers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/settlement-offers", headers=headers, params=params
        )

    def authorize_settlement_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-offers/{offer_id}/authorize", payload, headers
        )

    def respond_settlement_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-offers/{offer_id}/respond", payload, headers
        )

    # ---------------- arbitrators ----------------
    def create_arbitrator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/arbitrators", payload, headers)

    def get_arbitrator(self, arbitrator_id, headers):
        return self._request("GET", f"{PREFIX}/arbitrators/{arbitrator_id}", headers=headers)

    def update_arbitrator(self, arbitrator_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/arbitrators/{arbitrator_id}", payload, headers
        )

    def list_arbitrator_strike_history(self, arbitrator_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/arbitrators/{arbitrator_id}/strike-history",
            headers=headers,
            params=params,
        )

    # ---------------- arbitration demands ----------------
    def create_arbitration_demand(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/arbitration-demands", payload, headers
        )

    def get_arbitration_demand(self, demand_id, headers):
        return self._request(
            "GET", f"{PREFIX}/arbitration-demands/{demand_id}", headers=headers
        )

    def list_arbitration_demands(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/arbitration-demands", headers=headers, params=params
        )

    def request_panel(self, demand_id, headers):
        return self._request(
            "POST", f"{PREFIX}/arbitration-demands/{demand_id}/request-panel", {}, headers
        )

    def list_panel_strikes(self, demand_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/arbitration-demands/{demand_id}/panel-strikes",
            headers=headers,
            params=params,
        )

    def create_panel_strike(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/arbitration-demands/{demand_id}/strikes", payload, headers
        )

    def schedule_hearing(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/arbitration-demands/{demand_id}/schedule-hearing", payload, headers
        )

    def create_prep_filing(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/arbitration-demands/{demand_id}/prep-filings", payload, headers
        )

    # ---------------- witnesses ----------------
    def create_witness_assignment(self, demand_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/arbitration-demands/{demand_id}/witness-assignments",
            payload,
            headers,
        )

    def list_demand_witness_assignments(self, demand_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/arbitration-demands/{demand_id}/witness-assignments",
            headers=headers,
            params=params,
        )

    def confirm_witness_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/witness-assignments/{assignment_id}/confirm", {}, headers
        )

    # ---------------- awards ----------------
    def create_award(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/arbitration-demands/{demand_id}/awards", payload, headers
        )

    def list_demand_awards(self, demand_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/arbitration-demands/{demand_id}/awards",
            headers=headers,
            params=params,
        )

    def get_award(self, award_id, headers):
        return self._request("GET", f"{PREFIX}/awards/{award_id}", headers=headers)

    def implement_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/awards/{award_id}/implement", payload, headers
        )

    # ---------------- case cost ledger ----------------
    def create_cost_entry(self, grievance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/grievances/{grievance_id}/cost-entries", payload, headers
        )

    def list_cost_entries(self, grievance_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/grievances/{grievance_id}/cost-entries",
            headers=headers,
            params=params,
        )

    def void_cost_entry(self, cost_entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-entries/{cost_entry_id}/void", payload, headers
        )


api_client = ApiClient()
