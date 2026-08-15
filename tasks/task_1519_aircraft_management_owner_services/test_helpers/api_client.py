"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Owner ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    # --- ManagementAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def patch_agreement_terms(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/agreements/{agreement_id}/terms", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/activate", None, headers)

    def give_termination_notice(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/give-termination-notice", None, headers)

    def release_records(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/release-records", payload, headers)

    def complete_termination(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/complete-termination", None, headers)

    # --- OperatingBudget ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/budgets", payload, headers)

    def list_aircraft_budgets(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/budgets", headers=headers)

    def patch_budget(self, budget_id, payload, headers):
        return self._request("PATCH", f"/budgets/{budget_id}", payload, headers)

    def submit_budget(self, budget_id, headers):
        return self._request("POST", f"/budgets/{budget_id}/submit", None, headers)

    def approve_budget(self, budget_id, headers):
        return self._request("POST", f"/budgets/{budget_id}/approve", None, headers)

    def reject_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/budgets/{budget_id}/reject", payload, headers)

    # --- Expense ---
    def create_expense(self, payload, headers):
        return self._request("POST", "/expenses", payload, headers)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expenses/{expense_id}", headers=headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/expenses", headers=headers, params=params)

    def void_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/void", None, headers)

    # --- MonthlyStatement ---
    def create_statement(self, payload, headers):
        return self._request("POST", "/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_aircraft_statements(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/statements", headers=headers)

    def certify_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/certify", None, headers)

    def deliver_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/deliver", None, headers)

    # --- CrewMember ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew", payload, headers)

    def get_crew_member(self, crew_id, headers):
        return self._request("GET", f"/crew/{crew_id}", headers=headers)

    def list_aircraft_crew(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/crew", headers=headers)

    def begin_training(self, crew_id, headers):
        return self._request("POST", f"/crew/{crew_id}/begin-training", None, headers)

    def complete_training(self, crew_id, payload, headers):
        return self._request("POST", f"/crew/{crew_id}/complete-training", payload, headers)

    def deactivate_crew(self, crew_id, headers):
        return self._request("POST", f"/crew/{crew_id}/deactivate", None, headers)

    # --- TripRequest ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_aircraft_trips(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/trips", headers=headers)

    def approve_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/approve", None, headers)

    def decline_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/decline", payload, headers)

    def resubmit_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/resubmit", payload, headers)

    def schedule_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/schedule", None, headers)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", None, headers)

    def void_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/void", None, headers)

    # --- DutyAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def delete_assignment(self, assignment_id, headers):
        return self._request("DELETE", f"/assignments/{assignment_id}", headers=headers)

    # --- MaintenanceProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_aircraft_programs(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/programs", headers=headers)

    def enroll_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/enroll", None, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend", None, headers)

    def cancel_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/cancel", None, headers)

    # --- MaintenanceEvent ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def schedule_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/schedule", payload, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", None, headers)

    # --- ComplianceFiling ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def list_aircraft_filings(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/filings", headers=headers)

    def file_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/file", payload, headers)

    def record_decision(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/record-decision", payload, headers)

    # --- VendorContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_aircraft_contracts(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}/contracts", headers=headers)

    def propose_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/propose", payload, headers)

    def counter_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/counter", payload, headers)

    def execute_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/execute", None, headers)

    def expire_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/expire", None, headers)

    # --- Test-driving: logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
